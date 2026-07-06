# -*- coding: utf-8 -*-
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
"""Integration tests for versioning command."""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

from gslib.commands import versioning
import gslib.tests.testcase as testcase
from gslib.tests.util import ObjectToURI as suri
from gslib.tests.util import SetBotoConfigForTest
from gslib.tests.util import SetEnvironmentForTest
from gslib.utils import shim_util
from gslib.utils.retry_util import Retry
from unittest import mock


class TestVersioning(testcase.GsUtilIntegrationTestCase):
  """Integration tests for versioning command."""

  _set_ver_cmd = ['versioning', 'set']
  _get_ver_cmd = ['versioning', 'get']

  def test_off_default(self):
    bucket_uri = self.CreateBucket()
    stdout = self.RunGsUtil(self._get_ver_cmd + [suri(bucket_uri)],
                            return_stdout=True)
    self.assertEqual(stdout.strip(), '%s: Suspended' % suri(bucket_uri))

  def test_turning_on(self):
    bucket_uri = self.CreateBucket()
    self.RunGsUtil(self._set_ver_cmd + ['on', suri(bucket_uri)])

    # Work around eventual consistency for S3 versioning.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(self._get_ver_cmd + [suri(bucket_uri)],
                              return_stdout=True)
      self.assertEqual(stdout.strip(), '%s: Enabled' % suri(bucket_uri))

    _Check1()

  def test_turning_off(self):
    bucket_uri = self.CreateBucket()
    self.RunGsUtil(self._set_ver_cmd + ['on', suri(bucket_uri)])

    # Work around eventual consistency for S3 versioning.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(self._get_ver_cmd + [suri(bucket_uri)],
                              return_stdout=True)
      self.assertEqual(stdout.strip(), '%s: Enabled' % suri(bucket_uri))

    _Check1()

    self.RunGsUtil(self._set_ver_cmd + ['off', suri(bucket_uri)])

    # Work around eventual consistency for S3 versioning.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check2():
      stdout = self.RunGsUtil(self._get_ver_cmd + [suri(bucket_uri)],
                              return_stdout=True)
      self.assertEqual(stdout.strip(), '%s: Suspended' % suri(bucket_uri))

    _Check2()

  def testTooFewArgumentsFails(self):
    """Ensures versioning commands fail with too few arguments."""
    # No arguments for set, but valid subcommand.
    stderr = self.RunGsUtil(self._set_ver_cmd,
                            return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

    # No arguments for get, but valid subcommand.
    stderr = self.RunGsUtil(self._get_ver_cmd,
                            return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

    # Neither arguments nor subcommand.
    stderr = self.RunGsUtil(['versioning'],
                            return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

  def test_versioning_invalid_arguments(self):
    """Tests versioning command failure modes with invalid subcommands, settings or URLs."""
    bucket_uri = self.CreateBucket()

    # 1. Invalid subcommand
    stderr = self.RunGsUtil(['versioning', 'invalid', suri(bucket_uri)], expected_status=1, return_stderr=True)
    self.assertIn('Invalid subcommand "invalid"', stderr)

    # 2. Invalid setting value
    stderr = self.RunGsUtil(['versioning', 'set', 'maybe', suri(bucket_uri)], expected_status=1, return_stderr=True)
    self.assertIn('must be either <on|off>', stderr)

    # 3. Provider URL
    stderr = self.RunGsUtil(['versioning', 'get', 'gs://'], expected_status=1, return_stderr=True)
    self.assertIn('does not support provider-only URLs', stderr)



class TestVersioningOldAlias(TestVersioning):
  _set_ver_cmd = ['setversioning']
  _get_ver_cmd = ['getversioning']


class TestVersioningShim(testcase.ShimUnitTestBase):

  @mock.patch.object(versioning.VersioningCommand, '_GetVersioning', new=mock.Mock())
  def test_shim_translates_get_command(self):
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand('versioning', ['get', 'gs://bucket'],
                                           return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(
            ('Gcloud Storage Command: {} storage buckets list --raw'
             ' {} gs://bucket'
            ).format(shim_util._get_gcloud_binary_path('fake_dir'),
                     versioning._GCLOUD_FORMAT_STRING), info_lines)

  @mock.patch.object(versioning.VersioningCommand, '_SetVersioning', new=mock.Mock())
  def test_shim_translates_set_on_command(self):
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand('versioning', ['set', 'on', 'gs://bucket'],
                                           return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(
            ('Gcloud Storage Command: {} storage buckets update --versioning gs://bucket'
            ).format(shim_util._get_gcloud_binary_path('fake_dir')), info_lines)

  @mock.patch.object(versioning.VersioningCommand, '_SetVersioning', new=mock.Mock())
  def test_shim_translates_set_off_command(self):
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand('versioning', ['set', 'off', 'gs://bucket'],
                                           return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(
            ('Gcloud Storage Command: {} storage buckets update --no-versioning gs://bucket'
            ).format(shim_util._get_gcloud_binary_path('fake_dir')), info_lines)

