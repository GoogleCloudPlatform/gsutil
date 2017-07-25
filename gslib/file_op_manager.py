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
"""A file operation manager that governs buffer memory allocation."""

from __future__ import absolute_import

import multiprocessing
import threading

from gslib.exception import CommandException


class FileOpManager(object):
  """Wrapper around a dictionary for a file operation manager.

  Manages memory allocation of the system given the multiprocessing
  and maximum memory availability.
  """

  def __init__(self, max_memory, manager=None):
    """Initializes the FileOperationManager.

    Args:
      max_memory: The maximum memory in bytes that the manager is allowing the
        system to use.
      manager: The manager is used to maintain atomicity throughout processes.
        A manager argument is passed in when multiprocessing is available, and
        in the threading case, no manager argument is passed in and is by
        default None.
    """
    self.max_memory = max_memory
    if manager is not None:
      self.lock = manager.Lock()
      self.memory_used = multiprocessing.Value('i', 0).value
      self.available = manager.Condition()
    else:
      self.lock = threading.Lock()
      self.memory_used = 0
      self.available = threading.Condition()

  def AllocMemory(self, size):
    """Handles requests for memory allocation from disk reads.

    Receives an input size and determines whether file wrapper object
    should have permission to allocate a memory buffer of that size to store
    bytes from the disk read. If there is available memory to allocate, the
    memory used value in the manager is incremented to reflect the memory
    allocation and returns True, else returns False. Note that this function
    is called by the FileOperationThread as when the FileOperationThread
    dequeues a read request, it calls AllocMemory and blocks until AllocMemory
    return True.

    Args:
      size: Size of the memory request in bytes.

    Returns:
      True if memory has been allocated for a disk read request,
        False otherwise.
    """
    with self.lock:
      if self.memory_used + size <= self.max_memory:
        self.memory_used += size
        return True
      else:
        return False

  def FreeMemory(self, size):
    """Decrements the used system memory value within the manager.

    This function is called by the file wrapper objects. When the file wrapper
    object dequeues from its buffer queue to send data over the network, it
    calls FreeMemory so that more data reads can be performed.

    Args:
      size: The size of memory in bytes that is read from the file wrapper
        object's buffer queue and to be sent over the network.
    """
    self.available.acquire()
    with self.lock:
      self.memory_used -= size
      if self.memory_used < 0:
        raise CommandException(
            'Manager tracking that negative memory is used.')
      self.available.notify_all()
      self.available.release()

  def GetUsedMemory(self):
    with self.lock:
      return self.memory_used

