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
"""Helper class for disk read file wrapper object."""

import collections
import os
import threading

from gslib.exception import CommandException

WriteRequest = collections.namedtuple('WriteRequest', (
    'success',         # Whether the read operation succeeded.
    'position',        # The position where the read operator started.
    'data',            # The data read.
    'data_len',        # The length of the data read.
    'err_msg'))        # Error message if success is False.


class DiskReadFileWrapperObject(object):
  """Wraps a file into a Python file-like stream.

  This class takes a source file, communicates with the file operation
  thread to read from the disk, and exposes it as a stream.
  """

  def __init__(self, source_file_url, source_file_size, buffer_size,
               manager=None, file_obj_queue=None):
    """Initializes the wrapper.

    Args:
      source_file_url: Source file that represents the file to be read
          from the disk.
      source_file_size: Size of the source file in bytes.
      buffer_size: Maximum buffer size in bytes that the file wrapper
          object can request for a data read from disk at a time.
      manager: Manager that is only passed in for testing unit tests.
      file_obj_queue: File object queue that is only passed in for testing
          unit tests.
    """
    # Local file information.
    self._source_url = source_file_url
    self.name = source_file_url.object_name
    self._size = source_file_size

    self._stream = None
    self._done = False

    self._buffer_size = buffer_size
    # Maximum number of buffers allowed on the file wrapper object's buffer
    # queue at once, serves as a representation of the maximum number of bytes
    # that can be stored in this wrapper object.
    # TODO: Update maximum buffer queue length based on specified maximum
    # system memory limit and/or dynamically change based on process and
    # thread count.
    self._max_buffer_queue_size = 2
    self._buffer_queue = collections.deque()
    # The start and end of the stream that the buffer currently contains.
    self._buffer_queue_start = 0
    self._buffer_queue_end = 0
    self._buffer_queue_nonempty = threading.Condition()
    self._position = 0
    # Most recently popped request from the buffer.
    self._current_request = None

    if manager is None:
      # command is imported here so that the manager and file_obj_queue can
      # be instantiated first in command.py.
      import gslib.command as command   # pylint: disable=g-import-not-at-top
      self._global_manager = command.file_op_manager
      self._read_queue = command.file_obj_queue
    else:
      self._global_manager = manager
      self._read_queue = file_obj_queue

    # Send the first requests for buffer of size max_buffer_size. The number
    # of outstanding requests will be monitored and maintained by the
    # wrapper object to ensure that the max_buffer_queue_size will not be
    # exceeded.
    for _ in xrange(self._max_buffer_queue_size):
      self._RequestRead()
    self._stream = open(self._source_url.object_name, 'rb')

  def close(self):
    """Closes the local file, if necessary."""
    self._done = True
    self._stream.close()

  def _RequestRead(self, blocks=1):  # pylint: disable=invalid-name
    """Queues a read for this file."""
    if not self._done:
      # Send <blocks> number of requests for max_buffer_size bytes to read.
      # Note: For future optimizations, can dynamically change the number
      # of blocks and request size.
      for _ in xrange(blocks):
        self._read_queue.put((self, self._buffer_size))

  def read(self, size=-1):
    """Reads "size" bytes from the file wrapper object stream.

    Args:
      size: The size is the number of bytes that are to be read from the file.
          Default size is -1, which means read EOF.

    Returns:
      "size" number of bytes from the file, and the rest of the file if
          size=-1.

    Raises:
      CommandException: We fetched a WriteRequest from the buffer queue
          indicating that a disk read was unsuccessful.
    """
    read_all_bytes = size is None or size < 0
    if read_all_bytes:
      bytes_remaining = self._size
    else:
      bytes_remaining = size
    buffered_data = []

    while bytes_remaining > 0 and self._position != self._size:
      # There are still bytes to read.
      if(self._current_request is not None and
         self._current_request.data_len > 0):
        # Check if there's remainder bytes in the current_request buffer to
        # read from and process before dequeuing the next buffer read
        # from the buffer queue.
        read_size = min(bytes_remaining, self._current_request.data_len)
        read_from_curr_req = self._current_request.data[:read_size]
        buffered_data.append(read_from_curr_req)

        self._position += read_size
        new_curr_req_data = self._current_request.data[read_size:]
        new_curr_req_data_len = self._current_request.data_len - read_size
        self._current_request = WriteRequest(
            True, self._position, new_curr_req_data,
            new_curr_req_data_len, None)
        bytes_remaining -= read_size
      else:
        # No more bytes in the current_request buffer, so dequeue next read
        # buffer from buffer queue.
        self._buffer_queue_nonempty.acquire()
        # Since seek and read cannot be called simultaneously, we will
        # never remove items from the queue asynchronously. However, a seek
        # could invalidate the buffer queue, but outstanding requests to the
        # file operation thread could signal the condition after the queue was
        # cleared. Therefore, now that the nonempty Condition has been signaled,
        # ensure that the queue is nonempty before proceeding or else wait
        # again.
        while not self._buffer_queue:
          # Block until the buffer queue has bytes to read.
          self._buffer_queue_nonempty.wait()

        self._current_request = self._buffer_queue.popleft()
        self._buffer_queue_nonempty.release()
        # If the read from the disk was not a success, then raise
        # CommandException.
        if not self._current_request.success:
          raise CommandException(self._current_request.err_msg)

        # Update the buffer_queue_start and global file operation manager to
        # reflect the system memory used since the request has been completed.
        # In the current implementation, the request size is always
        # <buffer_size> and the file operation thread asks the file operation
        # manager to allocate enough for the full buffer size. Therefore, we
        # update the buffer_queue_start and manager by <buffer_size> every time
        # even if it may be EOF and there are less than <buffer_size> bytes in
        # the most recently popped buffer queue element.
        self._buffer_queue_start += self._buffer_size
        self._global_manager.available.acquire()
        self._global_manager.FreeMemory(self._buffer_size)
        # Check if there are still bytes in the file to be read. If there are,
        # then send a new request to the read request queue and increment the
        # buffer end to represent the to-be allocated buffer space. Similar
        # to the file operation manager's memory value, buffer_queue_end
        # represents the amount of buffer space that is reserved to be allowed
        # to be allocated and at the EOF may be an overestimate of the actual
        # buffer queue size.
        # Note: if/when request sizes other than
        # <buffer_size> are sent, this decrement in memory in the file
        # operation manager and this increment in the buffer_queue_end will
        # need to be modified to reflect the updated request sizes.
        if self._buffer_queue_end < self._size:
          self._RequestRead()
          self._buffer_queue_end += self._buffer_size
        self._global_manager.available.notify()
        self._global_manager.available.release()

    data = b''.join(buffered_data)
    return data

  def ReadFromDisk(self, size=-1):  # pylint: disable=invalid-name
    """"Reads from the source file "size" bytes from the disk.

    This function is called by the File Operation Thread, and reads from the
    disk the desired number of bytes and enqueues the bytes onto the buffer
    queue of the file wrapper object.

    Args:
      size: The amount of bytes to read. If omitted or negative, the entire
          contents of the stream will be read and returned.
    """
    if self._done or self._stream is None:
      return

    stream_position = self._stream.tell()
    try:
      data = []
      data_len = 0
      while True:
        data.append(self._stream.read(size))
        data_len += len(data[-1])
        if data_len == size or self._stream.tell() == self._size:
          break
    except IOError as e:
      self._buffer_queue.append(WriteRequest(
          False, stream_position, None, None, str(e)))
      return

    data = ''.join(data)
    self._done = self._stream.tell() == self._size

    # Append new disk read onto local file operation buffer queue.
    self._buffer_queue_nonempty.acquire()
    self._buffer_queue.append(WriteRequest(
        True, stream_position, data, len(data), None))
    self._buffer_queue_nonempty.notify()
    self._buffer_queue_nonempty.release()

    return

  def tell(self):
    """Returns the current stream position."""
    return self._position

  def seekable(self):  # pylint: disable=invalid-name
    """Returns true since limited seek support exists."""
    return True

  def closed(self):
    """Returns if the file is closed."""
    return self._stream.closed

  def seek(self, offset, whence=os.SEEK_SET):  # pylint: disable=invalid-name
    """Seeks on the buffered stream.

    Args:
      offset: The offset to seek to; must be within the buffer bounds.
      whence: The location in the file where the offset is relative to.
        os.SEEK_SET refers to the start of the stream; os.SEEK_CUR, the current
        stream position; os.SEEK_END, the end of the stream.

    Raises:
      CommandException if an unsupported seek mode or position is used.
    """
    if whence == os.SEEK_END:
      # Check whence to see where offset is set relative to, then set
      # offset to be offset from the beginning so that all cases of whence can
      # be handled in the same way.
      offset = self._size + offset
    if whence == os.SEEK_CUR:
      offset = self._position + offset

    if offset == self._position:
      return
    elif offset < self._position:
      # If need to seek to bytes before the buffer, invalidate buffer bytes.
      self._buffer_queue = collections.deque()
      self._position = 0
      self._done = False
      self._stream.seek(0)
      self._current_request = None

      self._global_manager.available.acquire()
      # Note that self._buffer_queue_end - self._buffer_queue_start may be an
      # overestimate of the actual size of the buffer queue. (end - start)
      # represents the amount of bytes reserved for this wrapper object's
      # buffers. These reservations will eventually be allocated by the
      # FileOperationManager.
      self._global_manager.FreeMemory(
          self._buffer_queue_end - self._buffer_queue_start)
      self._buffer_queue_start = 0
      self._buffer_queue_end = 0
      for _ in xrange(self._max_buffer_queue_size):
        self._RequestRead()
      self._global_manager.available.notify()
      self._global_manager.available.release()

      self.read(offset)
    elif offset <= self._size:
      # Offset is greater than position and offset is within file size bounds.
      self.read(offset - self._position)
    else:
      raise CommandException('Invalid seek (mode %s), seeking to offset %s but '
                             'end-of-file is %s' % (whence, offset, self._size))
