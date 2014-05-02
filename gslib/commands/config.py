# Copyright 2011 Google Inc. All Rights Reserved.
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
"""Implementation of config command for creating a gsutil configuration file."""

from __future__ import absolute_import

import datetime
from httplib import ResponseNotReady
import multiprocessing
import os
import platform
import signal
import stat
import sys
import textwrap
import time
import webbrowser

import boto
from boto.provider import Provider
from httplib2 import ServerNotFoundError
from oauth2client.client import HAS_CRYPTO

import gslib
from gslib.command import Command
from gslib.commands.compose import MAX_COMPONENT_COUNT
from gslib.cred_types import CredTypes
from gslib.exception import AbortException
from gslib.exception import CommandException
from gslib.util import IS_WINDOWS
from gslib.util import TWO_MB


_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil [-D] config [-a] [-b] [-e] [-f] [-o <file>] [-r] [-s <scope>] [-w]


<B>DESCRIPTION</B>
  The gsutil config command obtains access credentials for Google Cloud
  Storage and writes a boto/gsutil configuration file containing the obtained
  credentials along with a number of other configuration-controllable values.

  Unless specified otherwise (see OPTIONS), the configuration file is written
  to ~/.boto (i.e., the file .boto under the user's home directory). If the
  default file already exists, an attempt is made to rename the existing file
  to ~/.boto.bak; if that attempt fails the command will exit. A different
  destination file can be specified with the -o option (see OPTIONS).

  Because the boto configuration file contains your credentials you should
  keep its file permissions set so no one but you has read access. (The file
  is created read-only when you run gsutil config.)


<B>CREDENTIALS</B>
  By default gsutil config obtains OAuth2 credentials, and writes them
  to the [Credentials] section of the configuration file. The -r, -w,
  -f options (see OPTIONS below) cause gsutil config to request a token
  with restricted scope; the resulting token will be restricted to read-only
  operations, read-write operations, or all operations (including acl get/set,
  defacl get/set, and logging get/'set on'/'set off' operations). In
  addition, -s <scope> can be used to request additional (non-Google-Storage)
  scopes.

  If you want to use credentials based on access key and secret (the older
  authentication method before OAuth2 was supported) instead of OAuth2,
  see help about the -a option in the OPTIONS section.

  If you wish to use gsutil with other providers (or to copy data back and
  forth between multiple providers) you can edit their credentials into the
  [Credentials] section after creating the initial configuration file.


<B>CONFIGURING SERVICE ACCOUNT CREDENTIALS</B>
  You can configure credentials for service accounts using the gsutil config -e
  option. Service accounts are useful for authenticating on behalf of a service
  or application (as opposed to a user).

  When you run gsutil config -e, you will be prompted for your service account
  email address and the path to your private key file. To get these data, visit
  the `Google Developers Console <https://cloud.google.com/console#/project>`_,
  click on the project you are using, then click "APIs & auth", then click
  "Credentials", then click "CREATE NEW CLIENT ID"; on the pop-up dialog box
  select "Service account" and click "Create Client ID". This will download
  a private key file, which you should move to a somewhere
  accessible from the machine where you run gsutil. Make sure to set its
  protection so only the users you want to be able to authenticate as have
  access.
  
  Note that your service account will NOT be considered an Owner for the
  purposes of API access (see "gsutil help creds" for more information about
  this). See https://developers.google.com/accounts/docs/OAuth2ServiceAccount
  for further information on service account authentication.


<B>CONFIGURATION FILE SELECTION PROCEDURE</B>
  By default, gsutil will look for the configuration file in /etc/boto.cfg and
  ~/.boto. You can override this choice by setting the BOTO_CONFIG environment
  variable. This is also useful if you have several different identities or
  cloud storage environments: By setting up the credentials and any additional
  configuration in separate files for each, you can switch environments by
  changing environment variables.

  You can also set up a path of configuration files, by setting the BOTO_PATH
  environment variable to contain a ":" delimited path. For example setting
  the BOTO_PATH environment variable to:

    /etc/projects/my_group_project.boto.cfg:/home/mylogin/.boto

  will cause gsutil to load each configuration file found in the path in
  order. This is useful if you want to set up some shared configuration
  state among many users: The shared state can go in the central shared file
  ( /etc/projects/my_group_project.boto.cfg) and each user's individual
  credentials can be placed in the configuration file in each of their home
  directories. (For security reasons users should never share credentials
  via a shared configuration file.)


<B>CONFIGURATION FILE STRUCTURE</B>
  The configuration file contains a number of sections: [Credentials],
  [Boto], [GSUtil], and [OAuth2]. If you edit the file make sure to edit the
  appropriate section (discussed below), and to be careful not to mis-edit
  any of the setting names (like "gs_access_key_id") and not to remove the
  section delimiters (like "[Credentials]").


<B>ADDITIONAL CONFIGURATION-CONTROLLABLE FEATURES</B>
  With the exception of setting up gsutil to work through a proxy (see
  below), most users won't need to edit values in the boto configuration file;
  values found in there tend to be of more specialized use than command line
  option-controllable features.

  The following are the currently defined configuration settings, broken
  down by section. Their use is documented in comments preceding each, in
  the configuration file. If you see a setting you want to change that's not
  listed in your current file, see the section below on Updating to the Latest
  Configuration File.

  The currently supported settings, are, by section:

    [Credentials]
      aws_access_key_id
      aws_secret_access_key
      gs_access_key_id
      gs_host
      gs_json_host
      gs_json_port 
      gs_oauth2_refresh_token
      gs_port
      gs_secret_access_key
      s3_host
      s3_port

    [Boto]
      proxy
      proxy_port
      proxy_user
      proxy_pass
      http_socket_timeout
      https_validate_certificates
      debug
      num_retries

    [GSUtil]
      check_hashes
      content_language
      default_api_version
      default_project_id
      json_api_version
      parallel_composite_upload_component_size
      parallel_composite_upload_threshold
      parallel_process_count
      parallel_thread_count
      prefer_api
      resumable_threshold
      resumable_tracker_dir
      rsync_buffer_lines
      software_update_check_period
      use_magicfile

    [OAuth2]
      client_id
      client_secret
      oauth2_refresh_retries
      provider_authorization_uri
      provider_label
      provider_token_uri
      token_cache


<B>UPDATING TO THE LATEST CONFIGURATION FILE</B>
  We add new configuration controllable features to the boto configuration file
  over time, but most gsutil users create a configuration file once and then
  keep it for a long time, so new features aren't apparent when you update
  to a newer version of gsutil. If you want to get the latest configuration
  file (which includes all the latest settings and documentation about each)
  you can rename your current file (e.g., to '.boto_old'), run gsutil config,
  and then edit any configuration settings you wanted from your old file
  into the newly created file. Note, however, that if you're using OAuth2
  credentials and you go back through the OAuth2 configuration dialog it will
  invalidate your previous OAuth2 credentials.

  If no explicit scope option is given, -f (full control) is assumed by default.


<B>OPTIONS</B>
  -a          Prompt for Google Cloud Storage access key and secret (the older
              authentication method before OAuth2 was supported) instead of
              obtaining an OAuth2 token.

  -b          Causes gsutil config to launch a browser to obtain OAuth2 approval
              and the project ID instead of showing the URL for each and asking
              the user to open the browser. This will probably not work as
              expected if you are running gsutil from an ssh window, or using
              gsutil on Windows.

  -e          Prompt for service account credentials. This option requires that
              -a is not set.

  -f          Request token with full-control access (default).

  -o <file>   Write the configuration to <file> instead of ~/.boto.
              Use '-' for stdout.

  -r          Request token restricted to read-only access.

  -s <scope>  Request additional OAuth2 <scope>.

  -w          Request token restricted to read-write access.
""")


try:
  from oauth2_plugin import oauth2_helper  # pylint: disable=g-import-not-at-top
except ImportError:
  pass

GOOG_CLOUD_CONSOLE_URI = 'https://cloud.google.com/console#/project'

SCOPE_FULL_CONTROL = 'https://www.googleapis.com/auth/devstorage.full_control'
SCOPE_READ_WRITE = 'https://www.googleapis.com/auth/devstorage.read_write'
SCOPE_READ_ONLY = 'https://www.googleapis.com/auth/devstorage.read_only'

CONFIG_PRELUDE_CONTENT = """
# This file contains credentials and other configuration information needed
# by the boto library, used by gsutil. You can edit this file (e.g., to add
# credentials) but be careful not to mis-edit any of the variable names (like
# "gs_access_key_id") or remove important markers (like the "[Credentials]" and
# "[Boto]" section delimiters).
#
"""

# Default number of OS processes and Python threads for parallel operations.
# On Linux systems we automatically scale the number of processes to match
# the underlying CPU/core count. Given we'll be running multiple concurrent
# processes on a typical multi-core Linux computer, to avoid being too
# aggressive with resources, the default number of threads is reduced from
# the previous value of 24 to 10.
# On Windows and Mac systems parallel multi-processing and multi-threading
# in Python presents various challenges so we retain compatibility with
# the established parallel mode operation, i.e. one process and 24 threads.
if platform.system() == 'Linux':
  DEFAULT_PARALLEL_PROCESS_COUNT = multiprocessing.cpu_count()
  DEFAULT_PARALLEL_THREAD_COUNT = 10
else:
  DEFAULT_PARALLEL_PROCESS_COUNT = 1
  DEFAULT_PARALLEL_THREAD_COUNT = 24

DEFAULT_PARALLEL_COMPOSITE_UPLOAD_THRESHOLD = '150M'
DEFAULT_PARALLEL_COMPOSITE_UPLOAD_COMPONENT_SIZE = '50M'

CONFIG_BOTO_SECTION_CONTENT = """
[Boto]

# http_socket_timeout specifies the timeout (in seconds) used to tell httplib
# how long to wait for socket timeouts. The default is 70 seconds. Note that
# this timeout only applies to httplib, not to httplib2 (which is used for
# OAuth2 refresh/access token exchanges).
#http_socket_timeout = 70

# The following two options control the use of a secure transport for requests
# to S3 and Google Cloud Storage. It is highly recommended to set both options
# to True in production environments, especially when using OAuth2 bearer token
# authentication with Google Cloud Storage.

# Set 'https_validate_certificates' to False to disable server certificate
# checking. The default for this option in the boto library is currently
# 'False' (to avoid breaking apps that depend on invalid certificates); it is
# therefore strongly recommended to always set this option explicitly to True
# in configuration files, to protect against "man-in-the-middle" attacks.
https_validate_certificates = True

# 'debug' controls the level of debug messages printed: 0 for none, 1
# for basic boto debug, 2 for all boto debug plus HTTP requests/responses.
# Note: 'gsutil -d' sets debug to 2 for that one command run.
#debug = <0, 1, or 2>

# 'num_retries' controls the number of retry attempts made when errors occur
# during data transfers. The default is 6. Note: don't set this value to 0, as
# it will cause boto to fail when reusing HTTP connections.
#num_retries = <integer value>
"""

CONFIG_INPUTLESS_GSUTIL_SECTION_CONTENT = """
[GSUtil]

# 'resumable_threshold' specifies the smallest file size [bytes] for which
# resumable Google Cloud Storage transfers are attempted. The default is 2097152
# (2 MiB).
#resumable_threshold = %(resumable_threshold)d

# 'rsync_buffer_lines' specifies the number of lines of bucket or directory
# listings saved in each temp file during sorting. (The complete set is
# split across temp files and separately sorted/merged, to avoid needing to
# fit everything in memory at once.) If you are trying to synchronize very
# large directories/buckets (e.g., containing millions or more objects),
# having too small a value here can cause gsutil to run out of open file
# handles. If that happens, you can try to increase the number of open file
# handles your system allows (e.g., see 'man ulimit' on Linux; see also
# http://docs.python.org/2/library/resource.html). If you can't do that (or
# if you're already at the upper limit), increasing rsync_buffer_lines will
# cause gsutil to use fewer file handles, but at the cost of more memory. With
# rsync_buffer_lines set to 32000 and assuming a typical URL is 100 bytes
# long, gsutil will require approximately 10MB of memory while building
# the synchronization state, and will require approximately 60 open file
# descriptors to build the synchronization state over all 1M source and 1M
# destination URLs. Memory and file descriptors are only consumed while
# building the state; once the state is built, it resides in two temp files that
# are read and processed incrementally during the actual copy/delete
# operations.
#rsync_buffer_lines = 32000

# 'resumable_tracker_dir' specifies the base location where resumable
# transfer tracker files are saved. By default they're in ~/.gsutil
#resumable_tracker_dir = <file path>
# gsutil also saves a file called .last_software_update_check in this directory,
# that tracks the last time a check was made whether a new version of the gsutil
# software is available. 'software_update_check_period' specifies the number of
# days between such checks. The default is 30. Setting the value to 0 disables
# periodic software update checks.
#software_update_check_period = 30

# 'parallel_process_count' and 'parallel_thread_count' specify the number
# of OS processes and Python threads, respectively, to use when executing
# operations in parallel. The default settings should work well as configured,
# however, to enhance performance for transfers involving large numbers of
# files, you may experiment with hand tuning these values to optimize
# performance for your particular system configuration.
# MacOS and Windows users should see
# https://github.com/GoogleCloudPlatform/gsutil/issues/77 before attempting
# to experiment with these values.
#parallel_process_count = %(parallel_process_count)d
#parallel_thread_count = %(parallel_thread_count)d

# 'parallel_composite_upload_threshold' specifies the maximum size of a file to
# upload in a single stream. Files larger than this threshold will be
# partitioned into component parts and uploaded in parallel and then composed
# into a single object.
# The number of components will be the smaller of
# ceil(file_size / parallel_composite_upload_component_size) and
# MAX_COMPONENT_COUNT. The current value of MAX_COMPONENT_COUNT is
# %(max_component_count)d.
# If 'parallel_composite_upload_threshold' is set to 0, then automatic parallel
# uploads will never occur.
# Setting an extremely low threshold is unadvisable. The vast majority of
# environments will see degraded performance for thresholds below 80M, and it
# is almost never advantageous to have a threshold below 20M.
# 'parallel_composite_upload_component_size' specifies the ideal size of a
# component in bytes, which will act as an upper bound to the size of the
# components if ceil(file_size / parallel_composite_upload_component_size) is
# less than MAX_COMPONENT_COUNT.
# Values can be provided either in bytes or as human-readable values
# (e.g., "150M" to represent 150 megabytes)
#parallel_composite_upload_threshold = %(parallel_composite_upload_threshold)s
#parallel_composite_upload_component_size = %(parallel_composite_upload_component_size)s

# 'use_magicfile' specifies if the 'file --mime-type <filename>' command should
# be used to guess content types instead of the default filename extension-based
# mechanism. Available on UNIX and MacOS (and possibly on Windows, if you're
# running Cygwin or some other package that provides implementations of
# UNIX-like commands). When available and enabled use_magicfile should be more
# robust because it analyzes file contents in addition to extensions.
#use_magicfile = False

# 'content_language' specifies the ISO 639-1 language code of the content, to be
# passed in the Content-Language header. By default no Content-Language is sent.
# See the ISO 639-1 column of
# http://www.loc.gov/standards/iso639-2/php/code_list.php for a list of
# language codes.
content_language = en

# 'check_hashes' specifies how strictly to require integrity checking for
# downloaded data. Legal values are:
#   'if_fast_else_fail' - (default) Only integrity check if the digest will run
#       efficiently (using compiled code), else fail the download.
#   'if_fast_else_skip' - Only integrity check if the server supplies a hash and
#       the local digest computation will run quickly, else skip the check.
#   'always' - Always check download integrity regardless of possible
#       performance costs.
#   'never' - Don't perform download integrity checks. This settings is not
#       recommended except for special cases such as measuring download
#       performance excluding time for integrity checking.
# This option exists to assist users who wish to download a GCS composite object
# and are unable to install crcmod with the C-extension. CRC32c is the only
# available integrity check for composite objects, and without the C-extension,
# download performance can be significantly degraded by the digest computation.
#check_hashes = if_fast_else_fail

# The ability to specify an alternative JSON API version is primarily for cloud
# storage service developers.
#json_api_version = v1beta2

# Specifies the API to use when interacting with cloud storage providers.  If
# the gsutil command supports this API for the provider, it will be used
# instead of the default.
# Commands typically default to XML for S3 and JSON for GCS.
#prefer_api = json
#prefer_api = xml

""" % {'resumable_threshold': TWO_MB,
       'parallel_process_count': DEFAULT_PARALLEL_PROCESS_COUNT,
       'parallel_thread_count': DEFAULT_PARALLEL_THREAD_COUNT,
       'parallel_composite_upload_threshold': (
           DEFAULT_PARALLEL_COMPOSITE_UPLOAD_THRESHOLD),
       'parallel_composite_upload_component_size': (
           DEFAULT_PARALLEL_COMPOSITE_UPLOAD_COMPONENT_SIZE),
       'max_component_count': MAX_COMPONENT_COUNT}

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

# 'oauth2_refresh_retries' controls the number of retry attempts made when
# rate limiting errors occur for OAuth2 requests to retrieve an access token.
# The default value is 6.
#oauth2_refresh_retries = <integer value>
"""


class ConfigCommand(Command):
  """Implementation of gsutil config command."""

  # Command specification. See base class for documentation.
  command_spec = Command.CreateCommandSpec(
      'config',
      command_name_aliases=['cfg', 'conf', 'configure'],
      min_args=0,
      max_args=0,
      supported_sub_args='habefwrs:o:',
      file_url_ok=False,
      provider_url_ok=False,
      urls_start_arg=0,
  )
  # Help specification. See help_provider.py for documentation.
  help_spec = Command.HelpSpec(
      help_name='config',
      help_name_aliases=['cfg', 'conf', 'configure', 'proxy', 'aws', 's3'],
      help_type='command_help',
      help_one_line_summary=(
          'Obtain credentials and create configuration file'),
      help_text=_detailed_help_text,
      subcommand_help_text={},
  )

  def _OpenConfigFile(self, file_path):
    """Creates and opens a configuration file for writing.

    The file is created with mode 0600, and attempts to open existing files will
    fail (the latter is important to prevent symlink attacks).

    It is the caller's responsibility to close the file.

    Args:
      file_path: Path of the file to be created.

    Returns:
      A writable file object for the opened file.

    Raises:
      CommandException: if an error occurred when opening the file (including
          when the file already exists).
    """
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    # Accommodate Windows; copied from python2.6/tempfile.py.
    if hasattr(os, 'O_NOINHERIT'):
      flags |= os.O_NOINHERIT
    try:
      fd = os.open(file_path, flags, 0600)
    except (OSError, IOError), e:
      raise CommandException('Failed to open %s for writing: %s' %
                             (file_path, e))
    return os.fdopen(fd, 'w')

  def _CheckPrivateKeyFilePermissions(self, file_path):
    """Checks that the file has reasonable permissions for a private key.

    In particular, check that the filename provided by the user is not
    world- or group-readable. If either of these are true, we issue a warning
    and offer to fix the permissions.

    Args:
      file_path: The name of the private key file.
    """
    if IS_WINDOWS:
      # For Windows, this check doesn't work (it actually just checks whether
      # the file is read-only). Since Windows files have a complicated ACL
      # system, this check doesn't make much sense on Windows anyway, so we
      # just don't do it.
      return

    st = os.stat(file_path)
    if bool((stat.S_IRGRP | stat.S_IROTH) & st.st_mode):
      self.logger.warn(
          '\nYour private key file is readable by people other than yourself.\n'
          'This is a security risk, since anyone with this information can use '
          'your service account.\n')
      fix_it = raw_input('Would you like gsutil to change the file '
                         'permissions for you? (y/N) ')
      if fix_it in ('y', 'Y'):
        try:
          os.chmod(file_path, 0400)
          self.logger.info(
              '\nThe permissions on your file have been successfully '
              'modified.'
              '\nThe only access allowed is readability by the user '
              '(permissions 0400 in chmod).')
        except Exception, _:  # pylint: disable=broad-except
          self.logger.warn(
              '\nWe were unable to modify the permissions on your file.\n'
              'If you would like to fix this yourself, consider running:\n'
              '"sudo chmod 400 </path/to/key>" for improved security.')
      else:
        self.logger.info(
            '\nYou have chosen to allow this file to be readable by others.\n'
            'If you would like to fix this yourself, consider running:\n'
            '"sudo chmod 400 </path/to/key>" for improved security.')

  def _PromptForProxyConfigVarAndMaybeSaveToBotoConfig(self, varname, prompt):
    """Prompts for one proxy config line, saves to boto.config if not empty.

    Args:
      varname: The config variable name.
      prompt: The prompt to output to the user.
    """
    value = raw_input(prompt)
    if value:
      boto.config.set('Boto', varname, value)

  def _PromptForProxyConfig(self):
    """Prompts for proxy config data, loads non-empty values into boto.config.
    """
    self._PromptForProxyConfigVarAndMaybeSaveToBotoConfig(
        'proxy', 'What is your proxy host? ')
    self._PromptForProxyConfigVarAndMaybeSaveToBotoConfig(
        'proxy_port', 'What is your proxy port? ')
    self._PromptForProxyConfigVarAndMaybeSaveToBotoConfig(
        'proxy_user', 'What is your proxy user (leave blank if not used)? ')
    self._PromptForProxyConfigVarAndMaybeSaveToBotoConfig(
        'proxy_pass', 'What is your proxy pass (leave blank if not used)? ')

  def _WriteConfigLineMaybeCommented(self, config_file, name, value, desc):
    """Writes proxy name/value pair or comment line to config file.

    Writes proxy name/value pair if value is not None.  Otherwise writes
    comment line.

    Args:
      config_file: File object to which the resulting config file will be
          written.
      name: The config variable name.
      value: The value, or None.
      desc: Human readable description (for comment).
    """
    if not value:
      name = '#%s' % name
      value = '<%s>' % desc
    config_file.write('%s = %s\n' % (name, value))

  def _WriteProxyConfigFileSection(self, config_file):
    """Writes proxy section of configuration file.

    Args:
      config_file: File object to which the resulting config file will be
          written.
    """
    config = boto.config
    config_file.write(
        '# To use a proxy, edit and uncomment the proxy and proxy_port lines.\n'
        '# If you need a user/password with this proxy, edit and uncomment\n'
        '# those lines as well.\n')
    self._WriteConfigLineMaybeCommented(
        config_file, 'proxy', config.get_value('Boto', 'proxy', None),
        'proxy host')
    self._WriteConfigLineMaybeCommented(
        config_file, 'proxy_port', config.get_value('Boto', 'proxy_port', None),
        'proxy port')
    self._WriteConfigLineMaybeCommented(
        config_file, 'proxy_user', config.get_value('Boto', 'proxy_user', None),
        'proxy user')
    self._WriteConfigLineMaybeCommented(
        config_file, 'proxy_pass', config.get_value('Boto', 'proxy_pass', None),
        'proxy password')

  # pylint: disable=dangerous-default-value,too-many-statements
  def _WriteBotoConfigFile(self, config_file, launch_browser=True,
                           oauth2_scopes=[SCOPE_FULL_CONTROL],
                           cred_type=CredTypes.OAUTH2_USER_ACCOUNT):
    """Creates a boto config file interactively.

    Needed credentials are obtained interactively, either by asking the user for
    access key and secret, or by walking the user through the OAuth2 approval
    flow.

    Args:
      config_file: File object to which the resulting config file will be
          written.
      launch_browser: In the OAuth2 approval flow, attempt to open a browser
          window and navigate to the approval URL.
      oauth2_scopes: A list of OAuth2 scopes to request authorization for, when
          using OAuth2.
      cred_type: There are three options:
        - for HMAC, ask the user for access key and secret
        - for OAUTH2_USER_ACCOUNT, walk the user through OAuth2 approval flow
          and produce a config with an oauth2_refresh_token credential.
        - for OAUTH2_SERVICE_ACCOUNT, prompt the user for OAuth2 for service
          account email address and private key file (and password for that
          file).
    """
    # Collect credentials
    provider_map = {'aws': 'aws', 'google': 'gs'}
    uri_map = {'aws': 's3', 'google': 'gs'}
    key_ids = {}
    sec_keys = {}
    if cred_type == CredTypes.OAUTH2_SERVICE_ACCOUNT:
      gs_service_client_id = raw_input('What is your service account email '
                                       'address? ')
      gs_service_key_file = raw_input('What is the full path to your private '
                                      'key file? ')
      gs_service_key_file_password = raw_input(
          '\n'.join(textwrap.wrap(
              'What is the password for your service key file [if you haven\'t '
              'set one explicitly, leave this line blank]?')) + ' ')
      self._CheckPrivateKeyFilePermissions(gs_service_key_file)
    elif cred_type == CredTypes.OAUTH2_USER_ACCOUNT:
      oauth2_client = oauth2_helper.OAuth2ClientFromBotoConfig(boto.config,
                                                               cred_type)
      try:
        oauth2_refresh_token = oauth2_helper.OAuth2ApprovalFlow(
            oauth2_client, oauth2_scopes, launch_browser)
      except (ResponseNotReady, ServerNotFoundError):
        # TODO: Determine condition to check for in the ResponseNotReady
        # exception so we only run proxy config flow if failure was caused by
        # request being blocked because it wasn't sent through proxy. (This
        # error could also happen if gsutil or the oauth2 client had a bug that
        # attempted to incorrectly reuse an HTTP connection, for example.)
        sys.stdout.write('\n'.join(textwrap.wrap(
            "Unable to connect to accounts.google.com during OAuth2 flow. This "
            "can happen if your site uses a proxy. If you are using gsutil "
            "through a proxy, please enter the proxy's information; otherwise "
            "leave the following fields blank.")) + '\n')
        self._PromptForProxyConfig()
        oauth2_client = oauth2_helper.OAuth2ClientFromBotoConfig(boto.config,
                                                                 cred_type)
        oauth2_refresh_token = oauth2_helper.OAuth2ApprovalFlow(
            oauth2_client, oauth2_scopes, launch_browser)
    elif cred_type == CredTypes.HMAC:
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
    config_file.write(CONFIG_PRELUDE_CONTENT.lstrip())
    config_file.write(
        '# This file was created by gsutil version %s at %s.\n'
        % (gslib.VERSION,
           datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    config_file.write(
        '#\n# You can create additional configuration files by '
        'running\n# gsutil config [options] [-o <config-file>]\n\n\n')

    # Write the config file Credentials section.
    config_file.write('[Credentials]\n\n')
    if cred_type == CredTypes.OAUTH2_SERVICE_ACCOUNT:
      config_file.write('# Google OAuth2 service account credentials '
                        '(for "gs://" URIs):\n')
      config_file.write('gs_service_client_id = %s\n'
                        % gs_service_client_id)
      config_file.write('gs_service_key_file = %s\n' % gs_service_key_file)

      if not gs_service_key_file_password:
        config_file.write(
            '# If you would like to set your password, you can do so using\n'
            '# the following commands (replaced with your information):\n'
            '# "openssl pkcs12 -in cert1.p12 -out temp_cert.pem"\n'
            '# "openssl pkcs12 -export -in temp_cert.pem -out cert2.p12"\n'
            '# "rm -f temp_cert.pem"\n'
            '# Your initial password is "notasecret" - for more information,'
            '\n# please see http://www.openssl.org/docs/apps/pkcs12.html.\n')
        config_file.write('#gs_service_key_file_password =\n\n')
      else:
        config_file.write('gs_service_key_file_password = %s\n\n'
                          % gs_service_key_file_password)
    elif cred_type == CredTypes.OAUTH2_USER_ACCOUNT:
      config_file.write(
          '# Google OAuth2 credentials (for "gs://" URIs):\n'
          '# The following OAuth2 account is authorized for scope(s):\n')
      for scope in oauth2_scopes:
        config_file.write('#     %s\n' % scope)
      config_file.write(
          'gs_oauth2_refresh_token = %s\n\n' % oauth2_refresh_token)
    else:
      config_file.write(
          '# To add Google OAuth2 credentials ("gs://" URIs), '
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
        config_file.write(
            '# To add %s credentials ("%s://" URIs), edit and '
            'uncomment the\n# following two lines:\n'
            '#%s_access_key_id = <your %s access key ID>\n'
            '#%s_secret_access_key = <your %s secret access key>\n' %
            (provider, uri_scheme, key_prefix, provider, key_prefix,
             provider))
      host_key = Provider.HostKeyMap[provider]
      config_file.write(
          '# The ability to specify an alternate storage host and port\n'
          '# is primarily for cloud storage service developers.\n'
          '#%s_host = <alternate storage host address>\n'
          '#%s_port = <alternate storage host port>\n\n'
          % (host_key, host_key))

    # Write the config file Boto section.
    config_file.write('%s\n' % CONFIG_BOTO_SECTION_CONTENT)
    self._WriteProxyConfigFileSection(config_file)

    # Write the config file GSUtil section that doesn't depend on user input.
    config_file.write(CONFIG_INPUTLESS_GSUTIL_SECTION_CONTENT)

    # Write the default API version.
    config_file.write("""
# 'default_api_version' specifies the default Google Cloud Storage XML API
# version to use. If not set below gsutil defaults to API version 1.
""")
    api_version = 2
    if cred_type == CredTypes.HMAC: api_version = 1

    config_file.write('default_api_version = %d\n' % api_version)

    # Write the config file GSUtil section that includes the default
    # project ID input from the user.
    if launch_browser:
      sys.stdout.write(
          'Attempting to launch a browser to open the Google Cloud Console at '
          'URL: %s\n\n'
          '[Note: due to a Python bug, you may see a spurious error message '
          '"object is not\ncallable [...] in [...] Popen.__del__" which can '
          'be ignored.]\n\n' % GOOG_CLOUD_CONSOLE_URI)
      sys.stdout.write(
          'In your browser you should see the Cloud Console. Find the project '
          'you will\nuse, and then copy the Project ID string from the second '
          'column. Older projects do\nnot have Project ID strings. For such '
          'projects, click the project and then copy the\nProject Number '
          'listed under that project.\n\n')
      if not webbrowser.open(GOOG_CLOUD_CONSOLE_URI, new=1, autoraise=True):
        sys.stdout.write(
            'Launching browser appears to have failed; please navigate a '
            'browser to the following URL:\n%s\n' % GOOG_CLOUD_CONSOLE_URI)
      # Short delay; webbrowser.open on linux insists on printing out a message
      # which we don't want to run into the prompt for the auth code.
      time.sleep(2)
    else:
      sys.stdout.write(
          '\nPlease navigate your browser to %s,\nthen find the project you '
          'will use, and copy the Project ID string from the\nsecond column. '
          'Older projects do not have Project ID strings. For such projects,\n'
          'click the project and then copy the Project Number listed under '
          'that project.\n\n' % GOOG_CLOUD_CONSOLE_URI)
    default_project_id = raw_input('What is your project-id? ').strip()
    project_id_section_prelude = """
# 'default_project_id' specifies the default Google Cloud Storage project ID to
# use with the 'mb' and 'ls' commands. This default can be overridden by
# specifying the -p option to the 'mb' and 'ls' commands.
"""
    if not default_project_id:
      raise CommandException(
          'No default project ID entered. The default project ID is needed by '
          'the\nls and mb commands; please try again.')
    config_file.write('%sdefault_project_id = %s\n\n\n' %
                      (project_id_section_prelude, default_project_id))

    # Write the config file OAuth2 section.
    config_file.write(CONFIG_OAUTH2_CONFIG_CONTENT)

  def RunCommand(self):
    """Command entry point for the config command."""
    scopes = []
    cred_type = CredTypes.OAUTH2_USER_ACCOUNT
    launch_browser = False
    output_file_name = None
    has_a = False
    has_e = False
    for opt, opt_arg in self.sub_opts:
      if opt == '-a':
        cred_type = CredTypes.HMAC
        has_a = True
      elif opt == '-b':
        launch_browser = True
      elif opt == '-e':
        cred_type = CredTypes.OAUTH2_SERVICE_ACCOUNT
        has_e = True
      elif opt == '-f':
        scopes.append(SCOPE_FULL_CONTROL)
      elif opt == '-o':
        output_file_name = opt_arg
      elif opt == '-r':
        scopes.append(SCOPE_READ_ONLY)
      elif opt == '-s':
        scopes.append(opt_arg)
      elif opt == '-w':
        scopes.append(SCOPE_READ_WRITE)

    if has_e:
      if has_a:
        raise CommandException('Both -a and -e cannot be specified. Please see '
                               '"gsutil help config" for more information.')
      if not HAS_CRYPTO:
        raise CommandException(
            'Service account authentication requires either\nPyOpenSSL or '
            'PyCrypto 2.6 or later. Please install either of these\nto proceed,'
            ' or configure a different type of credentials.')

    if not scopes:
      scopes.append(SCOPE_FULL_CONTROL)

    default_config_path_bak = None
    if not output_file_name:
      # Check to see if a default config file name is requested via
      # environment variable. If so, use it, otherwise use the hard-coded
      # default file. Then use the default config file name, if it doesn't
      # exist or can be moved out of the way without clobbering an existing
      # backup file.
      boto_config_from_env = os.environ.get('BOTO_CONFIG', None)
      if boto_config_from_env:
        default_config_path = boto_config_from_env
      else:
        default_config_path = os.path.expanduser(os.path.join('~', '.boto'))
      if not os.path.exists(default_config_path):
        output_file_name = default_config_path
      else:
        default_config_path_bak = default_config_path + '.bak'
        if os.path.exists(default_config_path_bak):
          raise CommandException(
              'Cannot back up existing config '
              'file "%s": backup file exists ("%s").'
              % (default_config_path, default_config_path_bak))
        else:
          try:
            sys.stderr.write(
                'Backing up existing config file "%s" to "%s"...\n'
                % (default_config_path, default_config_path_bak))
            os.rename(default_config_path, default_config_path_bak)
          except Exception, e:
            raise CommandException(
                'Failed to back up existing config '
                'file ("%s" -> "%s"): %s.'
                % (default_config_path, default_config_path_bak, e))
          output_file_name = default_config_path

    if output_file_name == '-':
      output_file = sys.stdout
    else:
      output_file = self._OpenConfigFile(output_file_name)
      sys.stderr.write('\n'.join(textwrap.wrap(
          'This command will create a boto config file at %s containing your '
          'credentials, based on your responses to the following questions.'
          % output_file_name)) + '\n')

    # Catch ^C so we can restore the backup.
    signal.signal(signal.SIGINT, CleanupHandler)
    try:
      self._WriteBotoConfigFile(output_file, launch_browser=launch_browser,
                                oauth2_scopes=scopes, cred_type=cred_type)
    except Exception as e:
      user_aborted = isinstance(e, AbortException)
      if user_aborted:
        sys.stderr.write('\nCaught ^C; cleaning up\n')
      # If an error occurred during config file creation, remove the invalid
      # config file and restore the backup file.
      if output_file_name != '-':
        output_file.close()
        os.unlink(output_file_name)
        try:
          if default_config_path_bak:
            sys.stderr.write('Restoring previous backed up file (%s)\n' %
                             default_config_path_bak)
            os.rename(default_config_path_bak, output_file_name)
        except Exception as e:
          # Raise the original exception so that we can see what actually went
          # wrong, rather than just finding out that we died before assigning
          # a value to default_config_path_bak.
          raise e
      raise

    if output_file_name != '-':
      output_file.close()
      if not boto.config.has_option('Boto', 'proxy'):
        sys.stderr.write('\n' + '\n'.join(textwrap.wrap(
            'Boto config file "%s" created.\nIf you need to use a proxy to '
            'access the Internet please see the instructions in that file.'
            % output_file_name)) + '\n')

    return 0


def CleanupHandler(unused_signalnum, unused_handler):
  raise AbortException('User interrupted config command')
