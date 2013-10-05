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

import gslib.help_provider as help_provider
import gslib.tests.testcase as testcase

from gslib.command import Command
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.command import DummyArgChecker
from gslib.command import CreateGsutilLogger
from gslib.commands.lifecycle import LifecycleCommand
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HelpType
from gslib.help_provider import HELP_TYPE
from gslib.tests.util import unittest
from gslib.util import IS_WINDOWS
from gslib.util import MultiprocessingIsAvailable


class CustomException(Exception):
  def __init__(self, str):
    super(CustomException, self).__init__(str)


def _ReturnOneValue(cls, args):
  return 1

def _FailureFunc(cls, args):
  raise CustomException("Failing on purpose.")

def _FailingExceptionHandler(cls, e):
  cls.failure_count += 1
  raise CustomException("Exception handler failing on purpose.")

def _ExceptionHandler(cls, e):
  cls.logger.exception(e)
  cls.failure_count += 1

def _IncrementByLength(cls, args):
  cls.arg_length_sum += len(args)

def _AdjustProcessCountIfWindows(process_count):
  if IS_WINDOWS:
    return 1
  else:
    return process_count
  
def _ReApplyWithReplicatedArguments(cls, args):
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

def _PerformNRecursiveCalls(cls, args):
  process_count = _AdjustProcessCountIfWindows(2)
  return_values = cls.Apply(_ReturnOneValue, [()] * args, _ExceptionHandler,
                            arg_checker=DummyArgChecker,
                            process_count=process_count, thread_count=2,
                            should_return_results=True)
  return len(return_values)


class FakeCommand(Command):
  command_spec = {
    COMMAND_NAME : 'fake',
    COMMAND_NAME_ALIASES : [],
  }
  help_spec = {
    HELP_NAME : 'fake',
    HELP_NAME_ALIASES : [],
    HELP_TYPE : HelpType.COMMAND_HELP,
    HELP_ONE_LINE_SUMMARY : 'Something to take up space.',
    HELP_TEXT : 'Something else to take up space.',
  }

  def __init__(self, do_parallel):
    self.logger = CreateGsutilLogger('FakeCommand')
    self.parallel_operations = do_parallel
    self.failure_count = 0
    self.multiprocessing_is_available = MultiprocessingIsAvailable()[0]


class FakeCommandWithoutMultiprocessingModule(FakeCommand):
  def __init__(self, do_parallel):
    super(FakeCommandWithoutMultiprocessingModule, self).__init__(do_parallel)
    self.multiprocessing_is_available = False


# TODO: Figure out a good way to test that ctrl+C really stops execution,
#       and also that ctrl+C works when there are still tasks enqueued.
class TestParallelismFramework(testcase.GsUtilUnitTestCase):
  """gsutil parallelism framework test suite."""
  
  command_class = FakeCommand

  def _TestBasicApply(self, process_count, thread_count):
    args = [()] * (17 * process_count * thread_count + 1)
    
    results = self._RunApply(_ReturnOneValue, args, thread_count,
                                     process_count)
    self.assertEqual(len(args), len(results))

  def _RunApply(self, func, args_iterator,
                        thread_count, process_count, command_inst=None,
                        shared_attrs=None, fail_on_error=False,
                        thr_exc_handler=None):
    command_inst = command_inst or self.command_class(True)
    exception_handler = thr_exc_handler or _ExceptionHandler
    process_count = _AdjustProcessCountIfWindows(process_count)
    return command_inst.Apply(func, args_iterator, exception_handler,
                              thread_count=thread_count,
                              process_count=process_count,
                              arg_checker=DummyArgChecker,
                              should_return_results=True,
                              shared_attrs=shared_attrs,
                              fail_on_error=fail_on_error)

  def testApplySingleProcessSingleThread(self):
    self._TestBasicApply(1, 1)

  def testApplySingleProcessMultiThread(self):
    self._TestBasicApply(1, 10)

  @unittest.skipIf(IS_WINDOWS, 'Multiprocessing is not supported on Windows')
  def testApplyMultiProcessSingleThread(self):
    self._TestBasicApply(10, 1)

  @unittest.skipIf(IS_WINDOWS, 'Multiprocessing is not supported on Windows')
  def testApplyMultiProcessMultiThread(self):
    self._TestBasicApply(10, 10)

  def testSharedAttrsWork(self):
    command_inst = self.command_class(True)
    command_inst.arg_length_sum = 0
    args = ['foo', ['bar', 'baz'], [], ['x', 'y'], [], 'abcd']
    results = self._RunApply(_IncrementByLength, args, 2, 2,
                                     command_inst=command_inst,
                                     shared_attrs=['arg_length_sum'])
    expected_sum = 0
    for arg in args:
      expected_sum += len(arg)
    self.assertEqual(expected_sum, command_inst.arg_length_sum)

  def testThreadsSurviveExceptions(self):
    command_inst = self.command_class(True)
    args = ([()] * 5)
    results = self._RunApply(_FailureFunc, args, 2, 2,
                                     command_inst=command_inst,
                                     shared_attrs=['failure_count'])
    self.assertEqual(len(args), command_inst.failure_count)
    
  def testThreadsSurviveExceptionsInExceptionHandler(self):
    command_inst = self.command_class(True)
    args = ([()] * 5)
    results = self._RunApply(_FailureFunc, args, 2, 2,
                                     command_inst=command_inst,
                                     shared_attrs=['failure_count'],
                                     thr_exc_handler=_FailingExceptionHandler)
    self.assertEqual(len(args), command_inst.failure_count)

  def testFailOnErrorFlag(self):
    command_inst = self.command_class(True)
    args = ([()] * 5)
    try:
      results = self._RunApply(_FailureFunc, args, 1, 1,
                                       command_inst=command_inst,
                                       shared_attrs=['failure_count'],
                                       fail_on_error=True)
      self.fail('Setting fail_on_error should raise any exception encountered.')
    except CustomException, e:
      pass
    except Exception, e:
      self.fail("Got unexpected error: " + str(e))

  def testRecursiveDepthOfThreeWithDifferentSimultaneousFunctionsWorks(self):
    """Calls Apply(A), where A calls Apply(B) followed by Apply(C) and B calls
       Apply(C).
    """
    args = ([3, 1, 4, 1, 5])
    results = self._RunApply(_ReApplyWithReplicatedArguments, args, 2, 2)
    self.assertEqual(7 * (sum(args) + len(args)), sum(results))


class TestParallelismFrameworkWithoutMultiprocessing(TestParallelismFramework):
  """Tests that the parallelism framework works when the multiprocessing module
     is not available. Notably, this test has no way to override previous calls
     to gslib.util.MultiprocessingIsAvailable to prevent the initialization of
     all of the global variables in command.py, so this still behaves slightly
     differently than the behavior one would see on a machine where the
     multiprocessing functionality is actually not available (in particular, it
     will not catch the case where a global variable that is not available for
     the sequential path is referenced before initialization).
  """
  command_class = FakeCommandWithoutMultiprocessingModule
