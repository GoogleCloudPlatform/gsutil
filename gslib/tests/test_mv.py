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
"""Integration tests for mv command."""

from __future__ import absolute_import

import gslib.tests.testcase as testcase
from gslib.tests.util import ObjectToURI as suri


class TestMv(testcase.GsUtilIntegrationTestCase):
  """Integration tests for mv command."""

  def test_moving(self):
    """Tests moving two buckets, one with 2 objects and one with 0 objects."""
    bucket1_uri = self.CreateBucket(test_objects=2)
    self.AssertNObjectsInBucket(bucket1_uri, 2)
    bucket2_uri = self.CreateBucket()
    self.AssertNObjectsInBucket(bucket2_uri, 0)

    # Move two objects from bucket1 to bucket2.
    objs = [bucket1_uri.clone_replace_key(key).versionless_uri
            for key in bucket1_uri.list_bucket()]
    cmd = (['-m', 'mv'] + objs + [suri(bucket2_uri)])
    stderr = self.RunGsUtil(cmd, return_stderr=True)
    self.assertEqual(stderr.count('Copying'), 2)
    self.assertEqual(stderr.count('Removing'), 2)

    self.AssertNObjectsInBucket(bucket1_uri, 0)
    self.AssertNObjectsInBucket(bucket2_uri, 2)

    # Remove one of the objects.
    objs = [bucket2_uri.clone_replace_key(key).versionless_uri
            for key in bucket2_uri.list_bucket()]
    obj1 = objs[0]
    self.RunGsUtil(['rm', obj1])

    self.AssertNObjectsInBucket(bucket1_uri, 0)
    self.AssertNObjectsInBucket(bucket2_uri, 1)

    # Move the 1 remaining object back.
    objs = [suri(bucket2_uri.clone_replace_key(key))
            for key in bucket2_uri.list_bucket()]
    cmd = (['-m', 'mv'] + objs + [suri(bucket1_uri)])
    stderr = self.RunGsUtil(cmd, return_stderr=True)
    self.assertEqual(stderr.count('Copying'), 1)
    self.assertEqual(stderr.count('Removing'), 1)

    self.AssertNObjectsInBucket(bucket1_uri, 1)
    self.AssertNObjectsInBucket(bucket2_uri, 0)

  def test_move_dir_to_bucket(self):
    """Tests moving a local directory to a bucket."""
    bucket_uri = self.CreateBucket()
    dir_to_move = self.CreateTempDir(test_files=2)
    self.RunGsUtil(['mv', dir_to_move, suri(bucket_uri)])
    self.AssertNObjectsInBucket(bucket_uri, 2)



