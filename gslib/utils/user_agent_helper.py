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

import re
import sys
import gslib
from gslib.utils import system_util


def GetUserAgent(args, metrics_off=True):
  """Using the command arguments return a suffix for the UserAgent string.

  Args:
    args: str[], parsed set of arguments entered in the CLI.
    metrics_off: boolean, whether the MetricsCollector is disabled.

  Returns:
    str, A string value that can be appended to an existing UserAgent.
  """
  user_agent = ' gsutil/%s' % gslib.VERSION
  user_agent += ' (%s)' % sys.platform
  user_agent += ' analytics/%s ' % ('disabled' if metrics_off else 'enabled')

  if system_util.InvokedViaCloudSdk():
    user_agent += ' google-cloud-sdk'
    if system_util.CloudSdkVersion():
      user_agent += '/%s' % system_util.CloudSdkVersion()

  return user_agent
