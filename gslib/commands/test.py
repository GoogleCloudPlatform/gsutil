# Copyright 2011 Google Inc.
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

import subprocess
import unittest
import os
import re
import getpass
import platform

from gslib.command import Command
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.command import CONFIG_REQUIRED
from gslib.command import FILE_URIS_OK
from gslib.command import MAX_ARGS
from gslib.command import MIN_ARGS
from gslib.command import PROVIDER_URIS_OK
from gslib.command import SUPPORTED_SUB_ARGS
from gslib.command import URIS_START_ARG
from gslib.exception import CommandException
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HelpType
from gslib.help_provider import HELP_TYPE
from gslib.util import NO_MAX
from tests.s3.mock_storage_service import MockBucketStorageUri

_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil test [command command...]


<B>DESCRIPTION</B>
  The gsutil test command runs end-to-end tests of gsutil commands (i.e.,
  tests that send requests to the production service.  This stands in contrast
  to tests that use an in-memory mock storage service implementation (see
  "gsutil help dev" for more details on the latter).

  To run all end-to-end tests run the command with no arguments:

    gsutil test

  To see additional details for test failures:

    gsutil -d test

  To run tests for one or more individual commands add those commands as
  arguments. For example:

    gsutil test cp mv

  will run the cp and mv command tests.

  Note: the end-to-end tests are defined in the code for each command (e.g.,
  cp end-to-end tests are in gslib/commands/cp.py). See the comments around
  'test_steps' in each of the Command subclasses.
""")


class TestCommand(Command):
  """Implementation of gsutil test command."""

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'test',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : [],
    # Min number of args required by this command.
    MIN_ARGS : 0,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : NO_MAX,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : '',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : True,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 0,
    # True if must configure gsutil before running command.
    CONFIG_REQUIRED : True,
  }
  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'test',
    # List of help name aliases.
    HELP_NAME_ALIASES : [],
    # Type of help:
    HELP_TYPE : HelpType.COMMAND_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Run end to end gsutil tests',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }

  # Define constants & class attributes for command testing.
  username = getpass.getuser().lower()
  _test_prefix_file = 'gsutil_test_file_' + username + '_'
  _test_prefix_bucket = 'gsutil_test_bucket_' + username + '_'
  _test_prefix_object = 'gsutil_test_object_' + username + '_'
  # Replacement regexps for format specs in test_steps values.
  _test_replacements = {
    r'\$B(\d)' : _test_prefix_bucket + r'\1',
    r'\$O(\d)' : _test_prefix_object + r'\1',
    r'\$F(\d)' : _test_prefix_file + r'\1',
  }

  def _TestRunner(self, cmd, debug):
    """Run a test command in a subprocess and return result. If debugging
       requested, display the command, otherwise redirect stdout & stderr
       to /dev/null.
    """
    if not debug and '>' not in cmd:
      cmd += ' >/dev/null 2>&1'
    if debug:
      print 'cmd:', cmd
    return subprocess.call(cmd, shell=True)

  def global_setup(self, debug):
    """General test setup.

    For general testing use create three buckets, one empty, one
    containing one object and one containing two objects. Also create
    three files for general use.
    """
    print 'Global setup started...'

    # Build lists of buckets and files.
    bucket_list = ['gs://$B%d' % i for i in range(0, 10)]
    file_list = ['$F%d' % i for i in range(0, 3)]

    # Create test buckets.
    bucket_cmd = self.gsutil_cmd + ' mb ' + ' '.join(bucket_list)
    bucket_cmd = self.sub_format_specs(bucket_cmd)
    self._TestRunner(bucket_cmd, debug)

    # Create test objects - zero in first bucket, one in second, two in third.
    for i in range(0, 3):
      for j in range(0, i):
        object_cmd = 'echo test | ' + self.gsutil_cmd + \
                     ' cp - gs://$B%d/$O%d' % (i, j)
        object_cmd = self.sub_format_specs(object_cmd)
        self._TestRunner(object_cmd, debug)

    # Create three test files of size 10MB each.
    for file in file_list:
      file = self.sub_format_specs(file)
      f = open(file, 'w')
      f.write(os.urandom(10**6))
      f.close()

    print 'Global setup completed.'

  def global_teardown(self, debug):
    """General test cleanup.

    Remove all buckets, objects and files used by this test facility.
    """
    print 'Global teardown started...'
    # Build commands to remove objects, buckets and files.
    bucket_list = ['gs://$B%d' % i for i in range(0, 10)]
    object_list = ['gs://$B%d/*' % i for i in range(0, 10)]
    file_list = ['$F%d' % i for i in range(0, 10)]
    bucket_cmd = self.gsutil_cmd + ' rb ' + ' '.join(bucket_list)
    object_cmd = self.gsutil_cmd + ' rm -f ' + ' '.join(object_list)
    for f in file_list:
      f = self.sub_format_specs(f)
      if os.path.exists(f):
        os.unlink(f)

    # Substitute format specifiers ($Bn, $On, $Fn).
    bucket_cmd = self.sub_format_specs(bucket_cmd)
    if not debug:
      bucket_cmd += ' >/dev/null 2>&1'
    object_cmd = self.sub_format_specs(object_cmd)
    if not debug:
      object_cmd += ' >/dev/null 2>&1'

    # Run the commands.
    self._TestRunner(object_cmd, debug)
    self._TestRunner(bucket_cmd, debug)

    print 'Global teardown completed.'

  # Command entry point.
  def RunCommand(self):

    # To avoid testing aliases, we keep track of previous tests.
    already_tested = {}

    self.gsutil_cmd = ''
    # If running on Windows, invoke python interpreter explicitly.
    if platform.system() == "Windows":
      self.gsutil_cmd += 'python '
    # Add full path to gsutil to make sure we test the correct version.
    self.gsutil_cmd += os.path.join(self.gsutil_bin_dir, 'gsutil')

    # Set sim option on exec'ed commands if user requested mock provider.
    if issubclass(self.bucket_storage_uri_class, MockBucketStorageUri):
      self.gsutil_cmd += ' -s'

    # Instantiate test generator for creating test functions on the fly.
    gen = test_generator()

    # Set list of commands to test to include user supplied commands or all
    # commands if none specified by user ('gsutil test' implies test all).
    commands_to_test = []
    if self.args:
      for name in self.args:
        if name in self.command_runner.command_map:
          commands_to_test.append(name)
        else:
          raise CommandException('Test requested for unknown command %s.'
                                 % name)
    else:
      # No commands specified so test all commands.
      commands_to_test = self.command_runner.command_map.keys()

    for name in commands_to_test:
      cmd = self.command_runner.command_map[name]

      # Skip this command if test steps not defined or empty.
      if not hasattr(cmd, 'test_steps') or not cmd.test_steps:
        if self.debug:
          print 'Skipping %s command because no test steps defined.' % name
        continue

      # Skip aliases for commands we've already tested.
      if cmd in already_tested:
        continue
      already_tested[cmd] = 1

      # Run global test setup.
      self.global_setup(self.debug)

      # If command has a test_setup method, run per command setup here.
      if hasattr(cmd, 'test_setup'):
        cmd.test_setup(self.debug)

      # Instantiate a test suite, which we'll dynamically add tests to.
      suite = unittest.TestSuite()

      # Iterate over the entries in this command's test specification.
      for (cmdname, cmdline, expect_ret, diff) in cmd.test_steps:
        cmdline = cmdline.replace('gsutil ', self.gsutil_cmd + ' ')
        if platform.system() == 'Windows':
          cmdline = cmdline.replace('cat ', 'type ')

        # Store file names requested for diff.
        result_file = None
        expect_file = None
        if diff:
          (result_file, expect_file) = diff

        # Substitute format specifiers ($Bn, $On, $Fn).
        cmdline = self.sub_format_specs(cmdline)
        result_file = self.sub_format_specs(result_file)
        expect_file = self.sub_format_specs(expect_file)

        # Generate test function, wrap in a test case and add to test suite.
        func = gen.genTest(self._TestRunner, cmdline, expect_ret,
                            result_file, expect_file, self.debug)
        test_case = unittest.FunctionTestCase(func, description=cmdname)
        suite.addTest(test_case)

      # Run the tests we've just accumulated.
      print 'Running tests for', name, 'command.'
      unittest.TextTestRunner(verbosity=2).run(suite)

      # If command has a test_teardown method, run per command teardown here.
      if hasattr(cmd, 'test_teardown'):
        cmd.test_teardown(self.debug)

      # Run global test teardown.
      self.global_teardown(self.debug)

  def sub_format_specs(self, s):
    """Perform iterative regexp substitutions on passed string.

    This method iteratively substitutes values in a passed string,
    returning the modified string when done.
    """
    # Don't bother if the passed string is empty or None.
    if s:
      for (template, repl_str) in self._test_replacements.items():
        while re.search(template, s):
          # Keep substituting as long as the template is found.
          s = re.sub(template, repl_str, s)
    return s


class test_generator(unittest.TestCase):
  """Dynamic test generator for use with unittest module.

  This class is used to generate a test case function. It
  inherits from unittest.TestCase so that it has access to
  all the TestCase componentry (e.g. self.assertEqual, etc.).
  """

  def runTest():
    """Required method to instantiate unittest.TestCase derived class."""
    pass

  def genTest(self, runner, cmd, expect_ret, result_file, expect_file, debug):
    """Create and return a function to execute unittest module test cases.

    This method generates a test function based on the passed
    input and some inherited methods and returns the generated
    function to the caller.
    """

    def test_func():
      # Run the test command and capture the result in ret.
      ret = runner(cmd, debug)
      if expect_ret is not None:
        # If an expected return code was passed, make sure we got it.
        self.assertEqual(ret, expect_ret)
      if result_file and expect_file:
        # If cmd generated output, diff it against expected output.
        if platform.system() == 'Windows':
          diff_cmd = 'echo n | comp '
        else:
          diff_cmd = 'diff '
        diff_cmd += '%s %s' % (result_file, expect_file)
        diff_ret = runner(diff_cmd, debug)
        self.assertEqual(diff_ret, 0)
    # Return the generated function to the caller.
    return test_func

