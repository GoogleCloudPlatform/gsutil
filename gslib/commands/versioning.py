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

from gslib.command import Command
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.command import FILE_URIS_OK
from gslib.command import MAX_ARGS
from gslib.command import MIN_ARGS
from gslib.command import PROVIDER_URIS_OK
from gslib.command import SUPPORTED_SUB_ARGS
from gslib.command import URIS_START_ARG
from gslib.exception import CommandException
from gslib.help_provider import CreateHelpText
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HelpType
from gslib.help_provider import HELP_TYPE
from gslib.help_provider import SUBCOMMAND_HELP_TEXT
from gslib.util import NO_MAX


_SET_SYNOPSIS = """
  gsutil versioning set [on|off] bucket_uri...
"""

_GET_SYNOPSIS = """
  gsutil versioning get bucket_uri
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
  bucket and displays an XML representation of the configuration.

  In Google Cloud Storage, this would look like:

    <?xml version="1.0" ?>
    <VersioningConfiguration>
      <Status>
        Enabled
      </Status>
    </VersioningConfiguration>

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
    COMMAND_NAME : 'versioning',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : ['setversioning', 'getversioning'],
    # Min number of args required by this command.
    MIN_ARGS : 2,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : NO_MAX,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : '',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : False,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 2,
  }
  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'versioning',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['getversioning', 'setversioning'],
    # Type of help)
    HELP_TYPE : HelpType.COMMAND_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Enable or suspend versioning for one or more '
                            'buckets',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
    # Help text for sub-commands.
    SUBCOMMAND_HELP_TEXT : {'get' : _get_help_text,
                            'set' : _set_help_text},
  }

  def _CalculateUrisStartArg(self):
    if not self.args:
      self._RaiseWrongNumberOfArgumentsException()
    if (self.args[0].lower() == 'set'):
      return 2
    else:
      return 1

  def _SetVersioning(self):
    versioning_arg = self.args[0].lower()
    if not versioning_arg in ('on', 'off'):
      raise CommandException('Argument to "%s set" must be either [on|off]'
                             % (self.command_name))
    uri_args = self.args[1:]
    if len(uri_args) == 0:
      self._RaiseWrongNumberOfArgumentsException()

    # Iterate over URIs, expanding wildcards, and setting the website
    # configuration on each.
    some_matched = False
    for uri_str in uri_args:
      for blr in self.WildcardIterator(uri_str):
        uri = blr.GetUri()
        if not uri.names_bucket():
          raise CommandException('URI %s must name a bucket for the %s command'
                                 % (str(uri), self.command_name))
        some_matched = True
        if versioning_arg == 'on':
          self.logger.info('Enabling versioning for %s...', uri)
          uri.configure_versioning(True)
        else:
          self.logger.info('Suspending versioning for %s...', uri)
          uri.configure_versioning(False)
    if not some_matched:
      raise CommandException('No URIs matched')
    
  def _GetVersioning(self):
    uri_args = self.args

    # Iterate over URIs, expanding wildcards, and getting the website
    # configuration on each.
    some_matched = False
    for uri_str in uri_args:
      for blr in self.WildcardIterator(uri_str):
        uri = blr.GetUri()
        if not uri.names_bucket():
          raise CommandException('URI %s must name a bucket for the %s command'
                                 % (str(uri), self.command_name))
        some_matched = True
        uri_str = '%s://%s' % (uri.scheme, uri.bucket_name)
        if uri.get_versioning_config():
          print '%s: Enabled' % uri_str
        else:
          print '%s: Suspended' % uri_str
    if not some_matched:
      raise CommandException('No URIs matched')

  # Command entry point.
  def RunCommand(self):
    action_subcommand = self.args.pop(0)
    if action_subcommand == 'get':
      func = self._GetVersioning
    elif action_subcommand == 'set':
      func = self._SetVersioning
    else:
      raise CommandException((
          'Invalid subcommand "%s" for the %s command.\n'
          'See "gsutil help %s".') %
          (action_subcommand, self.command_name, self.command_name))
    func()
    return 0
