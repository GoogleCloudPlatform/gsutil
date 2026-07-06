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
"""Unit tests for functions in rsync command."""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

import logging
import os
from unittest import mock

from gslib.commands.rsync import _ComputeNeededFileChecksums
from gslib.commands.rsync import _NA
from gslib.tests.testcase.unit_testcase import GsUtilUnitTestCase
from gslib.utils.hashing_helper import CalculateB64EncodedCrc32cFromContents
from gslib.utils.hashing_helper import CalculateB64EncodedMd5FromContents


class TestRsyncFuncs(GsUtilUnitTestCase):

  def test_compute_needed_file_checksums(self):
    """Tests that we compute all/only needed file checksums."""
    size = 4
    logger = logging.getLogger()
    tmpdir = self.CreateTempDir()
    file_url_str = 'file://%s' % os.path.join(tmpdir, 'obj1')
    self.CreateTempFile(tmpdir=tmpdir, file_name='obj1', contents=b'obj1')
    cloud_url_str = 'gs://whatever'
    with open(os.path.join(tmpdir, 'obj1'), 'rb') as fp:
      crc32c = CalculateB64EncodedCrc32cFromContents(fp)
      fp.seek(0)
      md5 = CalculateB64EncodedMd5FromContents(fp)

    # Test case where source is a file and dest has CRC32C.
    (src_crc32c, src_md5, dst_crc32c,
     dst_md5) = _ComputeNeededFileChecksums(logger, file_url_str, size, _NA,
                                            _NA, cloud_url_str, size, crc32c,
                                            _NA)
    self.assertEqual(crc32c, src_crc32c)
    self.assertEqual(_NA, src_md5)
    self.assertEqual(crc32c, dst_crc32c)
    self.assertEqual(_NA, dst_md5)

    # Test case where source is a file and dest has MD5 but not CRC32C.
    (src_crc32c, src_md5, dst_crc32c,
     dst_md5) = _ComputeNeededFileChecksums(logger, file_url_str, size, _NA,
                                            _NA, cloud_url_str, size, _NA, md5)
    self.assertEqual(_NA, src_crc32c)
    self.assertEqual(md5, src_md5)
    self.assertEqual(_NA, dst_crc32c)
    self.assertEqual(md5, dst_md5)

    # Test case where dest is a file and src has CRC32C.
    (src_crc32c, src_md5, dst_crc32c,
     dst_md5) = _ComputeNeededFileChecksums(logger, cloud_url_str, size, crc32c,
                                            _NA, file_url_str, size, _NA, _NA)
    self.assertEqual(crc32c, dst_crc32c)
    self.assertEqual(_NA, src_md5)
    self.assertEqual(crc32c, src_crc32c)
    self.assertEqual(_NA, src_md5)

    # Test case where dest is a file and src has MD5 but not CRC32C.
    (src_crc32c, src_md5, dst_crc32c,
     dst_md5) = _ComputeNeededFileChecksums(logger, cloud_url_str, size, _NA,
                                            md5, file_url_str, size, _NA, _NA)
    self.assertEqual(_NA, dst_crc32c)
    self.assertEqual(md5, src_md5)
    self.assertEqual(_NA, src_crc32c)
    self.assertEqual(md5, src_md5)

  def test_encode_decode_url(self):
    from gslib.commands.rsync import _EncodeUrl, _DecodeUrl

    # 1. Simple ASCII url
    url = 'gs://my-bucket/path/to/object.txt'
    enc = _EncodeUrl(url)
    self.assertEqual(url, _DecodeUrl(enc))

    # 2. Spaces and special characters
    url = 'gs://my-bucket/path to/object name.txt'
    enc = _EncodeUrl(url)
    self.assertEqual(url, _DecodeUrl(enc))

    # 3. Unicode characters
    url = 'gs://my-bucket/path/è_中文_object.txt'
    enc = _EncodeUrl(url)
    self.assertEqual(url, _DecodeUrl(enc))

  def test_batch_sort(self):
    from gslib.commands.rsync import _BatchSort
    import tempfile

    lines = [
        'gs://bucket/object_c 10 123456789 - - - - - -\n',
        'gs://bucket/object_a 20 123456789 - - - - - -\n',
        'gs://bucket/object_b 30 123456789 - - - - - -\n',
    ]

    with tempfile.NamedTemporaryFile(mode='w+', delete=False) as out_file:
      filename = out_file.name
      try:
        # Sort lines
        _BatchSort(iter(lines), out_file)
        out_file.seek(0)
        sorted_lines = out_file.readlines()

        expected_sorted = [
            'gs://bucket/object_a 20 123456789 - - - - - -\n',
            'gs://bucket/object_b 30 123456789 - - - - - -\n',
            'gs://bucket/object_c 10 123456789 - - - - - -\n',
        ]
        self.assertEqual(sorted_lines, expected_sorted)
      finally:
        os.unlink(filename)

  @mock.patch('os.path.islink')
  def test_diff_to_apply_arg_checker(self, mock_islink):
    from gslib.commands.rsync import _DiffToApplyArgChecker
    from gslib.utils.rsync_util import RsyncDiffToApply, DiffAction

    class MockCommand(object):
      def __init__(self, exclude_symlinks):
        self.exclude_symlinks = exclude_symlinks
        self.logger = mock.Mock()

    # 1. Action is REMOVE -> should always return True
    cmd = MockCommand(exclude_symlinks=True)
    diff = RsyncDiffToApply(
        src_url_str=None,
        dst_url_str='file:///tmp/dest',
        src_posix_attrs=None,
        diff_action=DiffAction.REMOVE,
        copy_size=None
    )
    self.assertTrue(_DiffToApplyArgChecker(cmd, diff))

    # 2. Exclude symlinks is False -> should return True
    cmd = MockCommand(exclude_symlinks=False)
    diff = RsyncDiffToApply(
        src_url_str='file:///tmp/src',
        dst_url_str='gs://bucket/dest',
        src_posix_attrs=None,
        diff_action=DiffAction.COPY,
        copy_size=10
    )
    self.assertTrue(_DiffToApplyArgChecker(cmd, diff))

    # 3. Exclude symlinks is True, and file is a symlink -> should return False
    cmd = MockCommand(exclude_symlinks=True)
    diff = RsyncDiffToApply(
        src_url_str='file:///tmp/src-link',
        dst_url_str='gs://bucket/dest',
        src_posix_attrs=None,
        diff_action=DiffAction.COPY,
        copy_size=10
    )
    mock_islink.return_value = True
    self.assertFalse(_DiffToApplyArgChecker(cmd, diff))
    self.assertTrue(cmd.logger.info.called)

    # 4. Exclude symlinks is True, and file is NOT a symlink -> should return True
    cmd = MockCommand(exclude_symlinks=True)
    diff = RsyncDiffToApply(
        src_url_str='file:///tmp/src-file',
        dst_url_str='gs://bucket/dest',
        src_posix_attrs=None,
        diff_action=DiffAction.COPY,
        copy_size=10
    )
    mock_islink.return_value = False
    self.assertTrue(_DiffToApplyArgChecker(cmd, diff))

