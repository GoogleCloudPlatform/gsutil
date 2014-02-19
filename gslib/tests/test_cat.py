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
"""Tests for cat command."""
import gslib.tests.testcase as testcase
from gslib.tests.util import ObjectToURI as suri


class TestCat(testcase.GsUtilIntegrationTestCase):
  """Integration tests for cat command."""

  def test_cat_range(self):
    """Tests cat command with various range arguments."""
    key_uri = self.CreateObject(contents='0123456789')
    # Test various invalid ranges.
    stderr = self.RunGsUtil(['cat', '-r -', suri(key_uri)],
                            return_stderr=True, expected_status=1)
    self.assertIn('Invalid range', stderr)
    stderr = self.RunGsUtil(['cat', '-r a-b', suri(key_uri)],
                            return_stderr=True, expected_status=1)
    self.assertIn('Invalid range', stderr)
    stderr = self.RunGsUtil(['cat', '-r 1-2-3', suri(key_uri)],
                            return_stderr=True, expected_status=1)
    self.assertIn('Invalid range', stderr)
    stderr = self.RunGsUtil(['cat', '-r 1.7-3', suri(key_uri)],
                            return_stderr=True, expected_status=1)
    self.assertIn('Invalid range', stderr)

    # Test various valid ranges.
    stdout = self.RunGsUtil(['cat', '-r 1-3', suri(key_uri)],
                            return_stdout=True)
    self.assertEqual('123', stdout)
    stdout = self.RunGsUtil(['cat', '-r 8-', suri(key_uri)],
                            return_stdout=True)
    self.assertEqual('89', stdout)
    stdout = self.RunGsUtil(['cat', '-r -3', suri(key_uri)],
                            return_stdout=True)
    self.assertEqual('789', stdout)

  def test_cat_version(self):
    """Tests cat command on versioned objects."""
    bucket_uri = self.CreateVersionedBucket()
    # Create 2 versions of an object.
    uri1 = self.CreateObject(bucket_uri=bucket_uri, contents='data1')
    uri2 = self.CreateObject(bucket_uri=bucket_uri,
                             object_name=uri1.object_name, contents='data2')
    stdout = self.RunGsUtil(['cat', suri(uri1)], return_stdout=True)
    # Last version written should be live.
    self.assertEqual('data2', stdout)
    # Using either version-specific URI should work.
    stdout = self.RunGsUtil(['cat', uri1.version_specific_uri],
                            return_stdout=True)
    self.assertEqual('data1', stdout)
    stdout = self.RunGsUtil(['cat', uri2.version_specific_uri],
                            return_stdout=True)
    self.assertEqual('data2', stdout)
    # Attempting to cat invalid version should result in an error.
    stderr = self.RunGsUtil(['cat', uri2.version_specific_uri + '23'],
                            return_stderr=True, expected_status=1)
    self.assertIn('No URLs matched', stderr)

  def test_cat_multi_arg(self):
    """Tests cat command with multiple arguments."""
    bucket_uri = self.CreateBucket()
    data1 = '0123456789'
    data2 = 'abcdefghij'
    obj_uri1 = self.CreateObject(bucket_uri=bucket_uri, contents=data1)
    obj_uri2 = self.CreateObject(bucket_uri=bucket_uri, contents=data2)
    stdout, stderr = self.RunGsUtil(
        ['cat', suri(obj_uri1), suri(bucket_uri) + 'nonexistent'],
        return_stdout=True, return_stderr=True, expected_status=1)
    # First object should print, second should produce an exception.
    self.assertIn(data1, stdout)
    self.assertIn('NotFoundException', stderr)

    stdout, stderr = self.RunGsUtil(
        ['cat', suri(bucket_uri) + 'nonexistent', suri(obj_uri1)],
        return_stdout=True, return_stderr=True, expected_status=1)

    # If first object is invalid, exception should halt output immediately.
    self.assertNotIn(data1, stdout)
    self.assertIn('NotFoundException', stderr)

    # Two valid objects should both print successfully.
    stdout = self.RunGsUtil(['cat', suri(obj_uri1), suri(obj_uri2)],
                            return_stdout=True)
    self.assertIn(data1 + data2, stdout)
