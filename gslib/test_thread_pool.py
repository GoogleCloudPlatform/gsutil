#!/usr/bin/env python
#
# Copyright 2011 Google Inc.
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

"""Unit tests for gsutil thread pool."""

import sys
import threading
import thread_pool
import unittest


class GsutilThreadPoolTests(unittest.TestCase):
  """gsutil thread pool test suite."""

  def GetSuiteDescription(self):
    return 'gsutil thread pool test suite'

  @classmethod
  def SetUpClass(cls):
    """Creates class level artifacts useful to multiple tests."""
    pass

  @classmethod
  def TearDownClass(cls):
    """Cleans up any artifacts created by SetUpClass."""
    pass

  def _TestThreadPool(self, threads):
    """Tests pool with specified threads from end to end."""
    pool = thread_pool.ThreadPool(threads)

    self.actual_call_count = 0
    expected_call_count = 10000

    self.data = xrange(expected_call_count)

    self.actual_result = 0
    expected_result = sum(self.data)

    stats_lock = threading.Lock()

    def _Dummy(num):
      stats_lock.acquire()
      self.actual_call_count += 1
      self.actual_result += num
      stats_lock.release()

    for data in xrange(expected_call_count):
      pool.AddTask(_Dummy, data)

    pool.WaitCompletion()
    self.assertEqual(self.actual_call_count, expected_call_count)

    self.assertEqual(self.actual_result, expected_result)

    pool.Shutdown()
    for thread in pool.threads:
      self.assertFalse(thread.is_alive())

  def TestSingleThreadPool(self):
    """Tests thread pool with a single thread."""
    self._TestThreadPool(1)

  def TestThirtyThreadPool(self):
    """Tests thread pool with 30 threads."""
    self._TestThreadPool(30)

  def TestThreadPoolExceptionHandler(self):
    """Tests thread pool with exceptions."""
    self.exception_raised = False

    def _ExceptionHandler(e):
      """Verify an exception is raised and that it's the correct one."""
      self.assertTrue(isinstance(e, TypeError))
      self.assertEqual(e[0], 'gsutil')
      self.exception_raised = True

    pool = thread_pool.ThreadPool(1, exception_handler=_ExceptionHandler)

    def _Dummy():
      raise TypeError('gsutil')

    pool.AddTask(_Dummy)
    pool.WaitCompletion()
    pool.Shutdown()

    self.assertTrue(self.exception_raised)


if __name__ == '__main__':
  if sys.version_info[:3] < (2, 5, 1):
    sys.exit('These tests must be run on at least Python 2.5.1\n')
  test_loader = unittest.TestLoader()
  test_loader.testMethodPrefix = 'Test'
  suite = test_loader.loadTestsFromTestCase(GsutilThreadPoolTests)
  # Seems like there should be a cleaner way to find the test_class.
  test_class = suite.__getattribute__('_tests')[0]
  # We call SetUpClass() and TearDownClass() ourselves because we
  # don't assume the user has Python 2.7 (which supports classmethods
  # that do it, with camelCase versions of these names).
  try:
    print 'Setting up %s...' % test_class.GetSuiteDescription()
    test_class.SetUpClass()
    print 'Running %s...' % test_class.GetSuiteDescription()
    unittest.TextTestRunner(verbosity=2).run(suite)
  finally:
    print 'Cleaning up after %s...' % test_class.GetSuiteDescription()
    test_class.TearDownClass()
    print ''
