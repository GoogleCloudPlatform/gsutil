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

from argcomplete.completers import FilesCompleter
from storage_url import StorageUrlFromString
from wildcard_iterator import CreateWildcardIterator


class CompleterType(object):
  CLOUD_OBJECT = 'cloud_object'
  CLOUD_OR_LOCAL_OBJECT = 'cloud_or_local_object'


class CloudObjectCompleter(object):
  """Completer object for Cloud URIs."""

  def __init__(self, gsutil_api):
    self.gsutil_api = gsutil_api

  def __call__(self, prefix, **kwargs):
    return [str(c) for c in CreateWildcardIterator(
        prefix + '*', self.gsutil_api).IterAll(bucket_listing_fields=['name'])]


class CloudOrLocalObjectCompleter(object):
  """Completer object for Cloud URIs or local files.

  Invokes the Cloud object completer if the input looks like a Cloud URI and
  falls back to local file completer otherwise.
  """

  def __init__(self, gsutil_api):
    self.cloud_object_completer = CloudObjectCompleter(gsutil_api)
    self.local_object_completer = FilesCompleter()

  def __call__(self, prefix, **kwargs):
    url = StorageUrlFromString(prefix)
    if url.IsFileUrl():
      completer = self.local_object_completer
    else:
      completer = self.cloud_object_completer
    return completer(prefix, **kwargs)
