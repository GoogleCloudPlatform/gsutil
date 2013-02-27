# Copyright 2010 Google Inc. All Rights Reserved.
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

import math
import os
import re
import sys
import time
import xml.etree.ElementTree as ElementTree

import boto
from boto import config
from gslib.third_party.oauth2_plugin import oauth2_helper
from gslib.third_party.retry_decorator import decorators
from oauth2client.client import HAS_CRYPTO


TWO_MB = 2 * 1024 * 1024

NO_MAX = sys.maxint

# Binary exponentiation strings.
_EXP_STRINGS = [
  (0, 'B', 'bit'),
  (10, 'KB', 'Kbit'),
  (20, 'MB', 'Mbit'),
  (30, 'GB', 'Gbit'),
  (40, 'TB', 'Tbit'),
  (50, 'PB', 'Pbit'),
  (60, 'EB', 'Ebit'),
]

SECONDS_PER_DAY = 3600 * 24

# Detect platform types.
IS_WINDOWS = 'win32' in str(sys.platform).lower()
IS_LINUX = 'linux' in str(sys.platform).lower()
IS_OSX = 'darwin' in str(sys.platform).lower()

GSUTIL_PUB_TARBALL = 'gs://pub/gsutil.tar.gz'

Retry = decorators.retry

# Enum class for specifying listing style.
class ListingStyle(object):
  SHORT = 'SHORT'
  LONG = 'LONG'
  LONG_LONG = 'LONG_LONG'


def CreateTrackerDirIfNeeded():
  """Looks up the configured directory where gsutil keeps its resumable
     transfer tracker files, and creates it if it doesn't already exist.

  Returns:
    The pathname to the tracker directory.
  """
  tracker_dir = config.get(
      'GSUtil', 'resumable_tracker_dir',
      os.path.expanduser('~' + os.sep + '.gsutil'))
  if not os.path.exists(tracker_dir):
    os.makedirs(tracker_dir)
  return tracker_dir


# Name of file where we keep the timestamp for the last time we checked whether
# a new version of gsutil is available.
LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE = (
    os.path.join(CreateTrackerDirIfNeeded(), '.last_software_update_check'))


def HasConfiguredCredentials():
  """Determines if boto credential/config file exists."""
  config = boto.config
  has_goog_creds = (config.has_option('Credentials', 'gs_access_key_id') and
                    config.has_option('Credentials', 'gs_secret_access_key'))
  has_amzn_creds = (config.has_option('Credentials', 'aws_access_key_id') and
                    config.has_option('Credentials', 'aws_secret_access_key'))
  has_oauth_creds = (
      config.has_option('Credentials', 'gs_oauth2_refresh_token'))
  has_service_account_creds = (HAS_CRYPTO and
      config.has_option('Credentials', 'gs_service_client_id') 
      and config.has_option('Credentials', 'gs_service_key_file'))
  has_auth_plugins = config.has_option('Plugin', 'plugin_directory')
  return (has_goog_creds or has_amzn_creds or has_oauth_creds
          or has_auth_plugins or has_service_account_creds)


def _RoundToNearestExponent(num):
  i = 0
  while i+1 < len(_EXP_STRINGS) and num >= (2 ** _EXP_STRINGS[i+1][0]):
    i += 1
  return i, round(float(num) / 2 ** _EXP_STRINGS[i][0], 2)

def MakeHumanReadable(num):
  """Generates human readable string for a number of bytes.

  Args:
    num: The number, in bytes.

  Returns:
    A string form of the number using size abbreviations (KB, MB, etc.).
  """
  i, rounded_val = _RoundToNearestExponent(num)
  return '%s %s' % (rounded_val, _EXP_STRINGS[i][1])

def MakeBitsHumanReadable(num):
  """Generates human readable string for a number of bits.

  Args:
    num: The number, in bits.

  Returns:
    A string form of the number using bit size abbreviations (kbit, Mbit, etc.)
  """
  i, rounded_val = _RoundToNearestExponent(num)
  return '%s %s' % (rounded_val, _EXP_STRINGS[i][2])

def Percentile(values, percent, key=lambda x:x):
  """Find the percentile of a list of values.

  Taken from: http://code.activestate.com/recipes/511478/

  Args:
    values: a list of numeric values. Note that the values MUST BE already
            sorted.
    percent: a float value from 0.0 to 1.0.
    key: optional key function to compute value from each element of the list
         of values.

  Returns:
    The percentile of the values.
  """
  if not values:
    return None
  k = (len(values) - 1) * percent
  f = math.floor(k)
  c = math.ceil(k)
  if f == c:
    return key(values[int(k)])
  d0 = key(values[int(f)]) * (c-k)
  d1 = key(values[int(c)]) * (k-f)
  return d0 + d1

def ExtractErrorDetail(e):
  """Extract <Details> text from XML content.

  Args:
    e: The GSResponseError that includes XML to be parsed.

  Returns:
    (exception_name, d), where d is <Details> text or None if not found.
  """
  exc_name_parts = re.split("[\.']", str(type(e)))
  if len(exc_name_parts) < 2:
    # Shouldn't happen, but have fallback in case.
    exc_name = str(type(e))
  else:
    exc_name = exc_name_parts[-2]
  if not hasattr(e, 'body'):
    return (exc_name, None)
  detail_start = e.body.find('<Details>')
  detail_end = e.body.find('</Details>')
  if detail_start != -1 and detail_end != -1:
    return (exc_name, e.body[detail_start+9:detail_end])
  return (exc_name, None)

def UnaryDictToXml(message):
  """Generates XML representation of a nested dict with exactly one
  top-level entry and an arbitrary number of 2nd-level entries, e.g.
  capturing a WebsiteConfiguration message.

  Args:
    message: The dict encoding the message.

  Returns:
    XML string representation of the input dict.
  """
  if len(message) != 1:
    raise Exception("Expected dict of size 1, got size %d" % len(message))

  name, content = message.items()[0]
  T = ElementTree.Element(name)
  for property, value in sorted(content.items()):
    node = ElementTree.SubElement(T, property)
    node.text = value
  return ElementTree.tostring(T)

def LookUpGsutilVersion(uri):
  """Looks up the gustil version of the specified gsutil tarball URI, from the
     metadata field set on that object.

  Args:
    URI: gsutil URI tarball (such as gs://pub/gsutil.tar.gz).

  Returns:
    Version string if URI is a cloud URI containing x-goog-meta-gsutil-version
    metadata, else None.
  """
  if uri.is_cloud_uri():
    obj = uri.get_key(False)
    if obj.metadata and 'gsutil_version' in obj.metadata:
      return obj.metadata['gsutil_version']
