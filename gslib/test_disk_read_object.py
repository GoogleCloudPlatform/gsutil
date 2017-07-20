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
"""Unit tests for disk read file wrapper object functions and classes."""

from __future__ import absolute_import

import os
import pkgutil

from gslib.disk_read_object import DiskReadFileWrapperObject
import gslib.tests.testcase as testcase
from gslib.util import GetJsonResumableChunkSize
from gslib.util import GetStreamFromFileUrl
from gslib.storage_url import StorageUrlFromString

_TEST_FILE = 'test.txt'
TEST_MAX_BUFFER_SIZE = 512

class TestDiskReadFileWrapperObject(testcase.GsUtilUnitTestCase):
  """Unit tests for the DiskReadFileWrapperObject class."""

  _temp_test_file = None
  _temp_test_file_contents = None
  _temp_test_file_len = None

  def _GetTestFile(self):
    if not self._temp_test_file:
      self._temp_test_file_contents = pkgutil.get_data(
          'gslib', 'tests/test_data/%s' % _TEST_FILE)
      self._temp_test_file = self.CreateTempFile(
          file_name=_TEST_FILE, contents=self._temp_test_file_contents)
      self._temp_test_file_len = len(self._temp_test_file_contents)
    return self._temp_test_file

  def testInit(self):
    print 'DEBUG: beginning'
    tmp_file = self._GetTestFile()
    print 'DEBUG: init wrapper object'
    wrapper = DiskReadFileWrapperObject(
        StorageUrlFromString(tmp_file), self._temp_test_file_len, TEST_MAX_BUFFER_SIZE)

  def testReadMaxBufferSizeAndTell(self):
    """Reads from both wrapper stream and real stream return the same position
    in the file when file.tell() is called."""
    print 'DEBUG: beginning'
    tmp_file = self._GetTestFile()
    print 'DEBUG: init wrapper object'
    wrapper = DiskReadFileWrapperObject(
        StorageUrlFromString(tmp_file), self._temp_test_file_len, TEST_MAX_BUFFER_SIZE)
    print 'DEBUG: open'
    wrapper_stream = wrapper.open()
    print 'DEBUG: before insert'
    self.assertEqual(0, wrapper_stream.tell())

    print 'DEBUG: before read'
    wrapper_buffer_data = wrapper_stream.read(TEST_MAX_BUFFER_SIZE)
    print 'DEBUG: after read'
    self.assertEqual(TEST_MAX_BUFFER_SIZE, wrapper_filestream.tell())

  def testRead(self):
    """Reads from both wrapper stream and real stream and test that the
    same data is being read and returned."""
    tmp_file = self._GetTestFile()
    wrapper = DiskReadFileWrapperObject(
        tmp_file, self._temp_test_file_len, TEST_MAX_BUFFER_SIZE)
    wrapper_stream = wrapper.open()

    # Check that each chunk read is as expected
    while not wrapper_stream.tell() == self._temp_test_file_len:
      wrapper_buffer_data = wrapper_stream.read(TEST_MAX_BUFFER_SIZE)
      self.assertEqual(wrapper_buffer_data,
                       self._temp_test_file_contents[-len(wrapper_buffer_data):])

  def testClosed(self):
    """Reads the whole file from file wrapper object and tests that the file
    is closed afterwards."""
    tmp_file = self._GetTestFile()
    wrapper = DiskReadFileWrapperObject(
        tmp_file, self._temp_test_file_len, TEST_MAX_BUFFER_SIZE)
    wrapper_stream = wrapper.open()

    wrapper_buffer_data = wrapper_stream.read(self._temp_test_file_len)
    self.assertEqual(wrapper_stream.closed(), True)

  def testReadThenSeekToBeginning(self):
    """Reads one buffer and seeks back to the beginning."""
    tmp_file = self._GetTestFile()
    wrapper = DiskReadFileWrapperObject(
        tmp_file, self._temp_test_file_len, TEST_MAX_BUFFER_SIZE)
    wrapper_stream = wrapper.open()

    wrapper_buffer_data = wrapper_stream.read(2 * TEST_MAX_BUFFER_SIZE)
    wrapper_stream.seek(0)
    self.assertEqual(0, wrapper_stream.tell())

  def testReadChunksThenSeekBack(self):
    """Reads one buffer, then seeks back one buffer_size
    and reads chunks until the end."""
    tmp_file = self._GetTestFile()
    wrapper = DiskReadFileWrapperObject(
        tmp_file, self._temp_test_file_len, TEST_MAX_BUFFER_SIZE)
    wrapper_stream = wrapper.open()
    actual_filestream = GetStreamFromFileUrl(tmp_file)

    wrapper_buffer_data = wrapper_stream.read(2 * TEST_MAX_BUFFER_SIZE)
    wrapper_stream.seek(TEST_MAX_BUFFER_SIZE)
    wrapper_buffer_data = wrapper_stream.read(TEST_MAX_BUFFER_SIZE)

    actual_buffer_data = actual_stream.read(2 * TEST_MAX_BUFFER_SIZE)
    actual_stream.seek(TEST_MAX_BUFFER_SIZE)
    actual_buffer_data = actual_stream.read(TEST_MAX_BUFFER_SIZE)

    self.assertEqual(TEST_MAX_BUFFER_SIZE, wrapper_stream.tell())
    self.assertEqual(wrapper_buffer_data, actual_buffer_data)

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
      buffer_size: Maximum buffer size for the wrapper.
      seek_back_amount: N umber of bytes to seek backward.

    Raises:
      AssertionError on wrong data returned by the wrapper.
    """
    tmp_file = self._GetTestFile()
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


    wrapper = DiskReadFileWrapperObject(
        tmp_file, self._temp_test_file_len, TEST_MAX_BUFFER_SIZE)
    wrapper_stream = wrapper.open()
    position = 0
    for read_size in initial_reads:
      data = wrapper_stream.read(read_size)
      self.assertEqual(
          self._temp_test_file_contents[position:position + read_size],
          data, 'Data from position %s to %s did not match file contents.' %
          (position, position + read_size))
      position += len(data)
    wrapper_stream.seek(initial_position - seek_back_amount)
    self.assertEqual(wrapper_stream.tell(),
                     initial_position - seek_back_amount)
    data = wrapper_stream.read()
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
    """Tests performing reads on the wrapper, seeking, then reading to EOF."""
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
    tmp_file = self._GetTestFile()
    read_size = TEST_MAX_BUFFER_SIZE

    wrapper = DiskReadFileWrapperObject(
        tmp_file, self._temp_test_file_len, TEST_MAX_BUFFER_SIZE * 3)
    wrapper_stream = wrapper.open()

    position = 0
    for _ in xrange(3):
      data = wrapper_stream.read(read_size)
      self.assertEqual(
          self._temp_test_file_contents[position:position + read_size],
          data, 'Data from position %s to %s did not match file contents.' %
          (position, position + read_size))
      position += len(data)

    data = wrapper_stream.read(read_size / 2)
    # Buffer contents should now be have contents from:
    # read_size/2 through 7*read_size/2.
    position = read_size / 2
    wrapper_stream.seek(position)
    data = wrapper_stream.read()
    self.assertEqual(
        self._temp_test_file_contents[-len(data):], data,
        'Data from position %s to EOF did not match file contents.' %
        position)

  def testSeekEnd(self):
    tmp_file = self._GetTestFile()
    for buffer_size in (TEST_MAX_BUFFER_SIZE - 1,
                        TEST_MAX_BUFFER_SIZE,
                        TEST_MAX_BUFFER_SIZE + 1):
      for seek_back in (TEST_MAX_BUFFER_SIZE - 1,
                        TEST_MAX_BUFFER_SIZE,
                        TEST_MAX_BUFFER_SIZE + 1):
        expect_exception = seek_back > buffer_size

        wrapper = DiskReadFileWrapperObject(
            tmp_file, self._temp_test_file_len, TEST_MAX_BUFFER_SIZE)
        wrapper_stream = wrapper.open()

        # Read to the end.
        while wrapper_stream.read(TEST_MAX_BUFFER_SIZE):
          pass
        try:
          wrapper_stream.seek(seek_back, whence=os.SEEK_END)
          if expect_exception:
            self.fail('Did not get expected CommandException for '
                      'seek_back size %s, buffer size %s' %
                      (seek_back, buffer_size))
        except CommandException, e:
          if not expect_exception:
            self.fail('Got unexpected CommandException "%s" for '
                      'seek_back size %s, buffer size %s' %
                      (str(e), seek_back, buffer_size))
