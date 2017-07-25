# -*- coding: utf-8 -*-
# Copyright 2017 Google Inc. All Rights Reserved.
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
"""Unit tests for file operation thread functions and classes."""

from __future__ import absolute_import

import Queue
import threading
import time

from gslib.file_op_thread import FileOperationThread
import gslib.tests.testcase as testcase
import mock

_TEST_FILE = 'test.txt'
TEST_MAX_BUFFER_SIZE = 512


class TestFileOperationThread(testcase.GsUtilUnitTestCase):
  """Unit tests for the FileOperationThread class."""

  # After waiting this long, assume the FileOperationThread is hung.
  thread_wait_time = 5

  _temp_test_file = None
  _temp_test_file_contents = None
  _temp_test_file_len = None
  _test_file_op_queue = None
  _test_file_op_thread = None
  _mock_file_op_manager = mock.Mock(return_value=True)
  _mock_disk_lock = threading.Lock()

  def testCancelFileOpThread(self):
    """Test cancelling file operation thread via threading.Event."""
    self._test_file_op_queue = Queue.Queue()
    self._test_file_op_thread = FileOperationThread(
        self._test_file_op_queue, self._mock_file_op_manager,
        self._mock_disk_lock)
    self._test_file_op_thread.start()

    self._test_file_op_thread.cancel_event.set()
    self._test_file_op_thread.join(self.thread_wait_time)
    self.assertEqual(self._test_file_op_thread.is_alive(), False)

  def testAddOneRequestToFileOpThreadQueue(self):
    """Test adding one file wrapper object request to the queue."""
    self._test_file_op_queue = Queue.Queue()
    self._test_file_op_thread = FileOperationThread(
        self._test_file_op_queue, self._mock_file_op_manager,
        self._mock_disk_lock)
    self._test_file_op_thread.start()

    # Mock a file wrapper object and submit it onto the file read request
    # queue associated with the FileOperationThread
    mock_disk_read_object = mock.Mock()
    self._test_file_op_queue.put((mock_disk_read_object, 1, True))

    time.sleep(1)
    self._test_file_op_thread.cancel_event.set()
    self._test_file_op_thread.join(self.thread_wait_time)
    # Assert that ReadFromDisk was called for the mock disk read object
    # from the FileOperationThread
    mock_disk_read_object.ReadFromDisk.assert_called_with(1)

  def testAddMultipleFileObjectsToQueue(self):
    """Test adding multiple file wrapper object requests to the queue."""
    # Create a new file operation thread
    self._test_file_op_queue = Queue.Queue()
    self._test_file_op_thread = FileOperationThread(
        self._test_file_op_queue, self._mock_file_op_manager,
        self._mock_disk_lock)
    self._test_file_op_thread.start()

    # Add one file wrapper objects and size requests to the file object
    # queue
    mock_disk_read_object = mock.Mock()
    mock_disk_read_object2 = mock.Mock()

    self._test_file_op_queue.put((mock_disk_read_object, 0, False))
    self._test_file_op_queue.put((mock_disk_read_object2, 1, False))
    self._test_file_op_queue.put((mock_disk_read_object, 2, False))
    self._test_file_op_queue.put((mock_disk_read_object2, 3, True))

    time.sleep(1)
    # Assert that request enqueued to file read request queue was made
    self._test_file_op_thread.cancel_event.set()
    self._test_file_op_thread.join(self.thread_wait_time)

    # Ensures ReadFromDisk is called correctly
    mock_disk_read_object.ReadFromDisk.assert_has_calls(
        [mock.call(0), mock.call(2)])
    mock_disk_read_object2.ReadFromDisk.assert_has_calls(
        [mock.call(1), mock.call(3)])
