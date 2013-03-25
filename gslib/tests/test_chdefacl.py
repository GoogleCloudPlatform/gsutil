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

import gslib.tests.testcase as case
from gslib.tests.util import ObjectToURI as suri


class ChdefaclIntegrationTest(case.GsUtilIntegrationTestCase):
  """Tests gslib.commands.chdefacl."""

  def _MakeScopeRegex(self, scope_type, email_address, perm):
    template_regex = (
        r'<Scope type="{0}">\s*<EmailAddress>\s*{1}\s*</EmailAddress>\s*'
        r'</Scope>\s*<Permission>\s*{2}\s*</Permission>')
    return template_regex.format(scope_type, email_address, perm)

  def testChangeDefaultAcl(self):
    bucket = self.CreateBucket()

    test_regex = self._MakeScopeRegex(
        'GroupByEmail', self.GROUP_TEST_ADDRESS, 'READ')
    xml = self.RunGsUtil(['getdefacl', suri(bucket)], return_stdout=True)
    self.assertNotRegexpMatches(xml, test_regex)

    self.RunGsUtil(['chdefacl', '-g', self.GROUP_TEST_ADDRESS+':READ',
                    suri(bucket)])
    xml = self.RunGsUtil(['getdefacl', suri(bucket)], return_stdout=True)
    self.assertRegexpMatches(xml, test_regex)

  def testChangeMultipleBuckets(self):
    bucket1 = self.CreateBucket()
    bucket2 = self.CreateBucket()

    test_regex = self._MakeScopeRegex(
        'GroupByEmail', self.GROUP_TEST_ADDRESS, 'READ')
    xml = self.RunGsUtil(['getdefacl', suri(bucket1)], return_stdout=True)
    self.assertNotRegexpMatches(xml, test_regex)
    xml = self.RunGsUtil(['getdefacl', suri(bucket2)], return_stdout=True)
    self.assertNotRegexpMatches(xml, test_regex)

    self.RunGsUtil(['chdefacl', '-g', self.GROUP_TEST_ADDRESS+':READ',
                    suri(bucket1), suri(bucket2)])
    xml = self.RunGsUtil(['getdefacl', suri(bucket1)], return_stdout=True)
    self.assertRegexpMatches(xml, test_regex)
    xml = self.RunGsUtil(['getdefacl', suri(bucket2)], return_stdout=True)
    self.assertRegexpMatches(xml, test_regex)

  def testChangeMultipleAcls(self):
    bucket = self.CreateBucket()

    test_regex_group = self._MakeScopeRegex(
        'GroupByEmail', self.GROUP_TEST_ADDRESS, 'READ')
    test_regex_user = self._MakeScopeRegex(
        'UserByEmail', self.USER_TEST_ADDRESS, 'FULL_CONTROL')
    xml = self.RunGsUtil(['getdefacl', suri(bucket)], return_stdout=True)
    self.assertNotRegexpMatches(xml, test_regex_group)
    self.assertNotRegexpMatches(xml, test_regex_user)

    self.RunGsUtil(['chdefacl', '-g', self.GROUP_TEST_ADDRESS+':READ',
                    '-u', self.USER_TEST_ADDRESS+':fc', suri(bucket)])
    xml = self.RunGsUtil(['getdefacl', suri(bucket)], return_stdout=True)
    self.assertRegexpMatches(xml, test_regex_group)
    self.assertRegexpMatches(xml, test_regex_user)

  def testEmptyDefAcl(self):
    bucket = self.CreateBucket()
    self.RunGsUtil(['setdefacl', 'private', suri(bucket)])
    self.RunGsUtil(['chdefacl', '-u', self.USER_TEST_ADDRESS+':fc',
                    suri(bucket)])
