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

from xml.dom.minidom import parseString

import gslib.tests.testcase as testcase
from gslib.tests.util import ObjectToURI as suri


WEBCFG_FULL = parseString(
    '<WebsiteConfiguration><MainPageSuffix>main'
    '</MainPageSuffix><NotFoundPage>404</NotFoundPage>'
    '</WebsiteConfiguration>').toprettyxml()

WEBCFG_MAIN = parseString(
    '<WebsiteConfiguration>'
    '<MainPageSuffix>main</MainPageSuffix>'
    '</WebsiteConfiguration>').toprettyxml()

WEBCFG_ERROR = parseString(
    '<WebsiteConfiguration><NotFoundPage>'
    '404</NotFoundPage></WebsiteConfiguration>').toprettyxml()

WEBCFG_EMPTY = parseString('<WebsiteConfiguration/>').toprettyxml()


class TestWeb(testcase.GsUtilIntegrationTestCase):
  """Integration tests for the webcfg command."""

  _set_cmd_prefix = ['web', 'set']
  _get_cmd_prefix = ['web', 'get']

  def test_full(self):
    bucket_uri = self.CreateBucket()
    self.RunGsUtil(
        self._set_cmd_prefix + ['-m', 'main', '-e', '404', suri(bucket_uri)])
    stdout = self.RunGsUtil(
        self._get_cmd_prefix + [suri(bucket_uri)], return_stdout=True)
    self.assertEquals(stdout, WEBCFG_FULL)

  def test_main(self):
    bucket_uri = self.CreateBucket()
    self.RunGsUtil(self._set_cmd_prefix + ['-m', 'main', suri(bucket_uri)])
    stdout = self.RunGsUtil(
        self._get_cmd_prefix + [suri(bucket_uri)], return_stdout=True)
    self.assertEquals(stdout, WEBCFG_MAIN)

  def test_error(self):
    bucket_uri = self.CreateBucket()
    self.RunGsUtil(self._set_cmd_prefix + ['-e', '404', suri(bucket_uri)])
    stdout = self.RunGsUtil(
        self._get_cmd_prefix + [suri(bucket_uri)], return_stdout=True)
    self.assertEquals(stdout, WEBCFG_ERROR)
    
  def test_empty(self):
    bucket_uri = self.CreateBucket()
    self.RunGsUtil(self._set_cmd_prefix + [suri(bucket_uri)])
    stdout = self.RunGsUtil(
        self._get_cmd_prefix + [suri(bucket_uri)], return_stdout=True)
    self.assertEquals(stdout, WEBCFG_EMPTY)

  def testTooFewArgumentsFails(self):
    # No arguments for get, but valid subcommand.
    stderr = self.RunGsUtil(self._get_cmd_prefix, return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

    # No arguments for set, but valid subcommand.
    stderr = self.RunGsUtil(self._set_cmd_prefix, return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

    # Neither arguments nor subcommand.
    stderr = self.RunGsUtil(['web'], return_stderr=True, expected_status=1)
    self.assertIn('command requires at least', stderr)
    
class TestWebOldAlias(TestWeb):
  _set_cmd_prefix = ['setwebcfg']
  _get_cmd_prefix = ['getwebcfg']
