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

class TestLogging(testcase.GsUtilIntegrationTestCase):
  
  _enable_cmd_prefix = ['logging', 'set', 'on']
  _disable_cmd_prefix = ['logging', 'set', 'off']
  _get_cmd_prefix = ['logging', 'get']

  def testLogging(self):
    bucket_uri = self.CreateBucket()
    bucket_suri = suri(bucket_uri)
    stderr = self.RunGsUtil(
        self._enable_cmd_prefix + ['-b', bucket_suri, bucket_suri],
        return_stderr=True)
    self.assertIn('Enabling logging', stderr)

    stdout = self.RunGsUtil(self._get_cmd_prefix + [bucket_suri],
                            return_stdout=True)
    self.assertIn('LogObjectPrefix', stdout)

    stderr = self.RunGsUtil(self._disable_cmd_prefix + [bucket_suri],
                            return_stderr=True)
    self.assertIn('Disabling logging', stderr)

  def testTooFewArgumentsFails(self):
    # No arguments for enable, but valid subcommand.
    stderr = self.RunGsUtil(self._enable_cmd_prefix, return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

    # No arguments for disable, but valid subcommand.
    stderr = self.RunGsUtil(self._disable_cmd_prefix, return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)
    
    # No arguments for get, but valid subcommand.
    stderr = self.RunGsUtil(self._get_cmd_prefix, return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

    # Neither arguments nor subcommand.
    stderr = self.RunGsUtil(['logging'], return_stderr=True, expected_status=1)
    self.assertIn('command requires at least', stderr)

class TestLoggingOldAlias(TestLogging):
  _enable_cmd_prefix = ['enablelogging']
  _disable_cmd_prefix = ['disablelogging']
  _get_cmd_prefix = ['getlogging']
