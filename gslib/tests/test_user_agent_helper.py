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

from gslib.utils import system_util
from gslib.utils.user_agent_helper import GetUserAgent
import gslib.tests.testcase as testcase

import six
from six import add_move, MovedModule
add_move(MovedModule('mock', 'mock', 'unittest.mock'))
from six.moves import mock


class TestUserAgentHelper(testcase.GsUtilUnitTestCase):
  """Unit tests for the GetUserAgent helper function."""

  def testNoArgs(self):
    self.assertRegexpMatches(
        GetUserAgent([]),
        r" gsutil/[0-9\.]+ \([^\)]+\) analytics/disabled")

  def testAnalyticsFlag(self):
    self.assertRegexpMatches(
        GetUserAgent([], False),
        r" gsutil/[0-9\.]+ \([^\)]+\) analytics/enabled")
  
  @mock.patch.object(system_util, 'IsRunningInteractively')
  def testInteractiveFlag(self, mock_interactive):
    mock_interactive.return_value = True
    self.assertRegexpMatches(
        GetUserAgent([]),
        r" gsutil/[0-9\.]+ \([^\)]+\) .+ interactive/True$")
    mock_interactive.return_value = False
    self.assertRegexpMatches(
        GetUserAgent([]),
        r" gsutil/[0-9\.]+ \([^\)]+\) .+ interactive/False$")

  def testHelp(self):
    self.assertRegexpMatches(
        GetUserAgent(['help']),
        r" gsutil/[0-9\.]+ \([^\)]+\) .+ command/help$"
    )

  def testCp(self):
    self.assertRegexpMatches(
        GetUserAgent(['cp', '-r', '-Z', 'test.txt', 'gs://my-bucket']),
        r" gsutil/[0-9\.]+ \([^\)]+\) .+ command/cp$"
    )

  def testRsync(self):
    self.assertRegexpMatches(
        GetUserAgent(['rsync', '-r', '-U', 'src', 'gs://dst']),
        r" gsutil/[0-9\.]+ \([^\)]+\) .+ command/rsync$"
    )

  def testCpCloudToCloud(self):
    self.assertRegexpMatches(
        GetUserAgent(['cp', '-r', '-D', 'gs://src', 'gs://dst']),
        r" gsutil/[0-9\.]+ \([^\)]+\) .+ command/cp$"
    )

  def testCpDaisyChain(self):
    self.assertRegexpMatches(
        GetUserAgent(['cp', '-r', '-Z', 'gs://src', 's3://dst']),
        r" gsutil/[0-9\.]+ \([^\)]+\) .+ command/cp-DaisyChain$"
    )

  def testPassOnInvalidUrlError(self):
    self.assertRegexpMatches(
        GetUserAgent(['cp', '-r', '-Z', 'invalid://src', 's3://dst']),
        r" gsutil/[0-9\.]+ \([^\)]+\) .+ command/cp$"
    )

  @mock.patch.object(system_util, 'CloudSdkVersion')
  @mock.patch.object(system_util, 'InvokedViaCloudSdk')
  def testCloudSdk(self, mock_invoked, mock_version):
    mock_invoked.return_value = True
    mock_version.return_value = '500.1'
    self.assertRegexpMatches(
        GetUserAgent(['help']),
        r" gsutil/[0-9\.]+ \([^\)]+\) .+ google-cloud-sdk/500.1$"
    )
    mock_invoked.return_value = False
    mock_version.return_value = '500.1'
    self.assertRegexpMatches(
        GetUserAgent(['help']),
        r" gsutil/[0-9\.]+ \([^\)]+\) .+ command/help$"
    )
