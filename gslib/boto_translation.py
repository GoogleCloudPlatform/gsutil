# Copyright 2013 Google Inc. All Rights Reserved.
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
"""XML/boto gsutil Cloud API implementation for GCS and Amazon S3."""

from __future__ import absolute_import

import base64
import binascii
import datetime
import errno
import httplib
import json
import multiprocessing
import os
import pickle
import random
import re
import socket
import tempfile
import textwrap
import time
import xml
from xml.dom.minidom import parseString as XmlParseString
from xml.sax import _exceptions as SaxExceptions

import boto
from boto import handler
from boto.exception import ResumableDownloadException as BotoResumableDownloadException
from boto.exception import ResumableTransferDisposition
from boto.gs.cors import Cors
from boto.gs.lifecycle import LifecycleConfig
from boto.s3.deletemarker import DeleteMarker
from boto.s3.prefix import Prefix

from gslib.boto_resumable_upload import BotoResumableUpload
from gslib.cloud_api import AccessDeniedException
from gslib.cloud_api import ArgumentException
from gslib.cloud_api import BadRequestException
from gslib.cloud_api import CloudApi
from gslib.cloud_api import NotEmptyException
from gslib.cloud_api import NotFoundException
from gslib.cloud_api import PreconditionException
from gslib.cloud_api import ResumableDownloadException
from gslib.cloud_api import ResumableUploadAbortException
from gslib.cloud_api import ResumableUploadException
from gslib.cloud_api import ServiceException
from gslib.cloud_api_helper import ValidateDstObjectMetadata
from gslib.exception import CommandException
from gslib.exception import InvalidUrlError
from gslib.project_id import GOOG_PROJ_ID_HDR
from gslib.project_id import PopulateProjectId
from gslib.storage_url import StorageUrlFromString
from gslib.third_party.storage_apitools import storage_v1_messages as apitools_messages
from gslib.translation_helper import AclTranslation
from gslib.translation_helper import AddS3MarkerAclToObjectMetadata
from gslib.translation_helper import CorsTranslation
from gslib.translation_helper import CreateBucketNotFoundException
from gslib.translation_helper import CreateObjectNotFoundException
from gslib.translation_helper import DEFAULT_CONTENT_TYPE
from gslib.translation_helper import EncodeStringAsLong
from gslib.translation_helper import GenerationFromUrlAndString
from gslib.translation_helper import HeadersFromObjectMetadata
from gslib.translation_helper import LifecycleTranslation
from gslib.translation_helper import REMOVE_CORS_CONFIG
from gslib.translation_helper import S3MarkerAclFromObjectMetadata
from gslib.util import ConfigureNoOpAuthIfNeeded
from gslib.util import DEFAULT_FILE_BUFFER_SIZE
from gslib.util import GetFileSize
from gslib.util import GetMaxRetryDelay
from gslib.util import GetNumRetries
from gslib.util import MultiprocessingIsAvailable
from gslib.util import S3_DELETE_MARKER_GUID
from gslib.util import TWO_MB
from gslib.util import UnaryDictToXml
from gslib.util import UTF8
from gslib.util import XML_PROGRESS_CALLBACKS

TRANSLATABLE_BOTO_EXCEPTIONS = (boto.exception.BotoServerError,
                                boto.exception.InvalidUriError,
                                boto.exception.ResumableDownloadException,
                                boto.exception.ResumableUploadException,
                                boto.exception.StorageCreateError,
                                boto.exception.StorageResponseError)

# If multiprocessing is available, this will be overridden to a (thread-safe)
# multiprocessing.Value in a call to InitializeMultiprocessingVariables.
boto_auth_initialized = False

NON_EXISTENT_OBJECT_REGEX = re.compile(r'.*non-\s*existent\s*object',
                                       flags=re.DOTALL)
# Determines whether an etag is a valid MD5.
MD5_REGEX = re.compile(r'^"*[a-fA-F0-9]{32}"*$')


def InitializeMultiprocessingVariables():
  """Perform necessary initialization for multiprocessing.

    See gslib.command.InitializeMultiprocessingVariables for an explanation
    of why this is necessary.
  """
  global boto_auth_initialized  # pylint: disable=global-variable-undefined
  boto_auth_initialized = multiprocessing.Value('i', 0)


class BotoTranslation(CloudApi):
  """Boto-based XML translation implementation of gsutil Cloud API.

  This class takes gsutil Cloud API objects, translates them to XML service
  calls, and translates the results back into gsutil Cloud API objects for
  use by the caller.
  """

  def __init__(self, bucket_storage_uri_class, logger, provider=None,
               credentials=None, debug=0):
    """Performs necessary setup for interacting with the cloud storage provider.

    Args:
      bucket_storage_uri_class: boto storage_uri class, used by APIs that
                                provide boto translation or mocking.
      logger: logging.logger for outputting log messages.
      provider: Provider prefix describing cloud storage provider to connect to.
                'gs' and 's3' are supported. Function implementations ignore
                the provider argument and use this one instead.
      credentials: Unused.
      debug: Debug level for the API implementation (0..3).
    """
    super(BotoTranslation, self).__init__(bucket_storage_uri_class, logger,
                                          provider=provider, debug=debug)
    _ = credentials
    global boto_auth_initialized  # pylint: disable=global-variable-undefined
    if MultiprocessingIsAvailable()[0] and not boto_auth_initialized.value:
      ConfigureNoOpAuthIfNeeded()
      boto_auth_initialized.value = 1
    elif not boto_auth_initialized:
      ConfigureNoOpAuthIfNeeded()
      boto_auth_initialized = True
    self.api_version = boto.config.get_value(
        'GSUtil', 'default_api_version', '1')

  def GetBucket(self, bucket_name, provider=None, fields=None):
    """See CloudApi class for function doc strings."""
    _ = provider
    bucket_uri = self._StorageUriForBucket(bucket_name)
    headers = {}
    self._AddApiVersionToHeaders(headers)
    try:
      return self._BotoBucketToBucket(bucket_uri.get_bucket(validate=True,
                                                            headers=headers),
                                      fields=fields)
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, bucket_name=bucket_name)

  def ListBuckets(self, project_id=None, provider=None, fields=None):
    """See CloudApi class for function doc strings."""
    _ = provider
    get_fields = self._ListToGetFields(list_fields=fields)
    headers = {}
    self._AddApiVersionToHeaders(headers)
    if self.provider == 'gs':
      headers[GOOG_PROJ_ID_HDR] = PopulateProjectId(project_id)
    try:
      provider_uri = boto.storage_uri(
          '%s://' % self.provider,
          suppress_consec_slashes=False,
          bucket_storage_uri_class=self.bucket_storage_uri_class,
          debug=self.debug)

      buckets_iter = provider_uri.get_all_buckets(headers=headers)
      for bucket in buckets_iter:
        if self.provider == 's3' and bucket.name.lower() != bucket.name:
          # S3 listings can return buckets with upper-case names, but boto
          # can't successfully call them.
          continue
        yield self._BotoBucketToBucket(bucket, fields=get_fields)
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e)

  def PatchBucket(self, bucket_name, metadata, preconditions=None,
                  provider=None, fields=None):
    """See CloudApi class for function doc strings."""
    _ = provider
    bucket_uri = self._StorageUriForBucket(bucket_name)
    headers = {}
    self._AddApiVersionToHeaders(headers)
    try:
      self._AddPreconditionsToHeaders(preconditions, headers)
      if metadata.acl:
        boto_acl = AclTranslation.BotoAclFromMessage(metadata.acl)
        bucket_uri.set_xml_acl(boto_acl.to_xml(), headers=headers)
      if metadata.cors:
        if metadata.cors == REMOVE_CORS_CONFIG:
          metadata.cors = []
        boto_cors = CorsTranslation.BotoCorsFromMessage(metadata.cors)
        bucket_uri.set_cors(boto_cors, False)
      if metadata.defaultObjectAcl:
        boto_acl = AclTranslation.BotoAclFromMessage(
            metadata.defaultObjectAcl)
        bucket_uri.set_def_xml_acl(boto_acl.to_xml(), headers=headers)
      if metadata.lifecycle:
        boto_lifecycle = LifecycleTranslation.BotoLifecycleFromMessage(
            metadata.lifecycle)
        bucket_uri.configure_lifecycle(boto_lifecycle, False)
      if metadata.logging:
        if self.provider == 'gs':
          headers[GOOG_PROJ_ID_HDR] = PopulateProjectId(None)
        if metadata.logging.logBucket and metadata.logging.logObjectPrefix:
          bucket_uri.enable_logging(metadata.logging.logBucket,
                                    metadata.logging.logObjectPrefix,
                                    False, headers)
        else:  # Logging field is present and empty.  Disable logging.
          bucket_uri.disable_logging(False, headers)
      if metadata.versioning:
        bucket_uri.configure_versioning(metadata.versioning.enabled,
                                        headers=headers)
      if metadata.website:
        main_page_suffix = metadata.website.mainPageSuffix
        error_page = metadata.website.notFoundPage
        bucket_uri.set_website_config(main_page_suffix, error_page)
      return self.GetBucket(bucket_name, fields=fields)
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, bucket_name=bucket_name)

  def CreateBucket(self, bucket_name, project_id=None, metadata=None,
                   provider=None, fields=None):
    """See CloudApi class for function doc strings."""
    _ = provider
    bucket_uri = self._StorageUriForBucket(bucket_name)
    location = ''
    if metadata and metadata.location:
      location = metadata.location
    # Pass storage_class param only if this is a GCS bucket. (In S3 the
    # storage class is specified on the key object.)
    headers = {}
    if bucket_uri.scheme == 'gs':
      self._AddApiVersionToHeaders(headers)
      headers[GOOG_PROJ_ID_HDR] = PopulateProjectId(project_id)
      storage_class = ''
      if metadata and metadata.storageClass:
        storage_class = metadata.storageClass
      try:
        bucket_uri.create_bucket(headers=headers, location=location,
                                 storage_class=storage_class)
      except TRANSLATABLE_BOTO_EXCEPTIONS, e:
        self._TranslateExceptionAndRaise(e, bucket_name=bucket_name)
    else:
      try:
        bucket_uri.create_bucket(headers=headers, location=location)
      except TRANSLATABLE_BOTO_EXCEPTIONS, e:
        self._TranslateExceptionAndRaise(e, bucket_name=bucket_name)
    return self.GetBucket(bucket_name, fields=fields)

  def DeleteBucket(self, bucket_name, preconditions=None, provider=None):
    """See CloudApi class for function doc strings."""
    _ = provider, preconditions
    bucket_uri = self._StorageUriForBucket(bucket_name)
    headers = {}
    self._AddApiVersionToHeaders(headers)
    try:
      bucket_uri.delete_bucket(headers=headers)
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      translated_exception = self._TranslateBotoException(
          e, bucket_name=bucket_name)
      if (translated_exception and
          'BucketNotEmpty' in translated_exception.reason):
        try:
          if bucket_uri.get_versioning_config():
            if self.provider == 's3':
              raise NotEmptyException(
                  'VersionedBucketNotEmpty (%s). Currently, gsutil does not '
                  'support listing or removing S3 DeleteMarkers, so you may '
                  'need to delete these using another tool to successfully '
                  'delete this bucket.' % bucket_name, status=e.status)
            raise NotEmptyException(
                'VersionedBucketNotEmpty (%s)' % bucket_name, status=e.status)
          else:
            raise NotEmptyException('BucketNotEmpty (%s)' % bucket_name,
                                    status=e.status)
        except TRANSLATABLE_BOTO_EXCEPTIONS, e2:
          self._TranslateExceptionAndRaise(e2, bucket_name=bucket_name)
      elif translated_exception and translated_exception.status == 404:
        raise NotFoundException('Bucket %s does not exist.' % bucket_name)
      else:
        self._TranslateExceptionAndRaise(e, bucket_name=bucket_name)

  def ListObjects(self, bucket_name, prefix=None, delimiter=None,
                  all_versions=None, provider=None, fields=None):
    """See CloudApi class for function doc strings."""
    _ = provider
    get_fields = self._ListToGetFields(list_fields=fields)
    bucket_uri = self._StorageUriForBucket(bucket_name)
    prefix_list = []
    headers = {}
    self._AddApiVersionToHeaders(headers)
    try:
      objects_iter = bucket_uri.list_bucket(prefix=prefix or '',
                                            delimiter=delimiter or '',
                                            all_versions=all_versions,
                                            headers=headers)
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, bucket_name=bucket_name)

    try:
      for key in objects_iter:
        if isinstance(key, Prefix):
          prefix_list.append(key.name)
          yield CloudApi.CsObjectOrPrefix(key.name,
                                          CloudApi.CsObjectOrPrefixType.PREFIX)
        else:
          key_to_convert = key

          # Listed keys are populated with these fields during bucket listing.
          key_http_fields = set(['bucket', 'etag', 'name', 'updated',
                                 'generation', 'metageneration', 'size'])

          # When fields == None, the caller is requesting all possible fields.
          # If the caller requested any fields that are not populated by bucket
          # listing, we'll need to make a separate HTTP call for each object to
          # get its metadata and populate the remaining fields with the result.
          if not get_fields or (get_fields and not
                                get_fields.issubset(key_http_fields)):

            generation = None
            if getattr(key, 'generation', None):
              generation = key.generation
            if getattr(key, 'version_id', None):
              generation = key.version_id
            key_to_convert = self._GetBotoKey(bucket_name, key.name,
                                              generation=generation)
          return_object = self._BotoKeyToObject(key_to_convert,
                                                fields=get_fields)

          yield CloudApi.CsObjectOrPrefix(return_object,
                                          CloudApi.CsObjectOrPrefixType.OBJECT)
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, bucket_name=bucket_name)

  def GetObjectMetadata(self, bucket_name, object_name, generation=None,
                        provider=None, fields=None):
    """See CloudApi class for function doc strings."""
    _ = provider
    try:
      return self._BotoKeyToObject(self._GetBotoKey(bucket_name, object_name,
                                                    generation=generation),
                                   fields=fields)
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, bucket_name=bucket_name,
                                       object_name=object_name,
                                       generation=generation)

  def _CurryDigester(self, digester_object):
    """Curries a digester object into a form consumable by boto.

    Key instantiates its own digesters by calling hash_algs[alg]() [note there
    are no arguments to this function].  So in order to pass in our caught-up
    digesters during a resumable download, we need to pass the digester
    object but don't get to look it up based on the algorithm name.  Here we
    use a lambda to make lookup implicit.

    Args:
      digester_object: Input object to be returned by the created function.

    Returns:
      A function which when called will return the input object.
    """
    return lambda: digester_object

  def GetObjectMedia(
      self, bucket_name, object_name, download_stream, provider=None,
      generation=None, object_size=None,
      download_strategy=CloudApi.DownloadStrategy.ONE_SHOT,
      start_byte=0, end_byte=None, progress_callback=None,
      serialization_data=None, digesters=None):
    """See CloudApi class for function doc strings."""
    # This implementation will get the object metadata first if we don't pass it
    # in via serialization_data.
    headers = {}
    self._AddApiVersionToHeaders(headers)
    if 'accept-encoding' not in headers:
      headers['accept-encoding'] = 'gzip'
    if end_byte:
      headers['range'] = 'bytes=%s-%s' % (start_byte, end_byte)
    elif start_byte > 0:
      headers['range'] = 'bytes=%s-' % (start_byte)
    else:
      headers['range'] = 'bytes=%s' % (start_byte)

    # Since in most cases we already made a call to get the object metadata,
    # here we avoid an extra HTTP call by unpickling the key.  This is coupled
    # with the implementation in _BotoKeyToObject.
    if serialization_data:
      serialization_dict = json.loads(serialization_data)
      key = pickle.loads(binascii.a2b_base64(serialization_dict['url']))
    else:
      key = self._GetBotoKey(bucket_name, object_name, generation=generation)

    if digesters and self.provider == 'gs':
      hash_algs = {}
      for alg in digesters:
        hash_algs[alg] = self._CurryDigester(digesters[alg])
    else:
      hash_algs = {}

    total_size = object_size or 0
    if serialization_data:
      total_size = json.loads(serialization_data)['total_size']

    if download_strategy is CloudApi.DownloadStrategy.RESUMABLE:
      try:
        if total_size:
          num_progress_callbacks = max(int(total_size) / TWO_MB,
                                       XML_PROGRESS_CALLBACKS)
        else:
          num_progress_callbacks = XML_PROGRESS_CALLBACKS
        self._PerformResumableDownload(
            download_stream, key, headers=headers, callback=progress_callback,
            num_callbacks=num_progress_callbacks, hash_algs=hash_algs)
      except TRANSLATABLE_BOTO_EXCEPTIONS, e:
        self._TranslateExceptionAndRaise(e, bucket_name=bucket_name,
                                         object_name=object_name,
                                         generation=generation)
    elif download_strategy is CloudApi.DownloadStrategy.ONE_SHOT:
      try:
        self._PerformSimpleDownload(download_stream, key, headers=headers,
                                    hash_algs=hash_algs)
      except TRANSLATABLE_BOTO_EXCEPTIONS, e:
        self._TranslateExceptionAndRaise(e, bucket_name=bucket_name,
                                         object_name=object_name,
                                         generation=generation)
    else:
      raise ArgumentException('Unsupported DownloadStrategy: %s' %
                              download_strategy)

    if self.provider == 's3':
      if digesters:

        class HashToDigester(object):
          """Wrapper class to expose hash digests.

          boto creates its own digesters in s3's get_file, returning on-the-fly
          hashes only by way of key.local_hashes.  To propagate the digest back
          to the caller, this stub class implements the digest() function.
          """

          def __init__(self, hash_val):
            self.hash_val = hash_val

          def digest(self):  # pylint: disable=invalid-name
            return self.hash_val

        for alg_name in digesters:
          if ((download_strategy == CloudApi.DownloadStrategy.RESUMABLE and
               start_byte != 0) or
              not ((getattr(key, 'local_hashes', None) and
                    alg_name in key.local_hashes))):
            # For resumable downloads, boto does not provide a mechanism to
            # catch up the hash in the case of a partially complete download.
            # In this case or in the case where no digest was successfully
            # calculated, set the digester to None, which indicates that we'll
            # need to manually calculate the hash from the local file once it
            # is complete.
            digesters[alg_name] = None
          else:
            # Use the on-the-fly hash.
            digesters[alg_name] = HashToDigester(key.local_hashes[alg_name])

  def _PerformSimpleDownload(self, download_stream, key, headers=None,
                             hash_algs=None):
    if not headers:
      headers = {}
      self._AddApiVersionToHeaders(headers)
    try:
      key.get_contents_to_file(download_stream, headers=headers,
                               hash_algs=hash_algs)
    except TypeError:  # s3 and mocks do not support hash_algs
      key.get_contents_to_file(download_stream, headers=headers)

  def _PerformResumableDownload(self, fp, key, headers=None, callback=None,
                                num_callbacks=XML_PROGRESS_CALLBACKS,
                                hash_algs=None):
    """Downloads bytes from key to fp, resuming as needed.

    Args:
      fp: File pointer into which data should be downloaded
      key: Key object from which data is to be downloaded
      headers: Headers to send when retrieving the file
      callback: (optional) a callback function that will be called to report
           progress on the download.  The callback should accept two integer
           parameters.  The first integer represents the number of
           bytes that have been successfully transmitted from the service.  The
           second represents the total number of bytes that need to be
           transmitted.
      num_callbacks: (optional) If a callback is specified with the callback
           parameter, this determines the granularity of the callback
           by defining the maximum number of times the callback will be
           called during the file transfer.
      hash_algs: Dict of hash algorithms to apply to downloaded bytes.

    Raises:
      ResumableDownloadException on error.
    """
    if not headers:
      headers = {}
      self._AddApiVersionToHeaders(headers)

    retryable_exceptions = (httplib.HTTPException, IOError, socket.error,
                            socket.gaierror)

    debug = key.bucket.connection.debug

    num_retries = GetNumRetries()
    progress_less_iterations = 0

    while True:  # Retry as long as we're making progress.
      had_file_bytes_before_attempt = GetFileSize(fp)
      try:
        cur_file_size = GetFileSize(fp, position_to_eof=True)

        def DownloadProxyCallback(total_bytes_downloaded, total_size):
          """Translates a boto callback into a gsutil Cloud API callback.

          Callbacks are originally made by boto.s3.Key.get_file(); here we take
          into account that we're resuming a download.

          Args:
            total_bytes_downloaded: Actual bytes downloaded so far, not
                                    including the point we resumed from.
            total_size: Total size of the download.
          """
          if callback:
            callback(cur_file_size + total_bytes_downloaded, total_size)

        headers = headers.copy()
        headers['Range'] = 'bytes=%d-%d' % (cur_file_size, key.size - 1)
        cb = DownloadProxyCallback

        # Disable AWSAuthConnection-level retry behavior, since that would
        # cause downloads to restart from scratch.
        try:
          key.get_file(fp, headers, cb, num_callbacks, override_num_retries=0,
                       hash_algs=hash_algs)
        except TypeError:
          key.get_file(fp, headers, cb, num_callbacks, override_num_retries=0)
        fp.flush()
        # Download succeeded.
        return
      except retryable_exceptions, e:
        if debug >= 1:
          self.logger.info('Caught exception (%s)' % e.__repr__())
        if isinstance(e, IOError) and e.errno == errno.EPIPE:
          # Broken pipe error causes httplib to immediately
          # close the socket (http://bugs.python.org/issue5542),
          # so we need to close and reopen the key before resuming
          # the download.
          if self.provider == 's3':
            key.get_file(fp, headers, cb, num_callbacks, override_num_retries=0)
          else:  # self.provider == 'gs'
            key.get_file(fp, headers, cb, num_callbacks,
                         override_num_retries=0, hash_algs=hash_algs)
      except BotoResumableDownloadException, e:
        if (e.disposition ==
            ResumableTransferDisposition.ABORT_CUR_PROCESS):
          raise ResumableDownloadException(e.message)
        else:
          if debug >= 1:
            self.logger.info('Caught ResumableDownloadException (%s) - will '
                             'retry' % e.message)

      # At this point we had a re-tryable failure; see if made progress.
      if GetFileSize(fp) > had_file_bytes_before_attempt:
        progress_less_iterations = 0
      else:
        progress_less_iterations += 1

      if progress_less_iterations > num_retries:
        # Don't retry any longer in the current process.
        raise ResumableDownloadException(
            'Too many resumable download attempts failed without '
            'progress. You might try this download again later')

      # Close the key, in case a previous download died partway
      # through and left data in the underlying key HTTP buffer.
      # Do this within a try/except block in case the connection is
      # closed (since key.close() attempts to do a final read, in which
      # case this read attempt would get an IncompleteRead exception,
      # which we can safely ignore).
      try:
        key.close()
      except httplib.IncompleteRead:
        pass

      sleep_time_secs = min(random.random() * (2 ** progress_less_iterations),
                            GetMaxRetryDelay())
      if debug >= 1:
        self.logger.info('Got retryable failure (%d progress-less in a row).\n'
                         'Sleeping %d seconds before re-trying' %
                         (progress_less_iterations, sleep_time_secs))
      time.sleep(sleep_time_secs)

  def PatchObjectMetadata(self, bucket_name, object_name, metadata,
                          generation=None, preconditions=None, provider=None,
                          fields=None):
    """See CloudApi class for function doc strings."""
    _ = provider
    object_uri = self._StorageUriForObject(bucket_name, object_name,
                                           generation=generation)

    headers = {}
    self._AddApiVersionToHeaders(headers)
    meta_headers = HeadersFromObjectMetadata(metadata, self.provider)

    metadata_plus = {}
    metadata_minus = set()
    metadata_changed = False
    for k, v in meta_headers.iteritems():
      metadata_changed = True
      if v is None:
        metadata_minus.add(k)
      else:
        metadata_plus[k] = v

    self._AddPreconditionsToHeaders(preconditions, headers)

    if metadata_changed:
      try:
        object_uri.set_metadata(metadata_plus, metadata_minus, False,
                                headers=headers)
      except TRANSLATABLE_BOTO_EXCEPTIONS, e:
        self._TranslateExceptionAndRaise(e, bucket_name=bucket_name,
                                         object_name=object_name,
                                         generation=generation)

    if metadata.acl:
      boto_acl = AclTranslation.BotoAclFromMessage(metadata.acl)
      try:
        object_uri.set_xml_acl(boto_acl.to_xml(), key_name=object_name)
      except TRANSLATABLE_BOTO_EXCEPTIONS, e:
        self._TranslateExceptionAndRaise(e, bucket_name=bucket_name,
                                         object_name=object_name,
                                         generation=generation)
    return self.GetObjectMetadata(bucket_name, object_name,
                                  generation=generation, fields=fields)

  def _PerformSimpleUpload(self, dst_uri, upload_stream, md5=None,
                           canned_acl=None, progress_callback=None,
                           headers=None):
    dst_uri.set_contents_from_file(upload_stream, md5=md5, policy=canned_acl,
                                   cb=progress_callback, headers=headers)

  def _PerformStreamingUpload(self, dst_uri, upload_stream, canned_acl=None,
                              progress_callback=None, headers=None):
    if dst_uri.get_provider().supports_chunked_transfer():
      dst_uri.set_contents_from_stream(upload_stream, policy=canned_acl,
                                       cb=progress_callback, headers=headers)
    else:
      # Provider doesn't support chunked transfer, so copy to a temporary
      # file.
      (temp_fh, temp_path) = tempfile.mkstemp()
      try:
        with open(temp_path, 'wb') as out_fp:
          stream_bytes = upload_stream.read(DEFAULT_FILE_BUFFER_SIZE)
          while stream_bytes:
            out_fp.write(stream_bytes)
            stream_bytes = upload_stream.read(DEFAULT_FILE_BUFFER_SIZE)
        with open(temp_path, 'rb') as in_fp:
          dst_uri.set_contents_from_file(in_fp, policy=canned_acl,
                                         headers=headers)
      finally:
        os.close(temp_fh)
        os.unlink(temp_path)

  def _PerformResumableUpload(self, key, upload_stream, upload_size,
                              tracker_callback, canned_acl=None,
                              serialization_data=None, progress_callback=None,
                              headers=None):
    resumable_upload = BotoResumableUpload(
        tracker_callback, self.logger, resume_url=serialization_data)
    resumable_upload.SendFile(key, upload_stream, upload_size,
                              canned_acl=canned_acl, cb=progress_callback,
                              headers=headers)

  def _UploadSetup(self, object_metadata, preconditions=None):
    """Shared upload implementation.

    Args:
      object_metadata: Object metadata describing destination object.
      preconditions: Optional gsutil Cloud API preconditions.

    Returns:
      Headers dictionary, StorageUri for upload (based on inputs)
    """
    ValidateDstObjectMetadata(object_metadata)

    headers = HeadersFromObjectMetadata(object_metadata, self.provider)
    self._AddApiVersionToHeaders(headers)

    if object_metadata.crc32c:
      if 'x-goog-hash' in headers:
        headers['x-goog-hash'] += (
            ',crc32c=%s' % object_metadata.crc32c.rstrip('\n'))
      else:
        headers['x-goog-hash'] = (
            'crc32c=%s' % object_metadata.crc32c.rstrip('\n'))
    if object_metadata.md5Hash:
      if 'x-goog-hash' in headers:
        headers['x-goog-hash'] += (
            ',md5=%s' % object_metadata.md5Hash.rstrip('\n'))
      else:
        headers['x-goog-hash'] = (
            'md5=%s' % object_metadata.md5Hash.rstrip('\n'))

    if 'content-type' in headers and not headers['content-type']:
      headers['content-type'] = 'application/octet-stream'

    self._AddPreconditionsToHeaders(preconditions, headers)

    dst_uri = self._StorageUriForObject(object_metadata.bucket,
                                        object_metadata.name)
    return headers, dst_uri

  def _HandleSuccessfulUpload(self, dst_uri, object_metadata, fields=None):
    """Set ACLs on an uploaded object and return its metadata.

    Args:
      dst_uri: Generation-specific StorageUri describing the object.
      object_metadata: Metadata for the object, including an ACL if applicable.
      fields: If present, return only these Object metadata fields.

    Returns:
      gsutil Cloud API Object metadata.

    Raises:
      CommandException if the object was overwritten / deleted concurrently.
    """
    try:
      # The XML API does not support if-generation-match for GET requests.
      # Therefore, if the object gets overwritten before the ACL and get_key
      # operations, the best we can do is warn that it happened.
      self._SetObjectAcl(object_metadata, dst_uri)
      return self._BotoKeyToObject(dst_uri.get_key(), fields=fields)
    except boto.exception.InvalidUriError as e:
      check_for_str = 'Attempt to get key for "%s" failed.' % dst_uri.uri
      if check_for_str in e.message:
        raise CommandException('\n'.join(textwrap.wrap(
            'Uploaded object (%s) was deleted or overwritten immediately '
            'after it was uploaded. This can happen if you attempt to upload '
            'to the same object multiple times concurrently.' % dst_uri.uri)))
      else:
        raise

  def _SetObjectAcl(self, object_metadata, dst_uri):
    """Sets the ACL (if present in object_metadata) on an uploaded object."""
    if object_metadata.acl:
      boto_acl = AclTranslation.BotoAclFromMessage(object_metadata.acl)
      dst_uri.set_xml_acl(boto_acl.to_xml())
    elif self.provider == 's3':
      s3_acl = S3MarkerAclFromObjectMetadata(object_metadata)
      if s3_acl:
        dst_uri.set_xml_acl(s3_acl)

  def UploadObjectResumable(
      self, upload_stream, object_metadata, canned_acl=None, preconditions=None,
      provider=None, fields=None, size=None, serialization_data=None,
      tracker_callback=None, progress_callback=None):
    """See CloudApi class for function doc strings."""
    if self.provider == 's3':
      # Resumable uploads are not supported for s3.
      return self.UploadObject(
          upload_stream, object_metadata, canned_acl=canned_acl,
          preconditions=preconditions, fields=fields, size=size)
    headers, dst_uri = self._UploadSetup(object_metadata,
                                         preconditions=preconditions)
    if not tracker_callback:
      raise ArgumentException('No tracker callback function set for '
                              'resumable upload of %s' % dst_uri)
    try:
      self._PerformResumableUpload(dst_uri.new_key(headers=headers),
                                   upload_stream, size, tracker_callback,
                                   canned_acl=canned_acl,
                                   serialization_data=serialization_data,
                                   progress_callback=progress_callback,
                                   headers=headers)
      return self._HandleSuccessfulUpload(dst_uri, object_metadata,
                                          fields=fields)
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, bucket_name=object_metadata.bucket,
                                       object_name=object_metadata.name)

  def UploadObjectStreaming(self, upload_stream, object_metadata,
                            canned_acl=None, progress_callback=None,
                            preconditions=None, provider=None, fields=None):
    """See CloudApi class for function doc strings."""
    headers, dst_uri = self._UploadSetup(object_metadata,
                                         preconditions=preconditions)

    try:
      self._PerformStreamingUpload(
          dst_uri, upload_stream, canned_acl=canned_acl,
          progress_callback=progress_callback, headers=headers)
      return self._HandleSuccessfulUpload(dst_uri, object_metadata,
                                          fields=fields)
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, bucket_name=object_metadata.bucket,
                                       object_name=object_metadata.name)

  def UploadObject(self, upload_stream, object_metadata, canned_acl=None,
                   preconditions=None, size=None, progress_callback=None,
                   provider=None, fields=None):
    """See CloudApi class for function doc strings."""
    headers, dst_uri = self._UploadSetup(object_metadata,
                                         preconditions=preconditions)

    try:
      md5 = None
      if object_metadata.md5Hash:
        md5 = []
        # boto expects hex at index 0, base64 at index 1
        md5.append(binascii.hexlify(
            base64.decodestring(object_metadata.md5Hash.strip('\n"\''))))
        md5.append(object_metadata.md5Hash.strip('\n"\''))
      self._PerformSimpleUpload(dst_uri, upload_stream, md5=md5,
                                canned_acl=canned_acl,
                                progress_callback=progress_callback,
                                headers=headers)
      return self._HandleSuccessfulUpload(dst_uri, object_metadata,
                                          fields=fields)
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, bucket_name=object_metadata.bucket,
                                       object_name=object_metadata.name)

  def DeleteObject(self, bucket_name, object_name, preconditions=None,
                   generation=None, provider=None):
    """See CloudApi class for function doc strings."""
    _ = provider
    headers = {}
    self._AddApiVersionToHeaders(headers)
    self._AddPreconditionsToHeaders(preconditions, headers)

    uri = self._StorageUriForObject(bucket_name, object_name,
                                    generation=generation)
    try:
      uri.delete_key(validate=False, headers=headers)
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, bucket_name=bucket_name,
                                       object_name=object_name,
                                       generation=generation)

  def CopyObject(self, src_bucket_name, src_obj_name, dst_obj_metadata,
                 src_generation=None, canned_acl=None, preconditions=None,
                 provider=None, fields=None):
    """See CloudApi class for function doc strings."""
    _ = provider
    dst_uri = self._StorageUriForObject(dst_obj_metadata.bucket,
                                        dst_obj_metadata.name)

    # Usually it's okay to treat version_id and generation as
    # the same, but in this case the underlying boto call determines the
    # provider based on the presence of one or the other.
    src_version_id = None
    if self.provider == 's3':
      src_version_id = src_generation
      src_generation = None

    headers = HeadersFromObjectMetadata(dst_obj_metadata, self.provider)
    self._AddApiVersionToHeaders(headers)
    self._AddPreconditionsToHeaders(preconditions, headers)

    if canned_acl:
      headers[dst_uri.get_provider().acl_header] = canned_acl

    preserve_acl = True if dst_obj_metadata.acl else False
    if self.provider == 's3':
      s3_acl = S3MarkerAclFromObjectMetadata(dst_obj_metadata)
      if s3_acl:
        preserve_acl = True

    try:
      new_key = dst_uri.copy_key(
          src_bucket_name, src_obj_name, preserve_acl=preserve_acl,
          headers=headers, src_version_id=src_version_id,
          src_generation=src_generation)

      return self._BotoKeyToObject(new_key, fields=fields)
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, dst_obj_metadata.bucket,
                                       dst_obj_metadata.name)

  def ComposeObject(self, src_objs_metadata, dst_obj_metadata,
                    preconditions=None, provider=None, fields=None):
    """See CloudApi class for function doc strings."""
    _ = provider
    ValidateDstObjectMetadata(dst_obj_metadata)

    dst_obj_name = dst_obj_metadata.name
    dst_obj_metadata.name = None
    dst_bucket_name = dst_obj_metadata.bucket
    dst_obj_metadata.bucket = None
    headers = HeadersFromObjectMetadata(dst_obj_metadata, self.provider)
    if not dst_obj_metadata.contentType:
      dst_obj_metadata.contentType = DEFAULT_CONTENT_TYPE
      headers['content-type'] = dst_obj_metadata.contentType
    self._AddApiVersionToHeaders(headers)
    self._AddPreconditionsToHeaders(preconditions, headers)

    dst_uri = self._StorageUriForObject(dst_bucket_name, dst_obj_name)

    src_components = []
    for src_obj in src_objs_metadata:
      src_uri = self._StorageUriForObject(dst_bucket_name, src_obj.name,
                                          generation=src_obj.generation)
      src_components.append(src_uri)

    try:
      dst_uri.compose(src_components, headers=headers)

      return self.GetObjectMetadata(dst_bucket_name, dst_obj_name,
                                    fields=fields)
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, dst_obj_metadata.bucket,
                                       dst_obj_metadata.name)

  def _AddPreconditionsToHeaders(self, preconditions, headers):
    """Adds preconditions (if any) to headers."""
    if preconditions and self.provider == 'gs':
      if preconditions.gen_match:
        headers['x-goog-if-generation-match'] = preconditions.gen_match
      if preconditions.meta_gen_match:
        headers['x-goog-if-metageneration-match'] = preconditions.meta_gen_match

  def _AddApiVersionToHeaders(self, headers):
    if self.provider == 'gs':
      headers['x-goog-api-version'] = self.api_version

  def _GetMD5FromETag(self, src_etag):
    """Returns an MD5 from the etag iff the etag is a valid MD5 hash.

    Args:
      src_etag: Object etag for which to return the MD5.

    Returns:
      MD5 in hex string format, or None.
    """
    if src_etag and MD5_REGEX.search(src_etag):
      return src_etag.strip('"\'').lower()

  def _StorageUriForBucket(self, bucket):
    """Returns a boto storage_uri for the given bucket name.

    Args:
      bucket: Bucket name (string).

    Returns:
      Boto storage_uri for the bucket.
    """
    return boto.storage_uri(
        '%s://%s' % (self.provider, bucket),
        suppress_consec_slashes=False,
        bucket_storage_uri_class=self.bucket_storage_uri_class,
        debug=self.debug)

  def _StorageUriForObject(self, bucket, object_name, generation=None):
    """Returns a boto storage_uri for the given object.

    Args:
      bucket: Bucket name (string).
      object_name: Object name (string).
      generation: Generation or version_id of object.  If None, live version
                  of the object is used.

    Returns:
      Boto storage_uri for the object.
    """
    uri_string = '%s://%s/%s' % (self.provider, bucket, object_name)
    if generation:
      uri_string += '#%s' % generation
    return boto.storage_uri(
        uri_string, suppress_consec_slashes=False,
        bucket_storage_uri_class=self.bucket_storage_uri_class,
        debug=self.debug)

  def _GetBotoKey(self, bucket_name, object_name, generation=None):
    """Gets the boto key for an object.

    Args:
      bucket_name: Bucket containing the object.
      object_name: Object name.
      generation: Generation or version of the object to retrieve.

    Returns:
      Boto key for the object.
    """
    object_uri = self._StorageUriForObject(bucket_name, object_name,
                                           generation=generation)
    try:
      key = object_uri.get_key()
      if not key:
        raise CreateObjectNotFoundException('404', self.provider,
                                            bucket_name, object_name,
                                            generation=generation)
      return key
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e, bucket_name=bucket_name,
                                       object_name=object_name,
                                       generation=generation)

  def _ListToGetFields(self, list_fields=None):
    """Removes 'items/' from the input fields and converts it to a set.

    This way field sets requested for ListBucket/ListObject can be used in
    _BotoBucketToBucket and _BotoKeyToObject calls.

    Args:
      list_fields: Iterable fields usable in ListBucket/ListObject calls.

    Returns:
      Set of fields usable in GetBucket/GetObject or
      _BotoBucketToBucket/_BotoKeyToObject calls.
    """
    if list_fields:
      get_fields = set()
      for field in list_fields:
        if field in ['kind', 'nextPageToken', 'prefixes']:
          # These are not actually object / bucket metadata fields.
          # They are fields specific to listing, so we don't consider them.
          continue
        get_fields.add(re.sub(r'items/', '', field))
      return get_fields

  # pylint: disable=too-many-statements
  def _BotoBucketToBucket(self, bucket, fields=None):
    """Constructs an apitools Bucket from a boto bucket.

    Args:
      bucket: Boto bucket.
      fields: If present, construct the apitools Bucket with only this set of
              metadata fields.

    Returns:
      apitools Bucket.
    """
    bucket_uri = self._StorageUriForBucket(bucket.name)

    cloud_api_bucket = apitools_messages.Bucket(name=bucket.name,
                                                id=bucket.name)
    headers = {}
    self._AddApiVersionToHeaders(headers)
    if self.provider == 'gs':
      if not fields or 'storageClass' in fields:
        if hasattr(bucket, 'get_storage_class'):
          cloud_api_bucket.storageClass = bucket.get_storage_class()
      if not fields or 'acl' in fields:
        for acl in AclTranslation.BotoBucketAclToMessage(
            bucket.get_acl(headers=headers)):
          try:
            cloud_api_bucket.acl.append(acl)
          except TRANSLATABLE_BOTO_EXCEPTIONS, e:
            translated_exception = self._TranslateBotoException(
                e, bucket_name=bucket.name)
            if (translated_exception and
                isinstance(translated_exception,
                           AccessDeniedException)):
              # JSON API doesn't differentiate between a blank ACL list
              # and an access denied, so this is intentionally left blank.
              pass
            else:
              self._TranslateExceptionAndRaise(e, bucket_name=bucket.name)
      if not fields or 'cors' in fields:
        try:
          boto_cors = bucket_uri.get_cors()
          cloud_api_bucket.cors = CorsTranslation.BotoCorsToMessage(boto_cors)
        except TRANSLATABLE_BOTO_EXCEPTIONS, e:
          self._TranslateExceptionAndRaise(e, bucket_name=bucket.name)
      if not fields or 'defaultObjectAcl' in fields:
        for acl in AclTranslation.BotoObjectAclToMessage(
            bucket.get_def_acl(headers=headers)):
          try:
            cloud_api_bucket.defaultObjectAcl.append(acl)
          except TRANSLATABLE_BOTO_EXCEPTIONS, e:
            translated_exception = self._TranslateBotoException(
                e, bucket_name=bucket.name)
            if (translated_exception and
                isinstance(translated_exception,
                           AccessDeniedException)):
              # JSON API doesn't differentiate between a blank ACL list
              # and an access denied, so this is intentionally left blank.
              pass
            else:
              self._TranslateExceptionAndRaise(e, bucket_name=bucket.name)
      if not fields or 'lifecycle' in fields:
        try:
          boto_lifecycle = bucket_uri.get_lifecycle_config()
          cloud_api_bucket.lifecycle = (
              LifecycleTranslation.BotoLifecycleToMessage(boto_lifecycle))
        except TRANSLATABLE_BOTO_EXCEPTIONS, e:
          self._TranslateExceptionAndRaise(e, bucket_name=bucket.name)
      if not fields or 'logging' in fields:
        try:
          boto_logging = bucket_uri.get_logging_config()
          if boto_logging and 'Logging' in boto_logging:
            logging_config = boto_logging['Logging']
            cloud_api_bucket.logging = apitools_messages.Bucket.LoggingValue()
            if 'LogObjectPrefix' in logging_config:
              cloud_api_bucket.logging.logObjectPrefix = (
                  logging_config['LogObjectPrefix'])
            if 'LogBucket' in logging_config:
              cloud_api_bucket.logging.logBucket = logging_config['LogBucket']
        except TRANSLATABLE_BOTO_EXCEPTIONS, e:
          self._TranslateExceptionAndRaise(e, bucket_name=bucket.name)
      if not fields or 'website' in fields:
        try:
          boto_website = bucket_uri.get_website_config()
          if boto_website and 'WebsiteConfiguration' in boto_website:
            website_config = boto_website['WebsiteConfiguration']
            cloud_api_bucket.website = apitools_messages.Bucket.WebsiteValue()
            if 'MainPageSuffix' in website_config:
              cloud_api_bucket.website.mainPageSuffix = (
                  website_config['MainPageSuffix'])
            if 'NotFoundPage' in website_config:
              cloud_api_bucket.website.notFoundPage = (
                  website_config['NotFoundPage'])
        except TRANSLATABLE_BOTO_EXCEPTIONS, e:
          self._TranslateExceptionAndRaise(e, bucket_name=bucket.name)
    if not fields or 'versioning' in fields:
      versioning = bucket_uri.get_versioning_config(headers=headers)
      if versioning:
        if (self.provider == 's3' and 'Versioning' in versioning and
            versioning['Versioning'] == 'Enabled'):
          cloud_api_bucket.versioning = (
              apitools_messages.Bucket.VersioningValue(enabled=True))
        elif self.provider == 'gs':
          cloud_api_bucket.versioning = (
              apitools_messages.Bucket.VersioningValue(enabled=True))

    # For S3 long bucket listing we do not support CORS, lifecycle, website, and
    # logging translation. The individual commands can be used to get
    # the XML equivalents for S3.
    return cloud_api_bucket

  def _BotoKeyToObject(self, key, fields=None):
    """Constructs an apitools Object from a boto key.

    Args:
      key: Boto key to construct Object from.
      fields: If present, construct the apitools Object with only this set of
              metadata fields.

    Returns:
      apitools Object corresponding to key.
    """
    custom_metadata = None
    if not fields or 'metadata' in fields:
      custom_metadata = self._TranslateBotoKeyCustomMetadata(key)
    cache_control = None
    if not fields or 'cacheControl' in fields:
      cache_control = getattr(key, 'cache_control', None)
    component_count = None
    if not fields or 'componentCount' in fields:
      component_count = getattr(key, 'component_count', None)
    content_disposition = None
    if not fields or 'contentDisposition' in fields:
      content_disposition = getattr(key, 'content_disposition', None)
    # Other fields like updated and ACL depend on the generation
    # of the object, so populate that regardless of whether it was requested.
    generation = self._TranslateBotoKeyGeneration(key)
    metageneration = None
    if not fields or 'metageneration' in fields:
      metageneration = self._TranslateBotoKeyMetageneration(key)
    updated = None
    # Translation code to avoid a dependency on dateutil.
    if not fields or 'updated' in fields:
      updated = self._TranslateBotoKeyTimestamp(key)
    etag = None
    if not fields or 'etag' in fields:
      etag = getattr(key, 'etag', None)
      if etag:
        etag = etag.strip('"\'')
    crc32c = None
    if not fields or 'crc32c' in fields:
      if hasattr(key, 'cloud_hashes') and 'crc32c' in key.cloud_hashes:
        crc32c = base64.encodestring(key.cloud_hashes['crc32c']).rstrip('\n')
    md5_hash = None
    if not fields or 'md5Hash' in fields:
      if hasattr(key, 'cloud_hashes') and 'md5' in key.cloud_hashes:
        md5_hash = base64.encodestring(key.cloud_hashes['md5']).rstrip('\n')
      elif self._GetMD5FromETag(getattr(key, 'etag', None)):
        md5_hash = base64.encodestring(
            binascii.unhexlify(self._GetMD5FromETag(key.etag))).rstrip('\n')
      elif self.provider == 's3':
        # S3 etags are MD5s for non-multi-part objects, but multi-part objects
        # (which include all objects >= 5GB) have a custom checksum
        # implementation that is not currently supported by gsutil.
        self.logger.warn('Non-MD5 etag (%s) present for key %s, data '
                         'integrity checks are not possible.' % (key.etag, key))

    # Serialize the boto key in the media link if it is requested.  This
    # way we can later access the key without adding an HTTP call.
    media_link = None
    if not fields or 'mediaLink' in fields:
      media_link = binascii.b2a_base64(
          pickle.dumps(key, pickle.HIGHEST_PROTOCOL))
    size = None
    if not fields or 'size' in fields:
      size = key.size or 0

    cloud_api_object = apitools_messages.Object(
        bucket=key.bucket.name,
        name=key.name,
        size=size,
        contentEncoding=key.content_encoding,
        contentLanguage=key.content_language,
        contentType=key.content_type,
        cacheControl=cache_control,
        contentDisposition=content_disposition,
        etag=etag,
        crc32c=crc32c,
        md5Hash=md5_hash,
        generation=generation,
        metageneration=metageneration,
        componentCount=component_count,
        updated=updated,
        metadata=custom_metadata,
        mediaLink=media_link)

    # Remaining functions amend cloud_api_object.
    self._TranslateDeleteMarker(key, cloud_api_object)
    if not fields or 'acl' in fields:
      generation_str = GenerationFromUrlAndString(
          StorageUrlFromString(self.provider), generation)
      self._TranslateBotoKeyAcl(key, cloud_api_object,
                                generation=generation_str)

    return cloud_api_object

  def _TranslateBotoKeyCustomMetadata(self, key):
    """Populates an apitools message from custom metadata in the boto key."""
    custom_metadata = None
    if getattr(key, 'metadata', None):
      custom_metadata = apitools_messages.Object.MetadataValue(
          additionalProperties=[])
      for k, v in key.metadata.iteritems():
        if k.lower() == 'content-language':
          # Work around content-language being inserted into custom metadata.
          continue
        custom_metadata.additionalProperties.append(
            apitools_messages.Object.MetadataValue.AdditionalProperty(
                key=k, value=v))
    return custom_metadata

  def _TranslateBotoKeyGeneration(self, key):
    """Returns the generation/version_id number from the boto key if present."""
    generation = None
    if self.provider == 'gs':
      if getattr(key, 'generation', None):
        generation = long(key.generation)
    elif self.provider == 's3':
      if getattr(key, 'version_id', None):
        generation = EncodeStringAsLong(key.version_id)
    return generation

  def _TranslateBotoKeyMetageneration(self, key):
    """Returns the metageneration number from the boto key if present."""
    metageneration = None
    if self.provider == 'gs':
      if getattr(key, 'metageneration', None):
        metageneration = long(key.metageneration)
    return metageneration

  def _TranslateBotoKeyTimestamp(self, key):
    """Parses the timestamp from the boto key into an datetime object.

    This avoids a dependency on dateutil.

    Args:
      key: Boto key to get timestamp from.

    Returns:
      datetime object if string is parsed successfully, None otherwise.
    """
    if key.last_modified:
      if '.' in key.last_modified:
        key_us_timestamp = key.last_modified.rstrip('Z') + '000Z'
      else:
        key_us_timestamp = key.last_modified.rstrip('Z') + '.000000Z'
      fmt = '%Y-%m-%dT%H:%M:%S.%fZ'
      try:
        return datetime.datetime.strptime(key_us_timestamp, fmt)
      except ValueError:
        try:
          # Try alternate format
          fmt = '%a, %d %b %Y %H:%M:%S %Z'
          return datetime.datetime.strptime(key.last_modified, fmt)
        except ValueError:
          # Could not parse the time; leave updated as None.
          return None

  def _TranslateDeleteMarker(self, key, cloud_api_object):
    """Marks deleted objects with a metadata value (for S3 compatibility)."""
    if isinstance(key, DeleteMarker):
      if not cloud_api_object.metadata:
        cloud_api_object.metadata = apitools_messages.Object.MetadataValue()
        cloud_api_object.metadata.additionalProperties = []
      cloud_api_object.metadata.additionalProperties.append(
          apitools_messages.Object.MetadataValue.AdditionalProperty(
              key=S3_DELETE_MARKER_GUID, value=True))

  def _TranslateBotoKeyAcl(self, key, cloud_api_object, generation=None):
    """Updates cloud_api_object with the ACL from the boto key."""
    storage_uri_for_key = self._StorageUriForObject(key.bucket.name, key.name,
                                                    generation=generation)
    headers = {}
    self._AddApiVersionToHeaders(headers)
    try:
      if self.provider == 'gs':
        key_acl = storage_uri_for_key.get_acl(headers=headers)
        # key.get_acl() does not support versioning so we need to use
        # storage_uri to ensure we're getting the versioned ACL.
        for acl in AclTranslation.BotoObjectAclToMessage(key_acl):
          cloud_api_object.acl.append(acl)
      if self.provider == 's3':
        key_acl = key.get_xml_acl(headers=headers)
        # ACLs for s3 are different and we use special markers to represent
        # them in the gsutil Cloud API.
        AddS3MarkerAclToObjectMetadata(cloud_api_object, key_acl)
    except boto.exception.GSResponseError, e:
      if e.status == 403:
        # Consume access denied exceptions to mimic JSON behavior of simply
        # returning None if sufficient permission is not present.  The caller
        # needs to handle the case where the ACL is not populated.
        pass
      else:
        raise

  def _TranslateExceptionAndRaise(self, e, bucket_name=None, object_name=None,
                                  generation=None):
    """Translates a Boto exception and raises the translated or original value.

    Args:
      e: Any Exception.
      bucket_name: Optional bucket name in request that caused the exception.
      object_name: Optional object name in request that caused the exception.
      generation: Optional generation in request that caused the exception.

    Raises:
      Translated CloudApi exception, or the original exception if it was not
      translatable.
    """
    translated_exception = self._TranslateBotoException(
        e, bucket_name=bucket_name, object_name=object_name,
        generation=generation)
    if translated_exception:
      raise translated_exception
    else:
      raise

  def _TranslateBotoException(self, e, bucket_name=None, object_name=None,
                              generation=None):
    """Translates boto exceptions into their gsutil Cloud API equivalents.

    Args:
      e: Any exception in TRANSLATABLE_BOTO_EXCEPTIONS.
      bucket_name: Optional bucket name in request that caused the exception.
      object_name: Optional object name in request that caused the exception.
      generation: Optional generation in request that caused the exception.

    Returns:
      CloudStorageApiServiceException for translatable exceptions, None
      otherwise.

    Because we're using isinstance, check for subtypes first.
    """
    if isinstance(e, boto.exception.StorageResponseError):
      if e.status == 400:
        return BadRequestException(e.code, status=e.status, body=e.body)
      elif e.status == 401 or e.status == 403:
        return AccessDeniedException(e.code, status=e.status, body=e.body)
      elif e.status == 404:
        if bucket_name:
          if object_name:
            return CreateObjectNotFoundException(e.status, self.provider,
                                                 bucket_name, object_name,
                                                 generation=generation)
          return CreateBucketNotFoundException(e.status, self.provider,
                                               bucket_name)
        return NotFoundException(e.code, status=e.status, body=e.body)
      elif e.status == 409 and e.code and 'BucketNotEmpty' in e.code:
        return NotEmptyException('BucketNotEmpty (%s)' % bucket_name,
                                 status=e.status, body=e.body)
      elif e.status == 412:
        return PreconditionException(e.code, status=e.status, body=e.body)
    if isinstance(e, boto.exception.StorageCreateError):
      return ServiceException('Bucket already exists.', status=e.status,
                              body=e.body)

    if isinstance(e, boto.exception.BotoServerError):
      return ServiceException(e.message, status=e.status, body=e.body)

    if isinstance(e, boto.exception.InvalidUriError):
      # Work around textwrap when searching for this string.
      if e.message and NON_EXISTENT_OBJECT_REGEX.match(e.message.encode(UTF8)):
        return NotFoundException(e.message, status=404)
      return InvalidUrlError(e.message)

    if isinstance(e, boto.exception.ResumableUploadException):
      if (e.disposition == boto.exception.ResumableTransferDisposition.ABORT or
          (e.disposition ==
           boto.exception.ResumableTransferDisposition.START_OVER)):
        return ResumableUploadAbortException(e.message)
      else:
        return ResumableUploadException(e.message)

    if isinstance(e, boto.exception.ResumableDownloadException):
      return ResumableDownloadException(e.message)

    return None

  # For function docstrings, see CloudApiDelegator class.
  def XmlPassThroughGetAcl(self, uri_string, def_obj_acl=False):
    """See CloudApiDelegator class for function doc strings."""
    try:
      uri = boto.storage_uri(
          uri_string, suppress_consec_slashes=False,
          bucket_storage_uri_class=self.bucket_storage_uri_class,
          debug=self.debug)
      if def_obj_acl:
        return uri.get_def_acl()
      else:
        return uri.get_acl()
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e)

  def XmlPassThroughSetAcl(self, acl_text, uri_string, canned=True,
                           def_obj_acl=False):
    """See CloudApiDelegator class for function doc strings."""
    try:
      uri = boto.storage_uri(
          uri_string, suppress_consec_slashes=False,
          bucket_storage_uri_class=self.bucket_storage_uri_class,
          debug=self.debug)
      if canned:
        if def_obj_acl:
          canned_acls = uri.canned_acls()
          if acl_text not in canned_acls:
            raise CommandException('Invalid canned ACL "%s".' % acl_text)
          uri.set_def_acl(acl_text, uri.object_name)
        else:
          canned_acls = uri.canned_acls()
          if acl_text not in canned_acls:
            raise CommandException('Invalid canned ACL "%s".' % acl_text)
          uri.set_acl(acl_text, uri.object_name)
      else:
        if def_obj_acl:
          uri.set_def_xml_acl(acl_text, uri.object_name)
        else:
          uri.set_xml_acl(acl_text, uri.object_name)
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e)

  def XmlPassThroughSetCors(self, cors_text, uri_string):
    """See CloudApiDelegator class for function doc strings."""
    # Parse XML document and convert into Cors object.
    cors_obj = Cors()
    h = handler.XmlHandler(cors_obj, None)
    try:
      xml.sax.parseString(cors_text, h)
    except SaxExceptions.SAXParseException, e:
      raise CommandException('Requested CORS is invalid: %s at line %s, '
                             'column %s' % (e.getMessage(), e.getLineNumber(),
                                            e.getColumnNumber()))

    try:
      uri = boto.storage_uri(
          uri_string, suppress_consec_slashes=False,
          bucket_storage_uri_class=self.bucket_storage_uri_class,
          debug=self.debug)
      uri.set_cors(cors_obj, False)
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e)

  def XmlPassThroughGetCors(self, uri_string):
    """See CloudApiDelegator class for function doc strings."""
    uri = boto.storage_uri(
        uri_string, suppress_consec_slashes=False,
        bucket_storage_uri_class=self.bucket_storage_uri_class,
        debug=self.debug)
    try:
      cors = uri.get_cors(False)
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e)

    parsed_xml = xml.dom.minidom.parseString(cors.to_xml().encode(UTF8))
    # Pretty-print the XML to make it more easily human editable.
    return parsed_xml.toprettyxml(indent='    ')

  def XmlPassThroughGetLifecycle(self, uri_string):
    """See CloudApiDelegator class for function doc strings."""
    try:
      uri = boto.storage_uri(
          uri_string, suppress_consec_slashes=False,
          bucket_storage_uri_class=self.bucket_storage_uri_class,
          debug=self.debug)
      lifecycle = uri.get_lifecycle_config(False)
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e)

    parsed_xml = xml.dom.minidom.parseString(lifecycle.to_xml().encode(UTF8))
    # Pretty-print the XML to make it more easily human editable.
    return parsed_xml.toprettyxml(indent='    ')

  def XmlPassThroughSetLifecycle(self, lifecycle_text, uri_string):
    """See CloudApiDelegator class for function doc strings."""
    # Parse XML document and convert into lifecycle object.
    lifecycle_obj = LifecycleConfig()
    h = handler.XmlHandler(lifecycle_obj, None)
    try:
      xml.sax.parseString(lifecycle_text, h)
    except SaxExceptions.SAXParseException, e:
      raise CommandException(
          'Requested lifecycle config is invalid: %s at line %s, column %s' %
          (e.getMessage(), e.getLineNumber(), e.getColumnNumber()))

    try:
      uri = boto.storage_uri(
          uri_string, suppress_consec_slashes=False,
          bucket_storage_uri_class=self.bucket_storage_uri_class,
          debug=self.debug)
      uri.configure_lifecycle(lifecycle_obj, False)
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e)

  def XmlPassThroughGetLogging(self, uri_string):
    """See CloudApiDelegator class for function doc strings."""
    try:
      uri = boto.storage_uri(
          uri_string, suppress_consec_slashes=False,
          bucket_storage_uri_class=self.bucket_storage_uri_class,
          debug=self.debug)
      logging_config_xml = UnaryDictToXml(uri.get_logging_config())
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e)

    return XmlParseString(logging_config_xml).toprettyxml()

  def XmlPassThroughGetWebsite(self, uri_string):
    """See CloudApiDelegator class for function doc strings."""
    try:
      uri = boto.storage_uri(
          uri_string, suppress_consec_slashes=False,
          bucket_storage_uri_class=self.bucket_storage_uri_class,
          debug=self.debug)
      web_config_xml = UnaryDictToXml(uri.get_website_config())
    except TRANSLATABLE_BOTO_EXCEPTIONS, e:
      self._TranslateExceptionAndRaise(e)

    return XmlParseString(web_config_xml).toprettyxml()
