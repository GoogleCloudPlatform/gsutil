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
"""Integration tests for rm command."""

from __future__ import absolute_import

import gslib.tests.testcase as testcase
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
    g1 = key_uri.generation or key_uri.version_id
    key_uri.set_contents_from_string('baz')
    g2 = key_uri.generation or key_uri.version_id
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1(stderr_lines):
      stderr = self.RunGsUtil(['-m', 'rm', '-a', suri(key_uri)],
                              return_stderr=True)
      stderr_lines.update(set(stderr.splitlines()))
      stderr = '\n'.join(stderr_lines)
      self.assertEqual(stderr.count('Removing %s://' % self.default_provider),
                       2)
      self.assertIn('Removing %s#%s...' % (suri(key_uri), g1), stderr)
      self.assertIn('Removing %s#%s...' % (suri(key_uri), g2), stderr)
    all_stderr_lines = set()
    _Check1(all_stderr_lines)
    self.AssertNObjectsInBucket(bucket_uri, 0, versioned=True)

  def test_all_versions_no_current(self):
    """Test that 'rm -a' for an object without a current version works."""
    bucket_uri = self.CreateVersionedBucket()
    key_uri = bucket_uri.clone_replace_name('foo')
    key_uri.set_contents_from_string('bar')
    g1 = key_uri.generation or key_uri.version_id
    key_uri.set_contents_from_string('baz')
    g2 = key_uri.generation or key_uri.version_id
    stderr = self.RunGsUtil(['rm', suri(key_uri)], return_stderr=True)
    self.assertEqual(stderr.count('Removing %s://' % self.default_provider), 1)
    self.assertIn('Removing %s...' % suri(key_uri), stderr)
    stderr = self.RunGsUtil(['-m', 'rm', '-a', suri(key_uri)],
                            return_stderr=True)
    self.assertEqual(stderr.count('Removing %s://' % self.default_provider), 2)
    self.assertIn('Removing %s#%s...' % (suri(key_uri), g1), stderr)
    self.assertIn('Removing %s#%s...' % (suri(key_uri), g2), stderr)
    # Use @Retry as hedge against bucket listing eventual consistency.
    self.AssertNObjectsInBucket(bucket_uri, 0, versioned=True)

  def test_fails_for_missing_obj(self):
    bucket_uri = self.CreateVersionedBucket()
    stderr = self.RunGsUtil(['rm', '-a', '%s/foo' % suri(bucket_uri)],
                            return_stderr=True, expected_status=1)
    self.assertIn('No URLs matched', stderr)

  def test_remove_all_versions_recursive_on_bucket(self):
    """Test that 'rm -r' works on bucket."""
    bucket_uri = self.CreateVersionedBucket()
    k1_uri = bucket_uri.clone_replace_name('foo')
    k2_uri = bucket_uri.clone_replace_name('foo2')
    k1_uri.set_contents_from_string('bar')
    k2_uri.set_contents_from_string('bar2')
    k1g1 = k1_uri.generation or k1_uri.version_id
    k2g1 = k2_uri.generation or k2_uri.version_id
    k1_uri.set_contents_from_string('baz')
    k2_uri.set_contents_from_string('baz2')
    k1g2 = k1_uri.generation or k1_uri.version_id
    k2g2 = k2_uri.generation or k2_uri.version_id

    self.AssertNObjectsInBucket(bucket_uri, 4, versioned=True)

    all_stderr_lines = set()
    stderr = self.RunGsUtil(['rm', '-r', suri(bucket_uri)],
                            return_stderr=True)
    all_stderr_lines.update(set(stderr.splitlines()))
    stderr = '\n'.join(all_stderr_lines)
    self.assertEqual(stderr.count('Removing %s://' % self.default_provider), 5)
    self.assertIn('Removing %s#%s...' % (suri(k1_uri), k1g1), stderr)
    self.assertIn('Removing %s#%s...' % (suri(k1_uri), k1g2), stderr)
    self.assertIn('Removing %s#%s...' % (suri(k2_uri), k2g1), stderr)
    self.assertIn('Removing %s#%s...' % (suri(k2_uri), k2g2), stderr)
    self.assertIn('Removing %s/...' % suri(bucket_uri), stderr)

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check():
      # Bucket should no longer exist.
      stderr = self.RunGsUtil(['ls', '-a', suri(bucket_uri)],
                              return_stderr=True, expected_status=1)
      self.assertIn('bucket does not exist', stderr)
    _Check()

  def test_remove_all_versions_recursive_on_subdir(self):
    """Test that 'rm -r' works on subdir."""
    bucket_uri = self.CreateVersionedBucket()
    k1_uri = bucket_uri.clone_replace_name('dir/foo')
    k2_uri = bucket_uri.clone_replace_name('dir/foo2')
    k1_uri.set_contents_from_string('bar')
    k2_uri.set_contents_from_string('bar2')
    k1g1 = k1_uri.generation or k1_uri.version_id
    k2g1 = k2_uri.generation or k2_uri.version_id
    k1_uri.set_contents_from_string('baz')
    k2_uri.set_contents_from_string('baz2')
    k1g2 = k1_uri.generation or k1_uri.version_id
    k2g2 = k2_uri.generation or k2_uri.version_id
    self.AssertNObjectsInBucket(bucket_uri, 4, versioned=True)

    stderr = self.RunGsUtil(['rm', '-r', '%s/dir' % suri(bucket_uri)],
                            return_stderr=True)
    self.assertEqual(stderr.count('Removing %s://' % self.default_provider), 4)
    self.assertIn('Removing %s#%s...' % (suri(k1_uri), k1g1), stderr)
    self.assertIn('Removing %s#%s...' % (suri(k1_uri), k1g2), stderr)
    self.assertIn('Removing %s#%s...' % (suri(k2_uri), k2g1), stderr)
    self.assertIn('Removing %s#%s...' % (suri(k2_uri), k2g2), stderr)
    self.AssertNObjectsInBucket(bucket_uri, 0, versioned=True)

  def test_missing_first_force(self):
    bucket_uri = self.CreateBucket()
    object_uri = self.CreateObject(bucket_uri=bucket_uri, object_name='present',
                                   contents='foo')
    self.AssertNObjectsInBucket(bucket_uri, 1)
    self.RunGsUtil(['rm', '%s/missing' % suri(bucket_uri),
                    suri(object_uri)], expected_status=1)
    stderr = self.RunGsUtil(
        ['rm', '-f', '%s/missing' % suri(bucket_uri), suri(object_uri)],
        return_stderr=True, expected_status=1)
    self.assertEqual(stderr.count('Removing %s://' % self.default_provider), 1)
    self.RunGsUtil(['stat', suri(object_uri)], expected_status=1)

  def test_some_missing(self):
    """Test that 'rm -a' fails when some but not all uris don't exist."""
    bucket_uri = self.CreateVersionedBucket()
    key_uri = bucket_uri.clone_replace_name('foo')
    key_uri.set_contents_from_string('bar')
    self.AssertNObjectsInBucket(bucket_uri, 1, versioned=True)
    stderr = self.RunGsUtil(['rm', '-a', suri(key_uri), '%s/missing'
                             % suri(bucket_uri)],
                            return_stderr=True, expected_status=1)
    self.assertEqual(stderr.count('Removing %s://' % self.default_provider), 1)
    self.assertIn('No URLs matched', stderr)

  def test_some_missing_force(self):
    """Test that 'rm -af' succeeds despite hidden first uri."""
    bucket_uri = self.CreateVersionedBucket()
    key_uri = bucket_uri.clone_replace_name('foo')
    key_uri.set_contents_from_string('bar')
    self.AssertNObjectsInBucket(bucket_uri, 1, versioned=True)
    stderr = self.RunGsUtil(
        ['rm', '-af', suri(key_uri), '%s/missing' % suri(bucket_uri)],
        return_stderr=True, expected_status=1)
    self.assertEqual(stderr.count('Removing %s://' % self.default_provider), 1)
    self.AssertNObjectsInBucket(bucket_uri, 0)

  def test_folder_objects_deleted(self):
    """Test for 'rm -r' of a folder with a dir_$folder$ marker."""
    bucket_uri = self.CreateVersionedBucket()
    key_uri = bucket_uri.clone_replace_name('abc/o1')
    key_uri.set_contents_from_string('foobar')
    folderkey = bucket_uri.clone_replace_name('abc_$folder$')
    folderkey.set_contents_from_string('')
    self.AssertNObjectsInBucket(bucket_uri, 2, versioned=True)
    self.RunGsUtil(['rm', '-r', '%s/abc' % suri(bucket_uri)])
    self.AssertNObjectsInBucket(bucket_uri, 0, versioned=True)
    # Bucket should not be deleted (Should not get ServiceException).
    bucket_uri.get_location(validate=False)

  def test_folder_objects_deleted_with_wildcard(self):
    """Test for 'rm -r' of a folder with a dir_$folder$ marker."""
    bucket_uri = self.CreateVersionedBucket()
    key_uri = bucket_uri.clone_replace_name('abc/o1')
    key_uri.set_contents_from_string('foobar')
    folderkey = bucket_uri.clone_replace_name('abc_$folder$')
    folderkey.set_contents_from_string('')

    self.AssertNObjectsInBucket(bucket_uri, 2, versioned=True)
    stderr = self.RunGsUtil(['rm', '-r', '%s/**' % suri(bucket_uri)],
                            return_stderr=True)
    # Folder wildcard should not generate an error if it's not matched.
    self.assertNotIn('No URLs matched', stderr)

    self.AssertNObjectsInBucket(bucket_uri, 0, versioned=True)
    # Bucket should not be deleted (Should not get ServiceException).
    bucket_uri.get_location(validate=False)

  def test_recursive_bucket_rm(self):
    """Test for 'rm -r' of a bucket."""
    bucket_uri = self.CreateBucket()
    self.CreateObject(bucket_uri)
    self.RunGsUtil(['rm', '-r', suri(bucket_uri)])
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
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
    self.AssertNObjectsInBucket(bucket_uri, 3, versioned=True)
    self.RunGsUtil(['rm', suri(bucket_uri, '**')])
    stderr = self.RunGsUtil(['rb', suri(bucket_uri)],
                            return_stderr=True, expected_status=1)
    self.assertIn('Bucket is not empty', stderr)

    # Now try with rm -r.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check2():
      self.RunGsUtil(['rm', '-r', suri(bucket_uri)])
      # Bucket should be deleted.
      stderr = self.RunGsUtil(['ls', '-Lb', suri(bucket_uri)],
                              return_stderr=True, expected_status=1)
      self.assertIn('bucket does not exist', stderr)
    _Check2()

  def test_recursive_bucket_rm_with_wildcarding(self):
    """Tests removing all objects and buckets matching a bucket wildcard."""
    buri_base = 'gsutil-test-%s' % self._testMethodName
    buri_base = buri_base[:MAX_BUCKET_LENGTH-20]
    buri_base = '%s-%s' % (buri_base, self.MakeRandomTestString())
    buri1 = self.CreateBucket(bucket_name='%s-tbuck1' % buri_base)
    buri2 = self.CreateBucket(bucket_name='%s-tbuck2' % buri_base)
    buri3 = self.CreateBucket(bucket_name='%s-tb3' % buri_base)
    self.CreateObject(bucket_uri=buri1, object_name='o1', contents='z')
    self.CreateObject(bucket_uri=buri2, object_name='o2', contents='z')
    self.CreateObject(bucket_uri=buri3, object_name='o3', contents='z')
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check():
      self.RunGsUtil(['rm', '-r', '%s://%s-tbu*' % (self.default_provider,
                                                    buri_base)])
      stdout = self.RunGsUtil(['ls', '%s://%s-tb*' % (self.default_provider,
                                                      buri_base)],
                              return_stdout=True)
      # 2 = one for single expected line plus one for final \n.
      self.assertEqual(2, len(stdout.split('\n')))
      self.assertEqual('%s://%s-tb3/o3' % (self.default_provider, buri_base),
                       stdout.strip())
    _Check()

  def test_rm_quiet(self):
    """Test that 'rm -q' outputs no progress indications."""
    bucket_uri = self.CreateBucket()
    key_uri = self.CreateObject(bucket_uri=bucket_uri, contents='foo')
    self.AssertNObjectsInBucket(bucket_uri, 1)
    stderr = self.RunGsUtil(['-q', 'rm', suri(key_uri)], return_stderr=True)
    self.assertEqual(stderr.count('Removing '), 0)

  def test_rm_object_with_slash(self):
    """Tests removing a bucket that has an object with a slash in it."""
    bucket_uri = self.CreateVersionedBucket()
    ouri1 = self.CreateObject(bucket_uri=bucket_uri,
                              object_name='/dirwithslash/foo', contents='z')
    ouri2 = self.CreateObject(bucket_uri=bucket_uri,
                              object_name='dirnoslash/foo', contents='z')
    ouri3 = self.CreateObject(bucket_uri=bucket_uri,
                              object_name='dirnoslash/foo2', contents='z')

    self.AssertNObjectsInBucket(bucket_uri, 3, versioned=True)

    # Test with and without final slash on dest subdir.
    all_stderr_lines = set()
    stderr = self.RunGsUtil(['rm', '-r', suri(bucket_uri)],
                            return_stderr=True)
    all_stderr_lines.update(set(stderr.splitlines()))
    stderr = '\n'.join(all_stderr_lines)
    self.assertEqual(stderr.count('Removing %s://' % self.default_provider), 4)
    self.assertIn('Removing %s' % suri(ouri1), stderr)
    self.assertIn('Removing %s' % suri(ouri2), stderr)
    self.assertIn('Removing %s' % suri(ouri3), stderr)

  def test_slasher_horror_film(self):
    """Tests removing a bucket with objects that are filled with slashes."""
    bucket_uri = self.CreateVersionedBucket()
    ouri1 = self.CreateObject(bucket_uri=bucket_uri,
                              object_name='h/e/l//lo',
                              contents='Halloween')
    ouri2 = self.CreateObject(bucket_uri=bucket_uri,
                              object_name='/h/e/l/l/o',
                              contents='A Nightmare on Elm Street')
    ouri3 = self.CreateObject(bucket_uri=bucket_uri,
                              object_name='//h//e/l//l/o',
                              contents='Friday the 13th')
    ouri4 = self.CreateObject(bucket_uri=bucket_uri,
                              object_name='//h//e//l//l//o',
                              contents='I Know What You Did Last Summer')
    ouri5 = self.CreateObject(bucket_uri=bucket_uri,
                              object_name='/',
                              contents='Scream')
    ouri6 = self.CreateObject(bucket_uri=bucket_uri,
                              object_name='//',
                              contents='Child\'s Play')
    ouri7 = self.CreateObject(bucket_uri=bucket_uri,
                              object_name='///',
                              contents='The Prowler')
    ouri8 = self.CreateObject(bucket_uri=bucket_uri,
                              object_name='////',
                              contents='Black Christmas')
    ouri9 = self.CreateObject(
        bucket_uri=bucket_uri,
        object_name='everything/is/better/with/slashes///////',
        contents='Maniac')

    self.AssertNObjectsInBucket(bucket_uri, 9, versioned=True)

    all_stderr_lines = set()
    stderr = self.RunGsUtil(['rm', '-r', suri(bucket_uri)],
                            return_stderr=True)
    all_stderr_lines.update(set(stderr.splitlines()))
    stderr = '\n'.join(all_stderr_lines)
    self.assertEqual(stderr.count('Removing %s://' % self.default_provider), 10)
    self.assertIn('Removing %s' % suri(ouri1), stderr)
    self.assertIn('Removing %s' % suri(ouri2), stderr)
    self.assertIn('Removing %s' % suri(ouri3), stderr)
    self.assertIn('Removing %s' % suri(ouri4), stderr)
    self.assertIn('Removing %s' % suri(ouri5), stderr)
    self.assertIn('Removing %s' % suri(ouri6), stderr)
    self.assertIn('Removing %s' % suri(ouri7), stderr)
    self.assertIn('Removing %s' % suri(ouri8), stderr)
    self.assertIn('Removing %s' % suri(ouri9), stderr)
    self.assertIn('Removing %s' % suri(bucket_uri), stderr)

