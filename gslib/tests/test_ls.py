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


class TestLs(testcase.GsUtilIntegrationTestCase):
  """Integration tests for ls command."""

  def test_blank_ls(self):
    self.RunGsUtil(['ls'])

  def test_empty_bucket(self):
    bucket = self.CreateBucket()
    stdout = self.RunGsUtil(['ls', suri(bucket)], return_stdout=True)
    self.assertEqual('', stdout)

  def test_empty_bucket_with_b(self):
    bucket = self.CreateBucket()
    stdout = self.RunGsUtil(['ls', '-b', suri(bucket)], return_stdout=True)
    self.assertEqual('%s/\n' % suri(bucket), stdout)

  def test_with_one_object(self):
    bucket = self.CreateBucket(test_objects=1)
    stdout = self.RunGsUtil(['ls', suri(bucket)], return_stdout=True)
    objuri = [suri(bucket.clone_replace_key(key))
              for key in bucket.list_bucket()][0]
    self.assertEqual('%s\n' % objuri, stdout)

  def test_subdir(self):
    bucket = self.CreateBucket(test_objects=1)
    k1 = bucket.clone_replace_name('foo')
    k1.set_contents_from_string('baz')
    k2 = bucket.clone_replace_name('dir/foo')
    k2.set_contents_from_string('bar')
    stdout = self.RunGsUtil(['ls', '%s/dir' % suri(bucket)],
                            return_stdout=True)
    self.assertEqual('%s\n' % suri(k2), stdout)
    stdout = self.RunGsUtil(['ls', suri(k1)], return_stdout=True)
    self.assertEqual('%s\n' % suri(k1), stdout)

  def test_versioning(self):
    bucket1 = self.CreateBucket(test_objects=1)
    bucket2 = self.CreateVersionedBucket(test_objects=1)
    objuri = [suri(bucket1.clone_replace_key(key))
              for key in bucket1.list_bucket()][0]
    self.RunGsUtil(['cp', objuri, suri(bucket2)])
    self.RunGsUtil(['cp', objuri, suri(bucket2)])
    stdout = self.RunGsUtil(['ls', '-a', suri(bucket2)], return_stdout=True)
    self.assertNumLines(stdout, 3)
