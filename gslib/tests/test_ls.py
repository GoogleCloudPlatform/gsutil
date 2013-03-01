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
from gslib.util import Retry
from gslib.tests.util import ObjectToURI as suri


class TestLs(testcase.GsUtilIntegrationTestCase):
  """Integration tests for ls command."""

  def test_blank_ls(self):
    self.RunGsUtil(['ls'])

  def test_empty_bucket(self):
    bucket_uri = self.CreateBucket()
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, delay=1, backoff=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', suri(bucket_uri)], return_stdout=True)
      self.assertEqual('', stdout)
    _Check1()

  def test_empty_bucket_with_b(self):
    bucket_uri = self.CreateBucket()
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, delay=1, backoff=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-b', suri(bucket_uri)],
                              return_stdout=True)
      self.assertEqual('%s/\n' % suri(bucket_uri), stdout)
    _Check1()

  def test_with_one_object(self):
    bucket_uri = self.CreateBucket(test_objects=1)
    objuri = [suri(bucket_uri.clone_replace_name(key.name))
              for key in bucket_uri.list_bucket()][0]
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, delay=1, backoff=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', suri(bucket_uri)], return_stdout=True)
      self.assertEqual('%s\n' % objuri, stdout)
    _Check1()

  def test_subdir(self):
    bucket_uri = self.CreateBucket(test_objects=1)
    k1_uri = bucket_uri.clone_replace_name('foo')
    k1_uri.set_contents_from_string('baz')
    k2_uri = bucket_uri.clone_replace_name('dir/foo')
    k2_uri.set_contents_from_string('bar')
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, delay=1, backoff=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '%s/dir' % suri(bucket_uri)],
                              return_stdout=True)
      self.assertEqual('%s\n' % suri(k2_uri), stdout)
      stdout = self.RunGsUtil(['ls', suri(k1_uri)], return_stdout=True)
      self.assertEqual('%s\n' % suri(k1_uri), stdout)
    _Check1()

  def test_versioning(self):
    bucket1_uri = self.CreateBucket(test_objects=1)
    bucket2_uri = self.CreateVersionedBucket(test_objects=1)
    bucket_list = list(bucket1_uri.list_bucket())
    objuri = [bucket1_uri.clone_replace_key(key).versionless_uri
              for key in bucket_list][0]
    self.RunGsUtil(['cp', objuri, suri(bucket2_uri)])
    self.RunGsUtil(['cp', objuri, suri(bucket2_uri)])
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, delay=1, backoff=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-a', suri(bucket2_uri)],
                              return_stdout=True)
      self.assertNumLines(stdout, 3)
      stdout = self.RunGsUtil(['ls', '-la', suri(bucket2_uri)],
                              return_stdout=True)
      self.assertIn('%s#' % bucket2_uri.clone_replace_name(bucket_list[0].name),
                    stdout)
      self.assertIn('metageneration=', stdout)
    _Check1()
