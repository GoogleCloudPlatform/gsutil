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

import os

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
from gslib.util import NO_MAX

class EnableLoggingCommand(Command):
  """Implementation of gsutil enablelogging command."""

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'enablelogging',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : [],
    # Min number of args required by this command.
    MIN_ARGS : 1,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : NO_MAX,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : 'b:o:',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : False,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 0,
    # True if must configure gsutil before running command.
    CONFIG_REQUIRED : True,
  }

  # Command entry point.
  def RunCommand(self):
    # Disallow multi-provider enablelogging calls, because the schemas
    # differ.
    storage_uri = self.UrisAreForSingleProvider(self.args)
    if not storage_uri:
      raise CommandException('enablelogging command spanning providers not '
                             'allowed.')
    target_bucket = None
    target_prefix = None
    for opt, opt_arg in self.sub_opts:
      if opt == '-b':
        target_bucket = opt_arg
      if opt == '-o':
        target_prefix = opt_arg

    if not target_bucket:
      raise CommandException('enablelogging requires \'-b <log_bucket>\' '
                             'option')

    for uri_str in self.args:
      for uri in self.CmdWildcardIterator(uri_str):
        if uri.object_name:
          raise CommandException('enablelogging cannot be applied to objects')
        print 'Enabling logging on %s...' % uri
        self.proj_id_handler.FillInProjectHeaderIfNeeded(
            'enablelogging', storage_uri, self.headers)
        uri.enable_logging(target_bucket, target_prefix, False, self.headers)
