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

import boto
import gslib.tests.testcase as testcase
from gslib.tests.util import ObjectToURI as suri


class TestCat(testcase.GsUtilIntegrationTestCase):
  """Integration tests for cat command."""

  def test_cat_range(self):
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
