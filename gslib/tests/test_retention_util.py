# -*- coding: utf-8 -*-
# Copyright 2017 Google Inc. All Rights Reserved.
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
"""Unit tests for retention_util module."""

from __future__ import absolute_import

from unittest import mock

import gslib.tests.testcase as testcase
from gslib.utils.retention_util import _RetentionPeriodToString
from gslib.utils.retention_util import DaysToSeconds
from gslib.utils.retention_util import MonthsToSeconds
from gslib.utils.retention_util import RetentionInDaysMatch
from gslib.utils.retention_util import RetentionInMonthsMatch
from gslib.utils.retention_util import RetentionInSeconds
from gslib.utils.retention_util import RetentionInSecondsMatch
from gslib.utils.retention_util import RetentionInYearsMatch
from gslib.utils.retention_util import SECONDS_IN_DAY
from gslib.utils.retention_util import SECONDS_IN_MONTH
from gslib.utils.retention_util import SECONDS_IN_YEAR
from gslib.utils.retention_util import YearsToSeconds


class TestRetentionUtil(testcase.GsUtilUnitTestCase):
  """Unit tests for gsutil retention_util module."""

  def testDaysToSeconds(self):
    secs = DaysToSeconds(1)
    self.assertEqual(secs, 1 * SECONDS_IN_DAY)

    secs = DaysToSeconds(3)
    self.assertEqual(secs, 3 * SECONDS_IN_DAY)

  def testMonthsToSeconds(self):
    secs = MonthsToSeconds(1)
    self.assertEqual(secs, 1 * SECONDS_IN_MONTH)

    secs = MonthsToSeconds(3)
    self.assertEqual(secs, 3 * SECONDS_IN_MONTH)

  def testYearsToSeconds(self):
    secs = YearsToSeconds(1)
    self.assertEqual(secs, 1 * SECONDS_IN_YEAR)

    secs = YearsToSeconds(3)
    self.assertEqual(secs, 3 * SECONDS_IN_YEAR)

  def testRetentionInSecondsMatch(self):
    secs = '30s'
    secs_match = RetentionInSecondsMatch(secs)
    self.assertEqual('30', secs_match.group('number'))

    secs = '1s'
    secs_match = RetentionInSecondsMatch(secs)
    self.assertEqual('1', secs_match.group('number'))

    secs = '1second'
    secs_match = RetentionInSecondsMatch(secs)
    self.assertEqual(None, secs_match)

  def testRetentionInMonthsMatch(self):
    months = '30m'
    months_match = RetentionInMonthsMatch(months)
    self.assertEqual('30', months_match.group('number'))

    months = '1m'
    months_match = RetentionInMonthsMatch(months)
    self.assertEqual('1', months_match.group('number'))

    months = '1month'
    months_match = RetentionInMonthsMatch(months)
    self.assertEqual(None, months_match)

  def testRetentionInDaysMatch(self):
    days = '30d'
    days_match = RetentionInDaysMatch(days)
    self.assertEqual('30', days_match.group('number'))

    days = '1d'
    days_match = RetentionInDaysMatch(days)
    self.assertEqual('1', days_match.group('number'))

    days = '1day'
    days_match = RetentionInDaysMatch(days)
    self.assertEqual(None, days_match)

  def testRetentionInYearsMatch(self):
    years = '30y'
    years_match = RetentionInYearsMatch(years)
    self.assertEqual('30', years_match.group('number'))

    years = '1y'
    years_match = RetentionInYearsMatch(years)
    self.assertEqual('1', years_match.group('number'))

    years = '1year'
    years_match = RetentionInYearsMatch(years)
    self.assertEqual(None, years_match)

  def testRetentionInSeconds(self):
    one_year = '1y'
    one_year_in_seconds = RetentionInSeconds(one_year)
    self.assertEqual(SECONDS_IN_YEAR, one_year_in_seconds)

    one_month = '1m'
    one_month_in_seconds = RetentionInSeconds(one_month)
    self.assertEqual(SECONDS_IN_MONTH, one_month_in_seconds)

    one_day = '1d'
    one_day_in_seconds = RetentionInSeconds(one_day)
    self.assertEqual(SECONDS_IN_DAY, one_day_in_seconds)

    one_second = '1s'
    one_second_in_seconds = RetentionInSeconds(one_second)
    self.assertEqual(1, one_second_in_seconds)

  def testRetentionPeriodToString(self):
    retention_str = _RetentionPeriodToString(SECONDS_IN_DAY)
    self.assertRegex(retention_str, r'Duration: 1 Day\(s\)')

    retention_str = _RetentionPeriodToString(SECONDS_IN_DAY - 1)
    self.assertRegex(retention_str, r'Duration: 86399 Second\(s\)')

    retention_str = _RetentionPeriodToString(SECONDS_IN_DAY + 1)
    self.assertRegex(retention_str, r'Duration: 86401 Seconds \(~1 Day\(s\)\)')

    retention_str = _RetentionPeriodToString(SECONDS_IN_MONTH)
    self.assertRegex(retention_str, r'Duration: 1 Month\(s\)')

    retention_str = _RetentionPeriodToString(SECONDS_IN_MONTH - 1)
    self.assertRegex(retention_str,
                     r'Duration: 2678399 Seconds \(~30 Day\(s\)\)')

    retention_str = _RetentionPeriodToString(SECONDS_IN_MONTH + 1)
    self.assertRegex(retention_str,
                     r'Duration: 2678401 Seconds \(~31 Day\(s\)\)')

    retention_str = _RetentionPeriodToString(SECONDS_IN_YEAR)
    self.assertRegex(retention_str, r'Duration: 1 Year\(s\)')

    retention_str = _RetentionPeriodToString(SECONDS_IN_YEAR - 1)
    self.assertRegex(retention_str,
                     r'Duration: 31557599 Seconds \(~365 Day\(s\)\)')

    retention_str = _RetentionPeriodToString(SECONDS_IN_YEAR + 1)
    self.assertRegex(retention_str,
                     r'Duration: 31557601 Seconds \(~365 Day\(s\)\)')

  def testRetentionInSecondsInvalidRaises(self):
    from gslib.exception import CommandException

    with self.assertRaisesRegex(CommandException, 'Incorrect retention period specified'):
      RetentionInSeconds('10')

    with self.assertRaisesRegex(CommandException, 'Incorrect retention period specified'):
      RetentionInSeconds('5h')

    with self.assertRaisesRegex(CommandException, 'Incorrect retention period specified'):
      RetentionInSeconds('abc')

  def testRetentionPolicyToString(self):
    from gslib.utils.retention_util import RetentionPolicyToString
    import datetime

    # 1. No Policy
    self.assertEqual(
        RetentionPolicyToString(None, 'gs://my-bucket'),
        'gs://my-bucket has no Retention Policy.'
    )

    # Mock policy object
    class MockRetentionPolicy(object):
      def __init__(self, period, is_locked, effective_time):
        self.retentionPeriod = period
        self.isLocked = is_locked
        self.effectiveTime = effective_time

    # 2. Unlocked Policy
    unlocked_policy = MockRetentionPolicy(
        period=86400,
        is_locked=False,
        effective_time=datetime.datetime(2026, 7, 3, 12, 0, 0)
    )
    unlocked_str = RetentionPolicyToString(unlocked_policy, 'gs://my-bucket')
    self.assertIn('Retention Policy (UNLOCKED)', unlocked_str)
    self.assertIn('Duration: 1 Day(s)', unlocked_str)
    self.assertIn('Effective Time: Fri, 03 Jul 2026 12:00:00 GMT', unlocked_str)

    # 3. Locked Policy
    locked_policy = MockRetentionPolicy(
        period=86400,
        is_locked=True,
        effective_time=datetime.datetime(2026, 7, 3, 12, 0, 0)
    )
    locked_str = RetentionPolicyToString(locked_policy, 'gs://my-bucket')
    self.assertIn('Retention Policy (LOCKED)', locked_str)

  @mock.patch('gslib.utils.retention_util.input')
  def testConfirmLockRequest(self, mock_input):
    from gslib.utils.retention_util import ConfirmLockRequest
    import datetime

    class MockRetentionPolicy(object):
      def __init__(self, period, is_locked, effective_time):
        self.retentionPeriod = period
        self.isLocked = is_locked
        self.effectiveTime = effective_time

    policy = MockRetentionPolicy(
        period=86400,
        is_locked=False,
        effective_time=datetime.datetime(2026, 7, 3, 12, 0, 0)
    )

    # Test confirmation accepted (yes)
    mock_input.return_value = 'yes'
    self.assertTrue(ConfirmLockRequest('gs://my-bucket', policy))

    # Test confirmation rejected (no)
    mock_input.return_value = 'no'
    self.assertFalse(ConfirmLockRequest('gs://my-bucket', policy))

    # Test confirmation accepted with capital Y
    mock_input.return_value = 'Y'
    self.assertTrue(ConfirmLockRequest('gs://my-bucket', policy))

  def testUpdateObjectMetadataExceptionHandler(self):
    from gslib.utils.retention_util import UpdateObjectMetadataExceptionHandler

    class MockClass(object):
      def __init__(self):
        self.logger = mock.Mock()
        self.everything_set_okay = True

    cls_instance = MockClass()
    exception = Exception('test exception')
    UpdateObjectMetadataExceptionHandler(cls_instance, exception)

    cls_instance.logger.error.assert_called_once_with(exception)
    self.assertFalse(cls_instance.everything_set_okay)

  def testHoldFuncWrappers(self):
    from gslib.utils.retention_util import (
        SetTempHoldFuncWrapper,
        ReleaseTempHoldFuncWrapper,
        SetEventHoldFuncWrapper,
        ReleaseEventHoldFuncWrapper
    )
    from gslib.third_party.storage_apitools import storage_v1_messages as apitools_messages

    class MockClass(object):
      def __init__(self):
        self.calls = []

      def ObjectUpdateMetadataFunc(self, metadata_update, log_template, name_expansion_result, thread_state=None):
        self.calls.append((metadata_update, log_template, name_expansion_result, thread_state))

    # 1. Set Temp Hold
    cls_instance = MockClass()
    SetTempHoldFuncWrapper(cls_instance, 'result', 'state')
    self.assertEqual(len(cls_instance.calls), 1)
    metadata_update, log_template, res, state = cls_instance.calls[0]
    self.assertTrue(metadata_update.temporaryHold)
    self.assertIsNone(metadata_update.eventBasedHold)
    self.assertIn('Setting Temporary Hold', log_template)
    self.assertEqual(res, 'result')
    self.assertEqual(state, 'state')

    # 2. Release Temp Hold
    cls_instance = MockClass()
    ReleaseTempHoldFuncWrapper(cls_instance, 'result', 'state')
    self.assertEqual(len(cls_instance.calls), 1)
    metadata_update, log_template, res, state = cls_instance.calls[0]
    self.assertFalse(metadata_update.temporaryHold)
    self.assertIsNone(metadata_update.eventBasedHold)
    self.assertIn('Releasing Temporary Hold', log_template)

    # 3. Set Event Hold
    cls_instance = MockClass()
    SetEventHoldFuncWrapper(cls_instance, 'result', 'state')
    self.assertEqual(len(cls_instance.calls), 1)
    metadata_update, log_template, res, state = cls_instance.calls[0]
    self.assertTrue(metadata_update.eventBasedHold)
    self.assertIsNone(metadata_update.temporaryHold)
    self.assertIn('Setting Event-Based Hold', log_template)

    # 4. Release Event Hold
    cls_instance = MockClass()
    ReleaseEventHoldFuncWrapper(cls_instance, 'result', 'state')
    self.assertEqual(len(cls_instance.calls), 1)
    metadata_update, log_template, res, state = cls_instance.calls[0]
    self.assertFalse(metadata_update.eventBasedHold)
    self.assertIsNone(metadata_update.temporaryHold)
    self.assertIn('Releasing Event-Based Hold', log_template)

