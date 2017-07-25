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
      max_memory: The maximum memory that the manager is allowing the system to
        use.
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

  def RequestMemory(self, size):
    """Handles requests for memory allocation from disk reads.

    Receives an input size and determines whether file wrapper object
    should have permission to allocate a memory buffer of that size to store
    bytes from the disk read. Note that this function is called by the
    FileOperationThread as when the FileOperationThread dequeues a read
    request, it calls RequestMemory and blocks until memory is available.

    Args:
      size: Size of the memory request.

    Returns:
      True if request for memory is granted, False otherwise.
    """

    with self.lock:
      if self.memory_used + size <= self.max_memory:
        return True
      else:
        return False

  def IncMemory(self, size):
    """Increments the used system memory value within the manager.

    This function is called by the file wrapper objects. When the
    FileOperationThread calls the file wrapper object's read function,
    the file wrapper object reads from the disk, appends the data read to its
    buffer queue, and (by calling this function) increments the memory
    in the global manager.

    Args:
      size: The size of memory that is read from the disk and stored in system
         memory.
    """
    with self.lock:
      self.memory_used += size

  def DecMemory(self, size):
    """Decrements the used system memory value within the manager.

    This function is called by the file wrapper objects. When the file wrapper
    object dequeues from its buffer queue to send data over the network, it
    calls DecMemory so that more data reads can be performed.

    Args:
      size: The size of memory that is read from the file wrapper object's
      buffer queue and to be sent over the network.
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

