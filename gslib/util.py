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

import binascii
import errno
import math
import os
import re
import sys
import textwrap
import xml.etree.ElementTree as ElementTree

import boto
import boto.auth
from boto import config
from boto.exception import NoAuthHandlerFound
from boto.gs.connection import GSConnection
from boto.provider import Provider
from boto.pyami.config import BotoConfigLocations
import gslib
from gslib.exception import CommandException
from retry_decorator import retry_decorator 
from oauth2client.client import HAS_CRYPTO

TWO_MB = 2 * 1024 * 1024

NO_MAX = sys.maxint

VERSION_MATCHER = re.compile(r'^(?P<maj>\d+)(\.(?P<min>\d+)(?P<suffix>.*))?')

RELEASE_NOTES_URL = 'https://pub.storage.googleapis.com/gsutil_ReleaseNotes.txt'

# Binary exponentiation strings.
_EXP_STRINGS = [
  (0, 'B', 'bit'),
  (10, 'KB', 'Kbit', 'K'),
  (20, 'MB', 'Mbit', 'M'),
  (30, 'GB', 'Gbit', 'G'),
  (40, 'TB', 'Tbit', 'T'),
  (50, 'PB', 'Pbit', 'P'),
  (60, 'EB', 'Ebit', 'E'),
]


def _GenerateSuffixRegex():
  human_bytes_re = r'(?P<num>\d*\.\d+|\d+)\s*(?P<suffix>%s)?'
  suffixes = []
  suffix_to_si = {}
  for i, si in enumerate(_EXP_STRINGS):
    si_suffixes = [s.lower() for s in list(si)[1:]]
    for suffix in si_suffixes:
      suffix_to_si[suffix] = i
    suffixes.extend(si_suffixes)
  human_bytes_re = human_bytes_re % '|'.join(suffixes)
  matcher = re.compile(human_bytes_re)
  return suffix_to_si, matcher

SUFFIX_TO_SI, MATCH_HUMAN_BYTES = _GenerateSuffixRegex()

SECONDS_PER_DAY = 3600 * 24

# Detect platform types.
PLATFORM = str(sys.platform).lower()
IS_WINDOWS = 'win32' in PLATFORM
IS_CYGWIN = 'cygwin' in PLATFORM
IS_LINUX = 'linux' in PLATFORM
IS_OSX = 'darwin' in PLATFORM

GSUTIL_PUB_TARBALL = 'gs://pub/gsutil.tar.gz'

Retry = retry_decorator.retry


# Enum class for specifying listing style.
class ListingStyle(object):
  SHORT = 'SHORT'
  LONG = 'LONG'
  LONG_LONG = 'LONG_LONG'


def UsingCrcmodExtension(crcmod):
  return (getattr(crcmod, 'crcmod', None) and
          getattr(crcmod.crcmod, '_usingExtension', None))


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
    try:
      # Unfortunately, even though we catch and ignore EEXIST, this call will
      # will output a (needless) error message (no way to avoid that in Python).
      os.makedirs(tracker_dir)
    # Ignore 'already exists' in case user tried to start up several
    # resumable uploads concurrently from a machine where no tracker dir had
    # yet been created.
    except OSError as e:
      if e.errno != errno.EEXIST:
        raise
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

  valid_auth_handler = None
  try:
    valid_auth_handler = boto.auth.get_auth_handler(
        GSConnection.DefaultHost, config, Provider('google'),
        requested_capability=['s3'])
    # Exclude the no-op auth handler as indicating credentials are configured.
    # Note we can't use isinstance() here because the no-op module may not be
    # imported so we can't get a reference to the class type.
    if getattr(getattr(valid_auth_handler, '__class__', None),
               '__name__', None) == 'NoOpAuth':
      valid_auth_handler = None
  except NoAuthHandlerFound:
    pass

  return (has_goog_creds or has_amzn_creds or has_oauth_creds
          or has_service_account_creds or valid_auth_handler)


def ConfigureNoOpAuthIfNeeded():
  """
  Sets up no-op auth handler if no boto credentials are configured.
  """
  config = boto.config
  if not HasConfiguredCredentials():
    if (config.has_option('Credentials', 'gs_service_client_id')
        and not HAS_CRYPTO):
      raise CommandException('\n'.join(textwrap.wrap(
          'Your gsutil is configured with an OAuth2 service account, but you '
          'do not have PyOpenSSL or PyCrypto 2.6 or later installed.  Service '
          'account authentication requires one of these libraries; please '
          'install either of them to proceed, or configure  a different type '
          'of credentials with "gsutil config".')))
    else:
      # With no boto config file the user can still access publicly readable
      # buckets and objects.
      from gslib import no_op_auth_plugin


def GetConfigFilePath():
  config_path = 'no config found'
  for path in BotoConfigLocations:
    try:
      with open(path, 'r'):
        config_path = path
      break
    except IOError:
      pass
  return config_path


def GetBotoConfigFileList():
  """Returns list of boto config files that exist."""
  config_paths = boto.pyami.config.BotoConfigLocations
  if 'AWS_CREDENTIAL_FILE' in os.environ:
    config_paths.append(os.environ['AWS_CREDENTIAL_FILE'])
  config_files = {}
  for config_path in config_paths:
    if os.path.exists(config_path):
      config_files[config_path] = 1
  cf_list = []
  for config_file in config_files:
    cf_list.append(config_file)
  return cf_list


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
  return '%g %s' % (rounded_val, _EXP_STRINGS[i][1])


def MakeBitsHumanReadable(num):
  """Generates human readable string for a number of bits.

  Args:
    num: The number, in bits.

  Returns:
    A string form of the number using bit size abbreviations (kbit, Mbit, etc.)
  """
  i, rounded_val = _RoundToNearestExponent(num)
  return '%g %s' % (rounded_val, _EXP_STRINGS[i][2])


def HumanReadableToBytes(human_string):
  """Tries to convert a human-readable string to a number of bytes.

  Args:
    human_string: A string supplied by user, e.g. '1M', '3 GB'.
  Returns:
    An integer containing the number of bytes.
  """
  human_string = human_string.lower()
  m = MATCH_HUMAN_BYTES.match(human_string)
  if m:
    num = float(m.group('num'))
    if m.group('suffix'):
      power = _EXP_STRINGS[SUFFIX_TO_SI[m.group('suffix')]][0]
      num *= (2.0 ** power)
    num = int(round(num))
    return num
  raise ValueError('Invalid byte string specified: %s' % human_string)


def Percentile(values, percent, key=lambda x: x):
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


def ParseErrorDetail(e):
  """Parse <Message> and/or <Details> text from XML content.

  Args:
    e: The GSResponseError that includes XML to be parsed.

  Returns:
    (exception_name, m, d), where m is <Message> text or None,
                            and d is <Details> text or None.
  """
  exc_name_parts = re.split("[\.']", str(type(e)))
  if len(exc_name_parts) < 2:
    # Shouldn't happen, but have fallback in case.
    exc_name = str(type(e))
  else:
    exc_name = exc_name_parts[-2]
  if not hasattr(e, 'body'):
    return (exc_name, None)
  match = re.search(r'<Message>(?P<message>.*)</Message>', e.body)
  m = match.group('message') if match else None
  match = re.search(r'<Details>(?P<details>.*)</Details>', e.body)
  d = match.group('details') if match else None
  return (exc_name, m, d)

def FormatErrorMessage(exc_name, status, code, reason, message, detail):
  """Formats an error message from components parsed by ParseErrorDetail."""
  if message and detail:
    return('%s: status=%d, code=%s, reason="%s", message="%s", detail="%s"' %
           (exc_name, status, code, reason, message, detail))
  if message:
    return('%s: status=%d, code=%s, reason="%s", message="%s"' %
           (exc_name, status, code, reason, message))
  if detail:
    return('%s: status=%d, code=%s, reason="%s", detail="%s"' %
           (exc_name, status, code, reason, detail))
  return('%s: status=%d, code=%s, reason="%s"' %
         (exc_name, status, code, reason))

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
  """Looks up the gsutil version of the specified gsutil tarball URI, from the
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


def GetGsutilVersionModifiedTime():
  """Returns unix timestamp of when the VERSION file was last modified."""
  if not gslib.VERSION_FILE:
    return 0
  return int(os.path.getmtime(gslib.VERSION_FILE))


def IsRunningInteractively():
  """Returns True if currently running interactively on a TTY."""
  return sys.stdout.isatty() and sys.stderr.isatty() and sys.stdin.isatty()


def _BotoIsSecure():
  for cfg_var in ('is_secure', 'https_validate_certificates'):
    if (config.has_option('Boto', cfg_var)
        and not config.getboolean('Boto', cfg_var)):
      return False, cfg_var
  return True, ''

BOTO_IS_SECURE = _BotoIsSecure()


def AddAcceptEncoding(headers):
  """Adds accept-encoding:gzip to the dictionary of headers."""
  # If Accept-Encoding is not already set, set it to enable gzip.
  if 'accept-encoding' not in headers:
    headers['accept-encoding'] = 'gzip'


def PrintFullInfoAboutUri(uri, incl_acl, headers):
  """Print full info for given URI (like what displays for gsutil ls -L).

  Args:
    uri: StorageUri being listed.
    incl_acl: True if ACL info should be output.
    headers: The headers to pass to boto, if any.

  Returns:
    Tuple (number of objects,
           object length, if listing_style is one of the long listing formats)

  Raises:
    Exception: if calling bug encountered.
  """
  # Run in a try/except clause so we can continue listings past
  # access-denied errors (which can happen because user may have READ
  # permission on object and thus see the bucket listing data, but lack
  # FULL_CONTROL over individual objects and thus not be able to read
  # their ACLs).
  # TODO: Switch this code to use string formatting instead of tabs.
  try:
    print '%s:' % uri.uri.encode('utf-8')
    headers = headers.copy()
    # Add accept encoding so that the HEAD request matches what would be
    # sent for a GET request.
    AddAcceptEncoding(headers)
    obj = uri.get_key(False, headers=headers)
    print '\tCreation time:\t\t%s' % obj.last_modified
    if obj.cache_control:
      print '\tCache-Control:\t\t%s' % obj.cache_control
    if obj.content_disposition:
      print '\tContent-Disposition:\t\t%s' % obj.content_disposition
    if obj.content_encoding:
      print '\tContent-Encoding:\t%s' % obj.content_encoding
    if obj.content_language:
      print '\tContent-Language:\t%s' % obj.content_language
    print '\tContent-Length:\t\t%s' % obj.size
    print '\tContent-Type:\t\t%s' % obj.content_type
    if hasattr(obj, 'component_count') and obj.component_count:
      print '\tComponent-Count:\t%d' % obj.component_count
    if obj.metadata:
      prefix = uri.get_provider().metadata_prefix
      for name in obj.metadata:
        meta_string = '\t%s%s:\t%s' % (prefix, name, obj.metadata[name])
        print meta_string.encode('utf-8')
    if hasattr(obj, 'cloud_hashes'):
      for alg in obj.cloud_hashes:
        print '\tHash (%s):\t\t%s' % (
            alg, binascii.b2a_hex(obj.cloud_hashes[alg]))
    print '\tETag:\t\t\t%s' % obj.etag.strip('"\'')
    if hasattr(obj, 'generation'):
      print '\tGeneration:\t\t%s' % obj.generation
    if hasattr(obj, 'metageneration'):
      print '\tMetageneration:\t\t%s' % obj.metageneration
    if incl_acl:
      print '\tACL:\t\t%s' % (uri.get_acl(False, headers))
    return (1, obj.size)
  except boto.exception.GSResponseError as e:
    if e.status == 403:
      print ('\tACL:\t\t\tACCESS DENIED. Note: you need FULL_CONTROL '
             'permission\n\t\t\ton the object to read its ACL.')
      return (1, obj.size)
    else:
      raise e
  return (numobjs, numbytes)

def CompareVersions(first, second):
  """Compares the first and second gsutil version strings.

  For example, 3.33 > 3.7, and 4.1 is a greater major version than 3.33.
  Does not handle multiple periods (e.g. 3.3.4) or complicated suffixes
  (e.g., 3.3RC4 vs. 3.3RC5). A version string with a suffix is treated as
  less than its non-suffix counterpart (e.g. 3.32 > 3.32pre).

  Returns:
    (g, m):
       g is True if first known to be greater than second, else False.
       m is True if first known to be greater by at least 1 major version,
         else False.
  """
  m1 = VERSION_MATCHER.match(str(first))
  m2 = VERSION_MATCHER.match(str(second))

  # If passed strings we don't know how to handle, be conservative.
  if not m1 or not m2:
    return (False, False)

  major_ver1 = int(m1.group('maj'))
  minor_ver1 = int(m1.group('min')) if m1.group('min') else 0
  suffix_ver1 = m1.group('suffix')
  major_ver2 = int(m2.group('maj'))
  minor_ver2 = int(m2.group('min')) if m2.group('min') else 0
  suffix_ver2 = m2.group('suffix')

  if major_ver1 > major_ver2:
    return (True, True)
  elif major_ver1 == major_ver2:
    if minor_ver1 > minor_ver2:
      return (True, False)
    elif minor_ver1 == minor_ver2:
      return (bool(suffix_ver2) and not suffix_ver1, False)
  return (False, False)
