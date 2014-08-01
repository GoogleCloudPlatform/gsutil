# -*- coding: utf-8 -*-
#
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
"""Integration tests for cp command."""

from __future__ import absolute_import

import base64
import binascii
import datetime
import logging
import os
import pkgutil
import random
import re
import string

import boto
from boto import storage_uri

from gslib.copy_helper import GetTrackerFilePath
from gslib.copy_helper import TrackerFileType
from gslib.cs_api_map import ApiSelector
from gslib.hashing_helper import CalculateMd5FromContents
from gslib.storage_url import StorageUrlFromString
from gslib.tests.mock_logging_handler import MockLoggingHandler
import gslib.tests.testcase as testcase
from gslib.tests.testcase.base import NotParallelizable
from gslib.tests.testcase.integration_testcase import SkipForS3
from gslib.tests.util import HAS_S3_CREDS
from gslib.tests.util import ObjectToURI as suri
from gslib.tests.util import PerformsFileToObjectUpload
from gslib.tests.util import SetBotoConfigForTest
from gslib.tests.util import unittest
from gslib.util import IS_WINDOWS
from gslib.util import ONE_KB
from gslib.util import Retry
from gslib.util import START_CALLBACK_PER_BYTES
from gslib.util import UTF8


class TestCp(testcase.GsUtilIntegrationTestCase):
  """Integration tests for cp command."""

  # For tests that artificially halt, we need to ensure at least one callback
  # occurs.
  halt_size = START_CALLBACK_PER_BYTES * 2

  def _get_test_file(self, name):
    contents = pkgutil.get_data('gslib', 'tests/test_data/%s' % name)
    return self.CreateTempFile(file_name=name, contents=contents)

  @PerformsFileToObjectUpload
  def test_noclobber(self):
    key_uri = self.CreateObject(contents='foo')
    fpath = self.CreateTempFile(contents='bar')
    stderr = self.RunGsUtil(['cp', '-n', fpath, suri(key_uri)],
                            return_stderr=True)
    self.assertIn('Skipping existing item: %s' % suri(key_uri), stderr)
    self.assertEqual(key_uri.get_contents_as_string(), 'foo')
    stderr = self.RunGsUtil(['cp', '-n', suri(key_uri), fpath],
                            return_stderr=True)
    with open(fpath, 'r') as f:
      self.assertIn('Skipping existing item: %s' % suri(f), stderr)
      self.assertEqual(f.read(), 'bar')

  def test_object_and_prefix_same_name(self):
    # TODO: Make this a unit test when unit_testcase supports returning
    # stderr.
    bucket_uri = self.CreateBucket()
    object_uri = self.CreateObject(bucket_uri=bucket_uri, object_name='foo',
                                   contents='foo')
    self.CreateObject(bucket_uri=bucket_uri,
                      object_name='foo/bar', contents='bar')
    fpath = self.CreateTempFile()
    self.RunGsUtil(['cp', suri(object_uri), fpath], return_stderr=True)
    with open(fpath, 'r') as f:
      self.assertEqual(f.read(), 'foo')

  def test_dest_bucket_not_exist(self):
    fpath = self.CreateTempFile(contents='foo')
    invalid_bucket_uri = (
        '%s://%s' % (self.default_provider, self.nonexistent_bucket_name))
    stderr = self.RunGsUtil(['cp', fpath, invalid_bucket_uri],
                            expected_status=1, return_stderr=True)
    self.assertIn('does not exist.', stderr)

  def test_copy_in_cloud_noclobber(self):
    bucket1_uri = self.CreateBucket()
    bucket2_uri = self.CreateBucket()
    key_uri = self.CreateObject(bucket_uri=bucket1_uri, contents='foo')
    stderr = self.RunGsUtil(['cp', suri(key_uri), suri(bucket2_uri)],
                            return_stderr=True)
    self.assertEqual(stderr.count('Copying'), 1)
    stderr = self.RunGsUtil(['cp', '-n', suri(key_uri), suri(bucket2_uri)],
                            return_stderr=True)
    self.assertIn('Skipping existing item: %s' %
                  suri(bucket2_uri, key_uri.object_name), stderr)

  @PerformsFileToObjectUpload
  def test_streaming(self):
    bucket_uri = self.CreateBucket()
    stderr = self.RunGsUtil(['cp', '-', '%s' % suri(bucket_uri, 'foo')],
                            stdin='bar', return_stderr=True)
    self.assertIn('Copying from <STDIN>', stderr)
    key_uri = bucket_uri.clone_replace_name('foo')
    self.assertEqual(key_uri.get_contents_as_string(), 'bar')

  def test_streaming_multiple_arguments(self):
    bucket_uri = self.CreateBucket()
    stderr = self.RunGsUtil(['cp', '-', '-', suri(bucket_uri)],
                            stdin='bar', return_stderr=True, expected_status=1)
    self.assertIn('Multiple URL strings are not supported with streaming',
                  stderr)

  # TODO: Implement a way to test both with and without using magic file.

  @PerformsFileToObjectUpload
  def test_detect_content_type(self):
    """Tests local detection of content type."""
    bucket_uri = self.CreateBucket()
    dsturi = suri(bucket_uri, 'foo')

    self.RunGsUtil(['cp', self._get_test_file('test.mp3'), dsturi])

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      if IS_WINDOWS:
        self.assertTrue(
            re.search(r'Content-Type:\s+audio/x-mpg', stdout) or
            re.search(r'Content-Type:\s+audio/mpeg', stdout))
      else:
        self.assertRegexpMatches(stdout, r'Content-Type:\s+audio/mpeg')
    _Check1()

    self.RunGsUtil(['cp', self._get_test_file('test.gif'), dsturi])

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check2():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      self.assertRegexpMatches(stdout, r'Content-Type:\s+image/gif')
    _Check2()

  def test_content_type_override_default(self):
    """Tests overriding content type with the default value."""
    bucket_uri = self.CreateBucket()
    dsturi = suri(bucket_uri, 'foo')

    self.RunGsUtil(['-h', 'Content-Type:', 'cp',
                    self._get_test_file('test.mp3'), dsturi])

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      self.assertRegexpMatches(stdout,
                               r'Content-Type:\s+application/octet-stream')
    _Check1()

    self.RunGsUtil(['-h', 'Content-Type:', 'cp',
                    self._get_test_file('test.gif'), dsturi])

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check2():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      self.assertRegexpMatches(stdout,
                               r'Content-Type:\s+application/octet-stream')
    _Check2()

  def test_content_type_override(self):
    """Tests overriding content type with a value."""
    bucket_uri = self.CreateBucket()
    dsturi = suri(bucket_uri, 'foo')

    self.RunGsUtil(['-h', 'Content-Type:text/plain', 'cp',
                    self._get_test_file('test.mp3'), dsturi])

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      self.assertRegexpMatches(stdout, r'Content-Type:\s+text/plain')
    _Check1()

    self.RunGsUtil(['-h', 'Content-Type:text/plain', 'cp',
                    self._get_test_file('test.gif'), dsturi])

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check2():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      self.assertRegexpMatches(stdout, r'Content-Type:\s+text/plain')
    _Check2()

  @unittest.skipIf(IS_WINDOWS, 'magicfile is not available on Windows.')
  @PerformsFileToObjectUpload
  def test_magicfile_override(self):
    """Tests content type override with magicfile value."""
    bucket_uri = self.CreateBucket()
    dsturi = suri(bucket_uri, 'foo')
    fpath = self.CreateTempFile(contents='foo/bar\n')
    self.RunGsUtil(['cp', fpath, dsturi])

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      use_magicfile = boto.config.getbool('GSUtil', 'use_magicfile', False)
      content_type = ('text/plain' if use_magicfile
                      else 'application/octet-stream')
      self.assertRegexpMatches(stdout, r'Content-Type:\s+%s' % content_type)
    _Check1()

  @PerformsFileToObjectUpload
  def test_content_type_mismatches(self):
    """Tests overriding content type when it does not match the file type."""
    bucket_uri = self.CreateBucket()
    dsturi = suri(bucket_uri, 'foo')
    fpath = self.CreateTempFile(contents='foo/bar\n')

    self.RunGsUtil(['-h', 'Content-Type:image/gif', 'cp',
                    self._get_test_file('test.mp3'), dsturi])

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      self.assertRegexpMatches(stdout, r'Content-Type:\s+image/gif')
    _Check1()

    self.RunGsUtil(['-h', 'Content-Type:image/gif', 'cp',
                    self._get_test_file('test.gif'), dsturi])

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check2():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      self.assertRegexpMatches(stdout, r'Content-Type:\s+image/gif')
    _Check2()

    self.RunGsUtil(['-h', 'Content-Type:image/gif', 'cp', fpath, dsturi])

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check3():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      self.assertRegexpMatches(stdout, r'Content-Type:\s+image/gif')
    _Check3()

  @PerformsFileToObjectUpload
  def test_content_type_header_case_insensitive(self):
    """Tests that content type header is treated with case insensitivity."""
    bucket_uri = self.CreateBucket()
    dsturi = suri(bucket_uri, 'foo')
    fpath = self._get_test_file('test.gif')

    self.RunGsUtil(['-h', 'content-Type:text/plain', 'cp',
                    fpath, dsturi])

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      self.assertRegexpMatches(stdout, r'Content-Type:\s+text/plain')
      self.assertNotRegexpMatches(stdout, r'image/gif')
    _Check1()

    self.RunGsUtil(['-h', 'CONTENT-TYPE:image/gif',
                    '-h', 'content-type:image/gif',
                    'cp', fpath, dsturi])

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check2():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      self.assertRegexpMatches(stdout, r'Content-Type:\s+image/gif')
      self.assertNotRegexpMatches(stdout, r'image/gif,\s*image/gif')
    _Check2()

  @PerformsFileToObjectUpload
  def test_other_headers(self):
    """Tests that non-content-type headers are applied successfully on copy."""
    bucket_uri = self.CreateBucket()
    dsturi = suri(bucket_uri, 'foo')
    fpath = self._get_test_file('test.gif')

    self.RunGsUtil(['-h', 'Cache-Control:public,max-age=12',
                    '-h', 'x-%s-meta-1:abcd' % self.provider_custom_meta, 'cp',
                    fpath, dsturi])

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      self.assertRegexpMatches(stdout, r'Cache-Control\s*:\s*public,max-age=12')
      self.assertRegexpMatches(stdout, r'Metadata:\s*1:\s*abcd')
    _Check1()

  @PerformsFileToObjectUpload
  def test_versioning(self):
    """Tests copy with versioning."""
    bucket_uri = self.CreateVersionedBucket()
    k1_uri = self.CreateObject(bucket_uri=bucket_uri, contents='data2')
    k2_uri = self.CreateObject(bucket_uri=bucket_uri, contents='data1')
    g1 = k2_uri.generation or k2_uri.version_id
    self.RunGsUtil(['cp', suri(k1_uri), suri(k2_uri)])
    k2_uri = bucket_uri.clone_replace_name(k2_uri.object_name)
    k2_uri = bucket_uri.clone_replace_key(k2_uri.get_key())
    g2 = k2_uri.generation or k2_uri.version_id
    k2_uri.set_contents_from_string('data3')
    g3 = k2_uri.generation or k2_uri.version_id

    fpath = self.CreateTempFile()
    # Check to make sure current version is data3.
    self.RunGsUtil(['cp', k2_uri.versionless_uri, fpath])
    with open(fpath, 'r') as f:
      self.assertEqual(f.read(), 'data3')

    # Check contents of all three versions
    self.RunGsUtil(['cp', '%s#%s' % (k2_uri.versionless_uri, g1), fpath])
    with open(fpath, 'r') as f:
      self.assertEqual(f.read(), 'data1')
    self.RunGsUtil(['cp', '%s#%s' % (k2_uri.versionless_uri, g2), fpath])
    with open(fpath, 'r') as f:
      self.assertEqual(f.read(), 'data2')
    self.RunGsUtil(['cp', '%s#%s' % (k2_uri.versionless_uri, g3), fpath])
    with open(fpath, 'r') as f:
      self.assertEqual(f.read(), 'data3')

    # Copy first version to current and verify.
    self.RunGsUtil(['cp', '%s#%s' % (k2_uri.versionless_uri, g1),
                    k2_uri.versionless_uri])
    self.RunGsUtil(['cp', k2_uri.versionless_uri, fpath])
    with open(fpath, 'r') as f:
      self.assertEqual(f.read(), 'data1')

    # Attempt to specify a version-specific URI for destination.
    stderr = self.RunGsUtil(['cp', fpath, k2_uri.uri], return_stderr=True,
                            expected_status=1)
    self.assertIn('cannot be the destination for gsutil cp', stderr)

  @SkipForS3('S3 lists versioned objects in reverse timestamp order.')
  def test_recursive_copying_versioned_bucket(self):
    """Tests that cp -R with versioned buckets copies all versions in order."""
    bucket1_uri = self.CreateVersionedBucket()
    bucket2_uri = self.CreateVersionedBucket()

    # Write two versions of an object to the bucket1.
    self.CreateObject(bucket_uri=bucket1_uri, object_name='k', contents='data0')
    self.CreateObject(bucket_uri=bucket1_uri, object_name='k',
                      contents='longer_data1')

    self.AssertNObjectsInBucket(bucket1_uri, 2, versioned=True)
    self.AssertNObjectsInBucket(bucket2_uri, 0, versioned=True)

    # Recursively copy to second versioned bucket.
    self.RunGsUtil(['cp', '-R', suri(bucket1_uri, '*'), suri(bucket2_uri)])

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check2():
      """Validates the results of the cp -R."""
      listing1 = self.RunGsUtil(['ls', '-la', suri(bucket1_uri)],
                                return_stdout=True).split('\n')
      listing2 = self.RunGsUtil(['ls', '-la', suri(bucket2_uri)],
                                return_stdout=True).split('\n')
      # 2 lines of listing output, 1 summary line, 1 empty line from \n split.
      self.assertEquals(len(listing1), 4)
      self.assertEquals(len(listing2), 4)

      # First object in each bucket should match in size and version-less name.
      size1, _, uri_str1, _ = listing1[0].split()
      self.assertEquals(size1, str(len('data0')))
      self.assertEquals(storage_uri(uri_str1).object_name, 'k')
      size2, _, uri_str2, _ = listing2[0].split()
      self.assertEquals(size2, str(len('data0')))
      self.assertEquals(storage_uri(uri_str2).object_name, 'k')

      # Similarly for second object in each bucket.
      size1, _, uri_str1, _ = listing1[1].split()
      self.assertEquals(size1, str(len('longer_data1')))
      self.assertEquals(storage_uri(uri_str1).object_name, 'k')
      size2, _, uri_str2, _ = listing2[1].split()
      self.assertEquals(size2, str(len('longer_data1')))
      self.assertEquals(storage_uri(uri_str2).object_name, 'k')
    _Check2()

  @PerformsFileToObjectUpload
  @SkipForS3('Preconditions not supported for S3.')
  def test_cp_v_generation_match(self):
    """Tests that cp -v option handles the if-generation-match header."""
    bucket_uri = self.CreateVersionedBucket()
    k1_uri = self.CreateObject(bucket_uri=bucket_uri, contents='data1')
    g1 = k1_uri.generation

    tmpdir = self.CreateTempDir()
    fpath1 = self.CreateTempFile(tmpdir=tmpdir, contents='data2')

    gen_match_header = 'x-goog-if-generation-match:%s' % g1
    # First copy should succeed.
    self.RunGsUtil(['-h', gen_match_header, 'cp', fpath1, suri(k1_uri)])

    # Second copy should fail the precondition.
    stderr = self.RunGsUtil(['-h', gen_match_header, 'cp', fpath1,
                             suri(k1_uri)],
                            return_stderr=True, expected_status=1)

    self.assertIn('PreconditionException', stderr)

    # Specifiying a generation with -n should fail before the request hits the
    # server.
    stderr = self.RunGsUtil(['-h', gen_match_header, 'cp', '-n', fpath1,
                             suri(k1_uri)],
                            return_stderr=True, expected_status=1)

    self.assertIn('ArgumentException', stderr)
    self.assertIn('Specifying x-goog-if-generation-match is not supported '
                  'with cp -n', stderr)

  @PerformsFileToObjectUpload
  def test_cp_nv(self):
    """Tests that cp -nv works when skipping existing file."""
    bucket_uri = self.CreateVersionedBucket()
    k1_uri = self.CreateObject(bucket_uri=bucket_uri, contents='data1')

    tmpdir = self.CreateTempDir()
    fpath1 = self.CreateTempFile(tmpdir=tmpdir, contents='data2')

    # First copy should succeed.
    self.RunGsUtil(['cp', '-nv', fpath1, suri(k1_uri)])

    # Second copy should skip copying.
    stderr = self.RunGsUtil(['cp', '-nv', fpath1, suri(k1_uri)],
                            return_stderr=True)
    self.assertIn('Skipping existing item:', stderr)

  @PerformsFileToObjectUpload
  @SkipForS3('S3 lists versioned objects in reverse timestamp order.')
  def test_cp_v_option(self):
    """"Tests that cp -v returns the created object's version-specific URI."""
    bucket_uri = self.CreateVersionedBucket()
    k1_uri = self.CreateObject(bucket_uri=bucket_uri, contents='data1')
    k2_uri = self.CreateObject(bucket_uri=bucket_uri, contents='data2')

    # Case 1: Upload file to object using one-shot PUT.
    tmpdir = self.CreateTempDir()
    fpath1 = self.CreateTempFile(tmpdir=tmpdir, contents='data1')
    self._run_cp_minus_v_test('-v', fpath1, k2_uri.uri)

    # Case 2: Upload file to object using resumable upload.
    size_threshold = ONE_KB
    boto_config_for_test = ('GSUtil', 'resumable_threshold',
                            str(size_threshold))
    with SetBotoConfigForTest([boto_config_for_test]):
      file_as_string = os.urandom(size_threshold)
      tmpdir = self.CreateTempDir()
      fpath1 = self.CreateTempFile(tmpdir=tmpdir, contents=file_as_string)
      self._run_cp_minus_v_test('-v', fpath1, k2_uri.uri)

    # Case 3: Upload stream to object.
    self._run_cp_minus_v_test('-v', '-', k2_uri.uri)

    # Case 4: Download object to file. For this case we just expect output of
    # gsutil cp -v to be the URI of the file.
    tmpdir = self.CreateTempDir()
    fpath1 = self.CreateTempFile(tmpdir=tmpdir)
    dst_uri = storage_uri(fpath1)
    stderr = self.RunGsUtil(['cp', '-v', suri(k1_uri), suri(dst_uri)],
                            return_stderr=True)
    self.assertIn('Created: %s' % dst_uri.uri, stderr.split('\n')[-2])

    # Case 5: Daisy-chain from object to object.
    self._run_cp_minus_v_test('-Dv', k1_uri.uri, k2_uri.uri)

    # Case 6: Copy object to object in-the-cloud.
    self._run_cp_minus_v_test('-v', k1_uri.uri, k2_uri.uri)

  def _run_cp_minus_v_test(self, opt, src_str, dst_str):
    """Runs cp -v with the options and validates the results."""
    stderr = self.RunGsUtil(['cp', opt, src_str, dst_str], return_stderr=True)
    match = re.search(r'Created: (.*)\n', stderr)
    self.assertIsNotNone(match)
    created_uri = match.group(1)

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-a', dst_str], return_stdout=True)
      lines = stdout.split('\n')
      # Final (most recent) object should match the "Created:" URI. This is
      # in second-to-last line (last line is '\n').
      self.assertGreater(len(lines), 2)
      self.assertEqual(created_uri, lines[-2])
    _Check1()

  @PerformsFileToObjectUpload
  def test_stdin_args(self):
    """Tests cp with the -I option."""
    tmpdir = self.CreateTempDir()
    fpath1 = self.CreateTempFile(tmpdir=tmpdir, contents='data1')
    fpath2 = self.CreateTempFile(tmpdir=tmpdir, contents='data2')
    bucket_uri = self.CreateBucket()
    self.RunGsUtil(['cp', '-I', suri(bucket_uri)],
                   stdin='\n'.join((fpath1, fpath2)))

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', suri(bucket_uri)], return_stdout=True)
      self.assertIn(os.path.basename(fpath1), stdout)
      self.assertIn(os.path.basename(fpath2), stdout)
      self.assertNumLines(stdout, 2)
    _Check1()

  def test_cross_storage_class_cloud_cp(self):
    bucket1_uri = self.CreateBucket(storage_class='STANDARD')
    bucket2_uri = self.CreateBucket(
        storage_class='DURABLE_REDUCED_AVAILABILITY')
    key_uri = self.CreateObject(bucket_uri=bucket1_uri, contents='foo')
    # Server now allows copy-in-the-cloud across storage classes.
    self.RunGsUtil(['cp', suri(key_uri), suri(bucket2_uri)])

  @unittest.skipUnless(HAS_S3_CREDS, 'Test requires both S3 and GS credentials')
  def test_cross_provider_cp(self):
    s3_bucket = self.CreateBucket(provider='s3')
    gs_bucket = self.CreateBucket(provider='gs')
    s3_key = self.CreateObject(bucket_uri=s3_bucket, contents='foo')
    gs_key = self.CreateObject(bucket_uri=gs_bucket, contents='bar')
    self.RunGsUtil(['cp', suri(s3_key), suri(gs_bucket)])
    self.RunGsUtil(['cp', suri(gs_key), suri(s3_bucket)])

  @unittest.skipUnless(HAS_S3_CREDS, 'Test requires both S3 and GS credentials')
  @unittest.skip('This test performs a large copy but remains here for '
                 'debugging purposes.')
  def test_cross_provider_large_cp(self):
    s3_bucket = self.CreateBucket(provider='s3')
    gs_bucket = self.CreateBucket(provider='gs')
    s3_key = self.CreateObject(bucket_uri=s3_bucket, contents='f'*1024*1024)
    gs_key = self.CreateObject(bucket_uri=gs_bucket, contents='b'*1024*1024)
    self.RunGsUtil(['cp', suri(s3_key), suri(gs_bucket)])
    self.RunGsUtil(['cp', suri(gs_key), suri(s3_bucket)])
    with SetBotoConfigForTest([
        ('GSUtil', 'resumable_threshold', str(ONE_KB)),
        ('GSUtil', 'json_resumable_chunk_size', str(ONE_KB * 256))]):
      # Ensure copy also works across json upload chunk boundaries.
      self.RunGsUtil(['cp', suri(s3_key), suri(gs_bucket)])

  @unittest.skip('This test is slow due to creating many objects, '
                 'but remains here for debugging purposes.')
  def test_daisy_chain_cp_file_sizes(self):
    """Ensure daisy chain cp works with a wide of file sizes."""
    bucket_uri = self.CreateBucket()
    bucket2_uri = self.CreateBucket()
    exponent_cap = 22  # Up to 2MB in size.
    for i in range(exponent_cap):
      one_byte_smaller = 2**i - 1
      normal = 2**i
      one_byte_larger = 2**i + 1
      self.CreateObject(bucket_uri=bucket_uri, contents='a'*one_byte_smaller)
      self.CreateObject(bucket_uri=bucket_uri, contents='b'*normal)
      self.CreateObject(bucket_uri=bucket_uri, contents='c'*one_byte_larger)

    self.AssertNObjectsInBucket(bucket_uri, exponent_cap*3)
    self.RunGsUtil(['-m', 'cp', '-D', suri(bucket_uri, '**'),
                    suri(bucket2_uri)])

    self.AssertNObjectsInBucket(bucket2_uri, exponent_cap*3)

  def test_daisy_chain_cp(self):
    """Tests cp with the -D option."""
    bucket1_uri = self.CreateBucket(storage_class='STANDARD')
    bucket2_uri = self.CreateBucket(
        storage_class='DURABLE_REDUCED_AVAILABILITY')
    key_uri = self.CreateObject(bucket_uri=bucket1_uri, contents='foo')
    # Set some headers on source object so we can verify that headers are
    # presereved by daisy-chain copy.
    self.RunGsUtil(['setmeta', '-h', 'Cache-Control:public,max-age=12',
                    '-h', 'Content-Type:image/gif',
                    '-h', 'x-%s-meta-1:abcd' % self.provider_custom_meta,
                    suri(key_uri)])
    # Set public-read (non-default) ACL so we can verify that cp -D -p works.
    self.RunGsUtil(['acl', 'set', 'public-read', suri(key_uri)])
    acl_json = self.RunGsUtil(['acl', 'get', suri(key_uri)], return_stdout=True)
    # Perform daisy-chain copy and verify that source object headers and ACL
    # were preserved. Also specify -n option to test that gsutil correctly
    # removes the x-goog-if-generation-match:0 header that was set at uploading
    # time when updating the ACL.
    stderr = self.RunGsUtil(['cp', '-Dpn', suri(key_uri), suri(bucket2_uri)],
                            return_stderr=True)
    self.assertNotIn('Copy-in-the-cloud disallowed', stderr)

    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check():
      uri = suri(bucket2_uri, key_uri.object_name)
      stdout = self.RunGsUtil(['ls', '-L', uri], return_stdout=True)
      self.assertRegexpMatches(stdout, r'Cache-Control:\s+public,max-age=12')
      self.assertRegexpMatches(stdout, r'Content-Type:\s+image/gif')
      self.assertRegexpMatches(stdout, r'Metadata:\s+1:\s+abcd')
      new_acl_json = self.RunGsUtil(['acl', 'get', uri], return_stdout=True)
      self.assertEqual(acl_json, new_acl_json)
    _Check()

  def test_canned_acl_cp(self):
    """Tests copying with a canned ACL."""
    bucket1_uri = self.CreateBucket()
    bucket2_uri = self.CreateBucket()
    key_uri = self.CreateObject(bucket_uri=bucket1_uri, contents='foo')
    self.RunGsUtil(['cp', '-a', 'public-read', suri(key_uri),
                    suri(bucket2_uri)])
    # Set public-read on the original key after the copy so we can compare
    # the ACLs.
    self.RunGsUtil(['acl', 'set', 'public-read', suri(key_uri)])
    public_read_acl = self.RunGsUtil(['acl', 'get', suri(key_uri)],
                                     return_stdout=True)

    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check():
      uri = suri(bucket2_uri, key_uri.object_name)
      new_acl_json = self.RunGsUtil(['acl', 'get', uri], return_stdout=True)
      self.assertEqual(public_read_acl, new_acl_json)
    _Check()

  @PerformsFileToObjectUpload
  def test_canned_acl_upload(self):
    """Tests uploading a file with a canned ACL."""
    bucket1_uri = self.CreateBucket()
    key_uri = self.CreateObject(bucket_uri=bucket1_uri, contents='foo')
    # Set public-read on the object so we can compare the ACLs.
    self.RunGsUtil(['acl', 'set', 'public-read', suri(key_uri)])
    public_read_acl = self.RunGsUtil(['acl', 'get', suri(key_uri)],
                                     return_stdout=True)

    file_name = 'bar'
    fpath = self.CreateTempFile(file_name=file_name, contents='foo')
    self.RunGsUtil(['cp', '-a', 'public-read', fpath, suri(bucket1_uri)])
    new_acl_json = self.RunGsUtil(['acl', 'get', suri(bucket1_uri, file_name)],
                                  return_stdout=True)
    self.assertEqual(public_read_acl, new_acl_json)

    resumable_size = ONE_KB
    boto_config_for_test = ('GSUtil', 'resumable_threshold',
                            str(resumable_size))
    with SetBotoConfigForTest([boto_config_for_test]):
      resumable_file_name = 'resumable_bar'
      resumable_contents = os.urandom(resumable_size)
      resumable_fpath = self.CreateTempFile(
          file_name=resumable_file_name, contents=resumable_contents)
      self.RunGsUtil(['cp', '-a', 'public-read', resumable_fpath,
                      suri(bucket1_uri)])
      new_resumable_acl_json = self.RunGsUtil(
          ['acl', 'get', suri(bucket1_uri, resumable_file_name)],
          return_stdout=True)
      self.assertEqual(public_read_acl, new_resumable_acl_json)

  def test_cp_key_to_local_stream(self):
    bucket_uri = self.CreateBucket()
    contents = 'foo'
    key_uri = self.CreateObject(bucket_uri=bucket_uri, contents=contents)
    stdout = self.RunGsUtil(['cp', suri(key_uri), '-'], return_stdout=True)
    self.assertIn(contents, stdout)

  def test_cp_local_file_to_local_stream(self):
    contents = 'content'
    fpath = self.CreateTempFile(contents=contents)
    stdout = self.RunGsUtil(['cp', fpath, '-'], return_stdout=True)
    self.assertIn(contents, stdout)

  @PerformsFileToObjectUpload
  def test_cp_zero_byte_file(self):
    dst_bucket_uri = self.CreateBucket()
    src_dir = self.CreateTempDir()
    fpath = os.path.join(src_dir, 'zero_byte')
    with open(fpath, 'w') as unused_out_file:
      pass  # Write a zero byte file
    self.RunGsUtil(['cp', fpath, suri(dst_bucket_uri)])

    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', suri(dst_bucket_uri)], return_stdout=True)
      self.assertIn(os.path.basename(fpath), stdout)
    _Check1()

    download_path = os.path.join(src_dir, 'zero_byte_download')
    self.RunGsUtil(['cp', suri(dst_bucket_uri, 'zero_byte'), download_path])
    self.assertTrue(os.stat(download_path))

  def test_copy_bucket_to_bucket(self):
    """Tests that recursively copying from bucket to bucket.

    This should produce identically named objects (and not, in particular,
    destination objects named by the version-specific URI from source objects).
    """
    src_bucket_uri = self.CreateVersionedBucket()
    dst_bucket_uri = self.CreateVersionedBucket()
    self.CreateObject(bucket_uri=src_bucket_uri, object_name='obj0',
                      contents='abc')
    self.CreateObject(bucket_uri=src_bucket_uri, object_name='obj1',
                      contents='def')

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _CopyAndCheck():
      self.RunGsUtil(['cp', '-R', suri(src_bucket_uri),
                      suri(dst_bucket_uri)])
      stdout = self.RunGsUtil(['ls', '-R', dst_bucket_uri.uri],
                              return_stdout=True)
      self.assertIn('%s%s/obj0\n' % (dst_bucket_uri,
                                     src_bucket_uri.bucket_name), stdout)
      self.assertIn('%s%s/obj1\n' % (dst_bucket_uri,
                                     src_bucket_uri.bucket_name), stdout)
    _CopyAndCheck()

  def test_copy_bucket_to_dir(self):
    """Tests recursively copying from bucket to a directory.

    This should produce identically named objects (and not, in particular,
    destination objects named by the version- specific URI from source objects).
    """
    src_bucket_uri = self.CreateBucket()
    dst_dir = self.CreateTempDir()
    self.CreateObject(bucket_uri=src_bucket_uri, object_name='obj0',
                      contents='abc')
    self.CreateObject(bucket_uri=src_bucket_uri, object_name='obj1',
                      contents='def')

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _CopyAndCheck():
      """Copies the bucket recursively and validates the results."""
      self.RunGsUtil(['cp', '-R', suri(src_bucket_uri), dst_dir])
      dir_list = []
      for dirname, _, filenames in os.walk(dst_dir):
        for filename in filenames:
          dir_list.append(os.path.join(dirname, filename))
      dir_list = sorted(dir_list)
      self.assertEqual(len(dir_list), 2)
      self.assertEqual(os.path.join(dst_dir, src_bucket_uri.bucket_name,
                                    'obj0'), dir_list[0])
      self.assertEqual(os.path.join(dst_dir, src_bucket_uri.bucket_name,
                                    'obj1'), dir_list[1])
    _CopyAndCheck()

  def test_recursive_download_with_leftover_dir_placeholder(self):
    """Tests that we correctly handle leftover dir placeholders."""
    src_bucket_uri = self.CreateBucket()
    dst_dir = self.CreateTempDir()
    self.CreateObject(bucket_uri=src_bucket_uri, object_name='obj0',
                      contents='abc')
    self.CreateObject(bucket_uri=src_bucket_uri, object_name='obj1',
                      contents='def')

    # Create a placeholder like what can be left over by web GUI tools.
    key_uri = src_bucket_uri.clone_replace_name('/')
    key_uri.set_contents_from_string('')
    self.AssertNObjectsInBucket(src_bucket_uri, 3)

    stderr = self.RunGsUtil(['cp', '-R', suri(src_bucket_uri), dst_dir],
                            return_stderr=True)
    self.assertIn('Skipping cloud sub-directory placeholder object', stderr)
    dir_list = []
    for dirname, _, filenames in os.walk(dst_dir):
      for filename in filenames:
        dir_list.append(os.path.join(dirname, filename))
    dir_list = sorted(dir_list)
    self.assertEqual(len(dir_list), 2)
    self.assertEqual(os.path.join(dst_dir, src_bucket_uri.bucket_name,
                                  'obj0'), dir_list[0])
    self.assertEqual(os.path.join(dst_dir, src_bucket_uri.bucket_name,
                                  'obj1'), dir_list[1])

  def test_copy_quiet(self):
    bucket_uri = self.CreateBucket()
    key_uri = self.CreateObject(bucket_uri=bucket_uri, contents='foo')
    stderr = self.RunGsUtil(['-q', 'cp', suri(key_uri),
                             suri(bucket_uri.clone_replace_name('o2'))],
                            return_stderr=True)
    self.assertEqual(stderr.count('Copying '), 0)

  def test_cp_md5_match(self):
    """Tests that the uploaded object has the expected MD5.

    Note that while this does perform a file to object upload, MD5's are
    not supported for composite objects so we don't use the decorator in this
    case.
    """
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents='bar')
    with open(fpath, 'r') as f_in:
      file_md5 = base64.encodestring(binascii.unhexlify(
          CalculateMd5FromContents(f_in))).rstrip('\n')
    self.RunGsUtil(['cp', fpath, suri(bucket_uri)])

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-L', suri(bucket_uri)],
                              return_stdout=True)
      self.assertRegexpMatches(stdout,
                               r'Hash\s+\(md5\):\s+%s' % re.escape(file_md5))
    _Check1()

  @unittest.skipIf(IS_WINDOWS,
                   'Unicode handling on Windows requires mods to site-packages')
  @PerformsFileToObjectUpload
  def test_cp_manifest_upload_unicode(self):
    return self._ManifestUpload('foo-unicöde', 'bar-unicöde',
                                'manifest-unicöde')

  @PerformsFileToObjectUpload
  def test_cp_manifest_upload(self):
    """Tests uploading with a mnifest file."""
    return self._ManifestUpload('foo', 'bar', 'manifest')

  def _ManifestUpload(self, file_name, object_name, manifest_name):
    """Tests uploading with a manifest file."""
    bucket_uri = self.CreateBucket()
    dsturi = suri(bucket_uri, object_name)

    fpath = self.CreateTempFile(file_name=file_name, contents='bar')
    logpath = self.CreateTempFile(file_name=manifest_name, contents='')
    # Ensure the file is empty.
    open(logpath, 'w').close()
    self.RunGsUtil(['cp', '-L', logpath, fpath, dsturi])
    with open(logpath, 'r') as f:
      lines = f.readlines()
    self.assertEqual(len(lines), 2)

    expected_headers = ['Source', 'Destination', 'Start', 'End', 'Md5',
                        'UploadId', 'Source Size', 'Bytes Transferred',
                        'Result', 'Description']
    self.assertEqual(expected_headers, lines[0].strip().split(','))
    results = lines[1].strip().split(',')
    self.assertEqual(results[0][:7], 'file://')  # source
    self.assertEqual(results[1][:5], '%s://' %
                     self.default_provider)      # destination
    date_format = '%Y-%m-%dT%H:%M:%S.%fZ'
    start_date = datetime.datetime.strptime(results[2], date_format)
    end_date = datetime.datetime.strptime(results[3], date_format)
    self.assertEqual(end_date > start_date, True)
    if self.RunGsUtil == testcase.GsUtilIntegrationTestCase.RunGsUtil:
      # Check that we didn't do automatic parallel uploads - compose doesn't
      # calculate the MD5 hash. Since RunGsUtil is overriden in
      # TestCpParallelUploads to force parallel uploads, we can check which
      # method was used.
      self.assertEqual(results[4], 'rL0Y20zC+Fzt72VPzMSk2A==')  # md5
    self.assertEqual(int(results[6]), 3)  # Source Size
    self.assertEqual(int(results[7]), 3)  # Bytes Transferred
    self.assertEqual(results[8], 'OK')  # Result

  @PerformsFileToObjectUpload
  def test_cp_manifest_download(self):
    """Tests downloading with a manifest file."""
    key_uri = self.CreateObject(contents='foo')
    fpath = self.CreateTempFile(contents='')
    logpath = self.CreateTempFile(contents='')
    # Ensure the file is empty.
    open(logpath, 'w').close()
    self.RunGsUtil(['cp', '-L', logpath, suri(key_uri), fpath],
                   return_stdout=True)
    with open(logpath, 'r') as f:
      lines = f.readlines()
    self.assertEqual(len(lines), 2)

    expected_headers = ['Source', 'Destination', 'Start', 'End', 'Md5',
                        'UploadId', 'Source Size', 'Bytes Transferred',
                        'Result', 'Description']
    self.assertEqual(expected_headers, lines[0].strip().split(','))
    results = lines[1].strip().split(',')
    self.assertEqual(results[0][:5], '%s://' %
                     self.default_provider)      # source
    self.assertEqual(results[1][:7], 'file://')  # destination
    date_format = '%Y-%m-%dT%H:%M:%S.%fZ'
    start_date = datetime.datetime.strptime(results[2], date_format)
    end_date = datetime.datetime.strptime(results[3], date_format)
    self.assertEqual(end_date > start_date, True)
    self.assertEqual(results[4], 'rL0Y20zC+Fzt72VPzMSk2A==')  # md5
    self.assertEqual(int(results[6]), 3)  # Source Size
    # Bytes transferred might be more than 3 if the file was gzipped, since
    # the minimum gzip header is 10 bytes.
    self.assertGreaterEqual(int(results[7]), 3)  # Bytes Transferred
    self.assertEqual(results[8], 'OK')  # Result

  @PerformsFileToObjectUpload
  def test_copy_unicode_non_ascii_filename(self):
    key_uri = self.CreateObject(contents='foo')
    # Make file large enough to cause a resumable upload (which hashes filename
    # to construct tracker filename).
    fpath = self.CreateTempFile(file_name=u'Аудиоархив',
                                contents='x' * 3 * 1024 * 1024)
    fpath_bytes = fpath.encode(UTF8)
    stderr = self.RunGsUtil(['cp', fpath_bytes, suri(key_uri)],
                            return_stderr=True)
    self.assertIn('Copying file:', stderr)

  # Note: We originally one time implemented a test
  # (test_copy_invalid_unicode_filename) that invalid unicode filenames were
  # skipped, but it turns out os.walk() on MacOS doesn't have problems with
  # such files (so, failed that test). Given that, we decided to remove the
  # test.

  def test_gzip_upload_and_download(self):
    bucket_uri = self.CreateBucket()
    contents = 'x' * 10000
    tmpdir = self.CreateTempDir()
    self.CreateTempFile(file_name='test.html', tmpdir=tmpdir, contents=contents)
    self.CreateTempFile(file_name='test.js', tmpdir=tmpdir, contents=contents)
    self.CreateTempFile(file_name='test.txt', tmpdir=tmpdir, contents=contents)
    # Test that copying specifying only 2 of the 3 prefixes gzips the correct
    # files, and test that including whitespace in the extension list works.
    self.RunGsUtil(['cp', '-z', 'js, html',
                    os.path.join(tmpdir, 'test.*'), suri(bucket_uri)])
    self.AssertNObjectsInBucket(bucket_uri, 3)
    uri1 = suri(bucket_uri, 'test.html')
    uri2 = suri(bucket_uri, 'test.js')
    uri3 = suri(bucket_uri, 'test.txt')
    stdout = self.RunGsUtil(['stat', uri1], return_stdout=True)
    self.assertRegexpMatches(stdout, r'Content-Encoding:\s+gzip')
    stdout = self.RunGsUtil(['stat', uri2], return_stdout=True)
    self.assertRegexpMatches(stdout, r'Content-Encoding:\s+gzip')
    stdout = self.RunGsUtil(['stat', uri3], return_stdout=True)
    self.assertNotRegexpMatches(stdout, r'Content-Encoding:\s+gzip')
    fpath4 = self.CreateTempFile()
    for uri in (uri1, uri2, uri3):
      self.RunGsUtil(['cp', uri, suri(fpath4)])
      with open(fpath4, 'r') as f:
        self.assertEqual(f.read(), contents)

  def test_upload_with_subdir_and_unexpanded_wildcard(self):
    fpath1 = self.CreateTempFile(file_name=('tmp', 'x', 'y', 'z'))
    bucket_uri = self.CreateBucket()
    wildcard_uri = '%s*' % fpath1[:-5]
    stderr = self.RunGsUtil(['cp', '-R', wildcard_uri, suri(bucket_uri)],
                            return_stderr=True)
    self.assertIn('Copying file:', stderr)

  def test_cp_object_ending_with_slash(self):
    """Tests that cp works with object names ending with slash."""
    tmpdir = self.CreateTempDir()
    bucket_uri = self.CreateBucket()
    self.CreateObject(bucket_uri=bucket_uri,
                      object_name='abc/',
                      contents='dir')
    self.CreateObject(bucket_uri=bucket_uri,
                      object_name='abc/def',
                      contents='def')
    self.RunGsUtil(['cp', '-R', suri(bucket_uri), tmpdir])
    # Check that files in the subdir got copied even though subdir object
    # download was skipped.
    with open(os.path.join(tmpdir, bucket_uri.bucket_name, 'abc', 'def')) as f:
      self.assertEquals('def', '\n'.join(f.readlines()))

  def test_cp_without_read_access(self):
    """Tests that cp fails without read access to the object."""
    # TODO: With 401's triggering retries in apitools, this test will take
    # a long time.  Ideally, make apitools accept a num_retries config for this
    # until we stop retrying the 401's.
    bucket_uri = self.CreateBucket()
    object_uri = self.CreateObject(bucket_uri=bucket_uri, contents='foo')

    # Use @Retry as hedge against bucket listing eventual consistency.
    self.AssertNObjectsInBucket(bucket_uri, 1)

    with self.SetAnonymousBotoCreds():
      stderr = self.RunGsUtil(['cp', suri(object_uri), 'foo'],
                              return_stderr=True, expected_status=1)
      self.assertIn('AccessDenied', stderr)

  @unittest.skipIf(IS_WINDOWS, 'os.symlink() is not available on Windows.')
  def test_cp_minus_e(self):
    fpath_dir = self.CreateTempDir()
    fpath1 = self.CreateTempFile(tmpdir=fpath_dir)
    fpath2 = os.path.join(fpath_dir, 'cp_minus_e')
    bucket_uri = self.CreateBucket()
    os.symlink(fpath1, fpath2)
    stderr = self.RunGsUtil(
        ['cp', '-e', '%s%s*' % (fpath_dir, os.path.sep),
         suri(bucket_uri, 'files')],
        return_stderr=True)
    self.assertIn('Copying file', stderr)
    self.assertIn('Skipping symbolic link file', stderr)

  def test_cp_multithreaded_wildcard(self):
    """Tests that cp -m works with a wildcard."""
    num_test_files = 5
    tmp_dir = self.CreateTempDir(test_files=num_test_files)
    bucket_uri = self.CreateBucket()
    wildcard_uri = '%s%s*' % (tmp_dir, os.sep)
    self.RunGsUtil(['-m', 'cp', wildcard_uri, suri(bucket_uri)])
    self.AssertNObjectsInBucket(bucket_uri, num_test_files)

  def test_cp_upload_respects_no_hashes(self):
    # TODO: Make this a unit test when unit_testcase supports returning
    # stderr.
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents='abcd')
    with SetBotoConfigForTest([('GSUtil', 'check_hashes', 'never')]):
      stderr = self.RunGsUtil(['cp', fpath, suri(bucket_uri)],
                              return_stderr=True)
    self.assertIn('Found no hashes to validate object upload', stderr)

  @SkipForS3('No resumable upload support for S3.')
  def test_cp_resumable_upload_break(self):
    """Tests that an upload can be resumed after a connection break."""
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents='a' * self.halt_size)
    boto_config_for_test = ('GSUtil', 'resumable_threshold', str(ONE_KB))
    with SetBotoConfigForTest([boto_config_for_test]):
      stderr = self.RunGsUtil(['cp', '--haltatbyte', '5', fpath,
                               suri(bucket_uri)],
                              expected_status=1, return_stderr=True)
      self.assertIn('Artifically halting upload', stderr)
      stderr = self.RunGsUtil(['cp', fpath, suri(bucket_uri)],
                              return_stderr=True)
      self.assertIn('Resuming upload', stderr)

  @SkipForS3('No resumable upload support for S3.')
  def test_cp_resumable_upload(self):
    """Tests that a basic resumable upload completes successfully."""
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents='a' * self.halt_size)
    boto_config_for_test = ('GSUtil', 'resumable_threshold', str(ONE_KB))
    with SetBotoConfigForTest([boto_config_for_test]):
      self.RunGsUtil(['cp', fpath, suri(bucket_uri)])

  @SkipForS3('No resumable upload support for S3.')
  def test_resumable_upload_break_leaves_tracker(self):
    """Tests that a tracker file is created with a resumable upload."""
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(file_name='foo',
                                contents='a' * self.halt_size)
    boto_config_for_test = ('GSUtil', 'resumable_threshold', str(ONE_KB))
    with SetBotoConfigForTest([boto_config_for_test]):
      tracker_filename = GetTrackerFilePath(
          StorageUrlFromString(suri(bucket_uri, 'foo')),
          TrackerFileType.UPLOAD, self.test_api)
      try:
        stderr = self.RunGsUtil(['cp', '--haltatbyte', '5', fpath,
                                 suri(bucket_uri, 'foo')],
                                expected_status=1, return_stderr=True)
        self.assertIn('Artifically halting upload', stderr)
        self.assertTrue(os.path.exists(tracker_filename),
                        'Tracker file %s not present.' % tracker_filename)
      finally:
        if os.path.exists(tracker_filename):
          os.unlink(tracker_filename)

  @SkipForS3('No resumable upload support for S3.')
  def test_cp_resumable_upload_break_file_size_change(self):
    """Tests a resumable upload where the uploaded file changes size.

    This should fail when we read the tracker data.
    """
    bucket_uri = self.CreateBucket()
    tmp_dir = self.CreateTempDir()
    fpath = self.CreateTempFile(file_name='foo', tmpdir=tmp_dir,
                                contents='a' * self.halt_size)
    boto_config_for_test = ('GSUtil', 'resumable_threshold', str(ONE_KB))
    with SetBotoConfigForTest([boto_config_for_test]):
      stderr = self.RunGsUtil(['cp', '--haltatbyte', '5', fpath,
                               suri(bucket_uri)],
                              expected_status=1, return_stderr=True)
      self.assertIn('Artifically halting upload', stderr)
      fpath = self.CreateTempFile(file_name='foo', tmpdir=tmp_dir,
                                  contents='a' * self.halt_size * 2)
      stderr = self.RunGsUtil(['cp', fpath, suri(bucket_uri)],
                              expected_status=1, return_stderr=True)
      self.assertIn('ResumableUploadAbortException', stderr)

  @SkipForS3('No resumable upload support for S3.')
  def test_cp_resumable_upload_break_file_content_change(self):
    """Tests a resumable upload where the uploaded file changes content."""
    if self.test_api == ApiSelector.XML:
      return unittest.skip(
          'XML doesn\'t make separate HTTP calls at fixed-size boundaries for '
          'resumable uploads, so we can\'t guarantee that the server saves a '
          'specific part of the upload.')
    bucket_uri = self.CreateBucket()
    tmp_dir = self.CreateTempDir()
    fpath = self.CreateTempFile(file_name='foo', tmpdir=tmp_dir,
                                contents='a' * ONE_KB * 512)
    resumable_threshold_for_test = (
        'GSUtil', 'resumable_threshold', str(ONE_KB))
    resumable_chunk_size_for_test = (
        'GSUtil', 'json_resumable_chunk_size', str(ONE_KB * 256))
    with SetBotoConfigForTest([resumable_threshold_for_test,
                               resumable_chunk_size_for_test]):
      stderr = self.RunGsUtil(['cp', '--haltatbyte', str(ONE_KB * 384), fpath,
                               suri(bucket_uri)],
                              expected_status=1, return_stderr=True)
      self.assertIn('Artifically halting upload', stderr)
      fpath = self.CreateTempFile(file_name='foo', tmpdir=tmp_dir,
                                  contents='b' * ONE_KB * 512)
      stderr = self.RunGsUtil(['cp', fpath, suri(bucket_uri)],
                              expected_status=1, return_stderr=True)
      self.assertIn('doesn\'t match cloud-supplied digest', stderr)

  @SkipForS3('No resumable upload support for S3.')
  def test_cp_resumable_upload_break_file_smaller_size(self):
    """Tests a resumable upload where the uploaded file changes content.

    This should fail hash validation.
    """
    bucket_uri = self.CreateBucket()
    tmp_dir = self.CreateTempDir()
    fpath = self.CreateTempFile(file_name='foo', tmpdir=tmp_dir,
                                contents='a' * ONE_KB * 512)
    resumable_threshold_for_test = (
        'GSUtil', 'resumable_threshold', str(ONE_KB))
    resumable_chunk_size_for_test = (
        'GSUtil', 'json_resumable_chunk_size', str(ONE_KB * 256))
    with SetBotoConfigForTest([resumable_threshold_for_test,
                               resumable_chunk_size_for_test]):
      stderr = self.RunGsUtil(['cp', '--haltatbyte', str(ONE_KB * 384), fpath,
                               suri(bucket_uri)],
                              expected_status=1, return_stderr=True)
      self.assertIn('Artifically halting upload', stderr)
      fpath = self.CreateTempFile(file_name='foo', tmpdir=tmp_dir,
                                  contents='a' * ONE_KB)
      stderr = self.RunGsUtil(['cp', fpath, suri(bucket_uri)],
                              expected_status=1, return_stderr=True)
      self.assertIn('ResumableUploadAbortException', stderr)

  # This temporarily changes the tracker directory to unwritable which
  # interferes with any parallel running tests that use the tracker directory.
  @NotParallelizable
  @SkipForS3('No resumable upload support for S3.')
  @unittest.skipIf(IS_WINDOWS, 'chmod on dir unsupported on Windows.')
  @PerformsFileToObjectUpload
  def test_cp_unwritable_tracker_file(self):
    """Tests a resumable upload with an unwritable tracker file."""
    bucket_uri = self.CreateBucket()
    tracker_filename = GetTrackerFilePath(
        StorageUrlFromString(suri(bucket_uri, 'foo')),
        TrackerFileType.UPLOAD, self.test_api)
    tracker_dir = os.path.dirname(tracker_filename)
    fpath = self.CreateTempFile(file_name='foo', contents='a' * ONE_KB)
    boto_config_for_test = ('GSUtil', 'resumable_threshold', str(ONE_KB))
    save_mod = os.stat(tracker_dir).st_mode

    try:
      os.chmod(tracker_dir, 0)
      with SetBotoConfigForTest([boto_config_for_test]):
        stderr = self.RunGsUtil(['cp', fpath, suri(bucket_uri)],
                                expected_status=1, return_stderr=True)
        self.assertIn('Couldn\'t write tracker file', stderr)
    finally:
      os.chmod(tracker_dir, save_mod)
      if os.path.exists(tracker_filename):
        os.unlink(tracker_filename)

  def test_cp_resumable_download_break(self):
    """Tests that a download can be resumed after a connection break."""
    bucket_uri = self.CreateBucket()
    object_uri = self.CreateObject(bucket_uri=bucket_uri, object_name='foo',
                                   contents='a' * self.halt_size)
    fpath = self.CreateTempFile()
    boto_config_for_test = ('GSUtil', 'resumable_threshold', str(ONE_KB))
    with SetBotoConfigForTest([boto_config_for_test]):
      stderr = self.RunGsUtil(['cp', '--haltatbyte', '5', suri(object_uri),
                               fpath], expected_status=1, return_stderr=True)
      self.assertIn('Artifically halting download.', stderr)
      tracker_filename = GetTrackerFilePath(
          StorageUrlFromString(fpath), TrackerFileType.DOWNLOAD, self.test_api)
      self.assertTrue(os.path.isfile(tracker_filename))
      stderr = self.RunGsUtil(['cp', suri(object_uri), fpath],
                              return_stderr=True)
      self.assertIn('Resuming download', stderr)

  def test_cp_resumable_download_etag_differs(self):
    """Tests that download restarts the file when the source object changes.

    This causes the etag not to match.
    """
    bucket_uri = self.CreateBucket()
    object_uri = self.CreateObject(bucket_uri=bucket_uri, object_name='foo',
                                   contents='a' * self.halt_size)
    fpath = self.CreateTempFile()
    boto_config_for_test = ('GSUtil', 'resumable_threshold', str(ONE_KB))
    with SetBotoConfigForTest([boto_config_for_test]):
      # This will create a tracker file with an ETag.
      stderr = self.RunGsUtil(['cp', '--haltatbyte', '5', suri(object_uri),
                               fpath], expected_status=1, return_stderr=True)
      self.assertIn('Artifically halting download.', stderr)
      # Create a new object with different contents - it should have a
      # different ETag since the content has changed.
      object_uri = self.CreateObject(bucket_uri=bucket_uri, object_name='foo',
                                     contents='b' * self.halt_size)
      stderr = self.RunGsUtil(['cp', suri(object_uri), fpath],
                              return_stderr=True)
      self.assertNotIn('Resuming download', stderr)

  def test_cp_resumable_download_file_larger(self):
    """Tests download deletes the tracker file when existing file is larger."""
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile()
    object_uri = self.CreateObject(bucket_uri=bucket_uri, object_name='foo',
                                   contents='a' * self.halt_size)
    boto_config_for_test = ('GSUtil', 'resumable_threshold', str(ONE_KB))
    with SetBotoConfigForTest([boto_config_for_test]):
      stderr = self.RunGsUtil(['cp', '--haltatbyte', '5', suri(object_uri),
                               fpath],
                              expected_status=1, return_stderr=True)
      self.assertIn('Artifically halting download.', stderr)
      with open(fpath, 'w') as larger_file:
        for _ in range(self.halt_size * 2):
          larger_file.write('a')
      stderr = self.RunGsUtil(['cp', suri(object_uri), fpath],
                              expected_status=1, return_stderr=True)
      self.assertNotIn('Resuming download', stderr)
      self.assertIn('is larger', stderr)
      self.assertIn('Deleting tracker file', stderr)

  def test_cp_resumable_download_content_differs(self):
    """Tests that we do not re-download when tracker file matches existing file.

    We only compare size, not contents, so re-download should not occur even
    though the contents are technically different. However, hash validation on
    the file should still occur and we will delete the file then because
    the hashes differ.
    """
    bucket_uri = self.CreateBucket()
    tmp_dir = self.CreateTempDir()
    fpath = self.CreateTempFile(tmpdir=tmp_dir, contents='abcd' * ONE_KB)
    object_uri = self.CreateObject(bucket_uri=bucket_uri, object_name='foo',
                                   contents='efgh' * ONE_KB)
    stdout = self.RunGsUtil(['ls', '-L', suri(object_uri)], return_stdout=True)
    etag_match = re.search(r'\s*ETag:\s*(.*)', stdout)
    self.assertIsNotNone(etag_match, 'Could not get object ETag')
    self.assertEqual(len(etag_match.groups()), 1,
                     'Did not match expected single ETag')
    etag = etag_match.group(1)

    tracker_filename = GetTrackerFilePath(
        StorageUrlFromString(fpath), TrackerFileType.DOWNLOAD, self.test_api)
    try:
      with open(tracker_filename, 'w') as tracker_fp:
        tracker_fp.write(etag)
      boto_config_for_test = ('GSUtil', 'resumable_threshold', str(ONE_KB))
      with SetBotoConfigForTest([boto_config_for_test]):
        stderr = self.RunGsUtil(['cp', suri(object_uri), fpath],
                                return_stderr=True, expected_status=1)
        self.assertIn('Download already complete for file', stderr)
        self.assertIn('doesn\'t match cloud-supplied digest', stderr)
        # File and tracker file should be deleted.
        self.assertFalse(os.path.isfile(fpath))
        self.assertFalse(os.path.isfile(tracker_filename))
    finally:
      if os.path.exists(tracker_filename):
        os.unlink(tracker_filename)

  def test_cp_resumable_download_content_matches(self):
    """Tests download no-ops when tracker file matches existing file."""
    bucket_uri = self.CreateBucket()
    tmp_dir = self.CreateTempDir()
    matching_contents = 'abcd' * ONE_KB
    fpath = self.CreateTempFile(tmpdir=tmp_dir, contents=matching_contents)
    object_uri = self.CreateObject(bucket_uri=bucket_uri, object_name='foo',
                                   contents=matching_contents)
    stdout = self.RunGsUtil(['ls', '-L', suri(object_uri)], return_stdout=True)
    etag_match = re.search(r'\s*ETag:\s*(.*)', stdout)
    self.assertIsNotNone(etag_match, 'Could not get object ETag')
    self.assertEqual(len(etag_match.groups()), 1,
                     'Did not match expected single ETag')
    etag = etag_match.group(1)
    tracker_filename = GetTrackerFilePath(
        StorageUrlFromString(fpath), TrackerFileType.DOWNLOAD, self.test_api)
    with open(tracker_filename, 'w') as tracker_fp:
      tracker_fp.write(etag)
    try:
      boto_config_for_test = ('GSUtil', 'resumable_threshold', str(ONE_KB))
      with SetBotoConfigForTest([boto_config_for_test]):
        stderr = self.RunGsUtil(['cp', suri(object_uri), fpath],
                                return_stderr=True)
        self.assertIn('Download already complete for file', stderr)
        # Tracker file should be removed after successful hash validation.
        self.assertFalse(os.path.isfile(tracker_filename))
    finally:
      if os.path.exists(tracker_filename):
        os.unlink(tracker_filename)

  def test_cp_resumable_download_tracker_file_not_matches(self):
    """Tests that download overwrites when tracker file etag does not match."""
    bucket_uri = self.CreateBucket()
    tmp_dir = self.CreateTempDir()
    fpath = self.CreateTempFile(tmpdir=tmp_dir, contents='abcd' * ONE_KB)
    object_uri = self.CreateObject(bucket_uri=bucket_uri, object_name='foo',
                                   contents='efgh' * ONE_KB)
    stdout = self.RunGsUtil(['ls', '-L', suri(object_uri)], return_stdout=True)
    etag_match = re.search(r'\s*ETag:\s*(.*)', stdout)
    self.assertIsNotNone(etag_match, 'Could not get object ETag')
    self.assertEqual(len(etag_match.groups()), 1,
                     'Did not match regex for exactly one object ETag')
    etag = etag_match.group(1)
    etag += 'nonmatching'
    tracker_filename = GetTrackerFilePath(
        StorageUrlFromString(fpath), TrackerFileType.DOWNLOAD, self.test_api)
    with open(tracker_filename, 'w') as tracker_fp:
      tracker_fp.write(etag)
    try:
      boto_config_for_test = ('GSUtil', 'resumable_threshold', str(ONE_KB))
      with SetBotoConfigForTest([boto_config_for_test]):
        stderr = self.RunGsUtil(['cp', suri(object_uri), fpath],
                                return_stderr=True)
        self.assertNotIn('Resuming download', stderr)
        # Ensure the file was overwritten.
        with open(fpath, 'r') as in_fp:
          contents = in_fp.read()
          self.assertEqual(contents, 'efgh' * ONE_KB,
                           'File not overwritten when it should have been '
                           'due to a non-matching tracker file.')
        self.assertFalse(os.path.isfile(tracker_filename))
    finally:
      if os.path.exists(tracker_filename):
        os.unlink(tracker_filename)

  def test_cp_resumable_download_gzip(self):
    """Tests that download can be resumed successfully with a gzipped file."""
    # Generate some reasonably incompressible data.  This compresses to a bit
    # around 128K in practice, but we assert specifically below that it is
    # larger than self.halt_size to guarantee that we can halt the download
    # partway through.
    object_uri = self.CreateObject()
    random.seed(0)
    contents = str([random.choice(string.ascii_letters)
                    for _ in xrange(ONE_KB * 128)])
    random.seed()  # Reset the seed for any other tests.
    fpath1 = self.CreateTempFile(file_name='unzipped.txt', contents=contents)
    self.RunGsUtil(['cp', '-z', 'txt', suri(fpath1), suri(object_uri)])

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _GetObjectSize():
      stdout = self.RunGsUtil(['du', suri(object_uri)], return_stdout=True)
      size_match = re.search(r'(\d+)\s+.*', stdout)
      self.assertIsNotNone(size_match, 'Could not get object size')
      self.assertEqual(len(size_match.groups()), 1,
                       'Did not match regex for exactly one object size.')
      return long(size_match.group(1))

    object_size = _GetObjectSize()
    self.assertGreaterEqual(object_size, self.halt_size,
                            'Compresed object size was not large enough to '
                            'allow for a halted download, so the test results '
                            'would be invalid. Please increase the compressed '
                            'object size in the test.')
    fpath2 = self.CreateTempFile()
    boto_config_for_test = ('GSUtil', 'resumable_threshold', str(ONE_KB))
    with SetBotoConfigForTest([boto_config_for_test]):
      stderr = self.RunGsUtil(['cp', '--haltatbyte', '5', suri(object_uri),
                               suri(fpath2)],
                              return_stderr=True, expected_status=1)
      self.assertIn('Artifically halting download.', stderr)
      tracker_filename = GetTrackerFilePath(
          StorageUrlFromString(fpath2), TrackerFileType.DOWNLOAD, self.test_api)
      self.assertTrue(os.path.isfile(tracker_filename))
      self.assertIn('Downloading to temp gzip filename', stderr)
      # We should have a temporary gzipped file, a tracker file, and no
      # final file yet.
      self.assertTrue(os.path.isfile('%s_.gztmp' % fpath2))
      stderr = self.RunGsUtil(['cp', suri(object_uri), suri(fpath2)],
                              return_stderr=True)
      self.assertIn('Resuming download', stderr)
      with open(fpath2, 'r') as f:
        self.assertEqual(f.read(), contents, 'File contents did not match.')
      self.assertFalse(os.path.isfile(tracker_filename))
      self.assertFalse(os.path.isfile('%s_.gztmp' % fpath2))

  def test_cp_minus_c(self):
    bucket_uri = self.CreateBucket()
    object_uri = self.CreateObject(bucket_uri=bucket_uri, object_name='foo',
                                   contents='foo')
    self.RunGsUtil(
        ['cp', '-c', suri(bucket_uri) + '/foo2', suri(object_uri),
         suri(bucket_uri) + '/dir/'],
        expected_status=1)
    self.RunGsUtil(['stat', '%s/dir/foo' % suri(bucket_uri)])


class TestCpUnitTests(testcase.GsUtilUnitTestCase):
  """Unit tests for gsutil cp."""

  def testDownloadWithNoHashAvailable(self):
    """Tests a download with no valid server-supplied hash."""
    # S3 should have a special message for non-MD5 etags.
    bucket_uri = self.CreateBucket(provider='s3')
    object_uri = self.CreateObject(bucket_uri=bucket_uri, contents='foo')
    object_uri.get_key().etag = '12345'  # Not an MD5
    dst_dir = self.CreateTempDir()

    log_handler = MockLoggingHandler()
    logging.getLogger('cp').addHandler(log_handler)

    self.RunCommand('cp', [suri(object_uri), dst_dir])
    warning_messages = log_handler.messages['warning']
    self.assertEquals(2, len(warning_messages))
    self.assertRegexpMatches(
        warning_messages[0],
        r'Non-MD5 etag \(12345\) present for key .*, '
        r'data integrity checks are not possible')
    self.assertRegexpMatches(warning_messages[1], 'Integrity cannot be assured')


