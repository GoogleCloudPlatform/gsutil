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


import gslib
from gslib.third_party.storage_apitools import storage_v1_messages as apitools_messages
from gslib.utils.boto_util import PrintTrackerDirDeprecationWarningIfNeeded
from gslib.utils.boto_util import GetGsutilStateDir
from gslib.utils.constants import MIN_ACCEPTABLE_OPEN_FILES_LIMIT
from gslib.utils.system_util import CreateDirIfNeeded
from gslib.utils.system_util import IS_WINDOWS

import httplib2

# pylint: disable=g-import-not-at-top
try:
  # This module doesn't necessarily exist on Windows.
  import resource
  HAS_RESOURCE_MODULE = True
except ImportError, e:
  HAS_RESOURCE_MODULE = False


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



