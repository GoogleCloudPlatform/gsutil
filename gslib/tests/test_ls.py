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
"""Tests for ls command."""

import posixpath
import re
import subprocess
import sys

import gslib
from gslib.cs_api_map import ApiSelector
import gslib.tests.testcase as testcase
from gslib.tests.testcase.integration_testcase import SkipForS3
from gslib.tests.util import ObjectToURI as suri
from gslib.util import Retry
from gslib.util import UTF8


class TestLs(testcase.GsUtilIntegrationTestCase):
  """Integration tests for ls command."""

  def test_blank_ls(self):
    self.RunGsUtil(['ls'])

  def test_empty_bucket(self):
    bucket_uri = self.CreateBucket()
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', suri(bucket_uri)], return_stdout=True)
      self.assertEqual('', stdout)
    _Check1()

  def test_empty_bucket_with_b(self):
    bucket_uri = self.CreateBucket()
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-b', suri(bucket_uri)],
                              return_stdout=True)
      self.assertEqual('%s/\n' % suri(bucket_uri), stdout)
    _Check1()

  def test_bucket_with_Lb(self):
    """Tests ls -Lb."""
    bucket_uri = self.CreateBucket()
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-Lb', suri(bucket_uri)],
                              return_stdout=True)
      self.assertIn(suri(bucket_uri), stdout)
      self.assertNotIn('TOTAL:', stdout)
    _Check1()

  def test_bucket_with_lb(self):
    """Tests ls -lb."""
    bucket_uri = self.CreateBucket()
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-lb', suri(bucket_uri)],
                              return_stdout=True)
      self.assertIn(suri(bucket_uri), stdout)
      self.assertNotIn('TOTAL:', stdout)
    _Check1()

  def test_bucket_list_wildcard(self):
    """Tests listing multiple buckets with a wildcard."""
    random_prefix = self.MakeRandomTestString()
    bucket1_name = self.MakeTempName('bucket', prefix=random_prefix)
    bucket2_name = self.MakeTempName('bucket', prefix=random_prefix)
    bucket1_uri = self.CreateBucket(bucket_name=bucket1_name)
    bucket2_uri = self.CreateBucket(bucket_name=bucket2_name)
    # This just double checks that the common prefix of the two buckets is what
    # we think it should be (based on implementation detail of CreateBucket).
    # We want to be careful when setting a wildcard on buckets to make sure we
    # don't step outside the test buckets to affect other buckets.
    common_prefix = posixpath.commonprefix([suri(bucket1_uri),
                                            suri(bucket2_uri)])
    self.assertTrue(common_prefix.startswith(
        '%s://%sgsutil-test-test_bucket_list_wildcard-bucket-' %
        (self.default_provider, random_prefix)))
    wildcard = '%s*' % common_prefix

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-b', wildcard], return_stdout=True)
      expected = set([suri(bucket1_uri) + '/', suri(bucket2_uri) + '/'])
      actual = set(stdout.split())
      self.assertEqual(expected, actual)
    _Check1()

  def test_nonexistent_bucket_with_ls(self):
    """Tests a bucket that is known not to exist."""
    stderr = self.RunGsUtil(
        ['ls', '-lb', 'gs://%s' % self.nonexistent_bucket_name],
        return_stderr=True, expected_status=1)
    self.assertIn('404', stderr)

    stderr = self.RunGsUtil(
        ['ls', '-Lb', 'gs://%s' % self.nonexistent_bucket_name],
        return_stderr=True, expected_status=1)
    self.assertIn('404', stderr)

    stderr = self.RunGsUtil(
        ['ls', '-b', 'gs://%s' % self.nonexistent_bucket_name],
        return_stderr=True, expected_status=1)
    self.assertIn('404', stderr)

  def test_with_one_object(self):
    bucket_uri = self.CreateBucket()
    obj_uri = self.CreateObject(bucket_uri=bucket_uri, contents='foo')
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', suri(bucket_uri)], return_stdout=True)
      self.assertEqual('%s\n' % obj_uri, stdout)
    _Check1()

  def test_subdir(self):
    """Tests listing a bucket subdirectory."""
    bucket_uri = self.CreateBucket(test_objects=1)
    k1_uri = bucket_uri.clone_replace_name('foo')
    k1_uri.set_contents_from_string('baz')
    k2_uri = bucket_uri.clone_replace_name('dir/foo')
    k2_uri.set_contents_from_string('bar')
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '%s/dir' % suri(bucket_uri)],
                              return_stdout=True)
      self.assertEqual('%s\n' % suri(k2_uri), stdout)
      stdout = self.RunGsUtil(['ls', suri(k1_uri)], return_stdout=True)
      self.assertEqual('%s\n' % suri(k1_uri), stdout)
    _Check1()

  def test_versioning(self):
    """Tests listing a versioned bucket."""
    bucket1_uri = self.CreateBucket(test_objects=1)
    bucket2_uri = self.CreateVersionedBucket(test_objects=1)
    bucket_list = list(bucket1_uri.list_bucket())

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', suri(bucket1_uri)],
                              return_stdout=True)
      self.assertNumLines(stdout, 1)
    _Check1()

    objuri = [bucket1_uri.clone_replace_key(key).versionless_uri
              for key in bucket_list][0]
    self.RunGsUtil(['cp', objuri, suri(bucket2_uri)])
    self.RunGsUtil(['cp', objuri, suri(bucket2_uri)])
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check2():
      stdout = self.RunGsUtil(['ls', '-a', suri(bucket2_uri)],
                              return_stdout=True)
      self.assertNumLines(stdout, 3)
      stdout = self.RunGsUtil(['ls', '-la', suri(bucket2_uri)],
                              return_stdout=True)
      self.assertIn('%s#' % bucket2_uri.clone_replace_name(bucket_list[0].name),
                    stdout)
      self.assertIn('metageneration=', stdout)
    _Check2()

  def test_etag(self):
    """Tests that listing an object with an etag."""
    bucket_uri = self.CreateBucket()
    obj_uri = self.CreateObject(bucket_uri=bucket_uri, contents='foo')
    # TODO: When testcase setup can use JSON, match against the exact JSON
    # etag.
    etag = obj_uri.get_key().etag
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-l', suri(bucket_uri)],
                              return_stdout=True)
      if self.test_api == ApiSelector.XML:
        self.assertNotIn(etag, stdout)
      else:
        self.assertNotIn('etag=', stdout)
    _Check1()

    def _Check2():
      stdout = self.RunGsUtil(['ls', '-le', suri(bucket_uri)],
                              return_stdout=True)
      if self.test_api == ApiSelector.XML:
        self.assertIn(etag, stdout)
      else:
        self.assertIn('etag=', stdout)
    _Check2()

    def _Check3():
      stdout = self.RunGsUtil(['ls', '-ale', suri(bucket_uri)],
                              return_stdout=True)
      if self.test_api == ApiSelector.XML:
        self.assertIn(etag, stdout)
      else:
        self.assertIn('etag=', stdout)
    _Check3()

  def test_list_sizes(self):
    """Tests various size listing options."""
    bucket_uri = self.CreateBucket()
    self.CreateObject(bucket_uri=bucket_uri, contents='x' * 2048)

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-l', suri(bucket_uri)],
                              return_stdout=True)
      self.assertIn('2048', stdout)
    _Check1()

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check2():
      stdout = self.RunGsUtil(['ls', '-L', suri(bucket_uri)],
                              return_stdout=True)
      self.assertIn('2048', stdout)
    _Check2()

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check3():
      stdout = self.RunGsUtil(['ls', '-al', suri(bucket_uri)],
                              return_stdout=True)
      self.assertIn('2048', stdout)
    _Check3()

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check4():
      stdout = self.RunGsUtil(['ls', '-lh', suri(bucket_uri)],
                              return_stdout=True)
      self.assertIn('2 KB', stdout)
    _Check4()

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check5():
      stdout = self.RunGsUtil(['ls', '-alh', suri(bucket_uri)],
                              return_stdout=True)
      self.assertIn('2 KB', stdout)
    _Check5()

  def test_list_unicode_filename(self):
    """Tests listing an object with a unicode filename."""
    object_name = u'Аудиоархив'
    object_name_bytes = object_name.encode(UTF8)
    bucket_uri = self.CreateVersionedBucket()
    key_uri = self.CreateObject(bucket_uri=bucket_uri, contents='foo',
                                object_name=object_name)
    stdout = self.RunGsUtil(['ls', '-ael', suri(key_uri)],
                            return_stdout=True)
    self.assertIn(object_name_bytes, stdout)
    if self.default_provider == 'gs':
      self.assertIn(key_uri.generation, stdout)
      self.assertIn(
          'metageneration=%s' % key_uri.get_key().metageneration, stdout)
      if self.test_api == ApiSelector.XML:
        self.assertIn(key_uri.get_key().etag, stdout)
      else:
        # TODO: When testcase setup can use JSON, match against the exact JSON
        # etag.
        self.assertIn('etag=', stdout)
    elif self.default_provider == 's3':
      self.assertIn(key_uri.version_id, stdout)
      self.assertIn(key_uri.get_key().etag, stdout)

  def test_list_gzip_content_length(self):
    """Tests listing a gzipped object."""
    file_size = 10000
    file_contents = 'x' * file_size
    fpath = self.CreateTempFile(contents=file_contents, file_name='foo.txt')
    key_uri = self.CreateObject()
    self.RunGsUtil(['cp', '-z', 'txt', suri(fpath), suri(key_uri)])

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-L', suri(key_uri)], return_stdout=True)
      self.assertRegexpMatches(stdout, r'Content-Encoding:\s+gzip')
      find_content_length_re = r'Content-Length:\s+(?P<num>\d)'
      self.assertRegexpMatches(stdout, find_content_length_re)
      m = re.search(find_content_length_re, stdout)
      content_length = int(m.group('num'))
      self.assertGreater(content_length, 0)
      self.assertLess(content_length, file_size)
    _Check1()

  def test_output_chopped(self):
    """Tests that gsutil still succeeds with a truncated stdout."""
    bucket_uri = self.CreateBucket(test_objects=2)

    # Run Python with the -u flag so output is not buffered.
    gsutil_cmd = [
        sys.executable, '-u', gslib.GSUTIL_PATH, 'ls', suri(bucket_uri)]
    # Set bufsize to 0 to make sure output is not buffered.
    p = subprocess.Popen(gsutil_cmd, stdout=subprocess.PIPE, bufsize=0)
    # Immediately close the stdout pipe so that gsutil gets a broken pipe error.
    p.stdout.close()
    p.wait()
    # Make sure it still exited cleanly.
    self.assertEqual(p.returncode, 0)

  def test_recursive_list_trailing_slash(self):
    """Tests listing an object with a trailing slash."""
    bucket_uri = self.CreateBucket()
    self.CreateObject(bucket_uri=bucket_uri, object_name='/', contents='foo')
    stdout = self.RunGsUtil(['ls', '-R', suri(bucket_uri)], return_stdout=True)
    # Note: The suri function normalizes the URI, so the double slash gets
    # removed.
    self.assertIn(suri(bucket_uri) + '/', stdout)

  def test_recursive_list_trailing_two_slash(self):
    """Tests listing an object with two trailing slashes."""
    bucket_uri = self.CreateBucket()
    self.CreateObject(bucket_uri=bucket_uri, object_name='//', contents='foo')
    stdout = self.RunGsUtil(['ls', '-R', suri(bucket_uri)], return_stdout=True)
    # Note: The suri function normalizes the URI, so the double slash gets
    # removed.
    self.assertIn(suri(bucket_uri) + '//', stdout)

  @SkipForS3('S3 anonymous access is not supported.')
  def test_get_object_without_list_bucket_permission(self):
    # Bucket is not publicly readable by default.
    bucket_uri = self.CreateBucket()
    object_uri = self.CreateObject(bucket_uri=bucket_uri,
                                   object_name='permitted', contents='foo')
    # Set this object to be publicly readable.
    self.RunGsUtil(['acl', 'set', 'public-read', suri(object_uri)])
    # Drop credentials.
    with self.SetAnonymousBotoCreds():
      stdout = self.RunGsUtil(['ls', '-L', suri(object_uri)],
                              return_stdout=True)
      self.assertIn(suri(object_uri), stdout)


