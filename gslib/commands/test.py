# Copyright 2011 Google Inc. All Rights Reserved.
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
"""Implementation of gsutil test command."""

from __future__ import absolute_import

import logging
import subprocess
import sys
import textwrap
import time

import gslib
from gslib.command import Command
from gslib.command import ResetFailureCount
from gslib.exception import CommandException
import gslib.tests as tests
from gslib.util import IS_WINDOWS
from gslib.util import NO_MAX


# For Python 2.6, unittest2 is required to run the tests. If it's not available,
# display an error if the test command is run instead of breaking the whole
# program.
# pylint: disable=g-import-not-at-top
try:
  from gslib.tests.util import GetTestNames
  from gslib.tests.util import unittest
except ImportError as e:
  if 'unittest2' in str(e):
    unittest = None
    GetTestNames = None  # pylint: disable=invalid-name
  else:
    raise


DEFAULT_TEST_PARALLEL_PROCESSES = 15
DEFAULT_S3_TEST_PARALLEL_PROCESSES = 50


_DETAILED_HELP_TEXT = ("""
<B>SYNOPSIS</B>
  gsutil test [-l] [-u] [-f] [command command...]


<B>DESCRIPTION</B>
  The gsutil test command runs the gsutil unit tests and integration tests.
  The unit tests use an in-memory mock storage service implementation, while
  the integration tests send requests to the production service using the
  preferred API set in the boto configuration file (see "gsutil help apis" for
  details).

  To run both the unit tests and integration tests, run the command with no
  arguments:

    gsutil test

  To run the unit tests only (which run quickly):

    gsutil test -u

  To run integration tests in parallel (CPU-intensive but much faster):

    gsutil -m test

  To limit the number of tests run in parallel to 10 at a time:

    gsutil -m test -p 10

  To see additional details for test failures:

    gsutil -d test

  To have the tests stop running immediately when an error occurs:

    gsutil test -f

  To run tests for one or more individual commands add those commands as
  arguments. For example, the following command will run the cp and mv command
  tests:

    gsutil test cp mv

  To list available tests, run the test command with the -l argument:

    gsutil test -l

  The tests are defined in the code under the gslib/tests module. Each test
  file is of the format test_[name].py where [name] is the test name you can
  pass to this command. For example, running "gsutil test ls" would run the
  tests in "gslib/tests/test_ls.py".

  You can also run an individual test class or function name by passing the
  test module followed by the class name and optionally a test name. For
  example, to run the an entire test class by name:

    gsutil test naming.GsutilNamingTests

  or an individual test function:

    gsutil test cp.TestCp.test_streaming

  You can list the available tests under a module or class by passing arguments
  with the -l option. For example, to list all available test functions in the
  cp module:

    gsutil test -l cp


<B>OPTIONS</B>
  -f          Exit on first test failure.

  -l          List available tests.

  -p          Run at most N tests in parallel. The default value is %d.

  -s          Run tests against S3 instead of GS.

  -u          Only run unit tests.
""" % DEFAULT_TEST_PARALLEL_PROCESSES)


def MakeCustomTestResultClass(total_tests):
  """Creates a closure of CustomTestResult.

  Args:
    total_tests: The total number of tests being run.

  Returns:
    An instance of CustomTestResult.
  """

  class CustomTestResult(unittest.TextTestResult):
    """A subclass of unittest.TextTestResult that prints a progress report."""

    def startTest(self, test):
      super(CustomTestResult, self).startTest(test)
      if self.dots:
        test_id = '.'.join(test.id().split('.')[-2:])
        message = ('\r%d/%d finished - E[%d] F[%d] s[%d] - %s' % (
            self.testsRun, total_tests, len(self.errors),
            len(self.failures), len(self.skipped), test_id))
        message = message[:73]
        message = message.ljust(73)
        self.stream.write('%s - ' % message)

  return CustomTestResult


def GetTestNamesFromSuites(test_suite):
  """Takes a list of test suites and returns a list of contained test names."""
  suites = [test_suite]
  test_names = []
  while suites:
    suite = suites.pop()
    for test in suite:
      if isinstance(test, unittest.TestSuite):
        suites.append(test)
      else:
        test_names.append(test.id()[len('gslib.tests.test_'):])
  return test_names


# pylint: disable=protected-access
# Need to get into the guts of unittest to evaluate test cases for parallelism.
def TestCaseToName(test_case):
  """Converts a python.unittest to its gsutil test-callable name."""
  return (str(test_case.__class__).split('\'')[1] + '.' +
          test_case._testMethodName)


# pylint: disable=protected-access
# Need to get into the guts of unittest to evaluate test cases for parallelism.
def SplitParallelizableTestSuite(test_suite):
  """Splits a test suite into groups with different running properties.

  Args:
    test_suite: A python unittest test suite.

  Returns:
    3-part tuple of lists of test names:
    (tests that must be run sequentially,
     integration tests that can run in parallel,
     unit tests that can be run in parallel)
  """
  # pylint: disable=import-not-at-top
  # Need to import this after test globals are set so that skip functions work.
  from gslib.tests.testcase.unit_testcase import GsUtilUnitTestCase
  sequential_tests = []
  parallelizable_integration_tests = []
  parallelizable_unit_tests = []

  items_to_evaluate = [test_suite]
  cases_to_evaluate = []
  # Expand the test suites into individual test cases:
  while items_to_evaluate:
    suite_or_case = items_to_evaluate.pop()
    if isinstance(suite_or_case, unittest.suite.TestSuite):
      for item in suite_or_case._tests:
        items_to_evaluate.append(item)
    elif isinstance(suite_or_case, unittest.TestCase):
      cases_to_evaluate.append(suite_or_case)

  for test_case in cases_to_evaluate:
    test_method = getattr(test_case, test_case._testMethodName, None)
    if not getattr(test_method, 'is_parallelizable', True):
      sequential_tests.append(TestCaseToName(test_case))
    elif isinstance(test_case, GsUtilUnitTestCase):
      parallelizable_unit_tests.append(TestCaseToName(test_case))
    else:
      parallelizable_integration_tests.append(TestCaseToName(test_case))

  return (sorted(sequential_tests),
          sorted(parallelizable_integration_tests),
          sorted(parallelizable_unit_tests))


def CountFalseInList(input_list):
  """Counts number of falses in the input list."""
  num_false = 0
  for item in input_list:
    if not item:
      num_false += 1
  return num_false


def CreateTestProcesses(parallel_tests, test_index, process_list, process_done,
                        max_parallel_tests):
  """Creates test processes to run tests in parallel.

  Args:
    parallel_tests: List of all parallel tests.
    test_index: List index of last created test before this function call.
    process_list: List of running subprocesses. Created processes are appended
                  to this list.
    process_done: List of booleans indicating process completion. One 'False'
                  will be added per process created.
    max_parallel_tests: Maximum number of tests to run in parallel.

  Returns:
    Index of last created test.
  """
  orig_test_index = test_index
  executable_prefix = [sys.executable] if sys.executable and IS_WINDOWS else []
  s3_argument = ['-s'] if tests.util.RUN_S3_TESTS else []

  process_create_start_time = time.time()
  last_log_time = process_create_start_time
  while (CountFalseInList(process_done) < max_parallel_tests and
         test_index < len(parallel_tests)):
    process_list.append(subprocess.Popen(
        executable_prefix + [gslib.GSUTIL_PATH] + ['test'] + s3_argument +
        [parallel_tests[test_index][len('gslib.tests.test_'):]],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE))
    test_index += 1
    process_done.append(False)
    if time.time() - last_log_time > 5:
      print ('Created %d new processes (total %d/%d created)' %
             (test_index - orig_test_index, len(process_list),
              len(parallel_tests)))
      last_log_time = time.time()
  if test_index == len(parallel_tests):
    print ('Test process creation finished (%d/%d created)' %
           (len(process_list), len(parallel_tests)))
  return test_index


class TestCommand(Command):
  """Implementation of gsutil test command."""

  # Command specification. See base class for documentation.
  command_spec = Command.CreateCommandSpec(
      'test',
      command_name_aliases=[],
      min_args=0,
      max_args=NO_MAX,
      supported_sub_args='uflp:s',
      file_url_ok=True,
      provider_url_ok=False,
      urls_start_arg=0,
  )
  # Help specification. See help_provider.py for documentation.
  help_spec = Command.HelpSpec(
      help_name='test',
      help_name_aliases=[],
      help_type='command_help',
      help_one_line_summary='Run gsutil tests',
      help_text=_DETAILED_HELP_TEXT,
      subcommand_help_text={},
  )

  def RunCommand(self):
    """Command entry point for the test command."""
    if not unittest:
      raise CommandException('On Python 2.6, the unittest2 module is required '
                             'to run the gsutil tests.')

    failfast = False
    list_tests = False
    max_parallel_tests = DEFAULT_TEST_PARALLEL_PROCESSES
    if self.sub_opts:
      for o, a in self.sub_opts:
        if o == '-u':
          tests.util.RUN_INTEGRATION_TESTS = False
        elif o == '-f':
          failfast = True
        elif o == '-l':
          list_tests = True
        elif o == '-p':
          max_parallel_tests = long(a)
        elif o == '-s':
          if not tests.util.HAS_S3_CREDS:
            raise CommandException('S3 tests require S3 credentials. Please '
                                   'add appropriate credentials to your .boto '
                                   'file and re-run.')
          tests.util.RUN_S3_TESTS = True

    if self.parallel_operations:
      if IS_WINDOWS:
        raise CommandException('-m test is not supported on Windows.')
      elif (tests.util.RUN_S3_TESTS and
            max_parallel_tests > DEFAULT_S3_TEST_PARALLEL_PROCESSES):
        self.logger.warn('Reducing parallel tests to %d due to S3 '
                         'maximum bucket limitations.' %
                         DEFAULT_S3_TEST_PARALLEL_PROCESSES)
        max_parallel_tests = DEFAULT_S3_TEST_PARALLEL_PROCESSES

    test_names = sorted(GetTestNames())
    if list_tests and not self.args:
      print 'Found %d test names:' % len(test_names)
      print ' ', '\n  '.join(sorted(test_names))
      return 0

    # Set list of commands to test if supplied.
    if self.args:
      commands_to_test = []
      for name in self.args:
        if name in test_names or name.split('.')[0] in test_names:
          commands_to_test.append('gslib.tests.test_%s' % name)
        else:
          commands_to_test.append(name)
    else:
      commands_to_test = ['gslib.tests.test_%s' % name for name in test_names]

    # Installs a ctrl-c handler that tries to cleanly tear down tests.
    unittest.installHandler()

    loader = unittest.TestLoader()

    if commands_to_test:
      try:
        suite = loader.loadTestsFromNames(commands_to_test)
      except (ImportError, AttributeError) as e:
        raise CommandException('Invalid test argument name: %s' % e)

    if list_tests:
      test_names = GetTestNamesFromSuites(suite)
      print 'Found %d test names:' % len(test_names)
      print ' ', '\n  '.join(sorted(test_names))
      return 0

    if logging.getLogger().getEffectiveLevel() <= logging.INFO:
      verbosity = 1
    else:
      verbosity = 2
      logging.disable(logging.ERROR)

    num_parallel_failures = 0
    if self.parallel_operations:
      sequential_tests, parallel_integration_tests, parallel_unit_tests = (
          SplitParallelizableTestSuite(suite))

      sequential_start_time = time.time()
      # TODO: For now, run unit tests sequentially because they are fast.
      # We could potentially shave off several seconds of execution time
      # by executing them in parallel with the integration tests.
      # Note that parallelism_framework unit tests cannot be run in a
      # subprocess.
      print 'Running %d tests sequentially.' % (len(sequential_tests) +
                                                len(parallel_unit_tests))
      sequential_tests_to_run = sequential_tests + parallel_unit_tests
      suite = loader.loadTestsFromNames(
          sorted([test_name for test_name in sequential_tests_to_run]))
      num_sequential_tests = suite.countTestCases()
      resultclass = MakeCustomTestResultClass(num_sequential_tests)
      runner = unittest.TextTestRunner(verbosity=verbosity,
                                       resultclass=resultclass,
                                       failfast=failfast)
      ret = runner.run(suite)

      num_parallel_tests = len(parallel_integration_tests)
      max_processes = min(max_parallel_tests, num_parallel_tests)

      print ('\n'.join(textwrap.wrap(
          'Running %d integration tests in parallel mode (%d processes)! '
          'Please be patient while your CPU is incinerated. '
          'If your machine becomes unresponsive, consider reducing '
          'the amount of parallel test processes by running '
          '\'gsutil -m test -p <num_processes>\'.' %
          (num_parallel_tests, max_processes))))
      process_list = []
      process_done = []
      process_results = []  # Tuples of (name, return code, stdout, stderr)
      hang_detection_counter = 0
      completed_as_of_last_log = 0
      parallel_start_time = last_log_time = time.time()
      test_index = CreateTestProcesses(
          parallel_integration_tests, 0, process_list, process_done,
          max_parallel_tests)
      while len(process_results) < num_parallel_tests:
        for proc_num in xrange(len(process_list)):
          if process_done[proc_num] or process_list[proc_num].poll() is None:
            continue
          process_done[proc_num] = True
          stdout, stderr = process_list[proc_num].communicate()
          # TODO: Differentiate test failures from errors.
          if process_list[proc_num].returncode != 0:
            num_parallel_failures += 1
          process_results.append((parallel_integration_tests[proc_num],
                                  process_list[proc_num].returncode,
                                  stdout, stderr))
        if len(process_list) < num_parallel_tests:
          test_index = CreateTestProcesses(
              parallel_integration_tests, test_index, process_list,
              process_done, max_parallel_tests)
        if len(process_results) < num_parallel_tests:
          if time.time() - last_log_time > 5:
            print '%d/%d finished - %d failures' % (
                len(process_results), num_parallel_tests, num_parallel_failures)
            if len(process_results) == completed_as_of_last_log:
              hang_detection_counter += 1
            else:
              completed_as_of_last_log = len(process_results)
              hang_detection_counter = 0
            if hang_detection_counter > 4:
              still_running = []
              for proc_num in xrange(len(process_list)):
                if not process_done[proc_num]:
                  still_running.append(parallel_integration_tests[proc_num])
              print 'Still running: %s' % still_running
            last_log_time = time.time()
          time.sleep(1)
      process_run_finish_time = time.time()
      if num_parallel_failures:
        for result in process_results:
          if result[1] != 0:
            new_stderr = result[3].split('\n')
            print 'Results for failed test %s:' % result[0]
            for line in new_stderr:
              print line

      # TODO: Properly track test skips.
      print 'Parallel tests complete. Success: %s Fail: %s' % (
          num_parallel_tests - num_parallel_failures, num_parallel_failures)
      print (
          'Ran %d tests in %.3fs (%d sequential in %.3fs, %d parallel in %.3fs)'
          % (num_parallel_tests + num_sequential_tests,
             float(process_run_finish_time - sequential_start_time),
             num_sequential_tests,
             float(parallel_start_time - sequential_start_time),
             num_parallel_tests,
             float(process_run_finish_time - parallel_start_time)))
      print
      if not num_parallel_failures and ret.wasSuccessful():
        print 'OK'
      else:
        if num_parallel_failures:
          print 'FAILED (parallel tests)'
        if not ret.wasSuccessful():
          print 'FAILED (sequential tests)'
    else:
      total_tests = suite.countTestCases()
      resultclass = MakeCustomTestResultClass(total_tests)

      runner = unittest.TextTestRunner(verbosity=verbosity,
                                       resultclass=resultclass,
                                       failfast=failfast)
      ret = runner.run(suite)

    if ret.wasSuccessful() and not num_parallel_failures:
      ResetFailureCount()
      return 0
    return 1
