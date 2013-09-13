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

import boto
import crcmod
import os
import re
import sys

import gslib
from gslib.command import Command
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.command import FILE_URIS_OK
from gslib.command import MAX_ARGS
from gslib.command import MIN_ARGS
from gslib.command import PROVIDER_URIS_OK
from gslib.command import SUPPORTED_SUB_ARGS
from gslib.command import URIS_START_ARG
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HelpType
from gslib.help_provider import HELP_TYPE
from gslib.util import GetConfigFilePath
from gslib.util import UsingCrcmodExtension
from hashlib import md5

_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil version


<B>DESCRIPTION</B>
  Prints information about the version of gsutil.

<B>OPTIONS</B>
  -l          Prints additional information, such as the version of Python
              being used, the version of the Boto library, a checksum of the
              code, the path to gsutil, and the path to gsutil's configuration
              file.
""")


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
    SUPPORTED_SUB_ARGS : 'l',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : False,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 0,
  }
  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'version',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['ver'],
    # Type of help:
    HELP_TYPE : HelpType.COMMAND_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Print version info about gsutil',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }

  # Command entry point.
  def RunCommand(self):
    long_form = False
    if self.sub_opts:
      for o, a in self.sub_opts:
        if o == '-l':
          long_form = True

    config_path = GetConfigFilePath()

    shipped_checksum = gslib.CHECKSUM
    try:
      cur_checksum = self._ComputeCodeChecksum()
    except IOError:
      cur_checksum = 'MISSING FILES'
    if shipped_checksum == cur_checksum:
      checksum_ok_str = 'OK'
    else:
      checksum_ok_str = '!= %s' % shipped_checksum

    sys.stdout.write('gsutil version %s\n' % gslib.VERSION)

    if long_form:

      long_form_output = (
          'checksum {checksum} ({checksum_ok})\n'
          'boto version {boto_version}\n'
          'python version {python_version}\n'
          'config path: {config_path}\n'
          'gsutil path: {gsutil_path}\n'
          'compiled crcmod: {compiled_crcmod}\n'
          'installed via package manager: {is_package_install}\n'
          'editable install: {is_editable_install}\n'
          )

      sys.stdout.write(long_form_output.format(
          checksum=cur_checksum,
          checksum_ok=checksum_ok_str,
          boto_version=boto.__version__,
          python_version=sys.version,
          config_path=config_path,
          gsutil_path=gslib.GSUTIL_PATH,
          compiled_crcmod=UsingCrcmodExtension(crcmod),
          is_package_install=gslib.IS_PACKAGE_INSTALL,
          is_editable_install=gslib.IS_EDITABLE_INSTALL,
          ))

    return 0

  def _ComputeCodeChecksum(self):
    """
    Computes a checksum of gsutil code so we can see if users locally modified
    gsutil when requesting support. (It's fine for users to make local mods,
    but when users ask for support we ask them to run a stock version of
    gsutil so we can reduce possible variables.)
    """
    if gslib.IS_PACKAGE_INSTALL:
      return 'PACKAGED_GSUTIL_INSTALLS_DO_NOT_HAVE_CHECKSUMS'
    m = md5()
    # Checksum gsutil and all .py files under gslib directory.
    files_to_checksum = [gslib.GSUTIL_PATH]
    for root, sub_folders, files in os.walk(gslib.GSLIB_DIR):
      for file in files:
        if file[-3:] == '.py':
          files_to_checksum.append(os.path.join(root, file))
    # Sort to ensure consistent checksum build, no matter how os.walk
    # orders the list.
    for file in sorted(files_to_checksum):
      f = open(file, 'r')
      content = f.read()
      content = re.sub(r'(\r\n|\r|\n)', '\n', content)
      m.update(content)
      f.close()
    return m.hexdigest()
