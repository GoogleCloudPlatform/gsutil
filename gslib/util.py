# -*- coding: utf-8 -*-
# Copyright 2010 Google Inc. All Rights Reserved.
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
"""Static data and helper functions."""

from __future__ import absolute_import

import collections
import logging
import multiprocessing
import os
import threading
import time
import traceback
import xml.etree.ElementTree as ElementTree

from apitools.base.py import http_wrapper

import gslib
from gslib.storage_url import StorageUrlFromString
from gslib.third_party.storage_apitools import storage_v1_messages as apitools_messages
from gslib.thread_message import RetryableErrorMessage
from gslib.translation_helper import AclTranslation
from gslib.translation_helper import GenerationFromUrlAndString
from gslib.translation_helper import S3_ACL_MARKER_GUID
from gslib.translation_helper import S3_DELETE_MARKER_GUID
from gslib.translation_helper import S3_MARKER_GUIDS
from gslib.utils.boto_util import PrintTrackerDirDeprecationWarningIfNeeded
from gslib.utils.boto_util import GetGsutilStateDir
from gslib.utils.constants import UTF8
from gslib.utils.constants import WINDOWS_1252
from gslib.utils.system_util import CreateDirIfNeeded
from gslib.utils.system_util import IS_CP1252
from gslib.utils.system_util import IS_WINDOWS
from gslib.utils.system_util import WINDOWS_1252
from gslib.utils.unit_util import ONE_GIB
from gslib.utils.unit_util import ONE_KIB
from gslib.utils.unit_util import ONE_MIB

import httplib2
from retry_decorator import retry_decorator

# pylint: disable=g-import-not-at-top
try:
  # This module doesn't necessarily exist on Windows.
  import resource
  HAS_RESOURCE_MODULE = True
except ImportError, e:
  HAS_RESOURCE_MODULE = False


DEBUGLEVEL_DUMP_REQUESTS = 3
DEBUGLEVEL_DUMP_REQUESTS_AND_PAYLOADS = 4

DEFAULT_FILE_BUFFER_SIZE = 8 * ONE_KIB
RESUMABLE_THRESHOLD_MIB = 8
RESUMABLE_THRESHOLD_B = RESUMABLE_THRESHOLD_MIB * ONE_MIB


# Start with a progress callback every 64 KiB during uploads/downloads (JSON
# API). Callback implementation should back off until it hits the maximum size
# so that callbacks do not create huge amounts of log output.
START_CALLBACK_PER_BYTES = 256 * ONE_KIB
MAX_CALLBACK_PER_BYTES = 100 * ONE_MIB

# Upload/download files in 8 KiB chunks over the HTTP connection.
# TODO: This should say the unit in the name.
TRANSFER_BUFFER_SIZE = 8 * ONE_KIB

# Default number of progress callbacks during transfer (XML API).
XML_PROGRESS_CALLBACKS = 10

# Number of objects to request in listing calls.
NUM_OBJECTS_PER_LIST_PAGE = 1000

# For files >= this size, output a message indicating that we're running an
# operation on the file (like hashing or gzipping) so it does not appear to the
# user that the command is hanging.
# TODO: This should say the unit in the name.
MIN_SIZE_COMPUTE_LOGGING = 100 * ONE_MIB


# Number of seconds to wait before printing a long retry warning message.
LONG_RETRY_WARN_SEC = 10


# Compressed transport encoded uploads buffer chunks of compressed data. When
# running many uploads in parallel, compression may consume more memory than
# available. This restricts the number of compressed transport encoded uploads
# running in parallel such that they don't consume more memory than set here.
MAX_UPLOAD_COMPRESSION_BUFFER_SIZE = 2 * ONE_GIB

# On Unix-like systems, we will set the maximum number of open files to avoid
# hitting the limit imposed by the OS. This number was obtained experimentally.
MIN_ACCEPTABLE_OPEN_FILES_LIMIT = 1000



Retry = retry_decorator.retry  # pylint: disable=invalid-name

global manager  # pylint: disable=global-at-module-level

# Cache the values from this check such that they're available to all callers
# without needing to run all the checks again (some of these, such as calling
# multiprocessing.Manager(), are expensive operations).
cached_multiprocessing_is_available = None
cached_multiprocessing_is_available_stack_trace = None
cached_multiprocessing_is_available_message = None


def ObjectIsGzipEncoded(obj_metadata):
  """Returns true if source apitools Object has gzip content-encoding."""
  return (obj_metadata.contentEncoding and
          obj_metadata.contentEncoding.lower().endswith('gzip'))


def AddAcceptEncodingGzipIfNeeded(headers_dict, compressed_encoding=False):
  if compressed_encoding:
    # If we send accept-encoding: gzip with a range request, the service
    # may respond with the whole object, which would be bad for resuming.
    # So only accept gzip encoding if the object we are downloading has
    # a gzip content encoding.
    # TODO: If we want to support compressive transcoding fully in the client,
    # condition on whether we are requesting the entire range of the object.
    # In this case, we can accept the first bytes of the object compressively
    # transcoded, but we must perform data integrity checking on bytes after
    # they are decompressed on-the-fly, and any connection break must be
    # resumed without compressive transcoding since we cannot specify an
    # offset. We would also need to ensure that hashes for downloaded data
    # from objects stored with content-encoding:gzip continue to be calculated
    # prior to our own on-the-fly decompression so they match the stored hashes.
    headers_dict['accept-encoding'] = 'gzip'


# Name of file where we keep the timestamp for the last time we checked whether
# a new version of gsutil is available.
PrintTrackerDirDeprecationWarningIfNeeded()
CreateDirIfNeeded(GetGsutilStateDir())
LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE = (
    os.path.join(GetGsutilStateDir(), '.last_software_update_check'))


def UnaryDictToXml(message):
  """Generates XML representation of a nested dict.

  This dict contains exactly one top-level entry and an arbitrary number of
  2nd-level entries, e.g. capturing a WebsiteConfiguration message.

  Args:
    message: The dict encoding the message.

  Returns:
    XML string representation of the input dict.

  Raises:
    Exception: if dict contains more than one top-level entry.
  """
  if len(message) != 1:
    raise Exception('Expected dict of size 1, got size %d' % len(message))

  name, content = message.items()[0]
  element_type = ElementTree.Element(name)
  for element_property, value in sorted(content.items()):
    node = ElementTree.SubElement(element_type, element_property)
    node.text = value
  return ElementTree.tostring(element_type)


def LookUpGsutilVersion(gsutil_api, url_str):
  """Looks up the gsutil version of the specified gsutil tarball URL.

  Version is specified in the metadata field set on that object.

  Args:
    gsutil_api: gsutil Cloud API to use when retrieving gsutil tarball.
    url_str: tarball URL to retrieve (such as 'gs://pub/gsutil.tar.gz').

  Returns:
    Version string if URL is a cloud URL containing x-goog-meta-gsutil-version
    metadata, else None.
  """
  url = StorageUrlFromString(url_str)
  if url.IsCloudUrl():
    obj = gsutil_api.GetObjectMetadata(url.bucket_name, url.object_name,
                                       provider=url.scheme,
                                       fields=['metadata'])
    if obj.metadata and obj.metadata.additionalProperties:
      for prop in obj.metadata.additionalProperties:
        if prop.key == 'gsutil_version':
          return prop.value


def GetGsutilVersionModifiedTime():
  """Returns unix timestamp of when the VERSION file was last modified."""
  if not gslib.VERSION_FILE:
    return 0
  return int(os.path.getmtime(gslib.VERSION_FILE))


def CreateCustomMetadata(entries=None, custom_metadata=None):
  """Creates a custom metadata (apitools Object.MetadataValue) object.

  Inserts the key/value pairs in entries.

  Args:
    entries: The dictionary containing key/value pairs to insert into metadata.
    custom_metadata: A pre-existing custom metadata object to add to.

  Returns:
    An apitools Object.MetadataVlue.
  """
  if custom_metadata is None:
    custom_metadata = apitools_messages.Object.MetadataValue(
        additionalProperties=[])
  if entries is None:
    entries = {}
  for key, value in entries.iteritems():
    custom_metadata.additionalProperties.append(
        apitools_messages.Object.MetadataValue.AdditionalProperty(
            key=str(key), value=str(value)))
  return custom_metadata


def GetValueFromObjectCustomMetadata(obj_metadata, search_key,
                                     default_value=None):
  """Filters a specific element out of an object's custom metadata.

  Args:
    obj_metadata: The metadata for an object.
    search_key: The custom metadata key to search for.
    default_value: The default value to use for the key if it cannot be found.

  Returns:
    A tuple indicating if the value could be found in metadata and a value
    corresponding to search_key. The value at the specified key in custom
    metadata or the default value, if the specified key does not exist in the
    customer metadata.
  """
  try:
    value = next((attr.value for attr in
                  obj_metadata.metadata.additionalProperties
                  if attr.key == search_key), None)
    if value is None:
      return False, default_value
    return True, value
  except AttributeError:
    return False, default_value


def IsCustomMetadataHeader(header):
  """Returns true if header (which must be lowercase) is a custom header."""
  return header.startswith('x-goog-meta-') or header.startswith('x-amz-meta-')


# TODO(refactor): Move this to ls_helper?
# pylint: disable=too-many-statements
def PrintFullInfoAboutObject(bucket_listing_ref, incl_acl=True):
  """Print full info for given object (like what displays for gsutil ls -L).

  Args:
    bucket_listing_ref: BucketListingRef being listed.
                        Must have ref_type OBJECT and a populated root_object
                        with the desired fields.
    incl_acl: True if ACL info should be output.

  Returns:
    Tuple (number of objects, object_length)

  Raises:
    Exception: if calling bug encountered.
  """
  url_str = bucket_listing_ref.url_string
  storage_url = StorageUrlFromString(url_str)
  obj = bucket_listing_ref.root_object

  if (obj.metadata and S3_DELETE_MARKER_GUID in
      obj.metadata.additionalProperties):
    num_bytes = 0
    num_objs = 0
    url_str += '<DeleteMarker>'
  else:
    num_bytes = obj.size
    num_objs = 1

  print '%s:' % url_str.encode(UTF8)
  if obj.timeCreated:
    print MakeMetadataLine(
        'Creation time', obj.timeCreated.strftime('%a, %d %b %Y %H:%M:%S GMT'))
  if obj.updated:
    print MakeMetadataLine(
        'Update time', obj.updated.strftime('%a, %d %b %Y %H:%M:%S GMT'))
  if (obj.timeStorageClassUpdated and
      obj.timeStorageClassUpdated != obj.timeCreated):
    print MakeMetadataLine(
        'Storage class update time',
        obj.timeStorageClassUpdated.strftime('%a, %d %b %Y %H:%M:%S GMT'))
  if obj.storageClass:
    print MakeMetadataLine('Storage class', obj.storageClass)
  if obj.kmsKeyName:
    print MakeMetadataLine('KMS key', obj.kmsKeyName)
  if obj.cacheControl:
    print MakeMetadataLine('Cache-Control', obj.cacheControl)
  if obj.contentDisposition:
    print MakeMetadataLine('Content-Disposition', obj.contentDisposition)
  if obj.contentEncoding:
    print MakeMetadataLine('Content-Encoding', obj.contentEncoding)
  if obj.contentLanguage:
    print MakeMetadataLine('Content-Language', obj.contentLanguage)
  print MakeMetadataLine('Content-Length', obj.size)
  print MakeMetadataLine('Content-Type', obj.contentType)
  if obj.componentCount:
    print MakeMetadataLine('Component-Count', obj.componentCount)
  if obj.timeDeleted:
    print MakeMetadataLine(
        'Archived time',
        obj.timeDeleted.strftime('%a, %d %b %Y %H:%M:%S GMT'))
  marker_props = {}
  if obj.metadata and obj.metadata.additionalProperties:
    non_marker_props = []
    for add_prop in obj.metadata.additionalProperties:
      if add_prop.key not in S3_MARKER_GUIDS:
        non_marker_props.append(add_prop)
      else:
        marker_props[add_prop.key] = add_prop.value
    if non_marker_props:
      print MakeMetadataLine('Metadata', '')
      for ap in non_marker_props:
        print MakeMetadataLine(
            ('%s' % ap.key).encode(UTF8), ('%s' % ap.value).encode(UTF8),
            indent=2)
  if obj.customerEncryption:
    if not obj.crc32c:
      print MakeMetadataLine('Hash (crc32c)', 'encrypted')
    if not obj.md5Hash:
      print MakeMetadataLine('Hash (md5)', 'encrypted')
    print MakeMetadataLine(
        'Encryption algorithm', obj.customerEncryption.encryptionAlgorithm)
    print MakeMetadataLine(
        'Encryption key SHA256', obj.customerEncryption.keySha256)
  if obj.crc32c:
    print MakeMetadataLine('Hash (crc32c)', obj.crc32c)
  if obj.md5Hash:
    print MakeMetadataLine('Hash (md5)', obj.md5Hash)
  print MakeMetadataLine('ETag', obj.etag.strip('"\''))
  if obj.generation:
    generation_str = GenerationFromUrlAndString(storage_url, obj.generation)
    print MakeMetadataLine('Generation', generation_str)
  if obj.metageneration:
    print MakeMetadataLine('Metageneration', obj.metageneration)
  if incl_acl:
    # JSON API won't return acls as part of the response unless we have
    # full control scope
    if obj.acl:
      print MakeMetadataLine('ACL', AclTranslation.JsonFromMessage(obj.acl))
    elif S3_ACL_MARKER_GUID in marker_props:
      print MakeMetadataLine('ACL', marker_props[S3_ACL_MARKER_GUID])
    else:
      print MakeMetadataLine('ACL', 'ACCESS DENIED')
      print MakeMetadataLine(
          'Note', 'You need OWNER permission on the object to read its ACL', 2)
  return (num_objs, num_bytes)


# TODO(refactor): Move this to ls_helper?
def MakeMetadataLine(label, value, indent=1):
  """Returns a string with a vertically aligned label and value.

  Labels of the same indentation level will start at the same column. Values
  will all start at the same column (unless the combined left-indent and
  label length is excessively long). If a value spans multiple lines,
  indentation will only be applied to the first line. Example output from
  several calls:

      Label1:            Value (default indent of 1 was used)
          Sublabel1:     Value (used indent of 2 here)
      Label2:            Value

  Args:
    label: The label to print in the first column.
    value: The value to print in the second column.
    indent: (4 * indent) spaces will be placed before the label.
  Returns:
    A string with a vertically aligned label and value.
  """
  return '%s%s' % (((' ' * indent * 4) + label + ':').ljust(28), value)


def _IncreaseSoftLimitForResource(resource_name, fallback_value):
  """Sets a new soft limit for the maximum number of open files.

  The soft limit is used for this process (and its children), but the
  hard limit is set by the system and cannot be exceeded.

  We will first try to set the soft limit to the hard limit's value; if that
  fails, we will try to set the soft limit to the fallback_value iff this would
  increase the soft limit.

  Args:
    resource_name: Name of the resource to increase the soft limit for.
    fallback_value: Fallback value to be used if we couldn't set the
                    soft value to the hard value (e.g., if the hard value
                    is "unlimited").

  Returns:
    Current soft limit for the resource (after any changes we were able to
    make), or -1 if the resource doesn't exist.
  """

  # Get the value of the resource.
  try:
    (soft_limit, hard_limit) = resource.getrlimit(resource_name)
  except (resource.error, ValueError):
    # The resource wasn't present, so we can't do anything here.
    return -1

  # Try to set the value of the soft limit to the value of the hard limit.
  if hard_limit > soft_limit:  # Some OS's report 0 for "unlimited".
    try:
      resource.setrlimit(resource_name, (hard_limit, hard_limit))
      return hard_limit
    except (resource.error, ValueError):
      # We'll ignore this and try the fallback value.
      pass

  # Try to set the value of the soft limit to the fallback value.
  if soft_limit < fallback_value:
    try:
      resource.setrlimit(resource_name, (fallback_value, hard_limit))
      return fallback_value
    except (resource.error, ValueError):
      # We couldn't change the soft limit, so just report the current
      # value of the soft limit.
      return soft_limit
  else:
    return soft_limit


def GetCloudApiInstance(cls, thread_state=None):
  """Gets a gsutil Cloud API instance.

  Since Cloud API implementations are not guaranteed to be thread-safe, each
  thread needs its own instance. These instances are passed to each thread
  via the thread pool logic in command.

  Args:
    cls: Command class to be used for single-threaded case.
    thread_state: Per thread state from this thread containing a gsutil
                  Cloud API instance.

  Returns:
    gsutil Cloud API instance.
  """
  return thread_state or cls.gsutil_api


# TODO(refactor): Move this into storage_url or storage_url_util.
def UrlsAreForSingleProvider(url_args):
  """Tests whether the URLs are all for a single provider.

  Args:
    url_args: Strings to check.

  Returns:
    True if URLs are for single provider, False otherwise.
  """
  provider = None
  url = None
  for url_str in url_args:
    url = StorageUrlFromString(url_str)
    if not provider:
      provider = url.scheme
    elif url.scheme != provider:
      return False
  return provider is not None


# TODO(refactor): Move this into storage_url or storage_url_util.
def HaveFileUrls(args_to_check):
  """Checks whether args_to_check contain any file URLs.

  Args:
    args_to_check: Command-line argument subset to check.

  Returns:
    True if args_to_check contains any file URLs.
  """
  for url_str in args_to_check:
    storage_url = StorageUrlFromString(url_str)
    if storage_url.IsFileUrl():
      return True
  return False


# TODO(refactor): Move this into storage_url or storage_url_util.
def HaveProviderUrls(args_to_check):
  """Checks whether args_to_check contains any provider URLs (like 'gs://').

  Args:
    args_to_check: Command-line argument subset to check.

  Returns:
    True if args_to_check contains any provider URLs.
  """
  for url_str in args_to_check:
    storage_url = StorageUrlFromString(url_str)
    if storage_url.IsCloudUrl() and storage_url.IsProvider():
      return True
  return False

# This must be defined at the module level for pickling across processes.
MultiprocessingIsAvailableResult = collections.namedtuple(
    'MultiprocessingIsAvailableResult', ['is_available', 'stack_trace'])


def CheckMultiprocessingAvailableAndInit(logger=None):
  """Checks if multiprocessing is available.

  There are some environments in which there is no way to use multiprocessing
  logic that's built into Python (e.g., if /dev/shm is not available, then
  we can't create semaphores). This simply tries out a few things that will be
  needed to make sure the environment can support the pieces of the
  multiprocessing module that we need.

  If multiprocessing is available, this performs necessary initialization for
  multiprocessing.  See gslib.command.InitializeMultiprocessingVariables for
  an explanation of why this is necessary.

  Args:
    logger: logging.logger to use for debug output.

  Returns:
    (multiprocessing_is_available, stack_trace):
      multiprocessing_is_available: True iff the multiprocessing module is
                                    available for use.
      stack_trace: The stack trace generated by the call we tried that failed.
  """
  # pylint: disable=global-variable-undefined
  global cached_multiprocessing_is_available
  global cached_multiprocessing_check_stack_trace
  global cached_multiprocessing_is_available_message
  if cached_multiprocessing_is_available is not None:
    if logger:
      logger.debug(cached_multiprocessing_check_stack_trace)
      logger.warn(cached_multiprocessing_is_available_message)
    return MultiprocessingIsAvailableResult(
        is_available=cached_multiprocessing_is_available,
        stack_trace=cached_multiprocessing_check_stack_trace)

  if IS_WINDOWS:
    message = """
Multiple processes are not supported on Windows. Operations requesting
parallelism will be executed with multiple threads in a single process only.
"""
    if logger:
      logger.warn(message)
    return MultiprocessingIsAvailableResult(is_available=False,
                                            stack_trace=None)

  stack_trace = None
  multiprocessing_is_available = True
  message = """
You have requested multiple processes for an operation, but the
required functionality of Python\'s multiprocessing module is not available.
Operations requesting parallelism will be executed with multiple threads in a
single process only.
"""
  try:
    # Fails if /dev/shm (or some equivalent thereof) is not available for use
    # (e.g., there's no implementation, or we can't write to it, etc.).
    try:
      multiprocessing.Value('i', 0)
    except:
      message += """
Please ensure that you have write access to both /dev/shm and /run/shm.
"""
      raise  # We'll handle this in one place below.

    global manager  # pylint: disable=global-variable-undefined
    manager = multiprocessing.Manager()

    # Check that the max number of open files is reasonable. Always check this
    # after we're sure that the basic multiprocessing functionality is
    # available, since this won't matter unless that's true.
    limit = -1
    if HAS_RESOURCE_MODULE:
      # Try to set this with both resource names - RLIMIT_NOFILE for most Unix
      # platforms, and RLIMIT_OFILE for BSD. Ignore AttributeError because the
      # "resource" module is not guaranteed to know about these names.
      try:
        limit = max(limit,
                    _IncreaseSoftLimitForResource(
                        resource.RLIMIT_NOFILE,
                        MIN_ACCEPTABLE_OPEN_FILES_LIMIT))
      except AttributeError:
        pass
      try:
        limit = max(limit,
                    _IncreaseSoftLimitForResource(
                        resource.RLIMIT_OFILE, MIN_ACCEPTABLE_OPEN_FILES_LIMIT))
      except AttributeError:
        pass

    if limit < MIN_ACCEPTABLE_OPEN_FILES_LIMIT:
      message += ("""
Your max number of open files, %s, is too low to allow safe multiprocessing.
On Linux you can fix this by adding something like "ulimit -n 10000" to your
~/.bashrc or equivalent file and opening a new terminal.

On MacOS, you may also need to run a command like this once (in addition to the
above instructions), which might require a restart of your system to take
effect:
  launchctl limit maxfiles 10000

Alternatively, edit /etc/launchd.conf with something like:
  limit maxfiles 10000 10000

""" % limit)
      raise Exception('Max number of open files, %s, is too low.' % limit)
  except:  # pylint: disable=bare-except
    stack_trace = traceback.format_exc()
    multiprocessing_is_available = False
    if logger is not None:
      logger.debug(stack_trace)
      logger.warn(message)

  # Set the cached values so that we never need to do this check again.
  cached_multiprocessing_is_available = multiprocessing_is_available
  cached_multiprocessing_check_stack_trace = stack_trace
  cached_multiprocessing_is_available_message = message
  return MultiprocessingIsAvailableResult(
      is_available=cached_multiprocessing_is_available,
      stack_trace=cached_multiprocessing_check_stack_trace)


def CreateLock():
  """Returns either a multiprocessing lock or a threading lock.

  Use Multiprocessing lock iff we have access to the parts of the
  multiprocessing module that are necessary to enable parallelism in operations.

  Returns:
    Multiprocessing or threading lock.
  """
  if CheckMultiprocessingAvailableAndInit().is_available:
    return manager.Lock()
  else:
    return threading.Lock()


# TODO(refactor): Move this into storage_url or storage_url_util.
def IsCloudSubdirPlaceholder(url, blr=None):
  """Determines if URL is a cloud subdir placeholder.

  This function is needed because GUI tools (like the GCS cloud console) allow
  users to create empty "folders" by creating a placeholder object; and parts
  of gsutil need to treat those placeholder objects specially. For example,
  gsutil rsync needs to avoid downloading those objects because they can cause
  conflicts (see comments in rsync command for details).

  We currently detect two cases:
    - Cloud objects whose name ends with '_$folder$'
    - Cloud objects whose name ends with '/'

  Args:
    url: (gslib.storage_url.StorageUrl) The URL to be checked.
    blr: (gslib.BucketListingRef or None) The blr to check, or None if not
        available. If `blr` is None, size won't be checked.

  Returns:
    (bool) True if the URL is a cloud subdir placeholder, otherwise False.
  """
  if not url.IsCloudUrl():
    return False
  url_str = url.url_string
  if url_str.endswith('_$folder$'):
    return True
  if blr and blr.IsObject():
    size = blr.root_object.size
  else:
    size = 0
  return size == 0 and url_str.endswith('/')


def LogAndHandleRetries(is_data_transfer=False, status_queue=None):
  """Higher-order function allowing retry handler to access global status queue.

  Args:
    is_data_transfer: If True, disable retries in apitools.
    status_queue: The global status queue.

  Returns:
    A retry function for retryable errors in apitools.
  """
  def WarnAfterManyRetriesHandler(retry_args):
    """Exception handler for http failures in apitools.

    If the user has had to wait several seconds since their first request, print
    a progress message to the terminal to let them know we're still retrying,
    then perform the default retry logic and post a RetryableErrorMessage to the
    global status queue.

    Args:
      retry_args: An apitools ExceptionRetryArgs tuple.
    """
    if retry_args.total_wait_sec >= LONG_RETRY_WARN_SEC:
      logging.info('Retrying request, attempt #%d...', retry_args.num_retries)
    if status_queue:
      status_queue.put(RetryableErrorMessage(
          retry_args.exc, time.time(), num_retries=retry_args.num_retries,
          total_wait_sec=retry_args.total_wait_sec))
    http_wrapper.HandleExceptionsAndRebuildHttpConnections(retry_args)

  def RetriesInDataTransferHandler(retry_args):
    """Exception handler that disables retries in apitools data transfers.

    Post a RetryableErrorMessage to the global status queue. We handle the
    actual retries within the download and upload functions.

    Args:
      retry_args: An apitools ExceptionRetryArgs tuple.
    """
    if status_queue:
      status_queue.put(RetryableErrorMessage(
          retry_args.exc, time.time(), num_retries=retry_args.num_retries,
          total_wait_sec=retry_args.total_wait_sec))
    http_wrapper.RethrowExceptionHandler(retry_args)

  if is_data_transfer:
    return RetriesInDataTransferHandler
  return WarnAfterManyRetriesHandler


# TODO(refactor): Move this into storage_url or storage_url_util... or maybe
# text_util??
def ConvertRecursiveToFlatWildcard(url_strs):
  """A generator that adds '**' to each url string in url_strs."""
  for url_str in url_strs:
    yield '%s**' % url_str
