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
"""Integration tests for logging command."""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

import gslib.tests.testcase as testcase
from gslib.tests.testcase.integration_testcase import SkipForS3
from gslib.tests.util import ObjectToURI as suri


@SkipForS3('Logging command requires S3 ACL configuration on target bucket.')
class TestLogging(testcase.GsUtilIntegrationTestCase):
  """Integration tests for logging command."""

  _enable_log_cmd = ['logging', 'set', 'on']
  _disable_log_cmd = ['logging', 'set', 'off']
  _get_log_cmd = ['logging', 'get']

  def testLogging(self):
    """Tests enabling and disabling logging."""
    bucket_uri = self.CreateBucket()
    bucket_suri = suri(bucket_uri)
    stderr = self.RunGsUtil(self._enable_log_cmd +
                            ['-b', bucket_suri, bucket_suri],
                            return_stderr=True)
    if self._use_gcloud_storage:
      self.assertIn('Updating', stderr)
    else:
      self.assertIn('Enabling logging', stderr)

    stdout = self.RunGsUtil(self._get_log_cmd + [bucket_suri],
                            return_stdout=True)
    if self._use_gcloud_storage:
      _, _, prefixless_bucket = bucket_suri.partition('://')
      self.assertIn('"logBucket": "{}"'.format(prefixless_bucket), stdout)
      self.assertIn('"logObjectPrefix": "{}"'.format(prefixless_bucket), stdout)
    else:
      self.assertIn('LogObjectPrefix'.lower(), stdout.lower())

    stderr = self.RunGsUtil(self._disable_log_cmd + [bucket_suri],
                            return_stderr=True)
    if self._use_gcloud_storage:
      self.assertIn('Updating', stderr)
    else:
      self.assertIn('Disabling logging', stderr)

  def testTooFewArgumentsFails(self):
    """Ensures logging commands fail with too few arguments."""
    # No arguments for enable, but valid subcommand.
    stderr = self.RunGsUtil(self._enable_log_cmd,
                            return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

    # No arguments for disable, but valid subcommand.
    stderr = self.RunGsUtil(self._disable_log_cmd,
                            return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

    # No arguments for get, but valid subcommand.
    stderr = self.RunGsUtil(self._get_log_cmd,
                            return_stderr=True,
                            expected_status=1)
    self.assertIn('command requires at least', stderr)

    # Neither arguments nor subcommand.
    stderr = self.RunGsUtil(['logging'], return_stderr=True, expected_status=1)
    self.assertIn('command requires at least', stderr)

  def testLoggingGetNoConfig(self):
    bucket_uri = self.CreateBucket()
    bucket_suri = suri(bucket_uri)
    stdout = self.RunGsUtil(['logging', 'get', bucket_suri], return_stdout=True)
    self.assertIn('has no logging configuration', stdout)

  def testLoggingSpanningProvidersFails(self):
    stderr = self.RunGsUtil(['logging', 'set', 'on', '-b', 'gs://logbucket', 'gs://bucket', 's3://bucket'],
                            return_stderr=True, expected_status=1)
    self.assertIn('spanning providers not allowed', stderr)

  def testLoggingMissingLogBucketFails(self):
    bucket_uri = self.CreateBucket()
    bucket_suri = suri(bucket_uri)
    stderr = self.RunGsUtil(['logging', 'set', 'on', bucket_suri],
                            return_stderr=True, expected_status=1)
    self.assertIn('requires \'-b <log_bucket>\'', stderr)

  def testLoggingNonBucketLogBucketFails(self):
    bucket_uri = self.CreateBucket()
    bucket_suri = suri(bucket_uri)
    stderr = self.RunGsUtil(['logging', 'set', 'on', '-b', bucket_suri + '/obj', bucket_suri],
                            return_stderr=True, expected_status=1)
    self.assertIn('must specify a bucket URL', stderr)

  def testInvalidSubcommandsFails(self):
    bucket_uri = self.CreateBucket()
    bucket_suri = suri(bucket_uri)
    stderr = self.RunGsUtil(['logging', 'invalid', bucket_suri],
                            return_stderr=True, expected_status=1)
    self.assertIn('Invalid subcommand "invalid"', stderr)

    stderr = self.RunGsUtil(['logging', 'set', 'invalid', bucket_suri],
                            return_stderr=True, expected_status=1)
    self.assertIn('Invalid subcommand "invalid" for the "logging set"', stderr)



class TestLoggingOldAlias(TestLogging):
  _enable_log_cmd = ['enablelogging']
  _disable_log_cmd = ['disablelogging']
  _get_log_cmd = ['getlogging']
