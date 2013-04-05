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
"""Integration tests for the setacl and setdefacl commands."""

import gslib.tests.testcase as testcase
import re
from gslib.util import Retry
from gslib.tests.util import ObjectToURI as suri

PUBLIC_READ_ACL_TEXT = '<Scope type="AllUsers"/><Permission>READ</Permission>'


class TestSetAcl(testcase.GsUtilIntegrationTestCase):
  """Integration tests for setacl command."""

  def test_set_invalid_acl_object(self):
    """Ensures that invalid XML content returns a MalformedACLError."""
    obj_uri = suri(self.CreateObject(contents='foo'))
    inpath = self.CreateTempFile(contents='badXml')
    stderr = self.RunGsUtil(['setacl', inpath, obj_uri], return_stderr=True,
                            expected_status=1)

    self.assertIn('MalformedACLError', stderr)

  def test_set_invalid_acl_bucket(self):
    """Ensures that invalid XML content returns a MalformedACLError."""
    bucket_uri = suri(self.CreateBucket())
    inpath = self.CreateTempFile(contents='badXml')
    stderr = self.RunGsUtil(['setacl', inpath, bucket_uri], return_stderr=True,
                            expected_status=1)

    self.assertIn('MalformedACLError', stderr)

  def test_set_valid_acl_object(self):
    """Ensures that valid canned and XML ACLs work with get/set."""
    obj_uri = suri(self.CreateObject(contents='foo'))
    acl_string = self.RunGsUtil(['getacl', obj_uri], return_stdout=True)
    inpath = self.CreateTempFile(contents=acl_string)
    self.RunGsUtil(['setacl', 'public-read', obj_uri])
    acl_string2 = self.RunGsUtil(['getacl', obj_uri], return_stdout=True)
    self.RunGsUtil(['setacl', inpath, obj_uri])
    acl_string3 = self.RunGsUtil(['getacl', obj_uri], return_stdout=True)

    self.assertNotEqual(acl_string, acl_string2)
    self.assertEqual(acl_string, acl_string3)

  def test_set_valid_permission_whitespace_object(self):
    """Ensures that whitespace is allowed in <Permission> elements."""
    obj_uri = suri(self.CreateObject(contents='foo'))
    acl_string = self.RunGsUtil(['getacl', obj_uri], return_stdout=True)
    acl_string = re.sub(r'<Permission>', r'<Permission> \n', acl_string)
    acl_string = re.sub(r'</Permission>', r'\n </Permission>', acl_string)
    inpath = self.CreateTempFile(contents=acl_string)
    self.RunGsUtil(['setacl', inpath, obj_uri])

  def test_set_valid_acl_bucket(self):
    """Ensures that valid canned and XML ACLs work with get/set."""
    bucket_uri = suri(self.CreateBucket())
    acl_string = self.RunGsUtil(['getacl', bucket_uri], return_stdout=True)
    inpath = self.CreateTempFile(contents=acl_string)
    self.RunGsUtil(['setacl', 'public-read', bucket_uri])
    acl_string2 = self.RunGsUtil(['getacl', bucket_uri], return_stdout=True)
    self.RunGsUtil(['setacl', inpath, bucket_uri])
    acl_string3 = self.RunGsUtil(['getacl', bucket_uri], return_stdout=True)

    self.assertNotEqual(acl_string, acl_string2)
    self.assertEqual(acl_string, acl_string3)

  def test_get_and_set_valid_object_acl_with_non_ascii_chars(self):
    """Ensures that non-ASCII chars work correctly in ACL handling."""
    acl_entry_str = """
        <Entry>
            <Scope type="UserByEmail">
                <EmailAddress>gs-team@google.com</EmailAddress>
                <Name>%s</Name>
            </Scope>
            <Permission>READ</Permission>
        </Entry>
"""
    non_ascii_name = u'Test NonAscii łرح안'
    acl_entry_str = acl_entry_str % non_ascii_name
    obj_uri = self.CreateObject(contents='foo')
    stdout = self.RunGsUtil(['getacl', suri(obj_uri)], return_stdout=True)
    new_acl_str = re.sub('</Entries>', '%s</Entries>' % acl_entry_str, stdout)
    acl_path = self.CreateTempFile(contents=new_acl_str.encode('utf-8'))
    self.RunGsUtil(['setacl', acl_path, suri(obj_uri)])
    res_acl_str = self.RunGsUtil(['getacl', suri(obj_uri)], return_stdout=True)
    self.assertIn(non_ascii_name.encode('utf-8'), res_acl_str)

  def test_invalid_canned_acl_object(self):
    """Ensures that an invalid canned ACL returns a CommandException."""
    obj_uri = suri(self.CreateObject(contents='foo'))
    stderr = self.RunGsUtil(['setacl', 'not-a-canned-acl',
                             obj_uri], return_stderr=True, expected_status=1)
    self.assertIn('CommandException', stderr)
    self.assertIn('Invalid canned ACL', stderr)

  def test_set_valid_def_acl_bucket(self):
    """Ensures that valid default canned and XML ACLs works with get/set."""
    bucket_uri = self.CreateBucket()

    # Default ACL is project private.
    obj_uri1 = suri(self.CreateObject(bucket_uri=bucket_uri, contents='foo'))
    acl_string = self.RunGsUtil(['getacl', obj_uri1], return_stdout=True)

    # Change it to authenticated-read.
    self.RunGsUtil(['setdefacl', 'authenticated-read', suri(bucket_uri)])
    obj_uri2 = suri(self.CreateObject(bucket_uri=bucket_uri, contents='foo2'))
    acl_string2 = self.RunGsUtil(['getacl', obj_uri2], return_stdout=True)

    # Now change it back to the default via XML.
    inpath = self.CreateTempFile(contents=acl_string)
    self.RunGsUtil(['setdefacl', inpath, suri(bucket_uri)])
    obj_uri3 = suri(self.CreateObject(bucket_uri=bucket_uri, contents='foo3'))
    acl_string3 = self.RunGsUtil(['getacl', obj_uri3], return_stdout=True)

    self.assertNotEqual(acl_string, acl_string2)
    self.assertIn('AllAuthenticatedUsers', acl_string2)
    self.assertEqual(acl_string, acl_string3)

  def test_setacl_version_specific_uri(self):
    bucket_uri = self.CreateVersionedBucket()
    # Create initial object version.
    uri = self.CreateObject(bucket_uri=bucket_uri, contents='data')
    # Create a second object version.
    inpath = self.CreateTempFile(contents='def')
    self.RunGsUtil(['cp', inpath, uri.uri])

    # Find out the two object version IDs.
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, delay=1, backoff=1)
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
      acl = self.RunGsUtil(['getacl', uri_str], return_stdout=True)
      self.assertNotIn(PUBLIC_READ_ACL_TEXT, self._strip_xml_whitespace(acl))
      orig_acls.append(acl)

    # Set the ACL for the older version of the object to public-read.
    self.RunGsUtil(['setacl', 'public-read', v0_uri_str])
    # Check that the older version's ACL is public-read, but newer version
    # is not.
    acl = self.RunGsUtil(['getacl', v0_uri_str], return_stdout=True)
    self.assertIn(PUBLIC_READ_ACL_TEXT, self._strip_xml_whitespace(acl))
    acl = self.RunGsUtil(['getacl', v1_uri_str], return_stdout=True)
    self.assertNotIn(PUBLIC_READ_ACL_TEXT, self._strip_xml_whitespace(acl))

    # Check that reading the ACL with the version-less URI returns the
    # original ACL (since the version-less URI means the current version).
    acl = self.RunGsUtil(['getacl', uri.uri], return_stdout=True)
    self.assertEqual(acl, orig_acls[0])

  def _strip_xml_whitespace(self, xml):
    s = re.sub('>\s*', '>', xml.replace('\n', ''))
    return re.sub('\s*<', '<', s)
