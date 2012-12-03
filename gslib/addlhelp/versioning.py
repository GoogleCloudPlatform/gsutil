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
<B>OVERVIEW OF VERSIONING</B>
  Versioning-enabled buckets will maintain an archive of overwritten objects,
  thus providing a way to restore accidentally deleted or older versions of
  your data.

  For information about Google Cloud Storage versioning, see:
    https://developers.google.com/storage/docs/object-versioning

  Version-unaware gsutil commands will interact with the latest version of the
  target object. The template for version-aware commands is to use the "-a"
  flag to refer to all versions of an object and to use "-v" to indicate that
  storage URI arguments should be parsed for version IDs or generation numbers.

  Version-ful storage URIs are specified by appending a '#' character
  followed by a version ID (S3) or generation number (GCS). Google Cloud
  Storage users may also include a meta-generation number by further appending
  a '.' character followed by the meta-generation, although all commands
  currently ignore this value.

  Examples of version-ful URIs:
    gs://bucket/object#1348879296388002
    gs://bucket/object#1348879296388002.6
    s3://bucket/object#OQBvIrRQ6CLeBIi3oTnM3Jam..t0KGxo

  Note that version-ful URIs must be used in conjunction with the "-v" flag in
  order to distinguish these URIs from object names containing '#' characters.


<B>ENABLING VERSIONING</B>
  The <B>getversioning</B> and <B>setversioning</B> subcommands allow users to
  view and set the versioning property on cloud storage buckets respectively.


<B>LISTING OBJECT VERSIONS</B>
  As described in the overview, listing respects the "-a" argument to show all
  versions of objects. For example:

    gsutil ls -a -l gs://bucket


<B>DELETING OBJECT VERSIONS</B>
  Using the rm subcommand with "-a" will instruct gsutil to delete all versions
  of the target object (use with caution).

    gsutil rm -a gs://bucket/object

  Remove also supports "-v" for specifying that the target URI is version-ful:

    gsutil rm -v gs://bucket/object#1348879296388002


<B>OTHER VERSION-AWARE COMMANDS</B>
  In addition to rm, the following commands also support the "-v" flag to
  specify a target object's version:

    cat, cp, getacl, setacl


<B>WARNING ABOUT USING SETMETA WITH VERSIONING ENABLED</B>

Note that if you use the gsutil setmeta command on an object in a bucket
with versioning enabled, it will create a new object version (and thus,
you will get charged for the space required for holding the additional version.
""")


class CommandOptions(HelpProvider):
  """Additional help about object versioning."""

  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'versioning',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['versioning', 'versions'],
    # Type of help:
    HELP_TYPE : HelpType.ADDITIONAL_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Working with object versions',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }
