# Copyright 2010 Google Inc.
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

"""Static data and helper functions."""

import boto
import sys

# We don't use the oauth2 authentication plugin directly; importing it here
# ensures that it's loaded and available by default. Note: we made this static
# state instead of Command instance state because the top-level gsutil code
# needs to check it.
HAVE_OAUTH2 = False
try:
  from oauth2_plugin import oauth2_helper
  HAVE_OAUTH2 = True
except ImportError:
  pass

ONE_MB = 1024*1024

NO_MAX = sys.maxint

# Binary exponentiation strings.
_EXP_STRINGS = [
    (0, 'B'),
    (10, 'KB'),
    (20, 'MB'),
    (30, 'GB'),
    (40, 'TB'),
    (50, 'PB'),
]


# Enum class for specifying listing style.
class ListingStyle(object):
  SHORT = 'SHORT'
  LONG = 'LONG'
  LONG_LONG = 'LONG_LONG'


def HasConfiguredCredentials():
  """Determines if boto credential/config file exists."""
  config = boto.config
  has_goog_creds = (config.has_option('Credentials', 'gs_access_key_id') and
                    config.has_option('Credentials', 'gs_secret_access_key'))
  has_amzn_creds = (config.has_option('Credentials', 'aws_access_key_id') and
                    config.has_option('Credentials', 'aws_secret_access_key'))
  has_oauth_creds = (HAVE_OAUTH2 and
      config.has_option('Credentials', 'gs_oauth2_refresh_token'))
  has_auth_plugins = config.has_option('Plugin', 'plugin_directory')
  return (has_goog_creds or has_amzn_creds or has_oauth_creds
          or has_auth_plugins)


def MakeHumanReadable(num):
  """Generates human readable string for a number.

  Args:
    num: The number.

  Returns:
    A string form of the number using size abbreviations (KB, MB, etc.).
  """
  i = 0
  while i+1 < len(_EXP_STRINGS) and num >= (2 ** _EXP_STRINGS[i+1][0]):
    i += 1
  rounded_val = round(float(num) / 2 ** _EXP_STRINGS[i][0], 2)
  return '%s %s' % (rounded_val, _EXP_STRINGS[i][1])
