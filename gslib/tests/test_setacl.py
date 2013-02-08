# -*- coding: utf-8 -*-
# Copyright 2013 Google Inc.
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
import re
from gslib.tests.util import ObjectToURI as suri

PUBLIC_READ_ACL_TEXT = '<Scope type="AllUsers"/><Permission>READ</Permission>'


class TestSetAcl(testcase.GsUtilIntegrationTestCase):
  """Integration tests for setacl command."""

  def test_setacl_version_specific_uri(self):
    bucket_uri = self.CreateVersionedBucket()
    # Create initial object version.
    uri = self.CreateObject(bucket_uri=bucket_uri, contents='data')
    # Create a second object version.
    inpath = self.CreateTempFile(contents='def')
    self.RunGsUtil(['cp', inpath, uri.uri])

    # Find out the two object version IDs.
    stdout = self.RunGsUtil(['ls', '-a', uri.uri], return_stdout=True)
    lines = stdout.split('\n')
    # There should be 3 lines, counting final \n.
    self.assertEqual(len(lines), 3)
    v0_uri_str = lines[0]
    v1_uri_str = lines[1]

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
    return re.sub('> *<','><', xml.replace('\n',''))
