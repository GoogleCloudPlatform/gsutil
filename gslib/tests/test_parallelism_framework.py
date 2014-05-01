# Copyright 2013 Google Inc. All Rights Reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish, dis-
# tribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the fol-
# lowing conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABIL-
# ITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT
# SHALL THE AUTHOR BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.
"""Unit tests for gsutil parallelism framework."""

import functools
import signal

from boto.storage_uri import BucketStorageUri
from gslib import cs_api_map
from gslib.command import Command
from gslib.command import CreateGsutilLogger
from gslib.command import DummyArgChecker
import gslib.tests.testcase as testcase
from gslib.tests.util import unittest
from gslib.util import IS_WINDOWS
from gslib.util import MultiprocessingIsAvailable


def Timeout(func):
  """Decorator used to provide a timeout for functions."""
  @functools.wraps(func)
  def Wrapper(*args, **kwargs):
    if not IS_WINDOWS:
      signal.signal(signal.SIGALRM, _HandleAlarm)
      signal.alarm(5)
    try:
      func(*args, **kwargs)
    finally:
      if not IS_WINDOWS:
        signal.alarm(0)  # Cancel the alarm.
  return Wrapper


# pylint: disable=unused-argument
def _HandleAlarm(signal_num, cur_stack_frame):
  raise Exception('Test timed out.')


class CustomException(Exception):

  def __init__(self, exception_str):
    super(CustomException, self).__init__(exception_str)


def _ReturnOneValue(cls, args, thread_state=None):
  return 1


def _FailureFunc(cls, args, thread_state=None):
  raise CustomException('Failing on purpose.')


def _FailingExceptionHandler(cls, e):
  cls.failure_count += 1
  raise CustomException('Exception handler failing on purpose.')


def _ExceptionHandler(cls, e):
  cls.logger.exception(e)
  cls.failure_count += 1


def _IncrementByLength(cls, args, thread_state=None):
  cls.arg_length_sum += len(args)


def _AdjustProcessCountIfWindows(process_count):
  if IS_WINDOWS:
    return 1
  else:
    return process_count


def _ReApplyWithReplicatedArguments(cls, args, thread_state=None):
  """Calls Apply with arguments repeated seven times."""
  new_args = [args] * 7
  process_count = _AdjustProcessCountIfWindows(2)
  return_values = cls.Apply(_PerformNRecursiveCalls, new_args,
                            _ExceptionHandler, arg_checker=DummyArgChecker,
                            process_count=process_count, thread_count=2,
                            should_return_results=True)
  ret = sum(return_values)

  return_values = cls.Apply(_ReturnOneValue, new_args,
                            _ExceptionHandler, arg_checker=DummyArgChecker,
                            process_count=process_count, thread_count=2,
                            should_return_results=True)

  return len(return_values) + ret


def _PerformNRecursiveCalls(cls, args, thread_state=None):
  process_count = _AdjustProcessCountIfWindows(2)
  return_values = cls.Apply(_ReturnOneValue, [()] * args, _ExceptionHandler,
                            arg_checker=DummyArgChecker,
                            process_count=process_count, thread_count=2,
                            should_return_results=True)
  return len(return_values)


def _SkipEvenNumbersArgChecker(cls, arg):
  return arg % 2 != 0


class FailingIterator(object):

  def __init__(self, size, failure_indices):
    self.size = size
    self.failure_indices = failure_indices
    self.current_index = 0

  def __iter__(self):
    return self

  def next(self):
    if self.current_index == self.size:
      raise StopIteration('')
    elif self.current_index in self.failure_indices:
      self.current_index += 1
      raise CustomException(
          'Iterator failing on purpose at index %d.' % self.current_index)
    else:
      self.current_index += 1
      return self.current_index - 1


class FakeCommand(Command):
  """Fake command class for overriding command instance state."""
  command_spec = Command.CreateCommandSpec(
      'fake',
      command_name_aliases=[],
  )
  # Help specification. See help_provider.py for documentation.
  help_spec = Command.HelpSpec(
      help_name='fake',
      help_name_aliases=[],
      help_type='command_help',
      help_one_line_summary='Something to take up space.',
      help_text='Something else to take up space.',
      subcommand_help_text={},
  )

  def __init__(self, do_parallel):
    self.bucket_storage_uri_class = BucketStorageUri
    support_map = {
        'gs': ['JSON'],
        's3': ['XML']
    }
    default_map = {
        'gs': 'JSON',
        's3': 'XML'
    }
    self.gsutil_api_map = cs_api_map.GsutilApiMapFactory.GetApiMap(
        cs_api_map.GsutilApiClassMapFactory, support_map, default_map)
    self.logger = CreateGsutilLogger('FakeCommand')
    self.parallel_operations = do_parallel
    self.failure_count = 0
    self.multiprocessing_is_available = MultiprocessingIsAvailable()[0]
    self.debug = 0


class FakeCommandWithoutMultiprocessingModule(FakeCommand):

  def __init__(self, do_parallel):
    super(FakeCommandWithoutMultiprocessingModule, self).__init__(do_parallel)
    self.multiprocessing_is_available = False


# TODO: Figure out a good way to test that ctrl+C really stops execution,
#       and also that ctrl+C works when there are still tasks enqueued.
class TestParallelismFramework(testcase.GsUtilUnitTestCase):
  """gsutil parallelism framework test suite."""

  command_class = FakeCommand

  def _RunApply(self, func, args_iterator, process_count, thread_count,
                command_inst=None, shared_attrs=None, fail_on_error=False,
                thr_exc_handler=None, arg_checker=DummyArgChecker):
    command_inst = command_inst or self.command_class(True)
    exception_handler = thr_exc_handler or _ExceptionHandler

    return command_inst.Apply(func, args_iterator, exception_handler,
                              thread_count=thread_count,
                              process_count=process_count,
                              arg_checker=arg_checker,
                              should_return_results=True,
                              shared_attrs=shared_attrs,
                              fail_on_error=fail_on_error)

  def testBasicApplySingleProcessSingleThread(self):
    self._TestBasicApply(1, 1)

  def testBasicApplySingleProcessMultiThread(self):
    self._TestBasicApply(1, 10)

  @unittest.skipIf(IS_WINDOWS, 'Multiprocessing is not supported on Windows')
  def testBasicApplyMultiProcessSingleThread(self):
    self._TestBasicApply(10, 1)

  @unittest.skipIf(IS_WINDOWS, 'Multiprocessing is not supported on Windows')
  def testBasicApplyMultiProcessMultiThread(self):
    self._TestBasicApply(10, 10)

  @Timeout
  def _TestBasicApply(self, process_count, thread_count):
    args = [()] * (17 * process_count * thread_count + 1)

    results = self._RunApply(_ReturnOneValue, args, process_count, thread_count)
    self.assertEqual(len(args), len(results))

  def testIteratorFailureSingleProcessSingleThread(self):
    self._TestIteratorFailure(1, 1)

  def testIteratorFailureSingleProcessMultiThread(self):
    self._TestIteratorFailure(1, 10)

  @unittest.skipIf(IS_WINDOWS, 'Multiprocessing is not supported on Windows')
  def testIteratorFailureMultiProcessSingleThread(self):
    self._TestIteratorFailure(10, 1)

  @unittest.skipIf(IS_WINDOWS, 'Multiprocessing is not supported on Windows')
  def testIteratorFailureMultiProcessMultiThread(self):
    self._TestIteratorFailure(10, 10)

  @Timeout
  def _TestIteratorFailure(self, process_count, thread_count):
    """Tests apply with a failing iterator."""
    # Tests for fail_on_error == False.

    args = FailingIterator(10, [0])
    results = self._RunApply(_ReturnOneValue, args, process_count, thread_count)
    self.assertEqual(9, len(results))

    args = FailingIterator(10, [5])
    results = self._RunApply(_ReturnOneValue, args, process_count, thread_count)
    self.assertEqual(9, len(results))

    args = FailingIterator(10, [9])
    results = self._RunApply(_ReturnOneValue, args, process_count, thread_count)
    self.assertEqual(9, len(results))

    if process_count * thread_count > 1:
      # In this case, we should ignore the fail_on_error flag.
      args = FailingIterator(10, [9])
      results = self._RunApply(_ReturnOneValue, args, process_count,
                               thread_count, fail_on_error=True)
      self.assertEqual(9, len(results))

    args = FailingIterator(10, range(10))
    results = self._RunApply(_ReturnOneValue, args, process_count, thread_count)
    self.assertEqual(0, len(results))

    args = FailingIterator(0, [])
    results = self._RunApply(_ReturnOneValue, args, process_count, thread_count)
    self.assertEqual(0, len(results))

  def testTestSharedAttrsWorkSingleProcessSingleThread(self):
    self._TestSharedAttrsWork(1, 1)

  def testTestSharedAttrsWorkSingleProcessMultiThread(self):
    self._TestSharedAttrsWork(1, 10)

  @unittest.skipIf(IS_WINDOWS, 'Multiprocessing is not supported on Windows')
  def testTestSharedAttrsWorkMultiProcessSingleThread(self):
    self._TestSharedAttrsWork(10, 1)

  @unittest.skipIf(IS_WINDOWS, 'Multiprocessing is not supported on Windows')
  def testTestSharedAttrsWorkMultiProcessMultiThread(self):
    self._TestSharedAttrsWork(10, 10)

  @Timeout
  def _TestSharedAttrsWork(self, process_count, thread_count):
    """Tests that Apply successfully uses shared_attrs."""
    command_inst = self.command_class(True)
    command_inst.arg_length_sum = 19
    args = ['foo', ['bar', 'baz'], [], ['x', 'y'], [], 'abcd']
    self._RunApply(_IncrementByLength, args, process_count,
                   thread_count, command_inst=command_inst,
                   shared_attrs=['arg_length_sum'])
    expected_sum = 19
    for arg in args:
      expected_sum += len(arg)
    self.assertEqual(expected_sum, command_inst.arg_length_sum)

    # Test that shared variables work when the iterator fails.
    command_inst = self.command_class(True)
    args = FailingIterator(10, [1, 3, 5])
    self._RunApply(_ReturnOneValue, args, process_count, thread_count,
                   command_inst=command_inst, shared_attrs=['failure_count'])
    self.assertEqual(3, command_inst.failure_count)

  def testThreadsSurviveExceptionsInFuncSingleProcessSingleThread(self):
    self._TestThreadsSurviveExceptionsInFunc(1, 1)

  def testThreadsSurviveExceptionsInFuncSingleProcessMultiThread(self):
    self._TestThreadsSurviveExceptionsInFunc(1, 10)

  @unittest.skipIf(IS_WINDOWS, 'Multiprocessing is not supported on Windows')
  def testThreadsSurviveExceptionsInFuncMultiProcessSingleThread(self):
    self._TestThreadsSurviveExceptionsInFunc(10, 1)

  @unittest.skipIf(IS_WINDOWS, 'Multiprocessing is not supported on Windows')
  def testThreadsSurviveExceptionsInFuncMultiProcessMultiThread(self):
    self._TestThreadsSurviveExceptionsInFunc(10, 10)

  @Timeout
  def _TestThreadsSurviveExceptionsInFunc(self, process_count, thread_count):
    command_inst = self.command_class(True)
    args = ([()] * 5)
    self._RunApply(_FailureFunc, args, process_count, thread_count,
                   command_inst=command_inst, shared_attrs=['failure_count'],
                   thr_exc_handler=_FailingExceptionHandler)
    self.assertEqual(len(args), command_inst.failure_count)

  def testThreadsSurviveExceptionsInHandlerSingleProcessSingleThread(self):
    self._TestThreadsSurviveExceptionsInHandler(1, 1)

  def testThreadsSurviveExceptionsInHandlerSingleProcessMultiThread(self):
    self._TestThreadsSurviveExceptionsInHandler(1, 10)

  @unittest.skipIf(IS_WINDOWS, 'Multiprocessing is not supported on Windows')
  def testThreadsSurviveExceptionsInHandlerMultiProcessSingleThread(self):
    self._TestThreadsSurviveExceptionsInHandler(10, 1)

  @unittest.skipIf(IS_WINDOWS, 'Multiprocessing is not supported on Windows')
  def testThreadsSurviveExceptionsInHandlerMultiProcessMultiThread(self):
    self._TestThreadsSurviveExceptionsInHandler(10, 10)

  @Timeout
  def _TestThreadsSurviveExceptionsInHandler(self, process_count, thread_count):
    command_inst = self.command_class(True)
    args = ([()] * 5)
    self._RunApply(_FailureFunc, args, process_count, thread_count,
                   command_inst=command_inst, shared_attrs=['failure_count'],
                   thr_exc_handler=_FailingExceptionHandler)
    self.assertEqual(len(args), command_inst.failure_count)

  @Timeout
  def testFailOnErrorFlag(self):
    """Tests that fail_on_error produces the correct exception on failure."""
    def _ExpectCustomException(test_func):
      try:
        test_func()
        self.fail(
            'Setting fail_on_error should raise any exception encountered.')
      except CustomException, e:
        pass
      except Exception, e:
        self.fail('Got unexpected error: ' + str(e))

    def _RunFailureFunc():
      command_inst = self.command_class(True)
      args = ([()] * 5)
      self._RunApply(_FailureFunc, args, 1, 1, command_inst=command_inst,
                     shared_attrs=['failure_count'], fail_on_error=True)
    _ExpectCustomException(_RunFailureFunc)

    def _RunFailingIteratorFirstPosition():
      args = FailingIterator(10, [0])
      results = self._RunApply(_ReturnOneValue, args, 1, 1, fail_on_error=True)
      self.assertEqual(0, len(results))
    _ExpectCustomException(_RunFailingIteratorFirstPosition)

    def _RunFailingIteratorPositionMiddlePosition():
      args = FailingIterator(10, [5])
      results = self._RunApply(_ReturnOneValue, args, 1, 1, fail_on_error=True)
      self.assertEqual(5, len(results))
    _ExpectCustomException(_RunFailingIteratorPositionMiddlePosition)

    def _RunFailingIteratorLastPosition():
      args = FailingIterator(10, [9])
      results = self._RunApply(_ReturnOneValue, args, 1, 1, fail_on_error=True)
      self.assertEqual(9, len(results))
    _ExpectCustomException(_RunFailingIteratorLastPosition)

    def _RunFailingIteratorMultiplePositions():
      args = FailingIterator(10, [1, 3, 5])
      results = self._RunApply(_ReturnOneValue, args, 1, 1, fail_on_error=True)
      self.assertEqual(1, len(results))
    _ExpectCustomException(_RunFailingIteratorMultiplePositions)

  def testRecursiveDepthThreeDifferentFunctionsSingleProcessSingleThread(self):
    self._TestRecursiveDepthThreeDifferentFunctions(1, 1)

  def testRecursiveDepthThreeDifferentFunctionsSingleProcessMultiThread(self):
    self._TestRecursiveDepthThreeDifferentFunctions(1, 10)

  @unittest.skipIf(IS_WINDOWS, 'Multiprocessing is not supported on Windows')
  def testRecursiveDepthThreeDifferentFunctionsMultiProcessSingleThread(self):
    self._TestRecursiveDepthThreeDifferentFunctions(10, 1)

  @unittest.skipIf(IS_WINDOWS, 'Multiprocessing is not supported on Windows')
  def testRecursiveDepthThreeDifferentFunctionsMultiProcessMultiThread(self):
    self._TestRecursiveDepthThreeDifferentFunctions(10, 10)

  @Timeout
  def _TestRecursiveDepthThreeDifferentFunctions(self, process_count,
                                                 thread_count):
    """Tests recursive application of Apply.

    Calls Apply(A), where A calls Apply(B) followed by Apply(C) and B calls
    Apply(C).

    Args:
      process_count: Number of processes to use.
      thread_count: Number of threads to use.
    """
    args = ([3, 1, 4, 1, 5])
    results = self._RunApply(_ReApplyWithReplicatedArguments, args,
                             process_count, thread_count)
    self.assertEqual(7 * (sum(args) + len(args)), sum(results))

  def testExceptionInProducerRaisesAndTerminatesSingleProcessSingleThread(self):
    self._TestExceptionInProducerRaisesAndTerminates(1, 1)

  def testExceptionInProducerRaisesAndTerminatesSingleProcessMultiThread(self):
    self._TestExceptionInProducerRaisesAndTerminates(1, 10)

  @unittest.skipIf(IS_WINDOWS, 'Multiprocessing is not supported on Windows')
  def testExceptionInProducerRaisesAndTerminatesMultiProcessSingleThread(self):
    self._TestExceptionInProducerRaisesAndTerminates(10, 1)

  @unittest.skipIf(IS_WINDOWS, 'Multiprocessing is not supported on Windows')
  def testExceptionInProducerRaisesAndTerminatesMultiProcessMultiThread(self):
    self._TestExceptionInProducerRaisesAndTerminates(10, 10)

  @Timeout
  def _TestExceptionInProducerRaisesAndTerminates(self, process_count,
                                                  thread_count):
    args = self  # The ProducerThread will try and fail to iterate over this.
    try:
      self._RunApply(_ReturnOneValue, args, process_count, thread_count)
      self.fail('Did not raise expected exception.')
    except TypeError:
      pass

  def testSkippedArgumentsSingleThreadSingleProcess(self):
    self._TestSkippedArguments(1, 1)

  def testSkippedArgumentsMultiThreadSingleProcess(self):
    self._TestSkippedArguments(1, 10)

  @unittest.skipIf(IS_WINDOWS, 'Multiprocessing is not supported on Windows')
  def testSkippedArgumentsSingleThreadMultiProcess(self):
    self._TestSkippedArguments(10, 1)

  @unittest.skipIf(IS_WINDOWS, 'Multiprocessing is not supported on Windows')
  def testSkippedArgumentsMultiThreadMultiProcess(self):
    self._TestSkippedArguments(10, 10)

  @Timeout
  def _TestSkippedArguments(self, process_count, thread_count):

    # Skip a proper subset of the arguments.
    n = 2 * process_count * thread_count
    args = range(1, n + 1)
    results = self._RunApply(_ReturnOneValue, args, process_count, thread_count,
                             arg_checker=_SkipEvenNumbersArgChecker)
    self.assertEqual(n / 2, len(results))  # We know n is even.
    self.assertEqual(n / 2, sum(results))

    # Skip all arguments.
    args = [2 * x for x in args]
    results = self._RunApply(_ReturnOneValue, args, process_count, thread_count,
                             arg_checker=_SkipEvenNumbersArgChecker)
    self.assertEqual(0, len(results))


class TestParallelismFrameworkWithoutMultiprocessing(TestParallelismFramework):
  """Tests parallelism framework works with multiprocessing module unavailable.

  Notably, this test has no way to override previous calls
  to gslib.util.MultiprocessingIsAvailable to prevent the initialization of
  all of the global variables in command.py, so this still behaves slightly
  differently than the behavior one would see on a machine where the
  multiprocessing functionality is actually not available (in particular, it
  will not catch the case where a global variable that is not available for
  the sequential path is referenced before initialization).
  """
  command_class = FakeCommandWithoutMultiprocessingModule
