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

import errno
import math
import multiprocessing
import os
import re
import sys
import textwrap
import threading
import traceback
import xml.etree.ElementTree as ElementTree

import boto
from boto import config
import boto.auth
from boto.exception import NoAuthHandlerFound
from boto.gs.connection import GSConnection
from boto.provider import Provider
from boto.pyami.config import BotoConfigLocations
from oauth2client.client import HAS_CRYPTO
from retry_decorator import retry_decorator

import gslib
from gslib.exception import CommandException
from gslib.storage_url import StorageUrlFromString
from gslib.translation_helper import AclTranslation
from gslib.translation_helper import GenerationFromUrlAndString
from gslib.translation_helper import S3_ACL_MARKER_GUID
from gslib.translation_helper import S3_DELETE_MARKER_GUID
from gslib.translation_helper import S3_MARKER_GUIDS

# pylint: disable=g-import-not-at-top
try:
  from hashlib import md5
except ImportError:
  from md5 import md5

# pylint: disable=g-import-not-at-top
try:
  # This module doesn't necessarily exist on Windows.
  import resource
  HAS_RESOURCE_MODULE = True
except ImportError, e:
  HAS_RESOURCE_MODULE = False

TWO_MB = 2 * 1024 * 1024
DEFAULT_FILE_BUFFER_SIZE = 8192

# Make a progress callback every 64KB during uploads/downloads.
CALLBACK_PER_X_BYTES = 1024*64

NO_MAX = sys.maxint

UTF8 = 'utf-8'

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

global manager  # pylint: disable=global-at-module-level


def InitializeMultiprocessingVariables():
  """Perform necessary initialization for multiprocessing.

    See gslib.command.InitializeMultiprocessingVariables for an explanation
    of why this is necessary.
  """
  global manager  # pylint: disable=global-variable-undefined
  manager = multiprocessing.Manager()


def _GenerateSuffixRegex():
  """Creates a suffix regex for human-readable byte counts."""
  human_bytes_re = r'(?P<num>\d*\.\d+|\d+)\s*(?P<suffix>%s)?'
  suffixes = []
  suffix_to_si = {}
  for i, si in enumerate(_EXP_STRINGS):
    si_suffixes = [s.lower() for s in list(si)[1:]]
    for suffix in si_suffixes:
      suffix_to_si[suffix] = i
    suffixes.extend(si_suffixes)
  human_bytes_re %= '|'.join(suffixes)
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

# On Unix-like systems, we will set the maximum number of open files to avoid
# hitting the limit imposed by the OS. This number was obtained experimentally.
MIN_ACCEPTABLE_OPEN_FILES_LIMIT = 1000

GSUTIL_PUB_TARBALL = 'gs://pub/gsutil.tar.gz'

Retry = retry_decorator.retry  # pylint: disable=invalid-name

# Cache the values from this check such that they're available to all callers
# without needing to run all the checks again (some of these, such as calling
# multiprocessing.Manager(), are expensive operations).
cached_multiprocessing_is_available = None
cached_multiprocessing_is_available_stack_trace = None
cached_multiprocessing_is_available_message = None


# Enum class for specifying listing style.
class ListingStyle(object):
  SHORT = 'SHORT'
  LONG = 'LONG'
  LONG_LONG = 'LONG_LONG'


def UsingCrcmodExtension(crcmod):
  return (getattr(crcmod, 'crcmod', None) and
          getattr(crcmod.crcmod, '_usingExtension', None))


def CreateTrackerDirIfNeeded():
  """Looks up or creates the gsutil tracker file directory.

  This is the configured directory where gsutil keeps its resumable transfer
  tracker files. This function creates it if it doesn't already exist.

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
  has_goog_creds = (config.has_option('Credentials', 'gs_access_key_id') and
                    config.has_option('Credentials', 'gs_secret_access_key'))
  has_amzn_creds = (config.has_option('Credentials', 'aws_access_key_id') and
                    config.has_option('Credentials', 'aws_secret_access_key'))
  has_oauth_creds = (
      config.has_option('Credentials', 'gs_oauth2_refresh_token'))
  has_service_account_creds = (
      HAS_CRYPTO and
      config.has_option('Credentials', 'gs_service_client_id') and
      config.has_option('Credentials', 'gs_service_key_file'))

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
  """Sets up no-op auth handler if no boto credentials are configured."""
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
      from gslib import no_op_auth_plugin  # pylint: disable=unused-variable


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
  Raises:
    ValueError: on an invalid string.
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


def UnaryDictToXml(message):
  """Generates XML representation of a nested dict.

  This dict contains exactly one top-level entry and an arbitrary number of
  2nd-level entries, e.g. capturing a WebsiteConfiguration message.

  Args:
    message: The dict encoding the message.

  Returns:
    XML string representation of the input dict.

  Raises:
    Exception: if dict contains more than one top-level entry.
  """
  if len(message) != 1:
    raise Exception('Expected dict of size 1, got size %d' % len(message))

  name, content = message.items()[0]
  element_type = ElementTree.Element(name)
  for element_property, value in sorted(content.items()):
    node = ElementTree.SubElement(element_type, element_property)
    node.text = value
  return ElementTree.tostring(element_type)


def LookUpGsutilVersion(gsutil_api, url_str):
  """Looks up the gsutil version of the specified gsutil tarball URL.

  Version is specified in the metadata field set on that object.

  Args:
    gsutil_api: gsutil Cloud API to use when retrieving gsutil tarball.
    url_str: tarball URL to retrieve (such as 'gs://pub/gsutil.tar.gz').

  Returns:
    Version string if URL is a cloud URL containing x-goog-meta-gsutil-version
    metadata, else None.
  """
  url = StorageUrlFromString(url_str)
  if url.IsCloudUrl():
    obj = gsutil_api.GetObjectMetadata(url.bucket_name, url.object_name,
                                       provider=url.scheme,
                                       fields=['metadata'])
    if obj.metadata and obj.metadata.additionalProperties:
      for prop in obj.metadata.additionalProperties:
        if prop.key == 'gsutil_version':
          return prop.value


def GetGsutilVersionModifiedTime():
  """Returns unix timestamp of when the VERSION file was last modified."""
  if not gslib.VERSION_FILE:
    return 0
  return int(os.path.getmtime(gslib.VERSION_FILE))


def IsRunningInteractively():
  """Returns True if currently running interactively on a TTY."""
  return sys.stdout.isatty() and sys.stderr.isatty() and sys.stdin.isatty()


def _HttpsValidateCertifcatesEnabled():
  return config.get('Boto', 'https_validate_certificates', True)

CERTIFICATE_VALIDATION_ENABLED = _HttpsValidateCertifcatesEnabled()


def _BotoIsSecure():
  return config.get('Boto', 'is_secure', True)

BOTO_IS_SECURE = _BotoIsSecure()


def AddAcceptEncoding(headers):
  """Adds accept-encoding:gzip to the dictionary of headers."""
  # If Accept-Encoding is not already set, set it to enable gzip.
  if 'accept-encoding' not in headers:
    headers['accept-encoding'] = 'gzip'


def PrintFullInfoAboutObject(bucket_listing_ref, incl_acl=True):
  """Print full info for given object (like what displays for gsutil ls -L).

  Args:
    bucket_listing_ref: BucketListingRef being listed.
                        Must have ref_type OBJECT and a populated root_object
                        with the desired fields.
    incl_acl: True if ACL info should be output.

  Returns:
    Tuple (number of objects, object_length)

  Raises:
    Exception: if calling bug encountered.
  """
  url_str = bucket_listing_ref.GetUrlString()
  storage_url = StorageUrlFromString(url_str)
  obj = bucket_listing_ref.root_object

  if (obj.metadata and S3_DELETE_MARKER_GUID in
      obj.metadata.additionalProperties):
    num_bytes = 0
    num_objs = 0
    url_str += '<DeleteMarker>'
  else:
    num_bytes = obj.size
    num_objs = 1

  print '%s:' % url_str.encode(UTF8)
  if obj.updated:
    print '\tCreation time:\t\t%s' % obj.updated.strftime(
        '%a, %d %b %Y %H:%M:%S GMT')
  if obj.cacheControl:
    print '\tCache-Control:\t\t%s' % obj.cacheControl
  if obj.contentDisposition:
    print '\tContent-Disposition:\t\t%s' % obj.contentDisposition
  if obj.contentEncoding:
    print '\tContent-Encoding:\t\t%s' % obj.contentEncoding
  if obj.contentLanguage:
    print '\tContent-Language:\t%s' % obj.contentLanguage
  print '\tContent-Length:\t\t%s' % obj.size
  print '\tContent-Type:\t\t%s' % obj.contentType
  if obj.componentCount:
    print '\tComponent-Count:\t%d' % obj.componentCount
  marker_props = {}
  if obj.metadata and obj.metadata.additionalProperties:
    non_marker_props = []
    for add_prop in obj.metadata.additionalProperties:
      if add_prop.key not in S3_MARKER_GUIDS:
        non_marker_props.append(add_prop)
      else:
        marker_props[add_prop.key] = add_prop.value
    if non_marker_props:
      print '\tMetadata:'
      for ap in non_marker_props:
        meta_string = '\t\t%s:\t\t%s' % (ap.key, ap.value)
        print meta_string.encode(UTF8)
  if obj.crc32c: print '\tHash (crc32c):\t\t%s' % obj.crc32c
  if obj.md5Hash: print '\tHash (md5):\t\t%s' % obj.md5Hash
  print '\tETag:\t\t\t%s' % obj.etag.strip('"\'')
  if obj.generation:
    generation_str = GenerationFromUrlAndString(storage_url, obj.generation)
    print '\tGeneration:\t\t%s' % generation_str
  if obj.metageneration:
    print '\tMetageneration:\t\t%s' % obj.metageneration
  if incl_acl:
    # JSON API won't return acls as part of the response unless we have
    # full control scope
    if obj.acl:
      print '\tACL:\t\t%s' % AclTranslation.JsonFromMessage(obj.acl)
    elif S3_ACL_MARKER_GUID in marker_props:
      print '\tACL:\t\t%s' % marker_props[S3_ACL_MARKER_GUID]
    else:
      print ('\tACL:\t\t\tACCESS DENIED. Note: you need OWNER '
             'permission\n\t\t\t\ton the object to read its ACL.')

  return (num_objs, num_bytes)


def CompareVersions(first, second):
  """Compares the first and second gsutil version strings.

  For example, 3.33 > 3.7, and 4.1 is a greater major version than 3.33.
  Does not handle multiple periods (e.g. 3.3.4) or complicated suffixes
  (e.g., 3.3RC4 vs. 3.3RC5). A version string with a suffix is treated as
  less than its non-suffix counterpart (e.g. 3.32 > 3.32pre).

  Args:
    first: First gsutil version string.
    second: Second gsutil version string.

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


def _IncreaseSoftLimitForResource(resource_name):
  """Sets a new soft limit for the maximum number of open files.

  The soft limit is used for this process (and its children), but the
  hard limit is set by the system and cannot be exceeded.

  Args:
    resource_name: Name of the resource to increase the soft limit for.

  Returns:
    Hard limit for the resource
  """
  try:
    (_, hard_limit) = resource.getrlimit(resource_name)
    resource.setrlimit(resource_name, (hard_limit, hard_limit))
    return hard_limit
  except (resource.error, ValueError):
    return 0


def CalculateMd5FromContents(fp):
  """Calculates the MD5 hash of the contents of a file.

  This function resets the file pointer to position 0.

  Args:
    fp: An already-open file object.

  Returns:
    MD5 digest of the file in hex string format.
  """
  current_md5 = md5()
  fp.seek(0)
  while True:
    data = fp.read(DEFAULT_FILE_BUFFER_SIZE)
    if not data:
      break
    current_md5.update(data)
  fp.seek(0)
  return current_md5.hexdigest()


def GetCloudApiInstance(cls, thread_state=None):
  """Gets a gsutil Cloud API instance.

  Since Cloud API implementations are not guaranteed to be thread-safe, each
  thread needs its own instance. These instances are passed to each thread
  via the thread pool logic in command.

  Args:
    cls: Command class to be used for single-threaded case.
    thread_state: Per thread state from this thread containing a gsutil
                  Cloud API instance.

  Returns:
    gsutil Cloud API instance.
  """
  return thread_state or cls.gsutil_api


def GetFileSize(fp, position_to_eof=False):
  """Returns size of file, optionally leaving fp positioned at EOF."""
  if not position_to_eof:
    cur_pos = fp.tell()
  fp.seek(0, os.SEEK_END)
  cur_file_size = fp.tell()
  if not position_to_eof:
    fp.seek(cur_pos)
  return cur_file_size


def GetStreamFromFileUrl(storage_url):
  if storage_url.IsStream():
    return sys.stdin
  else:
    return open(storage_url.object_name, 'rb')


def UrlsAreForSingleProvider(url_args):
  """Tests whether the URLs are all for a single provider.

  Args:
    url_args: Strings to check.

  Returns:
    True if URLs are for single provider, False otherwise.
  """
  provider = None
  url = None
  for url_str in url_args:
    url = StorageUrlFromString(url_str)
    if not provider:
      provider = url.scheme
    elif url.scheme != provider:
      return False
  return provider is not None


def HaveFileUrls(args_to_check):
  """Checks whether args_to_check contain any file URLs.

  Args:
    args_to_check: Command-line argument subset to check.

  Returns:
    True if args_to_check contains any file URLs.
  """
  for url_str in args_to_check:
    storage_url = StorageUrlFromString(url_str)
    if storage_url.IsFileUrl():
      return True
  return False


def HaveProviderUrls(args_to_check):
  """Checks whether args_to_check contains any provider URLs (like 'gs://').

  Args:
    args_to_check: Command-line argument subset to check.

  Returns:
    True if args_to_check contains any provider URLs.
  """
  for url_str in args_to_check:
    storage_url = StorageUrlFromString(url_str)
    if storage_url.IsCloudUrl() and storage_url.IsProvider():
      return True
  return False


def MultiprocessingIsAvailable(logger=None):
  """Checks if multiprocessing is available.

  There are some environments in which there is no way to use multiprocessing
  logic that's built into Python (e.g., if /dev/shm is not available, then
  we can't create semaphores). This simply tries out a few things that will be
  needed to make sure the environment can support the pieces of the
  multiprocessing module that we need.

  Args:
    logger: logging.logger to use for debug output.

  Returns:
    (multiprocessing_is_available, stack_trace):
      multiprocessing_is_available: True iff the multiprocessing module is
                                    available for use.
      stack_trace: The stack trace generated by the call we tried that failed.
  """
  # pylint: disable=global-variable-undefined
  global cached_multiprocessing_is_available
  global cached_multiprocessing_check_stack_trace
  global cached_multiprocessing_is_available_message
  if cached_multiprocessing_is_available is not None:
    if logger:
      logger.debug(cached_multiprocessing_check_stack_trace)
      logger.warn('\n'.join(textwrap.wrap(
          cached_multiprocessing_is_available_message + '\n')))
    return (cached_multiprocessing_is_available,
            cached_multiprocessing_check_stack_trace)

  stack_trace = None
  multiprocessing_is_available = True
  message = (
      'You have requested multiple threads or processes for an operation,'
      ' but the required functionality of Python\'s multiprocessing '
      'module is not available. Your operations will be performed '
      'sequentially, and any requests for parallelism will be ignored.')
  try:
    # Fails if /dev/shm (or some equivalent thereof) is not available for use
    # (e.g., there's no implementation, or we can't write to it, etc.).
    try:
      multiprocessing.Value('i', 0)
    except:
      if not IS_WINDOWS:
        message += ('\nPlease ensure that you have write access to both '
                    '/dev/shm and /run/shm.')
      raise  # We'll handle this in one place below.

    # Manager objects and Windows are generally a pain to work with, so try it
    # out as a sanity check. This definitely works on some versions of Windows,
    # but it's certainly possible that there is some unknown configuration for
    # which it won't.
    multiprocessing.Manager()

    # Check that the max number of open files is reasonable. Always check this
    # after we're sure that the basic multiprocessing functionality is
    # available, since this won't matter unless that's true.
    limit = 0
    if HAS_RESOURCE_MODULE:
      # Try to set this with both resource names - RLIMIT_NOFILE for most Unix
      # platforms, and RLIMIT_OFILE for BSD. Ignore AttributeError because the
      # "resource" module is not guaranteed to know about these names.
      try:
        limit = max(limit,
                    _IncreaseSoftLimitForResource(resource.RLIMIT_NOFILE))
      except AttributeError:
        pass
      try:
        limit = max(limit,
                    _IncreaseSoftLimitForResource(resource.RLIMIT_OFILE))
      except AttributeError:
        pass
    if limit < MIN_ACCEPTABLE_OPEN_FILES_LIMIT and not IS_WINDOWS:
      message += (
          '\nYour max number of open files, %s, is too low to allow safe '
          'multiprocessing calls. If you are on a Unix-like OS, then you can '
          'fix this by adding something like "ulimit -n 10000" to your '
          '~/.bashrc (Linux), ~/.bash_profile (OS X), or equivalent file, '
          'and opening a new terminal.' % limit)
      raise Exception('Max number of open files, %s, is too low.' % limit)
  except:  # pylint: disable=bare-except
    stack_trace = traceback.format_exc()
    multiprocessing_is_available = False
    if logger is not None:
      logger.debug(stack_trace)
      logger.warn('\n'.join(textwrap.wrap(message + '\n')))

  # Set the cached values so that we never need to do this check again.
  cached_multiprocessing_is_available = multiprocessing_is_available
  cached_multiprocessing_check_stack_trace = stack_trace
  cached_multiprocessing_is_available_message = message
  return (multiprocessing_is_available, stack_trace)


def CreateLock():
  """Returns either a multiprocessing lock or a threading lock.

  Use Multiprocessing lock iff we have access to the parts of the
  multiprocessing module that are necessary to enable parallelism in operations.

  Returns:
    Multiprocessing or threading lock.
  """
  if MultiprocessingIsAvailable()[0]:
    return manager.Lock()
  else:
    return threading.Lock()

