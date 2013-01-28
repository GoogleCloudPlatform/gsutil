# Copyright 2013 Google Inc.
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

from tests.integration.s3 import mock_storage_service


CURDIR = os.path.abspath(os.path.dirname(__file__))
TESTS_DIR = os.path.split(CURDIR)[0]
GSLIB_DIR = os.path.split(TESTS_DIR)[0]
GSUTIL_DIR = os.path.split(GSLIB_DIR)[0]
BOTO_DIR = os.path.join(GSUTIL_DIR, 'boto')


class GSMockConnection(mock_storage_service.MockConnection):

  def __init__(self, *args, **kwargs):
    kwargs['provider'] = 'gs'
    super(GSMockConnection, self).__init__(*args, **kwargs)

mock_connection = GSMockConnection()


class GSMockBucketStorageUri(mock_storage_service.MockBucketStorageUri):

  def connect(self, access_key_id=None, secret_access_key=None):
    return mock_connection


@unittest.skipUnless(util.RUN_UNIT_TESTS,
                     'Not running integration tests.')
class GsUtilUnitTestCase(unittest.TestCase):
  """Base class for gsutil unit tests."""

  @classmethod
  def setUpClass(cls):
    cls.mock_bucket_storage_uri = GSMockBucketStorageUri
    cls.proj_id_handler = ProjectIdHandler()
    config_file_list = boto.pyami.config.BotoConfigLocations
    # Use "gsutil_test_commands" as a fake UserAgent. This value will never be
    # sent via HTTP because we're using MockStorageService here.
    cls.command_runner = CommandRunner(GSUTIL_DIR, BOTO_DIR,
                                   config_file_list, 'gsutil_test_commands',
                                   cls.mock_bucket_storage_uri)

  def RunCommand(self, command_name, args=None, headers=None, debug=0,
                 test_method=None, return_stdout=False):
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
      return_stdout: If true will save and return stdout produced by command.
    """
    if util.VERBOSE_OUTPUT:
      sys.stderr.write('\nRunning test of %s %s\n' %
                       (command_name, ' '.join(args)))
    if return_stdout:
      # Redirect stdout temporarily, to save output to a file.
      outfile = tempfile.mkstemp()[1]
    elif not util.VERBOSE_OUTPUT:
      outfile = os.devnull
    else:
      outfile = None

    stdout_sav = sys.stdout
    try:
      if outfile:
        fp = open(outfile, 'w')
        sys.stdout = fp
      self.command_runner.RunNamedCommand(
          command_name, args=args, headers=headers, debug=debug,
          parallel_operations=False, test_method=test_method)
    finally:
      if outfile:
        fp.close()
        sys.stdout = stdout_sav
        output = open(outfile, 'r').read()
        if return_stdout:
          os.unlink(outfile)
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
