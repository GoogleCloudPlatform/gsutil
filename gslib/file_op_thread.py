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
"""FileOperationThread implementation for handling disk read requests."""

import Queue
import threading


class FileOperationThread(threading.Thread):
  """Class of the FileOperationThread to handle disk read requests.

  This class handles the file read request queue, which is enqueued with
  DiskReadFileWrapperObjects that are ready to read bytes from a file on disk.
  The class also interacts with the manager and disk lock to ensure that
  memory allocation does not exceed the specified memory usage limit and only
  one FileOperationThread is reading from the disk at a time.

  Note that this class is utilized as part of the parallel_disk_optimization
  feature.
  """

  def __init__(self, read_queue, cmd_manager, cmd_disk_lock, timeout):
    """Initializes the FileOperationThread.

    Args:
      read_queue: The file read request queue that the
        DiskReadFileWrapperObjects send disk read requests to.
      cmd_manager: The manager that handles memory allocation.
      cmd_disk_lock: The lock to read from the disk.
      timeout: The timeout is a value in seconds that controls the timeout
        from dequeuing the read queue.
    """
    super(FileOperationThread, self).__init__()
    self.daemon = True
    self._read_queue = read_queue
    self.cancel_event = threading.Event()
    self._file_op_manager = cmd_manager
    self._disk_lock = cmd_disk_lock
    self._timeout = timeout

  def run(self):
    """Processes the file read request queue.

    The FileOperationThread runs and pulls DiskReadFileWrapperObjects from the
    disk read queue, then asks the global file operation manager for permission
    to allocate a buffer of the requested size. When given permission, the
    thread then calls the wrapper object to read from the disk the requested
    number of bytes.

    TODO: Enqueue only the read function necessary onto the read queue for the
    file operation threads since the FileOperationThread is currently only
    calling one function of the file wrapper object. Will need to modify in
    disk_read_object.py what is enqueued to the disk read request queue and
    modify in file_op_thread.py (here) what is dequeued.
    """
    while True:
      # Processes items from the read queue until it is empty.

      if self.cancel_event.isSet():
        break

      try:
        # Attempt to get the next read request from read request queue.
        (file_object, size) = self._read_queue.get(timeout=self._timeout)

        self._file_op_manager.available.acquire()
        while(not self._file_op_manager.AllocMemory(size)):
          self._file_op_manager.available.wait()

        with self._disk_lock:
          file_object.ReadFromDisk(size)

        self._file_op_manager.available.release()

      except Queue.Empty:
        pass

      except socket.error:
        break

    return
