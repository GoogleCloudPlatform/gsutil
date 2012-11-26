# Copyright 2012 Google Inc.
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

"""
Class that holds state (bucket_storage_uri_class and debug) needed for
instantiating StorageUri objects. The StorageUri func defined in this class
uses that state plus gsutil default flag values to instantiate this frequently
constructed object with just one param for most cases.
"""

import boto
import re
from gslib.exception import CommandException

GENERATION_RE = ('(?P<uri_str>.+)#'
                 '(?P<generation>[0-9]+)(\.(?P<meta_generation>[0-9]+))?')
VERSION_RE = '(?P<uri_str>.+)#(?P<version_id>.+)'


class StorageUriBuilder(object):

  def __init__(self, debug, bucket_storage_uri_class):
    """
    Args:
      debug: Debug level to pass in to boto connection (range 0..3).
      bucket_storage_uri_class: Class to instantiate for cloud StorageUris.
                                Settable for testing/mocking.
    """
    self.bucket_storage_uri_class = bucket_storage_uri_class
    self.debug = debug

  def StorageUri(self, uri_str, parse_version=False):
    """
    Instantiates StorageUri using class state and gsutil default flag values.

    Args:
      uri_str: StorageUri naming bucket + optional object.
      parse_version: boolean indicating whether to parse out version/generation
          information from uri_str.

    Returns:
      boto.StorageUri for given uri_str.

    Raises:
      InvalidUriError: if uri_str not valid.
    """
    version_id = None
    generation = None
    meta_generation = None

    uri_str_only = uri_str
    if parse_version:
      if uri_str.startswith('gs'):
        match = re.search(GENERATION_RE, uri_str)
        if not match:
          raise CommandException(
              'Generation number expected in uri %s' % uri_str)
        md = match.groupdict()
        uri_str_only = md['uri_str']
        generation = int(md['generation'])
        if md['meta_generation']:
          meta_generation = int(md['meta_generation'])

      elif uri_str.startswith('s3'):
        match = re.search(VERSION_RE, uri_str)
        if not match:
          raise CommandException('Version ID expected in uri %s' % uri_str)
        md = match.groupdict()
        uri_str_only = md['uri_str']
        version_id = md['version_id']

      else:
        raise CommandException('Unrecognized provider scheme in uri %s' %
                               uri_str)

    suri = boto.storage_uri(
        uri_str_only, 'file', debug=self.debug, validate=False,
        bucket_storage_uri_class=self.bucket_storage_uri_class,
        suppress_consec_slashes=False)

    suri.version_id = version_id
    suri.generation = generation
    suri.meta_generation = meta_generation

    return suri
