# -*- coding: utf-8 -*-
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
"""Shell tab completion."""

import itertools
import time

import boto

from gslib.storage_url import IsFileUrlString
from gslib.util import GetTabCompletionLogFilename
from gslib.wildcard_iterator import CreateWildcardIterator


_TAB_COMPLETE_MAX_RESULTS = 1000


class CompleterType(object):
  CLOUD_OBJECT = 'cloud_object'
  CLOUD_OR_LOCAL_OBJECT = 'cloud_or_local_object'
  LOCAL_OBJECT = 'local_object'
  NO_OP = 'no_op'


class LocalObjectCompleter(object):
  """Completer object for local files."""

  def __init__(self):
    # This is only safe to import if argcomplete is present in the install
    # (which happens for Cloud SDK installs), so import on usage, not on load.
    # pylint: disable=g-import-not-at-top
    from argcomplete.completers import FilesCompleter
    self.files_completer = FilesCompleter()

  def __call__(self, prefix, **kwargs):
    return self.files_completer(prefix, **kwargs)


class CloudObjectCompleter(object):
  """Completer object for Cloud URLs."""

  def __init__(self, gsutil_api):
    self.gsutil_api = gsutil_api

  def __call__(self, prefix, **kwargs):
    if not prefix:
      prefix = 'gs://'
    elif IsFileUrlString(prefix):
      return []
    start_time = time.time()
    it = CreateWildcardIterator(
        prefix + '*', self.gsutil_api).IterAll(bucket_listing_fields=['name'])
    results = [str(c) for c in itertools.islice(it, _TAB_COMPLETE_MAX_RESULTS)]
    end_time = time.time()
    if boto.config.getbool('GSUtil', 'tab_completion_timing', False):
      num_results = len(results)
      elapsed_seconds = end_time - start_time
      with open(GetTabCompletionLogFilename(), 'ab') as fp:
        fp.write('%s results in %.2fs, %.2f results/second for prefix: %s\n' %
                 (num_results, elapsed_seconds, num_results / elapsed_seconds,
                  prefix))
    return results


class CloudOrLocalObjectCompleter(object):
  """Completer object for Cloud URLs or local files.

  Invokes the Cloud object completer if the input looks like a Cloud URL and
  falls back to local file completer otherwise.
  """

  def __init__(self, gsutil_api):
    self.cloud_object_completer = CloudObjectCompleter(gsutil_api)
    self.local_object_completer = LocalObjectCompleter()

  def __call__(self, prefix, **kwargs):
    if IsFileUrlString(prefix):
      completer = self.local_object_completer
    else:
      completer = self.cloud_object_completer
    return completer(prefix, **kwargs)


class NoOpCompleter(object):
  """Completer that always returns 0 results."""

  def __call__(self, unused_prefix, **unused_kwargs):
    return []


def MakeCompleter(completer_type, gsutil_api):
  """Create a completer instance of the given type.

  Args:
    completer_type: The type of completer to create.
    gsutil_api: gsutil Cloud API instance to use.
  Returns:
    A completer instance.
  Raises:
    RuntimeError: if completer type is not supported.
  """
  if completer_type == CompleterType.CLOUD_OR_LOCAL_OBJECT:
    return CloudOrLocalObjectCompleter(gsutil_api)
  elif completer_type == CompleterType.LOCAL_OBJECT:
    return LocalObjectCompleter()
  elif completer_type == CompleterType.CLOUD_OBJECT:
    return CloudObjectCompleter(gsutil_api)
  elif completer_type == CompleterType.NO_OP:
    return NoOpCompleter()
  else:
    raise RuntimeError(
        'Unknown completer "%s"' % completer_type)
