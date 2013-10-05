# Copyright 2013 Google Inc. All Rights Reserved.
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

"""Utility classes for the parallelism framework."""

import multiprocessing
import threading

class BasicIncrementDict(object):
  """
  Dictionary meant for storing any values for which the "+" operation is
  defined (e.g., floats, lists, etc.). This class is neither thread- nor
  process-safe.
  """
  def __init__(self):
    self.dict = {}

  def get(self, key, default_value=None):
    return self.dict.get(key, default_value)

  def put(self, key, value):
    self.dict[key] = value

  def update(self, key, inc, default_value=0):
    """
    Update the stored value associated with the given key (or the default_value,
    if there is no existing value for the key) by performing the equivalent of
    self.put(key, self.get(key, default_value) + inc).
    """
    val = self.dict.get(key, default_value) + inc
    self.dict[key] = val
    return val


class AtomicIncrementDict(BasicIncrementDict):
  """
  Dictionary meant for storing any values for which the "+" operation is
  defined (e.g., floats, lists, etc.) in a way that allows for atomic get, put,
  and update in a thread- and process-safe way.
  """
  def __init__(self, manager):
    self.dict = ThreadAndProcessSafeDict(manager)
    self.lock = multiprocessing.Lock()

  def update(self, key, inc, default_value=0):
    """
    Update the stored value associated with the given key (or the default_value,
    if there is no existing value for the key) by performing the equivalent of
    self.put(key, self.get(key, default_value) + inc) atomically.
    """
    with self.lock:
      return super(AtomicIncrementDict, self).update(key, inc, default_value)


class ThreadAndProcessSafeDict(object):
  """
  The proxy objects returned by a manager are not necessarily thread-safe, so
  this class simply wraps their access with a lock for ease of use. They are,
  however, process-safe, so we can use the more efficient threading Lock.
  """
  def __init__(self, manager):
    self.dict = manager.dict()
    self.lock = threading.Lock()
    
  def __getitem__(self, key):
    with self.lock:
      return self.dict[key]
    
  def __setitem__(self, key, value):
    with self.lock:
      self.dict[key] = value
      
  def get(self, key, default_value=None):
    with self.lock:
      return self.dict.get(key, default_value)