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
"""Integration tests for publicaccessprevention command."""

from __future__ import absolute_import

from gslib.cs_api_map import ApiSelector
import gslib.tests.testcase as testcase
from gslib.tests.util import ObjectToURI as suri
from gslib.tests.util import unittest


class TestPublicAccessPrevention(testcase.GsUtilIntegrationTestCase):
  """Integration tests for publicaccessprevention command."""

  _set_publicaccessprevention_cmd = ['publicaccessprevention', 'set']
  _get_publicaccessprevention_cmd = ['publicaccessprevention', 'get']

  def test_off_on_default_buckets(self):
    if self.test_api == ApiSelector.XML:
      return unittest.skip('XML API has no concept of Public Access Prevention')
    bucket_uri = self.CreateBucket()
    self.VerifyPublicAccessPreventionValue(bucket_uri, 'unspecified')

  def test_turning_off_on_enabled_buckets(self):
    if self.test_api == ApiSelector.XML:
      return unittest.skip('XML API has no concept of Public Access Prevention')
    bucket_uri = self.CreateBucket(
        public_access_prevention='enforced', prefer_json_api=True)
    self.VerifyPublicAccessPreventionValue(bucket_uri, 'enforced')

    self.RunGsUtil(self._set_publicaccessprevention_cmd +
                   ['unspecified', suri(bucket_uri)])
    self.VerifyPublicAccessPreventionValue(bucket_uri, 'unspecified')

  def test_turning_on(self):
    if self.test_api == ApiSelector.XML:
      return unittest.skip('XML API has no concept of Public Access Prevention')

    bucket_uri = self.CreateBucket()
    self.RunGsUtil(self._set_publicaccessprevention_cmd +
                   ['enforced', suri(bucket_uri)])

    self.VerifyPublicAccessPreventionValue(bucket_uri, 'enforced')

  def test_turning_on_and_off(self):
    if self.test_api == ApiSelector.XML:
      return unittest.skip('XML API has no concept of Public Access Prevention')

    bucket_uri = self.CreateBucket()

    self.RunGsUtil(self._set_publicaccessprevention_cmd +
                   ['enforced', suri(bucket_uri)])
    self.VerifyPublicAccessPreventionValue(bucket_uri, 'enforced')

    self.RunGsUtil(self._set_publicaccessprevention_cmd +
                   ['unspecified', suri(bucket_uri)])
    self.VerifyPublicAccessPreventionValue(bucket_uri, 'unspecified')

  def test_too_few_arguments_fails(self):
    """Ensures publicaccessprevention commands fail with too few arguments."""
    # No arguments for set, but valid subcommand.
    stderr = self.RunGsUtil(
        self._set_publicaccessprevention_cmd,
        return_stderr=True,
        expected_status=1)
    self.assertIn('command requires at least', stderr)

    # No arguments for get, but valid subcommand.
    stderr = self.RunGsUtil(
        self._get_publicaccessprevention_cmd,
        return_stderr=True,
        expected_status=1)
    self.assertIn('command requires at least', stderr)

    # Neither arguments nor subcommand.
    stderr = self.RunGsUtil(['publicaccessprevention'],
                            return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)
