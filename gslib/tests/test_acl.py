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

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

import itertools
import json
import os
import re

from gslib.commands import acl
from gslib.command import CreateOrGetGsutilLogger
from gslib.cs_api_map import ApiSelector
from gslib.exception import CommandException
from gslib.storage_url import StorageUrlFromString
import gslib.tests.testcase as testcase
from gslib.tests.testcase.integration_testcase import SkipForGS
from gslib.tests.testcase.integration_testcase import SkipForS3
from gslib.tests.testcase.integration_testcase import SkipForXML
from gslib.tests.util import GenerationFromURI as urigen
from gslib.tests.util import ObjectToURI as suri
from gslib.tests.util import SetBotoConfigForTest
from gslib.tests.util import SetEnvironmentForTest
from gslib.tests.util import unittest
from gslib.utils import acl_helper
from gslib.utils.constants import UTF8
from gslib.utils.retry_util import Retry
from gslib.utils.translation_helper import AclTranslation
from gslib.utils import shim_util
from gslib.tests.testcase import GsUtilIntegrationTestCase
from gslib.tests.util import RunOnlyOnParityTesting


from six import add_move, MovedModule

add_move(MovedModule('mock', 'mock', 'unittest.mock'))
from six.moves import mock

PUBLIC_READ_JSON_ACL_TEXT = '"entity":"allUsers","role":"READER"'


class TestAclBase(testcase.GsUtilIntegrationTestCase):
  """Integration test case base class for acl command."""

  _set_acl_prefix = ['acl', 'set']
  _get_acl_prefix = ['acl', 'get']
  _set_defacl_prefix = ['defacl', 'set']
  _ch_acl_prefix = ['acl', 'ch']

  _project_team = 'viewers'


@SkipForS3('Tests use GS ACL model.')
class TestAcl(TestAclBase):
  """Integration tests for acl command."""

  def setUp(self):
    super(TestAcl, self).setUp()
    self.sample_uri = self.CreateBucket()
    self.sample_url = StorageUrlFromString(str(self.sample_uri))
    self.logger = CreateOrGetGsutilLogger('acl')
    # Argument to acl ch -p must be the project number, not a name; create a
    # bucket to perform translation.
    self._project_number = self.json_api.GetBucket(
        self.CreateBucket().bucket_name, fields=['projectNumber']).projectNumber
    self._project_test_acl = '%s-%s' % (self._project_team,
                                        self._project_number)

  def test_set_invalid_acl_object(self):
    """Ensures that invalid content returns a bad request error."""
    obj_uri = suri(self.CreateObject(contents=b'foo'))
    inpath = self.CreateTempFile(contents=b'badAcl')
    stderr = self.RunGsUtil(self._set_acl_prefix + [inpath, obj_uri],
                            return_stderr=True,
                            expected_status=1)
    if self._use_gcloud_storage:
      error_text = 'Found invalid JSON/YAML'
    else:
      error_text = 'ArgumentException'
    self.assertIn(error_text, stderr)

  def test_set_invalid_acl_bucket(self):
    """Ensures that invalid content returns a bad request error."""
    bucket_uri = suri(self.CreateBucket())
    inpath = self.CreateTempFile(contents=b'badAcl')
    stderr = self.RunGsUtil(self._set_acl_prefix + [inpath, bucket_uri],
                            return_stderr=True,
                            expected_status=1)
    if self._use_gcloud_storage:
      error_text = 'Found invalid JSON/YAML'
    else:
      error_text = 'ArgumentException'
    self.assertIn(error_text, stderr)

  def test_set_xml_acl_json_api_object(self):
    """Ensures XML content returns a bad request error and migration warning."""
    obj_uri = suri(self.CreateObject(contents=b'foo'))
    inpath = self.CreateTempFile(contents=b'<ValidXml></ValidXml>')
    stderr = self.RunGsUtil(self._set_acl_prefix + [inpath, obj_uri],
                            return_stderr=True,
                            expected_status=1)

    if self._use_gcloud_storage:
      self.assertIn('Found invalid JSON/YAML', stderr)
      # XML not currently supported in gcloud storage.
    else:
      self.assertIn('ArgumentException', stderr)
      self.assertIn('XML ACL data provided', stderr)

  def test_set_xml_acl_json_api_bucket(self):
    """Ensures XML content returns a bad request error and migration warning."""
    bucket_uri = suri(self.CreateBucket())
    inpath = self.CreateTempFile(contents=b'<ValidXml></ValidXml>')
    stderr = self.RunGsUtil(self._set_acl_prefix + [inpath, bucket_uri],
                            return_stderr=True,
                            expected_status=1)
    if self._use_gcloud_storage:
      self.assertIn('Found invalid JSON/YAML', stderr)
      # XML not currently supported in gcloud storage.
    else:
      self.assertIn('ArgumentException', stderr)
      self.assertIn('XML ACL data provided', stderr)

  def test_set_valid_acl_object(self):
    """Tests setting a valid ACL on an object."""
    obj_uri = suri(self.CreateObject(contents=b'foo'))
    acl_string = self.RunGsUtil(self._get_acl_prefix + [obj_uri],
                                return_stdout=True)
    inpath = self.CreateTempFile(contents=acl_string.encode(UTF8))
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
    obj_uri = suri(self.CreateObject(contents=b'foo'))
    acl_string = self.RunGsUtil(self._get_acl_prefix + [obj_uri],
                                return_stdout=True)
    acl_string = re.sub(r'"role"', r'"role" \n', acl_string)
    acl_string = re.sub(r'"entity"', r'\n "entity"', acl_string)
    inpath = self.CreateTempFile(contents=acl_string.encode(UTF8))

    self.RunGsUtil(self._set_acl_prefix + [inpath, obj_uri])

  def test_set_valid_acl_bucket(self):
    """Ensures that valid canned and XML ACLs work with get/set."""
    if self._ServiceAccountCredentialsPresent():
      # See comments in _ServiceAccountCredentialsPresent
      return unittest.skip('Canned ACLs orphan service account permissions.')
    bucket_uri = suri(self.CreateBucket())
    acl_string = self.RunGsUtil(self._get_acl_prefix + [bucket_uri],
                                return_stdout=True)
    inpath = self.CreateTempFile(contents=acl_string.encode(UTF8))
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
    obj_uri = suri(self.CreateObject(contents=b'foo'))
    stderr = self.RunGsUtil(self._set_acl_prefix +
                            ['not-a-canned-acl', obj_uri],
                            return_stderr=True,
                            expected_status=1)
    if self._use_gcloud_storage:
      self.assertIn('AttributeError', stderr)
    else:
      self.assertIn('CommandException', stderr)
      self.assertIn('Invalid canned ACL', stderr)

  def test_set_valid_def_acl_bucket(self):
    """Ensures that valid default canned and XML ACLs works with get/set."""
    bucket_uri = self.CreateBucket()

    # Default ACL is project private.
    obj_uri1 = suri(self.CreateObject(bucket_uri=bucket_uri, contents=b'foo'))
    acl_string = self.RunGsUtil(self._get_acl_prefix + [obj_uri1],
                                return_stdout=True)

    # Change it to authenticated-read.
    self.RunGsUtil(
        self._set_defacl_prefix +
        ['authenticated-read', suri(bucket_uri)])

    # Default object ACL may take some time to propagate.
    @Retry(AssertionError, tries=5, timeout_secs=1)
    def _Check1():
      obj_uri2 = suri(self.CreateObject(bucket_uri=bucket_uri,
                                        contents=b'foo2'))
      acl_string2 = self.RunGsUtil(self._get_acl_prefix + [obj_uri2],
                                   return_stdout=True)
      self.assertNotEqual(acl_string, acl_string2)
      self.assertIn('allAuthenticatedUsers', acl_string2)

    _Check1()

    # Now change it back to the default via XML.
    inpath = self.CreateTempFile(contents=acl_string.encode(UTF8))
    self.RunGsUtil(self._set_defacl_prefix + [inpath, suri(bucket_uri)])

    # Default object ACL may take some time to propagate.
    @Retry(AssertionError, tries=5, timeout_secs=1)
    def _Check2():
      obj_uri3 = suri(self.CreateObject(bucket_uri=bucket_uri,
                                        contents=b'foo3'))
      acl_string3 = self.RunGsUtil(self._get_acl_prefix + [obj_uri3],
                                   return_stdout=True)
      self.assertEqual(acl_string, acl_string3)

    _Check2()

  def test_acl_set_version_specific_uri(self):
    """Tests setting an ACL on a specific version of an object."""
    bucket_uri = self.CreateVersionedBucket()
    # Create initial object version.
    uri = self.CreateObject(bucket_uri=bucket_uri, contents=b'data')
    # Create a second object version.
    inpath = self.CreateTempFile(contents=b'def')
    self.RunGsUtil(['cp', inpath, uri.uri])

    # Find out the two object version IDs.
    lines = self.AssertNObjectsInBucket(bucket_uri, 2, versioned=True)
    v0_uri_str, v1_uri_str = lines[0], lines[1]

    # Check that neither version currently has public-read permission
    # (default ACL is project-private).
    orig_acls = []
    for uri_str in (v0_uri_str, v1_uri_str):
      acl = self.RunGsUtil(self._get_acl_prefix + [uri_str], return_stdout=True)
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

  def _MakeScopeRegex(self, role, entity_type, email_address):
    template_regex = (r'\{.*"entity":\s*"%s-%s".*"role":\s*"%s".*\}' %
                      (entity_type, email_address, role))
    return re.compile(template_regex, flags=re.DOTALL)

  def _MakeProjectScopeRegex(self, role, project_team, project_number):
    template_regex = (
        r'\{.*"entity":\s*"project-%s-%s",\s*"projectTeam":\s*\{\s*"'
        r'projectNumber":\s*"%s",\s*"team":\s*"%s"\s*\},\s*"role":\s*"%s".*\}' %
        (project_team, project_number, project_number, project_team, role))

    return re.compile(template_regex, flags=re.DOTALL)

  def testAclChangeWithUserId(self):
    test_regex = self._MakeScopeRegex('READER', 'user', self.USER_TEST_ADDRESS)
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertNotRegex(json_text, test_regex)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-u', self.USER_TEST_ID +
                    ':r', suri(self.sample_uri)])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertRegex(json_text, test_regex)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-d', self.USER_TEST_ADDRESS,
                    suri(self.sample_uri)])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertNotRegex(json_text, test_regex)

  def testAclChangeWithGroupId(self):
    test_regex = self._MakeScopeRegex('READER', 'group',
                                      self.GROUP_TEST_ADDRESS)
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertNotRegex(json_text, test_regex)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-g', self.GROUP_TEST_ID + ':r',
                    suri(self.sample_uri)])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertRegex(json_text, test_regex)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-d', self.GROUP_TEST_ADDRESS,
                    suri(self.sample_uri)])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertNotRegex(json_text, test_regex)

  def testAclChangeWithUserEmail(self):
    test_regex = self._MakeScopeRegex('READER', 'user', self.USER_TEST_ADDRESS)
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertNotRegex(json_text, test_regex)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-u', self.USER_TEST_ADDRESS + ':r',
                    suri(self.sample_uri)])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertRegex(json_text, test_regex)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-d', self.USER_TEST_ADDRESS,
                    suri(self.sample_uri)])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertNotRegex(json_text, test_regex)

  def testAclChangeWithGroupEmail(self):
    test_regex = self._MakeScopeRegex('OWNER', 'group', self.GROUP_TEST_ADDRESS)
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertNotRegex(json_text, test_regex)

    self.RunGsUtil(
        self._ch_acl_prefix +
        ['-g', self.GROUP_TEST_ADDRESS +
         ':fc', suri(self.sample_uri)])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertRegex(json_text, test_regex)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-d', self.GROUP_TEST_ADDRESS,
                    suri(self.sample_uri)])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertNotRegex(json_text, test_regex)

  def testAclChangeWithDomain(self):
    test_regex = self._MakeScopeRegex('READER', 'domain', self.DOMAIN_TEST)
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertNotRegex(json_text, test_regex)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-g', self.DOMAIN_TEST +
                    ':r', suri(self.sample_uri)])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertRegex(json_text, test_regex)

    self.RunGsUtil(
        self._ch_acl_prefix +
        ['-d', self.DOMAIN_TEST, suri(self.sample_uri)])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertNotRegex(json_text, test_regex)

  @SkipForXML('XML API does not support project scopes.')
  def testAclChangeWithProjectOwners(self):
    test_regex = self._MakeProjectScopeRegex('WRITER', self._project_team,
                                             self._project_number)
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertNotRegex(json_text, test_regex)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-p', self._project_test_acl + ':w',
                    suri(self.sample_uri)])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertRegex(json_text, test_regex)

  def testAclChangeWithAllUsers(self):
    test_regex = re.compile(
        r'\{.*"entity":\s*"allUsers".*"role":\s*"WRITER".*\}', flags=re.DOTALL)
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertNotRegex(json_text, test_regex)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-g', 'allusers' +
                    ':w', suri(self.sample_uri)])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertRegex(json_text, test_regex)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-d', 'allusers', suri(self.sample_uri)])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertNotRegex(json_text, test_regex)

  def testAclChangeWithAllAuthUsers(self):
    test_regex = re.compile(
        r'\{.*"entity":\s*"allAuthenticatedUsers".*"role":\s*"READER".*\}',
        flags=re.DOTALL)
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertNotRegex(json_text, test_regex)

    self.RunGsUtil(
        self._ch_acl_prefix +
        ['-g', 'allauthenticatedusers' +
         ':r', suri(self.sample_uri)])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertRegex(json_text, test_regex)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-d', 'allauthenticatedusers',
                    suri(self.sample_uri)])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertNotRegex(json_text, test_regex)

  def testBucketAclChange(self):
    """Tests acl change on a bucket."""
    test_regex = self._MakeScopeRegex('OWNER', 'user', self.USER_TEST_ADDRESS)
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertNotRegex(json_text, test_regex)

    self.RunGsUtil(
        self._ch_acl_prefix +
        ['-u', self.USER_TEST_ADDRESS +
         ':fc', suri(self.sample_uri)])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                               return_stdout=True)
    self.assertRegex(json_text, test_regex)

    test_regex2 = self._MakeScopeRegex('WRITER', 'user', self.USER_TEST_ADDRESS)
    s1, s2 = self.RunGsUtil(
        self._ch_acl_prefix +
        ['-u', self.USER_TEST_ADDRESS + ':w',
         suri(self.sample_uri)],
        return_stderr=True,
        return_stdout=True)

    json_text2 = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                                return_stdout=True)
    self.assertRegex(json_text2, test_regex2)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-d', self.USER_TEST_ADDRESS,
                    suri(self.sample_uri)])

    json_text3 = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                                return_stdout=True)
    self.assertNotRegex(json_text3, test_regex)

  def testProjectAclChangesOnBucket(self):
    """Tests project entity acl changes on a bucket."""
    if self.test_api == ApiSelector.XML:
      stderr = self.RunGsUtil(
          self._ch_acl_prefix +
          ['-p', self._project_test_acl + ':w',
           suri(self.sample_uri)],
          expected_status=1,
          return_stderr=True)
      self.assertIn(('CommandException: XML API does not support project'
                     ' scopes, cannot translate ACL.'), stderr)
    else:
      test_regex = self._MakeProjectScopeRegex('WRITER', self._project_team,
                                               self._project_number)
      self.RunGsUtil(
          self._ch_acl_prefix +
          ['-p', self._project_test_acl +
           ':w', suri(self.sample_uri)])
      json_text = self.RunGsUtil(self._get_acl_prefix + [suri(self.sample_uri)],
                                 return_stdout=True)

      self.assertRegex(json_text, test_regex)

      self.RunGsUtil(self._ch_acl_prefix +
                     ['-d', self._project_test_acl,
                      suri(self.sample_uri)])

      json_text2 = self.RunGsUtil(self._get_acl_prefix +
                                  [suri(self.sample_uri)],
                                  return_stdout=True)
      self.assertNotRegex(json_text2, test_regex)

  def testObjectAclChange(self):
    """Tests acl change on an object."""
    obj = self.CreateObject(bucket_uri=self.sample_uri, contents=b'something')
    self.AssertNObjectsInBucket(self.sample_uri, 1)

    test_regex = self._MakeScopeRegex('READER', 'group',
                                      self.GROUP_TEST_ADDRESS)
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(obj)],
                               return_stdout=True)
    self.assertNotRegex(json_text, test_regex)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-g', self.GROUP_TEST_ADDRESS +
                    ':READ', suri(obj)])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(obj)],
                               return_stdout=True)
    self.assertRegex(json_text, test_regex)

    test_regex2 = self._MakeScopeRegex('OWNER', 'group',
                                       self.GROUP_TEST_ADDRESS)
    self.RunGsUtil(self._ch_acl_prefix +
                   ['-g', self.GROUP_TEST_ADDRESS + ':OWNER',
                    suri(obj)])
    json_text2 = self.RunGsUtil(self._get_acl_prefix + [suri(obj)],
                                return_stdout=True)
    self.assertRegex(json_text2, test_regex2)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-d', self.GROUP_TEST_ADDRESS,
                    suri(obj)])
    json_text3 = self.RunGsUtil(self._get_acl_prefix + [suri(obj)],
                                return_stdout=True)
    self.assertNotRegex(json_text3, test_regex2)

    all_auth_regex = re.compile(
        r'\{.*"entity":\s*"allAuthenticatedUsers".*"role":\s*"OWNER".*\}',
        flags=re.DOTALL)

    self.RunGsUtil(self._ch_acl_prefix + ['-g', 'AllAuth:O', suri(obj)])
    json_text4 = self.RunGsUtil(self._get_acl_prefix + [suri(obj)],
                                return_stdout=True)
    self.assertRegex(json_text4, all_auth_regex)

  def testObjectAclChangeAllUsers(self):
    """Tests acl ch AllUsers:R on an object."""
    obj = self.CreateObject(bucket_uri=self.sample_uri, contents=b'something')
    self.AssertNObjectsInBucket(self.sample_uri, 1)

    all_users_regex = re.compile(
        r'\{.*"entity":\s*"allUsers".*"role":\s*"READER".*\}', flags=re.DOTALL)
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(obj)],
                               return_stdout=True)
    self.assertNotRegex(json_text, all_users_regex)

    self.RunGsUtil(self._ch_acl_prefix + ['-g', 'AllUsers:R', suri(obj)])
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(obj)],
                               return_stdout=True)
    self.assertRegex(json_text, all_users_regex)

  def testSeekAheadAcl(self):
    """Tests seek-ahead iterator with ACL sub-commands."""
    object_uri = self.CreateObject(contents=b'foo')
    # Get the object's current ACL for application via set.
    current_acl = self.RunGsUtil(['acl', 'get', suri(object_uri)],
                                 return_stdout=True)
    current_acl_file = self.CreateTempFile(contents=current_acl.encode(UTF8))

    with SetBotoConfigForTest([('GSUtil', 'task_estimation_threshold', '1'),
                               ('GSUtil', 'task_estimation_force', 'True')]):
      stderr = self.RunGsUtil(
          ['-m', 'acl', 'ch', '-u', 'AllUsers:R',
           suri(object_uri)],
          return_stderr=True)
      self.assertIn('Estimated work for this command: objects: 1\n', stderr)

      stderr = self.RunGsUtil(
          ['-m', 'acl', 'set', current_acl_file,
           suri(object_uri)],
          return_stderr=True)
      self.assertIn('Estimated work for this command: objects: 1\n', stderr)

    with SetBotoConfigForTest([('GSUtil', 'task_estimation_threshold', '0'),
                               ('GSUtil', 'task_estimation_force', 'True')]):
      stderr = self.RunGsUtil(
          ['-m', 'acl', 'ch', '-u', 'AllUsers:R',
           suri(object_uri)],
          return_stderr=True)
      self.assertNotIn('Estimated work', stderr)

  def testMultithreadedAclChange(self, count=10):
    """Tests multi-threaded acl changing on several objects."""
    objects = []
    for i in range(count):
      objects.append(
          self.CreateObject(bucket_uri=self.sample_uri,
                            contents='something {0}'.format(i).encode('ascii')))

    self.AssertNObjectsInBucket(self.sample_uri, count)

    test_regex = self._MakeScopeRegex('READER', 'group',
                                      self.GROUP_TEST_ADDRESS)
    json_texts = []
    for obj in objects:
      json_texts.append(
          self.RunGsUtil(self._get_acl_prefix + [suri(obj)],
                         return_stdout=True))
    for json_text in json_texts:
      self.assertNotRegex(json_text, test_regex)

    uris = [suri(obj) for obj in objects]
    self.RunGsUtil(['-m', '-DD'] + self._ch_acl_prefix +
                   ['-g', self.GROUP_TEST_ADDRESS + ':READ'] + uris)

    json_texts = []
    for obj in objects:
      json_texts.append(
          self.RunGsUtil(self._get_acl_prefix + [suri(obj)],
                         return_stdout=True))
    for json_text in json_texts:
      self.assertRegex(json_text, test_regex)

  def testRecursiveChangeAcl(self):
    """Tests recursively changing ACLs on nested objects."""
    obj = self.CreateObject(bucket_uri=self.sample_uri,
                            object_name='foo/bar',
                            contents=b'something')
    self.AssertNObjectsInBucket(self.sample_uri, 1)

    test_regex = self._MakeScopeRegex('READER', 'group',
                                      self.GROUP_TEST_ADDRESS)
    json_text = self.RunGsUtil(self._get_acl_prefix + [suri(obj)],
                               return_stdout=True)
    self.assertNotRegex(json_text, test_regex)

    @Retry(AssertionError, tries=5, timeout_secs=1)
    def _AddAcl():
      self.RunGsUtil(
          self._ch_acl_prefix +
          ['-R', '-g', self.GROUP_TEST_ADDRESS + ':READ',
           suri(obj)[:-3]])
      json_text = self.RunGsUtil(self._get_acl_prefix + [suri(obj)],
                                 return_stdout=True)
      self.assertRegex(json_text, test_regex)

    _AddAcl()

    @Retry(AssertionError, tries=5, timeout_secs=1)
    def _DeleteAcl():
      # Make sure we treat grant addresses case insensitively.
      delete_grant = self.GROUP_TEST_ADDRESS.upper()
      self.RunGsUtil(self._ch_acl_prefix + ['-d', delete_grant, suri(obj)])
      json_text = self.RunGsUtil(self._get_acl_prefix + [suri(obj)],
                                 return_stdout=True)
      self.assertNotRegex(json_text, test_regex)

    _DeleteAcl()

  def testMultiVersionSupport(self):
    """Tests changing ACLs on multiple object versions."""
    bucket = self.CreateVersionedBucket()
    object_name = self.MakeTempName('obj')
    obj1_uri = self.CreateObject(bucket_uri=bucket,
                                 object_name=object_name,
                                 contents=b'One thing')
    # Create another on the same URI, giving us a second version.
    self.CreateObject(bucket_uri=bucket,
                      object_name=object_name,
                      contents=b'Another thing',
                      gs_idempotent_generation=urigen(obj1_uri))

    lines = self.AssertNObjectsInBucket(bucket, 2, versioned=True)

    obj_v1, obj_v2 = lines[0], lines[1]

    test_regex = self._MakeScopeRegex('READER', 'group',
                                      self.GROUP_TEST_ADDRESS)
    json_text = self.RunGsUtil(self._get_acl_prefix + [obj_v1],
                               return_stdout=True)
    self.assertNotRegex(json_text, test_regex)

    self.RunGsUtil(self._ch_acl_prefix +
                   ['-g', self.GROUP_TEST_ADDRESS + ':READ', obj_v1])
    json_text = self.RunGsUtil(self._get_acl_prefix + [obj_v1],
                               return_stdout=True)
    self.assertRegex(json_text, test_regex)

    json_text = self.RunGsUtil(self._get_acl_prefix + [obj_v2],
                               return_stdout=True)
    self.assertNotRegex(json_text, test_regex)

  def testBadRequestAclChange(self):
    stdout, stderr = self.RunGsUtil(
        self._ch_acl_prefix +
        ['-u', 'invalid_$$@hello.com:R',
         suri(self.sample_uri)],
        return_stdout=True,
        return_stderr=True,
        expected_status=1)
    if self._use_gcloud_storage:
      self.assertIn('HTTPError', stderr)
    else:
      self.assertIn('BadRequestException', stderr)
    self.assertNotIn('Retrying', stdout)
    self.assertNotIn('Retrying', stderr)

  def testAclGetWithoutFullControl(self):
    object_uri = self.CreateObject(contents=b'foo')
    expected_error_regex = r'Anonymous \S+ do(es)? not have'
    with self.SetAnonymousBotoCreds():
      stderr = self.RunGsUtil(self._get_acl_prefix + [suri(object_uri)],
                              return_stderr=True,
                              expected_status=1)
      self.assertRegex(stderr, expected_error_regex)

  def testTooFewArgumentsFails(self):
    """Tests calling ACL commands with insufficient number of arguments."""
    # No arguments for get, but valid subcommand.
    stderr = self.RunGsUtil(self._get_acl_prefix,
                            return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

    # No arguments for set, but valid subcommand.
    stderr = self.RunGsUtil(self._set_acl_prefix,
                            return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

    # No arguments for ch, but valid subcommand.
    stderr = self.RunGsUtil(self._ch_acl_prefix,
                            return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

    # Neither arguments nor subcommand.
    stderr = self.RunGsUtil(['acl'], return_stderr=True, expected_status=1)
    self.assertIn('command requires at least', stderr)

  def testMinusF(self):
    """Tests -f option to continue after failure."""
    bucket_uri = self.CreateBucket()
    obj_uri = suri(
        self.CreateObject(bucket_uri=bucket_uri,
                          object_name='foo',
                          contents=b'foo'))
    acl_string = self.RunGsUtil(self._get_acl_prefix + [obj_uri],
                                return_stdout=True)
    self.RunGsUtil(['-d'] + self._set_acl_prefix +
                   ['-f', 'public-read', obj_uri + 'foo2', obj_uri],
                   expected_status=1)
    acl_string2 = self.RunGsUtil(self._get_acl_prefix + [obj_uri],
                                 return_stdout=True)
    self.assertNotEqual(acl_string, acl_string2)


class TestS3CompatibleAcl(TestAclBase):
  """ACL integration tests that work for s3 and gs URLs."""

  def testAclObjectGetSet(self):
    bucket_uri = self.CreateBucket()
    obj_uri = self.CreateObject(bucket_uri=bucket_uri, contents=b'foo')
    self.AssertNObjectsInBucket(bucket_uri, 1)

    stdout = self.RunGsUtil(self._get_acl_prefix + [suri(obj_uri)],
                            return_stdout=True)
    set_contents = self.CreateTempFile(contents=stdout.encode(UTF8))
    self.RunGsUtil(self._set_acl_prefix + [set_contents, suri(obj_uri)])

  def testAclBucketGetSet(self):
    bucket_uri = self.CreateBucket()
    stdout = self.RunGsUtil(self._get_acl_prefix + [suri(bucket_uri)],
                            return_stdout=True)
    set_contents = self.CreateTempFile(contents=stdout.encode(UTF8))
    self.RunGsUtil(self._set_acl_prefix + [set_contents, suri(bucket_uri)])


@SkipForGS('S3 ACLs accept XML and should not cause an XML warning.')
class TestS3OnlyAcl(TestAclBase):
  """ACL integration tests that work only for s3 URLs."""

  # TODO: Format all test case names consistently.
  def test_set_xml_acl(self):
    """Ensures XML content does not return an XML warning for S3."""
    obj_uri = suri(self.CreateObject(contents=b'foo'))
    inpath = self.CreateTempFile(contents=b'<ValidXml></ValidXml>')
    stderr = self.RunGsUtil(self._set_acl_prefix + [inpath, obj_uri],
                            return_stderr=True,
                            expected_status=1)
    self.assertIn('BadRequestException', stderr)
    self.assertNotIn('XML ACL data provided', stderr)

  def test_set_xml_acl_bucket(self):
    """Ensures XML content does not return an XML warning for S3."""
    bucket_uri = suri(self.CreateBucket())
    inpath = self.CreateTempFile(contents=b'<ValidXml></ValidXml>')
    stderr = self.RunGsUtil(self._set_acl_prefix + [inpath, bucket_uri],
                            return_stderr=True,
                            expected_status=1)
    self.assertIn('BadRequestException', stderr)
    self.assertNotIn('XML ACL data provided', stderr)


class TestAclOldAlias(TestAcl):
  _set_acl_prefix = ['setacl']
  _get_acl_prefix = ['getacl']
  _set_defacl_prefix = ['setdefacl']
  _ch_acl_prefix = ['chacl']


class TestAclShim(testcase.ShimUnitTestBase):

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_translates_acl_get_object(self):
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand('acl', ['get', 'gs://bucket/object'],
                                           return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(('Gcloud Storage Command: {} storage objects describe'
                       ' --format=multi(acl:format=json)'
                       ' gs://bucket/object').format(
                           shim_util._get_gcloud_binary_path('fake_dir')),
                      info_lines)

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_translates_acl_get_bucket(self):
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand('acl', ['get', 'gs://bucket'],
                                           return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(('Gcloud Storage Command: {} storage buckets describe'
                       ' --format=multi(acl:format=json)'
                       ' gs://bucket').format(
                           shim_util._get_gcloud_binary_path('fake_dir')),
                      info_lines)

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_translates_acl_set_object(self):
    inpath = self.CreateTempFile()
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand(
            'acl', ['set', inpath, 'gs://bucket/object'],
            return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(('Gcloud Storage Command: {} storage objects update'
                       ' --acl-file={}').format(
                           shim_util._get_gcloud_binary_path('fake_dir'),
                           inpath), info_lines)

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_translates_acl_set_bucket(self):
    inpath = self.CreateTempFile()
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand('acl',
                                           ['set', inpath, 'gs://bucket'],
                                           return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(('Gcloud Storage Command: {} storage buckets update'
                       ' --acl-file={} gs://bucket').format(
                           shim_util._get_gcloud_binary_path('fake_dir'),
                           inpath), info_lines)

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_translates_predefined_acl_set_object(self):
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand(
            'acl', ['set', 'private', 'gs://bucket/object'],
            return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(('Gcloud Storage Command: {} storage objects update'
                       ' --predefined-acl=private gs://bucket/object'.format(
                           shim_util._get_gcloud_binary_path('fake_dir'))),
                      info_lines)

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_translates_predefined_acl_set_bucket(self):
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand('acl',
                                           ['set', 'private', 'gs://bucket'],
                                           return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(('Gcloud Storage Command: {} storage buckets update'
                       ' --predefined-acl=private gs://bucket').format(
                           shim_util._get_gcloud_binary_path('fake_dir')),
                      info_lines)

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_translates_xml_predefined_acl_for_set(self):
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand(
            'acl', ['set', 'public-read', 'gs://bucket'],
            return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(('Gcloud Storage Command: {} storage buckets update'
                       ' --predefined-acl=publicRead gs://bucket').format(
                           shim_util._get_gcloud_binary_path('fake_dir')),
                      info_lines)

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_translates_acl_set_multiple_buckets_urls(self):
    inpath = self.CreateTempFile()
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand('acl', [
            'set', '-f', inpath, 'gs://bucket', 'gs://bucket1', 'gs://bucket2'
        ],
                                           return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(('Gcloud Storage Command: {} storage buckets update'
                       ' --acl-file={} --continue-on-error'
                       ' gs://bucket gs://bucket1 gs://bucket2').format(
                           shim_util._get_gcloud_binary_path('fake_dir'),
                           inpath), info_lines)

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_translates_acl_set_multiple_objects_urls(self):
    inpath = self.CreateTempFile()
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand('acl', [
            'set', '-f', inpath, 'gs://bucket/object', 'gs://bucket/object1',
            'gs://bucket/object2'
        ],
                                           return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(('Gcloud Storage Command: {} storage objects update'
                       ' --acl-file={} --continue-on-error gs://bucket/object'
                       ' gs://bucket/object1 gs://bucket/object2').format(
                           shim_util._get_gcloud_binary_path('fake_dir'),
                           inpath), info_lines)

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_translates_acl_set_multiple_buckets_urls_recursive_all_versions(
      self):
    inpath = self.CreateTempFile()
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand('acl', [
            'set', '-r', '-a', inpath, 'gs://bucket', 'gs://bucket1/o',
            'gs://bucket2'
        ],
                                           return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(('Gcloud Storage Command: {} storage objects update'
                       ' --acl-file={} --recursive --all-versions gs://bucket'
                       ' gs://bucket1/o gs://bucket2').format(
                           shim_util._get_gcloud_binary_path('fake_dir'),
                           inpath), info_lines)

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_translates_acl_set_mix_buckets_and_objects_raises_error(self):
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        with self.assertRaisesRegex(
            CommandException,
            'Cannot operate on a mix of buckets and objects.'):
          self.RunCommand(
              'acl', ['set', 'acl-file', 'gs://bucket', 'gs://bucket1/object'])

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_changes_bucket_acls_for_user(self):
    inpath = self.CreateTempFile()
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand(
            'acl',
            ['ch', '-u', 'user@example.com:R', 'gs://bucket1', 'gs://bucket2'],
            return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(
            ('Gcloud Storage Command: {} storage buckets update'
             ' --add-acl-grant entity=user-user@example.com,role=READER'
             ' gs://bucket1 gs://bucket2').format(
                 shim_util._get_gcloud_binary_path('fake_dir'),
                 inpath), info_lines)

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_changes_object_acls_for_user(self):
    inpath = self.CreateTempFile()
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand('acl', [
            'ch', '-u', 'user@example.com:R', 'gs://bucket1/o', 'gs://bucket2/o'
        ],
                                           return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(
            ('Gcloud Storage Command: {} storage objects update'
             ' --add-acl-grant entity=user-user@example.com,role=READER'
             ' gs://bucket1/o gs://bucket2/o').format(
                 shim_util._get_gcloud_binary_path('fake_dir'),
                 inpath), info_lines)

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_raises_error_for_mix_of_objects_and_buckets(self):
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        with self.assertRaisesRegex(
            CommandException,
            'Cannot operate on a mix of buckets and objects.'):
          self.RunCommand('acl', ['ch', 'gs://bucket', 'gs://bucket1/object'])

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_changes_acls_for_group(self):
    inpath = self.CreateTempFile()
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand(
            'acl', ['ch', '-g', 'group@example.com:W', 'gs://bucket1/o'],
            return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(
            ('Gcloud Storage Command: {} storage objects update'
             ' --add-acl-grant entity=group-group@example.com,role=WRITER'
             ' gs://bucket1/o').format(
                 shim_util._get_gcloud_binary_path('fake_dir'),
                 inpath), info_lines)

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_changes_acls_for_domain(self):
    inpath = self.CreateTempFile()
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand(
            'acl', ['ch', '-g', 'example.com:O', 'gs://bucket1/o'],
            return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(('Gcloud Storage Command: {} storage objects update'
                       ' --add-acl-grant entity=domain-example.com,role=OWNER'
                       ' gs://bucket1/o').format(
                           shim_util._get_gcloud_binary_path('fake_dir'),
                           inpath), info_lines)

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_changes_acls_for_project(self):
    inpath = self.CreateTempFile()
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand(
            'acl', ['ch', '-p', 'owners-example:O', 'gs://bucket1/o'],
            return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(
            ('Gcloud Storage Command: {} storage objects update'
             ' --add-acl-grant entity=project-owners-example,role=OWNER'
             ' gs://bucket1/o').format(
                 shim_util._get_gcloud_binary_path('fake_dir'),
                 inpath), info_lines)

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_changes_acls_for_all_users(self):
    inpath = self.CreateTempFile()
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        # Non-exhaustive set of strings allowed by gsutil's regex.
        for identifier in ['all', 'allUsers', 'AllUsers']:
          mock_log_handler = self.RunCommand(
              'acl', ['ch', '-g', identifier + ':O', 'gs://bucket1/o'],
              return_log_handler=True)
          info_lines = '\n'.join(mock_log_handler.messages['info'])
          self.assertIn(('Gcloud Storage Command: {} storage objects update'
                         ' --add-acl-grant entity=allUsers,role=OWNER'
                         ' gs://bucket1/o').format(
                             shim_util._get_gcloud_binary_path('fake_dir'),
                             inpath), info_lines)

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_changes_acls_for_all_authenticated_users(self):
    inpath = self.CreateTempFile()
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        # Non-exhaustive set of strings allowed by gsutil's regex.
        for identifier in [
            'allauth', 'allAuthenticatedUsers', 'AllAuthenticatedUsers'
        ]:
          mock_log_handler = self.RunCommand(
              'acl', ['ch', '-g', identifier + ':O', 'gs://bucket1/o'],
              return_log_handler=True)
          info_lines = '\n'.join(mock_log_handler.messages['info'])
          self.assertIn(
              ('Gcloud Storage Command: {} storage objects update'
               ' --add-acl-grant entity=allAuthenticatedUsers,role=OWNER'
               ' gs://bucket1/o').format(
                   shim_util._get_gcloud_binary_path('fake_dir'),
                   inpath), info_lines)

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_deletes_acls(self):
    inpath = self.CreateTempFile()
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        # Non-exhaustive set of strings allowed by gsutil's regex.
        mock_log_handler = self.RunCommand('acl', [
            'ch', '-d', 'user@example.com', '-d', 'user1@example.com',
            'gs://bucket1/o'
        ],
                                           return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(('Gcloud Storage Command: {} storage objects update'
                       ' --remove-acl-grant user@example.com'
                       ' --remove-acl-grant user1@example.com'
                       ' gs://bucket1/o').format(
                           shim_util._get_gcloud_binary_path('fake_dir'),
                           inpath), info_lines)

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_removes_acls_for_all_users(self):
    inpath = self.CreateTempFile()
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        # Non-exhaustive set of strings allowed by gsutil's regex.
        for identifier in ['all', 'allUsers', 'AllUsers']:
          mock_log_handler = self.RunCommand(
              'acl', ['ch', '-d', identifier, 'gs://bucket1/o'],
              return_log_handler=True)
          info_lines = '\n'.join(mock_log_handler.messages['info'])
          self.assertIn(('Gcloud Storage Command: {} storage objects update'
                         ' --remove-acl-grant AllUsers'
                         ' gs://bucket1/o').format(
                             shim_util._get_gcloud_binary_path('fake_dir'),
                             inpath), info_lines)

  @mock.patch.object(acl.AclCommand, 'RunCommand', new=mock.Mock())
  def test_shim_removes_acls_for_all_authenticated_users(self):
    inpath = self.CreateTempFile()
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        # Non-exhaustive set of strings allowed by gsutil's regex.
        for identifier in [
            'allauth', 'allAuthenticatedUsers', 'AllAuthenticatedUsers'
        ]:
          mock_log_handler = self.RunCommand(
              'acl', ['ch', '-d', identifier, 'gs://bucket1/o'],
              return_log_handler=True)
          info_lines = '\n'.join(mock_log_handler.messages['info'])
          self.assertIn(('Gcloud Storage Command: {} storage objects update'
                         ' --remove-acl-grant AllAuthenticatedUsers'
                         ' gs://bucket1/o').format(
                             shim_util._get_gcloud_binary_path('fake_dir'),
                             inpath), info_lines)


@RunOnlyOnParityTesting
class AclBase(GsUtilIntegrationTestCase):
    
    def setUp(self):
        super(AclBase, self).setUp()
        self.private_project_regex_bucket = [re.compile(
            '\\{.*"entity":\\s*".*project-owners.*".*"role":\\s*"OWNER".*\\}'
            ), re.compile(
            '\\{.*"entity":\\s*".*project-editors.*".*"role":\\s*"OWNER".*\\}'
            ), re.compile(
            '\\{.*"entity":\\s*".*project-viewers.*".*"role":\\s*"READER".*\\}')]
        self.private_project_regex_object = [re.compile(
            '\\{.*"entity":\\s*".*project-owners.*".*"role":\\s*"OWNER".*\\}'
            ), re.compile(
            '\\{.*"entity":\\s*".*project-editors.*".*"role":\\s*"OWNER".*\\}'
            ), re.compile(
            '\\{.*"entity":\\s*".*project-viewers.*".*"role":\\s*"READER".*\\}'
            ), re.compile(
            '\\{.*"entity":\\s*"user.*".*"role":\\s*"OWNER".*\\}')]
        self.private_regex_object = [re.compile(
            '\\{.*"entity":\\s*"user.*".*"role":\\s*"OWNER".*\\}')]
        self.private_regex_bucket = [re.compile(
            '\\{.*"entity":\\s*".*project-owners.*".*"role":\\s*"OWNER".*\\}')]
        self.public_read_regex_object = [re.compile(
            '\\{.*"entity":\\s*"user.*".*"role":\\s*"OWNER".*\\}'), re.
            compile('\\{.*"entity":\\s*"allUsers".*"role":\\s*"READER".*\\}')]
        self.public_read_regex_bucket = [re.compile(
            '\\{.*"entity":\\s*".*project-owners.*".*"role":\\s*"OWNER".*\\}'
            ), re.compile(
            '\\{.*"entity":\\s*"allUsers".*"role":\\s*"READER".*\\}')]
        self.bucket_owner_full_control_regex = [re.compile(
            '\\{.*"entity":\\s*"user.*".*"role":\\s*"OWNER".*\\}'), re.
            compile(
            '\\{.*"entity":\\s*".*project-owners.*".*"role":\\s*"OWNER".*\\}')]
        self.bucket_owner_read_regex = [re.compile(
            '\\{.*"entity":\\s*"user.*".*"role":\\s*"OWNER".*\\}'), re.
            compile(
            '\\{.*"entity":\\s*".*project-owners.*".*"role":\\s*"READER".*\\}')]

    def setup_bucket_with_predefined_acl(self, predefined_acl=None):
        bucket_name = suri(self.CreateBucket())
        self.RunGsUtil(["acl", "set", predefined_acl, bucket_name])
        return bucket_name
    
    def setup_object_with_predefined_acl(self, predefined_acl=None):
        object_name = suri(self.CreateObject(contents=b'foo'))
        self.RunGsUtil(["acl", "set", predefined_acl, object_name])
        return object_name
    
    def setup_bucket_with_versioned_objects(self, provider=None):
        bucket = (self.CreateVersionedBucket(provider=provider))
        url = self.CreateObject(contents=b'foobar1', object_name="obj.txt", bucket_uri=bucket)
        self.CreateObject(contents=b'foobar2', object_name="obj.txt", bucket_uri=bucket, gs_idempotent_generation=urigen(url))
        self.CreateObject(contents=b'foobar3', object_name="file.txt", bucket_uri=bucket)
        return suri(bucket)
        
    def setup_versioned_object(self, provider=None):
        bucket = (self.CreateVersionedBucket(provider=provider))
        url = self.CreateObject(contents=b'foobar1', object_name="obj.txt", bucket_uri=bucket)
        return suri(self.CreateObject(contents=b'foobar2', object_name="obj.txt", bucket_uri=bucket, gs_idempotent_generation=urigen(url)))
    
    def get_uri_listing(self, uri, is_recursive=False, is_versioned=False):
        if not is_recursive:
            return [uri]
        
        list_command = ['ls', '-a'] if is_versioned else ['ls']
        uri = uri+"**" if uri.endswith('/') else uri+"/**" 

        # num_objects + one trailing newline.
        listing = self.RunGsUtil(list_command + [uri], return_stdout=True).split('\n')
        listing.pop()
        return listing
    
    def check_if_resource_has_given_predefined_acl(self, uri,
        predefined_acl, aclStdout=None):
        if aclStdout is None:
            get_command = ['acl', 'get', uri]
            _, aclStdout, _ = self.RunGsUtil(get_command, return_status=
                True, return_stdout=True, return_stderr=True)

        uri = StorageUrlFromString(uri)
        is_bucket = uri.IsBucket()
        if uri.scheme == 's3':
            self.assertIn('s3-project-admin', aclStdout)
            return

        if predefined_acl == 'project-private':
            relevant_regex = (self.private_project_regex_bucket if
                is_bucket else self.private_project_regex_object)
        elif predefined_acl == 'private':
            relevant_regex = (self.private_regex_bucket if is_bucket else
                self.private_regex_object)
        elif predefined_acl == 'bucket-owner-full-control':
            relevant_regex = self.bucket_owner_full_control_regex
        elif predefined_acl == 'public-read':
            relevant_regex = (self.public_read_regex_bucket if is_bucket else
                self.public_read_regex_object)
        elif predefined_acl == 'bucket-owner-read':
            relevant_regex = self.bucket_owner_read_regex
        else:
            return
        
        aclStdout = json.loads(aclStdout)
        n = len(relevant_regex)
        self.assertEqual(len(aclStdout), n)
        is_matched = False
        for perm in itertools.permutations(aclStdout):
            is_matched = True
            for i in range(0, n):
                is_matched = is_matched and relevant_regex[i].fullmatch(json
                    .dumps(perm[i])) != None
            if is_matched:
                break
        self.assertTrue(is_matched)


# TODO(b/360834688): Gsutil acl shim issues.
@RunOnlyOnParityTesting
class AclBase(GsUtilIntegrationTestCase):
    
    def setUp(self):
        super(AclBase, self).setUp()
        self.private_project_regex_bucket = [re.compile(
            '\\{.*"entity":\\s*".*project-owners.*".*"role":\\s*"OWNER".*\\}'
            ), re.compile(
            '\\{.*"entity":\\s*".*project-editors.*".*"role":\\s*"OWNER".*\\}'
            ), re.compile(
            '\\{.*"entity":\\s*".*project-viewers.*".*"role":\\s*"READER".*\\}')]
        self.private_project_regex_object = [re.compile(
            '\\{.*"entity":\\s*".*project-owners.*".*"role":\\s*"OWNER".*\\}'
            ), re.compile(
            '\\{.*"entity":\\s*".*project-editors.*".*"role":\\s*"OWNER".*\\}'
            ), re.compile(
            '\\{.*"entity":\\s*".*project-viewers.*".*"role":\\s*"READER".*\\}'
            ), re.compile(
            '\\{.*"entity":\\s*"user.*".*"role":\\s*"OWNER".*\\}')]
        self.private_regex_object = [re.compile(
            '\\{.*"entity":\\s*"user.*".*"role":\\s*"OWNER".*\\}')]
        self.private_regex_bucket = [re.compile(
            '\\{.*"entity":\\s*".*project-owners.*".*"role":\\s*"OWNER".*\\}')]
        self.public_read_regex_object = [re.compile(
            '\\{.*"entity":\\s*"user.*".*"role":\\s*"OWNER".*\\}'), re.
            compile('\\{.*"entity":\\s*"allUsers".*"role":\\s*"READER".*\\}')]
        self.public_read_regex_bucket = [re.compile(
            '\\{.*"entity":\\s*".*project-owners.*".*"role":\\s*"OWNER".*\\}'
            ), re.compile(
            '\\{.*"entity":\\s*"allUsers".*"role":\\s*"READER".*\\}')]
        self.bucket_owner_full_control_regex = [re.compile(
            '\\{.*"entity":\\s*"user.*".*"role":\\s*"OWNER".*\\}'), re.
            compile(
            '\\{.*"entity":\\s*".*project-owners.*".*"role":\\s*"OWNER".*\\}')]
        self.bucket_owner_read_regex = [re.compile(
            '\\{.*"entity":\\s*"user.*".*"role":\\s*"OWNER".*\\}'), re.
            compile(
            '\\{.*"entity":\\s*".*project-owners.*".*"role":\\s*"READER".*\\}')]

    def setup_bucket_with_predefined_acl(self, predefined_acl=None):
        bucket_name = suri(self.CreateBucket())
        self.RunGsUtil(["acl", "set", predefined_acl, bucket_name])
        return bucket_name
    
    def setup_object_with_predefined_acl(self, predefined_acl=None):
        object_name = suri(self.CreateObject(contents=b'foo'))
        self.RunGsUtil(["acl", "set", predefined_acl, object_name])
        return object_name
    
    def setup_bucket_with_versioned_objects(self, provider=None):
        bucket = (self.CreateVersionedBucket(provider=provider))
        url = self.CreateObject(contents=b'foobar1', object_name="obj.txt", bucket_uri=bucket)
        self.CreateObject(contents=b'foobar2', object_name="obj.txt", bucket_uri=bucket, gs_idempotent_generation=urigen(url))
        self.CreateObject(contents=b'foobar3', object_name="file.txt", bucket_uri=bucket)
        return suri(bucket)
        
    def setup_versioned_object(self, provider=None):
        bucket = (self.CreateVersionedBucket(provider=provider))
        url = self.CreateObject(contents=b'foobar1', object_name="obj.txt", bucket_uri=bucket)
        return suri(self.CreateObject(contents=b'foobar2', object_name="obj.txt", bucket_uri=bucket, gs_idempotent_generation=urigen(url)))
    
    def get_uri_listing(self, uri, is_recursive=False, is_versioned=False):
        if not is_recursive:
            return [uri]
        
        list_command = ['ls', '-a'] if is_versioned else ['ls']
        uri = uri+"**" if uri.endswith('/') else uri+"/**" 

        # num_objects + one trailing newline.
        listing = self.RunGsUtil(list_command + [uri], return_stdout=True).split('\n')
        listing.pop()
        return listing
    
    def check_if_resource_has_given_predefined_acl(self, uri,
        predefined_acl, aclStdout=None):
        if aclStdout is None:
            get_command = ['acl', 'get', uri]
            _, aclStdout, _ = self.RunGsUtil(get_command, return_status=
                True, return_stdout=True, return_stderr=True)

        uri = StorageUrlFromString(uri)
        is_bucket = uri.IsBucket()
        if uri.scheme == 's3':
            self.assertIn('s3-project-admin', aclStdout)
            return

        if predefined_acl == 'project-private':
            relevant_regex = (self.private_project_regex_bucket if
                is_bucket else self.private_project_regex_object)
        elif predefined_acl == 'private':
            relevant_regex = (self.private_regex_bucket if is_bucket else
                self.private_regex_object)
        elif predefined_acl == 'bucket-owner-full-control':
            relevant_regex = self.bucket_owner_full_control_regex
        elif predefined_acl == 'public-read':
            relevant_regex = (self.public_read_regex_bucket if is_bucket else
                self.public_read_regex_object)
        elif predefined_acl == 'bucket-owner-read':
            relevant_regex = self.bucket_owner_read_regex
        else:
            return
        
        aclStdout = json.loads(aclStdout)
        n = len(relevant_regex)
        self.assertEqual(len(aclStdout), n)
        is_matched = False
        for perm in itertools.permutations(aclStdout):
            is_matched = True
            for i in range(0, n):
                is_matched = is_matched and relevant_regex[i].fullmatch(json
                    .dumps(perm[i])) != None
            if is_matched:
                break
        self.assertTrue(is_matched)

@RunOnlyOnParityTesting
class AclGet(AclBase):

    def Validate(self, command, result):
        retcode, aclStdout, _ = result
        self.assertEqual(retcode, 0)
        self.check_if_resource_has_given_predefined_acl(command[-1],
            'project-private', aclStdout)

    def validate_setup_resource_with_predefined_acl(self, command, result,
        predefined_acl):
        retcode, aclStdout, _ = result
        self.assertEqual(retcode, 0)
        self.check_if_resource_has_given_predefined_acl(command[-1],
            predefined_acl, aclStdout)

    @property
    def options(self):
        return []

    @property
    def arguments(self):
        return ['url']

    def test_acl_get_command_url_createbucket1(self):
        url = self.CreateBucket()
        command = 'acl get {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_get_command_url_createobject2(self):
        url = self.CreateObject(contents='foo')
        command = 'acl get {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_get_command_url_createbucket3(self):
        url = self.CreateBucket(provider='s3')
        command = 'acl get {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_get_command_url_createobject4(self):
        url = self.CreateObject(contents='foo', provider='s3')
        command = 'acl get {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_get_command_url_setup_bucket_with_predefined_acl5(self):
        url = self.setup_bucket_with_predefined_acl(predefined_acl=
            'project-private')
        command = 'acl get {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_setup_resource_with_predefined_acl(command, result,
            predefined_acl='project-private')

    def test_acl_get_command_url_setup_bucket_with_predefined_acl6(self):
        url = self.setup_bucket_with_predefined_acl(predefined_acl='private')
        command = 'acl get {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_setup_resource_with_predefined_acl(command, result,
            predefined_acl='private')

    def test_acl_get_command_url_setup_bucket_with_predefined_acl7(self):
        url = self.setup_bucket_with_predefined_acl(predefined_acl=
            'public-read')
        command = 'acl get {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_setup_resource_with_predefined_acl(command, result,
            predefined_acl='public-read')

    def test_acl_get_command_url_setup_bucket_with_predefined_acl8(self):
        url = self.setup_bucket_with_predefined_acl(predefined_acl=
            'authenticated-read')
        command = 'acl get {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_setup_resource_with_predefined_acl(command, result,
            predefined_acl='authenticated-read')

    def test_acl_get_command_url_setup_object_with_predefined_acl9(self):
        url = self.setup_object_with_predefined_acl(predefined_acl=
            'project-private')
        command = 'acl get {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_setup_resource_with_predefined_acl(command, result,
            predefined_acl='project-private')

    def test_acl_get_command_url_setup_object_with_predefined_acl10(self):
        url = self.setup_object_with_predefined_acl(predefined_acl='private')
        command = 'acl get {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_setup_resource_with_predefined_acl(command, result,
            predefined_acl='private')

    def test_acl_get_command_url_setup_object_with_predefined_acl11(self):
        url = self.setup_object_with_predefined_acl(predefined_acl=
            'public-read')
        command = 'acl get {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_setup_resource_with_predefined_acl(command, result,
            predefined_acl='public-read')

    def test_acl_get_command_url_setup_object_with_predefined_acl12(self):
        url = self.setup_object_with_predefined_acl(predefined_acl=
            'authenticated-read')
        command = 'acl get {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_setup_resource_with_predefined_acl(command, result,
            predefined_acl='authenticated-read')

    def test_acl_get_command_url_setup_object_with_predefined_acl13(self):
        url = self.setup_object_with_predefined_acl(predefined_acl=
            'bucket-owner-read')
        command = 'acl get {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_setup_resource_with_predefined_acl(command, result,
            predefined_acl='bucket-owner-read')

    def test_acl_get_command_url_setup_object_with_predefined_acl14(self):
        url = self.setup_object_with_predefined_acl(predefined_acl=
            'bucket-owner-full-control')
        command = 'acl get {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_setup_resource_with_predefined_acl(command, result,
            predefined_acl='bucket-owner-full-control')


# TODO(b/360834688): Gsutil acl shim issues.
@RunOnlyOnParityTesting
class AclSet(AclBase):

    def Validate(self, command, result):
        retcode, stdout, stderr = result
        self.assertEqual(retcode, 0)
        is_recursive = '-r' in command or '-R' in command
        is_versioned = '-a' in command
        uri_listing = self.get_uri_listing(command[-1], is_recursive=
            is_recursive, is_versioned=is_versioned)
        predefined_acl = command[-2]
        for uri in uri_listing:
            self.check_if_resource_has_given_predefined_acl(uri, predefined_acl
                )

    def validate_acl_set_via_file(self, command, result, acl):
        retcode, aclStdout, _ = result
        self.assertEqual(retcode, 0)
        acl = json.loads(acl)
        is_recursive = '-r' in command or '-R' in command
        is_versioned = '-a' in command
        uri_listing = self.get_uri_listing(command[-1], is_recursive=
            is_recursive, is_versioned=is_versioned)
        for uri in uri_listing:
            aclStdout = self.RunGsUtil(['acl', 'get', uri], return_stdout=True)
            aclStdout = json.loads(aclStdout)
            self.assertTrue(len(aclStdout) == len(acl) or len(aclStdout) ==
                len(acl) + 1)
            for acl_entry in acl:
                self.assertIn(acl_entry, aclStdout)

    @property
    def options(self):
        return ['-r', '-R', '-a']

    @property
    def arguments(self):
        return ['acl', 'url']

    def test_acl_set_command_set_acl_project_private_on_url_createbucket1(self
        ):
        url = self.CreateBucket()
        command = 'acl set project-private {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_set_acl_private_on_url_createbucket2(self):
        url = self.CreateBucket()
        command = 'acl set private {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_set_acl_public_read_on_url_createbucket3(self):
        url = self.CreateBucket()
        command = 'acl set public-read {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_set_acl_authenticated_read_on_url_createbucket4(
        self):
        url = self.CreateBucket()
        command = 'acl set authenticated-read {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_set_acl_createtempfile_on_url_createbucket5(self):
        acl = self.CreateTempFile(contents=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )
        url = self.CreateBucket()
        command = 'acl set {acl} {url}'.format(acl=acl, url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )

    def test_acl_set_command_set_acl_createtempfile_on_url_createbucket6(self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allUsers", "role": "READER"}]')
        url = self.CreateBucket()
        command = 'acl set {acl} {url}'.format(acl=acl, url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allUsers", "role": "READER"}]')

    def test_acl_set_command_set_acl_createtempfile_on_url_createbucket7(self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')
        url = self.CreateBucket()
        command = 'acl set {acl} {url}'.format(acl=acl, url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')

    def test_acl_set_command_with_recursive_set_acl_project_private_on_url_createbucket8(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -r project-private {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_set_acl_project_private_on_url_setup_bucket_with_versioned_objects9(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -r project-private {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_set_acl_private_on_url_createbucket10(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -r private {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_set_acl_private_on_url_setup_bucket_with_versioned_objects11(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -r private {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_set_acl_public_read_on_url_createbucket12(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -r public-read {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_set_acl_public_read_on_url_setup_bucket_with_versioned_objects13(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -r public-read {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_set_acl_authenticated_read_on_url_createbucket14(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -r authenticated-read {url}'.format(url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_set_acl_authenticated_read_on_url_setup_bucket_with_versioned_objects15(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -r authenticated-read {url}'.format(url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_set_acl_bucket_owner_read_on_url_createbucket16(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -r bucket-owner-read {url}'.format(url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_set_acl_bucket_owner_read_on_url_setup_bucket_with_versioned_objects17(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -r bucket-owner-read {url}'.format(url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_set_acl_bucket_owner_full_control_on_url_createbucket18(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -r bucket-owner-full-control {url}'.format(url=url
            ).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_set_acl_bucket_owner_full_control_on_url_setup_bucket_with_versioned_objects19(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -r bucket-owner-full-control {url}'.format(url=url
            ).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_set_acl_createtempfile_on_url_createbucket20(
        self):
        acl = self.CreateTempFile(contents=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -r {acl} {url}'.format(acl=acl, url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )

    def test_acl_set_command_with_recursive_set_acl_createtempfile_on_url_setup_bucket_with_versioned_objects21(
        self):
        acl = self.CreateTempFile(contents=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -r {acl} {url}'.format(acl=acl, url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )

    def test_acl_set_command_with_recursive_set_acl_createtempfile_on_url_createbucket22(
        self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allUsers", "role": "READER"}]')
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -r {acl} {url}'.format(acl=acl, url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allUsers", "role": "READER"}]')

    def test_acl_set_command_with_recursive_set_acl_createtempfile_on_url_setup_bucket_with_versioned_objects23(
        self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allUsers", "role": "READER"}]')
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -r {acl} {url}'.format(acl=acl, url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allUsers", "role": "READER"}]')

    def test_acl_set_command_with_recursive_set_acl_createtempfile_on_url_createbucket24(
        self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -r {acl} {url}'.format(acl=acl, url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')

    def test_acl_set_command_with_recursive_set_acl_createtempfile_on_url_setup_bucket_with_versioned_objects25(
        self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -r {acl} {url}'.format(acl=acl, url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')

    def test_acl_set_command_with_recursive_alias_set_acl_project_private_on_url_createbucket26(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -R project-private {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_set_acl_project_private_on_url_setup_bucket_with_versioned_objects27(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -R project-private {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_set_acl_private_on_url_createbucket28(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -R private {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_set_acl_private_on_url_setup_bucket_with_versioned_objects29(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -R private {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_set_acl_public_read_on_url_createbucket30(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -R public-read {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_set_acl_public_read_on_url_setup_bucket_with_versioned_objects31(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -R public-read {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_set_acl_authenticated_read_on_url_createbucket32(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -R authenticated-read {url}'.format(url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_set_acl_authenticated_read_on_url_setup_bucket_with_versioned_objects33(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -R authenticated-read {url}'.format(url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_set_acl_bucket_owner_read_on_url_createbucket34(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -R bucket-owner-read {url}'.format(url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_set_acl_bucket_owner_read_on_url_setup_bucket_with_versioned_objects35(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -R bucket-owner-read {url}'.format(url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_set_acl_bucket_owner_full_control_on_url_createbucket36(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -R bucket-owner-full-control {url}'.format(url=url
            ).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_set_acl_bucket_owner_full_control_on_url_setup_bucket_with_versioned_objects37(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -R bucket-owner-full-control {url}'.format(url=url
            ).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_set_acl_createtempfile_on_url_createbucket38(
        self):
        acl = self.CreateTempFile(contents=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -R {acl} {url}'.format(acl=acl, url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )

    def test_acl_set_command_with_recursive_alias_set_acl_createtempfile_on_url_setup_bucket_with_versioned_objects39(
        self):
        acl = self.CreateTempFile(contents=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -R {acl} {url}'.format(acl=acl, url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )

    def test_acl_set_command_with_recursive_alias_set_acl_createtempfile_on_url_createbucket40(
        self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allUsers", "role": "READER"}]')
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -R {acl} {url}'.format(acl=acl, url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allUsers", "role": "READER"}]')

    def test_acl_set_command_with_recursive_alias_set_acl_createtempfile_on_url_setup_bucket_with_versioned_objects41(
        self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allUsers", "role": "READER"}]')
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -R {acl} {url}'.format(acl=acl, url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allUsers", "role": "READER"}]')

    def test_acl_set_command_with_recursive_alias_set_acl_createtempfile_on_url_createbucket42(
        self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -R {acl} {url}'.format(acl=acl, url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')

    def test_acl_set_command_with_recursive_alias_set_acl_createtempfile_on_url_setup_bucket_with_versioned_objects43(
        self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -R {acl} {url}'.format(acl=acl, url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')

    def test_acl_set_command_with_set_on_all_versions_set_acl_project_private_on_url_createobject44(
        self):
        url = self.CreateObject(contents='foox')
        command = 'acl set -a project-private {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_set_on_all_versions_set_acl_project_private_on_url_setup_versioned_object45(
        self):
        url = self.setup_versioned_object()
        command = 'acl set -a project-private {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_set_on_all_versions_set_acl_private_on_url_createobject46(
        self):
        url = self.CreateObject(contents='foox')
        command = 'acl set -a private {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_set_on_all_versions_set_acl_private_on_url_setup_versioned_object47(
        self):
        url = self.setup_versioned_object()
        command = 'acl set -a private {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_set_on_all_versions_set_acl_public_read_on_url_createobject48(
        self):
        url = self.CreateObject(contents='foox')
        command = 'acl set -a public-read {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_set_on_all_versions_set_acl_public_read_on_url_setup_versioned_object49(
        self):
        url = self.setup_versioned_object()
        command = 'acl set -a public-read {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_set_on_all_versions_set_acl_authenticated_read_on_url_createobject50(
        self):
        url = self.CreateObject(contents='foox')
        command = 'acl set -a authenticated-read {url}'.format(url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_set_on_all_versions_set_acl_authenticated_read_on_url_setup_versioned_object51(
        self):
        url = self.setup_versioned_object()
        command = 'acl set -a authenticated-read {url}'.format(url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_set_on_all_versions_set_acl_bucket_owner_read_on_url_createobject52(
        self):
        url = self.CreateObject(contents='foox')
        command = 'acl set -a bucket-owner-read {url}'.format(url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_set_on_all_versions_set_acl_bucket_owner_read_on_url_setup_versioned_object53(
        self):
        url = self.setup_versioned_object()
        command = 'acl set -a bucket-owner-read {url}'.format(url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_set_on_all_versions_set_acl_bucket_owner_full_control_on_url_createobject54(
        self):
        url = self.CreateObject(contents='foox')
        command = 'acl set -a bucket-owner-full-control {url}'.format(url=url
            ).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_set_on_all_versions_set_acl_bucket_owner_full_control_on_url_setup_versioned_object55(
        self):
        url = self.setup_versioned_object()
        command = 'acl set -a bucket-owner-full-control {url}'.format(url=url
            ).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_set_on_all_versions_set_acl_createtempfile_on_url_createobject56(
        self):
        acl = self.CreateTempFile(contents=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )
        url = self.CreateObject(contents='foox')
        command = 'acl set -a {acl} {url}'.format(acl=acl, url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )

    def test_acl_set_command_with_set_on_all_versions_set_acl_createtempfile_on_url_setup_versioned_object57(
        self):
        acl = self.CreateTempFile(contents=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )
        url = self.setup_versioned_object()
        command = 'acl set -a {acl} {url}'.format(acl=acl, url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )

    def test_acl_set_command_with_set_on_all_versions_set_acl_createtempfile_on_url_createobject58(
        self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allUsers", "role": "READER"}]')
        url = self.CreateObject(contents='foox')
        command = 'acl set -a {acl} {url}'.format(acl=acl, url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allUsers", "role": "READER"}]')

    def test_acl_set_command_with_set_on_all_versions_set_acl_createtempfile_on_url_setup_versioned_object59(
        self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allUsers", "role": "READER"}]')
        url = self.setup_versioned_object()
        command = 'acl set -a {acl} {url}'.format(acl=acl, url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allUsers", "role": "READER"}]')

    def test_acl_set_command_with_set_on_all_versions_set_acl_createtempfile_on_url_createobject60(
        self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')
        url = self.CreateObject(contents='foox')
        command = 'acl set -a {acl} {url}'.format(acl=acl, url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')

    def test_acl_set_command_with_set_on_all_versions_set_acl_createtempfile_on_url_setup_versioned_object61(
        self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')
        url = self.setup_versioned_object()
        command = 'acl set -a {acl} {url}'.format(acl=acl, url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')

    def test_acl_set_command_with_recursive_with_set_on_all_versions_set_acl_project_private_on_url_createbucket62(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -r -a project-private {url}'.format(url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_with_set_on_all_versions_set_acl_project_private_on_url_setup_bucket_with_versioned_objects63(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -r -a project-private {url}'.format(url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_with_set_on_all_versions_set_acl_private_on_url_createbucket64(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -r -a private {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_with_set_on_all_versions_set_acl_private_on_url_setup_bucket_with_versioned_objects65(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -r -a private {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_with_set_on_all_versions_set_acl_public_read_on_url_createbucket66(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -r -a public-read {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_with_set_on_all_versions_set_acl_public_read_on_url_setup_bucket_with_versioned_objects67(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -r -a public-read {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_with_set_on_all_versions_set_acl_authenticated_read_on_url_createbucket68(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -r -a authenticated-read {url}'.format(url=url
            ).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_with_set_on_all_versions_set_acl_authenticated_read_on_url_setup_bucket_with_versioned_objects69(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -r -a authenticated-read {url}'.format(url=url
            ).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_with_set_on_all_versions_set_acl_bucket_owner_read_on_url_createbucket70(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -r -a bucket-owner-read {url}'.format(url=url
            ).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_with_set_on_all_versions_set_acl_bucket_owner_read_on_url_setup_bucket_with_versioned_objects71(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -r -a bucket-owner-read {url}'.format(url=url
            ).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_with_set_on_all_versions_set_acl_bucket_owner_full_control_on_url_createbucket72(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -r -a bucket-owner-full-control {url}'.format(url
            =url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_with_set_on_all_versions_set_acl_bucket_owner_full_control_on_url_setup_bucket_with_versioned_objects73(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -r -a bucket-owner-full-control {url}'.format(url
            =url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_with_set_on_all_versions_set_acl_createtempfile_on_url_createbucket74(
        self):
        acl = self.CreateTempFile(contents=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -r -a {acl} {url}'.format(acl=acl, url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )

    def test_acl_set_command_with_recursive_with_set_on_all_versions_set_acl_createtempfile_on_url_setup_bucket_with_versioned_objects75(
        self):
        acl = self.CreateTempFile(contents=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -r -a {acl} {url}'.format(acl=acl, url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )

    def test_acl_set_command_with_recursive_with_set_on_all_versions_set_acl_createtempfile_on_url_createbucket76(
        self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allUsers", "role": "READER"}]')
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -r -a {acl} {url}'.format(acl=acl, url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allUsers", "role": "READER"}]')

    def test_acl_set_command_with_recursive_with_set_on_all_versions_set_acl_createtempfile_on_url_setup_bucket_with_versioned_objects77(
        self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allUsers", "role": "READER"}]')
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -r -a {acl} {url}'.format(acl=acl, url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allUsers", "role": "READER"}]')

    def test_acl_set_command_with_recursive_with_set_on_all_versions_set_acl_createtempfile_on_url_createbucket78(
        self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -r -a {acl} {url}'.format(acl=acl, url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')

    def test_acl_set_command_with_recursive_with_set_on_all_versions_set_acl_createtempfile_on_url_setup_bucket_with_versioned_objects79(
        self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -r -a {acl} {url}'.format(acl=acl, url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')

    def test_acl_set_command_with_recursive_alias_with_set_on_all_versions_set_acl_project_private_on_url_createbucket80(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -R -a project-private {url}'.format(url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_with_set_on_all_versions_set_acl_project_private_on_url_setup_bucket_with_versioned_objects81(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -R -a project-private {url}'.format(url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_with_set_on_all_versions_set_acl_private_on_url_createbucket82(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -R -a private {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_with_set_on_all_versions_set_acl_private_on_url_setup_bucket_with_versioned_objects83(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -R -a private {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_with_set_on_all_versions_set_acl_public_read_on_url_createbucket84(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -R -a public-read {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_with_set_on_all_versions_set_acl_public_read_on_url_setup_bucket_with_versioned_objects85(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -R -a public-read {url}'.format(url=url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_with_set_on_all_versions_set_acl_authenticated_read_on_url_createbucket86(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -R -a authenticated-read {url}'.format(url=url
            ).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_with_set_on_all_versions_set_acl_authenticated_read_on_url_setup_bucket_with_versioned_objects87(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -R -a authenticated-read {url}'.format(url=url
            ).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_with_set_on_all_versions_set_acl_bucket_owner_read_on_url_createbucket88(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -R -a bucket-owner-read {url}'.format(url=url
            ).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_with_set_on_all_versions_set_acl_bucket_owner_read_on_url_setup_bucket_with_versioned_objects89(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -R -a bucket-owner-read {url}'.format(url=url
            ).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_with_set_on_all_versions_set_acl_bucket_owner_full_control_on_url_createbucket90(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -R -a bucket-owner-full-control {url}'.format(url
            =url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_with_set_on_all_versions_set_acl_bucket_owner_full_control_on_url_setup_bucket_with_versioned_objects91(
        self):
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -R -a bucket-owner-full-control {url}'.format(url
            =url).split(' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.Validate(command, result)

    def test_acl_set_command_with_recursive_alias_with_set_on_all_versions_set_acl_createtempfile_on_url_createbucket92(
        self):
        acl = self.CreateTempFile(contents=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -R -a {acl} {url}'.format(acl=acl, url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )

    def test_acl_set_command_with_recursive_alias_with_set_on_all_versions_set_acl_createtempfile_on_url_setup_bucket_with_versioned_objects93(
        self):
        acl = self.CreateTempFile(contents=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -R -a {acl} {url}'.format(acl=acl, url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"email": "foo@bar.com", "entity": "user-foo@bar.com", "role": "READER"}, {"email": "bar@foo.com", "entity": "user-bar@foo.com", "role": "READER"}]'
            )

    def test_acl_set_command_with_recursive_alias_with_set_on_all_versions_set_acl_createtempfile_on_url_createbucket94(
        self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allUsers", "role": "READER"}]')
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -R -a {acl} {url}'.format(acl=acl, url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allUsers", "role": "READER"}]')

    def test_acl_set_command_with_recursive_alias_with_set_on_all_versions_set_acl_createtempfile_on_url_setup_bucket_with_versioned_objects95(
        self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allUsers", "role": "READER"}]')
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -R -a {acl} {url}'.format(acl=acl, url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allUsers", "role": "READER"}]')

    def test_acl_set_command_with_recursive_alias_with_set_on_all_versions_set_acl_createtempfile_on_url_createbucket96(
        self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')
        url = self.CreateBucket(test_objects=2)
        command = 'acl set -R -a {acl} {url}'.format(acl=acl, url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')

    def test_acl_set_command_with_recursive_alias_with_set_on_all_versions_set_acl_createtempfile_on_url_setup_bucket_with_versioned_objects97(
        self):
        acl = self.CreateTempFile(contents=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')
        url = self.setup_bucket_with_versioned_objects()
        command = 'acl set -R -a {acl} {url}'.format(acl=acl, url=url).split(
            ' ')
        result = self.RunGsUtil(command, return_status=True, return_stdout=
            True, return_stderr=True, expected_status=None)
        self.validate_acl_set_via_file(command, result, acl=
            '[{"entity": "allAuthenticatedUsers", "role": "READER"}]')


# TODO(b/360834688): Gsutil acl shim issues.
@RunOnlyOnParityTesting
class AclCh(AclBase):

    def set_grants_on_resource(self, uri, grants=[]):
        command = ['acl', 'ch']
        for grant in grants:
            if grant.startswith('user-'):
                command.append('-u')
                command.append(grant[len('user-'):])
            if grant.startswith('group-'):
                command.append('-g')
                command.append(grant[len('group-'):])
            if grant.startswith('project-'):
                command.sub_append('-p')
                command.append(grant[len('group-'):])
        command.append(str(uri))
        self.RunGsUtil(command)

    def setup_bucket_with_grants(self, test_objects=0, grants=[]):
        uri = self.CreateBucket()
        self.set_grants_on_resource(uri, grants=grants)
        for _ in range(test_objects):
            url = self.CreateObject(contents='foo', bucket_uri=uri)
            self.set_grants_on_resource(url, grants=grants)
        return uri

    def setup_object_with_grants(self, grants=[]):
        url = self.CreateObject(contents='foo')
        self.set_grants_on_resource(url, grants=grants)
        return url

    def CustomRun(self, command, url):
        command = ' '.join(command).format(url=url).split(' ')
        retcode, _, _ = self.RunGsUtil(command, return_status=True,
            return_stdout=True, return_stderr=True, expected_status=None)
        self.assertEqual(retcode, 0)
        is_recursive = '-r' in command or '-R' in command
        listing = self.get_uri_listing(command[-1], is_recursive=is_recursive)
        return listing

    def Validate(self, command, result, acl_added_regex=[],
        acl_deleted_regex=[]):
        listing = result
        for uri in listing:
            uri = StorageUrlFromString(uri)
            aclStdout = self.RunGsUtil(['acl', 'get', str(uri)],
                return_stdout=True)
            for elem in acl_added_regex:
                if 'WRITER' in elem.pattern and uri.IsObject():
                    pass
                else:
                    self.assertRegex(aclStdout, elem)
            for elem in acl_deleted_regex:
                self.assertNotRegex(aclStdout, elem)

    @property
    def options(self):
        return ['-u', '-g', '-p', '-d', '-r', '-R']

    @property
    def arguments(self):
        return ['url']

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_on_url_createbucket1(
        self):
        url = self.CreateBucket()
        command = 'acl ch -u gsutiltesting123@gmail.com:R {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_on_url_createobject2(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = 'acl ch -u gsutiltesting123@gmail.com:R {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_foo_bar_com_w_on_url_createbucket3(
        self):
        url = self.CreateBucket()
        command = 'acl ch -u foo@bar.com:W {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_on_url_createbucket4(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_on_url_createobject5(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_on_url_createbucket6(
        self):
        url = self.CreateBucket()
        command = 'acl ch -g gs-discussion@googlegroups.com:R {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_on_url_createobject7(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = 'acl ch -g gs-discussion@googlegroups.com:R {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_on_url_createbucket8(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_group_entity_allusers_r_on_url_createbucket9(
        self):
        url = self.CreateBucket()
        command = 'acl ch -g allUsers:R {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])

    def test_acl_ch_command_with_group_entity_allusers_r_on_url_createobject10(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = 'acl ch -g allUsers:R {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])

    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_on_url_createbucket11(
        self):
        url = self.CreateBucket()
        command = 'acl ch -g allAuthenticatedUsers:R {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])

    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_on_url_createobject12(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = 'acl ch -g allAuthenticatedUsers:R {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_on_url_createbucket13(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_on_url_createobject14(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_on_url_createbucket15(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_on_url_createbucket16(
        self):
        url = self.CreateBucket()
        command = ('acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_on_url_createobject17(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = ('acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_on_url_createbucket18(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_on_url_createobject19(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_gs_discussion_googlegroups_com_r_on_url_createbucket20(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u foo@bar.com:W -g gs-discussion@googlegroups.com:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_on_url_createbucket21(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u foo@bar.com:W -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_allusers_r_on_url_createbucket22(
        self):
        url = self.CreateBucket()
        command = 'acl ch -u foo@bar.com:W -g allUsers:R {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])

    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_allauthenticatedusers_r_on_url_createbucket23(
        self):
        url = self.CreateBucket()
        command = ('acl ch -u foo@bar.com:W -g allAuthenticatedUsers:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_on_url_createbucket24(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_on_url_createobject25(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_on_url_createbucket26(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_on_url_createbucket27(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_on_url_createobject28(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_on_url_createbucket29(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_on_url_createobject30(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_project_entity_owners_seventhsky_r_on_url_createbucket31(
        self):
        url = self.CreateBucket()
        command = 'acl ch -p owners-seventhsky:R {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_project_entity_owners_seventhsky_r_on_url_createobject32(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = 'acl ch -p owners-seventhsky:R {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_on_url_createbucket33(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -p viewers-seventhsky:O -p editors-seventhsky:W {url}'.
            split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_project_entity_owners_seventhsky_r_on_url_createbucket34(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_project_entity_owners_seventhsky_r_on_url_createobject35(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_on_url_createbucket36(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -p viewers-seventhsky:O -p editors-seventhsky:W {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_project_entity_owners_seventhsky_r_on_url_createbucket37(
        self):
        url = self.CreateBucket()
        command = 'acl ch -u foo@bar.com:W -p owners-seventhsky:R {url}'.split(
            ' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_on_url_createbucket38(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u foo@bar.com:W -p viewers-seventhsky:O -p editors-seventhsky:W {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_project_entity_owners_seventhsky_r_on_url_createbucket39(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_project_entity_owners_seventhsky_r_on_url_createobject40(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_on_url_createbucket41(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -p viewers-seventhsky:O -p editors-seventhsky:W {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_on_url_createbucket42(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_on_url_createobject43(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_on_url_createbucket44(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_on_url_createbucket45(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_on_url_createbucket46(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_on_url_createbucket47(
        self):
        url = self.CreateBucket()
        command = 'acl ch -g allUsers:R -p owners-seventhsky:R {url}'.split(' '
            )
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_on_url_createobject48(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = 'acl ch -g allUsers:R -p owners-seventhsky:R {url}'.split(' '
            )
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_on_url_createbucket49(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -g allUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_on_url_createbucket50(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -g allAuthenticatedUsers:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_on_url_createobject51(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = (
            'acl ch -g allAuthenticatedUsers:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_on_url_createbucket52(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -g allAuthenticatedUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_on_url_createbucket53(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_on_url_createobject54(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_on_url_createbucket55(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_on_url_createbucket56(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_on_url_createbucket57(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_on_url_createbucket58(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_on_url_createobject59(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_on_url_createbucket60(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_on_url_createbucket61(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_on_url_createobject62(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_on_url_createbucket63(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_on_url_createbucket64(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u foo@bar.com:W -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_on_url_createbucket65(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u foo@bar.com:W -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_on_url_createbucket66(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u foo@bar.com:W -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_on_url_createbucket67(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u foo@bar.com:W -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_on_url_createbucket68(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u foo@bar.com:W -g allUsers:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_allusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_on_url_createbucket69(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u foo@bar.com:W -g allUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_on_url_createbucket70(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u foo@bar.com:W -g allAuthenticatedUsers:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_allauthenticatedusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_on_url_createbucket71(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u foo@bar.com:W -g allAuthenticatedUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_on_url_createbucket72(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_on_url_createobject73(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_on_url_createbucket74(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_on_url_createbucket75(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_on_url_createbucket76(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_on_url_createbucket77(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_on_url_createobject78(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_on_url_createbucket79(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_on_url_createbucket80(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_on_url_createobject81(
        self):
        url = self.CreateObject(contents=b'my-content')
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_on_url_createbucket82(
        self):
        url = self.CreateBucket()
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])

    def test_acl_ch_command_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants83(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = 'acl ch -d bar@foo.com {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants84(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = 'acl ch -d bar@foo.com {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants85(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = 'acl ch -d gcs-clients-and-probers@google.com {url}'.split(
            ' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants86(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = 'acl ch -d gcs-clients-and-probers@google.com {url}'.split(
            ' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants87(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -d bar@foo.com {url}'.
            split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants88(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -d bar@foo.com {url}'.
            split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants89(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants90(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants91(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = 'acl ch -u foo@bar.com:W -d bar@foo.com {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants92(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants93(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants94(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants95(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants96(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants97(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants98(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants99(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants100(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants101(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants102(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_group_entity_allusers_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants103(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = 'acl ch -g allUsers:R -d bar@foo.com {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_group_entity_allusers_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants104(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = 'acl ch -g allUsers:R -d bar@foo.com {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_group_entity_allusers_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants105(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -g allUsers:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_group_entity_allusers_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants106(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -g allUsers:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants107(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = ('acl ch -g allAuthenticatedUsers:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants108(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = ('acl ch -g allAuthenticatedUsers:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants109(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -g allAuthenticatedUsers:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants110(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -g allAuthenticatedUsers:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants111(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants112(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants113(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants114(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants115(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants116(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants117(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants118(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants119(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants120(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants121(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants122(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants123(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants124(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants125(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g gs-discussion@googlegroups.com:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants126(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g gs-discussion@googlegroups.com:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants127(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants128(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_allusers_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants129(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = ('acl ch -u foo@bar.com:W -g allUsers:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_allusers_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants130(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g allUsers:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_allauthenticatedusers_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants131(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g allAuthenticatedUsers:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_allauthenticatedusers_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants132(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g allAuthenticatedUsers:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants133(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants134(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants135(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants136(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants137(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants138(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants139(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants140(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants141(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants142(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants143(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants144(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants145(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants146(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants147(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = 'acl ch -p owners-seventhsky:R -d bar@foo.com {url}'.split(
            ' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants148(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = 'acl ch -p owners-seventhsky:R -d bar@foo.com {url}'.split(
            ' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants149(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants150(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants151(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -p viewers-seventhsky:O -p editors-seventhsky:W -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants152(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -p viewers-seventhsky:O -p editors-seventhsky:W -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants153(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants154(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants155(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants156(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants157(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -p viewers-seventhsky:O -p editors-seventhsky:W -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants158(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -p viewers-seventhsky:O -p editors-seventhsky:W -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants159(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants160(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants161(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -p viewers-seventhsky:O -p editors-seventhsky:W -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants162(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -p viewers-seventhsky:O -p editors-seventhsky:W -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants163(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants164(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants165(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants166(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants167(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -p viewers-seventhsky:O -p editors-seventhsky:W -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants168(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -p viewers-seventhsky:O -p editors-seventhsky:W -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants169(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants170(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants171(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants172(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants173(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants174(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants175(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants176(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants177(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants178(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants179(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -g allUsers:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants180(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -g allUsers:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants181(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -g allUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants182(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -g allUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants183(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -g allUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants184(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -g allUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants185(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -g allAuthenticatedUsers:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants186(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -g allAuthenticatedUsers:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants187(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -g allAuthenticatedUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants188(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -g allAuthenticatedUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants189(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -g allAuthenticatedUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants190(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -g allAuthenticatedUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants191(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants192(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants193(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants194(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants195(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants196(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants197(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants198(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants199(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants200(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants201(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants202(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants203(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants204(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants205(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants206(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants207(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants208(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants209(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants210(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants211(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants212(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants213(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants214(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants215(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants216(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants217(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants218(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants219(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants220(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants221(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g allUsers:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants222(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g allUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_allusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants223(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g allUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_allusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants224(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g allUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants225(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g allAuthenticatedUsers:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants226(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g allAuthenticatedUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_allauthenticatedusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants227(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g allAuthenticatedUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_foo_bar_com_w_with_group_entity_allauthenticatedusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants228(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u foo@bar.com:W -g allAuthenticatedUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "WRITER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants229(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants230(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants231(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants232(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants233(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants234(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants235(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants236(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants237(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gcs_clients_hyd_google_com_w__g_gs_discussion_googlegroups_com_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants238(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gcs-clients-hyd@google.com:W -g gs-discussion@googlegroups.com:R -p viewers-seventhsky:O -p editors-seventhsky:W -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gcs-clients-hyd@google.com".*"entity": "group-gcs-clients-hyd@google.com".*"role": "WRITER".*'
            , re.DOTALL), re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants239(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants240(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants241(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants242(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants243(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants244(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants245(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_on_url_setup_object_with_grants246(
        self):
        url = self.setup_object_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants247(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_object_with_grants248(
        self):
        url = self.setup_object_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_bar_foo_com_on_url_setup_bucket_with_grants249(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W -d bar@foo.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_viewers_seventhsky_o__p_editors_seventhsky_w_with_delete_entity_gcs_clients_and_probers_google_com_on_url_setup_bucket_with_grants250(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'])
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -p viewers-seventhsky:O -p editors-seventhsky:W -d gcs-clients-and-probers@google.com {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-viewers-690493439540".*"role": "OWNER".*',
            re.DOTALL), re.compile(
            '.*"entity": ".*project-editors-690493439540".*"role": "WRITER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_recursive_on_url_createbucket251(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl ch -u gsutiltesting123@gmail.com:R -r {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_recursive_on_url_createbucket252(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_recursive_on_url_createbucket253(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl ch -g gs-discussion@googlegroups.com:R -r {url}'.split(
            ' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_group_entity_allusers_r_recursive_on_url_createbucket254(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl ch -g allUsers:R -r {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])

    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_recursive_on_url_createbucket255(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl ch -g allAuthenticatedUsers:R -r {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_recursive_on_url_createbucket256(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_recursive_on_url_createbucket257(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_recursive_on_url_createbucket258(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_recursive_on_url_createbucket259(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_recursive_on_url_createbucket260(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_recursive_on_url_createbucket261(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_project_entity_owners_seventhsky_r_recursive_on_url_createbucket262(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl ch -p owners-seventhsky:R -r {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_project_entity_owners_seventhsky_r_recursive_on_url_createbucket263(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -p owners-seventhsky:R -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_project_entity_owners_seventhsky_r_recursive_on_url_createbucket264(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -p owners-seventhsky:R -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_recursive_on_url_createbucket265(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_recursive_on_url_createbucket266(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl ch -g allUsers:R -p owners-seventhsky:R -r {url}'.split(
            ' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_recursive_on_url_createbucket267(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -g allAuthenticatedUsers:R -p owners-seventhsky:R -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_recursive_on_url_createbucket268(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_recursive_on_url_createbucket269(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -p owners-seventhsky:R -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_recursive_on_url_createbucket270(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_recursive_on_url_createbucket271(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_recursive_on_url_createbucket272(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -p owners-seventhsky:R -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_recursive_on_url_createbucket273(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    def test_acl_ch_command_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants274(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = 'acl ch -d bar@foo.com -r {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants275(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = ('acl ch -d gcs-clients-and-probers@google.com -r {url}'.
            split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants276(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -d bar@foo.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants277(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants278(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -d bar@foo.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants279(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants280(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -d bar@foo.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants281(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_group_entity_allusers_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants282(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = 'acl ch -g allUsers:R -d bar@foo.com -r {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_group_entity_allusers_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants283(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -g allUsers:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants284(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = ('acl ch -g allAuthenticatedUsers:R -d bar@foo.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants285(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -g allAuthenticatedUsers:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants286(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -d bar@foo.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants287(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants288(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -d bar@foo.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants289(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants290(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -d bar@foo.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants291(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants292(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -d bar@foo.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants293(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants294(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -d bar@foo.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants295(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants296(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -d bar@foo.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants297(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants298(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = ('acl ch -p owners-seventhsky:R -d bar@foo.com -r {url}'.
            split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants299(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants300(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -p owners-seventhsky:R -d bar@foo.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants301(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants302(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -p owners-seventhsky:R -d bar@foo.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants303(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants304(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d bar@foo.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants305(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants306(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -g allUsers:R -p owners-seventhsky:R -d bar@foo.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants307(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -g allUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants308(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -g allAuthenticatedUsers:R -p owners-seventhsky:R -d bar@foo.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants309(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -g allAuthenticatedUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants310(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d bar@foo.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants311(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants312(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -p owners-seventhsky:R -d bar@foo.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants313(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants314(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R -d bar@foo.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants315(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants316(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d bar@foo.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants317(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants318(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -p owners-seventhsky:R -d bar@foo.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants319(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_on_url_setup_bucket_with_grants320(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R -d bar@foo.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_on_url_setup_bucket_with_grants321(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -r {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_recursive_alias_on_url_createbucket322(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl ch -u gsutiltesting123@gmail.com:R -R {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_recursive_alias_on_url_createbucket323(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_recursive_alias_on_url_createbucket324(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl ch -g gs-discussion@googlegroups.com:R -R {url}'.split(
            ' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_group_entity_allusers_r_recursive_alias_on_url_createbucket325(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl ch -g allUsers:R -R {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])

    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_recursive_alias_on_url_createbucket326(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl ch -g allAuthenticatedUsers:R -R {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_recursive_alias_on_url_createbucket327(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_recursive_alias_on_url_createbucket328(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_recursive_alias_on_url_createbucket329(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_recursive_alias_on_url_createbucket330(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_recursive_alias_on_url_createbucket331(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_recursive_alias_on_url_createbucket332(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_project_entity_owners_seventhsky_r_recursive_alias_on_url_createbucket333(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl ch -p owners-seventhsky:R -R {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_project_entity_owners_seventhsky_r_recursive_alias_on_url_createbucket334(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -p owners-seventhsky:R -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_project_entity_owners_seventhsky_r_recursive_alias_on_url_createbucket335(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -p owners-seventhsky:R -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_recursive_alias_on_url_createbucket336(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_recursive_alias_on_url_createbucket337(
        self):
        url = self.CreateBucket(test_objects=2)
        command = 'acl ch -g allUsers:R -p owners-seventhsky:R -R {url}'.split(
            ' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_recursive_alias_on_url_createbucket338(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -g allAuthenticatedUsers:R -p owners-seventhsky:R -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_recursive_alias_on_url_createbucket339(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_recursive_alias_on_url_createbucket340(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -p owners-seventhsky:R -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_recursive_alias_on_url_createbucket341(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_recursive_alias_on_url_createbucket342(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_recursive_alias_on_url_createbucket343(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -p owners-seventhsky:R -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_recursive_alias_on_url_createbucket344(
        self):
        url = self.CreateBucket(test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])

    def test_acl_ch_command_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants345(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = 'acl ch -d bar@foo.com -R {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants346(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = ('acl ch -d gcs-clients-and-probers@google.com -R {url}'.
            split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants347(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -d bar@foo.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants348(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants349(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -d bar@foo.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants350(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants351(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -d bar@foo.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants352(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_group_entity_allusers_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants353(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = 'acl ch -g allUsers:R -d bar@foo.com -R {url}'.split(' ')
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_group_entity_allusers_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants354(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -g allUsers:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants355(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = ('acl ch -g allAuthenticatedUsers:R -d bar@foo.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants356(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -g allAuthenticatedUsers:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants357(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -d bar@foo.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants358(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants359(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -d bar@foo.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants360(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants361(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -d bar@foo.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants362(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants363(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -d bar@foo.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants364(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants365(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -d bar@foo.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants366(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants367(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -d bar@foo.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants368(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants369(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = ('acl ch -p owners-seventhsky:R -d bar@foo.com -R {url}'.
            split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants370(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants371(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -p owners-seventhsky:R -d bar@foo.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants372(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants373(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -p owners-seventhsky:R -d bar@foo.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants374(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants375(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d bar@foo.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants376(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants377(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -g allUsers:R -p owners-seventhsky:R -d bar@foo.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants378(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -g allUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants379(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -g allAuthenticatedUsers:R -p owners-seventhsky:R -d bar@foo.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants380(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -g allAuthenticatedUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants381(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d bar@foo.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants382(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants383(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -p owners-seventhsky:R -d bar@foo.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants384(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants385(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R -d bar@foo.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants386(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants387(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d bar@foo.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_gs_discussion_googlegroups_com_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants388(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g gs-discussion@googlegroups.com:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gs-discussion@googlegroups.com".*"entity": "group-gs-discussion@googlegroups.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants389(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -p owners-seventhsky:R -d bar@foo.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants390(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allUsers".*"role": "READER".*', re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_bar_foo_com_recursive_alias_on_url_setup_bucket_with_grants391(
        self):
        url = self.setup_bucket_with_grants(grants=['user-bar@foo.com:R'],
            test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R -d bar@foo.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "bar@foo.com".*"entity": "user-bar@foo.com".*', re.
            DOTALL)])

    @SkipForXML('Please refer to generation script for reason!')
    def test_acl_ch_command_with_user_entity_gsutiltesting123_gmail_com_o__u_foo_bar_com_r_with_group_entity_allauthenticatedusers_r_with_project_entity_owners_seventhsky_r_with_delete_entity_gcs_clients_and_probers_google_com_recursive_alias_on_url_setup_bucket_with_grants392(
        self):
        url = self.setup_bucket_with_grants(grants=[
            'group-gcs-clients-and-probers@google.com:R'], test_objects=2)
        command = (
            'acl ch -u gsutiltesting123@gmail.com:O -u foo@bar.com:R -g allAuthenticatedUsers:R -p owners-seventhsky:R -d gcs-clients-and-probers@google.com -R {url}'
            .split(' '))
        result = self.CustomRun(command, url=url)
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"email": "gsutiltesting123@gmail.com".*"entity": "user-gsutiltesting123@gmail.com".*"role": "OWNER".*'
            , re.DOTALL), re.compile(
            '.*"email": "foo@bar.com".*"entity": "user-foo@bar.com".*"role": "READER".*'
            , re.DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": "allAuthenticatedUsers".*"role": "READER".*', re.
            DOTALL)])
        self.Validate(command, result, acl_added_regex=[re.compile(
            '.*"entity": ".*project-owners-690493439540".*"role": "READER".*',
            re.DOTALL)])
        self.Validate(command, result, acl_deleted_regex=[re.compile(
            '.*"email": "gcs-clients-and-probers@google.com".*"entity": "group-gcs-clients-and-probers@google.com".*'
            , re.DOTALL)])
