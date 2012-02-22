# Copyright 2012 Google Inc.
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

from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HelpProvider
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HelpType
from gslib.help_provider import HELP_TYPE

_detailed_help_text = ("""
Top-level gsutil options:
  -d: Shows HTTP requests/headers.
  -D: Shows HTTP requests/headers plus additional debug info needed when posting
      support requests.
  -DD Shows HTTP requests/headers plus additional debug info plus HTTP upstream
      payload.
  -h: Allows you to specify additional HTTP headers, for example:
      gsutil -h "Cache-Control:public,max-age=3600" \\
             -h "Content-Type:text/html" cp ...
  -m: Causes supported operations (cp, mv, rm) to run in parallel.
  -s: Tells gsutil to use a simulated storage provider (for testing).
""")


class CommandOptions(HelpProvider):
  """Additional help about gsutil command-level optinos."""

  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'options',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['cli', 'opt', 'opts'],
    # Type of help)
    HELP_TYPE : HelpType.ADDITIONAL_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'gsutil-level command line options',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }
