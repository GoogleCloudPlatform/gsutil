# -*- coding: utf-8 -*-
#  Copyright 2017 Google Inc. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
"""Unit tests for file operation manager class."""

from __future__ import absolute_import

import multiprocessing
import threading
import time

from gslib.exception import CommandException
from gslib.file_op_manager import FileOpManager
import gslib.tests.testcase as testcase


class TestFileOpManager(testcase.GsUtilUnitTestCase):
  """Unit tests for the FileOpManager class."""

  _manager = multiprocessing.Manager()
  _test_multiprocessing_manager = None
  _test_threading_manager = None
  _test_max_memory = 8388608
  _test_request_size = 512

  def testInitMultiprocessingManagerIsZero(self):
    self._test_multiprocessing_manager = FileOpManager(
        self._test_max_memory, self._manager)
    self.assertEqual(self._test_multiprocessing_manager.GetUsedMemory(), 0)

  def testInitThreadingManagerIsZero(self):
    self._test_threading_manager = FileOpManager(self._test_max_memory)
    self.assertEqual(self._test_threading_manager.GetUsedMemory(), 0)

  def testSetValueAtMaxAndTestMultiprocessingAllocMemory(self):
    self._test_multiprocessing_manager = FileOpManager(
        self._test_max_memory, self._manager)
    first_value = self._test_multiprocessing_manager.GetUsedMemory()
    self.assertEqual(first_value, 0)
    self.assertEqual(self._test_multiprocessing_manager.AllocMemory(
        self._test_max_memory), True)
    second_value = self._test_multiprocessing_manager.GetUsedMemory()
    self.assertEqual(second_value, 8388608)
    self.assertEqual(self._test_multiprocessing_manager.AllocMemory(
        self._test_request_size), False)
    self.assertEqual(self._test_multiprocessing_manager.AllocMemory(1), False)

  def testSetValueAtMaxAndTestThreadingAllocMemory(self):
    self._test_threading_manager = FileOpManager(self._test_max_memory)
    first_value = self._test_threading_manager.GetUsedMemory()
    self.assertEqual(first_value, 0)
    self.assertEqual(self._test_threading_manager.AllocMemory(
        self._test_max_memory), True)
    second_value = self._test_threading_manager.GetUsedMemory()
    self.assertEqual(second_value, 8388608)
    self.assertEqual(self._test_threading_manager.AllocMemory(
        self._test_request_size), False)
    self.assertEqual(self._test_threading_manager.AllocMemory(1), False)

  def testMultiprocessingIncFreeMemoryInOneProcess(self):
    self._test_multiprocessing_manager = FileOpManager(
        self._test_max_memory, self._manager)
    self.assertEqual(self._test_multiprocessing_manager.AllocMemory(1024),
                     True)
    self._test_multiprocessing_manager.FreeMemory(512)
    self.assertEqual(self._test_multiprocessing_manager.GetUsedMemory(), 512)

  def testMultiprocessingDecAllocMemoryIntoNegativeExceptRaise(self):
    self._test_multiprocessing_manager = FileOpManager(
        self._test_max_memory, self._manager)
    with self.assertRaises(CommandException):
      self._test_multiprocessing_manager.AllocMemory(512)
      self._test_multiprocessing_manager.FreeMemory(1024)

  def _ProcessAllocMemory(self):
    self._test_multiprocessing_manager.AllocMemory(1024)

  def _ProcessFreeMemory(self):
    time.sleep(0.5)
    self._test_multiprocessing_manager.FreeMemory(512)

  def testMultiprocessingIncFreeMemoryInTwoProcesses(self):
    self._test_multiprocessing_manager = FileOpManager(
        self._test_max_memory, self._manager)
    p1 = multiprocessing.Process(target=self._ProcessAllocMemory())
    p1.start()
    p2 = multiprocessing.Process(target=self._ProcessFreeMemory())
    p2.start()
    p1.join()
    p2.join()
    self.assertEqual(self._test_multiprocessing_manager.GetUsedMemory(), 512)

  def testThreadingIncFreeMemoryInOneThread(self):
    self._test_threading_manager = FileOpManager(self._test_max_memory)
    self._test_threading_manager.AllocMemory(1024)
    self._test_threading_manager.FreeMemory(512)
    self.assertEqual(self._test_threading_manager.GetUsedMemory(), 512)

  def testThreadingIncFreeMemoryIntoNegativeExpectRaise(self):
    self._test_threading_manager = FileOpManager(self._test_max_memory)
    with self.assertRaises(CommandException):
      self._test_threading_manager.AllocMemory(512)
      self._test_threading_manager.FreeMemory(1024)

  def _ThreadAllocMemory(self):
    self._test_threading_manager.AllocMemory(1024)

  def _ThreadFreeMemory(self):
    time.sleep(0.5)
    self._test_threading_manager.FreeMemory(512)

  def testThreadingIncFreeMemoryInTwoThreads(self):
    self._test_threading_manager = FileOpManager(self._test_max_memory)
    t1 = threading.Thread(target=self._ThreadAllocMemory())
    t1.start()
    t2 = threading.Thread(target=self._ThreadFreeMemory())
    t2.start()
    t1.join()
    t2.join()
    self.assertEqual(self._test_threading_manager.GetUsedMemory(), 512)

