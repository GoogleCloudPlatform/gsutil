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
"""Gsutil API for interacting with cloud storage providers."""


class CloudApi(object):
  """Abstract base class for interacting with cloud storage providers.

  Implementations of the gsutil Cloud API are not guaranteed to be thread-safe.
  Behavior when calling a gsutil Cloud API instance simultaneously across
  threads is undefined and doing so will likely cause errors. Therefore,
  a separate instance of the gsutil Cloud API should be instantiated per-thread.
  """

  def __init__(self, bucket_storage_uri_class, logger, provider=None, debug=0):
    """Performs necessary setup for interacting with the cloud storage provider.

    Args:
      bucket_storage_uri_class: boto storage_uri class, used by APIs that
                                provide boto translation or mocking.
      logger: logging.logger for outputting log messages.
      provider: Default provider prefix describing cloud storage provider to
                connect to.
      debug: Debug level for the API implementation (0..3).
    """
    self.bucket_storage_uri_class = bucket_storage_uri_class
    self.logger = logger
    self.provider = provider
    self.debug = debug

  def GetBucket(self, bucket_name, provider=None, fields=None):
    """Gets Bucket metadata.

    Args:
      bucket_name: Name of the bucket.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.
      fields: If present, return only these Bucket metadata fields, for
              example, ['logging', 'defaultObjectAcl']

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      Bucket object.
    """
    raise NotImplementedError('GetBucket must be overloaded')

  def ListBuckets(self, project_id=None, provider=None, fields=None):
    """Lists bucket metadata for the given project.

    Args:
      project_id: Project owning the buckets, default from config if None.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.
      fields: If present, return only these metadata fields for the listing,
              for example:
              ['items/logging', 'items/defaultObjectAcl'].
              Note that the WildcardIterator class should be used to list
              buckets instead of calling this function directly.  It amends
              the fields definition from get-like syntax such as
              ['logging', 'defaultObjectAcl'] so that the caller does not
              need to prepend 'items/' or specify fields necessary for listing
              (like nextPageToken).

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      Iterator over Bucket objects.
    """
    raise NotImplementedError('ListBuckets must be overloaded')

  def PatchBucket(self, bucket_name, metadata, preconditions=None,
                  provider=None, fields=None):
    """Updates bucket metadata for the bucket with patch semantics.

    Args:
      bucket_name: Name of bucket to update.
      metadata: Bucket object defining metadata to be updated.
      preconditions: Preconditions for the request.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.
      fields: If present, return only these Bucket metadata fields.

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      Bucket object describing new bucket metadata.
    """
    raise NotImplementedError('PatchBucket must be overloaded')

  def CreateBucket(self, bucket_name, project_id=None, metadata=None,
                   provider=None, fields=None):
    """Creates a new bucket with the specified metadata.

    Args:
      bucket_name: Name of the new bucket.
      project_id: Project owner of the new bucket, default from config if None.
      metadata: Bucket object defining new bucket metadata.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.
      fields: If present, return only these Bucket metadata fields.

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      Bucket object describing new bucket metadata.
    """
    raise NotImplementedError('CreateBucket must be overloaded')

  def DeleteBucket(self, bucket_name, preconditions=None, provider=None):
    """Deletes a bucket.

    Args:
      bucket_name: Name of the bucket to delete.
      preconditions: Preconditions for the request.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      None.
    """
    raise NotImplementedError('DeleteBucket must be overloaded')

  class CsObjectOrPrefixType(object):
    """Enum class for describing CsObjectOrPrefix types."""
    OBJECT = 'object'  # Cloud object
    PREFIX = 'prefix'  # Cloud bucket subdirectory

  class CsObjectOrPrefix(object):
    """Container class for ListObjects results."""

    def __init__(self, data, datatype):
      """Stores a ListObjects result.

      Args:
        data: Root object, either an apitools Object or a string Prefix.
        datatype: CsObjectOrPrefixType of data.
      """
      self.data = data
      self.datatype = datatype

  def ListObjects(self, bucket_name, prefix=None, delimiter=None,
                  all_versions=None, provider=None, fields=None):
    """Lists objects (with metadata) and prefixes in a bucket.

    Args:
      bucket_name: Bucket containing the objects.
      prefix: Prefix for directory-like behavior.
      delimiter: Delimiter for directory-like behavior.
      all_versions: If true, list all object versions.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.
      fields: If present, return only these metadata fields for the listing,
              for example:
              ['items/acl', 'items/updated', 'prefixes'].
              Note that the WildcardIterator class should be used to list
              objects instead of calling this function directly.  It amends
              the fields definition from get-like syntax such as
              ['acl', 'updated'] so that the caller does not need to
              prepend 'items/' or specify any fields necessary for listing
              (such as prefixes or nextPageToken).

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      Iterator over CsObjectOrPrefix wrapper class.
    """
    raise NotImplementedError('ListObjects must be overloaded')

  def GetObjectMetadata(self, bucket_name, object_name, generation=None,
                        provider=None, fields=None):
    """Gets object metadata.

    Args:
      bucket_name: Bucket containing the object.
      object_name: Object name.
      generation: Generation of the object to retrieve.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.
      fields: If present, return only these Object metadata fields, for
              example, ['acl', 'updated'].

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      Object object.
    """
    raise NotImplementedError('GetObjectMetadata must be overloaded')

  def PatchObjectMetadata(self, bucket_name, object_name, metadata,
                          generation=None, preconditions=None, provider=None,
                          fields=None):
    """Updates object metadata with patch semantics.

    Args:
      bucket_name: Bucket containing the object.
      object_name: Object name for object.
      metadata: Object object defining metadata to be updated.
      generation: Generation (or version) of the object to update.
      preconditions: Preconditions for the request.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.
      fields: If present, return only these Object metadata fields.

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      Updated object metadata.
    """
    raise NotImplementedError('PatchObjectMetadata must be overloaded')

  class DownloadStrategy(object):
    """Enum class for specifying download strategy."""
    ONE_SHOT = 'oneshot'
    RESUMABLE = 'resumable'

  def GetObjectMedia(self, bucket_name, object_name, download_stream,
                     provider=None, generation=None,
                     download_strategy=DownloadStrategy.ONE_SHOT, start_byte=0,
                     end_byte=None, progress_callback=None,
                     serialization_data=None, digesters=None):
    """Gets object data.

    Args:
      bucket_name: Bucket containing the object.
      object_name: Object name.
      download_stream: Stream to send the object data to.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.
      generation: Generation of the object to retrieve.
      download_strategy: Cloud API download strategy to use for download.
      start_byte: Starting point for download (for resumable downloads and
                  range requests). Can be set to negative to request a range
                  of bytes (python equivalent of [:-3])
      end_byte: Ending point for download (for range requests).
      progress_callback: Optional callback function for progress notifications.
                         Receives calls with arguments
                         (bytes_transferred, total_size).
      serialization_data: Implementation-specific dict containing serialization
                          information for the download.
      digesters: Dict of {string : digester}, where string is a name of a hash
                 algorithm, and digester is a validation digester that supports
                 update(bytes) and digest() using that algorithm.
                 Implementation can set the digester value to None to indicate
                 bytes were not successfully digested on-the-fly.

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.
    """
    raise NotImplementedError('GetObjectMedia must be overloaded')

  def UploadObject(self, upload_stream, object_metadata, size=None,
                   preconditions=None, provider=None, fields=None):
    """Uploads object data and metadata.

    Args:
      upload_stream: Seekable stream of object data.
      object_metadata: Object metadata for new object.  Must include bucket
                       and object name.
      size: Optional object size.
      preconditions: Preconditions for the request.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.
      fields: If present, return only these Object metadata fields.

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      Object object for newly created destination object.
    """
    raise NotImplementedError('UploadObject must be overloaded')

  def UploadObjectStreaming(self, upload_stream, object_metadata,
                            preconditions=None, provider=None, fields=None):
    """Uploads object data and metadata.

    Args:
      upload_stream: Stream of object data. May not be seekable.
      object_metadata: Object metadata for new object.  Must include bucket
                       and object name.
      preconditions: Preconditions for the request.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.
      fields: If present, return only these Object metadata fields.

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      Object object for newly created destination object.
    """
    raise NotImplementedError('UploadObject must be overloaded')

  def UploadObjectResumable(
      self, upload_stream, object_metadata, preconditions=None, size=None,
      serialization_data=None, tracker_callback=None, progress_callback=None,
      provider=None, fields=None):
    """Uploads object data and metadata using a resumable upload strategy.

    Args:
      upload_stream: Seekable stream of object data.
      object_metadata: Object metadata for new object.  Must include bucket
                       and object name.
      preconditions: Preconditions for the request.
      size: Total size of the object.
      serialization_data: Dict of {'url' : UploadURL} allowing for uploads to
                          be resumed.
      tracker_callback: Callback function taking a upload URL string.
                        Guaranteed to be called when the implementation gets an
                        upload URL, allowing the caller to resume the upload
                        across process breaks by saving the upload URL in
                        a tracker file.
      progress_callback: Optional callback function for progress notifications.
                         Receives calls with arguments
                         (bytes_transferred, total_size).
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.
      fields: If present, return only these Object metadata fields when the
              upload is complete.

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      Object object for newly created destination object.
    """
    raise NotImplementedError('UploadObjectResumable must be overloaded')

  def CopyObject(self, src_bucket_name, src_obj_name, dst_obj_metadata,
                 src_generation=None, preconditions=None, provider=None,
                 fields=None):
    """Copies an object in the cloud.

    Args:
      src_bucket_name: Bucket containing the source object
      src_obj_name: Name of the source object.
      dst_obj_metadata: Object metadata for new object.  Must include bucket
                        and object name.
      src_generation: Generation of the source object to copy.
      preconditions: Destination object preconditions for the request.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.
      fields: If present, return only these Object metadata fields..

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      Object object for newly created destination object.
    """
    raise NotImplementedError('CopyObject must be overloaded')

  def ComposeObject(self, src_objs_metadata, dst_obj_metadata,
                    preconditions=None, provider=None, fields=None):
    """Composes an object in the cloud.

    Args:
      src_objs_metadata: List of ComposeRequest.SourceObjectsValueListEntries
                         specifying the objects to compose.
      dst_obj_metadata: Metadata for the destination object including bucket
                        and object name.
      preconditions: Destination object preconditions for the request.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.
      fields: If present, return only these Object metadata fields..

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      Composed object metadata.
    """
    raise NotImplementedError('ComposeObject must be overloaded')

  def DeleteObject(self, bucket_name, object_name, preconditions=None,
                   generation=None, provider=None):
    """Deletes an object.

    Args:
      bucket_name: Name of the containing bucket.
      object_name: Name of the object to delete.
      preconditions: Preconditions for the request.
      generation: Generation (or version) of the object to delete; if None,
                  deletes the live object.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      None.
    """
    raise NotImplementedError('DeleteObject must be overloaded')

  def WatchBucket(self, bucket_name, address, channel_id, token=None,
                  provider=None, fields=None):
    """Creates a notification subscription for changes to objects in a bucket.

    Args:
      bucket_name: Bucket containing the objects.
      address: Address to which to send notifications.
      channel_id: Unique ID string for the channel.
      token: If present, token string is delivered with each notification.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.
      fields: If present, return only these Channel metadata fields.

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      Channel object describing the notification subscription.
    """
    raise NotImplementedError('WatchBucket must be overloaded')

  def StopChannel(self, channel_id, resource_id, provider=None):
    """Stops a notification channel.

    Args:
      channel_id: Unique ID string for the channel.
      resource_id: Version-agnostic ID string for the channel.
      provider: Cloud storage provider to connect to.  If not present,
                class-wide default is used.

    Raises:
      ArgumentException for errors during input validation.
      ServiceException for errors interacting with cloud storage providers.

    Returns:
      None.
    """
    raise NotImplementedError('StopChannel must be overloaded')


class Preconditions(object):
  """Preconditions class for specifying preconditions to cloud API requests."""

  def __init__(self, gen_match=None, meta_gen_match=None):
    """Instantiates a Preconditions object.

    Args:
      gen_match: Perform request only if generation of target object
                 matches the given integer. Ignored for bucket requests.
      meta_gen_match: Perform request only if metageneration of target
                      object/bucket matches the given integer.
    """
    self.gen_match = gen_match
    self.meta_gen_match = meta_gen_match


class ArgumentException(Exception):
  """Exception raised when arguments to a Cloud API method are invalid.

    This exception is never raised as a result of a failed call to a cloud
    storage provider.
  """

  def __init__(self, reason):
    Exception.__init__(self)
    self.reason = reason

  def __repr__(self):
    return str(self)

  def __str__(self):
    return '%s: %s' % (self.__class__.__name__, self.reason)


class ProjectIdException(ArgumentException):
  """Exception raised when a Project ID argument is required but not present."""


class ServiceException(Exception):
  """Exception raised when a cloud storage provider request fails.

    This exception is raised only as a result of a failed remote call.
  """

  def __init__(self, reason, status=None, body=None):
    Exception.__init__(self)
    self.reason = reason
    self.status = status
    self.body = body

  def __repr__(self):
    return str(self)

  def __str__(self):
    message = '%s:' % self.__class__.__name__
    if self.status:
      message += ' %s' % self.status
    message += ' %s' % self.reason
    if self.body:
      message += '\n%s' % self.body
    return message


class RetryableServiceException(ServiceException):
  """Exception class for retryable exceptions."""


class ResumableDownloadException(RetryableServiceException):
  """Exception raised for resumable downloads that can be retried later."""


class ResumableUploadException(RetryableServiceException):
  """Exception raised for resumable uploads that can be retried later."""


class ResumableUploadAbortException(ServiceException):
  """Exception raised for resumable uploads that cannot be retried later."""


class AuthenticationException(ServiceException):
  """Exception raised for errors during the authentication process."""


class PreconditionException(ServiceException):
  """Exception raised for precondition failures."""


class NotFoundException(ServiceException):
  """Exception raised when a resource is not found (404)."""


class NotEmptyException(ServiceException):
  """Exception raised when trying to delete a bucket is not empty."""


class BadRequestException(ServiceException):
  """Exception raised for malformed requests.

    Where it is possible to detect invalid arguments prior to sending them
    to the server, an ArgumentException should be raised instead.
  """


class AccessDeniedException(ServiceException):
  """Exception raised  when authenticated user has insufficient access rights.

    This is raised when the authentication process succeeded but the
    authenticated user does not have access rights to the requested resource.
  """


