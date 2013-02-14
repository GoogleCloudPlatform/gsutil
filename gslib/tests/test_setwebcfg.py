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


class TestSetWebCfg(testcase.GsUtilIntegrationTestCase):
  """Integration tests for setwebcfg command."""

  def test_full(self):
    bucket_uri = self.CreateBucket()
    self.RunGsUtil(['setwebcfg', '-m', 'main', '-e', '404', suri(bucket_uri)])
    stdout = self.RunGsUtil(['getwebcfg', suri(bucket_uri)], return_stdout=True)
    self.assertEquals(stdout, WEBCFG_FULL)

  def test_main(self):
    bucket_uri = self.CreateBucket()
    self.RunGsUtil(['setwebcfg', '-m', 'main', suri(bucket_uri)])
    stdout = self.RunGsUtil(['getwebcfg', suri(bucket_uri)], return_stdout=True)
    self.assertEquals(stdout, WEBCFG_MAIN)

  def test_error(self):
    bucket_uri = self.CreateBucket()
    self.RunGsUtil(['setwebcfg', '-e', '404', suri(bucket_uri)])
    stdout = self.RunGsUtil(['getwebcfg', suri(bucket_uri)], return_stdout=True)
    self.assertEquals(stdout, WEBCFG_ERROR)

  def test_empty(self):
    bucket_uri = self.CreateBucket()
    self.RunGsUtil(['setwebcfg', suri(bucket_uri)])
    stdout = self.RunGsUtil(['getwebcfg', suri(bucket_uri)], return_stdout=True)
    self.assertEquals(stdout, WEBCFG_EMPTY)
