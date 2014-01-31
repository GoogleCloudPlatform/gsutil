# Copyright 2012 Google Inc. All Rights Reserved.
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
"""Implementation of versioning configuration command for buckets."""

from gslib.command import Command
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.command import CommandSpecKey
from gslib.command import FILE_URLS_OK
from gslib.command import MAX_ARGS
from gslib.command import MIN_ARGS
from gslib.command import PROVIDER_URLS_OK
from gslib.command import SUPPORTED_SUB_ARGS
from gslib.command import URLS_START_ARG
from gslib.cs_api_map import ApiSelector
from gslib.exception import CommandException
from gslib.help_provider import CreateHelpText
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HELP_TYPE
from gslib.help_provider import HelpType
from gslib.help_provider import SUBCOMMAND_HELP_TEXT
from gslib.storage_url import StorageUrlFromString
from gslib.third_party.storage_apitools import storage_v1beta2_messages as apitools_messages
from gslib.util import NO_MAX


_SET_SYNOPSIS = """
  gsutil versioning set [on|off] bucket_url...
"""

_GET_SYNOPSIS = """
  gsutil versioning get bucket_url...
"""

_SYNOPSIS = _SET_SYNOPSIS + _GET_SYNOPSIS.lstrip('\n')

_SET_DESCRIPTION = """
<B>SET</B>
  The "set" sub-command requires an additional sub-command, either "on" or
  "off", which, respectively, will enable or disable versioning for the
  specified bucket(s).

"""

_GET_DESCRIPTION = """
<B>GET</B>
  The "get" sub-command gets the versioning configuration for a
  bucket and displays whether or not it is enabled.
"""

_DESCRIPTION = """
  The Versioning Configuration feature enables you to configure a Google Cloud
  Storage bucket to keep old versions of objects.

  The gsutil versioning command has two sub-commands:
""" + _SET_DESCRIPTION + _GET_DESCRIPTION

_detailed_help_text = CreateHelpText(_SYNOPSIS, _DESCRIPTION)

_get_help_text = CreateHelpText(_GET_SYNOPSIS, _GET_DESCRIPTION)
_set_help_text = CreateHelpText(_SET_SYNOPSIS, _SET_DESCRIPTION)


class VersioningCommand(Command):
  """Implementation of gsutil versioning command."""

  # Command specification (processed by parent class).
  command_spec = {
      # Name of command.
      COMMAND_NAME: 'versioning',
      # List of command name aliases.
      COMMAND_NAME_ALIASES: ['setversioning', 'getversioning'],
      # Min number of args required by this command.
      MIN_ARGS: 2,
      # Max number of args required by this command, or NO_MAX.
      MAX_ARGS: NO_MAX,
      # Getopt-style string specifying acceptable sub args.
      SUPPORTED_SUB_ARGS: '',
      # True if file URLs acceptable for this command.
      FILE_URLS_OK: False,
      # True if provider-only URLs acceptable for this command.
      PROVIDER_URLS_OK: False,
      # Index in args of first URL arg.
      URLS_START_ARG: 2,
      # List of supported APIs
      CommandSpecKey.GS_API_SUPPORT: [ApiSelector.XML, ApiSelector.JSON],
      # Default API to use for this command
      CommandSpecKey.GS_DEFAULT_API: ApiSelector.JSON,
  }
  help_spec = {
      # Name of command or auxiliary help info for which this help applies.
      HELP_NAME: 'versioning',
      # List of help name aliases.
      HELP_NAME_ALIASES: ['getversioning', 'setversioning'],
      # Type of help)
      HELP_TYPE: HelpType.COMMAND_HELP,
      # One line summary of this help.
      HELP_ONE_LINE_SUMMARY: 'Enable or suspend versioning for one or more '
                             'buckets',
      # The full help text.
      HELP_TEXT: _detailed_help_text,
      # Help text for sub-commands.
      SUBCOMMAND_HELP_TEXT: {'get': _get_help_text,
                             'set': _set_help_text},
  }

  def _CalculateUrlsStartArg(self):
    if not self.args:
      self._RaiseWrongNumberOfArgumentsException()
    if self.args[0].lower() == 'set':
      return 2
    else:
      return 1

  def _SetVersioning(self):
    """Gets versioning configuration for a bucket."""
    versioning_arg = self.args[0].lower()
    if versioning_arg not in ('on', 'off'):
      raise CommandException('Argument to "%s set" must be either [on|off]'
                             % (self.command_name))
    url_args = self.args[1:]
    if not url_args:
      self._RaiseWrongNumberOfArgumentsException()

    # Iterate over URLs, expanding wildcards and set the versioning
    # configuration on each.
    some_matched = False
    for url_str in url_args:
      bucket_iter = self.GetBucketUrlIterFromArg(url_str, bucket_fields=['id'])
      for blr in bucket_iter:
        url = StorageUrlFromString(blr.url_string)
        some_matched = True
        bucket_metadata = apitools_messages.Bucket(
            versioning=apitools_messages.Bucket.VersioningValue())
        if versioning_arg == 'on':
          self.logger.info('Enabling versioning for %s...', url)
          bucket_metadata.versioning.enabled = True
        else:
          self.logger.info('Suspending versioning for %s...', url)
          bucket_metadata.versioning.enabled = False
        self.gsutil_api.PatchBucket(url.bucket_name, bucket_metadata,
                                    provider=url.scheme, fields=['id'])
    if not some_matched:
      raise CommandException('No URLs matched')

  def _GetVersioning(self):
    """Gets versioning configuration for one or more buckets."""
    url_args = self.args

    # Iterate over URLs, expanding wildcards and getting the versioning
    # configuration on each.
    some_matched = False
    for url_str in url_args:
      bucket_iter = self.GetBucketUrlIterFromArg(url_str,
                                                 bucket_fields=['versioning'])
      for blr in bucket_iter:
        some_matched = True
        if blr.root_object.versioning and blr.root_object.versioning.enabled:
          print '%s: Enabled' % blr.url_string.rstrip('/')
        else:
          print '%s: Suspended' % blr.url_string.rstrip('/')
    if not some_matched:
      raise CommandException('No URLs matched')

  def RunCommand(self):
    """Command entry point for the versioning command."""
    action_subcommand = self.args.pop(0)
    if action_subcommand == 'get':
      func = self._GetVersioning
    elif action_subcommand == 'set':
      func = self._SetVersioning
    else:
      raise CommandException((
          'Invalid subcommand "%s" for the %s command.\n'
          'See "gsutil help %s".') % (
              action_subcommand, self.command_name, self.command_name))
    func()
    return 0
