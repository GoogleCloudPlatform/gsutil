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
"""Contains helper for appending user agent information."""

import sys
import gslib
from gslib.utils import system_util
from gslib.utils.arg_helper import GetArgumentsAndOptions


def GetUserAgent(metrics_off=True):
  """Using the command arguments return a suffix for the UserAgent string.

  Args:
    metrics_off: boolean, whether the MetricsCollector is disabled.

  Returns:
    str, A string value that can be appended to an existing UserAgent.
  """
  args, opts = GetArgumentsAndOptions()

  user_agent = ' gsutil/%s' % gslib.VERSION
  user_agent += ' (%s)' % sys.platform
  user_agent += ' analytics/%s ' % ('disabled' if metrics_off else 'enabled')
  user_agent += ' interactive/%s' % sys.stdin.isatty()
  user_agent += ' command/%s' % opts[0]

  if len([segment for segment in opts if '://' in segment]) > 1:
    user_agent += '-CloudToCloud'

  if system_util.InvokedViaCloudSdk():
    user_agent += ' google-cloud-sdk'
    if system_util.CloudSdkVersion():
      user_agent += '/%s' % system_util.CloudSdkVersion()

  return user_agent
