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

import os.path

import boto

import gslib.tests.testcase as testcase
from gslib.tests.util import ObjectToURI as suri


CURDIR = os.path.abspath(os.path.dirname(__file__))
TEST_DATA_DIR = os.path.join(CURDIR, 'test_data')


class TestCp(testcase.GsUtilIntegrationTestCase):
  """Integration tests for cp command."""

  def _get_test_file(self, name):
    return os.path.join(TEST_DATA_DIR, name)

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

  def test_streaming(self):
    bucket_uri = self.CreateBucket()
    stderr = self.RunGsUtil(['cp', '-', '%s' % suri(bucket_uri, 'foo')],
                            stdin='bar', return_stderr=True)
    self.assertIn('Copying from <STDIN>', stderr)
    key_uri = bucket_uri.clone_replace_name('foo')
    self.assertEqual(key_uri.get_contents_as_string(), 'bar')

  # TODO: Implement a way to test both with and without using magic file.

  def test_detect_content_type(self):
    bucket_uri = self.CreateBucket()
    dsturi = suri(bucket_uri, 'foo')

    self.RunGsUtil(['cp', self._get_test_file('test.mp3'), dsturi])
    stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
    self.assertIn('Content-Type:\taudio/mpeg', stdout)

    self.RunGsUtil(['cp', self._get_test_file('test.gif'), dsturi])
    stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
    self.assertIn('Content-Type:\timage/gif', stdout)

  def test_content_type_override_default(self):
    bucket_uri = self.CreateBucket()
    dsturi = suri(bucket_uri, 'foo')

    self.RunGsUtil(['-h', 'Content-Type:', 'cp',
                    self._get_test_file('test.mp3'), dsturi])
    stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
    self.assertIn('Content-Type:\tbinary/octet-stream', stdout)

    self.RunGsUtil(['-h', 'Content-Type:', 'cp',
                    self._get_test_file('test.gif'), dsturi])
    stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
    self.assertIn('Content-Type:\tbinary/octet-stream', stdout)

  def test_content_type_override(self):
    bucket_uri = self.CreateBucket()
    dsturi = suri(bucket_uri, 'foo')

    self.RunGsUtil(['-h', 'Content-Type:', 'cp',
                    self._get_test_file('test.mp3'), dsturi])
    stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
    self.assertIn('Content-Type:\tbinary/octet-stream', stdout)

    self.RunGsUtil(['-h', 'Content-Type:', 'cp',
                    self._get_test_file('test.gif'), dsturi])
    stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
    self.assertIn('Content-Type:\tbinary/octet-stream', stdout)

  def test_foo_noct(self):
    bucket_uri = self.CreateBucket()
    dsturi = suri(bucket_uri, 'foo')
    fpath = self.CreateTempFile(contents='foo/bar\n')
    self.RunGsUtil(['cp', fpath, dsturi])
    stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
    USE_MAGICFILE = boto.config.getbool('GSUtil', 'use_magicfile', False)
    content_type = 'text/plain' if USE_MAGICFILE else 'application/octet-stream'
    self.assertIn('Content-Type:\t%s' % content_type, stdout)

  def test_content_type_mismatches(self):
    bucket_uri = self.CreateBucket()
    dsturi = suri(bucket_uri, 'foo')
    fpath = self.CreateTempFile(contents='foo/bar\n')

    self.RunGsUtil(['-h', 'Content-Type:image/gif', 'cp',
                    self._get_test_file('test.mp3'), dsturi])
    stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
    self.assertIn('Content-Type:\timage/gif', stdout)

    self.RunGsUtil(['-h', 'Content-Type:image/gif', 'cp',
                    self._get_test_file('test.gif'), dsturi])
    stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
    self.assertIn('Content-Type:\timage/gif', stdout)

    self.RunGsUtil(['-h', 'Content-Type:image/gif', 'cp', fpath, dsturi])
    stdout = self.RunGsUtil(['ls', '-L', dsturi], return_stdout=True)
    self.assertIn('Content-Type:\timage/gif', stdout)

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
    self.RunGsUtil(['cp', '%s#%s.1' % (k2_uri.versionless_uri, g1), fpath])
    with open(fpath, 'r') as f:
      self.assertEqual(f.read(), 'data1')
    self.RunGsUtil(['cp', '%s#%s.1' % (k2_uri.versionless_uri, g2), fpath])
    with open(fpath, 'r') as f:
      self.assertEqual(f.read(), 'data2')
    self.RunGsUtil(['cp', '%s#%s.1' % (k2_uri.versionless_uri, g3), fpath])
    with open(fpath, 'r') as f:
      self.assertEqual(f.read(), 'data3')

    # Copy first version to current and verify.
    self.RunGsUtil(['cp', '%s#%s.1' % (k2_uri.versionless_uri, g1),
                    k2_uri.versionless_uri])
    self.RunGsUtil(['cp', k2_uri.versionless_uri, fpath])
    with open(fpath, 'r') as f:
      self.assertEqual(f.read(), 'data1')

  def test_stdin_args(self):
    tmpdir = self.CreateTempDir()
    fpath1 = self.CreateTempFile(tmpdir=tmpdir, contents='data1')
    fpath2 = self.CreateTempFile(tmpdir=tmpdir, contents='data2')
    bucket_uri = self.CreateBucket()
    self.RunGsUtil(['cp', '-I', suri(bucket_uri)],
                   stdin='\n'.join((fpath1, fpath2)))
    stdout = self.RunGsUtil(['ls', suri(bucket_uri)], return_stdout=True)
    self.assertIn(os.path.basename(fpath1), stdout)
    self.assertIn(os.path.basename(fpath2), stdout)
    self.assertNumLines(stdout, 2)

  def test_daisy_chain_cp(self):
    # Daisy chain mode is required for copying across storage classes,
    # so create 2 buckets and attempt to copy without vs with daisy chain mode.
    bucket1_uri = self.CreateBucket(storage_class='STANDARD')
    bucket2_uri = self.CreateBucket(
        storage_class='DURABLE_REDUCED_AVAILABILITY')
    key_uri = self.CreateObject(bucket_uri=bucket1_uri, contents='foo')
    stderr = self.RunGsUtil(['cp', suri(key_uri), suri(bucket2_uri)], 
                            return_stderr=True, expected_status=1)
    self.assertIn('Copy-in-the-cloud disallowed', stderr)
    key_uri = self.CreateObject(bucket_uri=bucket1_uri, contents='foo')
    stderr = self.RunGsUtil(['cp', '-D', suri(key_uri), suri(bucket2_uri)], 
                            return_stderr=True)
    self.assertNotIn('Copy-in-the-cloud disallowed', stderr)
