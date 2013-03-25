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


from gslib import aclhelpers
from gslib.command import _ThreadedLogger as ThreadedLogger
import gslib.tests.testcase as case
from gslib.tests.util import ObjectToURI as suri
from gslib.util import Retry


class ChaclIntegrationTest(case.GsUtilIntegrationTestCase):
  """Tests gslib.commands.chacl."""

  def setUp(self):
    super(ChaclIntegrationTest, self).setUp()
    self.sample_uri = self.CreateBucket()
    self.logger = ThreadedLogger('chacl')

  def testAclChangeWithUserId(self):
    change = aclhelpers.AclChange(self.USER_TEST_ID + ':r',
                                  scope_type=aclhelpers.ChangeType.USER,
                                  logger=self.logger)
    acl = self.sample_uri.get_acl()
    change.Execute(self.sample_uri, acl)
    self._AssertHas(acl, 'READ', 'UserById', self.USER_TEST_ID)

  def testAclChangeWithGroupId(self):
    change = aclhelpers.AclChange(self.GROUP_TEST_ID + ':r',
                                  scope_type=aclhelpers.ChangeType.GROUP,
                                  logger=self.logger)
    acl = self.sample_uri.get_acl()
    change.Execute(self.sample_uri, acl)
    self._AssertHas(acl, 'READ', 'GroupById', self.GROUP_TEST_ID)

  def testAclChangeWithUserEmail(self):
    change = aclhelpers.AclChange(self.USER_TEST_ADDRESS + ':r',
                                  scope_type=aclhelpers.ChangeType.USER,
                                  logger=self.logger)
    acl = self.sample_uri.get_acl()
    change.Execute(self.sample_uri, acl)
    self._AssertHas(acl, 'READ', 'UserByEmail', self.USER_TEST_ADDRESS)

  def testAclChangeWithGroupEmail(self):
    change = aclhelpers.AclChange(self.GROUP_TEST_ADDRESS + ':fc',
                                  scope_type=aclhelpers.ChangeType.GROUP,
                                  logger=self.logger)
    acl = self.sample_uri.get_acl()
    change.Execute(self.sample_uri, acl)
    self._AssertHas(acl, 'FULL_CONTROL', 'GroupByEmail',
                    self.GROUP_TEST_ADDRESS)

  def testAclChangeWithDomain(self):
    change = aclhelpers.AclChange(self.DOMAIN_TEST + ':READ',
                                  scope_type=aclhelpers.ChangeType.GROUP,
                                  logger=self.logger)
    acl = self.sample_uri.get_acl()
    change.Execute(self.sample_uri, acl)
    self._AssertHas(acl, 'READ', 'GroupByDomain', self.DOMAIN_TEST)

  def testAclChangeWithAllUsers(self):
    change = aclhelpers.AclChange('AllUsers:WRITE',
                                  scope_type=aclhelpers.ChangeType.GROUP,
                                  logger=self.logger)
    acl = self.sample_uri.get_acl()
    change.Execute(self.sample_uri, acl)
    self._AssertHas(acl, 'WRITE', 'AllUsers')

  def testAclChangeWithAllAuthUsers(self):
    change = aclhelpers.AclChange('AllAuthenticatedUsers:READ',
                                  scope_type=aclhelpers.ChangeType.GROUP,
                                  logger=self.logger)
    acl = self.sample_uri.get_acl()
    change.Execute(self.sample_uri, acl)
    self._AssertHas(acl, 'READ', 'AllAuthenticatedUsers')
    remove = aclhelpers.AclDel('AllAuthenticatedUsers', logger=self.logger)
    remove.Execute(self.sample_uri, acl)
    self._AssertHasNo(acl, 'READ', 'AllAuthenticatedUsers')

  def testAclDelWithUser(self):
    add = aclhelpers.AclChange(self.USER_TEST_ADDRESS + ':READ',
                               scope_type=aclhelpers.ChangeType.USER,
                               logger=self.logger)
    acl = self.sample_uri.get_acl()
    add.Execute(self.sample_uri, acl)
    self._AssertHas(acl, 'READ', 'UserByEmail', self.USER_TEST_ADDRESS)

    remove = aclhelpers.AclDel(self.USER_TEST_ADDRESS,
                               logger=self.logger)
    remove.Execute(self.sample_uri, acl)
    self._AssertHasNo(acl, 'READ', 'UserByEmail', self.USER_TEST_ADDRESS)

  def testAclDelWithGroup(self):
    add = aclhelpers.AclChange(self.USER_TEST_ADDRESS + ':READ',
                               scope_type=aclhelpers.ChangeType.GROUP,
                               logger=self.logger)
    acl = self.sample_uri.get_acl()
    add.Execute(self.sample_uri, acl)
    self._AssertHas(acl, 'READ', 'GroupByEmail', self.USER_TEST_ADDRESS)

    remove = aclhelpers.AclDel(self.USER_TEST_ADDRESS,
                               logger=self.logger)
    remove.Execute(self.sample_uri, acl)
    self._AssertHasNo(acl, 'READ', 'GroupByEmail', self.GROUP_TEST_ADDRESS)

  #
  # Here are a whole lot of verbose asserts
  #

  def _AssertHas(self, current_acl, perm, scope, value=None):
    matches = list(self._YieldMatchingEntries(current_acl, perm, scope, value))
    self.assertEqual(1, len(matches))

  def _AssertHasNo(self, current_acl, perm, scope, value=None):
    matches = list(self._YieldMatchingEntries(current_acl, perm, scope, value))
    self.assertEqual(0, len(matches))

  def _YieldMatchingEntries(self, current_acl, perm, scope, value=None):
    """Generator that finds entries that match the change descriptor."""
    for entry in current_acl.entries.entry_list:
      if entry.scope.type == scope:
        if scope in ['UserById', 'GroupById']:
          if value == entry.scope.id:
            yield entry
        elif scope in ['UserByEmail', 'GroupByEmail']:
          if value == entry.scope.email_address:
            yield entry
        elif scope == 'GroupByDomain':
          if value == entry.scope.domain:
            yield entry
        elif scope in ['AllUsers', 'AllAuthenticatedUsers']:
          yield entry
        else:
          raise Exception('Found an unrecognized ACL entry type, aborting.')

  def _MakeScopeRegex(self, scope_type, email_address, perm):
    template_regex = (
        r'<Scope type="{0}">\s*<EmailAddress>\s*{1}\s*</EmailAddress>\s*'
        r'</Scope>\s*<Permission>\s*{2}\s*</Permission>')
    return template_regex.format(scope_type, email_address, perm)

  def testBucketAclChange(self):
    test_regex = self._MakeScopeRegex(
        'UserByEmail', self.USER_TEST_ADDRESS, 'FULL_CONTROL')
    xml = self.RunGsUtil(
        ['getacl', suri(self.sample_uri)], return_stdout=True)
    self.assertNotRegexpMatches(xml, test_regex)

    self.RunGsUtil(
        ['chacl', '-u', self.USER_TEST_ADDRESS+':fc', suri(self.sample_uri)])
    xml = self.RunGsUtil(
        ['getacl', suri(self.sample_uri)], return_stdout=True)
    self.assertRegexpMatches(xml, test_regex)

    self.RunGsUtil(
        ['chacl', '-d', self.USER_TEST_ADDRESS, suri(self.sample_uri)])
    xml = self.RunGsUtil(
        ['getacl', suri(self.sample_uri)], return_stdout=True)
    self.assertNotRegexpMatches(xml, test_regex)

  def testObjectAclChange(self):
    obj = self.CreateObject(bucket_uri=self.sample_uri, contents='something')
    test_regex = self._MakeScopeRegex(
        'GroupByEmail', self.GROUP_TEST_ADDRESS, 'READ')
    xml = self.RunGsUtil(['getacl', suri(obj)], return_stdout=True)
    self.assertNotRegexpMatches(xml, test_regex)

    self.RunGsUtil(['chacl', '-g', self.GROUP_TEST_ADDRESS+':READ', suri(obj)])
    xml = self.RunGsUtil(['getacl', suri(obj)], return_stdout=True)
    self.assertRegexpMatches(xml, test_regex)

    self.RunGsUtil(['chacl', '-d', self.GROUP_TEST_ADDRESS, suri(obj)])
    xml = self.RunGsUtil(['getacl', suri(obj)], return_stdout=True)
    self.assertNotRegexpMatches(xml, test_regex)

  def testMultithreadedAclChange(self, count=10):
    objects = []
    for i in range(count):
      objects.append(self.CreateObject(
          bucket_uri=self.sample_uri,
          contents='something {0}'.format(i)))

    test_regex = self._MakeScopeRegex(
        'GroupByEmail', self.GROUP_TEST_ADDRESS, 'READ')
    xmls = []
    for obj in objects:
      xmls.append(self.RunGsUtil(['getacl', suri(obj)], return_stdout=True))
    for xml in xmls:
      self.assertNotRegexpMatches(xml, test_regex)

    uris = [suri(obj) for obj in objects]
    self.RunGsUtil(['-m', '-DD', 'chacl', '-g',
                    self.GROUP_TEST_ADDRESS+':READ'] + uris)

    xmls = []
    for obj in objects:
      xmls.append(self.RunGsUtil(['getacl', suri(obj)], return_stdout=True))
    for xml in xmls:
      self.assertRegexpMatches(xml, test_regex)

  def testMultiVersionSupport(self):
    bucket = self.CreateVersionedBucket()
    object_name = self.MakeTempName('obj')
    obj = self.CreateObject(
        bucket_uri=bucket, object_name=object_name, contents='One thing')
    # Create another on the same URI, giving us a second version.
    self.CreateObject(
        bucket_uri=bucket, object_name=object_name, contents='Another thing')

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, delay=1, backoff=1, logger=self.logger)
    def _getObjects():
      stdout = self.RunGsUtil(['ls', '-a', suri(obj)], return_stdout=True)
      lines = stdout.strip().split('\n')
      self.assertEqual(len(lines), 2)
      return lines

    obj_v1, obj_v2 = _getObjects()

    test_regex = self._MakeScopeRegex(
        'GroupByEmail', self.GROUP_TEST_ADDRESS, 'READ')
    xml = self.RunGsUtil(['getacl', obj_v1], return_stdout=True)
    self.assertNotRegexpMatches(xml, test_regex)

    self.RunGsUtil(['chacl', '-g', self.GROUP_TEST_ADDRESS+':READ', obj_v1])
    xml = self.RunGsUtil(['getacl', obj_v1], return_stdout=True)
    self.assertRegexpMatches(xml, test_regex)

    xml = self.RunGsUtil(['getacl', obj_v2], return_stdout=True)
    self.assertNotRegexpMatches(xml, test_regex)

  def testBadRequestAclChange(self):
    stdout, stderr = self.RunGsUtil(
        ['chacl', '-u', 'invalid_$$@hello.com:R', suri(self.sample_uri)],
        return_stdout=True, return_stderr=True, expected_status=1)
    self.assertIn('Bad Request', stderr)
    self.assertNotIn('Retrying', stdout)
    self.assertNotIn('Retrying', stderr)
