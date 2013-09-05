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

import boto
import datetime
import os
import re
import gslib.tests.testcase as testcase
from gslib.tests.util import HAS_S3_CREDS
from gslib.tests.util import unittest

from boto import storage_uri
from boto.storage_uri import BucketStorageUri
from gslib.commands.config import DEFAULT_PARALLEL_COMPOSITE_UPLOAD_THRESHOLD
from gslib.commands.cp import FilterExistingComponents
from gslib.commands.cp import MakeGsUri
from gslib.commands.cp import ObjectFromTracker
from gslib.commands.cp import PerformResumableUploadIfAppliesArgs
from gslib.storage_uri_builder import StorageUriBuilder
from gslib.tests.util import ObjectToURI as suri
from gslib.tests.util import PerformsFileToObjectUpload
from gslib.util import Retry
from gslib.util import TWO_MB


CURDIR = os.path.abspath(os.path.dirname(__file__))
TEST_DATA_DIR = os.path.join(CURDIR, 'test_data')


class TestCp(testcase.GsUtilIntegrationTestCase):
  """Integration tests for cp command."""

  def _get_test_file(self, name):
    return os.path.join(TEST_DATA_DIR, name)

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

  def test_copy_in_cloud_noclobber(self):
    bucket1_uri = self.CreateBucket()
    bucket2_uri = self.CreateBucket()
    key_uri = self.CreateObject(bucket_uri=bucket1_uri, contents='foo')
    stderr = self.RunGsUtil(['cp', suri(key_uri), suri(bucket2_uri)],
                            return_stderr=True)
    self.assertEqual(stderr.count('Copying'), 1)
    stderr = self.RunGsUtil(['cp', '-n', suri(key_uri), suri(bucket2_uri)],
                            return_stderr=True)
    self.assertIn('Skipping existing item: %s' % suri(bucket2_uri,
                  key_uri.object_name), stderr)
    
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

  # TODO: Implement a way to test both with and without using magic file.

  @PerformsFileToObjectUpload
  def test_detect_content_type(self):
    bucket_uri = self.CreateBucket()
    dsturi = suri(bucket_uri, 'foo')

    self.RunGsUtil(['cp', self._get_test_file('test.mp3'), dsturi])
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      self.assertRegexpMatches(stdout, 'Content-Type:\s+audio/mpeg')
    _Check1()

    self.RunGsUtil(['cp', self._get_test_file('test.gif'), dsturi])
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check2():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      self.assertRegexpMatches(stdout, 'Content-Type:\s+image/gif')
    _Check2()

  def test_content_type_override(self):
    bucket_uri = self.CreateBucket()
    dsturi = suri(bucket_uri, 'foo')

    self.RunGsUtil(['-h', 'Content-Type:', 'cp',
                    self._get_test_file('test.mp3'), dsturi])
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      self.assertRegexpMatches(stdout, 'Content-Type:\s+binary/octet-stream')
    _Check1()

    self.RunGsUtil(['-h', 'Content-Type:', 'cp',
                    self._get_test_file('test.gif'), dsturi])
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check2():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      self.assertRegexpMatches(stdout, 'Content-Type:\s+binary/octet-stream')
    _Check2()

  @PerformsFileToObjectUpload
  def test_foo_noct(self):
    bucket_uri = self.CreateBucket()
    dsturi = suri(bucket_uri, 'foo')
    fpath = self.CreateTempFile(contents='foo/bar\n')
    self.RunGsUtil(['cp', fpath, dsturi])
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      USE_MAGICFILE = boto.config.getbool('GSUtil', 'use_magicfile', False)
      content_type = ('text/plain' if USE_MAGICFILE
                      else 'application/octet-stream')
      self.assertRegexpMatches(stdout, 'Content-Type:\s+%s' % content_type)
    _Check1()

  @PerformsFileToObjectUpload
  def test_content_type_mismatches(self):
    bucket_uri = self.CreateBucket()
    dsturi = suri(bucket_uri, 'foo')
    fpath = self.CreateTempFile(contents='foo/bar\n')

    self.RunGsUtil(['-h', 'Content-Type:image/gif', 'cp',
                    self._get_test_file('test.mp3'), dsturi])
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      self.assertRegexpMatches(stdout, 'Content-Type:\s+image/gif')
    _Check1()

    self.RunGsUtil(['-h', 'Content-Type:image/gif', 'cp',
                    self._get_test_file('test.gif'), dsturi])
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check2():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      self.assertRegexpMatches(stdout, 'Content-Type:\s+image/gif')
    _Check2()

    self.RunGsUtil(['-h', 'Content-Type:image/gif', 'cp', fpath, dsturi])
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check3():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      self.assertRegexpMatches(stdout, 'Content-Type:\s+image/gif')
    _Check3()

  @PerformsFileToObjectUpload
  def test_content_type_header_case_insensitive(self):
    bucket_uri = self.CreateBucket()
    dsturi = suri(bucket_uri, 'foo')
    fpath = self._get_test_file('test.gif')

    self.RunGsUtil(['-h', 'content-Type:text/plain', 'cp',
                    fpath, dsturi])
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      self.assertRegexpMatches(stdout, 'Content-Type:\s+text/plain')
      self.assertNotRegexpMatches(stdout, 'image/gif')
    _Check1()

    self.RunGsUtil(['-h', 'CONTENT-TYPE:image/gif',
                    '-h', 'content-type:image/gif',
                    'cp', fpath, dsturi])
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check2():
      stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
      self.assertRegexpMatches(stdout, 'Content-Type:\s+image/gif')
      self.assertNotRegexpMatches(stdout, 'image/gif,\s*image/gif')
    _Check2()

  @PerformsFileToObjectUpload
  def test_versioning(self):
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
    # Tests that cp -R between versioned buckets copies all versions and
    # preserves version order.
    bucket1_uri = self.CreateVersionedBucket()
    bucket2_uri = self.CreateVersionedBucket()
    # Write two versions of an object to the bucket1.
    k_uri = self.CreateObject(bucket_uri=bucket1_uri, object_name='k',
                              contents='data0')
    self.CreateObject(bucket_uri=bucket1_uri, object_name='k',
                      contents='longer_data1')
    # Recursively copy to second versioned bucket.
    self.RunGsUtil(['cp', '-R', suri(bucket1_uri, '*'), suri(bucket2_uri)])
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
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
    _Check1()

  @PerformsFileToObjectUpload
  def test_cp_v_option(self):
    # Tests that cp -v option returns the created object's version-specific URI.
    bucket_uri = self.CreateVersionedBucket()
    k1_uri = self.CreateObject(bucket_uri=bucket_uri, contents='data1')
    k2_uri = self.CreateObject(bucket_uri=bucket_uri, contents='data2')
    g1 = k1_uri.generation

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
      self.assertEqual(created_uri, lines[-2])
    _Check1()

  @PerformsFileToObjectUpload
  def test_stdin_args(self):
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

  def test_daisy_chain_cp(self):
    # Daisy chain mode is required for copying across storage classes,
    # so create 2 buckets and attempt to copy without vs with daisy chain mode.
    bucket1_uri = self.CreateBucket(storage_class='STANDARD')
    bucket2_uri = self.CreateBucket(
        storage_class='DURABLE_REDUCED_AVAILABILITY')
    key_uri = self.CreateObject(bucket_uri=bucket1_uri, contents='foo')
    # Check that copy-in-the-cloud is disallowed.
    stderr = self.RunGsUtil(['cp', suri(key_uri), suri(bucket2_uri)],
                            return_stderr=True, expected_status=1)
    self.assertIn('Copy-in-the-cloud disallowed', stderr)
    # Set some headers on source object so we can verify that headers are
    # presereved by daisy-chain copy.
    self.RunGsUtil(['setmeta', '-h', 'Cache-Control:public,max-age=12',
                    '-h', 'Content-Type:image/gif',
                    '-h', 'x-goog-meta-1:abcd', suri(key_uri)])
    # Set public-read (non-default) ACL so we can verify that cp -D -p works.
    self.RunGsUtil(['acl', 'set', 'public-read', suri(key_uri)])
    acl_xml = self.RunGsUtil(['acl', 'get', suri(key_uri)], return_stdout=True)
    # Perform daisy-chain copy and verify that it wasn't disallowed and that
    # source object headers and ACL were preserved. Also specify -n option to
    # test that gsutil correctly removes the x-goog-if-generation-match:0 header
    # that was set at uploading time when updating the ACL.
    stderr = self.RunGsUtil(['cp', '-Dpn', suri(key_uri), suri(bucket2_uri)],
                            return_stderr=True)
    self.assertNotIn('Copy-in-the-cloud disallowed', stderr)
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check():
      uri = suri(bucket2_uri, key_uri.object_name)
      stdout = self.RunGsUtil(['ls', '-L', uri], return_stdout=True)
      self.assertRegexpMatches(stdout, 'Cache-Control:\s+public,max-age=12')
      self.assertRegexpMatches(stdout, 'Content-Type:\s+image/gif')
      self.assertRegexpMatches(stdout, 'x-goog-meta-1:\s+abcd')
      new_acl_xml = self.RunGsUtil(['acl', 'get', uri], return_stdout=True)
      self.assertEqual(acl_xml, new_acl_xml)
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
    # Tests that recursively copying from bucket to bucket produces identically
    # named objects (and not, in particular, destination objects named by the
    # version- specific URI from source objects).
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
    # Tests that recursively copying from bucket to dir produces identically
    # named objects (and not, in particular, destination objects named by the
    # version- specific URI from source objects).
    src_bucket_uri = self.CreateBucket()
    dst_dir = self.CreateTempDir()
    self.CreateObject(bucket_uri=src_bucket_uri, object_name='obj0',
                      contents='abc')
    self.CreateObject(bucket_uri=src_bucket_uri, object_name='obj1',
                      contents='def')
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _CopyAndCheck():
      self.RunGsUtil(['cp', '-R', suri(src_bucket_uri), dst_dir])
      dir_list = []
      for dirname, dirnames, filenames in os.walk(dst_dir):
        for filename in filenames:
          dir_list.append(os.path.join(dirname, filename))
      dir_list = sorted(dir_list)
      self.assertEqual(len(dir_list), 2)
      self.assertEqual(os.path.join(dst_dir, src_bucket_uri.bucket_name,
                                    "obj0"), dir_list[0])
      self.assertEqual(os.path.join(dst_dir, src_bucket_uri.bucket_name,
                                    "obj1"), dir_list[1])
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
    bucket_uri = self.CreateBucket()
    dsturi = suri(bucket_uri, 'foo')

    fpath = self.CreateTempFile(contents='bar')
    logpath = self.CreateTempFile(contents='')
    # Ensure the file is empty.
    open(logpath, 'w').close()
    stdout = self.RunGsUtil(['cp', '-L', logpath, fpath, dsturi],
                            return_stdout=True)
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
    key_uri = self.CreateObject(contents='foo')
    fpath = self.CreateTempFile(contents='')
    logpath = self.CreateTempFile(contents='')
    # Ensure the file is empty.
    open(logpath, 'w').close()
    stdout = self.RunGsUtil(['cp', '-L', logpath, suri(key_uri), fpath],
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
    fpath_bytes = fpath.encode('utf-8')
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

  def test_filter_existing_components_non_versioned(self):
    bucket_name = 'filter_existing_components_bucket_non_versioned'

    bucket_uri = self.CreateBucket(bucket_name=bucket_name)

    # Already uploaded, contents still match, component still used.
    fpath_uploaded_correctly = self.CreateTempFile(file_name='foo1',
                                                   contents='1')
    key_uploaded_correctly = self.CreateObject(object_name='foo1', contents='1',
                                               bucket_uri=bucket_uri)
    args_uploaded_correctly = PerformResumableUploadIfAppliesArgs(
        fpath_uploaded_correctly, 0, 1, fpath_uploaded_correctly,
        key_uploaded_correctly, '', {})

    # Not yet uploaded, but needed.
    fpath_not_uploaded = self.CreateTempFile(file_name='foo2', contents='2')
    key_not_uploaded = self.CreateObject(object_name='foo2', contents='2',
                                         bucket_uri=bucket_uri)
    args_not_uploaded = PerformResumableUploadIfAppliesArgs(
        fpath_not_uploaded, 0, 1, fpath_not_uploaded, key_not_uploaded, '', {})

    # Already uploaded, but contents no longer match. Even though the contents
    # differ, we don't delete this since the bucket is not versioned and it
    # will be overwritten anyway.
    fpath_wrong_contents = self.CreateTempFile(file_name='foo4', contents='4')
    key_wrong_contents = self.CreateObject(object_name='foo4', contents='_',
                             bucket_uri=bucket_uri)
    args_wrong_contents = PerformResumableUploadIfAppliesArgs(
        fpath_wrong_contents, 0, 1, fpath_wrong_contents, key_wrong_contents,
        '', {})

    # Exists in tracker file, but component object no longer exists.
    fpath_remote_deleted = self.CreateTempFile(file_name='foo5', contents='5')
    args_remote_deleted = PerformResumableUploadIfAppliesArgs(
        fpath_remote_deleted, 0, 1, fpath_remote_deleted, '', '', {})

    # Exists in tracker file and already uploaded, but no longer needed.
    fpath_no_longer_used = self.CreateTempFile(file_name='foo6', contents='6')
    key_no_longer_used = self.CreateObject(object_name='foo6', contents='6',
                             bucket_uri=bucket_uri)

    dst_args = {fpath_uploaded_correctly:args_uploaded_correctly,
                fpath_not_uploaded:args_not_uploaded,
                fpath_wrong_contents:args_wrong_contents,
                fpath_remote_deleted:args_remote_deleted}

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
        str([MakeGsUri(bucket_name, fpath_no_longer_used, suri_builder)]),
        str(existing_objects_to_delete))

  def test_filter_existing_components_versioned(self):
    bucket_name = 'filter_existing_components_bucket_versioned'
    bucket_uri = self.CreateVersionedBucket(bucket_name=bucket_name)

    # Already uploaded, contents still match, component still used.
    fpath_uploaded_correctly = self.CreateTempFile(file_name='foo1',
                                                   contents='1')
    key_uploaded_correctly = self.CreateObject(object_name='foo1', contents='1',
                             bucket_uri=bucket_uri)
    args_uploaded_correctly = PerformResumableUploadIfAppliesArgs(
        fpath_uploaded_correctly, 0, 1, fpath_uploaded_correctly,
        key_uploaded_correctly, key_uploaded_correctly.generation, {})

    # Already uploaded, but contents no longer match.
    fpath_wrong_contents = self.CreateTempFile(file_name='foo4', contents='4')
    key_wrong_contents = self.CreateObject(object_name='foo4', contents='_',
                             bucket_uri=bucket_uri)

    args_wrong_contents = PerformResumableUploadIfAppliesArgs(
        fpath_wrong_contents, 0, 1, fpath_wrong_contents, key_wrong_contents,
        key_wrong_contents.generation, {})

    dst_args = {fpath_uploaded_correctly:args_uploaded_correctly,
                fpath_wrong_contents:args_wrong_contents}

    existing_components = [ObjectFromTracker(fpath_uploaded_correctly,
                                             key_uploaded_correctly.generation),
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
                           args_wrong_contents.dst_uri.generation)]
    for uri in existing_objects_to_delete:
      self.assertTrue((uri.object_name, uri.generation) in expected_to_delete)
    self.assertEqual(len(expected_to_delete), len(existing_objects_to_delete))
