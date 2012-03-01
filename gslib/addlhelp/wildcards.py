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
<B>DESCRIPTION</B>
  gsutil supports URI wildcards. For example, the command:

    gsutil cp gs://bucket/data/abc* .

  will copy all objects that start with gs://bucket/data/abc followed by any
  number of characters within that subdirectory.


<B>DIRECTORY BY DIRECTORY VS RECURSIVE WILDCARDS</B>
  The "*" wildcard only matches up to the end of a path within
  a subdirectory. For example, if bucket contains objects
  named gs://bucket/data/abcd, gs://bucket/data/abcdef,
  and gs://bucket/data/abcxyx, as well as an object in a sub-directory
  (gs://bucket/data/abc/def) the above gsutil cp command would match the
  first 3 object names but not the last one.

  If you want matches to span directory boundaries, use a '**' wildcard:

    gsutil cp gs://bucket/data/abc** .

  will match all four objects above.

  Note that gsutil supports the same wildcards for both objects and file names.
  Thus, for example:

    gsutil cp data/abc* gs://bucket

  will match all names in the local file system. Most command shells also
  support wildcarding, so if you run the above command probably your shell
  is expanding the matches before running gsutil. However, most shells do not
  support recursive wildcards ('**'), and you can cause gsutil's wildcarding
  support to work for such shells by single-quoting the arguments so they
  don't get interpreted by the shell before being passed to gsutil:

    gsutil cp 'data/abc**' gs://bucket

  Note that wildcards containing '**' followed by a string containing additional
  wildcard characters are not supported. For example, you can't use:
    gs://bucket/abc**/*.txt
  Instead you should use simply:
    gs://bucket/abc**.txt


<B>OTHER WILDCARD CHARACTERS</B>
  In addition to '*', you can use these wildcards:

    ? Matches a single character. For example "gs://bucket/??.txt"
      only matches objects with two characters followed by .txt.

    [chars] Match any of the specified characters. For example
      "gs://bucket/[aeiou].txt" matches objects that contain a single vowel
      character followed by .txt

    [char range] Match any of the range of characters. For example
      "gs://bucket/[a-m].txt" matches objects that contain letters
      a, b, c, ... or m, and end with .txt.

    You can combine wildcards to provide more powerful matches, for example:
      gs://bucket/[a-m]??.j*g


<B>WILDCARDED BUCKET NAMES</B>
  Bucket names also can be wildcarded. For example you can specify multiple
  buckets using something like:
    gs://my_bucket_[0-8]??
""")


class CommandOptions(HelpProvider):
  """Additional help about wildcards."""

  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'wildcards',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['wildcard', '*', '**', '?', '[]'],
    # Type of help:
    HELP_TYPE : HelpType.ADDITIONAL_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Wildcard support',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }
