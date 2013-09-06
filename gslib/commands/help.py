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

import gslib
import itertools
import os
import re
import struct
import sys

from gslib.command import Command
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.command import FILE_URIS_OK
from gslib.command import MAX_ARGS
from gslib.command import MIN_ARGS
from gslib.command import OLD_ALIAS_MAP
from gslib.command import PROVIDER_URIS_OK
from gslib.command import SUPPORTED_SUB_ARGS
from gslib.command import URIS_START_ARG
from gslib.exception import CommandException
from gslib.help_provider import ALL_HELP_TYPES
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HelpProvider
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HelpType
from gslib.help_provider import HELP_TYPE
from gslib.help_provider import MAX_HELP_NAME_LEN
from gslib.help_provider import SUBCOMMAND_HELP_TEXT
from gslib.util import IsRunningInteractively
from subprocess import PIPE
from subprocess import Popen

_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil help [command or topic]


<B>DESCRIPTION</B>
  Running:

    gsutil help

  will provide a summary of all commands and additional topics on which
  help is available.

  Running:

    gsutil help command or topic

  will provide help about the specified command or topic.

  Running:

    gsutil help command sub-command

  will provide help about the specified sub-command. For example, running:

    gsutil help acl set

  will provide help about the "set" subcommand of the "acl" command.

  If you set the PAGER environment variable to the path to a pager program
  (such as /bin/less on Linux), long help sections will be piped through
  the specified pager.
""")

top_level_usage_string = (
    "Usage: gsutil [-d][-D] [-h header]... [-m] [command [opts...] args...] [-q]"
)

class HelpCommand(Command):
  """Implementation of gsutil help command."""

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'help',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : ['?', 'man'],
    # Min number of args required by this command.
    MIN_ARGS : 0,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : 2,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : '',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : True,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 0,
  }
  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'help',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['?'],
    # Type of help:
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
      output.append('%s\nAvailable commands:\n' % top_level_usage_string)
      format_str = '  %-' + str(MAX_HELP_NAME_LEN) + 's%s\n'
      for help_prov in sorted(help_type_map[HelpType.COMMAND_HELP],
                              key=lambda hp: hp.help_spec[HELP_NAME]):
        output.append(format_str % (help_prov.help_spec[HELP_NAME],
                                    help_prov.help_spec[HELP_ONE_LINE_SUMMARY]))
      output.append('\nAdditional help topics:\n')
      for help_prov in sorted(help_type_map[HelpType.ADDITIONAL_HELP],
                              key=lambda hp: hp.help_spec[HELP_NAME]):
        output.append(format_str % (help_prov.help_spec[HELP_NAME],
                                    help_prov.help_spec[HELP_ONE_LINE_SUMMARY]))
      output.append('\nUse gsutil help <command or topic> for detailed help.')
    else:
      invalid_subcommand = False
      arg = self.args[0]
      if arg not in help_name_map:
        output.append('No help available for "%s"' % arg)
      else:
        help_prov = help_name_map[arg]
        help_name = None
        if len(self.args) > 1:  # We also have a subcommand argument.
          subcommand_map = help_prov.help_spec.get(SUBCOMMAND_HELP_TEXT, None)
          if subcommand_map and self.args[1] in subcommand_map:
            help_name = arg + ' ' + self.args[1]
            help_text = subcommand_map[self.args[1]]
          else:
            invalid_subcommand = True
            if not subcommand_map:
              output.append((
                  'The "%s" command has no subcommands. You can ask for the ' +
                  'full help by running:\n\n\tgsutil help %s\n') %
                  (arg, arg))
            else:
              subcommand_examples = []
              for subcommand in subcommand_map:
                subcommand_examples.append(
                    '\tgsutil help %s %s' % (arg, subcommand))
              output.append(
                  ('Subcommand "%s" does not exist for command "%s".\n' +
                  'You can either ask for the full help about the command by ' +
                  'running:\n\n\tgsutil help %s\n\n'
                  'Or you can ask for help about one of the subcommands:\n\n%s'
                  ) % (self.args[1], arg, arg, '\n'.join(subcommand_examples)))
        if not invalid_subcommand:
          if not help_name:  # No subcommand or invalid subcommand.
            help_name = help_prov.help_spec[HELP_NAME]
            help_text = help_prov.help_spec[HELP_TEXT]

          output.append('<B>NAME</B>\n')
          output.append('  %s - %s\n' %
                        (help_name, help_prov.help_spec[HELP_ONE_LINE_SUMMARY]))
          output.append('\n\n')
          output.append(help_text.strip('\n'))
          new_alias = OLD_ALIAS_MAP.get(arg, [None])[0]
          if new_alias:
            deprecation_warning = """
  The "%s" alias is deprecated, and will eventually be removed completely.
  Please use the "%s" command instead.""" % (arg, new_alias)

            output.append('\n\n\n<B>DEPRECATION WARNING</B>\n')
            output.append(deprecation_warning)
    self._OutputHelp(''.join(output))
    return 0

  def _OutputHelp(self, str):
    """Outputs simply formatted string, paginating if long and PAGER defined and
       output is a tty"""
    # Replace <B> and </B> with terminal formatting strings if connected to tty.
    if not IsRunningInteractively():
      str = re.sub('<B>', '', str)
      str = re.sub('</B>', '', str)
      print str
      return
    str = re.sub('<B>', '\033[1m', str)
    str = re.sub('</B>', '\033[0;0m', str)
    num_lines = len(str.split('\n'))
    if 'PAGER' in os.environ and num_lines >= self.getTermLines():
      # Use -r option for less to make bolding work right.
      pager = os.environ['PAGER'].split(' ')
      if pager[0].endswith('less'):
        pager.append('-r')
      try:
        Popen(pager, stdin=PIPE).communicate(input=str)
      except OSError, e:
        raise CommandException('Unable to open pager (%s): %s' %
            (' '.join(pager), e))
    else:
      print str

  _DEFAULT_LINES = 25

  def getTermLines(self):
    """Returns number of terminal lines"""
    # fcntl isn't supported in Windows.
    try:
      import fcntl
      import termios
    except ImportError:
      return self._DEFAULT_LINES
    def ioctl_GWINSZ(fd):
      try:
        return struct.unpack(
            'hh', fcntl.ioctl(fd, termios.TIOCGWINSZ, '1234'))[0]
      except:
        return 0 # Failure (so will retry on different file descriptor below).
    # Try to find a valid number of lines from termio for stdin, stdout,
    # or stderr, in that order.
    ioc = ioctl_GWINSZ(0) or ioctl_GWINSZ(1) or ioctl_GWINSZ(2)
    if not ioc:
      try:
        fd = os.open(os.ctermid(), os.O_RDONLY)
        ioc = ioctl_GWINSZ(fd)
        os.close(fd)
      except:
        pass
    if not ioc:
      ioc = os.environ.get('LINES', self._DEFAULT_LINES)
    return int(ioc)

  def _LoadHelpMaps(self):
    """Returns tuple (help type -> [HelpProviders],
                      help name->HelpProvider dict,
                     )."""
    # Walk gslib/commands and gslib/addlhelp to find all HelpProviders.
    for f in os.listdir(os.path.join(gslib.GSLIB_DIR, 'commands')):
      # Handles no-extension files, etc.
      (module_name, ext) = os.path.splitext(f)
      if ext == '.py':
        __import__('gslib.commands.%s' % module_name)
    for f in os.listdir(os.path.join(gslib.GSLIB_DIR, 'addlhelp')):
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
      gslib.help_provider.SanityCheck(help_prov, help_name_map)
      help_name_map[help_prov.help_spec[HELP_NAME]] = help_prov
      for help_name_aliases in help_prov.help_spec[HELP_NAME_ALIASES]:
        help_name_map[help_name_aliases] = help_prov
      help_type_map[help_prov.help_spec[HELP_TYPE]].append(help_prov)
    return (help_type_map, help_name_map)
