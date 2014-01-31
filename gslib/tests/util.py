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

from contextlib import contextmanager
import functools
import os
import pkgutil
import posixpath
import re
import tempfile
import unittest
import urlparse

import boto
from boto.provider import Provider
import gslib.tests as gslib_tests

if not hasattr(unittest.TestCase, 'assertIsNone'):
  # external dependency unittest2 required for Python <= 2.6
  import unittest2 as unittest  # pylint: disable=g-import-not-at-top

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


def _HasGSHost():
  return boto.config.get('Credentials', 'gs_host', None) is not None

HAS_GS_HOST = _HasGSHost()


# TODO: gsutil-beta: Add annotations for XML/JSON/GS/S3 testing.
def _UsingJSONApi():
  return boto.config.get('GSUtil', 'force_api', 'json').upper() != 'XML'

USING_JSON_API = _UsingJSONApi()


def _NormalizeURI(uri):
  """Normalizes the path component of a URI.

  Args:
    uri: URI to normalize.

  Returns:
    Normalized URI.

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
    *suffixes: Suffixes to append. For example, ObjectToUri(bucketuri, 'foo')
               would return the URI for a key name 'foo' inside the given
               bucket.

  Returns:
    Storage URI string.
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

# The mock storage service comes from the Boto library, but it is not
# distributed with Boto when installed as a package. To get around this, we
# copy the file to gslib/tests/mock_storage_service.py when building the gsutil
# package. Try and import from both places here.
# pylint: disable=g-import-not-at-top
try:
  from gslib.tests import mock_storage_service
except ImportError:
  try:
    from boto.tests.integration.s3 import mock_storage_service
  except ImportError:
    try:
      from tests.integration.s3 import mock_storage_service
    except ImportError:
      import mock_storage_service


class GSMockConnection(mock_storage_service.MockConnection):

  def __init__(self, *args, **kwargs):
    kwargs['provider'] = 'gs'
    super(GSMockConnection, self).__init__(*args, **kwargs)

mock_connection = GSMockConnection()


class GSMockBucketStorageUri(mock_storage_service.MockBucketStorageUri):

  def connect(self, access_key_id=None, secret_access_key=None):
    return mock_connection

  def compose(self, components, headers=None):
    """Dummy implementation to allow parallel uploads with tests."""
    return self.new_key()


def PerformsFileToObjectUpload(func):
  """Decorator indicating that a test uploads from a local file to an object.

  This forces the test to run once normally, and again with a special .boto
  config file that will ensure that the test follows the parallel composite
  upload code path.

  Args:
    func: Function to wrap.

  Returns:
    Wrapped function.
  """
  @functools.wraps(func)
  def Wrapper(*args, **kwargs):
    tmp_fd, tmp_filename = tempfile.mkstemp(prefix='gsutil-temp-cfg')
    os.close(tmp_fd)

    try:
      # Run the test normally once.
      func(*args, **kwargs)

      # Try again, forcing parallel composite uploads.
      boto.config.set('GSUtil', 'parallel_composite_upload_threshold', '1')
      with open(tmp_filename, 'w') as tmp_file:
        boto.config.write(tmp_file)

      with SetBotoConfigForTest(tmp_filename):
        func(*args, **kwargs)
    finally:
      try:
        os.remove(tmp_filename)
      except OSError:
        pass

  return Wrapper


@contextmanager
def SetBotoConfigForTest(boto_config_path):
  """Sets a given file as the boto config file for a single test."""
  # Setup for entering "with" block.
  try:
    old_boto_config_env_variable = os.environ['BOTO_CONFIG']
    boto_config_was_set = True
  except KeyError:
    boto_config_was_set = False
  os.environ['BOTO_CONFIG'] = boto_config_path

  try:
    yield
  finally:
    # Teardown for exiting "with" block.
    if boto_config_was_set:
      os.environ['BOTO_CONFIG'] = old_boto_config_env_variable
    else:
      os.environ.pop('BOTO_CONFIG', None)


def GetTestNames():
  """Returns a list of the names of the test modules in gslib.tests."""
  matcher = re.compile(r'^test_(?P<name>.*)$')
  names = []
  for _, modname, _ in pkgutil.iter_modules(gslib_tests.__path__):
    m = matcher.match(modname)
    if m:
      names.append(m.group('name'))
  return names
