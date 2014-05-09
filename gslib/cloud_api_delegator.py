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
"""Gsutil API delegator for interacting with cloud storage providers."""

import boto
from boto import config
from gslib.cloud_api import ArgumentException
from gslib.cloud_api import CloudApi
from gslib.cs_api_map import ApiMapConstants
from gslib.cs_api_map import ApiSelector


class CloudApiDelegator(CloudApi):
  """Class that handles delegating requests to gsutil Cloud API implementations.

  This class is responsible for determining at runtime which gsutil Cloud API
  implementation should service the request based on the Cloud storage provider,
  command-level API support, and configuration file override.

  During initialization it takes as an argument a gsutil_api_map which maps
  providers to their default and supported gsutil Cloud API implementations
  (see comments in cs_api_map for details).

  Instantiation of multiple delegators per-thread is required for multiprocess
  and/or multithreaded operations. Calling methods on the same delegator in
  multiple threads is unsafe.
  """

  def __init__(self, bucket_storage_uri_class, gsutil_api_map, logger,
               provider=None, debug=0):
    """Performs necessary setup for delegating cloud storage requests.

    This function has different arguments than the gsutil Cloud API __init__
    function because of the delegation responsibilties of this class.

    Args:
      bucket_storage_uri_class: boto storage_uri class, used by APIs that
                                provide boto translation or mocking.
      gsutil_api_map: Map of providers and API selector tuples to api classes
                      which can be used to communicate with those providers.
      logger: logging.logger for outputting log messages.
      provider: Default provider prefix describing cloud storage provider to
                connect to.
      debug: Debug level for the API implementation (0..3).
    """
    super(CloudApiDelegator, self).__init__(bucket_storage_uri_class, logger,
                                            provider=provider, debug=debug)
    self.api_map = gsutil_api_map
    self.prefer_api = boto.config.get('GSUtil', 'prefer_api', '').upper()
    self.loaded_apis = {}

    if not self.api_map[ApiMapConstants.API_MAP]:
      raise ArgumentException('No apiclass supplied for gsutil Cloud API map.')

  def _GetApi(self, provider):
    """Returns a valid CloudApi for use by the caller.

    This function lazy-loads connection and credentials using the API map
    and credential store provided during class initialization.

    Args:
      provider: Provider to load API for. If None, class-wide default is used.

    Raises:
      ArgumentException if there is no matching API available in the API map.

    Returns:
      Valid API instance that can be used to communicate with the Cloud
      Storage provider.
    """
    provider = provider or self.provider
    if not provider:
      raise ArgumentException('No provider selected for _GetApi')

    provider = str(provider)

    if provider not in self.loaded_apis:
      self.loaded_apis[provider] = {}

    api_selector = self.GetApiSelector(provider)

    if api_selector not in self.loaded_apis[provider]:
      # Need to load the API.
      self._LoadApi(provider, api_selector)

    return self.loaded_apis[provider][api_selector]

  def _LoadApi(self, provider, api_selector):
    """Loads a CloudApi into the loaded_apis map for this class.

    Args:
      provider: Provider to load the API for.
      api_selector: cs_api_map.ApiSelector defining the API type.
    """
    if provider not in self.api_map[ApiMapConstants.API_MAP]:
      raise ArgumentException(
          'gsutil Cloud API map contains no entry for provider %s.' % provider)
    if api_selector not in self.api_map[ApiMapConstants.API_MAP][provider]:
      raise ArgumentException(
          'gsutil Cloud API map does not support API %s for provider %s.' %
          (api_selector, provider))
    self.loaded_apis[provider][api_selector] = (
        self.api_map[ApiMapConstants.API_MAP][provider][api_selector](
            self.bucket_storage_uri_class,
            self.logger,
            provider=provider,
            debug=self.debug))

  def GetApiSelector(self, provider=None):
    """Returns a cs_api_map.ApiSelector based on input and configuration.

    Args:
      provider: Provider to return the ApiSelector for.  If None, class-wide
                default is used.

    Returns:
      cs_api_map.ApiSelector that will be used for calls to the delegator
      for this provider.
    """
    selected_provider = provider or self.provider
    if not selected_provider:
      raise ArgumentException('No provider selected for CloudApi')

    if (selected_provider not in self.api_map[ApiMapConstants.DEFAULT_MAP] or
        self.api_map[ApiMapConstants.DEFAULT_MAP][selected_provider] not in
        self.api_map[ApiMapConstants.API_MAP][selected_provider]):
      raise ArgumentException('No default api available for provider %s' %
                              selected_provider)

    if selected_provider not in self.api_map[ApiMapConstants.SUPPORT_MAP]:
      raise ArgumentException('No supported apis available for provider %s' %
                              selected_provider)

    api = self.api_map[ApiMapConstants.DEFAULT_MAP][selected_provider]

    # If we have only HMAC credentials for Google Cloud Storage, we must use
    # the XML API as the JSON API does not support HMAC.
    #
    # Technically if we have only HMAC credentials, we should still be able to
    # access public read resources via the JSON API, but the XML API can do
    # that just as well. It is better to use it than inspect the credentials on
    # every HTTP call.
    if (provider == 'gs' and
        not config.has_option('Credentials', 'gs_oauth2_refresh_token') and
        not (config.has_option('Credentials', 'gs_service_client_id')
             and config.has_option('Credentials', 'gs_service_key_file')) and
        (config.has_option('Credentials', 'gs_access_key_id')
         and config.has_option('Credentials', 'gs_secret_access_key'))):
      api = ApiSelector.XML
    # Try to force the user's preference to a supported API.
    elif self.prefer_api in (self.api_map[ApiMapConstants.SUPPORT_MAP]
                             [selected_provider]):
      api = self.prefer_api
    return api

  # For function docstrings, see CloudApi class.
  def GetBucket(self, bucket_name, provider=None, fields=None):
    return self._GetApi(provider).GetBucket(bucket_name, fields=fields)

  def ListBuckets(self, project_id=None, provider=None, fields=None):
    return self._GetApi(provider).ListBuckets(project_id=project_id,
                                              fields=fields)

  def PatchBucket(self, bucket_name, metadata, preconditions=None,
                  provider=None, fields=None):
    return self._GetApi(provider).PatchBucket(
        bucket_name, metadata, preconditions=preconditions, fields=fields)

  def CreateBucket(self, bucket_name, project_id=None, metadata=None,
                   provider=None, fields=None):
    return self._GetApi(provider).CreateBucket(
        bucket_name, project_id=project_id, metadata=metadata, fields=fields)

  def DeleteBucket(self, bucket_name, preconditions=None, provider=None):
    return self._GetApi(provider).DeleteBucket(bucket_name,
                                               preconditions=preconditions)

  def ListObjects(self, bucket_name, prefix=None, delimiter=None,
                  all_versions=None, provider=None, fields=None):
    return self._GetApi(provider).ListObjects(
        bucket_name, prefix=prefix, delimiter=delimiter,
        all_versions=all_versions, fields=fields)

  def GetObjectMetadata(self, bucket_name, object_name, generation=None,
                        provider=None, fields=None):
    return self._GetApi(provider).GetObjectMetadata(
        bucket_name, object_name, generation=generation, fields=fields)

  def PatchObjectMetadata(self, bucket_name, object_name, metadata,
                          generation=None, preconditions=None, provider=None,
                          fields=None):
    return self._GetApi(provider).PatchObjectMetadata(
        bucket_name, object_name, metadata, generation=generation,
        preconditions=preconditions, fields=fields)

  def GetObjectMedia(
      self, bucket_name, object_name, download_stream, provider=None,
      generation=None, object_size=None,
      download_strategy=CloudApi.DownloadStrategy.ONE_SHOT,
      start_byte=0, end_byte=None, progress_callback=None,
      serialization_data=None, digesters=None):
    return self._GetApi(provider).GetObjectMedia(
        bucket_name, object_name, download_stream,
        download_strategy=download_strategy, start_byte=start_byte,
        end_byte=end_byte, generation=generation, object_size=object_size,
        progress_callback=progress_callback,
        serialization_data=serialization_data, digesters=digesters)

  def UploadObject(self, upload_stream, object_metadata, size=None,
                   canned_acl=None, preconditions=None, provider=None,
                   fields=None):
    return self._GetApi(provider).UploadObject(
        upload_stream, object_metadata, size=size, canned_acl=canned_acl,
        preconditions=preconditions, fields=fields)

  def UploadObjectStreaming(self, upload_stream, object_metadata,
                            canned_acl=None, preconditions=None, provider=None,
                            fields=None):
    return self._GetApi(provider).UploadObjectStreaming(
        upload_stream, object_metadata, canned_acl=canned_acl,
        preconditions=preconditions, fields=fields)

  def UploadObjectResumable(
      self, upload_stream, object_metadata, canned_acl=None, preconditions=None,
      provider=None, fields=None, size=None, serialization_data=None,
      tracker_callback=None, progress_callback=None):
    return self._GetApi(provider).UploadObjectResumable(
        upload_stream, object_metadata, canned_acl=canned_acl,
        preconditions=preconditions, size=size, fields=fields,
        serialization_data=serialization_data,
        tracker_callback=tracker_callback, progress_callback=progress_callback)

  def CopyObject(self, src_bucket_name, src_obj_name, dst_obj_metadata,
                 src_generation=None, canned_acl=None, preconditions=None,
                 provider=None, fields=None):
    return self._GetApi(provider).CopyObject(
        src_bucket_name, src_obj_name, dst_obj_metadata,
        src_generation=src_generation, canned_acl=canned_acl,
        preconditions=preconditions, fields=fields)

  def ComposeObject(self, src_objs_metadata, dst_obj_metadata,
                    preconditions=None, provider=None, fields=None):
    return self._GetApi(provider).ComposeObject(
        src_objs_metadata, dst_obj_metadata, preconditions=preconditions,
        fields=fields)

  def DeleteObject(self, bucket_name, object_name, preconditions=None,
                   generation=None, provider=None):
    return self._GetApi(provider).DeleteObject(
        bucket_name, object_name, preconditions=preconditions,
        generation=generation)

  def WatchBucket(self, bucket_name, address, channel_id, token=None,
                  provider=None, fields=None):
    return self._GetApi(provider).WatchBucket(
        bucket_name, address, channel_id, token=token, fields=fields)

  def StopChannel(self, channel_id, resource_id, provider=None):
    return self._GetApi(provider).StopChannel(channel_id, resource_id)

  def XmlPassThroughGetAcl(self, uri_string, def_obj_acl=False, provider=None):
    """XML compatibility function for getting ACLs.

    Args:
      uri_string: String describing bucket or object to get the ACL for.
      def_obj_acl: If true, get the default object ACL on a bucket.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      ACL XML for the resource specified by uri_string.
    """
    return self._GetApi(provider).XmlPassThroughGetAcl(uri_string,
                                                       def_obj_acl=def_obj_acl)

  def XmlPassThroughSetAcl(self, acl_text, uri_string, canned=True,
                           def_obj_acl=False, provider=None):
    """XML compatibility function for setting ACLs.

    Args:
      acl_text: XML ACL or canned ACL string.
      uri_string: String describing bucket or object to set the ACL on.
      canned: If true, acl_text is treated as a canned ACL string.
      def_obj_acl: If true, set the default object ACL on a bucket.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      None.
    """
    self._GetApi(provider).XmlPassThroughSetAcl(
        acl_text, uri_string, canned=canned, def_obj_acl=def_obj_acl)

  def XmlPassThroughGetCors(self, uri_string, provider=None):
    """XML compatibility function for getting CORS configuration on a bucket.

    Args:
      uri_string: String describing bucket to retrieve CORS configuration for.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      CORS configuration XML for the bucket specified by uri_string.
    """
    return self._GetApi(provider).XmlPassThroughGetCors(uri_string)

  def XmlPassThroughSetCors(self, cors_text, uri_string, provider=None):
    """XML compatibility function for setting CORS configuration on a bucket.

    Args:
      cors_text: Raw CORS XML string.
      uri_string: String describing bucket to set the CORS configuration on.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      None.
    """
    self._GetApi(provider).XmlPassThroughSetCors(cors_text, uri_string)

  def XmlPassThroughGetLifecycle(self, uri_string,
                                 provider=None):
    """XML compatibility function for getting lifecycle config on a bucket.

    Args:
      uri_string: String describing bucket to retrieve lifecycle
                  configuration for.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      Lifecycle configuration XML for the bucket specified by uri_string.
    """
    return self._GetApi(provider).XmlPassThroughGetLifecycle(uri_string)

  def XmlPassThroughSetLifecycle(self, lifecycle_text, uri_string,
                                 provider=None):
    """XML compatibility function for setting CORS configuration on a bucket.

    Args:
      lifecycle_text: Raw lifecycle configuration XML string.
      uri_string: String describing bucket to set the lifecycle configuration
                  on.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      None.
    """
    self._GetApi(provider).XmlPassThroughSetLifecycle(lifecycle_text,
                                                      uri_string)

  def XmlPassThroughGetLogging(self, uri_string, provider=None):
    """XML compatibility function for getting logging configuration on a bucket.

    Args:
      uri_string: String describing bucket to retrieve logging
                  configuration for.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      Logging configuration XML for the bucket specified by uri_string.
    """
    return self._GetApi(provider).XmlPassThroughGetLogging(uri_string)

  def XmlPassThroughGetWebsite(self, uri_string, provider=None):
    """XML compatibility function for getting website configuration on a bucket.

    Args:
      uri_string: String describing bucket to retrieve website
                  configuration for.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      Website configuration XML for the bucket specified by uri_string.
    """
    return self._GetApi(provider).XmlPassThroughGetWebsite(uri_string)

