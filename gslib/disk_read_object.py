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
"""Helper class for disk read file wrapper object."""

import collections
import os

import logging
import md5
import threading
import time
import multiprocessing
import sys
import traceback

from gslib.exception import CommandException
from gslib.storage_url import StorageUrlFromString
from gslib.util import GetJsonResumableChunkSize

# import gslib.command as command

WriteRequest = collections.namedtuple('WriteRequest', (
    'success',         # whether the read operator succeeded or not
    'position',        # the position where the read operator started
    'data',            # the chunk read from disk
    'data_len',        # length of the chunk read
    'last',            # boolean whether it's the last read of the file
    'err_msg'))        # error message if success is false


class DiskReadFileWrapperObject(object):
  """Wraps a file into a Python file-like stream.

  This class takes a source file, communicates with the file operation
  thread to read from the disk, and exposes it as a stream.

  """

  def __init__(self, source_file_url, source_file_size, max_buffer_size):
    """Initializes the wrapper.

    Args:
      source_file: source file that represents the file to be read
      from the disk
      source_file_size: size of the source file in bytes
    """

    # Local file information
    self._source_url = source_file_url
    self.name = source_file_url.object_name
    self._size = source_file_size

    self._stream = None
    self._done = False
    self._file_lock = threading.RLock()

    self._max_buffer_size = max_buffer_size
    self._buffer = collections.deque()
    self._buffer_start = 0
    self._buffer_end = 0
    self._position = 0
    # Most recently popped request from the buffer
    self._current_request = WriteRequest(True, 0, b'', 0, False, None)

    import gslib.command as command
    self._global_manager = command.file_op_manager

    self._buffer_nonempty = threading.Condition()

    self._read_queue = command.file_obj_queue

    # push first request for buffer of size max_buffer_size onto file operation
    # thread request queue
    if self._max_buffer_size >= self._size:
      last = True
    else:
      last = False
    self._read_queue.put((self, self._max_buffer_size, last))

  def open(self):
    """Opens the local file."""
    try:
      # print('DEBUG: open\n')
      if self._source_url.IsStream():
        self._stream = sys.stdin
      else:
        self._stream = open(self._source_url.object_name, 'rb')
      return self
    except IOError as e:
      self.close()
      return False
    return True

  def close(self):
    """Closes the local file, if necessary."""
    self._done = True
    with self._file_lock:
      if self._stream:
        self._stream.close()
        self._stream = None

  def RequestRead(self, blocks=1):
    """Queues a read for this file."""
    if not self._done:
      # Sends "blocks" number of requests for max_buffer_size bytes to read.
      # Also indicates whether this request is the last for the file
      for _ in xrange(blocks):
        last = (self._position + self._max_buffer_size >= self._size)
        self._read_queue.put((self, self._max_buffer_size, last))

  def ReadFromBufferQueue(self):
    """Blocks until data comes from the read thread and returns it."""
    # print('DEBUG: readfrombufferqueue\n')
    start_time = time.time()
    complain_after = 60 * 5
    complain_at = start_time + complain_after
    complained = False
    while True:
      try:
        # Pop from the left end of the buffer queue
        ret = self._buffer.popleft()
        if complained:
          now = time.time()
          logging.warning('Got next chunk of %s after %d sec.',
                          self._source_url, round(now - start_time))
        return ret
      except IndexError:
        now = time.time()
        if now >= complain_at:
          logging.warning('Waiting for next chunk of %s. (%d sec so far)',
                          self._source_url, round(now - start_time))
          complain_after *= 2
          complain_at = start_time + complain_after
          complained = True

  def read(self, size=-1):
    """Reads "size" bytes from the file wrapper object stream."""
    # print 'DEBUG: DEBUG: read with size %d' % (size)
    read_all_bytes = size is None or size < 0
    if read_all_bytes:
      bytes_remaining = self._size
    else:
      bytes_remaining = size
    buffered_data = []

    while bytes_remaining > 0 and not self._position == self._size:
      # print 'DEBUG: DEBUG: position: %d, size: %d' % (self._position, self._size)
      # print'DEBUG: bytes remaining: %d' % (bytes_remaining)
      # While size bytes haven't been read yet
      if self._current_request.data_len > 0:
        # Check if there's remainder buffer to read from before going to the queue
        #print 'DEBUG: self._current_request.data_len is %d' % self._current_request.data_len
        #print 'DEBUG: bytes_remaining %d' % bytes_remaining

        read_size = min(bytes_remaining, self._current_request.data_len)
        read_from_curr_req = self._current_request.data[:read_size]
        buffered_data.append(read_from_curr_req)
        # print 'DEBUG: read %d bytes into buffered data' % read_size

        new_curr_req_data_len = self._current_request.data_len - read_size
        self._position += read_size
        self._current_request = WriteRequest(True, self._position,
                                             read_from_curr_req, new_curr_req_data_len,
                                             self._current_request.last, None)
        bytes_remaining -= read_size

      else:
        self._buffer_nonempty.acquire()
        while not self._buffer:
          # Block until the buffer has bytes to read
          self._buffer_nonempty.wait()

        self._current_request = self.ReadFromBufferQueue()
        data_len = self._current_request.data_len
        self._buffer_start += data_len

        # print 'DEBUG: manager: %d, dec %d bytes' % (self._global_manager.getUsedMemory(), data_len)
        self._global_manager.available.acquire()
        self._global_manager.decMemory(data_len)
        self._global_manager.available.notify()
        self._global_manager.available.release()

        if(not self._current_request.last):
          self.RequestRead()

        self._buffer_nonempty.release()

    data = b''.join(buffered_data)
    # print 'DEBUG: returning %d bytes from read' % len(data)
    return data

  def ReadFromDisk(self, size=-1):  # pylint: disable=invalid-name
    """"Reads from the source file size bytes, and writes into the buffer queue
    of the file wrapper object.

    Args:
      size: The amount of bytes to read. If omitted or negative, the entire
          contents of the stream will be read and returned.
    """
    # print('DEBUG: readfromdisk\n')

    if self._done:
      self.close()
      return

    with self._file_lock:
      if self._stream is None:
        if not self.open():
          # Fail to open. open() already notified of the error
          return

      stream_position = self._stream.tell()
      try:
        data = []
        data_len = 0
        while True:
          data.append(self._stream.read(size))
          data_len += len(data[-1])
          if(data_len == size or self._stream.tell() == self._size):
            break
      except IOError as e:
        self.close()
        return

      data = ''.join(data)
      self._done = self._stream.tell() == self._size
      # Append new disk read onto local file operation buffer queue

      self._buffer_nonempty.acquire()
      self._buffer.append(WriteRequest(True, stream_position, data, len(data),
                                       self._done, None))
      self._buffer_nonempty.notify()
      self._buffer_nonempty.release()
      self._buffer_end += len(data)

      # Update global manager to include memory consumed
      # print 'DEBUG: disk read buffer: [%d, %d]' % (self._buffer_start, self._buffer_end)
      # print 'DEBUG: manager: %d, inc %d bytes' % (self._global_manager.getUsedMemory(), len(data))
      self._global_manager.incMemory(len(data))

      if self._done:
        self.close()
        return

  def tell(self):  # pylint: disable=invalid-name
    """Returns the current stream position."""
    return self._position

  def seekable(self):  # pylint: disable=invalid-name
    """Returns true since limited seek support exists."""
    return True

  def closed(self):
    """Returns if the file is closed."""
    return self._stream == None

  def seek(self, offset, whence=os.SEEK_SET):  # pylint: disable=invalid-name
    """Seeks on the buffered stream.

    Args:
      offset: The offset to seek to; must be within the buffer bounds.
      whence: Must be os.SEEK_SET.

    Raises:
      CommandException if an unsupported seek mode or position is used.
    """
    # print 'DEBUG: seek with %d' % offset
    if whence == os.SEEK_END:
      # Set offset to be offset from the beginning, then os.SEEK_END
      # and os.SEEK_SET can be handled in the same way
      offset = self._size - offset

    if(offset == self._position):
      return
    if offset < self._buffer_start:
      # If need to seek to bytes before the buffer, invalidate buffer bytes
      self._buffer = collections.deque()
      self._buffer_start = 0
      self._buffer_end = 0
      self._position = 0
      self._done = False
      self.read(offset)
    elif self._buffer_start <= offset:
      # Read until the new offset
      self.read(offset - self._position)
    else:
      raise CommandException('Invalid seek mode on streaming upload. '
                             '(mode %s, offset %s)' % (whence, offset))

