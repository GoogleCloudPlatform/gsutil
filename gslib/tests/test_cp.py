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

import datetime
import os
import pkgutil
import re

import boto
from boto import storage_uri
from boto.storage_uri import BucketStorageUri

from gslib.commands.cp import FilterExistingComponents
from gslib.commands.cp import MakeGsUri
from gslib.commands.cp import ObjectFromTracker
from gslib.commands.cp import PerformResumableUploadIfAppliesArgs
from gslib.storage_uri_builder import StorageUriBuilder
import gslib.tests.testcase as testcase
from gslib.tests.util import HAS_S3_CREDS
from gslib.tests.util import ObjectToURI as suri
from gslib.tests.util import PerformsFileToObjectUpload
from gslib.tests.util import unittest
from gslib.util import CreateLock
from gslib.util import IS_WINDOWS
from gslib.util import Retry
from gslib.util import TWO_MB
from gslib.util import UTF8


class TestCp(testcase.GsUtilIntegrationTestCase):
  """Integration tests for cp command."""

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
    # TODO: Make this a a unit test when unit_testcase supports returning
    # stderr.
    bucket_uri = self.CreateBucket()
    object_uri = self.CreateObject(bucket_uri=bucket_uri, object_name='foo',
                                   contents='foo')
    self.CreateObject(bucket_uri=bucket_uri,
                      object_name='foo/bar', contents='bar')
    fpath = self.CreateTempFile()
    stderr = self.RunGsUtil(['cp', suri(object_uri), fpath],
                            return_stderr=True)
    self.assertIn('Omitting prefix "%s/"' % suri(bucket_uri, 'foo'), stderr)

  def test_dest_bucket_not_exist(self):
    fpath = self.CreateTempFile(contents='foo')
    invalid_bucket_uri = 'gs://nonexistentbucket-asf801rj3r9as90mfnnkjxpo02/'
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

  def _run_streaming_test(self, provider):
    bucket_uri = self.CreateBucket(provider=provider)
    stderr = self.RunGsUtil(['cp', '-', '%s' % suri(bucket_uri, 'foo')],
                            stdin='bar', return_stderr=True)
    self.assertIn('Copying from <STDIN>', stderr)
    key_uri = bucket_uri.clone_replace_name('foo')
    self.assertEqual(key_uri.get_contents_as_string(), 'bar')

  @unittest.skipUnless(HAS_S3_CREDS, 'Test requires S3 credentials.')
  def test_streaming_s3(self):
    self._run_streaming_test('s3')

  @PerformsFileToObjectUpload
  def test_streaming_gs(self):
    self._run_streaming_test('gs')

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
                    '-h', 'x-goog-meta-1:abcd', 'cp',
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
    g1 = k2_uri.generation
    self.RunGsUtil(['cp', suri(k1_uri), suri(k2_uri)])
    k2_uri = bucket_uri.clone_replace_name(k2_uri.object_name)
    k2_uri = bucket_uri.clone_replace_key(k2_uri.get_key())
    g2 = k2_uri.generation
    k2_uri.set_contents_from_string('data3')
    g3 = k2_uri.generation

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

  def test_recursive_copying_versioned_bucket(self):
    """Tests that cp -R with versioned buckets copies all versions in order."""
    bucket1_uri = self.CreateVersionedBucket()
    bucket2_uri = self.CreateVersionedBucket()

    # Write two versions of an object to the bucket1.
    self.CreateObject(bucket_uri=bucket1_uri, object_name='k', contents='data0')
    self.CreateObject(bucket_uri=bucket1_uri, object_name='k',
                      contents='longer_data1')

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      listing1 = self.RunGsUtil(['ls', '-la', suri(bucket1_uri)],
                                return_stdout=True).split('\n')
      listing2 = self.RunGsUtil(['ls', '-la', suri(bucket2_uri)],
                                return_stdout=True).split('\n')
      self.assertEquals(len(listing1), 4)
      self.assertEquals(len(listing2), 1)  # Single empty line from \n split.
    _Check1()

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
  def test_cp_v_generation_match(self):
    """Tests that cp -v option handles the if-generation-match header."""
    bucket_uri = self.CreateVersionedBucket()
    k1_uri = self.CreateObject(bucket_uri=bucket_uri, contents='data1')
    g1 = k1_uri.generation

    tmpdir = self.CreateTempDir()
    fpath1 = self.CreateTempFile(tmpdir=tmpdir, contents='data2')

    gen_match_header = 'x-goog-if-generation-match:%s' % g1
    # First copy should succeed
    self.RunGsUtil(['-h', gen_match_header, 'cp', fpath1, suri(k1_uri)])

    # Second copy should fail the precondition.
    stderr = self.RunGsUtil(['-h', gen_match_header, 'cp', fpath1,
                             suri(k1_uri)],
                            return_stderr=True, expected_status=1)

    self.assertIn('PreconditionException', stderr)

    # Specifiying a generation with -n should fail before the request hits the
    # server
    stderr = self.RunGsUtil(['-h', gen_match_header, 'cp', '-n', fpath1,
                             suri(k1_uri)],
                            return_stderr=True, expected_status=1)

    self.assertIn('ArgumentException', stderr)
    self.assertIn('Specifying x-goog-if-generation-match is not supported '
                  'with cp -n', stderr)

  @PerformsFileToObjectUpload
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
    size_threshold = boto.config.get('GSUtil', 'resumable_threshold', TWO_MB)
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
                    '-h', 'x-goog-meta-1:abcd', suri(key_uri)])
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

  def test_copy_quiet(self):
    bucket_uri = self.CreateBucket()
    key_uri = self.CreateObject(bucket_uri=bucket_uri, contents='foo')
    stderr = self.RunGsUtil(['-q', 'cp', suri(key_uri),
                             suri(bucket_uri.clone_replace_name('o2'))],
                            return_stderr=True)
    self.assertEqual(stderr.count('Copying '), 0)

  @PerformsFileToObjectUpload
  def test_cp_manifest_upload(self):
    """Tests uploading with a manifest file."""
    bucket_uri = self.CreateBucket()
    dsturi = suri(bucket_uri, 'foo')

    fpath = self.CreateTempFile(contents='bar')
    logpath = self.CreateTempFile(contents='')
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
    self.assertEqual(results[1][:5], 'gs://')  # destination
    date_format = '%Y-%m-%dT%H:%M:%S.%fZ'
    start_date = datetime.datetime.strptime(results[2], date_format)
    end_date = datetime.datetime.strptime(results[3], date_format)
    self.assertEqual(end_date > start_date, True)
    if self.RunGsUtil == testcase.GsUtilIntegrationTestCase.RunGsUtil:
      # Check that we didn't do automatic parallel uploads - compose doesn't
      # calculate the MD5 hash. Since RunGsUtil is overriden in
      # TestCpParallelUploads to force parallel uploads, we can check which
      # method was used.
      self.assertEqual(results[4], '37b51d194a7513e45b56f6524f2d51f2')  # md5
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
    self.assertEqual(results[0][:5], 'gs://')  # source
    self.assertEqual(results[1][:7], 'file://')  # destination
    date_format = '%Y-%m-%dT%H:%M:%S.%fZ'
    start_date = datetime.datetime.strptime(results[2], date_format)
    end_date = datetime.datetime.strptime(results[3], date_format)
    self.assertEqual(end_date > start_date, True)
    # TODO: fix this when CRC32C's are added to the manifest.
    # self.assertEqual(results[4], '37b51d194a7513e45b56f6524f2d51f2')  # md5
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

  def test_gzip_upload_and_download(self):
    key_uri = self.CreateObject()
    contents = 'x' * 10000
    fpath1 = self.CreateTempFile(file_name='test.html', contents=contents)
    self.RunGsUtil(['cp', '-z', 'html', suri(fpath1), suri(key_uri)])
    fpath2 = self.CreateTempFile()
    self.RunGsUtil(['cp', suri(key_uri), suri(fpath2)])
    with open(fpath2, 'r') as f:
      self.assertEqual(f.read(), contents)

  def test_upload_with_subdir_and_unexpanded_wildcard(self):
    fpath1 = self.CreateTempFile(file_name=('tmp', 'x', 'y', 'z'))
    bucket_uri = self.CreateBucket()
    wildcard_uri = '%s*' % fpath1[:-5]
    stderr = self.RunGsUtil(['cp', '-R', wildcard_uri, suri(bucket_uri)],
                            return_stderr=True)
    self.assertIn('Copying file:', stderr)

  def test_cp_without_read_access(self):
    """Tests that cp fails without read access to the object."""
    bucket_uri = self.CreateBucket()
    object_uri = self.CreateObject(bucket_uri=bucket_uri, contents='foo')
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', suri(bucket_uri)], return_stdout=True)
      lines = stdout.split('\n')
      self.assertEqual(2, len(lines))
    _Check1()

    with self.SetAnonymousBotoCreds():
      stderr = self.RunGsUtil(['cp', suri(object_uri), 'foo'],
                              return_stderr=True, expected_status=1)
      self.assertIn('Access denied', stderr)

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
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', suri(bucket_uri)], return_stdout=True)
      lines = stdout.split('\n')
      self.assertEqual(num_test_files + 1, len(lines))  # +1 line for final \n
    _Check1()

  # TODO: gsutil-beta: Re-enable this once parallel composite upload is ported.
  @unittest.skipUnless(False,
                       'Parallel composite upload not yet implemented.')
  def test_filter_existing_components_non_versioned(self):
    """Tests upload with a variety of component states."""
    bucket_uri = self.CreateBucket()
    tracker_file = self.CreateTempFile(file_name='foo', contents='asdf')
    tracker_file_lock = CreateLock()

    # Already uploaded, contents still match, component still used.
    fpath_uploaded_correctly = self.CreateTempFile(file_name='foo1',
                                                   contents='1')
    key_uploaded_correctly = self.CreateObject(object_name='foo1', contents='1',
                                               bucket_uri=bucket_uri)
    args_uploaded_correctly = PerformResumableUploadIfAppliesArgs(
        fpath_uploaded_correctly, 0, 1, fpath_uploaded_correctly,
        key_uploaded_correctly, '', {}, tracker_file, tracker_file_lock)

    # Not yet uploaded, but needed.
    fpath_not_uploaded = self.CreateTempFile(file_name='foo2', contents='2')
    key_not_uploaded = self.CreateObject(object_name='foo2', contents='2',
                                         bucket_uri=bucket_uri)
    args_not_uploaded = PerformResumableUploadIfAppliesArgs(
        fpath_not_uploaded, 0, 1, fpath_not_uploaded, key_not_uploaded, '', {},
        tracker_file, tracker_file_lock)

    # Already uploaded, but contents no longer match. Even though the contents
    # differ, we don't delete this since the bucket is not versioned and it
    # will be overwritten anyway.
    fpath_wrong_contents = self.CreateTempFile(file_name='foo4', contents='4')
    key_wrong_contents = self.CreateObject(object_name='foo4', contents='_',
                                           bucket_uri=bucket_uri)
    args_wrong_contents = PerformResumableUploadIfAppliesArgs(
        fpath_wrong_contents, 0, 1, fpath_wrong_contents, key_wrong_contents,
        '', {}, tracker_file, tracker_file_lock)

    # Exists in tracker file, but component object no longer exists.
    fpath_remote_deleted = self.CreateTempFile(file_name='foo5', contents='5')
    args_remote_deleted = PerformResumableUploadIfAppliesArgs(
        fpath_remote_deleted, 0, 1, fpath_remote_deleted, '', '', {},
        tracker_file, tracker_file_lock)

    # Exists in tracker file and already uploaded, but no longer needed.
    fpath_no_longer_used = self.CreateTempFile(file_name='foo6', contents='6')
    self.CreateObject(object_name='foo6', contents='6', bucket_uri=bucket_uri)

    dst_args = {fpath_uploaded_correctly: args_uploaded_correctly,
                fpath_not_uploaded: args_not_uploaded,
                fpath_wrong_contents: args_wrong_contents,
                fpath_remote_deleted: args_remote_deleted}

    existing_components = [ObjectFromTracker(fpath_uploaded_correctly, ''),
                           ObjectFromTracker(fpath_wrong_contents, ''),
                           ObjectFromTracker(fpath_remote_deleted, ''),
                           ObjectFromTracker(fpath_no_longer_used, '')]

    suri_builder = StorageUriBuilder(0, BucketStorageUri)

    (components_to_upload, uploaded_components, existing_objects_to_delete) = (
        FilterExistingComponents(dst_args, existing_components,
                                 bucket_uri.bucket_name, suri_builder))

    for arg in [args_not_uploaded, args_wrong_contents, args_remote_deleted]:
      self.assertTrue(arg in components_to_upload)
    self.assertEqual(str([args_uploaded_correctly.dst_uri]),
                     str(uploaded_components))
    self.assertEqual(
        str([MakeGsUri(bucket_uri.bucket_name, fpath_no_longer_used,
                       suri_builder)]),
        str(existing_objects_to_delete))

  # TODO: gsutil-beta: Re-enable this once parallel composite upload is ported.
  @unittest.skipUnless(False,
                       'Parallel composite upload not yet implemented.')
  def test_filter_existing_components_versioned(self):
    """Tests upload with versionined parallel components."""
    suri_builder = StorageUriBuilder(0, BucketStorageUri)
    bucket_uri = self.CreateVersionedBucket()
    tracker_file = self.CreateTempFile(file_name='foo', contents='asdf')
    tracker_file_lock = CreateLock()

    # Already uploaded, contents still match, component still used.
    fpath_uploaded_correctly = self.CreateTempFile(file_name='foo1',
                                                   contents='1')
    key_uploaded_correctly = self.CreateObject(object_name='foo1', contents='1',
                                               bucket_uri=bucket_uri)
    args_uploaded_correctly = PerformResumableUploadIfAppliesArgs(
        fpath_uploaded_correctly, 0, 1, fpath_uploaded_correctly,
        key_uploaded_correctly, key_uploaded_correctly.generation, {},
        tracker_file, tracker_file_lock)

    # Duplicate object name in tracker file, but uploaded correctly.
    fpath_duplicate = fpath_uploaded_correctly
    key_duplicate = self.CreateObject(object_name='foo1', contents='1',
                                      bucket_uri=bucket_uri)
    args_duplicate = PerformResumableUploadIfAppliesArgs(
        fpath_duplicate, 0, 1, fpath_duplicate, key_duplicate,
        key_duplicate.generation, {}, tracker_file, tracker_file_lock)
    object_name_duplicate = ObjectFromTracker(
        fpath_duplicate, key_duplicate.generation).object_name
    uri_duplicate = MakeGsUri(bucket_uri.bucket_name, object_name_duplicate,
                              suri_builder)
    uri_duplicate.generation = args_duplicate.dst_uri.generation

    # Already uploaded, but contents no longer match.
    fpath_wrong_contents = self.CreateTempFile(file_name='foo4', contents='4')
    key_wrong_contents = self.CreateObject(object_name='foo4', contents='_',
                                           bucket_uri=bucket_uri)
    args_wrong_contents = PerformResumableUploadIfAppliesArgs(
        fpath_wrong_contents, 0, 1, fpath_wrong_contents, key_wrong_contents,
        key_wrong_contents.generation, {}, tracker_file, tracker_file_lock)

    dst_args = {fpath_uploaded_correctly: args_uploaded_correctly,
                fpath_wrong_contents: args_wrong_contents}

    existing_components = [ObjectFromTracker(fpath_uploaded_correctly,
                                             key_uploaded_correctly.generation),
                           ObjectFromTracker(fpath_duplicate,
                                             key_duplicate.generation),
                           ObjectFromTracker(fpath_wrong_contents,
                                             key_wrong_contents.generation)]

    suri_builder = StorageUriBuilder(0, BucketStorageUri)

    (components_to_upload, uploaded_components, existing_objects_to_delete) = (
        FilterExistingComponents(dst_args, existing_components,
                                 bucket_uri.bucket_name, suri_builder))

    self.assertEqual([args_wrong_contents], components_to_upload)
    self.assertEqual(str([args_uploaded_correctly.dst_uri]),
                     str(uploaded_components))
    expected_to_delete = [(args_wrong_contents.dst_uri.object_name,
                           args_wrong_contents.dst_uri.generation),
                          (uri_duplicate.object_name,
                           args_duplicate.dst_uri.generation)]
    for uri in existing_objects_to_delete:
      self.assertTrue((uri.object_name, uri.generation) in expected_to_delete)
    self.assertEqual(len(expected_to_delete), len(existing_objects_to_delete))

  # TODO: gsutil-beta: Robust testing for resumable download and upload
  # implementations, which differ substantially from the boto implementation.
  # We should try to unit test as many of the individual classes as possible,
  # possibly inserting some test hooks such that we can simulate breaks.
