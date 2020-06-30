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
"""Unit tests for hashing helper functions and classes."""

from gslib.utils.user_agent_helper import GetUserAgent
import gslib.tests.testcase as testcase


class TestUserAgentHelper(testcase.GsUtilUnitTestCase):
  """Unit tests for the GetUserAgent helper function."""

  def testNoArgs(self):
    actual = GetUserAgent([])
    self.assertRegexpMatches(
        actual,
        r" gsutil/[0-9\.]+ \([^\)]+\) analytics/disabled interactive/")

  def testAnalyticsFlag(self):
    actual = GetUserAgent([], False)
    self.assertRegexpMatches(
        actual,
        r" gsutil/[0-9\.]+ \([^\)]+\) analytics/enabled interactive/")

  def testHelp(self):
    actual = GetUserAgent(['help'])
    self.assertRegexpMatches(
        actual,
        r" gsutil/[0-9\.]+ \([^\)]+\) .+ command/help"
    )

  def testCp(self):
    actual = GetUserAgent(['cp', '-r', '-Z', 'test.txt', 'gs://my-bucket'])
    self.assertRegexpMatches(
        actual,
        r" gsutil/[0-9\.]+ \([^\)]+\) .+ command/cp"
    )

  def testRsync(self):
    actual = GetUserAgent(['rsync', '-r', '-U', 'src', 'gs://dst'])
    self.assertRegexpMatches(
        actual,
        r" gsutil/[0-9\.]+ \([^\)]+\) .+ command/rsync"
    )

  def testCpCloudToCloud(self):
    actual = GetUserAgent(['cp', '-r', '-D', 'gs://src', 'gs://dst'])
    self.assertRegexpMatches(
        actual,
        r" gsutil/[0-9\.]+ \([^\)]+\) .+ command/cp"
    )

  def testCpDaisyChain(self):
    actual = GetUserAgent(['cp', '-r', '-Z', 'gs://src', 's3://dst'])
    self.assertRegexpMatches(
        actual,
        r" gsutil/[0-9\.]+ \([^\)]+\) .+ command/cp-DaisyChain"
    )

  def testPassOnInvalidUrlError(self):
    actual = GetUserAgent(['cp', '-r', '-Z', 'invalid://src', 's3://dst'])
    self.assertRegexpMatches(
        actual,
        r" gsutil/[0-9\.]+ \([^\)]+\) .+ command/cp"
    )
