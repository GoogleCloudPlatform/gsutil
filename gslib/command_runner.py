#!/usr/bin/env python
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

import boto
import os
import sys
import textwrap
import time

from boto.storage_uri import BucketStorageUri
from gslib.command import Command
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.exception import CommandException
from gslib.storage_uri_builder import StorageUriBuilder
from gslib.util import CreateTrackerDirIfNeeded
from gslib.util import GSUTIL_PUB_TARBALL
from gslib.util import LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE
from gslib.util import LookUpGsutilVersion
from gslib.util import SECONDS_PER_DAY


class CommandRunner(object):

  def __init__(self, gsutil_bin_dir, config_file_list,
               gsutil_ver, bucket_storage_uri_class=BucketStorageUri):
    """
    Args:
      gsutil_bin_dir: Bin dir from which gsutil is running.
      config_file_list: Config file list returned by _GetBotoConfigFileList().
      gsutil_ver: Version string of currently running gsutil command.
      bucket_storage_uri_class: Class to instantiate for cloud StorageUris.
                                Settable for testing/mocking.
    """
    self.gsutil_bin_dir = gsutil_bin_dir
    self.config_file_list = config_file_list
    self.gsutil_ver = gsutil_ver
    self.bucket_storage_uri_class = bucket_storage_uri_class
    self.command_map = self._LoadCommandMap()

  def _LoadCommandMap(self):
    """Returns dict mapping each command_name to implementing class."""
    # Walk gslib/commands and find all commands.
    commands_dir = os.path.join(self.gsutil_bin_dir, 'gslib', 'commands')
    for f in os.listdir(commands_dir):
      # Handles no-extension files, etc.
      (module_name, ext) = os.path.splitext(f)
      if ext == '.py':
        __import__('gslib.commands.%s' % module_name)
    command_map = {}
    # Only include Command subclasses in the dict.
    for command in Command.__subclasses__():
      command_map[command.command_spec[COMMAND_NAME]] = command
      for command_name_aliases in command.command_spec[COMMAND_NAME_ALIASES]:
        command_map[command_name_aliases] = command
    return command_map

  def RunNamedCommand(self, command_name, args=None, headers=None, debug=0,
                      parallel_operations=False, test_method=None):
    """Runs the named command. Used by gsutil main, commands built atop
      other commands, and tests .

      Args:
        command_name: The name of the command being run.
        args: Command-line args (arg0 = actual arg, not command name ala bash).
        headers: Dictionary containing optional HTTP headers to pass to boto.
        debug: Debug level to pass in to boto connection (range 0..3).
        parallel_operations: Should command operations be executed in parallel?
        test_method: Optional general purpose method for testing purposes.
                     Application and semantics of this method will vary by
                     command and test type.

      Raises:
        CommandException: if errors encountered.
    """
    if self._MaybeCheckForAndOfferSoftwareUpdate(command_name, debug):
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
      raise CommandException('Invalid command "%s".' % command_name)
    if '--help' in args:
      args = [command_name]
      command_name = 'help'
    command_class = self.command_map[command_name]
    command_inst = command_class(
        self, args, headers, debug, parallel_operations, self.gsutil_bin_dir,
        self.config_file_list, self.gsutil_ver, self.bucket_storage_uri_class,
        test_method)
    return command_inst.RunCommand()


  def _MaybeCheckForAndOfferSoftwareUpdate(self, command_name, debug):
    """Checks the last time we checked for an update, and if it's been longer
       than the configured threshold offers the user to update gsutil.

      Args:
        command_name: The name of the command being run.
        debug: Debug level to pass in to boto connection (range 0..3).

      Returns:
        True if the user decides to update.
    """
    # Don't try to interact with user if gsutil is not connected to a tty (e.g.,
    # if being run from cron), or if they are running the update command (which
    # could otherwise cause an additional note that an update is available when
    # they are already trying to perform an update).
    if (not sys.stdout.isatty() or not sys.stderr.isatty()
        or not sys.stdin.isatty() or command_name == 'update'):
      return False

    software_update_check_period = boto.config.get(
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
      last_checked_ts = int(
          os.path.getmtime(os.path.join(self.gsutil_bin_dir, 'VERSION')))
      with open(LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE, 'w') as f:
        f.write(str(last_checked_ts))
    else:
      with open(LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE, 'r') as f:
        last_checked_ts = int(f.readline())

    if (cur_ts - last_checked_ts
        > software_update_check_period * SECONDS_PER_DAY):
      suri_builder = StorageUriBuilder(debug, self.bucket_storage_uri_class)
      cur_ver = LookUpGsutilVersion(suri_builder.StorageUri(GSUTIL_PUB_TARBALL))
      with open(LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE, 'w') as f:
        f.write(str(cur_ts))
      if self.gsutil_ver != cur_ver:
        answer = raw_input('\n'.join(textwrap.wrap(
            'A newer version of gsutil (%s) is available than the version you '
            'are running (%s). Would you like to update [Y/n]?' %
            (cur_ver, self.gsutil_ver), width=78)) + ' ')
        return answer.lower()[0] != 'n'
    return False
