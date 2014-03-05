# coding=utf8
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

"""Class that runs a named gsutil command."""

import difflib
import logging
import os
import pkgutil
import sys
import textwrap
import time

import boto
from boto.storage_uri import BucketStorageUri
import gslib
from gslib.command import Command
from gslib.command import OLD_ALIAS_MAP
from gslib.command import ShutDownGsutil
import gslib.commands
from gslib.cs_api_map import GsutilApiClassMapFactory
from gslib.exception import CommandException
from gslib.gcs_json_api import GcsJsonApi
from gslib.util import CompareVersions
from gslib.util import ConfigureNoOpAuthIfNeeded
from gslib.util import GetGsutilVersionModifiedTime
from gslib.util import GSUTIL_PUB_TARBALL
from gslib.util import IsRunningInteractively
from gslib.util import LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE
from gslib.util import LookUpGsutilVersion
from gslib.util import MultiprocessingIsAvailable
from gslib.util import RELEASE_NOTES_URL
from gslib.util import SECONDS_PER_DAY
from gslib.util import UTF8


def HandleArgCoding(args):
  """Handles coding of command-line args.

  Args:
    args: array of command-line args.

  Returns:
    array of command-line args.

  Raises:
    CommandException: if errors encountered.
  """
  # Python passes arguments from the command line as byte strings. To
  # correctly interpret them, we decode ones other than -h and -p args (which
  # will be passed as headers, and thus per HTTP spec should not be encoded) as
  # utf-8. The exception is x-goog-meta-* headers, which are allowed to contain
  # non-ASCII content (and hence, should be decoded), per
  # https://developers.google.com/storage/docs/gsutil/addlhelp/WorkingWithObjectMetadata
  processing_header = False
  for i in range(len(args)):
    arg = args[i]
    decoded = arg.decode(UTF8)
    if processing_header:
      if arg.lower().startswith('x-goog-meta'):
        args[i] = decoded
      else:
        try:
          # Try to encode as ASCII to check for invalid header values (which
          # can't be sent over HTTP).
          decoded.encode('ascii')
        except UnicodeEncodeError:
          # Raise the CommandException using the decoded value because
          # _OutputAndExit function re-encodes at the end.
          raise CommandException(
              'Invalid non-ASCII header value (%s).\nOnly ASCII characters are '
              'allowed in headers other than x-goog-meta- headers' % decoded)
    else:
      args[i] = decoded
    processing_header = (arg in ('-h', '-p'))
  return args


class CommandRunner(object):
  """Runs gsutil commands and does some top-level argument handling."""

  def __init__(self, config_file_list,
               bucket_storage_uri_class=BucketStorageUri,
               gsutil_api_class_map_factory=GsutilApiClassMapFactory):
    """Instantiates a CommandRunner.

    Args:
      config_file_list: Config file list returned by GetBotoConfigFileList().
      bucket_storage_uri_class: Class to instantiate for cloud StorageUris.
                                Settable for testing/mocking.
      gsutil_api_class_map_factory: Creates map of cloud storage interfaces.
                                    Settable for testing/mocking.
    """
    self.config_file_list = config_file_list
    self.bucket_storage_uri_class = bucket_storage_uri_class
    self.gsutil_api_class_map_factory = gsutil_api_class_map_factory
    self.command_map = self._LoadCommandMap()

  def _LoadCommandMap(self):
    """Returns dict mapping each command_name to implementing class."""
    # Import all gslib.commands submodules.
    for _, module_name, _ in pkgutil.iter_modules(gslib.commands.__path__):
      __import__('gslib.commands.%s' % module_name)

    command_map = {}
    # Only include Command subclasses in the dict.
    for command in Command.__subclasses__():
      command_map[command.command_spec.command_name] = command
      for command_name_aliases in command.command_spec.command_name_aliases:
        command_map[command_name_aliases] = command
    return command_map

  def RunNamedCommand(self, command_name, args=None, headers=None, debug=0,
                      parallel_operations=False, test_method=None,
                      skip_update_check=False, logging_filters=None,
                      do_shutdown=True):
    """Runs the named command.

    Used by gsutil main, commands built atop other commands, and tests.

    Args:
      command_name: The name of the command being run.
      args: Command-line args (arg0 = actual arg, not command name ala bash).
      headers: Dictionary containing optional HTTP headers to pass to boto.
      debug: Debug level to pass in to boto connection (range 0..3).
      parallel_operations: Should command operations be executed in parallel?
      test_method: Optional general purpose method for testing purposes.
                   Application and semantics of this method will vary by
                   command and test type.
      skip_update_check: Set to True to disable checking for gsutil updates.
      logging_filters: Optional list of logging.Filters to apply to this
                       command's logger.
      do_shutdown: Stop all parallelism framework workers iff this is True.

    Raises:
      CommandException: if errors encountered.

    Returns:
      Return value(s) from Command that was run.
    """
    ConfigureNoOpAuthIfNeeded()
    if (not skip_update_check and
        self.MaybeCheckForAndOfferSoftwareUpdate(command_name, debug)):
      command_name = 'update'
      args = ['-n']

    if not args:
      args = []

    # Include api_version header in all commands.
    api_version = boto.config.get_value('GSUtil', 'default_api_version', '1')
    if not headers:
      headers = {}
    headers['x-goog-api-version'] = api_version

    if command_name not in self.command_map:
      close_matches = difflib.get_close_matches(
          command_name, self.command_map.keys(), n=1)
      if close_matches:
        # Instead of suggesting a deprecated command alias, suggest the new
        # name for that command.
        translated_command_name = (
            OLD_ALIAS_MAP.get(close_matches[0], close_matches)[0])
        print >> sys.stderr, 'Did you mean this?'
        print >> sys.stderr, '\t%s' % translated_command_name
      raise CommandException('Invalid command "%s".' % command_name)
    if '--help' in args:
      new_args = [command_name]
      original_command_class = self.command_map[command_name]
      subcommands = original_command_class.help_spec.subcommand_help_text.keys()
      for arg in args:
        if arg in subcommands:
          new_args.append(arg)
          break  # Take the first match and throw away the rest.
      args = new_args
      command_name = 'help'

    args = HandleArgCoding(args)

    command_class = self.command_map[command_name]
    command_inst = command_class(
        self, args, headers, debug, parallel_operations, self.config_file_list,
        self.bucket_storage_uri_class, self.gsutil_api_class_map_factory,
        test_method, logging_filters, command_alias_used=command_name)
    return_values = command_inst.RunCommand()

    if MultiprocessingIsAvailable()[0] and do_shutdown:
      ShutDownGsutil()
    return return_values

  def MaybeCheckForAndOfferSoftwareUpdate(self, command_name, debug):
    """Checks the last time we checked for an update and offers one if needed.

    Offer is made if the time since the last update check is longer
    than the configured threshold offers the user to update gsutil.

    Args:
      command_name: The name of the command being run.
      debug: Debug level to pass in to boto connection (range 0..3).

    Returns:
      True if the user decides to update.
    """
    # Don't try to interact with user if:
    # - gsutil is not connected to a tty (e.g., if being run from cron);
    # - user is running gsutil -q
    # - user is running the config command (which could otherwise attempt to
    #   check for an update for a user running behind a proxy, who has not yet
    #   configured gsutil to go through the proxy; for such users we need the
    #   first connection attempt to be made by the gsutil config command).
    # - user is running the version command (which gets run when using
    #   gsutil -D, which would prevent users with proxy config problems from
    #   sending us gsutil -D output).
    # - user is running the update command (which could otherwise cause an
    #   additional note that an update is available when user is already trying
    #   to perform an update);
    # - user specified gs_host (which could be a non-production different
    #   service instance, in which case credentials won't work for checking
    #   gsutil tarball).
    logger = logging.getLogger()
    gs_host = boto.config.get('Credentials', 'gs_host', None)
    if (not IsRunningInteractively()
        or command_name in ('config', 'update', 'ver', 'version')
        or not logger.isEnabledFor(logging.INFO)
        or gs_host):
      return False

    software_update_check_period = boto.config.getint(
        'GSUtil', 'software_update_check_period', 30)
    # Setting software_update_check_period to 0 means periodic software
    # update checking is disabled.
    if software_update_check_period == 0:
      return False

    cur_ts = int(time.time())
    if not os.path.isfile(LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE):
      # Set last_checked_ts from date of VERSION file, so if the user installed
      # an old copy of gsutil it will get noticed (and an update offered) the
      # first time they try to run it.
      last_checked_ts = GetGsutilVersionModifiedTime()
      with open(LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE, 'w') as f:
        f.write(str(last_checked_ts))
    else:
      try:
        with open(LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE, 'r') as f:
          last_checked_ts = int(f.readline())
      except (TypeError, ValueError):
        return False

    if (cur_ts - last_checked_ts
        > software_update_check_period * SECONDS_PER_DAY):
      # Create a credential-less gsutil API to check for the public
      # update tarball.
      gsutil_api = GcsJsonApi(self.bucket_storage_uri_class, logger,
                              credentials=None, debug=debug)

      cur_ver = LookUpGsutilVersion(gsutil_api, GSUTIL_PUB_TARBALL)
      with open(LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE, 'w') as f:
        f.write(str(cur_ts))
      (g, m) = CompareVersions(cur_ver, gslib.VERSION)
      if m:
        print '\n'.join(textwrap.wrap(
            'A newer version of gsutil (%s) is available than the version you '
            'are running (%s). NOTE: This is a major new version, so it is '
            'strongly recommended that you review the release note details at '
            '%s before updating to this version, especially if you use gsutil '
            'in scripts.' % (cur_ver, gslib.VERSION, RELEASE_NOTES_URL)))
        if gslib.IS_PACKAGE_INSTALL:
          return False
        print
        answer = raw_input('Would you like to update [y/N]? ')
        return answer and answer.lower()[0] == 'y'
      elif g:
        print '\n'.join(textwrap.wrap(
            'A newer version of gsutil (%s) is available than the version you '
            'are running (%s). A detailed log of gsutil release changes is '
            'available at %s if you would like to read them before updating.'
            % (cur_ver, gslib.VERSION, RELEASE_NOTES_URL)))
        if gslib.IS_PACKAGE_INSTALL:
          return False
        print
        answer = raw_input('Would you like to update [Y/n]? ')
        return not answer or answer.lower()[0] != 'n'
    return False
