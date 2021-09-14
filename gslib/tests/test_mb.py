# -*- coding: utf-8 -*-
# Copyright 2014 Google Inc. All Rights Reserved.
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
"""Integration tests for mb command."""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

import boto
import gslib.tests.testcase as testcase
from gslib.tests.testcase.integration_testcase import SkipForS3
from gslib.tests.testcase.integration_testcase import SkipForXML
from gslib.tests.testcase.integration_testcase import SkipForJSON
from gslib.tests.util import ObjectToURI as suri
from gslib.utils.retention_util import SECONDS_IN_DAY
from gslib.utils.retention_util import SECONDS_IN_MONTH
from gslib.utils.retention_util import SECONDS_IN_YEAR

BUCKET_LOCK_SKIP_MSG = ('gsutil does not support bucket lock operations for '
                        'S3 buckets.')


class TestMb(testcase.GsUtilIntegrationTestCase):
  """Integration tests for mb command."""

  @SkipForS3('S3 returns success when bucket already exists.')
  def test_mb_bucket_exists(self):
    bucket_uri = self.CreateBucket()
    stderr = self.RunGsUtil(['mb', suri(bucket_uri)],
                            expected_status=1,
                            return_stderr=True)
    self.assertIn('already exists', stderr)

  def test_non_ascii_project_fails(self):
    stderr = self.RunGsUtil(['mb', '-p', 'ã', 'gs://fobarbaz'],
                            expected_status=1,
                            return_stderr=True)
    self.assertIn('Invalid non-ASCII', stderr)

  @SkipForS3(BUCKET_LOCK_SKIP_MSG)
  def test_create_with_retention_seconds(self):
    bucket_name = self.MakeTempName('bucket')
    bucket_uri = boto.storage_uri('gs://%s' % (bucket_name.lower()),
                                  suppress_consec_slashes=False)
    self.RunGsUtil(['mb', '--retention', '60s', suri(bucket_uri)])
    self.VerifyRetentionPolicy(bucket_uri,
                               expected_retention_period_in_seconds=60)

  @SkipForS3(BUCKET_LOCK_SKIP_MSG)
  def test_create_with_retention_days(self):
    bucket_name = self.MakeTempName('bucket')
    bucket_uri = boto.storage_uri('gs://%s' % (bucket_name.lower()),
                                  suppress_consec_slashes=False)
    self.RunGsUtil(['mb', '--retention', '1d', suri(bucket_uri)])
    self.VerifyRetentionPolicy(
        bucket_uri, expected_retention_period_in_seconds=SECONDS_IN_DAY)

  @SkipForS3(BUCKET_LOCK_SKIP_MSG)
  def test_create_with_retention_months(self):
    bucket_name = self.MakeTempName('bucket')
    bucket_uri = boto.storage_uri('gs://%s' % (bucket_name.lower()),
                                  suppress_consec_slashes=False)
    self.RunGsUtil(['mb', '--retention', '1m', suri(bucket_uri)])
    self.VerifyRetentionPolicy(
        bucket_uri, expected_retention_period_in_seconds=SECONDS_IN_MONTH)

  @SkipForS3(BUCKET_LOCK_SKIP_MSG)
  def test_create_with_retention_years(self):
    bucket_name = self.MakeTempName('bucket')
    bucket_uri = boto.storage_uri('gs://%s' % (bucket_name.lower()),
                                  suppress_consec_slashes=False)
    self.RunGsUtil(['mb', '--retention', '1y', suri(bucket_uri)])
    self.VerifyRetentionPolicy(
        bucket_uri, expected_retention_period_in_seconds=SECONDS_IN_YEAR)

  @SkipForS3(BUCKET_LOCK_SKIP_MSG)
  def test_create_with_retention_invalid_arg(self):
    bucket_name = self.MakeTempName('bucket')
    bucket_uri = boto.storage_uri('gs://%s' % (bucket_name.lower()),
                                  suppress_consec_slashes=False)
    stderr = self.RunGsUtil(['mb', '--retention', '1second',
                             suri(bucket_uri)],
                            expected_status=1,
                            return_stderr=True)
    self.assertRegexpMatches(stderr, r'Incorrect retention period specified')

  def test_create_with_retention_on_s3_urls_fails(self):
    bucket_name = self.MakeTempName('bucket')
    bucket_uri = boto.storage_uri('s3://%s' % (bucket_name.lower()),
                                  suppress_consec_slashes=False)
    stderr = self.RunGsUtil(
        ['mb', '--retention', '1y', suri(bucket_uri)],
        expected_status=1,
        return_stderr=True)
    self.assertRegexpMatches(
        stderr, r'Retention policy can only be specified for GCS buckets.')

  @SkipForXML('Public access prevention only runs on GCS JSON API.')
  def test_create_with_pap_enforced(self):
    bucket_name = self.MakeTempName('bucket')
    bucket_uri = boto.storage_uri('gs://%s' % (bucket_name.lower()),
                                  suppress_consec_slashes=False)
    self.RunGsUtil(['mb', '--pap', 'enforced', suri(bucket_uri)])
    self.VerifyPublicAccessPreventionValue(bucket_uri, 'enforced')

  @SkipForXML('Public access prevention only runs on GCS JSON API.')
  def test_create_with_pap_unspecified(self):
    bucket_name = self.MakeTempName('bucket')
    bucket_uri = boto.storage_uri('gs://%s' % (bucket_name.lower()),
                                  suppress_consec_slashes=False)
    self.RunGsUtil(['mb', '--pap', 'unspecified', suri(bucket_uri)])
    self.VerifyPublicAccessPreventionValue(bucket_uri, 'unspecified')

  @SkipForXML('Public access prevention only runs on GCS JSON API.')
  def test_create_with_pap_invalid_arg(self):
    bucket_name = self.MakeTempName('bucket')
    bucket_uri = boto.storage_uri('gs://%s' % (bucket_name.lower()),
                                  suppress_consec_slashes=False)
    stderr = self.RunGsUtil(['mb', '--pap', 'invalid_arg',
                             suri(bucket_uri)],
                            expected_status=1,
                            return_stderr=True)
    self.assertRegexpMatches(stderr, r'invalid_arg is not a valid value')

  @SkipForXML('RPO flag only works for GCS JSON API.')
  def test_create_with_rpo_async_turbo(self):
    bucket_name = self.MakeTempName('bucket')
    bucket_uri = boto.storage_uri('gs://%s' % (bucket_name.lower()),
                                  suppress_consec_slashes=False)
    self.RunGsUtil(
        ['mb', '-l', 'nam4', '--rpo', 'ASYNC_TURBO',
         suri(bucket_uri)])
    self.VerifyCommandGet(bucket_uri, 'rpo', 'ASYNC_TURBO')

  @SkipForXML('RPO flag only works for GCS JSON API.')
  def test_create_sets_rpo_to_default(self):
    bucket_name = self.MakeTempName('bucket')
    bucket_uri = boto.storage_uri('gs://%s' % (bucket_name.lower()),
                                  suppress_consec_slashes=False)
    self.RunGsUtil(['mb', '-l', 'nam4', suri(bucket_uri)])
    try:
      self.VerifyCommandGet(bucket_uri, 'rpo', 'DEFAULT')
    except AssertionError:
      # TODO: Remove the try/except block once we have consistent results
      # returned from the backend for rpo get.
      self.VerifyCommandGet(bucket_uri, 'rpo', 'None')

  @SkipForXML('RPO flag only works for GCS JSON API.')
  def test_create_with_rpo_async_turbo_fails_for_regional_bucket(self):
    """Turbo replication is only meant for dual-region."""
    bucket_name = self.MakeTempName('bucket')
    bucket_uri = boto.storage_uri('gs://%s' % (bucket_name.lower()),
                                  suppress_consec_slashes=False)
    stderr = self.RunGsUtil(
        ['mb', '-l', 'us-central1', '--rpo', 'ASYNC_TURBO',
         suri(bucket_uri)],
        return_stderr=True,
        expected_status=1)
    self.assertIn('Invalid argument', stderr)

  @SkipForXML('RPO flag only works for GCS JSON API.')
  def test_create_with_rpo_incorrect_value_raises_error(self):
    bucket_name = self.MakeTempName('bucket')
    bucket_uri = boto.storage_uri('gs://%s' % (bucket_name.lower()),
                                  suppress_consec_slashes=False)
    # Location nam4 is used for dual-region.
    stderr = self.RunGsUtil(
        ['mb', '-l', 'nam4', '--rpo', 'incorrect_value',
         suri(bucket_uri)],
        return_stderr=True,
        expected_status=1)
    self.assertIn(
        'Invalid value for --rpo. Must be one of: (ASYNC_TURBO|DEFAULT),'
        ' provided: incorrect_value', stderr)

  @SkipForXML('The --placement flag only works for GCS JSON API.')
  def test_create_with_placement_flag(self):
    bucket_name = self.MakeTempName('bucket')
    bucket_uri = boto.storage_uri('gs://%s' % (bucket_name.lower()),
                                  suppress_consec_slashes=False)
    self.RunGsUtil(
        ['mb', '--placement', 'us-central1,us-east1',
         suri(bucket_uri)])
    stdout = self.RunGsUtil(['ls', '-Lb', suri(bucket_uri)], return_stdout=True)
    self.assertRegex(stdout,
                     r"Placement locations:\t\t\['US-CENTRAL1', 'US-EAST1'\]")

  @SkipForXML('The --placement flag only works for GCS JSON API.')
  def test_create_with_invalid_placement_flag_raises_error(self):
    bucket_name = self.MakeTempName('bucket')
    bucket_uri = boto.storage_uri('gs://%s' % (bucket_name.lower()),
                                  suppress_consec_slashes=False)
    stderr = self.RunGsUtil(
        ['mb', '--placement', 'invalid_reg1,invalid_reg2',
         suri(bucket_uri)],
        return_stderr=True,
        expected_status=1)
    self.assertIn('BadRequestException: 400 Invalid custom placement config',
                  stderr)

  @SkipForXML('The --placement flag only works for GCS JSON API.')
  def test_create_with_incorrect_number_of_placement_values_raises_error(self):
    bucket_name = self.MakeTempName('bucket')
    bucket_uri = boto.storage_uri('gs://%s' % (bucket_name.lower()),
                                  suppress_consec_slashes=False)
    # Location nam4 is used for dual-region.
    stderr = self.RunGsUtil(
        ['mb', '--placement', 'val1,val2,val3',
         suri(bucket_uri)],
        return_stderr=True,
        expected_status=1)
    self.assertIn(
        'CommandException: Please specify two regions separated by comma'
        ' without space. Specified: val1,val2,val3', stderr)

  @SkipForJSON('Testing XML only behavior.')
  def test_single_json_only_flag_raises_error_with_xml_api(self):
    bucket_name = self.MakeTempName('bucket')
    bucket_uri = boto.storage_uri('gs://%s' % (bucket_name.lower()),
                                  suppress_consec_slashes=False)
    stderr = self.RunGsUtil(['mb', '--rpo', 'ASYNC_TURBO',
                             suri(bucket_uri)],
                            return_stderr=True,
                            expected_status=1)
    self.assertIn(
        'CommandException: The --rpo option(s) can only be used'
        ' for GCS Buckets with the JSON API', stderr)

  @SkipForJSON('Testing XML only behavior.')
  def test_multiple_json_only_flags_raise_error_with_xml_api(self):
    bucket_name = self.MakeTempName('bucket')
    bucket_uri = boto.storage_uri('gs://%s' % (bucket_name.lower()),
                                  suppress_consec_slashes=False)
    stderr = self.RunGsUtil([
        'mb', '--autoclass', '--pap', 'enabled', '--placement',
        'uscentral-1,us-asia1', '--rpo', 'ASYNC_TURBO', '-b', 'on',
        suri(bucket_uri)
    ],
                            return_stderr=True,
                            expected_status=1)
    self.assertIn(
        'CommandException: The --autoclass, --pap, --placement, --rpo,'
        ' -b option(s) can only be used for GCS Buckets with the JSON API',
        stderr)
