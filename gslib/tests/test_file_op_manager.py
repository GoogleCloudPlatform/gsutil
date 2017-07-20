# -*- coding: utf-8 -*-
#  Copyright 2017 Google Inc. All Rights Reserved.
#
## Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# # You may obtain a copy of the License at
# #
# #     http://www.apache.org/licenses/LICENSE-2.0
# #
# # Unless required by applicable law or agreed to in writing, software
# # distributed under the License is distributed on an "AS IS" BASIS,
# # WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# # See the License for the specific language governing permissions and
# # limitations under the License.
"""Unit tests for file operation manager class."""

from __future__ import absolute_import

import os
import pkgutil
import multiprocessing
import threading
import time

from gslib.cloud_api import ArgumentException
from gslib.file_op_manager import FileOpManager
import gslib.tests.testcase as testcase
from gslib.exception import CommandException

class TestFileOpManager(testcase.GsUtilUnitTestCase):
  """Unit tests for the FileOpManager class."""

  global manager
  manager = multiprocessing.Manager()
  _test_multiprocessing_manager = None
  _test_threading_manager = None
  _test_max_memory = 8388608
  _test_request_size = 512

  # Test that an initialized multiprocessing manager has value of 0
  def testInitMultiprocessingManagerIsZero(self):
    self._test_multiprocessing_manager = FileOpManager(
        True, self._test_max_memory, manager)
    self.assertEqual(self._test_multiprocessing_manager.getUsedMemory(), 0)

  # Test that an initialized multiprocessing manager with no
  # multiprocessing.Manager() raises an argument exception
  def testInitMultiprocessingWithoutManagerRaise(self):
    try:
      test_multiprocessing_no_manager = FileOpManager(
          True, self._test_max_memory)
      self.fail('Manager did not catch going into missing manager argument')
    except ArgumentException, e:
      pass
    except Exception, e:
      self.fail('Got unexpected error: ' + str(e))

  # Test that an initialized threading manager has value of 0
  def testInitThreadingManagerIsZero(self):
    self._test_threading_manager = FileOpManager(False, self._test_max_memory)
    self.assertEqual(self._test_threading_manager.getUsedMemory(), 0)

  # Test that the manager knows to not allow request for memory if the manager
  # is at max memory (in multiprocessing case)
  def testSetValueAtMaxAndTestMultiprocessingRequestMemory(self):
    self._test_multiprocessing_manager = FileOpManager(
        True, self._test_max_memory, manager)
    first_value = self._test_multiprocessing_manager.getUsedMemory()
    self.assertEqual(first_value, 0)
    self.assertEqual(self._test_multiprocessing_manager.requestMemory(
        self._test_request_size), True)
    self._test_multiprocessing_manager.incMemory(self._test_max_memory + 1)
    second_value = self._test_multiprocessing_manager.getUsedMemory()
    self.assertEqual(second_value, 8388609)
    self.assertEqual(self._test_multiprocessing_manager.requestMemory(
        self._test_request_size), False)

  # Test that the manager knows to not allow request for memory if the manager
  # is at max memory (in non-multiprocessing case)
  def testSetValueAtMaxAndTestThreadingRequestMemory(self):
    self._test_threading_manager = FileOpManager(False, self._test_max_memory)
    first_value = self._test_threading_manager.getUsedMemory()
    self.assertEqual(first_value, 0)
    self.assertEqual(self._test_threading_manager.requestMemory(
        self._test_request_size), True)
    self._test_threading_manager.incMemory(self._test_max_memory + 1)
    second_value = self._test_threading_manager.getUsedMemory()
    self.assertEqual(second_value, 8388609)
    self.assertEqual(self._test_threading_manager.requestMemory(
        self._test_request_size), False)

  # Test increment and decrement memory for multiprocessing manager in one process
  def testMultiprocessingIncDecMemoryInOneProcess(self):
    self._test_multiprocessing_manager = FileOpManager(
        True, self._test_max_memory, manager)
    self._test_multiprocessing_manager.incMemory(1024)
    self._test_multiprocessing_manager.decMemory(512)
    self.assertEqual(self._test_multiprocessing_manager.getUsedMemory(), 512)

  # Test going into negative memory for multiprocessing manager,
  # expect a CommandException raise
  def testMultiprocessingDecIncMemoryIntoNegativeExceptRaise(self):
    self._test_multiprocessing_manager = FileOpManager(
        True, self._test_max_memory, manager)
    try:
      self._test_multiprocessing_manager.incMemory(512)
      self._test_multiprocessing_manager.decMemory(1024)
      self.fail('Manager did not catch negative used memory')
    except CommandException, e:
      pass
    except Exception, e:
      self.fail('Got unexpected error: ', + str(e))

  def _ProcessIncMemory(self):
    self._test_multiprocessing_manager.incMemory(1024)

  def _ProcessDecMemory(self):
    time.sleep(0.5)
    self._test_multiprocessing_manager.decMemory(512)

  # Test increment and decrement memory for multiprocessing manager in two
  # processes
  def testMultiprocessingIncDecMemoryInTwoProcesses(self):
    self._test_multiprocessing_manager = FileOpManager(
        True, self._test_max_memory, manager)
    p1 = multiprocessing.Process(target=self._ProcessIncMemory())
    p1.start()
    p2 = multiprocessing.Process(target=self._ProcessDecMemory())
    p2.start()
    p1.join()
    p2.join()
    self.assertEqual(self._test_multiprocessing_manager.getUsedMemory(), 512)

  # Test increment and decrement memory for non-multiprocessing manager in one
  # thread
  def testThreadingIncDecMemoryInOneThread(self):
    self._test_threading_manager = FileOpManager(
        True, self._test_max_memory, manager)
    self._test_threading_manager.incMemory(1024)
    self._test_threading_manager.decMemory(512)
    self.assertEqual(self._test_threading_manager.getUsedMemory(), 512)

  # Test going into negative memory for multiprocessing manager,
  # expect a CommandException raise
  def testThreadingIncDecMemoryIntoNegativeExceptRaise(self):
    self._test_threading_manager = FileOpManager(
        True, self._test_max_memory, manager)
    try:
      self._test_threading_manager.incMemory(512)
      self._test_threading_manager.decMemory(1024)
      self.fail('Manager did not catch negative used memory')
    except CommandException, e:
      pass
    except Exception, e:
      self.fail('Got unexpected error: ', + str(e))

  def _ThreadIncMemory(self):
    self._test_threading_manager.incMemory(1024)

  def _ThreadDecMemory(self):
    time.sleep(0.5)
    self._test_threading_manager.decMemory(512)

  # Test increment and decrement memory for non-multiprocessing manager in two
  # threads
  def testThreadingIncDecMemoryInTwoThreads(self):
    self._test_threading_manager = FileOpManager(False, self._test_max_memory)
    t1 = threading.Thread(target=self._ThreadIncMemory())
    t1.start()
    t2 = threading.Thread(target=self._ThreadDecMemory())
    t2.start()
    t1.join()
    t2.join()
    self.assertEqual(self._test_threading_manager.getUsedMemory(), 512)

