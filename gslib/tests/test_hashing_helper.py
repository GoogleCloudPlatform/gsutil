# -*- coding: utf-8 -*-
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
"""Unit tests for hashing helper functions and classes."""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

import hashlib
import os
import pkgutil
from unittest import mock

from gslib.exception import CommandException
from gslib.storage_url import StorageUrlFromString
import gslib.tests.testcase as testcase
from gslib.utils.constants import TRANSFER_BUFFER_SIZE
from gslib.utils.hashing_helper import CalculateMd5FromContents
from gslib.utils.hashing_helper import GetMd5
from gslib.utils.hashing_helper import HashingFileUploadWrapper

_TEST_FILE = 'test.txt'


class TestGetMd5(testcase.GsUtilUnitTestCase):
  """Unit tests for the GetMd5 function."""

  @mock.patch.object(hashlib, 'md5')
  def testGetsMd5HashOnNonRedHatSystem(self, mock_md5):
    # Can't actually compare output to calling hashlib.md5 because that could
    # trigger an error on a Red Hat system.
    mock_md5.return_value = 'hash'
    self.assertEqual(GetMd5(b''), 'hash')
    mock_md5.assert_called_once_with(b'')

  @mock.patch.object(hashlib, 'md5')
  def testGetsMd5HashOnRedHatSystem(self, mock_md5):
    # Can't actually compare output to calling hashlib.md5 because that could
    # trigger an error on a non-Red Hat system.
    # Return one ValueError to simulate a FIPS-mode distribution.
    mock_md5.side_effect = [ValueError, 'hash']
    self.assertEqual(GetMd5(b''), 'hash')
    self.assertEqual(
        mock_md5.mock_calls,
        [mock.call(b''), mock.call(b'', usedforsecurity=False)])


class TestHashingFileUploadWrapper(testcase.GsUtilUnitTestCase):
  """Unit tests for the HashingFileUploadWrapper class."""

  _temp_test_file = None
  _dummy_url = StorageUrlFromString('gs://bucket/object')

  def _GetTestFile(self):
    contents = pkgutil.get_data('gslib', 'tests/test_data/%s' % _TEST_FILE)
    if not self._temp_test_file:
      self._temp_test_file = self.CreateTempFile(file_name=_TEST_FILE,
                                                 contents=contents)
    return self._temp_test_file

  def testReadToEOF(self):
    digesters = {'md5': GetMd5()}
    tmp_file = self.CreateTempFile(contents=b'a' * TRANSFER_BUFFER_SIZE * 4)
    with open(tmp_file, 'rb') as stream:
      wrapper = HashingFileUploadWrapper(stream, digesters, {'md5': GetMd5},
                                         self._dummy_url, self.logger)
      wrapper.read()
    with open(tmp_file, 'rb') as stream:
      actual = CalculateMd5FromContents(stream)
    self.assertEqual(actual, digesters['md5'].hexdigest())

  def _testSeekBack(self, initial_position, seek_back_amount):
    """Tests reading then seeking backwards.

    This function simulates an upload that is resumed after a connection break.
    It reads one transfer buffer at a time until it reaches initial_position,
    then seeks backwards (as if the server did not receive some of the bytes)
    and reads to the end of the file, ensuring the hash matches the original
    file upon completion.

    Args:
      initial_position: Initial number of bytes to read before seek.
      seek_back_amount: Number of bytes to seek backward.

    Raises:
      AssertionError on wrong amount of data remaining or hash mismatch.
    """
    tmp_file = self._GetTestFile()
    tmp_file_len = os.path.getsize(tmp_file)

    self.assertGreaterEqual(
        initial_position, seek_back_amount,
        'seek_back_amount must be less than initial position %s '
        '(but was actually: %s)' % (initial_position, seek_back_amount))
    self.assertLess(
        initial_position, tmp_file_len,
        'initial_position must be less than test file size %s '
        '(but was actually: %s)' % (tmp_file_len, initial_position))

    digesters = {'md5': GetMd5()}
    with open(tmp_file, 'rb') as stream:
      wrapper = HashingFileUploadWrapper(stream, digesters, {'md5': GetMd5},
                                         self._dummy_url, self.logger)
      position = 0
      while position < initial_position - TRANSFER_BUFFER_SIZE:
        data = wrapper.read(TRANSFER_BUFFER_SIZE)
        position += len(data)
      wrapper.read(initial_position - position)
      wrapper.seek(initial_position - seek_back_amount)
      self.assertEqual(wrapper.tell(), initial_position - seek_back_amount)
      data = wrapper.read()
      self.assertEqual(len(data),
                       tmp_file_len - (initial_position - seek_back_amount))
    with open(tmp_file, 'rb') as stream:
      actual = CalculateMd5FromContents(stream)
    self.assertEqual(actual, digesters['md5'].hexdigest())

  def testSeekToBeginning(self):
    for num_bytes in (TRANSFER_BUFFER_SIZE - 1, TRANSFER_BUFFER_SIZE,
                      TRANSFER_BUFFER_SIZE + 1, TRANSFER_BUFFER_SIZE * 2 - 1,
                      TRANSFER_BUFFER_SIZE * 2, TRANSFER_BUFFER_SIZE * 2 + 1,
                      TRANSFER_BUFFER_SIZE * 3 - 1, TRANSFER_BUFFER_SIZE * 3,
                      TRANSFER_BUFFER_SIZE * 3 + 1):
      self._testSeekBack(num_bytes, num_bytes)

  def testSeekBackAroundOneBuffer(self):
    for initial_position in (TRANSFER_BUFFER_SIZE + 1,
                             TRANSFER_BUFFER_SIZE * 2 - 1,
                             TRANSFER_BUFFER_SIZE * 2,
                             TRANSFER_BUFFER_SIZE * 2 + 1,
                             TRANSFER_BUFFER_SIZE * 3 - 1,
                             TRANSFER_BUFFER_SIZE * 3,
                             TRANSFER_BUFFER_SIZE * 3 + 1):
      for seek_back_amount in (TRANSFER_BUFFER_SIZE - 1, TRANSFER_BUFFER_SIZE,
                               TRANSFER_BUFFER_SIZE + 1):
        self._testSeekBack(initial_position, seek_back_amount)

  def testSeekBackMoreThanOneBuffer(self):
    for initial_position in (TRANSFER_BUFFER_SIZE * 2 + 1,
                             TRANSFER_BUFFER_SIZE * 3 - 1,
                             TRANSFER_BUFFER_SIZE * 3,
                             TRANSFER_BUFFER_SIZE * 3 + 1):
      for seek_back_amount in (TRANSFER_BUFFER_SIZE * 2 - 1,
                               TRANSFER_BUFFER_SIZE * 2,
                               TRANSFER_BUFFER_SIZE * 2 + 1):
        self._testSeekBack(initial_position, seek_back_amount)

  def _testSeekForward(self, initial_seek):
    """Tests seeking to an initial position and then reading.

    This function simulates an upload that is resumed after a process break.
    It seeks from zero to the initial position (as if the server already had
    those bytes). Then it reads to the end of the file, ensuring the hash
    matches the original file upon completion.

    Args:
      initial_seek: Number of bytes to initially seek.

    Raises:
      AssertionError on wrong amount of data remaining or hash mismatch.
    """
    tmp_file = self._GetTestFile()
    tmp_file_len = os.path.getsize(tmp_file)

    self.assertLess(
        initial_seek, tmp_file_len,
        'initial_seek must be less than test file size %s '
        '(but was actually: %s)' % (tmp_file_len, initial_seek))

    digesters = {'md5': GetMd5()}
    with open(tmp_file, 'rb') as stream:
      wrapper = HashingFileUploadWrapper(stream, digesters, {'md5': GetMd5},
                                         self._dummy_url, self.logger)
      wrapper.seek(initial_seek)
      self.assertEqual(wrapper.tell(), initial_seek)
      data = wrapper.read()
      self.assertEqual(len(data), tmp_file_len - initial_seek)
    with open(tmp_file, 'rb') as stream:
      actual = CalculateMd5FromContents(stream)
    self.assertEqual(actual, digesters['md5'].hexdigest())

  def testSeekForward(self):
    for initial_seek in (0, TRANSFER_BUFFER_SIZE - 1, TRANSFER_BUFFER_SIZE,
                         TRANSFER_BUFFER_SIZE + 1, TRANSFER_BUFFER_SIZE * 2 - 1,
                         TRANSFER_BUFFER_SIZE * 2,
                         TRANSFER_BUFFER_SIZE * 2 + 1):
      self._testSeekForward(initial_seek)

  def _testSeekAway(self, initial_read):
    """Tests reading to an initial position and then seeking to EOF and back.

    This function simulates an size check on the input file by seeking to the
    end of the file and then back to the current position. Then it reads to
    the end of the file, ensuring the hash matches the original file upon
    completion.

    Args:
      initial_read: Number of bytes to initially read.

    Raises:
      AssertionError on wrong amount of data remaining or hash mismatch.
    """
    tmp_file = self._GetTestFile()
    tmp_file_len = os.path.getsize(tmp_file)

    self.assertLess(
        initial_read, tmp_file_len,
        'initial_read must be less than test file size %s '
        '(but was actually: %s)' % (tmp_file_len, initial_read))

    digesters = {'md5': GetMd5()}
    with open(tmp_file, 'rb') as stream:
      wrapper = HashingFileUploadWrapper(stream, digesters, {'md5': GetMd5},
                                         self._dummy_url, self.logger)
      wrapper.read(initial_read)
      self.assertEqual(wrapper.tell(), initial_read)
      wrapper.seek(0, os.SEEK_END)
      self.assertEqual(wrapper.tell(), tmp_file_len)
      wrapper.seek(initial_read, os.SEEK_SET)
      data = wrapper.read()
      self.assertEqual(len(data), tmp_file_len - initial_read)
    with open(tmp_file, 'rb') as stream:
      actual = CalculateMd5FromContents(stream)
    self.assertEqual(actual, digesters['md5'].hexdigest())

  def testValidSeekAway(self):
    for initial_read in (0, TRANSFER_BUFFER_SIZE - 1, TRANSFER_BUFFER_SIZE,
                         TRANSFER_BUFFER_SIZE + 1, TRANSFER_BUFFER_SIZE * 2 - 1,
                         TRANSFER_BUFFER_SIZE * 2,
                         TRANSFER_BUFFER_SIZE * 2 + 1):
      self._testSeekAway(initial_read)

  def testInvalidSeekAway(self):
    """Tests seeking to EOF and then reading without first doing a SEEK_SET."""
    tmp_file = self._GetTestFile()
    digesters = {'md5': GetMd5()}
    with open(tmp_file, 'rb') as stream:
      wrapper = HashingFileUploadWrapper(stream, digesters, {'md5': GetMd5},
                                         self._dummy_url, self.logger)
      wrapper.read(TRANSFER_BUFFER_SIZE)
      wrapper.seek(0, os.SEEK_END)
      try:
        wrapper.read()
        self.fail('Expected CommandException for invalid seek.')
      except CommandException as e:
        self.assertIn(
            'Read called on hashing file pointer in an unknown position',
            str(e))

  def testWrapperInitializationErrors(self):
    tmp_file = self._GetTestFile()
    with open(tmp_file, 'rb') as stream:
      try:
        HashingFileUploadWrapper(stream, {}, {'md5': GetMd5}, self._dummy_url, self.logger)
        self.fail('Expected CommandException for empty digesters.')
      except CommandException as e:
        self.assertIn('used with no digesters', str(e))

      try:
        HashingFileUploadWrapper(stream, {'md5': GetMd5()}, {}, self._dummy_url, self.logger)
        self.fail('Expected CommandException for empty hash_algs.')
      except CommandException as e:
        self.assertIn('used with no hash_algs', str(e))


class TestCrcMath(testcase.GsUtilUnitTestCase):
  """Unit tests for ConcatCrc32c and helper functions."""

  def testConcatCrc32c(self):
    import crcmod
    from gslib.utils.hashing_helper import ConcatCrc32c

    crc_class = crcmod.predefined.Crc('crc-32c')

    a = b"Hello, "
    b = b"world!"
    ab = a + b

    crc_a = crc_class.copy()
    crc_a.update(a)
    crc_a_val = crc_a.crcValue

    crc_b = crc_class.copy()
    crc_b.update(b)
    crc_b_val = crc_b.crcValue

    crc_ab = crc_class.copy()
    crc_ab.update(ab)
    crc_ab_val = crc_ab.crcValue

    concat_val = ConcatCrc32c(crc_a_val, crc_b_val, len(b))
    self.assertEqual(concat_val, crc_ab_val)


class TestHashHelpers(testcase.GsUtilUnitTestCase):
  """Unit tests for conversion and hash calculation helpers."""

  def testHashConversions(self):
    from gslib.utils.hashing_helper import Base64EncodeHash, Base64ToHexHash
    hex_digest = 'f447b20a7fcbf53a5d5be013ea0b15af'
    base64_digest = '9EeyCn/L9TpdW+AT6gsVrw=='

    self.assertEqual(Base64EncodeHash(hex_digest), base64_digest)
    self.assertEqual(Base64ToHexHash(base64_digest), hex_digest.encode('ascii'))

  def testCalculateB64EncodedHashes(self):
    from gslib.utils.hashing_helper import (
        CalculateB64EncodedCrc32cFromContents,
        CalculateB64EncodedMd5FromContents
    )
    contents = b'123456\n'
    tmp_file = self.CreateTempFile(contents=contents)

    with open(tmp_file, 'rb') as fp:
      crc = CalculateB64EncodedCrc32cFromContents(fp)
    with open(tmp_file, 'rb') as fp:
      md5 = CalculateB64EncodedMd5FromContents(fp)

    self.assertEqual(crc, 'nYmSiA==')
    self.assertEqual(md5, '9EeyCn/L9TpdW+AT6gsVrw==')


class TestHashConfig(testcase.GsUtilUnitTestCase):
  """Unit tests for config-based upload/download hash functions."""

  def testGetUploadHashAlgs(self):
    from gslib.tests.util import SetBotoConfigForTest
    from gslib.utils import hashing_helper
    with SetBotoConfigForTest([('GSUtil', 'check_hashes', 'never')]):
      self.assertEqual(hashing_helper.GetUploadHashAlgs(), {})
    with SetBotoConfigForTest([('GSUtil', 'check_hashes', 'always')]):
      algs = hashing_helper.GetUploadHashAlgs()
      self.assertIn('md5', algs)
      self.assertEqual(algs['md5']().hexdigest(), GetMd5().hexdigest())

  def testGetDownloadHashAlgs(self):
    from gslib.tests.util import SetBotoConfigForTest
    from gslib.utils import hashing_helper
    # Test CHECK_HASH_NEVER
    with SetBotoConfigForTest([('GSUtil', 'check_hashes', 'never')]):
      self.assertEqual(hashing_helper.GetDownloadHashAlgs(self.logger, consider_md5=True), {})

    # Test MD5 always preferred
    with SetBotoConfigForTest([('GSUtil', 'check_hashes', 'always')]):
      algs = hashing_helper.GetDownloadHashAlgs(self.logger, consider_md5=True)
      self.assertIn('md5', algs)

    # Test misconfigured option raises CommandException
    with SetBotoConfigForTest([('GSUtil', 'check_hashes', 'invalid_option')]):
      try:
        hashing_helper.GetDownloadHashAlgs(self.logger, consider_crc32c=True)
        self.fail('Expected CommandException for invalid check_hashes config.')
      except CommandException as e:
        self.assertIn('option is misconfigured', str(e))

