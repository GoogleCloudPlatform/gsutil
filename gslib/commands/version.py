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

import sys

from boto.pyami.config import BotoConfigLocations
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

class VersionCommand(Command):
  """Implementation of gsutil version command."""

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'version',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : ['ver'],
    # Min number of args required by this command.
    MIN_ARGS : 0,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : 0,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : '',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : False,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 0,
    # True if must configure gsutil before running command.
    CONFIG_REQUIRED : False,
  }

  # Command entry point.
  def RunCommand(self):
    config_ver = ''
    for path in BotoConfigLocations:
      f = None
      try:
        f = open(path, 'r')
        while True:
          line = f.readline()
          if not line:
            break
          if line.find('was created by gsutil version') != -1:
            config_ver = ', config file version %s' % line.split('"')[-2]
            break
        # Only look at first config file found in BotoConfigLocations.
        break
      except IOError:
        pass
      finally:
        if f:
          f.close()

    sys.stderr.write('gsutil version %s%s, python version %s\n' % (
        self.LoadVersionString(), config_ver, sys.version))
