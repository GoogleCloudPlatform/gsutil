# -*- coding: utf-8 -*-
# Copyright 2018 Google Inc. All Rights Reserved.
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
"""Integration tests for pap command."""

from __future__ import absolute_import

import gslib.tests.testcase as testcase
from gslib.tests.testcase.integration_testcase import SkipForGS
from gslib.tests.testcase.integration_testcase import SkipForJSON
from gslib.tests.testcase.integration_testcase import SkipForXML
from gslib.tests.util import ObjectToURI as suri


class TestPublicAccessPrevention(testcase.GsUtilIntegrationTestCase):
  """Integration tests for pap command."""

  _set_pap_cmd = ['pap', 'set']
  _get_pap_cmd = ['pap', 'get']

  @SkipForXML('Public access prevention only runs on GCS JSON API')
  def test_off_on_default_buckets(self):
    bucket_uri = self.CreateBucket()
    self.VerifyPublicAccessPreventionValue(bucket_uri, 'unspecified')

  @SkipForXML('Public access prevention only runs on GCS JSON API')
  def test_turning_off_on_enabled_buckets(self):
    bucket_uri = self.CreateBucket(public_access_prevention='enforced',
                                   prefer_json_api=True)
    self.VerifyPublicAccessPreventionValue(bucket_uri, 'enforced')

    self.RunGsUtil(self._set_pap_cmd + ['unspecified', suri(bucket_uri)])
    self.VerifyPublicAccessPreventionValue(bucket_uri, 'unspecified')

  @SkipForXML('Public access prevention only runs on GCS JSON API')
  def test_turning_on(self):
    bucket_uri = self.CreateBucket()
    self.RunGsUtil(self._set_pap_cmd + ['enforced', suri(bucket_uri)])

    self.VerifyPublicAccessPreventionValue(bucket_uri, 'enforced')

  @SkipForXML('Public access prevention only runs on GCS JSON API')
  def test_turning_on_and_off(self):
    bucket_uri = self.CreateBucket()

    self.RunGsUtil(self._set_pap_cmd + ['enforced', suri(bucket_uri)])
    self.VerifyPublicAccessPreventionValue(bucket_uri, 'enforced')

    self.RunGsUtil(self._set_pap_cmd + ['unspecified', suri(bucket_uri)])
    self.VerifyPublicAccessPreventionValue(bucket_uri, 'unspecified')

  def test_multiple_buckets(self):
    bucket_uri1 = self.CreateBucket()
    bucket_uri2 = self.CreateBucket()
    stdout = self.RunGsUtil(
        self._get_pap_cmd +
        [suri(bucket_uri1), suri(bucket_uri2)],
        return_stdout=True)
    self.assertRegex(stdout, r'%s:\s+unspecified' % suri(bucket_uri1))
    self.assertRegex(stdout, r'%s:\s+unspecified' % suri(bucket_uri2))

  @SkipForJSON('Testing XML only behavior')
  def test_xml_fails(self):
    stderr = self.RunGsUtil(self._set_pap_cmd,
                            return_stderr=True,
                            expected_status=1)
    self.assertIn(
        'set command can only be used for GCS Buckets with the Cloud Storage JSON API',
        stderr)

    stderr = self.RunGsUtil(self._get_pap_cmd,
                            return_stderr=True,
                            expected_status=1)
    self.assertIn(
        'get command can only be used for GCS Buckets with the Cloud Storage JSON API',
        stderr)

  @SkipForGS('Testing S3 only behavior')
  def test_s3_fails(self):
    stderr = self.RunGsUtil(self._set_pap_cmd,
                            return_stderr=True,
                            expected_status=1)
    self.assertIn(
        'set command can only be used for GCS Buckets with the Cloud Storage JSON API',
        stderr)

    stderr = self.RunGsUtil(self._get_pap_cmd,
                            return_stderr=True,
                            expected_status=1)
    self.assertIn(
        'get command can only be used for GCS Buckets with the Cloud Storage JSON API',
        stderr)

  def test_too_few_arguments_fails(self):
    """Ensures pap commands fail with too few arguments."""
    # No arguments for set, but valid subcommand.
    stderr = self.RunGsUtil(self._set_pap_cmd,
                            return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

    # No arguments for get, but valid subcommand.
    stderr = self.RunGsUtil(self._get_pap_cmd,
                            return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

    # Neither arguments nor subcommand.
    stderr = self.RunGsUtil(['pap'], return_stderr=True, expected_status=1)
    self.assertIn('command requires at least', stderr)
