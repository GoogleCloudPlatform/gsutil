# Copyright 2011 Google Inc. All Rights Reserved.
# Copyright 2011, Nexenta Systems Inc.
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
"""Implementation of Unix-like cat command for cloud storage providers."""

import re

from gslib.cat_helper import CatHelper
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
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HELP_TYPE
from gslib.help_provider import HelpType
from gslib.util import NO_MAX

_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil cat [-h] url...


<B>DESCRIPTION</B>
  The cat command outputs the contents of one or more URLs to stdout.
  It is equivalent to doing:

    gsutil cp url... -

  (The final '-' causes gsutil to stream the output to stdout.)


<B>OPTIONS</B>
  -h          Prints short header for each object. For example:

                gsutil cat -h gs://bucket/meeting_notes/2012_Feb/*.txt

              This would print a header with the object name before the contents
              of each text object that matched the wildcard.

  -r range    Causes gsutil to output just the specified byte range of the
              object. Ranges are can be of these forms:

                start-end (e.g., -r 256-5939)
                start-    (e.g., -r 256-)
                -numbytes (e.g., -r -5)

              where offsets start at 0, start-end means to return bytes start
              through end (inclusive), start- means to return bytes start
              through the end of the object, and -numbytes means to return the
              last numbytes of the object. For example:

                gsutil cat -r 256-939 gs://bucket/object

              returns bytes 256 through 939, while:

                gsutil cat -r -5 gs://bucket/object

              returns the final 5 bytes of the object.
""")


class CatCommand(Command):
  """Implementation of gsutil cat command."""

  # Command specification (processed by parent class).
  command_spec = {
      # Name of command.
      COMMAND_NAME: 'cat',
      # List of command name aliases.
      COMMAND_NAME_ALIASES: [],
      # Min number of args required by this command.
      MIN_ARGS: 0,
      # Max number of args required by this command, or NO_MAX.
      MAX_ARGS: NO_MAX,
      # Getopt-style string specifying acceptable sub args.
      SUPPORTED_SUB_ARGS: 'hvr:',
      # True if file URLs acceptable for this command.
      FILE_URLS_OK: False,
      # True if provider-only URLs acceptable for this command.
      PROVIDER_URLS_OK: False,
      # Index in args of first URL arg.
      URLS_START_ARG: 0,
      # List of supported APIs
      CommandSpecKey.GS_API_SUPPORT: [ApiSelector.XML, ApiSelector.JSON],
      # Default API to use for this command
      CommandSpecKey.GS_DEFAULT_API: ApiSelector.JSON,
  }
  help_spec = {
      # Name of command or auxiliary help info for which this help applies.
      HELP_NAME: 'cat',
      # List of help name aliases.
      HELP_NAME_ALIASES: [],
      # Type of help:
      HELP_TYPE: HelpType.COMMAND_HELP,
      # One line summary of this help.
      HELP_ONE_LINE_SUMMARY: 'Concatenate object content to stdout',
      # The full help text.
      HELP_TEXT: _detailed_help_text,
  }

  # Command entry point.
  def RunCommand(self):
    """Command entry point for the cat command."""
    show_header = False
    request_range = None
    start_byte = 0
    end_byte = None
    if self.sub_opts:
      for o, a in self.sub_opts:
        if o == '-h':
          show_header = True
        elif o == '-r':
          request_range = a.strip()
          range_matcher = re.compile(
              '^(?P<start>[0-9]+)-(?P<end>[0-9]*)$|^(?P<endslice>-[0-9]+)$')
          range_match = range_matcher.match(request_range)
          if not range_match:
            raise CommandException('Invalid range (%s)' % request_range)
          if range_match.group('start'):
            start_byte = long(range_match.group('start'))
          if range_match.group('end'):
            end_byte = long(range_match.group('end'))
          if range_match.group('endslice'):
            start_byte = long(range_match.group('endslice'))
        elif o == '-v':
          self.logger.info('WARNING: The %s -v option is no longer'
                           ' needed, and will eventually be removed.\n'
                           % self.command_name)

    return CatHelper(self).CatUrlStrings(self.args,
                                         show_header=show_header,
                                         start_byte=start_byte,
                                         end_byte=end_byte)
