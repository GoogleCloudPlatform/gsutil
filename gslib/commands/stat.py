# Copyright 2013 Google Inc. All Rights Reserved.
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

from __future__ import absolute_import
import binascii
import logging
import re
import sys

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
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HelpType
from gslib.help_provider import HELP_TYPE
from gslib.util import PrintFullInfoAboutUri
from gslib.util import NO_MAX
from boto import InvalidUriError

_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil stat uri...


<B>DESCRIPTION</B>
  The stat command will output details about the specified object URIs.
  It is similar to running:

    gsutil ls -L gs://some-bucket/some-object

  but is more efficient because it avoids performing bucket listings and extra
  ACL GET's before reading each object's metadata. It performs a single HTTP
  HEAD request per listed object.

  The gsutil stat command will, however, perform bucket listings if you specify
  URIs using wildcards.

  If run with the gsutil -q option nothing will be printed, e.g.:

    gsutil -q stat gs://some-bucket/some-object

  This can be useful for writing scripts, because the exit status will be 0 for
  an existing object and 1 for a non-existent object.
""")

# TODO: Add ability to stat buckets.

class StatCommand(Command):
  """Implementation of gsutil stat command."""

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'stat',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : [],
    # Min number of args required by this command.
    MIN_ARGS : 1,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : NO_MAX,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : '',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : False,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 0,
  }
  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'stat',
    # List of help name aliases.
    HELP_NAME_ALIASES : [],
    # Type of help:
    HELP_TYPE : HelpType.COMMAND_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Display object status',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }

  # Command entry point.
  def RunCommand(self):
    for uri_str in self.args:
      uri = self.suri_builder.StorageUri(uri_str)
      if not uri.names_object():
        raise CommandException('The stat command only works with object URIs')
      for blr in self.WildcardIterator(uri):
        if logging.getLogger().isEnabledFor(logging.INFO):
          PrintFullInfoAboutUri(blr.uri, False, self.headers)
        else:
          try:
            uri.get_key(False, headers=self.headers)
          except InvalidUriError as e:
            sys.exit(1)
    return 0
