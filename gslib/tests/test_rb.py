# Copyright 2014 Google Inc. All Rights Reserved.
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
"""Integration tests for rb command."""

import gslib.tests.testcase as testcase
from gslib.tests.util import ObjectToURI as suri


class TestRb(testcase.GsUtilIntegrationTestCase):
  """Integration tests for rb command."""

  def test_rb_bucket_not_empty(self):
    bucket_uri = self.CreateBucket(test_objects=1)
    stderr = self.RunGsUtil(['rb', suri(bucket_uri)], expected_status=1,
                            return_stderr=True)
    self.assertIn('BucketNotEmpty', stderr)

  def test_rb_versioned_bucket_not_empty(self):
    bucket_uri = self.CreateVersionedBucket(test_objects=1)
    stderr = self.RunGsUtil(['rb', suri(bucket_uri)], expected_status=1,
                            return_stderr=True)
    self.assertIn('Bucket is not empty. Note: this is a versioned bucket',
                  stderr)
