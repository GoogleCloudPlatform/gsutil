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
"""Unit tests for disk read object functions and classes."""

from __future__ import absolute_import

from functools import partial
import os
import pkgutil

from gslib.disk_read_object import DiskReadFileWrapperObject
from gslib.storage_url import StorageUrlFromString
import gslib.tests.testcase as testcase
import mock

_TEST_FILE = 'test.txt'
TEST_MAX_BUFFER_SIZE = 512


class TestDiskReadFileWrapperObject(testcase.GsUtilUnitTestCase):
  """Unit tests for the DiskReadFileWrapperObject class."""

  _temp_test_file = None
  _temp_test_file_contents = None
  _temp_test_file_len = None
  _test_wrapper = None
  _test_wrapper_stream = None
  _test_wrapper_buffer_data = None

  def _GetTestFile(self):
    if not self._temp_test_file:
      self._temp_test_file_contents = pkgutil.get_data(
          'gslib', 'tests/test_data/%s' % _TEST_FILE)
      self._temp_test_file = self.CreateTempFile(
          file_name=_TEST_FILE, contents=self._temp_test_file_contents)
      self._temp_test_file_len = len(self._temp_test_file_contents)
    return self._temp_test_file

  def _mock_read(self, size=-1, wrapper_object_stream=None):
    """Mock out the read operation for the file wrapper objects.

    The mock explicitly populates the buffer queue (mocking the File Operation
    Thread's job of enqueuing the buffer queue) so that when seek is called,
    there is data to read.

    Args:
      size: Size of memory to read from the disk. Default of -1 indicates
        from the whole file.
      wrapper_object_stream: Wrapper object stream that is to be read from.

    Returns:
      The bytes read from the disk and passed through the network by
        the file wrapper object.
    """
    wrapper_object_stream.ReadFromDisk(size)
    return wrapper_object_stream.original_read(size)

  def _GenerateMockObject(self):
    """Generates a file wrapper object.

    The object wraps the test file and includes _mock_read as
    the mocked read function.
    """
    tmp_file = self._GetTestFile()
    self._test_wrapper = DiskReadFileWrapperObject(
        StorageUrlFromString(tmp_file), self._temp_test_file_len,
        TEST_MAX_BUFFER_SIZE)
    self._test_wrapper_stream = self._test_wrapper.open()
    # Create a mock for the file read function
    self._test_wrapper_stream.original_read = mock.Mock(
        side_effect=self._test_wrapper_stream.read)
    self._test_wrapper_stream.read = mock.Mock(
        side_effect=partial(self._mock_read,
                            wrapper_object_stream=self._test_wrapper_stream))

  def testInit(self):
    """Confirms the starting file pointer is at the beginning of the file."""
    tmp_file = self._GetTestFile()
    self._test_wrapper = DiskReadFileWrapperObject(
        StorageUrlFromString(tmp_file), self._temp_test_file_len,
        TEST_MAX_BUFFER_SIZE)
    self._test_wrapper_stream = self._test_wrapper.open()
    self.assertEqual(0, self._test_wrapper_stream.tell())

  def testReadMaxBufferSizeAndTell(self):
    """Reads from disk and asserts that the stream reads the right amount."""
    self._GenerateMockObject()

    self._test_wrapper_buffer_data = self._test_wrapper_stream.read(
        TEST_MAX_BUFFER_SIZE)
    self.assertEqual(TEST_MAX_BUFFER_SIZE, self._test_wrapper_stream.tell())
    self.assertEqual(self._temp_test_file_contents[:TEST_MAX_BUFFER_SIZE],
                     self._test_wrapper_buffer_data)

  def testReadWholeFile(self):
    """Reads the whole file and asserts accurate data from file is read."""
    self._GenerateMockObject()

    # Check that each chunk read is as expected
    while self._test_wrapper_stream.tell() != self._temp_test_file_len:
      old_position = self._test_wrapper.tell()
      self._test_wrapper_buffer_data = self._test_wrapper_stream.read(
          TEST_MAX_BUFFER_SIZE)
      new_position = self._test_wrapper.tell()
      self.assertEqual(self._test_wrapper_buffer_data,
                       self._temp_test_file_contents[old_position:new_position])

  def testClosed(self):
    """Reads the whole file and tests that the file is closed afterwards."""
    self._GenerateMockObject()

    self._test_wrapper_buffer_data = self._test_wrapper_stream.read(
        self._temp_test_file_len)
    self.assertEqual(self._test_wrapper_stream.closed(), True)

  def testReadThenSeekToBeginning(self):
    """Reads two buffers and seeks back to the beginning."""
    self._GenerateMockObject()

    self._test_wrapper_buffer_data = self._test_wrapper_stream.read(
        2 * TEST_MAX_BUFFER_SIZE)
    self.assertEqual(self._test_wrapper_buffer_data,
                     self._temp_test_file_contents[:2 * TEST_MAX_BUFFER_SIZE])

    self._test_wrapper_stream.seek(0)
    self.assertEqual(0, self._test_wrapper_stream.tell())

    self._test_wrapper_buffer_data = self._test_wrapper_stream.read(
        2 * TEST_MAX_BUFFER_SIZE)
    self.assertEqual(2 * TEST_MAX_BUFFER_SIZE, self._test_wrapper_stream.tell())
    self.assertEqual(self._test_wrapper_buffer_data,
                     self._temp_test_file_contents[:2 * TEST_MAX_BUFFER_SIZE])

  def testReadChunksThenSeekBack(self):
    """Reads two chunks, seeks back one chunk, and reads two more chunks."""
    self._GenerateMockObject()

    # Read two chunks of data from the disk.
    self._test_wrapper_buffer_data = self._test_wrapper_stream.read(
        2 * TEST_MAX_BUFFER_SIZE)
    self.assertEqual(2 * TEST_MAX_BUFFER_SIZE, self._test_wrapper_stream.tell())
    self.assertEqual(self._test_wrapper_buffer_data,
                     self._temp_test_file_contents[:2 * TEST_MAX_BUFFER_SIZE])

    # Seek to before current file pointer.
    self._test_wrapper_stream.seek(TEST_MAX_BUFFER_SIZE)
    self.assertEqual(TEST_MAX_BUFFER_SIZE, self._test_wrapper_stream.tell())

    # Read ahead again.
    self._test_wrapper_buffer_data = self._test_wrapper_stream.read(
        2 * TEST_MAX_BUFFER_SIZE)
    self.assertEqual(3 * TEST_MAX_BUFFER_SIZE, self._test_wrapper_stream.tell())
    self.assertEqual(self._test_wrapper_buffer_data,
                     self._temp_test_file_contents[
                         TEST_MAX_BUFFER_SIZE:3 * TEST_MAX_BUFFER_SIZE])

  def _testSeekBack(self, initial_reads, buffer_size, seek_back_amount):
    """Tests reading then seeking backwards.

    This function simulates an upload that is resumed after a connection break.
    It reads one transfer buffer at a time until it reaches initial_position,
    then seeks backwards (as if the server did not receive some of the bytes)
    and reads to the end of the file, ensuring the data read after the seek
    matches the original file.

    Args:
      initial_reads: List of integers containing read sizes to perform
          before seek.
      buffer_size: Maximum buffer size for the self._test_wrapper.
      seek_back_amount: Number of bytes to seek backward.

    Raises:
      AssertionError on wrong data returned by the self._test_wrapper.
    """
    self._GenerateMockObject()
    initial_position = 0
    for read_size in initial_reads:
      initial_position += read_size
    self.assertGreaterEqual(
        buffer_size, seek_back_amount,
        'seek_back_amount must be less than initial position %s '
        '(but was actually: %s)' % (buffer_size, seek_back_amount))
    self.assertLess(
        initial_position, self._temp_test_file_len,
        'initial_position must be less than test file size %s '
        '(but was actually: %s)' % (self._temp_test_file_len, initial_position))

    position = 0
    for read_size in initial_reads:
      data = self._test_wrapper_stream.read(read_size)
      self.assertEqual(
          self._temp_test_file_contents[position:position + read_size],
          data, 'Data from position %s to %s did not match file contents.' %
          (position, position + read_size))
      position += len(data)

    self._test_wrapper_stream.seek(initial_position - seek_back_amount)
    self.assertEqual(self._test_wrapper_stream.tell(),
                     initial_position - seek_back_amount)
    data = self._test_wrapper_stream.read()
    self.assertEqual(
        self._temp_test_file_len - (initial_position - seek_back_amount),
        len(data),
        'Unexpected data length with initial pos %s seek_back_amount %s. '
        'Expected: %s, actual: %s.' %
        (initial_position, seek_back_amount,
         self._temp_test_file_len - (initial_position - seek_back_amount),
         len(data)))
    self.assertEqual(
        self._temp_test_file_contents[-len(data):], data,
        'Data from position %s to EOF did not match file contents.' %
        position)

  def testReadSeekAndReadToEOF(self):
    """Tests performing reads, seeking, then reading to EOF."""
    for initial_reads in ([1],
                          [TEST_MAX_BUFFER_SIZE - 1],
                          [TEST_MAX_BUFFER_SIZE],
                          [TEST_MAX_BUFFER_SIZE + 1],
                          [1, TEST_MAX_BUFFER_SIZE - 1],
                          [1, TEST_MAX_BUFFER_SIZE],
                          [1, TEST_MAX_BUFFER_SIZE + 1],
                          [TEST_MAX_BUFFER_SIZE - 1, 1],
                          [TEST_MAX_BUFFER_SIZE, 1],
                          [TEST_MAX_BUFFER_SIZE + 1, 1],
                          [TEST_MAX_BUFFER_SIZE - 1, TEST_MAX_BUFFER_SIZE - 1],
                          [TEST_MAX_BUFFER_SIZE - 1, TEST_MAX_BUFFER_SIZE],
                          [TEST_MAX_BUFFER_SIZE - 1, TEST_MAX_BUFFER_SIZE + 1],
                          [TEST_MAX_BUFFER_SIZE, TEST_MAX_BUFFER_SIZE - 1],
                          [TEST_MAX_BUFFER_SIZE, TEST_MAX_BUFFER_SIZE],
                          [TEST_MAX_BUFFER_SIZE, TEST_MAX_BUFFER_SIZE + 1],
                          [TEST_MAX_BUFFER_SIZE + 1, TEST_MAX_BUFFER_SIZE - 1],
                          [TEST_MAX_BUFFER_SIZE + 1, TEST_MAX_BUFFER_SIZE],
                          [TEST_MAX_BUFFER_SIZE + 1, TEST_MAX_BUFFER_SIZE + 1],
                          [TEST_MAX_BUFFER_SIZE, TEST_MAX_BUFFER_SIZE,
                           TEST_MAX_BUFFER_SIZE]):
      initial_position = 0
      for read_size in initial_reads:
        initial_position += read_size
      for buffer_size in (initial_position,
                          initial_position + 1,
                          initial_position * 2 - 1,
                          initial_position * 2):
        for seek_back_amount in (
            min(TEST_MAX_BUFFER_SIZE - 1, initial_position),
            min(TEST_MAX_BUFFER_SIZE, initial_position),
            min(TEST_MAX_BUFFER_SIZE + 1, initial_position),
            min(TEST_MAX_BUFFER_SIZE * 2 - 1, initial_position),
            min(TEST_MAX_BUFFER_SIZE * 2, initial_position),
            min(TEST_MAX_BUFFER_SIZE * 2 + 1, initial_position)):
          self._testSeekBack(initial_reads, buffer_size, seek_back_amount)

  def testSeekPartialBuffer(self):
    """Tests seeking back partially within the buffer."""
    self._GenerateMockObject()
    read_size = TEST_MAX_BUFFER_SIZE

    position = 0
    for _ in xrange(3):
      data = self._test_wrapper_stream.read(read_size)
      self.assertEqual(
          self._temp_test_file_contents[position:position + read_size],
          data, 'Data from position %s to %s did not match file contents.' %
          (position, position + read_size))
      position += len(data)

    data = self._test_wrapper_stream.read(read_size / 2)
    # Buffer contents should now be have contents from:
    # read_size/2 through 7*read_size/2.
    position = read_size / 2
    self._test_wrapper_stream.seek(position)
    data = self._test_wrapper_stream.read()
    self.assertEqual(
        self._temp_test_file_contents[-len(data):], data,
        'Data from position %s to EOF did not match file contents.' %
        position)

  def testSeekEnd(self):
    """Tests seeking from the end of the file."""
    for buffer_size in (TEST_MAX_BUFFER_SIZE - 1,
                        TEST_MAX_BUFFER_SIZE,
                        TEST_MAX_BUFFER_SIZE + 1):
      for seek_back in (TEST_MAX_BUFFER_SIZE - 1,
                        TEST_MAX_BUFFER_SIZE,
                        TEST_MAX_BUFFER_SIZE + 1):
        self._GenerateMockObject()

        # Read to the end.
        while self._test_wrapper_stream.read(buffer_size):
          pass
        self._test_wrapper_stream.seek(seek_back, whence=os.SEEK_END)
        self.assertEqual(self._temp_test_file_len - seek_back,
                         self._test_wrapper_stream.tell())
