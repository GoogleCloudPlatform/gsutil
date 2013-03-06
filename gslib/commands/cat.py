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

import re
import sys

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
from gslib.exception import CommandException
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HelpType
from gslib.help_provider import HELP_TYPE
from gslib.util import NO_MAX
from gslib.wildcard_iterator import ContainsWildcard

_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil cat [-h] uri...


<B>DESCRIPTION</B>
  The cat command outputs the contents of one or more URIs to stdout.
  It is equivalent to doing::

    gsutil cp uri... -

  (The final '-' causes gsutil to stream the output to stdout.)


<B>OPTIONS</B>
  -h          Prints short header for each object. For example::

                gsutil cat -h gs://bucket/meeting_notes/2012_Feb/*.txt

  -r range    Causes gsutil to output just the specified byte range of the
              object. Ranges are can be of these forms::

                start-end (e.g., -r 256-5939)
                start-    (e.g., -r 256-)
                -numbytes (e.g., -r -5)

              where offsets start at 0, start-end means to return bytes start
              through end (inclusive), start- means to return bytes start
              through the end of the object, and -numbytes means to return the
              last numbytes of the object. For example::

                gsutil cat -r 256-939 gs://bucket/object

              returns bytes 256 through 939, while::

                gsutil cat -r -5 gs://bucket/object

              returns the final 5 bytes of the object.
""")


class CatCommand(Command):
  """Implementation of gsutil cat command."""

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'cat',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : [],
    # Min number of args required by this command.
    MIN_ARGS : 0,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : NO_MAX,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : 'hvr:',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : False,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 0,
    # True if must configure gsutil before running command.
    CONFIG_REQUIRED : True,
  }
  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'cat',
    # List of help name aliases.
    HELP_NAME_ALIASES : [],
    # Type of help:
    HELP_TYPE : HelpType.COMMAND_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Concatenate object content to stdout',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }

  # Command entry point.
  def RunCommand(self):
    show_header = False
    range = None
    if self.sub_opts:
      for o, a in self.sub_opts:
        if o == '-h':
          show_header = True
        elif o == '-r':
          range = a.strip()
          if not re.match('^[0-9]+-[0-9]*$|^-[0-9]+$', range):
            raise CommandException('Invalid range (%s)' % range)
        elif o == '-v':
          self.THREADED_LOGGER.info('WARNING: The %s -v option is no longer'
                                    ' needed, and will eventually be removed.\n'
                                    % self.command_name)

    printed_one = False
    # We manipulate the stdout so that all other data other than the Object
    # contents go to stderr.
    cat_outfd = sys.stdout
    sys.stdout = sys.stderr
    did_some_work = False

    for uri_str in self.args:
      for uri in self.WildcardIterator(uri_str).IterUris():
        if not uri.names_object():
          raise CommandException('"%s" command must specify objects.' %
                                 self.command_name)
        did_some_work = True
        if show_header:
          if printed_one:
            print
          print '==> %s <==' % uri.__str__()
          printed_one = True
        key = uri.get_key(False, self.headers)
        headers = self.headers.copy()
        if range:
          headers['range'] = 'bytes=%s' % range
        key.get_file(cat_outfd, headers)
    sys.stdout = cat_outfd
    if not did_some_work:
      raise CommandException('No URIs matched')

    return 0
