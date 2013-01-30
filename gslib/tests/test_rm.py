# Copyright 2013 Google Inc.
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
from gslib.tests.util import ObjectToURI as suri


class TestRm(testcase.GsUtilIntegrationTestCase):
  """Integration tests for rm command."""

  def test_all_versions_current(self):
    """Test that 'rm -a' for an object with a current version works."""
    bucket = self.CreateVersionedBucket()
    k = bucket.clone_replace_name('foo')
    k.set_contents_from_string('bar')
    g1 = k.generation
    k.set_contents_from_string('baz')
    g2 = k.generation
    stderr = self.RunGsUtil(['-m', 'rm', '-a', suri(k)], return_stderr=True)
    self.assertEqual(stderr.count('Removing gs://'), 2)
    self.assertIn('Removing %s#%s.1...' % (suri(k), g1), stderr)
    self.assertIn('Removing %s#%s.1...' % (suri(k), g2), stderr)
    stdout = self.RunGsUtil(['ls', '-a', suri(bucket)], return_stdout=True)
    self.assertEqual(stdout, '')

  def test_all_versions_no_current(self):
    """Test that 'rm -a' for an object without a current version works."""
    bucket = self.CreateVersionedBucket()
    k = bucket.clone_replace_name('foo')
    k.set_contents_from_string('bar')
    g1 = k.generation
    k.set_contents_from_string('baz')
    g2 = k.generation
    stderr = self.RunGsUtil(['rm', suri(k)], return_stderr=True)
    self.assertEqual(stderr.count('Removing gs://'), 1)
    self.assertIn('Removing %s...' % suri(k), stderr)
    stderr = self.RunGsUtil(['-m', 'rm', '-a', suri(k)], return_stderr=True)
    self.assertEqual(stderr.count('Removing gs://'), 2)
    self.assertIn('Removing %s#%s.1...' % (suri(k), g1), stderr)
    self.assertIn('Removing %s#%s.1...' % (suri(k), g2), stderr)
    stdout = self.RunGsUtil(['ls', '-a', suri(bucket)], return_stdout=True)
    self.assertEqual(stdout, '')

  def test_fails_for_missing_obj(self):
    bucket = self.CreateVersionedBucket()
    stderr = self.RunGsUtil(['rm', '-a', '%s/foo' % suri(bucket)],
                            return_stderr=True, expected_status=1)
    self.assertIn('Not Found', stderr)

  def test_remove_all_versions_recursive_on_bucket(self):
    """Test that 'rm -ar' works on bucket."""
    bucket = self.CreateVersionedBucket()
    k1 = bucket.clone_replace_name('foo')
    k2 = bucket.clone_replace_name('foo2')
    k1.set_contents_from_string('bar')
    k2.set_contents_from_string('bar2')
    k1g1 = k1.generation
    k2g1 = k2.generation
    k1.set_contents_from_string('baz')
    k2.set_contents_from_string('baz2')
    k1g2 = k1.generation
    k2g2 = k2.generation

    stderr = self.RunGsUtil(['rm', '-ar', suri(bucket)], return_stderr=True)
    self.assertEqual(stderr.count('Removing gs://'), 4)
    self.assertIn('Removing %s#%s.1...' % (suri(k1), k1g1), stderr)
    self.assertIn('Removing %s#%s.1...' % (suri(k1), k1g2), stderr)
    self.assertIn('Removing %s#%s.1...' % (suri(k2), k2g1), stderr)
    self.assertIn('Removing %s#%s.1...' % (suri(k2), k2g2), stderr)
    stdout = self.RunGsUtil(['ls', '-a', suri(bucket)], return_stdout=True)
    self.assertEqual(stdout, '')

  def test_remove_all_versions_recursive_on_subdir(self):
    """Test that 'rm -ar' works on subdir."""
    bucket = self.CreateVersionedBucket()
    k1 = bucket.clone_replace_name('dir/foo')
    k2 = bucket.clone_replace_name('dir/foo2')
    k1.set_contents_from_string('bar')
    k2.set_contents_from_string('bar2')
    k1g1 = k1.generation
    k2g1 = k2.generation
    k1.set_contents_from_string('baz')
    k2.set_contents_from_string('baz2')
    k1g2 = k1.generation
    k2g2 = k2.generation

    stderr = self.RunGsUtil(['rm', '-ar', '%s/dir' % suri(bucket)],
                            return_stderr=True)
    self.assertEqual(stderr.count('Removing gs://'), 4)
    self.assertIn('Removing %s#%s.1...' % (suri(k1), k1g1), stderr)
    self.assertIn('Removing %s#%s.1...' % (suri(k1), k1g2), stderr)
    self.assertIn('Removing %s#%s.1...' % (suri(k2), k2g1), stderr)
    self.assertIn('Removing %s#%s.1...' % (suri(k2), k2g2), stderr)
    stdout = self.RunGsUtil(['ls', '-a', suri(bucket)], return_stdout=True)
    self.assertEqual(stdout, '')

  def test_some_missing(self):
    """Test that 'rm -a' fails when some but not all uris don't exist."""
    bucket = self.CreateVersionedBucket()
    k = bucket.clone_replace_name('foo')
    k.set_contents_from_string('bar')
    stderr = self.RunGsUtil(['rm', '-a', suri(k), '%s/missing' % suri(bucket)],
                            return_stderr=True, expected_status=1)
    self.assertEqual(stderr.count('Removing gs://'), 2)
    self.assertIn('Not Found', stderr)

  def test_some_missing_force(self):
    """Test that 'rm -af' succeeds despite hidden first uri."""
    bucket = self.CreateVersionedBucket()
    k = bucket.clone_replace_name('foo')
    k.set_contents_from_string('bar')
    stderr = self.RunGsUtil(['rm', '-af', suri(k), '%s/missing' % suri(bucket)],
                            return_stderr=True)
    self.assertEqual(stderr.count('Removing gs://'), 2)
    stdout = self.RunGsUtil(['ls', '-a', suri(bucket)], return_stdout=True)
    self.assertEqual(stdout, '')

  def test_folder_objects_deleted(self):
    """Test for 'rm -r' of a folder with a dir_$folder$ marker."""
    bucket = self.CreateVersionedBucket()
    k = bucket.clone_replace_name('abc/o1')
    k.set_contents_from_string('foobar')
    folderkey = bucket.clone_replace_name('abc_$folder$')
    folderkey.set_contents_from_string('')

    stderr = self.RunGsUtil(['rm', '-r', '%s/abc' % suri(bucket)],
                            return_stderr=True)
    self.assertEqual(stderr.count('Removing gs://'), 2)
    stdout = self.RunGsUtil(['ls', suri(bucket)], return_stdout=True)
    self.assertEqual(stdout, '')
