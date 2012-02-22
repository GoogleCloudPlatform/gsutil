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
Omitting URI scheme defaults to "file". For example, "dir/file.txt" is
equivalent to "file://dir/file.txt"

URIs support object name wildcards, for example:
  gsutil cp gs://mybucket/[a-f]*.doc localdir

Source directory or bucket names are implicitly wildcarded, so
  gsutil cp localdir gs://mybucket
will recursively copy localdir.

canned_acl_name can be one of: "private", "project-private",
"public-read", "public-read-write", "authenticated-read",
"bucket-owner-read", "bucket-owner-full-control"
""")


class CommandOptions(HelpProvider):
  """Additional help about gsutil object and bucket naming."""

  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'naming',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['name', 'names', 'subdirs', 'wildcards', 'wildcarding'],
    # Type of help)
    HELP_TYPE : HelpType.ADDITIONAL_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Object and bucket naming',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }
