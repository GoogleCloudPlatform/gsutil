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

  def testSetValueAtMaxAndTestMultiprocessingRequestMemory(self):
    self._test_multiprocessing_manager = FileOpManager(
        self._test_max_memory, self._manager)
    first_value = self._test_multiprocessing_manager.GetUsedMemory()
    self.assertEqual(first_value, 0)
    self.assertEqual(self._test_multiprocessing_manager.RequestMemory(
        self._test_request_size), True)
    self._test_multiprocessing_manager.IncMemory(self._test_max_memory + 1)
    second_value = self._test_multiprocessing_manager.GetUsedMemory()
    self.assertEqual(second_value, 8388609)
    self.assertEqual(self._test_multiprocessing_manager.RequestMemory(
        self._test_request_size), False)

  def testSetValueAtMaxAndTestThreadingRequestMemory(self):
    self._test_threading_manager = FileOpManager(self._test_max_memory)
    first_value = self._test_threading_manager.GetUsedMemory()
    self.assertEqual(first_value, 0)
    self.assertEqual(self._test_threading_manager.RequestMemory(
        self._test_request_size), True)
    self._test_threading_manager.IncMemory(self._test_max_memory + 1)
    second_value = self._test_threading_manager.GetUsedMemory()
    self.assertEqual(second_value, 8388609)
    self.assertEqual(self._test_threading_manager.RequestMemory(
        self._test_request_size), False)

  def testMultiprocessingIncDecMemoryInOneProcess(self):
    self._test_multiprocessing_manager = FileOpManager(
        self._test_max_memory, self._manager)
    self._test_multiprocessing_manager.IncMemory(1024)
    self._test_multiprocessing_manager.DecMemory(512)
    self.assertEqual(self._test_multiprocessing_manager.GetUsedMemory(), 512)

  def testMultiprocessingDecIncMemoryIntoNegativeExceptRaise(self):
    self._test_multiprocessing_manager = FileOpManager(
        self._test_max_memory, self._manager)
    with self.assertRaises(CommandException):
      self._test_multiprocessing_manager.IncMemory(512)
      self._test_multiprocessing_manager.DecMemory(1024)

  def _ProcessIncMemory(self):
    self._test_multiprocessing_manager.IncMemory(1024)

  def _ProcessDecMemory(self):
    time.sleep(0.5)
    self._test_multiprocessing_manager.DecMemory(512)

  def testMultiprocessingIncDecMemoryInTwoProcesses(self):
    self._test_multiprocessing_manager = FileOpManager(
        self._test_max_memory, self._manager)
    p1 = multiprocessing.Process(target=self._ProcessIncMemory())
    p1.start()
    p2 = multiprocessing.Process(target=self._ProcessDecMemory())
    p2.start()
    p1.join()
    p2.join()
    self.assertEqual(self._test_multiprocessing_manager.GetUsedMemory(), 512)

  def testThreadingIncDecMemoryInOneThread(self):
    self._test_threading_manager = FileOpManager(self._test_max_memory)
    self._test_threading_manager.IncMemory(1024)
    self._test_threading_manager.DecMemory(512)
    self.assertEqual(self._test_threading_manager.GetUsedMemory(), 512)

  def testThreadingIncDecMemoryIntoNegativeExpectRaise(self):
    self._test_threading_manager = FileOpManager(self._test_max_memory)
    with self.assertRaises(CommandException):
      self._test_threading_manager.IncMemory(512)
      self._test_threading_manager.DecMemory(1024)

  def _ThreadIncMemory(self):
    self._test_threading_manager.IncMemory(1024)

  def _ThreadDecMemory(self):
    time.sleep(0.5)
    self._test_threading_manager.DecMemory(512)

  def testThreadingIncDecMemoryInTwoThreads(self):
    self._test_threading_manager = FileOpManager(self._test_max_memory)
    t1 = threading.Thread(target=self._ThreadIncMemory())
    t1.start()
    t2 = threading.Thread(target=self._ThreadDecMemory())
    t2.start()
    t1.join()
    t2.join()
    self.assertEqual(self._test_threading_manager.GetUsedMemory(), 512)

