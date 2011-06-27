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

"""Implementation of gsutil commands."""

import ctypes
import datetime
import gzip
import mimetypes
import os
import platform
import re
import shutil
import signal
import sys
import tarfile
import tempfile
import time
import webbrowser
import xml.dom.minidom
import xml.sax.xmlreader
import boto
import boto.s3.connection

from boto import handler
from boto.gs.resumable_upload_handler import ResumableUploadHandler
from boto.provider import Provider
from boto.pyami.config import BotoConfigLocations
from boto.s3.resumable_download_handler import ResumableDownloadHandler
from boto.storage_uri import BucketStorageUri
from exception import CommandException
from gslib.project_id import ProjectIdHandler
import wildcard_iterator
from wildcard_iterator import ContainsWildcard
from wildcard_iterator import ResultType
from wildcard_iterator import WildcardException

GOOG_API_CONSOLE_URI = "http://code.google.com/apis/console"

_HAVE_OAUTH2 = False
try:
  from oauth2_plugin import oauth2_helper
  _HAVE_OAUTH2 = True
except ImportError:
  pass

# Enum class for specifying listing style.
class ListingStyle(object):
  SHORT = 'SHORT'
  LONG = 'LONG'
  LONG_LONG = 'LONG_LONG'


# Binary exponentiation strings.
EXP_STRINGS = [
    (0, 'B'),
    (10, 'KB'),
    (20, 'MB'),
    (30, 'GB'),
    (40, 'TB'),
    (50, 'PB'),
]

ONE_MB = 1024*1024

SCOPE_FULL_CONTROL = 'https://www.googleapis.com/auth/devstorage.full_control'
SCOPE_READ_WRITE = 'https://www.googleapis.com/auth/devstorage.read_write'
SCOPE_READ_ONLY = 'https://www.googleapis.com/auth/devstorage.read_only'

CONFIG_PRELUDE_CONTENT = """
# This file contains credentials and other configuration information needed
# by the boto library, used by gsutil. You can edit this file (e.g., to add
# credentials) but be careful not to mis-edit any of the variable names (like
# "gs_access_key_id") or remove important markers (like the "[Credentials]" and
# "[Boto]" section delimeters).
#
"""

CONFIG_BOTO_SECTION_CONTENT = """
[Boto]

# To use a proxy, edit and uncomment the proxy and proxy_port lines. If you
# need a user/password with this proxy, edit and uncomment those lines as well.
#proxy = <proxy host>
#proxy_port = <proxy port>
#proxy_user = <your proxy user name>
#proxy_pass = <your proxy password>

# The following two options control the use of a secure transport for requests
# to S3 and Google Storage. It is highly recommended to set both options to
# True in production environments, especially when using OAuth2 bearer token
# authentication with Google Storage.

# Set 'is_secure' to False to cause boto to connect using HTTP instead of the
# default HTTPS. This is useful if you want to capture/analyze traffic
# (e.g., with tcpdump). This option should always be set to True in production
# environments.
#is_secure = False

# Set 'https_validate_certificates' to False to disable server certificate
# checking. This is useful if you want to capture/analyze traffic using an
# intercepting proxy. This option should always be set to True in production
# environments.
# In gsutil, the default for this option is True. *However*, the default for
# this option in the boto library itself is currently 'False'; it is therefore
# recommended to always set this option explicitly to True in configuration
# files.
https_validate_certificates = True

# 'debug' controls the level of debug messages printed: 0 for none, 1
# for basic boto debug, 2 for all boto debug plus HTTP requests/responses.
# Note: 'gsutil -d' sets debug to 2 for that one command run.
#debug = <0, 1, or 2>

# 'num_retries' controls the number of retry attempts made when errors occur.
# The default is 5. Note: don't set this value to 0, as it will cause boto to
# fail when reusing HTTP connections.
#num_retries = <integer value>
"""

CONFIG_INPUTLESS_GSUTIL_SECTION_CONTENT = """
[GSUtil]

# 'resumable_threshold' specifies the smallest file size [bytes] for which
# resumable Google Storage transfers are attempted. The default is 1048576
# (1MB).
#resumable_threshold = 1048576

# 'resumable_tracker_dir' specifies the base location where resumable
# transfer tracker files are saved. By default they're in ~/.gsutil
#resumable_tracker_dir = <file path>

# 'default_api_version' specifies the default Google Storage API version to
# use use. If not set below gsutil defaults to API version 1.
default_api_version = 2
"""

CONFIG_OAUTH2_CONFIG_CONTENT = """
[OAuth2]
# This section specifies options used with OAuth2 authentication.

# 'token_cache' specifies how the OAuth2 client should cache access tokens.
# Valid values are:
#  'in_memory': an in-memory cache is used. This is only useful if the boto
#      client instance (and with it the OAuth2 plugin instance) persists
#      across multiple requests.
#  'file_system' : access tokens will be cached in the file system, in files
#      whose names include a key derived from the refresh token the access token
#      based on.
# The default is 'file_system'.
#token_cache = file_system
#token_cache = in_memory

# 'token_cache_path_pattern' specifies a path pattern for token cache files.
# This option is only relevant if token_cache = file_system.
# The value of this option should be a path, with place-holders '%(key)s' (which
# will be replaced with a key derived from the refresh token the cached access
# token was based on), and (optionally), %(uid)s (which will be replaced with
# the UID of the current user, if available via os.getuid()).
# Note that the config parser itself interpolates '%' placeholders, and hence
# the above placeholders need to be escaped as '%%(key)s'.
# The default value of this option is
#  token_cache_path_pattern = <tmpdir>/oauth2client-tokencache.%%(uid)s.%%(key)s
# where <tmpdir> is the system-dependent default temp directory.

# The following options specify the OAuth2 client identity and secret that is
# used when requesting and using OAuth2 tokens. If not specified, a default
# OAuth2 client for the gsutil tool is used; for uses of the boto library (with
# OAuth2 authentication plugin) in other client software, it is recommended to
# use a tool/client-specific OAuth2 client. For more information on OAuth2, see
# http://code.google.com/apis/accounts/docs/OAuth2.html
#client_id = <OAuth2 client id>
#client_secret = <OAuth2 client secret>

# The following options specify the label and endpoint URIs for the OAUth2
# authorization provider being used. Primarily useful for tool developers.
#provider_label = Google
#provider_authorization_uri = https://accounts.google.com/o/oauth2/auth
#provider_token_uri = https://accounts.google.com/o/oauth2/token
"""

CONFIG_COMMAND_HELP = """
Help on the gsutil config command:
  gsutil [-D] config [OPTION]

  The gsutil config command obtains access credentials for Google Storage, and
  writes a boto/gsutil configuration file with the obtained credentials.

  Unless specified otherwise, the configuration file is written to the default
  config file path '%s'. If the default config file already exists, an attempt
  is made to rename the existing file to a backup file '%s'; if that attempt
  fails the command will exit.

  A different destination file can be specified with the -o <file> option (use
  '-o -' to write the config to standard output). If the specified file already
  exists, the command will fail.

  By default, gsutil config obtains OAuth2 tokens as follows (for background
  on OAuth2, see http://code.google.com/apis/accounts/docs/OAuth2.html):
  The command asks the user to open a web broswer to a URL for Google's
  OAuth2 authorization page. In the browser, the user will be asked to sign
  into the user's Google Account, unless already signed in. The user is then
  prompted to authorize gsutil to access the user's Google Storage account
  on the user's behalf. If the user approves the request, a verification
  code is shown. The gsutil config command prompts for this verification
  code, which is used to obtain an OAuth2 token that is written to the
  configuration file.

  The -b option can be used to instruct gsutil config to launch a browser,
  (using python's webbrowser module) to navigate to Google's OAuth2
  authorization page.  Note that this will probably not work as expected
  if you are running gsutil from an ssh window, or using gsutil on Windows.

  The -r, -w, -f options cause gsutil config to request a token with restricted
  scope; the resulting token will be restricted to read-only operations,
  read-write operation, or all operations (including getacl/setacl operations).
  In addition, -s <scope> can be used to request additional (non-Google-Storage)
  scopes.

  If no explicit scope option is given, -f (full control) is assumed by default.

  The -a option can be used to prompt for Google Storage access key and secret
  instead.

  Options:
    -h          Print this help.
    -a          Prompt for Google Storage access key and secret instead of
                obtaining an OAuth2 token.
    -b          Launch browser to obtain OAuth2 approval and project ID instead
                of showing the URL and asking user to open the browser.
    -D          Print debug output.
    -f          Request token with full-control access (default).
    -o <file>   Write the configuration to <file> (use '-' for stdout)
    -r          Request token restricted to read-only access.
    -s <scope>  Request additional OAuth2 <scope>.
    -w          Request token restricted to read-write access.

"""

def MakeHumanReadable(num):
  """Generates human readable string for a number.

  Args:
    num: the number

  Returns:
    A string form of the number using size abbreviations (KB, MB, etc.)
  """
  i = 0
  while i+1 < len(EXP_STRINGS) and num >= (2 ** EXP_STRINGS[i+1][0]):
    i += 1
  rounded_val = round(float(num) / 2 ** EXP_STRINGS[i][0], 2)
  return '%s %s' % (rounded_val, EXP_STRINGS[i][1])


def UriStrFor(iterated_uri, obj):
  """Constructs a StorageUri string for the given iterated_uri and object.

  For example if we were iterating gs://*, obj could be an object in one
  of the user's buckets enumerated by the ls command.

  Args:
    iterated_uri: base StorageUri being iterated.
    obj: object being listed.

  Returns:
    URI string.
  """
  return '%s://%s/%s' % (iterated_uri.scheme, obj.bucket.name, obj.name)


def OpenConfigFile(file_path):
  """Creates and opens a configuration file for writing.

  The file is created with mode 0600, and attempts to open existing files will
  fail (the latter is important to prevent symlink attacks).

  It is the caller's responsibility to close the file.

  Args:
    file_path: Path of the file to be created.

  Returns:
    A writable file object for the opened file.

  Raises:
    CommandException: if an error occurred when opening the file (including when
        the file already exists).
  """
  flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
  # Accommodate Windows; stolen from python2.6/tempfile.py.
  if hasattr(os, 'O_NOINHERIT'):
    flags |= os.O_NOINHERIT
  try:
    fd = os.open(file_path, flags, 0600)
  except (OSError, IOError), e:
    raise CommandException("Failed to open %s for writing: %s" %
        (file_path, e))
  return os.fdopen(fd, "w")


class Command(object):
  """Class that contains all gsutil command code."""

  def __init__(self, gsutil_bin_dir, boto_lib_dir, usage_string,
               config_file_list, bucket_storage_uri_class=BucketStorageUri):
    """Instantiates Command class.

    Args:
      gsutil_bin_dir: bin dir from which gsutil is running.
      boto_lib_dir: lib dir where boto runs.
      usage_string: usage string to print when user makes command error.
      config_file_list: config file list returned by GetBotoConfigFileList().
      bucket_storage_uri_class: Class to instantiate for cloud StorageUris.
                                Settable for testing/mocking.
    """
    self.gsutil_bin_dir = gsutil_bin_dir
    self.usage_string = usage_string
    self.boto_lib_dir = boto_lib_dir
    self.config_file_list = config_file_list
    self.bucket_storage_uri_class = bucket_storage_uri_class

    config = boto.config
    self.proj_id_handler = ProjectIdHandler()

  def OutputUsageAndExit(self):
    sys.stderr.write(self.usage_string)
    sys.exit(0)

  def StorageUri(self, uri_str, debug=0, validate=True):
    """
    Helper to instantiate boto.StorageUri with gsutil default flag values.
    Uses self.bucket_storage_uri_class to support mocking/testing.

    Args:
      uri_str: StorageUri naming bucket + optional object.
      debug: debug level to pass in to boto connection (range 0..3).
      validate: Whether to check for bucket name validity.

    Returns:
      boto.StorageUri for given uri_str.

    Raises:
      InvalidUriError: if uri_str not valid.
    """
    return boto.storage_uri(
        uri_str, 'file', debug=debug, validate=validate,
        bucket_storage_uri_class=self.bucket_storage_uri_class)

  def CmdWildcardIterator(self, uri_or_str, result_type=ResultType.URIS,
                          headers=None, debug=0):
    """
    Helper to instantiate gslib.WildcardIterator, passing
    self.bucket_storage_uri_class to support mocking/testing.
    Args are same as gslib.WildcardIterator interface, but without the
    bucket_storage_uri_class param (which is instead filled in from Command
    class state).
    """
    return wildcard_iterator.wildcard_iterator(
        uri_or_str, self.proj_id_handler, result_type=result_type,
        bucket_storage_uri_class=self.bucket_storage_uri_class,
        headers=headers, debug=debug)

  def InsistUriNamesContainer(self, command, uri):
    """Checks that URI names a directory or bucket.

    Args:
      command: command being run
      uri: StorageUri to check

    Raises:
      CommandException: if errors encountered.
    """
    if uri.names_singleton():
      raise CommandException('Destination StorageUri must name a bucket or '
                             'directory for the\nmultiple source form of the '
                             '"%s" command.' % command)

  def CatCommand(self, args, sub_opts=None, headers=None, debug=0):
    """Implementation of cat command.

    Args:
      args: command-line argument list.
      sub_opts: list of command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: debug level to pass in to boto connection (range 0..3).

    Raises:
      CommandException: if errors encountered.
    """
    show_header = False
    if sub_opts:
      for o, unused_a in sub_opts:
        if o == '-h':
          show_header = True

    printed_one = False
    for uri_str in args:
      for uri in self.CmdWildcardIterator(uri_str, headers=headers,
                                          debug=debug):
        if not uri.object_name:
          raise CommandException('"cat" command must specify objects.')
        if show_header:
          if printed_one:
            print
          print '==> %s <==' % uri.__str__()
          printed_one = True
        tmp_file = tempfile.TemporaryFile()
        key = uri.get_key(False, headers)
        key.get_file(tmp_file, headers)
        tmp_file.seek(0)
        while True:
          # Use 8k buffer size.
          data = tmp_file.read(8192)
          if not data:
            break
          sys.stdout.write(data)
        tmp_file.close()

  def SetAclCommand(self, args, unused_sub_opts=None, headers=None, debug=0):
    """Implementation of setacl command.

    Args:
      args: command-line argument list.
      unused_sub_opts: list of command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: debug level to pass in to boto connection (range 0..3).

    Raises:
      CommandException: if errors encountered.
    """
    acl_arg = args[0]
    uri_args = args[1:]
    provider = None
    first_uri = None
    # Do a first pass over all matched objects to disallow multi-provider
    # setacl requests, because there are differences in the ACL models.
    for uri_str in uri_args:
      for uri in self.CmdWildcardIterator(uri_str, headers=headers, 
                                          debug=debug):
        if not provider:
          provider = uri.scheme
        elif uri.scheme != provider:
          raise CommandException('"setacl" command spanning providers not '
                                 'allowed.')
        if not first_uri:
          first_uri = uri

    # Get ACL object from connection for the first URI, for interpreting the
    # ACL. This won't fail because the main startup code insists on 1 arg
    # for this command.
    storage_uri = first_uri
    acl_class = storage_uri.acl_class()
    canned_acls = storage_uri.canned_acls()

    # Determine whether acl_arg names a file containing XML ACL text vs. the
    # string name of a canned ACL.
    if os.path.isfile(acl_arg):
      acl_file = open(acl_arg, 'r')
      acl_txt = acl_file.read()
      acl_file.close()
      acl_obj = acl_class()
      h = handler.XmlHandler(acl_obj, storage_uri.get_bucket())
      try:
        xml.sax.parseString(acl_txt, h)
      except xml.sax._exceptions.SAXParseException, e:
        raise CommandException('Requested ACL is invalid: %s at line %s, '
                               'column %s' % (e.getMessage(), e.getLineNumber(),
                                              e.getColumnNumber()))
      acl_arg = acl_obj
    else:
      # No file exists, so expect a canned ACL string.
      if acl_arg not in canned_acls:
        raise CommandException('Invalid canned ACL "%s".' % acl_arg)

    # Now iterate over URIs and set the ACL on each.
    for uri_str in uri_args:
      for uri in self.CmdWildcardIterator(uri_str, headers=headers,
                                          debug=debug):
        print 'Setting ACL on %s...' % uri
        uri.set_acl(acl_arg, uri.object_name, False, headers)

  def ExplainIfSudoNeeded(self, tf, dirs_to_remove):
    """Explains what to do if sudo needed to update gsutil software.

    Happens if gsutil was previously installed by a different user (typically if
    someone originally installed in a shared file system location, using sudo).

    Args:
      tf: opened TarFile.
      dirs_to_remove: list of directories to remove.

    Raises:
      CommandException: if errors encountered.
    """
    system = platform.system()
    # If running under Windows we don't need (or have) sudo.
    if system.lower().startswith('windows'):
      return

    user_id = os.getuid()
    if (os.stat(self.gsutil_bin_dir).st_uid == user_id and
        os.stat(self.boto_lib_dir).st_uid == user_id):
      return

    # Won't fail - this command runs after main startup code that insists on
    # having a config file.
    config_file = self.config_file_list
    self.CleanUpUpdateCommand(tf, dirs_to_remove)
    raise CommandException(
        ('Since it was installed by a different user previously, you will need '
         'to update using the following commands.\nYou will be prompted for '
         'your password, and the install will run as "root". If you\'re unsure '
         'what this means please ask your system administrator for help:'
         '\n\tchmod 644 %s\n\tsudo env BOTO_CONFIG=%s gsutil update'
         '\n\tchmod 600 %s') % (config_file, config_file, config_file),
        informational=True)

  # This list is checked during gsutil update by doing a lowercased
  # slash-left-stripped check. For example "/Dev" would match the "dev" entry.
  unsafe_update_dirs = [
      'applications', 'auto', 'bin', 'boot', 'desktop', 'dev',
      'documents and settings', 'etc', 'export', 'home', 'kernel', 'lib',
      'lib32', 'library', 'lost+found', 'mach_kernel', 'media', 'mnt', 'net',
      'null', 'network', 'opt', 'private', 'proc', 'program files', 'python',
      'root', 'sbin', 'scripts', 'srv', 'sys', 'system', 'tmp', 'users', 'usr',
      'var', 'volumes', 'win', 'win32', 'windows', 'winnt',
  ]

  def EnsureDirsSafeForUpdate(self, dirs):
    """Throws Exception if any of dirs is known to be unsafe for gsutil update.

    This provides a fail-safe check to ensure we don't try to overwrite
    or delete any important directories. (That shouldn't happen given the
    way we construct tmp dirs, etc., but since the gsutil update cleanup
    use shutil.rmtree() it's prudent to add extra checks.)

    Args:
      dirs: list of directories to check.

    Raises:
      CommandException: If unsafe directory encountered.
    """
    for d in dirs:
      if not d:
        d = 'null'
      if d.lstrip(os.sep).lower() in self.unsafe_update_dirs:
        raise CommandException('EnsureDirsSafeForUpdate: encountered unsafe '
                               'directory (%s); aborting update' % d)

  def CleanUpUpdateCommand(self, tf, dirs_to_remove):
    """Cleans up temp files etc. from running update command.

    Args:
      tf: opened TarFile.
      dirs_to_remove: list of directories to remove.

    """
    tf.close()
    self.EnsureDirsSafeForUpdate(dirs_to_remove)
    for directory in dirs_to_remove:
      shutil.rmtree(directory)

  def LoadVersionString(self):
    """Loads version string for currently installed gsutil command.

    Returns:
      Version string.

    Raises:
      CommandException: if errors encountered.
    """
    ver_file_path = self.gsutil_bin_dir + os.sep + 'VERSION'
    if not os.path.isfile(ver_file_path):
      raise CommandException(
          '%s not found. Did you install the\ncomplete gsutil software after '
          'the gsutil "update" command was implemented?' % ver_file_path)
    ver_file = open(ver_file_path, 'r')
    installed_version_string = ver_file.read().rstrip('\n')
    ver_file.close()
    return installed_version_string

  def UpdateCommand(self, unused_args, sub_opts=None, headers=None, debug=0):
    """Implementation of experimental update command.

    Args:
      unused_args: command-line argument list.
      sub_opts: list of command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: debug level to pass in to boto connection (range 0..3).

    Raises:
      CommandException: if errors encountered.
    """
    installed_version_string = self.LoadVersionString()

    dirs_to_remove = []
    # Retrieve gsutil tarball and check if it's newer than installed code.
    # TODO: Store this version info as metadata on the tarball object and
    # change this command's implementation to check that metadata instead of
    # downloading the tarball to check the version info.
    tmp_dir = tempfile.mkdtemp()
    dirs_to_remove.append(tmp_dir)
    os.chdir(tmp_dir)
    print 'Checking for software update...'
    self.CopyObjsCommand(['gs://pub/gsutil.tar.gz', 'file://gsutil.tar.gz'], [],
                         headers, debug)
    tf = tarfile.open('gsutil.tar.gz')
    tf.errorlevel = 1  # So fatal tarball unpack errors raise exceptions.
    tf.extract('./gsutil/VERSION')
    ver_file = open('gsutil/VERSION', 'r')
    latest_version_string = ver_file.read().rstrip('\n')
    ver_file.close()

    # The force_update option works around a problem with the way the
    # first gsutil "update" command exploded the gsutil and boto directories,
    # which didn't correctly install boto. People running that older code can
    # run "gsutil update" (to update to the newer gsutil update code) followed
    # by "gsutil update -f" (which will then update the boto code, even though
    # the VERSION is already the latest version).
    force_update = False
    if sub_opts:
      for o, unused_a in sub_opts:
        if o == '-f':
          force_update = True
    if not force_update and installed_version_string == latest_version_string:
      self.CleanUpUpdateCommand(tf, dirs_to_remove)
      raise CommandException('You have the latest version of gsutil installed.',
                             informational=True)

    print(('This command will update to the "%s" version of\ngsutil at %s') %
          (latest_version_string, self.gsutil_bin_dir))
    self.ExplainIfSudoNeeded(tf, dirs_to_remove)

    answer = raw_input('Proceed (Note: experimental command)? [y/N] ')
    if not answer or answer.lower()[0] != 'y':
      self.CleanUpUpdateCommand(tf, dirs_to_remove)
      raise CommandException('Not running update.', informational=True)

    # Ignore keyboard interrupts during the update to reduce the chance someone
    # hitting ^C leaves gsutil in a broken state.
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    # gsutil_bin_dir lists the path where the code should end up (like
    # /usr/local/gsutil), which is one level down from the relative path in the
    # tarball (since the latter creates files in ./gsutil). So, we need to
    # extract at the parent directory level.
    gsutil_bin_parent_dir = os.path.dirname(self.gsutil_bin_dir)

    # Extract tarball to a temporary directory in a sibling to gsutil_bin_dir.
    old_dir = tempfile.mkdtemp(dir=gsutil_bin_parent_dir)
    new_dir = tempfile.mkdtemp(dir=gsutil_bin_parent_dir)
    dirs_to_remove.append(old_dir)
    dirs_to_remove.append(new_dir)
    self.EnsureDirsSafeForUpdate(dirs_to_remove)
    try:
      tf.extractall(path=new_dir)
    except Exception, e:
      self.CleanUpUpdateCommand(tf, dirs_to_remove)
      raise CommandException('Update failed: %s.' % e)

    # Move old installation aside and new into place.
    os.rename(self.gsutil_bin_dir, old_dir + os.sep + 'old')
    os.rename(new_dir + os.sep + 'gsutil', self.gsutil_bin_dir)
    self.CleanUpUpdateCommand(tf, dirs_to_remove)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    print 'Update complete.'

  def CheckForDirFileConflict(self, src_uri, dst_path):
    """Checks whether copying src_uri into dst_path is not possible.

       This happens if a directory exists in local file system where a file
       needs to go or vice versa. In that case we print an error message and
       exits. Example: if the file "./x" exists and you try to do:
         gsutil cp gs://mybucket/x/y .
       the request can't succeed because it requires a directory where
       the file x exists.

    Args:
      src_uri: source StorageUri of copy
      dst_path: destination path.

    Raises:
      CommandException: if errors encountered.
    """
    final_dir = os.path.dirname(dst_path)
    if os.path.isfile(final_dir):
      raise CommandException('Cannot retrieve %s because it a file exists '
                             'where a directory needs to be created (%s).' %
                             (src_uri, final_dir))
    if os.path.isdir(dst_path):
      raise CommandException('Cannot retrieve %s because a directory exists '
                             '(%s) where the file needs to be created.' %
                             (src_uri, dst_path))

  def GetAclCommand(self, args, unused_sub_opts=None, headers=None, debug=0):
    """Implementation of getacl command.

    Args:
      args: command-line argument list.
      unused_sub_opts: list of command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: debug level to pass in to boto connection (range 0..3).

    Raises:
      CommandException: if errors encountered.
    """
    # Wildcarding is allowed but must resolve to just one object.
    uris = list(self.CmdWildcardIterator(args[0], headers=headers,
                                        debug=debug))
    if len(uris) != 1:
      raise CommandException('Wildcards must resolve to exactly one object for '
                             '"getacl" command.')
    uri = uris[0]
    if not uri.bucket_name:
      raise CommandException('"getacl" command must specify a bucket or '
                             'object.')
    acl = uri.get_acl(False, headers)
    # Pretty-print the XML to make it more easily human editable.
    parsed_xml = xml.dom.minidom.parseString(acl.to_xml().encode('utf-8'))
    print parsed_xml.toprettyxml(indent='    ')

  class FileCopyCallbackHandler(object):
    """Outputs progress info for large copy requests."""

    def __init__(self, upload):
      if upload:
        self.announce_text = 'Uploading'
      else:
        self.announce_text = 'Downloading'

    def call(self, total_bytes_transferred, total_size):
      sys.stderr.write('%s: %s/%s    \r' % (
          self.announce_text,
          MakeHumanReadable(total_bytes_transferred),
          MakeHumanReadable(total_size)))
      if total_bytes_transferred == total_size:
        sys.stderr.write('\n')

  def GetTransferHandlers(self, uri, key, file_size, upload):
    """
    Selects upload/download and callback handlers.

    We use a callback handler that shows a simple textual progress indicator
    if file_size is above the configurable threshold.

    We use a resumable transfer handler if file_size is >= the configurable
    threshold and resumable transfers are supported by the given provider.
    boto supports resumable downloads for all providers, but resumable
    uploads are currently only supported by GS.
    """
    config = boto.config
    resumable_threshold = config.getint('GSUtil', 'resumable_threshold', ONE_MB)
    if file_size >= resumable_threshold:
      cb = self.FileCopyCallbackHandler(upload).call
      num_cb = int(file_size / ONE_MB)
      resumable_tracker_dir = config.get(
          'GSUtil', 'resumable_tracker_dir',
          os.path.expanduser('~' + os.sep + '.gsutil'))
      if not os.path.exists(resumable_tracker_dir):
        os.makedirs(resumable_tracker_dir)
      if upload:
        # Encode the src bucket and key into the tracker file name.
        res_tracker_file_name = (
            re.sub('[/\\\\]', '_', 'resumable_upload__%s__%s.url' %
                   (key.bucket.name, key.name)))
      else:
        # Encode the fully-qualified src file name into the tracker file name.
        res_tracker_file_name = (
            re.sub('[/\\\\]', '_', 'resumable_download__%s.etag' %
                   (os.path.realpath(uri.object_name))))
      tracker_file = '%s%s%s' % (resumable_tracker_dir, os.sep,
                                 res_tracker_file_name)
      if upload:
        if uri.scheme == 'gs':
          transfer_handler = ResumableUploadHandler(tracker_file)
        else:
          transfer_handler = None
      else:
        transfer_handler = ResumableDownloadHandler(tracker_file)
    else:
      transfer_handler = None
      cb = None
      num_cb = None
    return (cb, num_cb, transfer_handler)

  def CopyObjToObjSameProvider(self, src_key, src_uri, dst_uri, headers):
    # Do Object -> object copy within same provider (uses
    # x-<provider>-copy-source metadata HTTP header to request copying at the
    # server). (Note: boto does not currently provide a way to pass canned_acl
    # when copying from object-to-object through x-<provider>-copy-source)
    src_bucket = src_uri.get_bucket(False, headers)
    dst_bucket = dst_uri.get_bucket(False, headers)
    start_time = time.time()
    dst_bucket.copy_key(dst_uri.object_name, src_bucket.name,
                        src_uri.object_name, headers)
    end_time = time.time()
    return (end_time - start_time, src_key.size)

  def CheckFreeSpace(self, path):
    """Return path/drive free space (in bytes)."""
    if platform.system() == 'Windows':
      free_bytes = ctypes.c_ulonglong(0)
      ctypes.windll.kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(path), None,
                                                 None,
                                                 ctypes.pointer(free_bytes))
      return free_bytes.value
    else:
      (_, f_frsize, _, _, f_bavail, _, _, _, _, _) = os.statvfs(path)
      return f_frsize * f_bavail

  def PerformResumableUploadIfApplies(self, fp, dst_uri, headers, canned_acl):
    """
    Performs resumable upload if supported by provider and file is above
    threshold, else performs non-resumable upload.

    Returns (elapsed_time, bytes_transferred).
    """
    start_time = time.time()
    file_size = os.path.getsize(fp.name)
    dst_key = dst_uri.new_key(False, headers)
    (cb, num_cb, res_upload_handler) = self.GetTransferHandlers(
        dst_uri, dst_key, file_size, True)
    if dst_uri.scheme == 'gs':
      # Resumable upload protocol is Google Storage-specific.
      dst_key.set_contents_from_file(fp, headers, policy=canned_acl,
                                     cb=cb, num_cb=num_cb,
                                     res_upload_handler=res_upload_handler)
    else:
      dst_key.set_contents_from_file(fp, headers, policy=canned_acl,
                                     cb=cb, num_cb=num_cb)
    if res_upload_handler:
      bytes_transferred = file_size - res_upload_handler.upload_start_point
    else:
      bytes_transferred = file_size
    end_time = time.time()
    return (end_time - start_time, bytes_transferred)

  def UploadFileToObject(self, sub_opts, src_key, src_uri, dst_uri, headers,
                         debug):
    gzip_exts = []
    canned_acl = None
    if sub_opts:
      for o, a in sub_opts:
        if o == '-a':
          canned_acls = dst_uri.canned_acls()
          if a not in canned_acls:
            raise CommandException('Invalid canned ACL "%s".' % a)
          canned_acl = a
        elif o == '-t':
          mimetype_tuple = mimetypes.guess_type(src_uri.object_name)
          mime_type = mimetype_tuple[0]
          content_encoding = mimetype_tuple[1]
          if mime_type:
            headers['Content-Type'] = mime_type
            print '\t[Setting Content-Type=%s]' % mime_type
          else:
            print '\t[Unknown content type -> using application/octet stream]'
          if content_encoding:
            headers['Content-Encoding'] = content_encoding
        elif o == '-z':
          gzip_exts = a.split(',')
    fname_parts = src_uri.object_name.split('.')
    if len(fname_parts) > 1 and fname_parts[-1] in gzip_exts:
      if debug:
        print 'Compressing %s (to tmp)...' % src_key
      gzip_tmp = tempfile.mkstemp()
      gzip_path = gzip_tmp[1]
      # Check for temp space. Assume the compressed object is at most 2x
      # the size of the object (normally should compress to smaller than
      # the object)
      if self.CheckFreeSpace(gzip_path) < 2*int(os.path.getsize(src_key.name)):
        raise CommandException('Inadequate temp space available to compress '
                               '%s' % src_key.name)
      the_gzip = gzip.open(gzip_path, 'wb')
      the_gzip.writelines(src_key.fp)
      the_gzip.close()
      headers['Content-Encoding'] = 'gzip'
      (elapsed_time, bytes_transferred) = self.PerformResumableUploadIfApplies(
          open(gzip_path, 'rb'), dst_uri, headers, canned_acl)
      os.unlink(gzip_path)
    else:
      (elapsed_time, bytes_transferred) = self.PerformResumableUploadIfApplies(
          src_key.fp, dst_uri, headers, canned_acl)
    return (elapsed_time, bytes_transferred)

  def DownloadObjectToFile(self, src_key, src_uri, dst_uri, headers, debug):
    (cb, num_cb, res_download_handler) = self.GetTransferHandlers(
        src_uri, src_key, src_key.size, False)
    file_name = dst_uri.object_name
    dir_name = os.path.dirname(file_name)
    if dir_name and not os.path.exists(dir_name):
      os.makedirs(dir_name)
    # For gzipped objects not named *.gz download to a temp file and unzip.
    if (hasattr(src_key, 'content_encoding') and
        src_key.content_encoding == 'gzip' and
        not file_name.endswith('.gz')):
        # We can't use tempfile.mkstemp() here because we need a predictable
        # filename for resumable downloads.
        download_file_name = '%s_.gztmp' % file_name
        need_to_unzip = True
    else:
        download_file_name = file_name
        need_to_unzip = False
    if res_download_handler:
      fp = open(download_file_name, 'ab')
    else:
      fp = open(download_file_name, 'wb')
    start_time = time.time()
    src_key.get_contents_to_file(fp, headers, cb=cb, num_cb=num_cb,
                                 res_download_handler=res_download_handler)
    fp.close()
    end_time = time.time()
    if res_download_handler:
      bytes_transferred = (
          src_key.size - res_download_handler.download_start_point)
    else:
      bytes_transferred = src_key.size
    if need_to_unzip:
      if debug:
        print 'Uncompressing tmp to %s...' % file_name
      # Downloaded gzipped file to a filename w/o .gz extension, so unzip.
      f_in = gzip.open(download_file_name, 'rb')
      f_out = open(file_name, 'wb')
      f_out.writelines(f_in)
      f_out.close();
      f_in.close();
      os.unlink(download_file_name)
    return (end_time - start_time, bytes_transferred)

  def CopyFileToFile(self, src_key, dst_uri, headers):
    dst_key = dst_uri.new_key(False, headers)
    start_time = time.time()
    dst_key.set_contents_from_file(src_key.fp, headers)
    end_time = time.time()
    return (end_time - start_time, os.path.getsize(src_key.fp.name))

  def CopyObjToObjDiffProvider(self, sub_opts, src_key, src_uri, dst_uri,
                               headers, debug):
    # We implement cross-provider object copy through a local temp file.
    # Note that a downside of this approach is that killing the gsutil
    # process partway through and then restarting will always repeat the
    # download and upload, because the temp file name is different for each
    # incarnation. (If however you just leave the process running and failures
    # happen along the way, they will continue to restart and make progress
    # as long as not too many failures happen in a row with no progress.)
    tmp = tempfile.NamedTemporaryFile()
    if self.CheckFreeSpace(tempfile.tempdir) < src_key.size:
      raise CommandException('Inadequate temp space available to perform the '
                             'requested copy')
    start_time = time.time()
    file_uri = self.StorageUri('file://%s' % tmp.name, debug=debug,
                               validate=False)
    try:
      self.DownloadObjectToFile(src_key, src_uri, file_uri, headers, debug)
      self.UploadFileToObject(sub_opts, file_uri.get_key(), file_uri, dst_uri,
                              headers, debug)
    finally:
      tmp.close()
    end_time = time.time()
    return (end_time - start_time, src_key.size)

  def PerformCopy(self, src_uri, dst_uri, sub_opts=None, headers=None, debug=0):
    """Helper method for CopyObjsCommand.

    Args:
      src_uri: source StorageUri.
      dst_uri: destination StorageUri.
      sub_opts: list of command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: debug level to pass in to boto connection (range 0..3).

    Returns:
      (elapsed_time, bytes_transferred) excluding overhead like initial HEAD.

    Raises:
      CommandException: if errors encountered.
    """
    # Make a copy of the input headers each time so we can set a different
    # MIME type for each object.
    if headers:
      headers = headers.copy()
    else:
      headers = {}

    src_key = src_uri.get_key(False, headers)
    if not src_key:
      raise CommandException('"%s" does not exist.' % src_uri)

    # Separately handle cases to avoid extra file and network copying of
    # potentially very large files/objects.

    if src_uri.is_cloud_uri() and dst_uri.is_cloud_uri():
      if src_uri.scheme == dst_uri.scheme:
        return self.CopyObjToObjSameProvider(src_key, src_uri, dst_uri,
                                             headers)
      else:
        return self.CopyObjToObjDiffProvider(sub_opts, src_key, src_uri,
                                             dst_uri, headers, debug)
    elif src_uri.is_file_uri() and dst_uri.is_cloud_uri():
      return self.UploadFileToObject(sub_opts, src_key, src_uri, dst_uri,
                                     headers, debug)
    elif src_uri.is_cloud_uri() and dst_uri.is_file_uri():
      return self.DownloadObjectToFile(src_key, src_uri, dst_uri, headers,
                                       debug)
    elif src_uri.is_file_uri() and dst_uri.is_file_uri():
      return self.CopyFileToFile(src_key, dst_uri, headers)
    else:
      raise CommandException('Unexpected src/dest case')

  def ExpandWildcardsAndContainers(self, uri_strs, sub_opts=None, headers=None,
                                   debug=0):
    """Expands URI wildcarding, object-less bucket names, and directory names.

    Examples:
      Calling with uri_strs='gs://bucket' will enumerate all contained objects.
      Calling with uri_strs='file:///tmp' will enumerate all files under /tmp
         (or under any subdirectory).
      The previous example is equivalent to uri_strs='file:///tmp/*'
         and to uri_strs='file:///tmp/**'

    Args:
      uri_strs: URI strings needing expansion
      sub_opts: list of command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: debug level to pass in to boto connection (range 0..3).

    Returns:
      dict mapping StorageUri -> list of StorageUri, for each input uri_str.

      We build a dict of the expansion instead of using a generator to
      iterate incrementally because caller needs to know count before
      iterating and performing copy operations.
    """
    # The algorithm we use is:
    # 1. Build a first level expanded list from uri_strs consisting of all
    #    URIs that aren't file wildcards, plus expansions of the file wildcards.
    # 2. Build dict from above expanded list.
    #    We do so that we can properly handle the following example:
    #      gsutil cp file0 dir0 gs://bucket
    #    where dir0 contains file1 and dir1/file2.
    # If we didn't do the first expansion, this cp command would end up
    # with this expansion:
    #   {file://file0:[file://file0],file://dir0:[file://dir0/file1,
    #                                             file://dir0/dir1/file2]}
    # instead of the (correct) expansion:
    #   {file://file0:[file://file0],file://dir0/file1:[file://dir0/file1],
    #                                file://dir0/dir1:[file://dir0/dir1/file2]}
    # The latter expansion is needed so that in the "Copying..." loop of
    # CopyObjsCommand we know that dir0 was being copied, so we create an
    # object called gs://bucket/dir0/dir1/file2. (Otherwise it would look
    # like a single file was being copied, so we'd create an object called
    # gs://bucket/file2.)

    should_recurse = False
    if sub_opts:
      for o, unused_a in sub_opts:
        if o == '-r' or o == '-R':
          should_recurse = True

    # Step 1.
    uris_to_expand = []
    for uri_str in uri_strs:
      uri = self.StorageUri(uri_str, debug=debug, validate=False)
      if uri.is_file_uri() and ContainsWildcard(uri_str):
        uris_to_expand.extend(list(
            self.CmdWildcardIterator(uri, headers=headers, debug=debug)))
      else:
        uris_to_expand.append(uri)

    # Step 2.
    result = {}
    for uri in uris_to_expand:
      if uri.names_container():
        if not should_recurse:
          if uri.is_file_uri():
            desc = 'directory'
          else:
            desc = 'bucket'
          print 'Omitting %s "%s".' % (desc, uri.uri)
          result[uri] = []
          continue
        if uri.is_file_uri():
          # dir -> convert to implicit recursive wildcard.
          uri_to_iter = '%s/**' % uri.uri
        else:
          # bucket -> convert to implicit wildcard.
          uri_to_iter = uri.clone_replace_name('*')
      else:
        uri_to_iter = uri
      result[uri] = list(self.CmdWildcardIterator(
          uri_to_iter, headers=headers, debug=debug))
    return result

  def ErrorCheckCopyRequest(self, src_uri_expansion, dst_uri_str, headers,
                            debug, command='cp'):
    """Checks copy request for problems, and builds needed base_dst_uri.

    base_dst_uri is the base uri to be used if it's a multi-object copy, e.g.,
    the URI for the destination bucket. The actual dst_uri can then be
    constructed from the src_uri and this base_dst_uri.

    Args:
      src_uri_expansion: result from ExpandWildcardsAndContainers call.
      dst_uri_str: string representation of destination StorageUri.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: flag indicating whether to include debug output
      command: name of command on behalf of which this call is running.

    Returns:
      (base_dst_uri to use for copy, bool indicator of multi-source request).

    Raises:
      CommandException: if errors found.
    """
    for src_uri in src_uri_expansion:
      if src_uri.is_cloud_uri() and not src_uri.bucket_name:
        raise CommandException('Provider-only src_uri (%s)')

    if ContainsWildcard(dst_uri_str):
      matches = list(self.CmdWildcardIterator(dst_uri_str, headers=headers,
                                              debug=debug))
      if len(matches) > 1:
        raise CommandException('Destination (%s) matches more than 1 URI' %
                               dst_uri_str)
      base_dst_uri = matches[0]
    else:
      base_dst_uri = self.StorageUri(dst_uri_str, debug=debug)

    # Make sure entire expansion didn't result in nothing to copy. This can
    # happen if user request copying a directory w/o -r option, for example.
    have_work = False
    for v in src_uri_expansion.values():
      if v:
        have_work = True
        break
    if not have_work:
      raise CommandException('Nothing to copy')

    # If multi-object copy request ensure base_dst_uri names a container.
    multi_src_request = (len(src_uri_expansion) > 1 or
                         len(src_uri_expansion.values()[0]) > 1)
    if multi_src_request:
      self.InsistUriNamesContainer(command, base_dst_uri)

    # Ensure no src/dest pairs would overwrite src. Note that this is
    # more restrictive than the UNIX 'cp' command (which would, for example,
    # allow "mv * dir" and just skip the implied mv dir dir). We disallow such
    # partial completion operations in cloud copies because they are risky.
    for src_uri in iter(src_uri_expansion):
      for exp_src_uri in src_uri_expansion[src_uri]:
        new_dst_uri = self.ConstructDstUri(src_uri, exp_src_uri, base_dst_uri)
        if self.SrcDstSame(exp_src_uri, new_dst_uri):
          raise CommandException('cp: "%s" and "%s" are the same object - '
                                 'abort.' % (exp_src_uri.uri, new_dst_uri.uri))

    return (base_dst_uri, multi_src_request)

  def HandleMultiSrcCopyRequst(self, src_uri_expansion, dst_uri):
    """
    Rewrites dst_uri and creates dest dir as needed, if this is a
    multi-source copy.

    Args:
      src_uri_expansion: result from ExpandWildcardsAndContainers call.
      dst_uri: uri constructed by ErrorCheckCopyRequest() call.

    Returns:
      dst_uri to use for copy.
    """
    # If src_uri and dst_uri both name containers, handle
    # two cases to make copy command work like UNIX "cp -r" works:
    #   a) if dst_uri names a non-existent directory, copy objects to a new
    #      directory with the dst_uri name. In this case,
    #        gsutil gs://bucket/a dir
    #      should create dir/a.
    #   b) if dst_uri names an existing directory, copy objects under that
    #      directory. In this case,
    #        gsutil gs://bucket/a dir
    #      should create dir/bucket/a.
    src_uri_to_check = src_uri_expansion.keys()[0]
    if (src_uri_to_check.names_container() and dst_uri.names_container() and
        os.path.exists(dst_uri.object_name)):
      new_name = ('%s%s%s' % (dst_uri.object_name, os.sep,
                              src_uri_to_check.bucket_name)).rstrip('/')
      dst_uri = dst_uri.clone_replace_name(new_name)
    # Create dest directory if needed.
    if dst_uri.is_file_uri() and not os.path.exists(dst_uri.object_name):
      os.makedirs(dst_uri.object_name)
    return dst_uri

  def SrcDstSame(self, src_uri, dst_uri):
    """Checks if src_uri and dst_uri represent same object.

    We don't handle anything about hard or symbolic links.

    Args:
      src_uri: source StorageUri.
      dst_uri: dest StorageUri.

    Returns:
      Bool indication.
    """
    if src_uri.is_file_uri() and dst_uri.is_file_uri():
      # Translate a/b/./c to a/b/c, so src=dst comparison below works.
      new_src_path = re.sub('%s+\.%s+' % (os.sep, os.sep), os.sep,
                            src_uri.object_name)
      new_src_path = re.sub('^.%s+' % os.sep, '', new_src_path)
      new_dst_path = re.sub('%s+\.%s+' % (os.sep, os.sep), os.sep,
                            dst_uri.object_name)
      new_dst_path = re.sub('^.%s+' % os.sep, '', new_dst_path)
      return (src_uri.clone_replace_name(new_src_path).uri ==
              dst_uri.clone_replace_name(new_dst_path).uri)
    else:
      return src_uri.uri == dst_uri.uri

  def ConstructDstUri(self, src_uri, exp_src_uri, base_dst_uri):
    """Constructs a destination URI for CopyObjsCommand.

    Args:
      src_uri: src_uri to be copied.
      exp_src_uri: single URI from wildcard expansion of src_uri.
      base_dst_uri: uri constructed by ErrorCheckCopyRequest() call.

    Returns:
      dst_uri to use for copy.
    """
    if base_dst_uri.names_container():
      # To match naming semantics of UNIX 'cp' command, copying files
      # to buckets/dirs should result in objects/files named by just the
      # final filename component; while copying directories should result
      # in objects/files mirroring the directory hierarchy. Example of the
      # first case:
      #   gsutil cp dir1/file1 gs://bucket
      # should create object gs://bucket/file1
      # Example of the second case:
      #   gsutil cp dir1/dir2 gs://bucket
      # should create object gs://bucket/dir2/file2 (assuming dir1/dir2
      # contains file2).
      if src_uri.names_container():
        dst_path_start = (src_uri.object_name.rstrip(os.sep)
                          .rpartition(os.sep)[-1])
        start_pos = exp_src_uri.object_name.find(dst_path_start)
        dst_key_name = exp_src_uri.object_name[start_pos:]
      else:
        # src is a file or object, so use final component of src name.
        dst_key_name = os.path.basename(exp_src_uri.object_name)
      if base_dst_uri.is_file_uri():
        # dst names a directory, so append src obj name to dst obj name.
        dst_key_name = '%s%s%s' % (base_dst_uri.object_name, os.sep,
                                   dst_key_name)
        self.CheckForDirFileConflict(exp_src_uri, dst_key_name)
    else:
      # dest is an object or file: use dst obj name
      dst_key_name = base_dst_uri.object_name
    return base_dst_uri.clone_replace_name(dst_key_name)

  def CopyObjsCommand(self, args, sub_opts=None, headers=None, debug=0,
                      command='cp'):
    """Implementation of cp command.

    Args:
      args: command-line argument list.
      sub_opts: list of command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: debug level to pass in to boto connection (range 0..3).
      command: name of command on behalf of which this call is running.

    Raises:
      CommandException: if errors encountered.
    """
    # Expand wildcards and containers in source StorageUris.
    src_uri_expansion = self.ExpandWildcardsAndContainers(
        args[0:len(args)-1], sub_opts, headers, debug)

    # Check for various problems and determine base_dst_uri based for request.
    (base_dst_uri, multi_src_request) = self.ErrorCheckCopyRequest(
        src_uri_expansion, args[-1], headers, debug, command)
    # Rewrite base_dst_uri and create dest dir as needed for multi-source copy.
    if multi_src_request:
      base_dst_uri = self.HandleMultiSrcCopyRequst(src_uri_expansion,
                                                   base_dst_uri)

    # Now iterate over expanded src URIs, and perform copy operations.
    total_elapsed_time = total_bytes_transferred = 0
    for src_uri in iter(src_uri_expansion):
      for exp_src_uri in src_uri_expansion[src_uri]:
        print 'Copying %s...' % exp_src_uri
        dst_uri = self.ConstructDstUri(src_uri, exp_src_uri, base_dst_uri)
        (elapsed_time, bytes_transferred) = self.PerformCopy(
            exp_src_uri, dst_uri, sub_opts, headers, debug)
        total_elapsed_time += elapsed_time
        total_bytes_transferred += bytes_transferred
    if debug == 3:
      # Note that this only counts the actual GET and PUT bytes for the copy
      # - not any transfers for doing wildcard expansion, the initial HEAD
      # request boto performs when doing a bucket.get_key() operation, etc.
      if total_bytes_transferred != 0:
        print 'Total bytes copied=%d, total elapsed time=%5.3f secs (%sps)' % (
            total_bytes_transferred, total_elapsed_time,
            MakeHumanReadable(float(total_bytes_transferred) /
                              float(total_elapsed_time)))

  def HelpCommand(self, unused_args, unused_sub_opts=None, unused_headers=None,
                  unused_debug=None):
    """Implementation of help command.

    Args:
      unused_args: command-line argument list.
      unused_sub_opts: list of command-specific options from getopt.
      unused_headers: dictionary containing optional HTTP headers to send.
      unused_debug: flag indicating whether to include debug output.
    """
    self.OutputUsageAndExit()

  def VerCommand(self, unused_args, unused_sub_opts=None, unused_headers=None,
                 unused_debug=None):
    """Implementation of ver command.

    Args:
      unused_args: command-line argument list.
      unused_sub_opts: list of command-specific options from getopt.
      unused_headers: dictionary containing optional HTTP headers to send.
      unused_debug: flag indicating whether to include debug output.
    """
    config_ver = ''
    for path in BotoConfigLocations:
      try:
        f = open(path, 'r')
        while True:
          line = f.readline()
          if not line:
            break
          if line.find('was created by gsutil version') != -1:
            config_ver = ', config file version %s' % line.split('"')[-2]
            break
        # Only look at first first config file found in BotoConfigLocations.
        break
      except IOError:
        pass

    print 'gsutil version %s%s, python version %s' % (
        self.LoadVersionString(), config_ver, sys.version)

  def PrintBucketInfo(self, bucket_uri, listing_style, headers=None, debug=0):
    """Print listing info for given bucket.

    Args:
      bucket_uri: StorageUri being listed.
      listing_style: ListingStyle enum describing type of output desired.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: debug level to pass in to boto connection (range 0..3).

    Returns:
      Tuple (total objects, total bytes) in the bucket.
    """
    bucket_objs = 0
    bucket_bytes = 0
    if listing_style == ListingStyle.SHORT:
      print bucket_uri
    else:
      try:
        for obj in self.CmdWildcardIterator(
            bucket_uri.clone_replace_name('*'), 
            ResultType.KEYS, headers=headers, debug=debug):
          bucket_objs += 1
          bucket_bytes += obj.size
      except WildcardException, e:
        # Ignore non-matching wildcards, to allow empty bucket listings.
        if e.reason.find('No matches') == -1:
          raise e
      if listing_style == ListingStyle.LONG:
        print '%s : %s objects, %s' % (
            bucket_uri, bucket_objs, MakeHumanReadable(bucket_bytes))
      else:  # listing_style == ListingStyle.LONG_LONG:
        location_constraint = bucket_uri.get_location(validate=False,
                                                      headers=headers)
        location_output = ''
        if location_constraint:
            location_output = '\n\tLocationConstraint: %s' % location_constraint
        self.proj_id_handler.FillInProjectHeaderIfNeeded(
            'get_acl', bucket_uri, headers)
        print '%s :\n\t%d objects, %s%s\n\tACL: %s' % (
            bucket_uri, bucket_objs, MakeHumanReadable(bucket_bytes),
            location_output, bucket_uri.get_acl(False, headers))
    return (bucket_objs, bucket_bytes)

  def PrintObjectInfo(self, iterated_uri, obj, listing_style, headers, debug):
    """Print listing info for given object.

    Args:
      iterated_uri: base StorageUri being listed (e.g., gs://abc/*).
      obj: object to be listed (or None if no associated object).
      listing_style: ListingStyle enum describing type of output desired.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: flag indicating whether to include debug output

    Returns:
      Object length (if listing_style is one of the long listing formats).

    Raises:
      Exception: if calling bug encountered.
    """
    if listing_style == ListingStyle.SHORT:
      print UriStrFor(iterated_uri, obj)
      return 0
    elif listing_style == ListingStyle.LONG:
      # Exclude timestamp fractional secs (example: 2010-08-23T12:46:54.187Z).
      timestamp = obj.last_modified[:19].decode('utf8').encode('ascii')
      print '%10s  %s  %s' % (obj.size, timestamp, UriStrFor(iterated_uri, obj))
      return obj.size
    elif listing_style == ListingStyle.LONG_LONG:
      uri_str = UriStrFor(iterated_uri, obj)
      print '%s:' % uri_str
      obj.open_read()
      print '\tObject size:\t%s' % obj.size
      print '\tLast mod:\t%s' % obj.last_modified
      if obj.cache_control:
        print '\tCache control:\t%s' % obj.cache_control
      print '\tMIME type:\t%s' % obj.content_type
      if obj.content_encoding:
        print '\tContent-Encoding:\t%s' % obj.content_encoding
      if obj.metadata:
        for name in obj.metadata:
          print '\tMetadata:\t%s = %s' % (name, obj.metadata[name])
      print '\tEtag:\t%s' % obj.etag.strip('"\'')
      print '\tACL:\t%s' % (
          self.StorageUri(uri_str, debug=debug).get_acl(False, headers))
      return obj.size
    else:
      raise Exception('Unexpected ListingStyle(%s)' % listing_style)

  def ListCommand(self, args, sub_opts=None, headers=None, debug=0):
    """Implementation of ls command.

    Args:
      args: command-line argument list.
      sub_opts: list of command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: debug level to pass in to boto connection (range 0..3).
    """
    listing_style = ListingStyle.SHORT
    get_bucket_info = False
    if sub_opts:
      for o, a in sub_opts:
        if o == '-b':
          get_bucket_info = True
        elif o == '-l':
          listing_style = ListingStyle.LONG
        elif o == '-L':
          listing_style = ListingStyle.LONG_LONG
        elif o == '-p':
          self.proj_id_handler.SetProjectId(a)

    if not args:
      # default to listing all gs buckets
      args = ['gs://']

    total_objs = 0
    total_bytes = 0
    for uri_str in args:
      uri = self.StorageUri(uri_str, debug=debug, validate=False)
      self.proj_id_handler.FillInProjectHeaderIfNeeded('ls', uri, headers)

      if not uri.bucket_name:
        # Provider URI: add bucket wildcard to list buckets.
        for uri in self.CmdWildcardIterator('%s://*' % uri.scheme,
                                            headers=headers, debug=debug):
          (bucket_objs, bucket_bytes) = self.PrintBucketInfo(uri, listing_style,
                                                             headers=headers,
                                                             debug=debug)
          total_bytes += bucket_bytes
          total_objs += bucket_objs

      elif not uri.object_name:
        if get_bucket_info:
          # ls -b request on provider+bucket URI: List info about bucket(s).
          for uri in self.CmdWildcardIterator(uri, headers=headers,
                                              debug=debug):
            (bucket_objs, bucket_bytes) = self.PrintBucketInfo(uri,
                                                               listing_style,
                                                               headers=headers,
                                                               debug=debug)
            total_bytes += bucket_bytes
            total_objs += bucket_objs
        else:
          # ls request on provider+bucket URI: List objects in the bucket(s).
          for obj in self.CmdWildcardIterator(uri.clone_replace_name('*'),
                                              ResultType.KEYS, headers=headers,
                                              debug=debug):
            total_bytes += self.PrintObjectInfo(uri, obj, listing_style,
                                                headers=headers, debug=debug)
            total_objs += 1

      else:
        # Provider+bucket+object URI -> list the object(s).
        for obj in self.CmdWildcardIterator(uri, ResultType.KEYS,
                                            headers=headers, debug=debug):
          total_bytes += self.PrintObjectInfo(uri, obj, listing_style,
                                              headers=headers, debug=debug)
          total_objs += 1
    if listing_style != ListingStyle.SHORT:
      print ('TOTAL: %d objects, %d bytes (%s)' %
             (total_objs, total_bytes, MakeHumanReadable(float(total_bytes))))

  def MakeBucketsCommand(self, args, sub_opts=None, headers=None, debug=0):
    """Implementation of mb command.

    Args:
      args: command-line argument list.
      sub_opts: list of command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: debug level to pass in to boto connection (range 0..3).

    Raises:
      CommandException: if errors encountered.
    """
    location = ''
    if sub_opts:
      for o, a in sub_opts:
        if o == '-l':
          location = a
        elif o == '-p':
          self.proj_id_handler.SetProjectId(a)

    if not headers:
      headers = {}
    else:
      headers = headers.copy()

    for bucket_uri_str in args:
      bucket_uri = self.StorageUri(bucket_uri_str, debug=debug)
      self.proj_id_handler.FillInProjectHeaderIfNeeded('mb', bucket_uri, headers)
      print 'Creating %s...' % bucket_uri
      bucket_uri.create_bucket(headers=headers, location=location)

  def MoveObjsCommand(self, args, sub_opts=None, headers=None, debug=0):
    """Implementation of mv command.

       Note that there is no atomic rename operation - this command is simply
       a shorthand for 'cp' followed by 'rm'.

    Args:
      args: command-line argument list.
      sub_opts: list of command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: debug level to pass in to boto connection (range 0..3).

    Raises:
      CommandException: if errors encountered.
    """
    # Refuse to delete a bucket or directory src URI (force users to explicitly
    # do that as a separate operation).
    src_uri_to_check = self.StorageUri(args[0], debug=debug, validate=False)
    if src_uri_to_check.names_container():
      raise CommandException('Will not remove source buckets or directories. '
                             'You must separately copy and remove for that '
                             'purpose.')

    if len(args) > 2:
      self.InsistUriNamesContainer('mv', self.StorageUri(args[-1]))

    # Expand wildcards before calling CopyObjsCommand and RemoveObjsCommand,
    # to prevent the following problem: starting with a bucket containing
    # only the object gs://bucket/obj, say the user does:
    #   gsutil mv gs://bucket/* gs://bucket/d.txt
    # If we didn't expand the wildcard first, the CopyObjsCommand would
    # first copy gs://bucket/obj to gs://bucket/d.txt, and the
    # RemoveObjsCommand would then remove that object.
    exp_arg_list = []
    for uri_str in args:
      uri = self.StorageUri(uri_str, debug=debug, validate=False)
      if ContainsWildcard(uri_str):
        exp_arg_list.extend(str(u) for u in list(
            self.CmdWildcardIterator(uri, headers=headers, debug=debug)))
      else:
        exp_arg_list.append(uri.uri)

    self.CopyObjsCommand(exp_arg_list, sub_opts, headers, debug, 'mv')
    self.RemoveObjsCommand(exp_arg_list[0:-1], sub_opts, headers, debug)

  def RemoveBucketsCommand(self, args, unused_sub_opts=None, headers=None,
                           debug=0):
    """Implementation of rb command.

    Args:
      args: command-line argument list.
      unused_sub_opts: list of command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: debug level to pass in to boto connection (range 0..3).

    Raises:
      CommandException: if errors encountered.
    """
    # Expand bucket name wildcards, if any.
    for uri_str in args:
      for uri in self.CmdWildcardIterator(uri_str, headers=headers,
                                          debug=debug):
        if uri.object_name:
          raise CommandException('"rb" command requires a URI with no object '
                                 'name')
        print 'Removing %s...' % uri
        uri.delete_bucket(headers)

  def RemoveObjsCommand(self, args, sub_opts=None, headers=None, debug=0):
    """Implementation of rm command.

    Args:
      args: command-line argument list.
      sub_opts: list of command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: debug level to pass in to boto connection (range 0..3).

    Raises:
      CommandException: if errors encountered.
    """
    continue_on_error = False
    if sub_opts:
      for o, unused_a in sub_opts:
        if o == '-f':
          continue_on_error = True
    # Expand object name wildcards, if any.
    for uri_str in args:
      try:
        for uri in self.CmdWildcardIterator(uri_str, headers=headers,
                                            debug=debug):
          if uri.names_container():
            if uri.is_cloud_uri():
              # Before offering advice about how to do rm + rb, ensure those
              # commands won't fail because of bucket naming problems.
              boto.s3.connection.check_lowercase_bucketname(uri.bucket_name)
            uri_str = uri_str.rstrip('/\\')
            raise CommandException('"rm" command will not remove buckets. To '
                                   'delete this/these bucket(s) do:\n\tgsutil rm '
                                   '%s/*\n\tgsutil rb %s' % (uri_str, uri_str))
          print 'Removing %s...' % uri
          uri.delete_key(validate=False, headers=headers)
      except Exception, e:
        if not continue_on_error:
          raise

  def WriteBotoConfigFile(self, config_file, use_oauth2=True,
      launch_browser=True, oauth2_scopes=[SCOPE_FULL_CONTROL]):
    """Creates a boto config file interactively.
    
    Needed credentials are obtained interactively, either by asking the user for
    access key and secret, or by walking the user through the OAuth2 approval
    flow.

    Args:
      config_file: file object to which the resulting config file will be
          written.
      use_oauth2: if True, walk user through OAuth2 approval flow and produce a
          config with an oauth2_refresh_token credential. If false, ask the
          user for access key and secret.
      launch_browser: in the OAuth2 approval flow, attempt to open a browser
          window and navigate to the approval URL.
      oauth2_scopes: a list of OAuth2 scopes to request authorization for, when
          using OAuth2.
    """

    # Collect credentials
    provider_map = {'aws': 'aws', 'google': 'gs'}
    uri_map = {'aws': 's3', 'google': 'gs'}
    key_ids = {}
    sec_keys = {}
    if use_oauth2:
      oauth2_refresh_token = oauth2_helper.OAuth2ApprovalFlow(
          oauth2_helper.OAuth2ClientFromBotoConfig(boto.config),
          oauth2_scopes, launch_browser)
    else:
      got_creds = False
      for provider in provider_map:
        if provider == 'google':
          key_ids[provider] = raw_input('What is your %s access key ID? ' %
                                        provider)
          sec_keys[provider] = raw_input('What is your %s secret access key? ' %
                                         provider)
          got_creds = True
          if not key_ids[provider] or not sec_keys[provider]:
            raise CommandException(
                'Incomplete credentials provided. Please try again.')
      if not got_creds:
        raise CommandException('No credentials provided. Please try again.')

    # Write the config file prelude.
    config_file.write(CONFIG_PRELUDE_CONTENT)
    config_file.write(
        '# This file was created by gsutil version "%s"\n# at %s.\n'
        % (self.LoadVersionString(),
           datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    config_file.write('#\n# You can create additional configuration files by '
        'running\n# gsutil config [options] [-o <config-file>]\n\n\n')

    # Write the config file Credentials section.
    config_file.write('[Credentials]\n\n')
    if use_oauth2:
      config_file.write('# Google OAuth2 credentials (for "gs://" URIs):\n')
      config_file.write('# The following OAuth2 token is authorized for '
          'scope(s):\n')
      for scope in oauth2_scopes:
        config_file.write('#     %s\n' % scope)
      config_file.write('gs_oauth2_refresh_token = %s\n\n' %
          oauth2_refresh_token.refresh_token)
    else:
      config_file.write('# To add Google OAuth2 credentials ("gs://" URIs), '
          'edit and uncomment the\n# following line:\n'
          '#gs_oauth2_refresh_token = <your OAuth2 refresh token>\n\n')
    
    for provider in provider_map:
      key_prefix = provider_map[provider]
      uri_scheme = uri_map[provider]
      if provider in key_ids and provider in sec_keys:
        config_file.write('# %s credentials ("%s://" URIs):\n' %
                  (provider, uri_scheme))
        config_file.write('%s_access_key_id = %s\n' %
            (key_prefix, key_ids[provider]))
        config_file.write('%s_secret_access_key = %s\n' %
            (key_prefix, sec_keys[provider]))
      else:
        config_file.write('# To add %s credentials ("%s://" URIs), edit and '
                  'uncomment the\n# following two lines:\n'
                  '#%s_access_key_id = <your %s access key ID>\n'
                  '#%s_secret_access_key = <your %s secret access key>\n' %
                  (provider, uri_scheme, key_prefix, provider, key_prefix,
                   provider))
      host_key = Provider.HostKeyMap[provider]
      config_file.write('# The ability to specify an alternate storage host '
                'is primarily for cloud\n# storage service developers.\n'
                '#%s_host = <alternate storage host address>\n\n' % host_key)

    # Write the config file Boto section.
    config_file.write('%s\n' % CONFIG_BOTO_SECTION_CONTENT)

    # Write the config file GSUtil section that doesn't depend on user input.
    config_file.write(CONFIG_INPUTLESS_GSUTIL_SECTION_CONTENT)

    # Write the config file GSUtil section that includes the default
    # project ID input from the user.
    if launch_browser:
      sys.stdout.write(
          'Attempting to launch a browser to open the Google API console at '
          'URL: %s\n\n' 
          '[Note: due to a Python bug, you may see a spurious error message '
          '"object is not\n callable [...] in [...] Popen.__del__" which can '
          'be ignored.]\n\n' % GOOG_API_CONSOLE_URI)
      sys.stdout.write(
          'In your browser you should see the API Console. Click "Storage" and look '
          'for the value under "Identifying your project\n\n')
      if not webbrowser.open(GOOG_API_CONSOLE_URI, new=1, autoraise=True):
        sys.stdout.write(
            'Launching browser appears to have failed; please navigate a browser '
            'to the following URL:\n%s\n' % GOOG_API_CONSOLE_URI)
      # Short delay; webbrowser.open on linux insists on printing out a message
      # which we don't want to run into the prompt for the auth code.
      time.sleep(2)
    else:
      sys.stdout.write(
          '\nPlease navigate your browser to %s,\nthen click "Services" on the '
          'left side panel and ensure you have Storage'
          '\nactivated, then click "Storage" on the left side panel and find '
          'the "x-goog-project-id" on that page.\n' %
          GOOG_API_CONSOLE_URI)
    default_project_id = raw_input('What is your project-id? ')
    project_id_section_prelude = """
# 'default_project_id' specifies the default Google Storage project ID to use
# with the 'mb' and 'ls' commands. If defined it overrides the default value
# you set in the API Console. Either of these defaults can be overridden
# by specifying the -p option to the 'mb' and 'ls' commands.
"""
    if default_project_id:
      config_file.write('%sdefault_project_id = %s\n\n\n' %
                        (project_id_section_prelude, default_project_id))
    else:
      sys.stderr.write('No default project ID entered. You will need to edit '
                       'the default_project_id value\nin your boto config file '
                       'before using "gsutil ls gs://" or "mb" commands'
                       'with the default API version 2.\n')
      config_file.write('%s#default_project_id = <value>\n\n\n' %
                        project_id_section_prelude)

    # Write the config file OAuth2 section.
    config_file.write(CONFIG_OAUTH2_CONFIG_CONTENT)

  def CreateConfigCommand(self, args_unused=[], sub_opts=[],
                          headers_unused=None, debug=0):
    """Implementation of the 'config' command.

    Args:
      sub_opts: list of command-specific options from getopt.
      debug: debug level to pass in to boto connection (range 0..3).

    Raises:
      CommandException: if errors encountered.
    """
    scopes = []
    use_oauth2 = True
    launch_browser = False
    output_file_name = None
    for opt, opt_arg in sub_opts:
      if opt == '-h':
        sys.stderr.write(CONFIG_COMMAND_HELP)
        sys.exit(0)
      if opt == '-a':
        use_oauth2 = False
      if opt == '-b':
        launch_browser = True
      if opt == '-f':
        scopes.append(SCOPE_FULL_CONTROL)
      if opt == '-w':
        scopes.append(SCOPE_READ_WRITE)
      if opt == '-r':
        scopes.append(SCOPE_READ_ONLY)
      if opt == '-s':
        scopes.append(opt_arg)
      if opt == '-o':
        output_file_name = opt_arg

    if use_oauth2 and not _HAVE_OAUTH2:
      raise CommandException(
          "OAuth2 is only supported when running under Python 2.6 or later\n"
          "(unless additional dependencies are installed, "
          "see README for details);\n"
          "you are running Python %s.\nUse 'gsutil config -a' to create a "
          "config with Developer Key authentication credentials." % sys.version)

    if len(scopes) == 0:
      scopes.append(SCOPE_FULL_CONTROL)

    if output_file_name is None:
      # Use the default config file name, if it doesn't exist or can be moved
      # out of the way without clobbering an existing backup file.
      default_config_path = os.path.expanduser(os.path.join('~', '.boto'))
      if not os.path.exists(default_config_path):
        output_file_name = default_config_path
      else:
        default_config_path_bak = default_config_path + ".bak"
        if os.path.exists(default_config_path_bak):
          raise CommandException("Cannot back up existing config "
              "file '%s': backup file exists ('%s')."
              % (default_config_path, default_config_path_bak))
        else:
          try:
            sys.stderr.write(
                "Backing up existing config file '%s' to '%s'...\n"
                % (default_config_path, default_config_path_bak))
            os.rename(default_config_path, default_config_path_bak)
          except e:
            raise CommandException("Failed to back up existing config "
                "file ('%s' -> '%s'): %s."
                % (default_config_path, default_config_path_bak, e))
          output_file_name = default_config_path

    if output_file_name == '-':
      output_file = sys.stdout
    else:
      output_file = OpenConfigFile(output_file_name)
      sys.stderr.write(
          'This script will create a boto config file at\n%s\ncontaining your '
          'credentials, based on your responses to the following questions.\n\n'
          % output_file_name)

    try:
      self.WriteBotoConfigFile(output_file, use_oauth2=use_oauth2,
          launch_browser=launch_browser, oauth2_scopes=scopes)
    except Exception, e:
      # If an error occurred during config file creation, remove the invalid
      # config file.
      if output_file_name != '-':
        output_file.close()
        os.unlink(output_file_name)
      raise

    if output_file_name != '-':
      output_file.close()
      sys.stderr.write(
          '\nBoto config file "%s" created. If you need to use\na proxy to '
          'access the Internet please see the instructions in that file.\n'
          % output_file_name)
