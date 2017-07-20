"""A file operation manager that governs buffer memory allocation.
"""

from __future__ import division
from __future__ import print_function

from gslib.cloud_api import ArgumentException
from gslib.exception import CommandException

import functools
import signal
import multiprocessing
import threading

class FileOpManager(object):
  """Wrapper around a dictionary for a file operation manager, keeps track of
  metadata about the system, such as the total memory consumed.
  """

  def __init__(self, multiprocessing_is_available, max_memory, manager=None):
    self.multiprocessing_is_available = multiprocessing_is_available
    if self.multiprocessing_is_available and manager is not None:
      self.lock = manager.Lock()
      self.memory_used = multiprocessing.Value('i', 0)
      self.available = manager.Condition()
    elif self.multiprocessing_is_available and manager is None:
      raise ArgumentException('Need to include manager')
    else:
      self.lock = threading.Lock()
      self.memory_used = 0
      self.available = threading.Condition()

    self.max_memory = max_memory

  def RequestMemory(self, size):
    """Receives an input size and determines whether file wrapper object
    should have permission to allocate a memory buffer of that size to store
    bytes from the disk read."""
    if self.multiprocessing_is_available:
      with self.lock:
        if(self.memory_used.value + size <= self.max_memory):
          return True
        else:
          return False
    else:
      with self.lock:
        if(self.memory_used + size <= self.max_memory):
          return True
        else:
          return False

  def IncMemory(self, size):
    if self.multiprocessing_is_available:
      with self.lock:
        self.memory_used.value += size
    else:
      with self.lock:
        self.memory_used += size

  def DecMemory(self, size):
    self.available.acquire()

    if self.multiprocessing_is_available:
      with self.lock:
        self.memory_used.value -= size
        if self.memory_used.value < 0:
          raise CommandException(
              'Manager tracking that negative memory is used')
        self.available.notify_all()
        self.available.release()
    else:
      with self.lock:
        self.memory_used -= size
        if self.memory_used < 0:
          raise CommandException(
              'Manager tracking that negative memory is used')
        self.available.notifyAll()
        self.available.release()

  def GetUsedMemory(self):
    if self.multiprocessing_is_available:
      with self.lock:
        return self.memory_used.value
    else:
      with self.lock:
        return self.memory_used

