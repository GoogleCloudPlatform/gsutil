# Copyright 2014 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""JSON gsutil Cloud API implementation for Google Cloud Storage."""

import json
import os
import pkgutil
import tempfile

import boto
from boto import config
import httplib2
from oauth2_plugin import oauth2_helper
from oauth2client import multistore_file

import gslib
from gslib.cloud_api import AccessDeniedException
from gslib.cloud_api import ArgumentException
from gslib.cloud_api import BadRequestException
from gslib.cloud_api import CloudApi
from gslib.cloud_api import NotEmptyException
from gslib.cloud_api import NotFoundException
from gslib.cloud_api import PreconditionException
from gslib.cloud_api import Preconditions
from gslib.cloud_api import ResumableUploadAbortException
from gslib.cloud_api import ResumableUploadException
from gslib.cloud_api import ServiceException
from gslib.cloud_api_helper import ValidateDstObjectMetadata
from gslib.cred_types import CredTypes
from gslib.exception import CommandException
from gslib.gcs_json_media import BytesUploadedContainer
from gslib.gcs_json_media import DownloadCallbackConnectionClassFactory
from gslib.gcs_json_media import UploadCallbackConnectionClassFactory
from gslib.gcs_json_media import WrapDownloadHttpRequest
from gslib.gcs_json_media import WrapUploadHttpRequest
from gslib.no_op_credentials import NoOpCredentials
from gslib.project_id import PopulateProjectId
from gslib.third_party.storage_apitools import credentials_lib as credentials_lib
from gslib.third_party.storage_apitools import encoding as encoding
from gslib.third_party.storage_apitools import exceptions as apitools_exceptions
from gslib.third_party.storage_apitools import storage_v1_client as apitools_client
from gslib.third_party.storage_apitools import storage_v1_messages as apitools_messages
from gslib.third_party.storage_apitools import transfer as apitools_transfer
from gslib.translation_helper import CreateBucketNotFoundException
from gslib.translation_helper import CreateObjectNotFoundException
from gslib.translation_helper import DEFAULT_CONTENT_TYPE
from gslib.translation_helper import REMOVE_CORS_CONFIG
from gslib.util import CALLBACK_PER_X_BYTES
from gslib.util import GetCredentialStoreFilename


# Implementation supports only 'gs' URLs, so provider is unused.
# pylint: disable=unused-argument

DEFAULT_GCS_JSON_VERSION = 'v1'

NUM_BUCKETS_PER_LIST_PAGE = 100
NUM_OBJECTS_PER_LIST_PAGE = 500


# Resumable downloads and uploads make one HTTP call per chunk (and must be
# in multiples of 256KB). Overridable for testing.
def _ResumableChunkSize():
  chunk_size = config.getint('GSUtil', 'json_resumable_chunk_size',
                             1024*1024*100L)
  if chunk_size == 0:
    chunk_size = 1024*256L
  elif chunk_size % 1024*256L != 0:
    chunk_size += (1024*256L - (chunk_size % 1024*256L))
  return chunk_size

TRANSLATABLE_APITOOLS_EXCEPTIONS = (apitools_exceptions.HttpError,
                                    apitools_exceptions.TransferError,
                                    apitools_exceptions.TransferInvalidError)


class GcsJsonApi(CloudApi):
  """Google Cloud Storage JSON implementation of gsutil Cloud API."""

  def __init__(self, bucket_storage_uri_class, logger, provider=None,
               credentials=None, debug=0):
    """Performs necessary setup for interacting with Google Cloud Storage.

    Args:
      bucket_storage_uri_class: Unused.
      logger: logging.logger for outputting log messages.
      provider: Unused.  This implementation supports only Google Cloud Storage.
      credentials: Credentials to be used for interacting with Google Cloud
                   Storage.
      debug: Debug level for the API implementation (0..3).
    """
    # TODO: Plumb host_header for perfdiag / test_perfdiag.
    # TODO: Add jitter to apitools' http_wrapper retry mechanism.
    super(GcsJsonApi, self).__init__(bucket_storage_uri_class, logger,
                                     provider='gs', debug=debug)
    no_op_credentials = False
    if not credentials:
      loaded_credentials = self._CheckAndGetCredentials(logger)

      if not loaded_credentials:
        loaded_credentials = NoOpCredentials()
        no_op_credentials = True
    else:
      if isinstance(credentials, NoOpCredentials):
        no_op_credentials = True

    self.credentials = credentials or loaded_credentials

    self.certs_file = self._GetCertsFile()

    self.http = self._GetNewHttp()

    self.http.disable_ssl_certificate_validation = (not config.getbool(
        'Boto', 'https_validate_certificates'))

    self.http_base = 'https://'
    gs_json_host = config.get('Credentials', 'gs_json_host', None)
    self.host_base = gs_json_host or 'www.googleapis.com'

    if not gs_json_host:
      gs_host = config.get('Credentials', 'gs_host', None)
      if gs_host:
        raise ArgumentException(
            'JSON API is selected but gs_json_host is not configured, '
            'while gs_host is configured to %s. Please also configure '
            'gs_json_host and gs_json_port to match your desired endpoint.'
            % gs_host)

    gs_json_port = config.get('Credentials', 'gs_json_port', None)

    if not gs_json_port:
      gs_port = config.get('Credentials', 'gs_port', None)
      if gs_port:
        raise ArgumentException(
            'JSON API is selected but gs_json_port is not configured, '
            'while gs_port is configured to %s. Please also configure '
            'gs_json_host and gs_json_port to match your desired endpoint.'
            % gs_port)
      self.host_port = ''
    else:
      self.host_port = ':' + config.get('Credentials', 'gs_json_port')

    self.api_version = config.get('GSUtil', 'json_api_version',
                                  DEFAULT_GCS_JSON_VERSION)
    self.url_base = (self.http_base + self.host_base + self.host_port + '/' +
                     'storage/' + self.api_version + '/')

    self.credentials.set_store(
        multistore_file.get_credential_storage_custom_string_key(
            GetCredentialStoreFilename(), self.api_version))

    log_request = (debug >= 3)
    log_response = (debug >= 3)

    self.api_client = apitools_client.StorageV1(
        url=self.url_base, http=self.http, log_request=log_request,
        log_response=log_response, credentials=self.credentials,
        version=self.api_version)

    if no_op_credentials:
      # This API key is not secret and is used to identify gsutil during
      # anonymous requests.
      self.api_client.AddGlobalParam('key',
                                     u'AIzaSyDnacJHrKma0048b13sh8cgxNUwulubmJM')

  def _CheckAndGetCredentials(self, logger):
    configured_cred_types = []
    try:
      if self._HasOauth2UserAccountCreds():
        configured_cred_types.append(CredTypes.OAUTH2_USER_ACCOUNT)
      if self._HasOauth2ServiceAccountCreds():
        configured_cred_types.append(CredTypes.OAUTH2_SERVICE_ACCOUNT)
      if self._HasGceCreds():
        configured_cred_types.append(CredTypes.GCE)
      if len(configured_cred_types) > 1:
        # We only allow one set of configured credentials. Otherwise, we're
        # choosing one arbitrarily, which can be very confusing to the user
        # (e.g., if only one is authorized to perform some action) and can
        # also mask errors.
        failed_cred_type = None
        raise CommandException(
            ('You have multiple types of configured credentials (%s), which is '
             'not supported. For more help, see "gsutil help creds".')
            % configured_cred_types)

      failed_cred_type = CredTypes.OAUTH2_USER_ACCOUNT
      user_creds = self._GetOauth2UserAccountCreds()
      failed_cred_type = CredTypes.OAUTH2_SERVICE_ACCOUNT
      service_account_creds = self._GetOauth2ServiceAccountCreds()
      failed_cred_type = CredTypes.GCE
      gce_creds = self._GetGceCreds()
      return user_creds or service_account_creds or gce_creds
    except:  # pylint: disable=bare-except

      # If we didn't actually try to authenticate because there were multiple
      # types of configured credentials, don't emit this warning.
      if failed_cred_type:
        logger.warn(('Your "%s" credentials are invalid. For more help, see '
                     '"gsutil help creds", or re-run the gsutil config command '
                     '(see "gsutil help config").') % failed_cred_type)

      # If there's any set of configured credentials, we'll fail if they're
      # invalid, rather than silently falling back to anonymous config (as
      # boto does). That approach leads to much confusion if users don't
      # realize their credentials are invalid.
      raise

  def _HasOauth2ServiceAccountCreds(self):
    return (config.has_option('Credentials', 'gs_service_client_id') and
            config.has_option('Credentials', 'gs_service_key_file'))

  def _HasOauth2UserAccountCreds(self):
    return config.has_option('Credentials', 'gs_oauth2_refresh_token')

  def _HasGceCreds(self):
    return config.has_option('GoogleCompute', 'service_account')

  def _GetOauth2ServiceAccountCreds(self):
    if self._HasOauth2ServiceAccountCreds():
      return oauth2_helper.OAuth2ClientFromBotoConfig(
          boto.config,
          cred_type=CredTypes.OAUTH2_SERVICE_ACCOUNT).GetCredentials()

  def _GetOauth2UserAccountCreds(self):
    if self._HasOauth2UserAccountCreds():
      return oauth2_helper.OAuth2ClientFromBotoConfig(
          boto.config).GetCredentials()

  def _GetGceCreds(self):
    if self._HasGceCreds():
      return credentials_lib.GceAssertionCredentials()

  # Some installers don't package a certs file with httplib2, so use the
  # one included with gsutil.
  def _GetNewHttp(self):
    if self.certs_file:
      return httplib2.Http(ca_certs=self.certs_file)
    else:
      return httplib2.Http()

  def _GetCertsFile(self):
    # TODO: This code is shared with main, merge the implementations.
    certs_file = boto.config.get('Boto', 'ca_certificates_file', None)
    if not certs_file:
      disk_certs_file = os.path.abspath(
          os.path.join(gslib.GSLIB_DIR, 'data', 'cacerts.txt'))
      if not os.path.exists(disk_certs_file):
        certs_data = pkgutil.get_data('gslib', 'data/cacerts.txt')
        if not certs_data:
          raise CommandException('Certificates file not found. Please '
                                 'reinstall gsutil from scratch')
        fd, fname = tempfile.mkstemp(suffix='.txt', prefix='gsutil-cacerts')
        f = os.fdopen(fd, 'w')
        f.write(certs_data)
        f.close()
        disk_certs_file = fname
      certs_file = disk_certs_file
    return certs_file

  def GetBucket(self, bucket_name, provider=None, fields=None):
    """See CloudApi class for function doc strings."""
    projection = (apitools_messages.StorageBucketsGetRequest
                  .ProjectionValueValuesEnum.full)
    apitools_request = apitools_messages.StorageBucketsGetRequest(
        bucket=bucket_name, projection=projection)
    global_params = apitools_messages.StandardQueryParameters()
    if fields:
      global_params.fields = ','.join(set(fields))

    # Here and in list buckets, we have no way of knowing
    # whether we requested a field and didn't get it because it didn't exist
    # or because we didn't have permission to access it.
    try:
      return self.api_client.buckets.Get(apitools_request,
                                         global_params=global_params)
    except TRANSLATABLE_APITOOLS_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, bucket_name=bucket_name)

  def PatchBucket(self, bucket_name, metadata, preconditions=None,
                  provider=None, fields=None):
    """See CloudApi class for function doc strings."""
    projection = (apitools_messages.StorageBucketsPatchRequest
                  .ProjectionValueValuesEnum.full)
    bucket_metadata = metadata

    if not preconditions:
      preconditions = Preconditions()

    # For blank metadata objects, we need to explicitly call
    # them out to apitools so it will send/erase them.
    apitools_include_fields = []
    for metadata_field in ('metadata', 'lifecycle', 'logging', 'versioning',
                           'website'):
      attr = getattr(bucket_metadata, metadata_field, None)
      if attr and not encoding.MessageToDict(attr):
        setattr(bucket_metadata, metadata_field, None)
        apitools_include_fields.append(metadata_field)

    if bucket_metadata.cors and bucket_metadata.cors == REMOVE_CORS_CONFIG:
      bucket_metadata.cors = []
      apitools_include_fields.append('cors')

    apitools_request = apitools_messages.StorageBucketsPatchRequest(
        bucket=bucket_name, bucketResource=bucket_metadata,
        projection=projection,
        ifMetagenerationMatch=preconditions.meta_gen_match)
    global_params = apitools_messages.StandardQueryParameters()
    if fields:
      global_params.fields = ','.join(set(fields))
    with self.api_client.IncludeFields(apitools_include_fields):
      try:
        return self.api_client.buckets.Patch(apitools_request,
                                             global_params=global_params)
      except TRANSLATABLE_APITOOLS_EXCEPTIONS, e:
        self._TranslateExceptionAndRaise(e)

  def CreateBucket(self, bucket_name, project_id=None, metadata=None,
                   provider=None, fields=None):
    """See CloudApi class for function doc strings."""
    projection = (apitools_messages.StorageBucketsInsertRequest
                  .ProjectionValueValuesEnum.full)
    if not metadata:
      metadata = apitools_messages.Bucket()
    metadata.name = bucket_name

    if metadata.location:
      metadata.location = metadata.location.upper()
    if metadata.storageClass:
      metadata.storageClass = metadata.storageClass.upper()

    project_id = PopulateProjectId(project_id)

    apitools_request = apitools_messages.StorageBucketsInsertRequest(
        bucket=metadata, project=project_id, projection=projection)
    global_params = apitools_messages.StandardQueryParameters()
    if fields:
      global_params.fields = ','.join(set(fields))
    try:
      return self.api_client.buckets.Insert(apitools_request,
                                            global_params=global_params)
    except TRANSLATABLE_APITOOLS_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, bucket_name=bucket_name)

  def DeleteBucket(self, bucket_name, preconditions=None, provider=None):
    """See CloudApi class for function doc strings."""
    if not preconditions:
      preconditions = Preconditions()

    apitools_request = apitools_messages.StorageBucketsDeleteRequest(
        bucket=bucket_name, ifMetagenerationMatch=preconditions.meta_gen_match)

    try:
      self.api_client.buckets.Delete(apitools_request)
    except TRANSLATABLE_APITOOLS_EXCEPTIONS, e:
      if isinstance(
          self._TranslateApitoolsException(e, bucket_name=bucket_name),
          NotEmptyException):
        # If bucket is not empty, check to see if versioning is enabled and
        # signal that in the exception if it is.
        bucket_metadata = self.GetBucket(bucket_name,
                                         fields=['versioning'])
        if bucket_metadata.versioning and bucket_metadata.versioning.enabled:
          raise NotEmptyException('VersionedBucketNotEmpty',
                                  status=e.status_code)
      self._TranslateExceptionAndRaise(e, bucket_name=bucket_name)

  def ListBuckets(self, project_id=None, provider=None, fields=None):
    """See CloudApi class for function doc strings."""
    projection = (apitools_messages.StorageBucketsListRequest
                  .ProjectionValueValuesEnum.full)
    project_id = PopulateProjectId(project_id)

    apitools_request = apitools_messages.StorageBucketsListRequest(
        project=project_id, maxResults=NUM_BUCKETS_PER_LIST_PAGE,
        projection=projection)
    global_params = apitools_messages.StandardQueryParameters()
    if fields:
      if 'nextPageToken' not in fields:
        fields.add('nextPageToken')
      global_params.fields = ','.join(set(fields))
    try:
      bucket_list = self.api_client.buckets.List(apitools_request,
                                                 global_params=global_params)
    except TRANSLATABLE_APITOOLS_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e)

    for bucket in self._YieldBuckets(bucket_list):
      yield bucket

    while bucket_list.nextPageToken:
      apitools_request = apitools_messages.StorageBucketsListRequest(
          project=project_id, pageToken=bucket_list.nextPageToken,
          maxResults=NUM_BUCKETS_PER_LIST_PAGE, projection=projection)
      try:
        bucket_list = self.api_client.buckets.List(apitools_request,
                                                   global_params=global_params)
      except TRANSLATABLE_APITOOLS_EXCEPTIONS, e:
        self._TranslateExceptionAndRaise(e)

      for bucket in self._YieldBuckets(bucket_list):
        yield bucket

  def _YieldBuckets(self, bucket_list):
    """Yields buckets from a list returned by apitools."""
    if bucket_list.items:
      for bucket in bucket_list.items:
        yield bucket

  def ListObjects(self, bucket_name, prefix=None, delimiter=None,
                  all_versions=None, provider=None, fields=None):
    """See CloudApi class for function doc strings."""
    projection = (apitools_messages.StorageObjectsListRequest
                  .ProjectionValueValuesEnum.full)
    apitools_request = apitools_messages.StorageObjectsListRequest(
        bucket=bucket_name, prefix=prefix, delimiter=delimiter,
        versions=all_versions, projection=projection,
        maxResults=NUM_OBJECTS_PER_LIST_PAGE)
    global_params = apitools_messages.StandardQueryParameters()

    if fields:
      if 'nextPageToken' not in fields:
        fields.add('nextPageToken')
      global_params.fields = ','.join(set(fields))

    try:
      object_list = self.api_client.objects.List(apitools_request,
                                                 global_params=global_params)
    except TRANSLATABLE_APITOOLS_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, bucket_name=bucket_name)

    for object_or_prefix in self._YieldObjectsAndPrefixes(object_list):
      yield object_or_prefix

    while object_list.nextPageToken:
      apitools_request = apitools_messages.StorageObjectsListRequest(
          bucket=bucket_name, prefix=prefix, delimiter=delimiter,
          versions=all_versions, projection=projection,
          pageToken=object_list.nextPageToken,
          maxResults=NUM_OBJECTS_PER_LIST_PAGE)
      try:
        object_list = self.api_client.objects.List(apitools_request,
                                                   global_params=global_params)
      except TRANSLATABLE_APITOOLS_EXCEPTIONS, e:
        self._TranslateExceptionAndRaise(e, bucket_name=bucket_name)

      for object_or_prefix in self._YieldObjectsAndPrefixes(object_list):
        yield object_or_prefix

  def _YieldObjectsAndPrefixes(self, object_list):
    if object_list.items:
      for cloud_obj in object_list.items:
        yield CloudApi.CsObjectOrPrefix(cloud_obj,
                                        CloudApi.CsObjectOrPrefixType.OBJECT)
    if object_list.prefixes:
      for prefix in object_list.prefixes:
        yield CloudApi.CsObjectOrPrefix(prefix,
                                        CloudApi.CsObjectOrPrefixType.PREFIX)

  def GetObjectMetadata(self, bucket_name, object_name, generation=None,
                        provider=None, fields=None):
    """See CloudApi class for function doc strings."""
    projection = (apitools_messages.StorageObjectsGetRequest
                  .ProjectionValueValuesEnum.full)

    if generation:
      generation = long(generation)

    apitools_request = apitools_messages.StorageObjectsGetRequest(
        bucket=bucket_name, object=object_name, projection=projection,
        generation=generation)
    global_params = apitools_messages.StandardQueryParameters()
    if fields:
      global_params.fields = ','.join(set(fields))

    try:
      return self.api_client.objects.Get(apitools_request,
                                         global_params=global_params)
    except TRANSLATABLE_APITOOLS_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, bucket_name=bucket_name,
                                       object_name=object_name,
                                       generation=generation)

  def GetObjectMedia(
      self, bucket_name, object_name, download_stream,
      provider=None, generation=None,
      download_strategy=CloudApi.DownloadStrategy.ONE_SHOT, start_byte=0,
      end_byte=None, progress_callback=None, serialization_data=None,
      digesters=None):
    """See CloudApi class for function doc strings."""
    # This implementation will get the object metadata first if we don't pass it
    # in via serialization_data.
    if generation:
      generation = long(generation)

    outer_total_size = None
    callback_per_bytes = 0
    if serialization_data:
      outer_total_size = json.loads(serialization_data)['total_size']

    if progress_callback:
      if outer_total_size is None:
        raise ArgumentException('Download size is required when callbacks are '
                                'requested for a download, but no size was '
                                'provided.')
      callback_per_bytes = CALLBACK_PER_X_BYTES
      progress_callback(0, outer_total_size)

    callback_class_factory = DownloadCallbackConnectionClassFactory(
        total_size=outer_total_size, callback_per_bytes=callback_per_bytes,
        progress_callback=progress_callback, digesters=digesters)
    download_http_class = callback_class_factory.GetConnectionClass()

    download_http = self._GetNewHttp()
    download_http.connections = {'https': download_http_class}
    authorized_download_http = self.credentials.authorize(download_http)

    WrapDownloadHttpRequest(authorized_download_http)

    if serialization_data:
      apitools_download = apitools_transfer.Download.FromData(
          download_stream, serialization_data, self.api_client.http)
      apitools_download.chunksize = _ResumableChunkSize()
    else:
      apitools_download = apitools_transfer.Download(
          download_stream, chunksize=_ResumableChunkSize(), auto_transfer=False)

    apitools_download.bytes_http = authorized_download_http
    apitools_request = apitools_messages.StorageObjectsGetRequest(
        bucket=bucket_name, object=object_name, generation=generation)

    if not serialization_data:
      try:
        self.api_client.objects.Get(apitools_request,
                                    download=apitools_download)
      except TRANSLATABLE_APITOOLS_EXCEPTIONS, e:
        self._TranslateExceptionAndRaise(e, bucket_name=bucket_name,
                                         object_name=object_name,
                                         generation=generation)

    # Disable apitools' default print callbacks.
    def _NoopCallback(unused_response, unused_download_object):
      pass

    # TODO: If we have a resumable download with accept-encoding:gzip
    # on a object that is compressible but not in gzip form in the cloud,
    # on-the-fly compression will gzip the object.  In this case if our
    # download breaks, future requests will ignore the range header and just
    # return the object (gzipped) in its entirety.  Ideally, we would unzip
    # the bytes that we have locally and send a range request without
    # accept-encoding:gzip so that we can download only the (uncompressed) bytes
    # that we don't yet have.

    # Since bytes_http is created in this function, we don't get the
    # user-agent header from api_client's http automatically.
    additional_headers = {
        'accept-encoding': 'gzip',
        'user-agent': self.api_client.user_agent
    }
    try:
      if start_byte or end_byte:
        apitools_download.GetRange(additional_headers=additional_headers,
                                   start=start_byte, end=end_byte)
      else:
        apitools_download.StreamInChunks(
            callback=_NoopCallback, finish_callback=_NoopCallback,
            additional_headers=additional_headers)
    except TRANSLATABLE_APITOOLS_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, bucket_name=bucket_name,
                                       object_name=object_name,
                                       generation=generation)
    except apitools_exceptions.TransferInvalidError, _:
      raise ServiceException(
          'Transfer invalid (possible encoding error)')

  def PatchObjectMetadata(self, bucket_name, object_name, metadata,
                          generation=None, preconditions=None, provider=None,
                          fields=None):
    """See CloudApi class for function doc strings."""
    projection = (apitools_messages.StorageObjectsPatchRequest
                  .ProjectionValueValuesEnum.full)

    if not preconditions:
      preconditions = Preconditions()

    if generation:
      generation = long(generation)

    apitools_request = apitools_messages.StorageObjectsPatchRequest(
        bucket=bucket_name, object=object_name, objectResource=metadata,
        generation=generation, projection=projection,
        ifGenerationMatch=preconditions.gen_match,
        ifMetagenerationMatch=preconditions.meta_gen_match)
    global_params = apitools_messages.StandardQueryParameters()
    if fields:
      global_params.fields = ','.join(set(fields))

    try:
      return self.api_client.objects.Patch(apitools_request,
                                           global_params=global_params)
    except TRANSLATABLE_APITOOLS_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, bucket_name=bucket_name,
                                       object_name=object_name,
                                       generation=generation)

  def _UploadObject(self, upload_stream, object_metadata, canned_acl=None,
                    size=None, preconditions=None, provider=None, fields=None,
                    serialization_data=None, tracker_callback=None,
                    progress_callback=None, apitools_strategy='simple'):
    """Upload implementation, apitools_strategy plus gsutil Cloud API args."""
    ValidateDstObjectMetadata(object_metadata)
    assert not canned_acl, 'Canned ACLs not supported by JSON API.'

    bytes_uploaded_container = BytesUploadedContainer()

    callback_per_bytes = 0
    total_size = 0
    if progress_callback and size:
      callback_per_bytes = CALLBACK_PER_X_BYTES
      total_size = size
      progress_callback(0, size)

    callback_class_factory = UploadCallbackConnectionClassFactory(
        bytes_uploaded_container, total_size=total_size,
        callback_per_bytes=callback_per_bytes,
        progress_callback=progress_callback)

    upload_http = self._GetNewHttp()
    upload_http_class = callback_class_factory.GetConnectionClass()
    upload_http.connections = {'http': upload_http_class,
                               'https': upload_http_class}

    # Disable apitools' default print callbacks.
    def _NoopCallback(unused_response, unused_upload_object):
      pass

    authorized_upload_http = self.credentials.authorize(upload_http)
    WrapUploadHttpRequest(authorized_upload_http)
    # Since bytes_http is created in this function, we don't get the
    # user-agent header from api_client's http automatically.
    additional_headers = {
        'user-agent': self.api_client.user_agent
    }

    try:
      if not serialization_data:
        # This is a new upload, set up initial upload state.
        content_type = object_metadata.contentType
        if not content_type:
          content_type = DEFAULT_CONTENT_TYPE

        if not preconditions:
          preconditions = Preconditions()

        apitools_request = apitools_messages.StorageObjectsInsertRequest(
            bucket=object_metadata.bucket, object=object_metadata,
            ifGenerationMatch=preconditions.gen_match,
            ifMetagenerationMatch=preconditions.meta_gen_match)

        global_params = apitools_messages.StandardQueryParameters()
        if fields:
          global_params.fields = ','.join(set(fields))

      if apitools_strategy == 'simple':  # One-shot upload.
        apitools_upload = apitools_transfer.Upload(
            upload_stream, content_type, total_size=size, auto_transfer=True)
        apitools_upload.strategy = apitools_strategy
        apitools_upload.bytes_http = authorized_upload_http

        return self.api_client.objects.Insert(
            apitools_request,
            upload=apitools_upload,
            global_params=global_params)
      else:  # Resumable upload.
        try:
          if serialization_data:
            # Resuming an existing upload.
            apitools_upload = apitools_transfer.Upload.FromData(
                upload_stream, serialization_data, self.api_client.http)
            apitools_upload.chunksize = _ResumableChunkSize()
            apitools_upload.bytes_http = authorized_upload_http
          else:
            # New resumable upload.
            apitools_upload = apitools_transfer.Upload(
                upload_stream, content_type, total_size=size,
                chunksize=_ResumableChunkSize(), auto_transfer=False)
            apitools_upload.strategy = apitools_strategy
            apitools_upload.bytes_http = authorized_upload_http
            self.api_client.objects.Insert(
                apitools_request,
                upload=apitools_upload,
                global_params=global_params)

          # If we're resuming an upload, apitools has at this point received
          # from the server how many bytes it already has. Update our
          # callback class with this information.
          bytes_uploaded_container.bytes_uploaded = apitools_upload.progress
          if tracker_callback:
            tracker_callback(json.dumps(apitools_upload.serialization_data))

          http_response = apitools_upload.StreamInChunks(
              callback=_NoopCallback, finish_callback=_NoopCallback,
              additional_headers=additional_headers)
          return self.api_client.objects.ProcessHttpResponse(
              self.api_client.objects.GetMethodConfig('Insert'), http_response)
        except TRANSLATABLE_APITOOLS_EXCEPTIONS, e:
          resumable_ex = self._TranslateApitoolsResumableUploadException(e)
          if resumable_ex:
            raise resumable_ex
          else:
            raise
    except TRANSLATABLE_APITOOLS_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, bucket_name=object_metadata.bucket,
                                       object_name=object_metadata.name)

  def UploadObject(self, upload_stream, object_metadata, canned_acl=None,
                   size=None, preconditions=None, provider=None, fields=None):
    """See CloudApi class for function doc strings."""
    return self._UploadObject(
        upload_stream, object_metadata, canned_acl=canned_acl,
        preconditions=preconditions, fields=fields, size=size,
        apitools_strategy='simple')

  def UploadObjectStreaming(self, upload_stream, object_metadata,
                            canned_acl=None, preconditions=None, provider=None,
                            fields=None):
    """See CloudApi class for function doc strings."""
    # Streaming indicated by not passing a size.
    return self._UploadObject(
        upload_stream, object_metadata, canned_acl=canned_acl,
        preconditions=preconditions, fields=fields, apitools_strategy='simple')

  def UploadObjectResumable(
      self, upload_stream, object_metadata, canned_acl=None, preconditions=None,
      provider=None, fields=None, size=None, serialization_data=None,
      tracker_callback=None, progress_callback=None):
    """See CloudApi class for function doc strings."""
    return self._UploadObject(
        upload_stream, object_metadata, canned_acl=canned_acl,
        preconditions=preconditions, fields=fields, size=size,
        serialization_data=serialization_data,
        tracker_callback=tracker_callback, progress_callback=progress_callback,
        apitools_strategy='resumable')

  def CopyObject(self, src_bucket_name, src_obj_name, dst_obj_metadata,
                 src_generation=None, canned_acl=None, preconditions=None,
                 provider=None, fields=None):
    """See CloudApi class for function doc strings."""
    ValidateDstObjectMetadata(dst_obj_metadata)
    assert not canned_acl, 'Canned ACLs not supported by JSON API.'

    if src_generation:
      src_generation = long(src_generation)

    if not preconditions:
      preconditions = Preconditions()

    projection = (apitools_messages.StorageObjectsCopyRequest
                  .ProjectionValueValuesEnum.full)
    global_params = apitools_messages.StandardQueryParameters()
    if fields:
      global_params.fields = ','.join(set(fields))

    apitools_request = apitools_messages.StorageObjectsCopyRequest(
        sourceBucket=src_bucket_name, sourceObject=src_obj_name,
        destinationBucket=dst_obj_metadata.bucket,
        destinationObject=dst_obj_metadata.name,
        projection=projection, object=dst_obj_metadata,
        sourceGeneration=src_generation,
        ifGenerationMatch=preconditions.gen_match,
        ifMetagenerationMatch=preconditions.meta_gen_match)
    try:
      return self.api_client.objects.Copy(apitools_request,
                                          global_params=global_params)
    except TRANSLATABLE_APITOOLS_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, bucket_name=dst_obj_metadata.bucket,
                                       object_name=dst_obj_metadata.name)

  def DeleteObject(self, bucket_name, object_name, preconditions=None,
                   generation=None, provider=None):
    """See CloudApi class for function doc strings."""
    if not preconditions:
      preconditions = Preconditions()

    if generation:
      generation = long(generation)

    apitools_request = apitools_messages.StorageObjectsDeleteRequest(
        bucket=bucket_name, object=object_name, generation=generation,
        ifGenerationMatch=preconditions.gen_match,
        ifMetagenerationMatch=preconditions.meta_gen_match)
    try:
      return self.api_client.objects.Delete(apitools_request)
    except TRANSLATABLE_APITOOLS_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, bucket_name=bucket_name,
                                       object_name=object_name,
                                       generation=generation)

  def ComposeObject(self, src_objs_metadata, dst_obj_metadata,
                    preconditions=None, provider=None, fields=None):
    """See CloudApi class for function doc strings."""
    ValidateDstObjectMetadata(dst_obj_metadata)

    dst_obj_name = dst_obj_metadata.name
    dst_obj_metadata.name = None
    dst_bucket_name = dst_obj_metadata.bucket
    dst_obj_metadata.bucket = None
    if not dst_obj_metadata.contentType:
      dst_obj_metadata.contentType = DEFAULT_CONTENT_TYPE

    if not preconditions:
      preconditions = Preconditions()

    global_params = apitools_messages.StandardQueryParameters()
    if fields:
      global_params.fields = ','.join(set(fields))

    src_objs_compose_request = apitools_messages.ComposeRequest(
        sourceObjects=src_objs_metadata, destination=dst_obj_metadata)

    apitools_request = apitools_messages.StorageObjectsComposeRequest(
        composeRequest=src_objs_compose_request,
        destinationBucket=dst_bucket_name,
        destinationObject=dst_obj_name,
        ifGenerationMatch=preconditions.gen_match,
        ifMetagenerationMatch=preconditions.meta_gen_match)
    try:
      return self.api_client.objects.Compose(apitools_request,
                                             global_params=global_params)
    except TRANSLATABLE_APITOOLS_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, bucket_name=dst_bucket_name,
                                       object_name=dst_obj_name)

  def WatchBucket(self, bucket_name, address, channel_id, token=None,
                  provider=None, fields=None):
    """See CloudApi class for function doc strings."""
    projection = (apitools_messages.StorageObjectsWatchAllRequest
                  .ProjectionValueValuesEnum.full)

    channel = apitools_messages.Channel(address=address, id=channel_id,
                                        token=token, type='WEB_HOOK')

    apitools_request = apitools_messages.StorageObjectsWatchAllRequest(
        bucket=bucket_name, channel=channel, projection=projection)

    global_params = apitools_messages.StandardQueryParameters()
    if fields:
      global_params.fields = ','.join(set(fields))

    try:
      return self.api_client.objects.WatchAll(apitools_request,
                                              global_params=global_params)
    except TRANSLATABLE_APITOOLS_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, bucket_name=bucket_name)

  def StopChannel(self, channel_id, resource_id, provider=None):
    """See CloudApi class for function doc strings."""
    channel = apitools_messages.Channel(id=channel_id, resourceId=resource_id)
    try:
      self.api_client.channels.Stop(channel)
    except TRANSLATABLE_APITOOLS_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e)

  def _TranslateExceptionAndRaise(self, e, bucket_name=None, object_name=None,
                                  generation=None):
    """Translates an HTTP exception and raises the translated or original value.

    Args:
      e: Any Exception.
      bucket_name: Optional bucket name in request that caused the exception.
      object_name: Optional object name in request that caused the exception.
      generation: Optional generation in request that caused the exception.

    Raises:
      Translated CloudApi exception, or the original exception if it was not
      translatable.
    """
    translated_exception = self._TranslateApitoolsException(
        e, bucket_name=bucket_name, object_name=object_name,
        generation=generation)
    if translated_exception:
      raise translated_exception
    else:
      raise

  def _GetMessageFromHttpError(self, http_error):
    if isinstance(http_error, apitools_exceptions.HttpError):
      if getattr(http_error, 'content', None):
        try:
          json_obj = json.loads(http_error.content)
          if 'error' in json_obj and 'message' in json_obj['error']:
            return json_obj['error']['message']
        except Exception:  # pylint: disable=broad-except
          # If we couldn't decode anything, just leave the message as None.
          pass

  def _TranslateApitoolsResumableUploadException(
      self, e, bucket_name=None, object_name=None, generation=None):
    if isinstance(e, apitools_exceptions.HttpError):
      message = self._GetMessageFromHttpError(e)
      if e.status_code == 400:
        return ResumableUploadAbortException(
            message or 'Bad Request', status=e.status_code)
      elif (e.status_code >= 500
            and not self.http.disable_ssl_certificate_validation):
        return ResumableUploadException(message, status=e.status_code)
    if (isinstance(e, apitools_exceptions.TransferError) and
        'Aborting transfer' in e.message):
      return ResumableUploadAbortException(e.message)

  def _TranslateApitoolsException(self, e, bucket_name=None, object_name=None,
                                  generation=None):
    """Translates apitools exceptions into their gsutil Cloud Api equivalents.

    Args:
      e: Any exception in TRANSLATABLE_APITOOLS_EXCEPTIONS.
      bucket_name: Optional bucket name in request that caused the exception.
      object_name: Optional object name in request that caused the exception.
      generation: Optional generation in request that caused the exception.

    Returns:
      CloudStorageApiServiceException for translatable exceptions, None
      otherwise.
    """
    if isinstance(e, apitools_exceptions.HttpError):
      message = self._GetMessageFromHttpError(e)
      if e.status_code == 400:
        # It is possible that the Project ID is incorrect.  Unfortunately the
        # JSON API does not give us much information about what part of the
        # request was bad.
        return BadRequestException(message or 'Bad Request',
                                   status=e.status_code)
      elif e.status_code == 401:
        if 'Login Required' in str(e):
          return AccessDeniedException(
              message or 'Access denied: login required.',
              status=e.status_code)
      elif e.status_code == 403:
        if 'The account for the specified project has been disabled' in str(e):
          return AccessDeniedException(message or 'Account disabled.',
                                       status=e.status_code)
        elif 'Daily Limit for Unauthenticated Use Exceeded' in str(e):
          return AccessDeniedException(
              message or 'Access denied: quota exceeded. '
              'Is your project ID valid?',
              status=e.status_code)
        elif 'The bucket you tried to delete was not empty.' in str(e):
          return NotEmptyException('BucketNotEmpty (%s)' % bucket_name,
                                   status=e.status_code)
        elif ('The bucket you tried to create requires domain ownership '
              'verification.' in str(e)):
          return AccessDeniedException(
              'The bucket you tried to create requires domain ownership '
              'verification. Please see '
              'https://developers.google.com/storage/docs/bucketnaming'
              '?hl=en#verification for more details.', status=e.status_code)
        return AccessDeniedException(e.message, status=e.status_code)
      elif e.status_code == 404:
        if bucket_name:
          if object_name:
            return CreateObjectNotFoundException(e.status_code, self.provider,
                                                 bucket_name, object_name,
                                                 generation=generation)
          return CreateBucketNotFoundException(e.status_code, self.provider,
                                               bucket_name)
        return NotFoundException(e.message, status=e.status_code)
      elif e.status_code == 409 and bucket_name:
        if 'The bucket you tried to delete was not empty.' in str(e):
          return NotEmptyException('BucketNotEmpty (%s)' % bucket_name,
                                   status=e.status_code)
        return ServiceException(
            'Bucket %s already exists.' % bucket_name, status=e.status_code)
      elif e.status_code == 412:
        return PreconditionException(message, status=e.status_code)
      elif (e.status_code == 503 and
            not self.http.disable_ssl_certificate_validation):
        return ServiceException(
            'Service Unavailable. If you have recently changed '
            'https_validate_certificates from True to False in your boto '
            'configuration file, please delete any cached access tokens '
            'in your filesystem and try again.',
            status=e.status_code)
      return ServiceException(message, status=e.status_code)
    elif isinstance(e, apitools_exceptions.TransferInvalidError):
      return ServiceException('Transfer invalid (possible encoding error)')

