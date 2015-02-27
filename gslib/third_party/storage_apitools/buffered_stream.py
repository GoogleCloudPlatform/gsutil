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
"""Small helper class to provide a buffered stream.

This class reads ahead to detect if we are at the end of the stream.
"""

import logging
import time

from gslib.third_party.storage_apitools import exceptions
from gslib.third_party.storage_apitools import util


# TODO: Consider replacing this with a StringIO.
class BufferedStream(object):
  """Buffers a stream, reading ahead to determine if we're at the end."""

  def __init__(self, stream, start, size):
    self.__stream = stream
    self.__start_pos = start
    self.__buffer_pos = 0
    self.__stream_at_end = False
    self.__buffered_data = b''
    bytes_remaining = size
    non_blocking_retry_attempt = 0
    while bytes_remaining:
      data = self.__stream.read(bytes_remaining)
      if data is None:
        # stream.read(...) return value of None indicates stream is in
        # non-blocking mode and no bytes were available. Best we can do is
        # keep trying.
        # TODO: Use configurable values for retry logic.
        non_blocking_retry_attempt += 1
        if non_blocking_retry_attempt > 6:
          logging.info('Non-blocking stream yielded no data for BufferedStream'
                       'over %s attempts, retrying infinitely.',
                       non_blocking_retry_attempt)
        time.sleep(util.CalculateWaitForRetry(non_blocking_retry_attempt))
        continue
      elif not data and bytes_remaining > 0:
        # stream.read(n) return value of b'' indicates EOF, unless we
        # requested a zero-length read.
        self.__stream_at_end = True
        break
      self.__buffered_data += data
      bytes_remaining -= len(data)
    self.__end_pos = self.__start_pos + len(self.__buffered_data)

  def __str__(self):
    return ('Buffered stream %s from position %s-%s with %s '
            'bytes remaining' % (self.__stream, self.__start_pos,
                                 self.__end_pos, self._bytes_remaining))

  def __len__(self):
    return len(self.__buffered_data)

  @property
  def stream_exhausted(self):
    return self.__stream_at_end

  @property
  def stream_end_position(self):
    return self.__end_pos

  @property
  def _bytes_remaining(self):
    return len(self.__buffered_data) - self.__buffer_pos

  def read(self, size=None):  # pylint: disable=invalid-name
    """Reads from the buffer."""
    if size is None or size < 0:
      raise exceptions.NotYetImplementedError(
          'Illegal read of size %s requested on BufferedStream. '
          'Wrapped stream %s is at position %s-%s, '
          '%s bytes remaining.' %
          (size, self.__stream, self.__start_pos, self.__end_pos,
           self._bytes_remaining))

    data = ''
    if self._bytes_remaining:
      size = min(size, self._bytes_remaining)
      data = self.__buffered_data[self.__buffer_pos:self.__buffer_pos + size]
      self.__buffer_pos += size
    return data
