# Copyright 2014 Google Inc. All Rights Reserved.
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
"""Small helper class to provide a small slice of a stream."""

from gslib.third_party.storage_apitools import exceptions


class StreamSlice(object):
  """Provides access to part of a stream."""

  def __init__(self, stream, max_bytes):
    self.__stream = stream
    self.__remaining_bytes = max_bytes
    self.__max_bytes = max_bytes

  def __str__(self):
    return 'Slice of stream %s with %s/%s bytes not yet read' % (
        self.__stream, self.__remaining_bytes, self.__max_bytes)

  def __len__(self):
    return self.__max_bytes

  def __nonzero__(self):
    # For 32-bit python2.x, len() cannot exceed a 32-bit number; avoid
    # accidental len() calls from httplib in the form of "if this_object:".
    return bool(self.__max_bytes)

  @property
  def length(self):
    # For 32-bit python2.x, len() cannot exceed a 32-bit number.
    return self.__max_bytes

  def read(self, size=None):
    if size is not None:
      size = min(size, self.__remaining_bytes)
    else:
      size = self.__remaining_bytes
    data = self.__stream.read(size)
    if not data and self.__remaining_bytes:
      raise exceptions.TransferInvalidError(
          'Not enough bytes in stream; expected %d, stream exhausted after %d'
          % (self.__max_bytes, self.__remaining_bytes))
    self.__remaining_bytes -= len(data)
    return data
