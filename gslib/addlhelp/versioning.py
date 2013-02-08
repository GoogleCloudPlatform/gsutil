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
  Versioning-enabled buckets maintain an archive of overwritten objects,
  thus providing a way to un-delete data that you accidentally deleted,
  or to retrieve older versions of your data.

  Google Cloud Storage associates two versioning-related fields with each
  object in a versioning-enabled bucket:
    - generation, which identifies the content generation, and is updated
      when the content of an object is overwritten.
    - meta-generation, which identifies the metadata generation and is
      updated every time the metadata (e.g. ACL) for a given content generation
      is updated.

  gsutil commands interact with the latest object version unless you specify a
  version-specific URI. For example, the version-less object:
  
    gs://bucket/object

  might have the version-specific name:

    gs://bucket/object#1348879296388002.6
    
  For this URI, 1348879296388002 is the object's generation, and 6 is its
  meta-generation.


<B>ENABLING VERSIONING</B>
  The <B>getversioning</B> and <B>setversioning</B> subcommands allow users to
  view and set the versioning property on cloud storage buckets respectively.


<B>WORKING WITH OBJECT VERSIONS</B>
  To see all object versions in a versioning-enabled bucket along with
  their generation.meta-generation information, use gsutil ls -a:

    gsutil ls -a gs://bucket

  You can also use wildcards:

    gsutil ls -a gs://bucket/images/*.jpg

  The generation.meta-generation values form a monotonically increasing
  sequence as you create additional object generations. Because of this,
  the latest object version is always the last one listed in the gsutil ls
  output for a particular object. For example, if a bucket contains these
  three object versions:

    gs://bucket/object1#1360035307075000.1
    gs://bucket/object1#1360101007329000.1
    gs://bucket/object2#1360102216114000.1

  then gs://bucket/object1#1360101007329000.1 is the latest version of
  gs://bucket/object1.

  If you specify version-less URIs with gsutil, you will operate on the
  latest not-deleted version of an object, for example:

    gsutil cp gs://bucket/object ./dir

  or

    gsutil rm gs://bucket/object

  To operate on a specific object version, use a version-specific URI.
  For example, suppose the output of the above gsutil ls -a command is:

    gs://bucket/object#1360035307075000.1
    gs://bucket/object#1360101007329000.1

  Thus, the command:

    gsutil cp gs://bucket/object#1360035307075000.1 ./dir

  will retrieve the previous version of the object.

  If an object has been deleted, it will not show up in a normal gsutil ls
  listing (i.e., one that doesn't specify the -a option). You can restore
  a deleted object by running gsutil ls -a to find the available versions,
  and then copying one of the version-specific URIs to the version-less URI,
  for example:

    gsutil cp gs://bucket/object#1360101007329000.1 gs://bucket/object

  Note that when you do this it creates a new object version, which will
  incur additional charges.

  You can get rid of the extra copy by deleting the older version-specfic
  object:

    gsutil rm gs://bucket/object#1360101007329000.1

  Or you can combine the two steps by using the gsutil mv command:

    gsutil mv gs://bucket/object#1360101007329000.1 gs://bucket/object

  If you want to remove all versions of an object use the gsutil rm -a option:

    gsutil rm -a gs://bucket/object


<B>For MORE INFORMATION</B>
  For more information about Google Cloud Storage versioning, see:
    https://developers.google.com/storage/docs/object-versioning
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
