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

"""Contains gsutil base unit test case class."""

import os.path
import sys
import tempfile

import boto

from gslib import wildcard_iterator
from gslib.command_runner import CommandRunner
from gslib.project_id import ProjectIdHandler
import gslib.tests.util as util
from gslib.tests.util import unittest
import base

# The mock storage service comes from the Boto library, but it is not
# distributed with Boto when installed as a package. To get around this, we
# copy the file to gslib/tests/mock_storage_service.py when building the gsutil
# package. Try and import from several places here to find it.
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

@unittest.skipUnless(util.RUN_UNIT_TESTS,
                     'Not running integration tests.')
class GsUtilUnitTestCase(base.GsUtilTestCase):
  """Base class for gsutil unit tests."""

  @classmethod
  def setUpClass(cls):
    base.GsUtilTestCase.setUpClass()
    cls.mock_bucket_storage_uri = GSMockBucketStorageUri
    cls.proj_id_handler = ProjectIdHandler()
    config_file_list = boto.pyami.config.BotoConfigLocations
    # Use "gsutil_test_commands" as a fake UserAgent. This value will never be
    # sent via HTTP because we're using MockStorageService here.
    cls.command_runner = CommandRunner(config_file_list,
                                       cls.mock_bucket_storage_uri)

  def setUp(self):
    super(GsUtilUnitTestCase, self).setUp()
    self.bucket_uris = []

  def RunCommand(self, command_name, args=None, headers=None, debug=0,
                 test_method=None, return_stdout=False, cwd=None):
    """
    Method for calling gslib.command_runner.CommandRunner, passing
    parallel_operations=False for all tests, optionally saving/returning stdout
    output. We run all tests multi-threaded, to exercise those more complicated
    code paths.
    TODO: change to run with parallel_operations=True for all tests. At
    present when you do this it causes many test failures.

    Args:
      command_name: The name of the command being run.
      args: Command-line args (arg0 = actual arg, not command name ala bash).
      headers: Dictionary containing optional HTTP headers to pass to boto.
      debug: Debug level to pass in to boto connection (range 0..3).
      parallel_operations: Should command operations be executed in parallel?
      test_method: Optional general purpose method for testing purposes.
                   Application and semantics of this method will vary by
                   command and test type.
      cwd: The working directory that should be switched to before running the
           command. The working directory will be reset back to its original
           value after running the command. If not specified, the working
           directory is left unchanged.
      return_stdout: If true will save and return stdout produced by command.
    """
    if util.VERBOSE_OUTPUT:
      sys.stderr.write('\nRunning test of %s %s\n' %
                       (command_name, ' '.join(args)))
    if return_stdout:
      # Redirect stdout temporarily, to save output to a file.
      fh, outfile = tempfile.mkstemp()
      os.close(fh)
    elif not util.VERBOSE_OUTPUT:
      outfile = os.devnull
    else:
      outfile = None

    stdout_sav = sys.stdout
    output = None
    cwd_sav = None
    try:
      cwd_sav = os.getcwd()
    except OSError:
      # This can happen if the current working directory no longer exists.
      pass
    try:
      if outfile:
        fp = open(outfile, 'w')
        sys.stdout = fp
      if cwd:
        os.chdir(cwd)
      self.command_runner.RunNamedCommand(
          command_name, args=args, headers=headers, debug=debug,
          parallel_operations=False, test_method=test_method)
    finally:
      if cwd and cwd_sav:
        os.chdir(cwd_sav)
      if outfile:
        fp.close()
        sys.stdout = stdout_sav
        with open(outfile, 'r') as f:
          output = f.read()
        if return_stdout:
          os.unlink(outfile)

    if output is not None and return_stdout:
      return output

  @classmethod
  def _test_wildcard_iterator(cls, uri_or_str, debug=0):
    """
    Convenience method for instantiating a testing instance of
    WildCardIterator, without having to specify all the params of that class
    (like bucket_storage_uri_class=mock_storage_service.MockBucketStorageUri).
    Also naming the factory method this way makes it clearer in the test code
    that WildcardIterator needs to be set up for testing.

    Args are same as for wildcard_iterator.wildcard_iterator(), except there's
    no bucket_storage_uri_class arg.

    Returns:
      WildcardIterator.IterUris(), over which caller can iterate.
    """
    return wildcard_iterator.wildcard_iterator(
        uri_or_str, cls.proj_id_handler, cls.mock_bucket_storage_uri,
        debug=debug)

  @staticmethod
  def _test_storage_uri(uri_str, default_scheme='file', debug=0,
                        validate=True):
    """
    Convenience method for instantiating a testing
    instance of StorageUri, without having to specify
    bucket_storage_uri_class=mock_storage_service.MockBucketStorageUri.
    Also naming the factory method this way makes it clearer in the test
    code that StorageUri needs to be set up for testing.

    Args, Returns, and Raises are same as for boto.storage_uri(), except there's
    no bucket_storage_uri_class arg.
    """
    return boto.storage_uri(uri_str, default_scheme, debug, validate,
                            GSMockBucketStorageUri)

  def CreateBucket(self, bucket_name=None, test_objects=0, storage_class=None):
    """Creates a test bucket.

    The bucket and all of its contents will be deleted after the test.

    Args:
      bucket_name: Create the bucket with this name. If not provided, a
                   temporary test bucket name is constructed.
      test_objects: The number of objects that should be placed in the bucket or
                    a list of object names to place in the bucket. Defaults to
                    0.
      storage_class: storage class to use. If not provided we us standard.

    Returns:
      StorageUri for the created bucket.
    """
    bucket_name = bucket_name or self.MakeTempName('bucket')
    bucket_uri = boto.storage_uri(
        'gs://%s' % bucket_name.lower(),
        suppress_consec_slashes=False,
        bucket_storage_uri_class=GSMockBucketStorageUri)
    bucket_uri.create_bucket(storage_class=storage_class)
    self.bucket_uris.append(bucket_uri)
    try:
      iter(test_objects)
    except TypeError:
      test_objects = [self.MakeTempName('obj') for _ in range(test_objects)]
    for i, name in enumerate(test_objects):
      self.CreateObject(bucket_uri=bucket_uri, object_name=name,
                        contents='test %d' % i)
    return bucket_uri

  def CreateObject(self, bucket_uri=None, object_name=None, contents=None):
    """Creates a test object.

    Args:
      bucket: The URI of the bucket to place the object in. If not specified, a
              new temporary bucket is created.
      object_name: The name to use for the object. If not specified, a temporary
                   test object name is constructed.
      contents: The contents to write to the object. If not specified, the key
                is not written to, which means that it isn't actually created
                yet on the server.

    Returns:
      A StorageUri for the created object.
    """
    bucket_uri = bucket_uri or self.CreateBucket()
    object_name = object_name or self.MakeTempName('obj')
    key_uri = bucket_uri.clone_replace_name(object_name)
    if contents is not None:
      key_uri.set_contents_from_string(contents)
    return key_uri
