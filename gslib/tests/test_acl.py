# -*- coding: utf-8 -*-
# Copyright 2013 Google Inc.  All Rights Reserved.
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
"""Integration tests for the acl command."""

import re

from gslib import aclhelpers
from gslib.command import CreateGsutilLogger
import gslib.tests.testcase as testcase
from gslib.tests.util import ObjectToURI as suri
from gslib.tests.util import unittest
from gslib.tests.util import USING_JSON_API
from gslib.util import Retry

PUBLIC_READ_JSON_ACL_TEXT = '"entity":"allUsers","role":"READER"'


class TestAcl(testcase.GsUtilIntegrationTestCase):
  """Integration tests for acl command."""

  _set_acl_prefix = ['acl', 'set']
  _get_acl_prefix = ['acl', 'get']
  _set_defacl_prefix = ['defacl', 'set']
  _ch_acl_prefix = ['acl', 'ch']

  def setUp(self):
    super(TestAcl, self).setUp()
    self.sample_uri = self.CreateBucket()
    self.logger = CreateGsutilLogger('acl')

  def test_set_invalid_acl_object(self):
    """Ensures that invalid content returns a bad request error."""
    obj_uri = suri(self.CreateObject(contents='foo'))
    inpath = self.CreateTempFile(contents='badAcl')
    stderr = self.RunGsUtil(self._set_acl_prefix + [inpath, obj_uri],
                            return_stderr=True, expected_status=1)
    self.assertIn('ArgumentException', stderr)

  def test_set_invalid_acl_bucket(self):
    """Ensures that invalid content returns a bad request error."""
    bucket_uri = suri(self.CreateBucket())
    inpath = self.CreateTempFile(contents='badAcl')
    stderr = self.RunGsUtil(self._set_acl_prefix + [inpath, bucket_uri],
                            return_stderr=True, expected_status=1)
    self.assertIn('ArgumentException', stderr)

  def test_set_xml_acl_json_api_object(self):
    """Ensures XML content returns a bad request error and migration warning."""
    obj_uri = suri(self.CreateObject(contents='foo'))
    inpath = self.CreateTempFile(contents='<ValidXml></ValidXml>')
    stderr = self.RunGsUtil(self._set_acl_prefix + [inpath, obj_uri],
                            return_stderr=True, expected_status=1)
    self.assertIn('ArgumentException', stderr)
    self.assertIn('XML ACL data provided', stderr)

  def test_set_xml_acl_json_api_bucket(self):
    """Ensures XML content returns a bad request error and migration warning."""
    bucket_uri = suri(self.CreateBucket())
    inpath = self.CreateTempFile(contents='<ValidXml></ValidXml>')
    stderr = self.RunGsUtil(self._set_acl_prefix + [inpath, bucket_uri],
                            return_stderr=True, expected_status=1)
    self.assertIn('ArgumentException', stderr)
    self.assertIn('XML ACL data provided', stderr)

  def test_set_valid_acl_object(self):
    """Tests setting a valid ACL on an object."""
    obj_uri = suri(self.CreateObject(contents='foo'))
    acl_string = self.RunGsUtil(self._get_acl_prefix + [obj_uri],
                                return_stdout=True)
    inpath = self.CreateTempFile(contents=acl_string)
    self.RunGsUtil(self._set_acl_prefix + ['public-read', obj_uri])
    acl_string2 = self.RunGsUtil(self._get_acl_prefix + [obj_uri],
                                 return_stdout=True)
    self.RunGsUtil(self._set_acl_prefix + [inpath, obj_uri])
    acl_string3 = self.RunGsUtil(self._get_acl_prefix + [obj_uri],
                                 return_stdout=True)

    self.assertNotEqual(acl_string, acl_string2)
    self.assertEqual(acl_string, acl_string3)

  def test_set_valid_permission_whitespace_object(self):
    """Ensures that whitespace is allowed in role and entity elements."""
    obj_uri = suri(self.CreateObject(contents='foo'))
    acl_string = self.RunGsUtil(self._get_acl_prefix + [obj_uri],
                                return_stdout=True)
    acl_string = re.sub(r'"role"', r'"role" \n', acl_string)
    acl_string = re.sub(r'"entity"', r'\n "entity"', acl_string)
    inpath = self.CreateTempFile(contents=acl_string)

    self.RunGsUtil(self._set_acl_prefix + [inpath, obj_uri])

  def test_set_valid_acl_bucket(self):
    """Ensures that valid canned and XML ACLs work with get/set."""
    bucket_uri = suri(self.CreateBucket())
    acl_string = self.RunGsUtil(self._get_acl_prefix + [bucket_uri],
                                return_stdout=True)
    inpath = self.CreateTempFile(contents=acl_string)
    self.RunGsUtil(self._set_acl_prefix + ['public-read', bucket_uri])
    acl_string2 = self.RunGsUtil(self._get_acl_prefix + [bucket_uri],
                                 return_stdout=True)
    self.RunGsUtil(self._set_acl_prefix + [inpath, bucket_uri])
    acl_string3 = self.RunGsUtil(self._get_acl_prefix + [bucket_uri],
                                 return_stdout=True)

    self.assertNotEqual(acl_string, acl_string2)
    self.assertEqual(acl_string, acl_string3)

  def test_invalid_canned_acl_object(self):
    """Ensures that an invalid canned ACL returns a CommandException."""
    obj_uri = suri(self.CreateObject(contents='foo'))
    stderr = self.RunGsUtil(
        self._set_acl_prefix + ['not-a-canned-acl', obj_uri],
        return_stderr=True, expected_status=1)
    self.assertIn('CommandException', stderr)
    self.assertIn('Invalid canned ACL', stderr)

  def test_set_valid_def_acl_bucket(self):
    """Ensures that valid default canned and XML ACLs works with get/set."""
    bucket_uri = self.CreateBucket()

    # Default ACL is project private.
    obj_uri1 = suri(self.CreateObject(bucket_uri=bucket_uri, contents='foo'))
    acl_string = self.RunGsUtil(self._get_acl_prefix + [obj_uri1],
                                return_stdout=True)

    # Change it to authenticated-read.
    self.RunGsUtil(
        self._set_defacl_prefix + ['authenticated-read', suri(bucket_uri)])
    obj_uri2 = suri(self.CreateObject(bucket_uri=bucket_uri, contents='foo2'))
    acl_string2 = self.RunGsUtil(self._get_acl_prefix + [obj_uri2],
                                 return_stdout=True)

    # Now change it back to the default via XML.
    inpath = self.CreateTempFile(contents=acl_string)
    self.RunGsUtil(self._set_defacl_prefix + [inpath, suri(bucket_uri)])
    obj_uri3 = suri(self.CreateObject(bucket_uri=bucket_uri, contents='foo3'))
    acl_string3 = self.RunGsUtil(self._get_acl_prefix + [obj_uri3],
                                 return_stdout=True)

    self.assertNotEqual(acl_string, acl_string2)
    self.assertIn('allAuthenticatedUsers', acl_string2)
    self.assertEqual(acl_string, acl_string3)

  def test_acl_set_version_specific_uri(self):
    """Tests setting an ACL on a specific version of an object."""
    bucket_uri = self.CreateVersionedBucket()
    # Create initial object version.
    uri = self.CreateObject(bucket_uri=bucket_uri, contents='data')
    # Create a second object version.
    inpath = self.CreateTempFile(contents='def')
    self.RunGsUtil(['cp', inpath, uri.uri])

    # Find out the two object version IDs.
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _GetVersions():
      stdout = self.RunGsUtil(['ls', '-a', uri.uri], return_stdout=True)
      lines = stdout.split('\n')
      # There should be 3 lines, counting final \n.
      self.assertEqual(len(lines), 3)
      return lines[0], lines[1]

    v0_uri_str, v1_uri_str = _GetVersions()

    # Check that neither version currently has public-read permission
    # (default ACL is project-private).
    orig_acls = []
    for uri_str in (v0_uri_str, v1_uri_str):
      acl = self.RunGsUtil(self._get_acl_prefix + [uri_str],
                           return_stdout=True)
      self.assertNotIn(PUBLIC_READ_JSON_ACL_TEXT,
                       self._strip_json_whitespace(acl))
      orig_acls.append(acl)

    # Set the ACL for the older version of the object to public-read.
    self.RunGsUtil(self._set_acl_prefix + ['public-read', v0_uri_str])
    # Check that the older version's ACL is public-read, but newer version
    # is not.
    acl = self.RunGsUtil(self._get_acl_prefix + [v0_uri_str],
                         return_stdout=True)
    self.assertIn(PUBLIC_READ_JSON_ACL_TEXT, self._strip_json_whitespace(acl))
    acl = self.RunGsUtil(self._get_acl_prefix + [v1_uri_str],
                         return_stdout=True)
    self.assertNotIn(PUBLIC_READ_JSON_ACL_TEXT,
                     self._strip_json_whitespace(acl))

    # Check that reading the ACL with the version-less URI returns the
    # original ACL (since the version-less URI means the current version).
    acl = self.RunGsUtil(self._get_acl_prefix + [uri.uri], return_stdout=True)
    self.assertEqual(acl, orig_acls[0])

  def _strip_json_whitespace(self, json_text):
    return re.sub(r'\s*', '', json_text)

  def testAclChangeWithUserId(self):
    change = aclhelpers.AclChange(self.USER_TEST_ID + ':r',
                                  scope_type=aclhelpers.ChangeType.USER)
    acl = self.sample_uri.get_acl()
    change.Execute(self.sample_uri, acl, self.logger)
    self._AssertHas(acl, 'READ', 'UserById', self.USER_TEST_ID)

  def testAclChangeWithGroupId(self):
    change = aclhelpers.AclChange(self.GROUP_TEST_ID + ':r',
                                  scope_type=aclhelpers.ChangeType.GROUP)
    acl = self.sample_uri.get_acl()
    change.Execute(self.sample_uri, acl, self.logger)
    self._AssertHas(acl, 'READ', 'GroupById', self.GROUP_TEST_ID)

  def testAclChangeWithUserEmail(self):
    change = aclhelpers.AclChange(self.USER_TEST_ADDRESS + ':r',
                                  scope_type=aclhelpers.ChangeType.USER)
    acl = self.sample_uri.get_acl()
    change.Execute(self.sample_uri, acl, self.logger)
    self._AssertHas(acl, 'READ', 'UserByEmail', self.USER_TEST_ADDRESS)

  def testAclChangeWithGroupEmail(self):
    change = aclhelpers.AclChange(self.GROUP_TEST_ADDRESS + ':fc',
                                  scope_type=aclhelpers.ChangeType.GROUP)
    acl = self.sample_uri.get_acl()
    change.Execute(self.sample_uri, acl, self.logger)
    self._AssertHas(acl, 'FULL_CONTROL', 'GroupByEmail',
                    self.GROUP_TEST_ADDRESS)

  def testAclChangeWithDomain(self):
    change = aclhelpers.AclChange(self.DOMAIN_TEST + ':READ',
                                  scope_type=aclhelpers.ChangeType.GROUP)
    acl = self.sample_uri.get_acl()
    change.Execute(str(self.sample_uri), acl, self.logger)
    self._AssertHas(acl, 'READ', 'GroupByDomain', self.DOMAIN_TEST)

  def testAclChangeWithAllUsers(self):
    change = aclhelpers.AclChange('AllUsers:WRITE',
                                  scope_type=aclhelpers.ChangeType.GROUP)
    acl = self.sample_uri.get_acl()
    change.Execute(str(self.sample_uri), acl, self.logger)
    self._AssertHas(acl, 'WRITE', 'AllUsers')

  def testAclChangeWithAllAuthUsers(self):
    change = aclhelpers.AclChange('AllAuthenticatedUsers:READ',
                                  scope_type=aclhelpers.ChangeType.GROUP)
    acl = self.sample_uri.get_acl()
    change.Execute(str(self.sample_uri), acl, self.logger)
    self._AssertHas(acl, 'READ', 'AllAuthenticatedUsers')
    remove = aclhelpers.AclDel('AllAuthenticatedUsers')
    remove.Execute(str(self.sample_uri), acl, self.logger)
    self._AssertHasNo(acl, 'READ', 'AllAuthenticatedUsers')

  def testAclDelWithUser(self):
    add = aclhelpers.AclChange(self.USER_TEST_ADDRESS + ':READ',
                               scope_type=aclhelpers.ChangeType.USER)
    acl = self.sample_uri.get_acl()
    add.Execute(str(self.sample_uri), acl, self.logger)
    self._AssertHas(acl, 'READ', 'UserByEmail', self.USER_TEST_ADDRESS)

    remove = aclhelpers.AclDel(self.USER_TEST_ADDRESS)
    remove.Execute(str(self.sample_uri), acl, self.logger)
    self._AssertHasNo(acl, 'READ', 'UserByEmail', self.USER_TEST_ADDRESS)

  def testAclDelWithGroup(self):
    add = aclhelpers.AclChange(self.USER_TEST_ADDRESS + ':READ',
                               scope_type=aclhelpers.ChangeType.GROUP)
    acl = self.sample_uri.get_acl()
    add.Execute(str(self.sample_uri), acl, self.logger)
    self._AssertHas(acl, 'READ', 'GroupByEmail', self.USER_TEST_ADDRESS)

    remove = aclhelpers.AclDel(self.USER_TEST_ADDRESS)
    remove.Execute(str(self.sample_uri), acl, self.logger)
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

  def _MakeScopeRegex(self, role, entity_type, email_address):
    template_regex = (r'\{.*"entity":\s*"%s-%s".*"role":\s*"%s".*\}' %
                      (entity_type, email_address, role))
    return re.compile(template_regex, flags=re.DOTALL)

  def testBucketAclChange(self):
    """Tests acl change on a bucket."""
    test_regex = self._MakeScopeRegex(
        'OWNER', 'user', self.USER_TEST_ADDRESS)
    json_text = self.RunGsUtil(
        self._get_acl_prefix + [suri(self.sample_uri)], return_stdout=True)
    self.assertNotRegexpMatches(json_text, test_regex)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-u', self.USER_TEST_ADDRESS+':fc', suri(self.sample_uri)])
    json_text = self.RunGsUtil(
        self._get_acl_prefix + [suri(self.sample_uri)], return_stdout=True)
    self.assertRegexpMatches(json_text, test_regex)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-d', self.USER_TEST_ADDRESS, suri(self.sample_uri)])
    json_text = self.RunGsUtil(
        self._get_acl_prefix + [suri(self.sample_uri)], return_stdout=True)
    self.assertNotRegexpMatches(json_text, test_regex)

  def testObjectAclChange(self):
    """Tests acl change on an object."""
    obj = self.CreateObject(bucket_uri=self.sample_uri, contents='something')
    test_regex = self._MakeScopeRegex(
        'READER', 'group', self.GROUP_TEST_ADDRESS)
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(obj)],
                               return_stdout=True)
    self.assertNotRegexpMatches(json_text, test_regex)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-g', self.GROUP_TEST_ADDRESS+':READ', suri(obj)])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(obj)],
                               return_stdout=True)
    self.assertRegexpMatches(json_text, test_regex)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-d', self.GROUP_TEST_ADDRESS, suri(obj)])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(obj)],
                               return_stdout=True)
    self.assertNotRegexpMatches(json_text, test_regex)

  def testMultithreadedAclChange(self, count=10):
    """Tests multi-threaded acl changing on several objects."""
    objects = []
    for i in range(count):
      objects.append(self.CreateObject(
          bucket_uri=self.sample_uri,
          contents='something {0}'.format(i)))

    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _ListObjects():
      stdout = self.RunGsUtil(['ls', suri(self.sample_uri)], return_stdout=True)
      lines = stdout.strip().split('\n')
      self.assertEqual(len(lines), count)
    _ListObjects()

    test_regex = self._MakeScopeRegex(
        'READER', 'group', self.GROUP_TEST_ADDRESS)
    json_texts = []
    for obj in objects:
      json_texts.append(self.RunGsUtil(
          self._get_acl_prefix + [suri(obj)], return_stdout=True))
    for json_text in json_texts:
      self.assertNotRegexpMatches(json_text, test_regex)

    uris = [suri(obj) for obj in objects]
    self.RunGsUtil(['-m', '-DD'] + self._ch_acl_prefix +
                   ['-g', self.GROUP_TEST_ADDRESS+':READ'] + uris)

    json_texts = []
    for obj in objects:
      json_texts.append(self.RunGsUtil(
          self._get_acl_prefix + [suri(obj)], return_stdout=True))
    for json_text in json_texts:
      self.assertRegexpMatches(json_text, test_regex)

  def testRecursiveChangeAcl(self):
    """Tests recursively changing ACLs on nested objects."""
    obj = self.CreateObject(bucket_uri=self.sample_uri, object_name='foo/bar',
                            contents='something')
    test_regex = self._MakeScopeRegex(
        'READER', 'group', self.GROUP_TEST_ADDRESS)
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(obj)],
                               return_stdout=True)
    self.assertNotRegexpMatches(json_text, test_regex)

    self.RunGsUtil(
        self._ch_acl_prefix +
        ['-R', '-g', self.GROUP_TEST_ADDRESS+':READ', suri(obj)[:-3]])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(obj)],
                               return_stdout=True)
    self.assertRegexpMatches(json_text, test_regex)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-d', self.GROUP_TEST_ADDRESS, suri(obj)])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(obj)],
                               return_stdout=True)
    self.assertNotRegexpMatches(json_text, test_regex)

  def testMultiVersionSupport(self):
    """Tests changing ACLs on multiple object versions."""
    bucket = self.CreateVersionedBucket()
    object_name = self.MakeTempName('obj')
    obj = self.CreateObject(
        bucket_uri=bucket, object_name=object_name, contents='One thing')
    # Create another on the same URI, giving us a second version.
    self.CreateObject(
        bucket_uri=bucket, object_name=object_name, contents='Another thing')

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _GetObjects():
      stdout = self.RunGsUtil(['ls', '-a', suri(obj)], return_stdout=True)
      lines = stdout.strip().split('\n')
      self.assertEqual(len(lines), 2)
      return lines

    obj_v1, obj_v2 = _GetObjects()

    test_regex = self._MakeScopeRegex(
        'READER', 'group', self.GROUP_TEST_ADDRESS)
    json_text = self.RunGsUtil(self._get_acl_prefix + [obj_v1],
                               return_stdout=True)
    self.assertNotRegexpMatches(json_text, test_regex)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-g', self.GROUP_TEST_ADDRESS+':READ', obj_v1])
    json_text = self.RunGsUtil(self._get_acl_prefix + [obj_v1],
                               return_stdout=True)
    self.assertRegexpMatches(json_text, test_regex)

    json_text = self.RunGsUtil(self._get_acl_prefix + [obj_v2],
                               return_stdout=True)
    self.assertNotRegexpMatches(json_text, test_regex)

  def testBadRequestAclChange(self):
    stdout, stderr = self.RunGsUtil(
        self._ch_acl_prefix +
        ['-u', 'invalid_$$@hello.com:R', suri(self.sample_uri)],
        return_stdout=True, return_stderr=True, expected_status=1)
    self.assertIn('BadRequestException', stderr)
    self.assertNotIn('Retrying', stdout)
    self.assertNotIn('Retrying', stderr)

  def testAclGetWithoutFullControl(self):
    object_uri = self.CreateObject(contents='foo')
    with self.SetAnonymousBotoCreds():
      stderr = self.RunGsUtil(self._get_acl_prefix + [suri(object_uri)],
                              return_stderr=True, expected_status=1)
      self.assertIn('Access denied', stderr)

  def testTooFewArgumentsFails(self):
    """Tests calling ACL commands with insufficient number of arguments."""
    # No arguments for get, but valid subcommand.
    stderr = self.RunGsUtil(self._get_acl_prefix, return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

    # No arguments for set, but valid subcommand.
    stderr = self.RunGsUtil(self._set_acl_prefix, return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

    # No arguments for ch, but valid subcommand.
    stderr = self.RunGsUtil(self._ch_acl_prefix, return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

    # Neither arguments nor subcommand.
    stderr = self.RunGsUtil(['acl'], return_stderr=True, expected_status=1)
    self.assertIn('command requires at least', stderr)


class TestAclOldAlias(TestAcl):
  _set_acl_prefix = ['setacl']
  _get_acl_prefix = ['getacl']
  _set_defacl_prefix = ['setdefacl']
  _ch_acl_prefix = ['chacl']
