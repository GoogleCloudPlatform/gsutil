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

import boto
import functools
import os
import posixpath
import pkgutil
import re
import urlparse

import unittest
if not hasattr(unittest.TestCase, 'assertIsNone'):
  # external dependency unittest2 required for Python <= 2.6
  import unittest2 as unittest

from boto.provider import Provider
import gslib.tests as gslib_tests


# Flags for running different types of tests.
RUN_INTEGRATION_TESTS = True
RUN_UNIT_TESTS = True

# Whether the tests are running verbose or not.
VERBOSE_OUTPUT = False

PARALLEL_COMPOSITE_UPLOAD_TEST_CONFIG = '/tmp/.boto.parallel_upload_test_config'


def _HasS3Credentials():
  provider = Provider('aws')
  if not provider.access_key or not provider.secret_key:
    return False
  return True

HAS_S3_CREDS = _HasS3Credentials()


def _NormalizeURI(uri):
  """Normalizes the path component of a URI.

  Examples:
    gs://foo//bar -> gs://foo/bar
    gs://foo/./bar -> gs://foo/bar
  """
  # Note: we have to do this dance of changing gs:// to file:// because on
  # Windows, the urlparse function won't work with URL schemes that are not
  # known. urlparse('gs://foo/bar') on Windows turns into:
  #     scheme='gs', netloc='', path='//foo/bar'
  # while on non-Windows platforms, it turns into:
  #     scheme='gs', netloc='foo', path='/bar'
  uri = uri.replace('gs://', 'file://')
  parsed = list(urlparse.urlparse(uri))
  parsed[2] = posixpath.normpath(parsed[2])
  if parsed[2].startswith('//'):
    # The normpath function doesn't change '//foo' -> '/foo' by design.
    parsed[2] = parsed[2][1:]
  unparsed = urlparse.urlunparse(parsed)
  unparsed = unparsed.replace('file://', 'gs://')
  return unparsed


def ObjectToURI(obj, *suffixes):
  """Returns the storage URI string for a given StorageUri or file object.

  Args:
    obj: The object to get the URI from. Can be a file object, a subclass of
         boto.storage_uri.StorageURI, or a string. If a string, it is assumed to
         be a local on-disk path.
    suffixes: Suffixes to append. For example, ObjectToUri(bucketuri, 'foo')
              would return the URI for a key name 'foo' inside the given bucket.
  """
  if isinstance(obj, file):
    return 'file://%s' % os.path.abspath(os.path.join(obj.name, *suffixes))
  if isinstance(obj, basestring):
    return 'file://%s' % os.path.join(obj, *suffixes)
  uri = obj.uri
  if suffixes:
    uri = _NormalizeURI('/'.join([uri] + list(suffixes)))

  # Storage URIs shouldn't contain a trailing slash.
  if uri.endswith('/'):
    uri = uri[:-1]
  return uri

def PerformsFileToObjectUpload(func):
  """Decorator used to indicate that a test performs an upload from a local
     file to an object. This forces the test to run once normally, and again
     with a special .boto config file that will ensure that the test follows
     the parallel composite upload code path.
  """
  @functools.wraps(func)
  def wrapper(*args, **kwargs):
    try:
      old_boto_config = os.environ['BOTO_CONFIG']
      boto_config_was_set = True
    except KeyError as e:
      boto_config_was_set = False
    try:
      # Run the test normally once.
      func(*args, **kwargs)

      # Try again, forcing parallel composite uploads.
      boto.config.set('GSUtil', 'parallel_composite_upload_threshold', '1')
      os.environ['BOTO_CONFIG'] = PARALLEL_COMPOSITE_UPLOAD_TEST_CONFIG

      # Write a new config file corresponding to the new BOTO_CONFIG.
      with open(PARALLEL_COMPOSITE_UPLOAD_TEST_CONFIG, 'w') as f:
        boto.config.write(f)
      func(*args, **kwargs)
    finally:
      if boto_config_was_set:
        os.environ['BOTO_CONFIG'] = old_boto_config
  return wrapper

def GetTestNames():
  """Returns a list of the names of the test modules in gslib.tests."""
  matcher = re.compile(r'^test_(?P<name>.*)$')
  names = []
  for importer, modname, ispkg in pkgutil.iter_modules(gslib_tests.__path__):
    m = matcher.match(modname)
    if m:
      names.append(m.group('name'))
  return names
