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
"""Integration tests for bucketpolicyonly command."""

from __future__ import absolute_import
import re
from unittest import mock

from gslib import exception
from gslib.commands import bucketpolicyonly
from gslib.cs_api_map import ApiSelector
import gslib.tests.testcase as testcase
from gslib.tests.testcase.integration_testcase import SkipForXML
from gslib.tests.util import ObjectToURI as suri
from gslib.tests.util import SetBotoConfigForTest
from gslib.tests.util import SetEnvironmentForTest
from gslib.tests.util import unittest
from gslib.utils import shim_util
from gslib.utils.retry_util import Retry


class TestBucketPolicyOnlyUnit(testcase.GsUtilUnitTestCase):

  def test_set_invalid_mode_fails(self):
    with self.assertRaisesRegex(exception.CommandException,
                                'Only on and off values allowed'):
      self.RunCommand('bucketpolicyonly', ['set', 'invalid_mode', 'gs://bucket'])

  def test_s3_fails(self):
    bucket_uri = self.CreateBucket(provider='s3')
    with self.assertRaisesRegex(exception.CommandException,
                                'only be used with gs:// bucket URLs'):
      self.RunCommand('bucketpolicyonly', ['set', 'on', suri(bucket_uri)])


class TestBucketPolicyOnly(testcase.GsUtilIntegrationTestCase):
  """Integration tests for bucketpolicyonly command."""

  _set_bpo_cmd = ['bucketpolicyonly', 'set']
  _get_bpo_cmd = ['bucketpolicyonly', 'get']

  def _AssertEnabled(self, bucket_uri, value):
    stdout = self.RunGsUtil(self._get_bpo_cmd + [suri(bucket_uri)],
                            return_stdout=True)
    bucket_policy_only_re = re.compile(r'^\s*Enabled:\s+(?P<enabled_val>.+)$',
                                       re.MULTILINE)
    bucket_policy_only_match = re.search(bucket_policy_only_re, stdout)
    bucket_policy_only_val = bucket_policy_only_match.group('enabled_val')
    self.assertEqual(str(value), bucket_policy_only_val)

  @SkipForXML('XML API has no concept of Bucket Policy Only')
  def test_off_on_default_buckets(self):
    bucket_uri = self.CreateBucket()
    self._AssertEnabled(bucket_uri, False)

  @SkipForXML('XML API has no concept of Bucket Policy Only')
  def test_turning_off_on_enabled_buckets(self):
    bucket_uri = self.CreateBucket(bucket_policy_only=True,
                                   prefer_json_api=True)
    self._AssertEnabled(bucket_uri, True)

    self.RunGsUtil(self._set_bpo_cmd + ['off', suri(bucket_uri)])
    self._AssertEnabled(bucket_uri, False)

  @SkipForXML('XML API has no concept of Bucket Policy Only')
  def test_turning_on(self):
    bucket_uri = self.CreateBucket()
    self.RunGsUtil(self._set_bpo_cmd + ['on', suri(bucket_uri)])

    self._AssertEnabled(bucket_uri, True)

  @SkipForXML('XML API has no concept of Bucket Policy Only')
  def test_turning_on_and_off(self):
    bucket_uri = self.CreateBucket()

    self.RunGsUtil(self._set_bpo_cmd + ['on', suri(bucket_uri)])
    self._AssertEnabled(bucket_uri, True)

    self.RunGsUtil(self._set_bpo_cmd + ['off', suri(bucket_uri)])
    self._AssertEnabled(bucket_uri, False)

  def testTooFewArgumentsFails(self):
    """Ensures bucketpolicyonly commands fail with too few arguments."""
    # No arguments for set, but valid subcommand.
    stderr = self.RunGsUtil(self._set_bpo_cmd,
                            return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

    # No arguments for get, but valid subcommand.
    stderr = self.RunGsUtil(self._get_bpo_cmd,
                            return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

    # Neither arguments nor subcommand.
    stderr = self.RunGsUtil(['bucketpolicyonly'],
                            return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

  @SkipForXML('XML API has no concept of Bucket Policy Only')
  def test_get_nonexistent_bucket(self):
    stderr = self.RunGsUtil(self._get_bpo_cmd + ['gs://' + self.nonexistent_bucket_name],
                            return_stderr=True,
                            expected_status=1)
    self.assertRegex(stderr, r'(BucketNotFoundException|404)')

  @SkipForXML('XML API has no concept of Bucket Policy Only')
  def test_set_nonexistent_bucket(self):
    stderr = self.RunGsUtil(self._set_bpo_cmd + ['on', 'gs://' + self.nonexistent_bucket_name],
                            return_stderr=True,
                            expected_status=1)
    self.assertRegex(stderr, r'(BucketNotFoundException|404)')

  @SkipForXML('XML API has no concept of Bucket Policy Only')
  def test_set_multiple_buckets(self):
    bucket_uri1 = self.CreateBucket()
    bucket_uri2 = self.CreateBucket()

    # Set both to 'on'.
    self.RunGsUtil(self._set_bpo_cmd + ['on', suri(bucket_uri1), suri(bucket_uri2)])
    self._AssertEnabled(bucket_uri1, True)
    self._AssertEnabled(bucket_uri2, True)

    # Set both to 'off'.
    self.RunGsUtil(self._set_bpo_cmd + ['off', suri(bucket_uri1), suri(bucket_uri2)])
    self._AssertEnabled(bucket_uri1, False)
    self._AssertEnabled(bucket_uri2, False)


class TestBucketPolicyOnlyShim(testcase.ShimUnitTestBase):

  @mock.patch.object(bucketpolicyonly.BucketPolicyOnlyCommand, '_GetBucketPolicyOnly', new=mock.Mock())
  def test_shim_translates_get_command(self):
    bucket_uri = self.CreateBucket()
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand('bucketpolicyonly', [
            'get',
            suri(bucket_uri),
        ],
                                           return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        expected_format = (
            '--format=multi[terminator="%s"](name:format="value(format(\'Bucket Policy Only setting for gs://{}:\'))", iamConfiguration.uniformBucketLevelAccess.enabled.yesno(no="False"):format="value[terminator=\'%s\'](format(\'  Enabled: {}\'))", iamConfiguration.uniformBucketLevelAccess.lockedTime.sub("T", " "):format="value(format(\'  LockedTime: {}\'))")'
        ) % (shim_util.get_format_flag_newline(), shim_util.get_format_flag_newline())

        expected_command = (
            'Gcloud Storage Command: %s storage buckets list %s --raw %s'
        ) % (
            shim_util._get_gcloud_binary_path('fake_dir'),
            expected_format,
            suri(bucket_uri),
        )
        self.assertIn(expected_command, info_lines)

  @mock.patch.object(bucketpolicyonly.BucketPolicyOnlyCommand, '_SetBucketPolicyOnly', new=mock.Mock())
  def test_shim_translates_set_on_command(self):
    bucket_uri = self.CreateBucket()
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand('bucketpolicyonly', [
            'set',
            'on',
            suri(bucket_uri),
        ],
                                           return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        expected_command = (
            'Gcloud Storage Command: %s storage buckets update'
            ' --uniform-bucket-level-access %s'
        ) % (shim_util._get_gcloud_binary_path('fake_dir'), suri(bucket_uri))
        self.assertIn(expected_command, info_lines)

  @mock.patch.object(bucketpolicyonly.BucketPolicyOnlyCommand, '_SetBucketPolicyOnly', new=mock.Mock())
  def test_shim_translates_set_off_command(self):
    bucket_uri = self.CreateBucket()
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand('bucketpolicyonly', [
            'set',
            'off',
            suri(bucket_uri),
        ],
                                           return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        expected_command = (
            'Gcloud Storage Command: %s storage buckets update'
            ' --no-uniform-bucket-level-access %s'
        ) % (shim_util._get_gcloud_binary_path('fake_dir'), suri(bucket_uri))
        self.assertIn(expected_command, info_lines)
