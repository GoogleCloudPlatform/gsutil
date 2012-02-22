# Copyright 2011 Google Inc.
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

import fcntl
import gslib
import itertools
import os
import struct
import sys
import termios

from gslib.command import Command
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.command import CONFIG_REQUIRED
from gslib.command import FILE_URIS_OK
from gslib.command import MAX_ARGS
from gslib.command import MIN_ARGS
from gslib.command import PROVIDER_URIS_OK
from gslib.command import SUPPORTED_SUB_ARGS
from gslib.command import URIS_START_ARG
from gslib.help_provider import ALL_HELP_TYPES
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HelpProvider
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HelpType
from gslib.help_provider import HELP_TYPE
from gslib.help_provider import MAX_HELP_NAME_LEN
from subprocess import PIPE
from subprocess import Popen

_detailed_help_text = ("""
gsutil help [command or topic]
""")

top_level_usage_string = (
    "Usage: gsutil [-d][-D] [-h header]... [-m] [command [opts...] args...]"
)

class HelpCommand(Command):
  """Implementation of gsutil help command."""

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'help',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : ['?'],
    # Min number of args required by this command.
    MIN_ARGS : 0,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : 1,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : '',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : True,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 0,
    # True if must configure gsutil before running command.
    CONFIG_REQUIRED : False,
  }
  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'help',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['?'],
    # Type of help)
    HELP_TYPE : HelpType.COMMAND_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Get help about commands and topics',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }

  # Command entry point.
  def RunCommand(self):
    (help_type_map, help_name_map) = self._LoadHelpMaps()
    output = []
    if not len(self.args):
      format_str = '  %-' + str(MAX_HELP_NAME_LEN) + 's%s\n'
      output.append('%s\nAvailable commands:\n' % top_level_usage_string)
      for help_prov in sorted(help_type_map[HelpType.COMMAND_HELP],
                              key=lambda hp: hp.help_spec[HELP_NAME]):
        output.append(format_str % (help_prov.help_spec[HELP_NAME],
                                    help_prov.help_spec[HELP_ONE_LINE_SUMMARY]))
      output.append('\nAdditional help topics:\n')
      for help_prov in sorted(help_type_map[HelpType.ADDITIONAL_HELP],
                              key=lambda hp: hp.help_spec[HELP_NAME]):
        output.append(format_str % (help_prov.help_spec[HELP_NAME],
                                    help_prov.help_spec[HELP_ONE_LINE_SUMMARY]))
      output.append('\nUse gsutil help <command or topic> for detailed help')
    else:
      arg = self.args[0]
      if arg not in help_name_map:
        output.append('No help available for "%s"' % arg)
      else:
        help_prov = help_name_map[self.args[0]]
        output.append(help_prov.help_spec[HELP_TEXT].strip('\n'))
    self._OutputHelp(''.join(output))

  def _OutputHelp(self, str):
    """Outputs string, paginating if long and PAGER env var defined"""
    num_lines = len(str.split('\n'))
    if 'PAGER' in os.environ and num_lines > self.getTerminalSize()[1]:
      Popen(os.environ['PAGER'], stdin=PIPE).communicate(input=str)
    else:
      print str

  def getTerminalSize(self):
    """Returns terminal (width, height)"""
    def ioctl_GWINSZ(fd):
      try:
        cr = struct.unpack('hh', fcntl.ioctl(fd, termios.TIOCGWINSZ, '1234'))
      except:
        return (0, 0)
      return cr
    cr = ioctl_GWINSZ(0) or ioctl_GWINSZ(1) or ioctl_GWINSZ(2)
    if not cr:
      try:
        fd = os.open(os.ctermid(), os.O_RDONLY)
        cr = ioctl_GWINSZ(fd)
        os.close(fd)
      except:
        pass
    if not cr:
      try:
        cr = (env['LINES'], env['COLUMNS'])
      except:
        cr = (25, 80)
    return int(cr[1]), int(cr[0])

  def _LoadHelpMaps(self):
    """Returns tuple (help type -> [HelpProviders],
                      help name->HelpProvider dict,
                     )."""
    # Walk gslib/commands and gslib/addlhelp to find all HelpProviders.
    for f in os.listdir(os.path.join(self.gsutil_bin_dir, 'gslib', 'commands')):
      # Handles no-extension files, etc.
      (module_name, ext) = os.path.splitext(f)
      if ext == '.py':
        __import__('gslib.commands.%s' % module_name)
    for f in os.listdir(os.path.join(self.gsutil_bin_dir, 'gslib', 'addlhelp')):
      (module_name, ext) = os.path.splitext(f)
      if ext == '.py':
        __import__('gslib.addlhelp.%s' % module_name)
    help_type_map = {}
    help_name_map = {}
    for s in gslib.help_provider.ALL_HELP_TYPES:
      help_type_map[s] = []
    # Only include HelpProvider subclasses in the dict.
    for help_prov in itertools.chain(
        HelpProvider.__subclasses__(), Command.__subclasses__()):
      if help_prov is Command:
        # Skip the Command base class itself; we just want its subclasses,
        # where the help command text lives (in addition to non-Command
        # HelpProviders, like naming.py).
        continue
      gslib.help_provider.SanityCheck(help_prov)
      help_name_map[help_prov.help_spec[HELP_NAME]] = help_prov
      for help_name_aliases in help_prov.help_spec[HELP_NAME_ALIASES]:
        help_name_map[help_name_aliases] = help_prov
      help_type_map[help_prov.help_spec[HELP_TYPE]].append(help_prov)
    return (help_type_map, help_name_map)
