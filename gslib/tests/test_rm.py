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

import gslib.tests.testcase as testcase
from boto.exception import GSResponseError
from gslib.exception import CommandException
from gslib.tests.testcase.base import MAX_BUCKET_LENGTH
from gslib.tests.util import ObjectToURI as suri
from gslib.util import Retry


class TestRm(testcase.GsUtilIntegrationTestCase):
  """Integration tests for rm command."""

  def test_all_versions_current(self):
    """Test that 'rm -a' for an object with a current version works."""
    bucket_uri = self.CreateVersionedBucket()
    key_uri = bucket_uri.clone_replace_name('foo')
    key_uri.set_contents_from_string('bar')
    g1 = key_uri.generation
    key_uri.set_contents_from_string('baz')
    g2 = key_uri.generation
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1(stderr_lines):
      stderr = self.RunGsUtil(['-m', 'rm', '-a', suri(key_uri)],
                              return_stderr=True)
      stderr_lines.update(set(stderr.splitlines()))
      stderr = '\n'.join(stderr_lines)
      self.assertEqual(stderr.count('Removing gs://'), 2)
      self.assertIn('Removing %s#%s...' % (suri(key_uri), g1), stderr)
      self.assertIn('Removing %s#%s...' % (suri(key_uri), g2), stderr)
    all_stderr_lines = set()
    _Check1(all_stderr_lines)
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check2():
      stdout = self.RunGsUtil(['ls', '-a', suri(bucket_uri)],
                              return_stdout=True)
      self.assertEqual(stdout, '')
    _Check2()

  def test_all_versions_no_current(self):
    """Test that 'rm -a' for an object without a current version works."""
    bucket_uri = self.CreateVersionedBucket()
    key_uri = bucket_uri.clone_replace_name('foo')
    key_uri.set_contents_from_string('bar')
    g1 = key_uri.generation
    key_uri.set_contents_from_string('baz')
    g2 = key_uri.generation
    stderr = self.RunGsUtil(['rm', suri(key_uri)], return_stderr=True)
    self.assertEqual(stderr.count('Removing gs://'), 1)
    self.assertIn('Removing %s...' % suri(key_uri), stderr)
    stderr = self.RunGsUtil(['-m', 'rm', '-a', suri(key_uri)],
                            return_stderr=True)
    self.assertEqual(stderr.count('Removing gs://'), 2)
    self.assertIn('Removing %s#%s...' % (suri(key_uri), g1), stderr)
    self.assertIn('Removing %s#%s...' % (suri(key_uri), g2), stderr)
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-a', suri(bucket_uri)],
                              return_stdout=True)
      self.assertEqual(stdout, '')
    _Check1()

  def test_fails_for_missing_obj(self):
    bucket_uri = self.CreateVersionedBucket()
    stderr = self.RunGsUtil(['rm', '-a', '%s/foo' % suri(bucket_uri)],
                            return_stderr=True, expected_status=1)
    self.assertIn('Not Found', stderr)

  def test_remove_all_versions_recursive_on_bucket(self):
    """Test that 'rm -ar' works on bucket."""
    bucket_uri = self.CreateVersionedBucket()
    k1_uri = bucket_uri.clone_replace_name('foo')
    k2_uri = bucket_uri.clone_replace_name('foo2')
    k1_uri.set_contents_from_string('bar')
    k2_uri.set_contents_from_string('bar2')
    k1g1 = k1_uri.generation
    k2g1 = k2_uri.generation
    k1_uri.set_contents_from_string('baz')
    k2_uri.set_contents_from_string('baz2')
    k1g2 = k1_uri.generation
    k2g2 = k2_uri.generation

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check(stderr_lines):
      status = self.RunGsUtil(['ls', '-b', suri(bucket_uri)],
                              return_status=True, expected_status=None)
      if status == 0:
        # If ls succeeded, the bucket exists, so try and delete.
        stderr = self.RunGsUtil(['rm', '-ar', suri(bucket_uri)],
                                return_stderr=True)
        stderr_lines.update(set(stderr.splitlines()))
      stderr = '\n'.join(stderr_lines)
      self.assertEqual(stderr.count('Removing gs://'), 5)
      self.assertIn('Removing %s#%s...' % (suri(k1_uri), k1g1), stderr)
      self.assertIn('Removing %s#%s...' % (suri(k1_uri), k1g2), stderr)
      self.assertIn('Removing %s#%s...' % (suri(k2_uri), k2g1), stderr)
      self.assertIn('Removing %s#%s...' % (suri(k2_uri), k2g2), stderr)
      # Bucket should no longer exist.
      stderr = self.RunGsUtil(['ls', '-a', suri(bucket_uri)],
                              return_stderr=True, expected_status=1)
      self.assertIn('bucket does not exist', stderr)
    all_stderr_lines = set()
    _Check(all_stderr_lines)

  def test_remove_all_versions_recursive_on_subdir(self):
    """Test that 'rm -ar' works on subdir."""
    bucket_uri = self.CreateVersionedBucket()
    k1_uri = bucket_uri.clone_replace_name('dir/foo')
    k2_uri = bucket_uri.clone_replace_name('dir/foo2')
    k1_uri.set_contents_from_string('bar')
    k2_uri.set_contents_from_string('bar2')
    k1g1 = k1_uri.generation
    k2g1 = k2_uri.generation
    k1_uri.set_contents_from_string('baz')
    k2_uri.set_contents_from_string('baz2')
    k1g2 = k1_uri.generation
    k2g2 = k2_uri.generation

    stderr = self.RunGsUtil(['rm', '-ar', '%s/dir' % suri(bucket_uri)],
                            return_stderr=True)
    self.assertEqual(stderr.count('Removing gs://'), 4)
    self.assertIn('Removing %s#%s...' % (suri(k1_uri), k1g1), stderr)
    self.assertIn('Removing %s#%s...' % (suri(k1_uri), k1g2), stderr)
    self.assertIn('Removing %s#%s...' % (suri(k2_uri), k2g1), stderr)
    self.assertIn('Removing %s#%s...' % (suri(k2_uri), k2g2), stderr)
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-a', suri(bucket_uri)],
                              return_stdout=True)
      self.assertEqual(stdout, '')
    _Check1()

  def test_some_missing(self):
    """Test that 'rm -a' fails when some but not all uris don't exist."""
    bucket_uri = self.CreateVersionedBucket()
    key_uri = bucket_uri.clone_replace_name('foo')
    key_uri.set_contents_from_string('bar')
    stderr = self.RunGsUtil(['rm', '-a', suri(key_uri), '%s/missing'
                            % suri(bucket_uri)],
                            return_stderr=True, expected_status=1)
    self.assertEqual(stderr.count('Removing gs://'), 2)
    self.assertIn('Not Found', stderr)

  def test_some_missing_force(self):
    """Test that 'rm -af' succeeds despite hidden first uri."""
    bucket_uri = self.CreateVersionedBucket()
    key_uri = bucket_uri.clone_replace_name('foo')
    key_uri.set_contents_from_string('bar')
    stderr = self.RunGsUtil(['rm', '-af', suri(key_uri), '%s/missing'
                            % suri(bucket_uri)], return_stderr=True)
    self.assertEqual(stderr.count('Removing gs://'), 2)
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-a', suri(bucket_uri)],
                              return_stdout=True)
      self.assertEqual(stdout, '')
    _Check1()

  def test_folder_objects_deleted(self):
    """Test for 'rm -r' of a folder with a dir_$folder$ marker."""
    bucket_uri = self.CreateVersionedBucket()
    key_uri = bucket_uri.clone_replace_name('abc/o1')
    key_uri.set_contents_from_string('foobar')
    folderkey = bucket_uri.clone_replace_name('abc_$folder$')
    folderkey.set_contents_from_string('')
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      self.RunGsUtil(['rm', '-r', '%s/abc' % suri(bucket_uri)])
      stdout = self.RunGsUtil(['ls', suri(bucket_uri)], return_stdout=True)
      self.assertEqual(stdout, '')
    _Check1()
    # Bucket should not be deleted (Should not get GSResponseError).
    bucket_uri.get_location(validate=False)

  def test_recursive_bucket_rm(self):
    """Test for 'rm -r' of a bucket."""
    bucket_uri = self.CreateBucket()
    self.CreateObject(bucket_uri) 
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      self.RunGsUtil(['rm', '-r', suri(bucket_uri)])
      # Bucket should be deleted.
      stderr = self.RunGsUtil(['ls', '-Lb', suri(bucket_uri)],
                              return_stderr=True, expected_status=1)
      self.assertIn('bucket does not exist', stderr)
    _Check1()

    # Now try same thing, but for a versioned bucket with multiple versions of
    # an object present.
    bucket_uri = self.CreateVersionedBucket()
    self.CreateObject(bucket_uri, 'obj', 'z') 
    self.CreateObject(bucket_uri, 'obj', 'z') 
    self.CreateObject(bucket_uri, 'obj', 'z') 
    stderr = self.RunGsUtil(['rm', '-r', suri(bucket_uri)],
                            return_stderr=True, expected_status=1)
    self.assertIn('versioning enabled', stderr)

    # Now try with rm -ra.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check2():
      self.RunGsUtil(['rm', '-ra', suri(bucket_uri)])
      # Bucket should be deleted.
      stderr = self.RunGsUtil(['ls', '-Lb', suri(bucket_uri)],
                              return_stderr=True, expected_status=1)
      self.assertIn('bucket does not exist', stderr)
    _Check2()

  def test_recursive_bucket_rm_with_wildcarding(self):
    """Tests removing all objects and buckets matching a bucket wildcard"""
    buri_base = 'gsutil-test-%s' % self._testMethodName
    buri_base = buri_base[:MAX_BUCKET_LENGTH-20]
    buri_base = '%s-%s' % (buri_base, self.MakeRandomTestString())
    buri1 = self.CreateBucket(bucket_name='%s-tbuck1' % buri_base)
    buri2 = self.CreateBucket(bucket_name='%s-tbuck2' % buri_base)
    buri3 = self.CreateBucket(bucket_name='%s-tb3' % buri_base)
    ouri1 = self.CreateObject(bucket_uri=buri1, object_name='o1', contents='z')
    ouri2 = self.CreateObject(bucket_uri=buri2, object_name='o2', contents='z')
    ouri3 = self.CreateObject(bucket_uri=buri3, object_name='o3', contents='z')
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check():
      self.RunGsUtil(['rm', '-r', 'gs://%s-tbu*' % buri_base])
      stdout = self.RunGsUtil(['ls', 'gs://%s-tb*' % buri_base],
                              return_stdout=True)
      # 2 = one for single expected line plus one for final \n.
      self.assertEqual(2, len(stdout.split('\n')))
      self.assertEqual('gs://%s-tb3/o3' % buri_base, stdout.strip())
    _Check()

  def test_rm_quiet(self):
    """Test that 'rm -q' outputs no progress indications."""
    bucket_uri = self.CreateBucket()
    key_uri = self.CreateObject(bucket_uri=bucket_uri, contents='foo')
    stderr = self.RunGsUtil(['-q', 'rm', suri(key_uri)], return_stderr=True)
    self.assertEqual(stderr.count('Removing '), 0)
