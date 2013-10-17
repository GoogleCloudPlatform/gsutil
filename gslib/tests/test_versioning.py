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
from gslib.tests.util import ObjectToURI as suri


class TestVersioning(testcase.GsUtilIntegrationTestCase):
  """Integration tests for versioning command."""
  
  _set_cmd_prefix = ['versioning', 'set']
  _get_cmd_prefix = ['versioning', 'get']

  def test_off_default(self):
    bucket_uri = self.CreateBucket()
    stdout = self.RunGsUtil(
        self._get_cmd_prefix + [suri(bucket_uri)], return_stdout=True)
    self.assertEqual(stdout.strip(), '%s: Suspended' % suri(bucket_uri))

  def test_turning_on(self):
    bucket_uri = self.CreateBucket()
    self.RunGsUtil(self._set_cmd_prefix + ['on', suri(bucket_uri)])
    stdout = self.RunGsUtil(
        self._get_cmd_prefix + [suri(bucket_uri)], return_stdout=True)
    self.assertEqual(stdout.strip(), '%s: Enabled' % suri(bucket_uri))

  def test_turning_off(self):
    bucket_uri = self.CreateBucket()
    self.RunGsUtil(self._set_cmd_prefix + ['on', suri(bucket_uri)])
    stdout = self.RunGsUtil(
        self._get_cmd_prefix + [suri(bucket_uri)], return_stdout=True)
    self.assertEqual(stdout.strip(), '%s: Enabled' % suri(bucket_uri))
    self.RunGsUtil(self._set_cmd_prefix + ['off', suri(bucket_uri)])
    stdout = self.RunGsUtil(
        self._get_cmd_prefix + [suri(bucket_uri)], return_stdout=True)
    self.assertEqual(stdout.strip(), '%s: Suspended' % suri(bucket_uri))

  def testTooFewArgumentsFails(self):
    # No arguments for set, but valid subcommand.
    stderr = self.RunGsUtil(self._set_cmd_prefix, return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

    # No arguments for get, but valid subcommand.
    stderr = self.RunGsUtil(self._get_cmd_prefix, return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

    # Neither arguments nor subcommand.
    stderr = self.RunGsUtil(['versioning'], return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

class TestVersioningOldAlias(TestVersioning):
  _set_cmd_prefix = ['setversioning']
  _get_cmd_prefix = ['getversioning']
