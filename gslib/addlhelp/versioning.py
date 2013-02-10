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
<B>OVERVIEW</B>
  Versioning-enabled buckets maintain an archive of objects, providing a way to
  un-delete data that you accidentally deleted, or to retrieve older versions of
  your data. You can turn versioning on or off for a bucket at any time. Turning
  versioning off leaves existing object versions in place, and simply causes the
  bucket to stop accumulating new object versions. In this case, if you upload
  to an existing object, the current version is overwritten instead of creating
  a new version.

  Regardless of whether you have enabled versioning on a bucket, every object
  has two associated versioning-related fields, each of which is a positive
  integer:
    - the generation, which is updated when the content of an object is
      overwritten.
    - the meta-generation identifies the metadata generation. It starts at 1; is
      updated every time the metadata (e.g., ACL or Content-Type) for a given
      content generation is updated; and gets reset when the generation number
      changes.

  When working with versioning in gsutil, you use a more detailed flavor of
  "version-specific" URIs, which embed the generation and meta-generation.
  Generation and meta-generation can also be used for concurrency control
  (discussed in the CONCURRENCY CONTROL section), regardless of whether you have
  versioning enabled for a bucket.

  Every object can be named using either version-less or version-specific URIs.
  For example, the version-less object URI:

    gs://bucket/object

  might have have two versions, with these version-specific URIs:

    gs://bucket/x#1360383693690000.1
    gs://bucket/x#1360383802725000.3
  
  Version-specific URIs encode the generation and meta-generation described
  earlier. For the second version-specific URI listed above, the generation
  is 1360383802725000 and the meta-generation is 3.

  The following sections discussion how to work with versioning and concurrency
  control.


<B>OBJECT VERSIONING</B>
  You can view, enable, and disable object versioning on a bucket using
  the getversioning and setversioning commands.

  To see all object versions in a versioning-enabled bucket along with
  their generation.meta-generation information, use gsutil ls -a:

    gsutil ls -a gs://bucket

  You can also specify particular objects for which you want to find the
  version-specific URI(s), or you can use wildcards:

    gsutil ls -a gs://bucket/object1 gs://bucket/images/*.jpg

  The generation.meta-generation values form a monotonically increasing
  sequence as you create additional object generations and as you update
  metadata on objects. Because of this, the latest object version is always the
  last one listed in the gsutil ls output for a particular object. For example,
  if a bucket contains these three versions of gs://bucket/object:

    gs://bucket/object#1360035307075000.3
    gs://bucket/object#1360101007329000.5
    gs://bucket/object#1360102216114000.1

  then gs://bucket/object#1360102216114000.1 is the latest version and
  gs://bucket/object#1360035307075000.1 is the oldest available version.

  If you specify version-less URIs with gsutil, you will operate on the
  latest not-deleted version of an object, for example:

    gsutil cp gs://bucket/object ./dir

  or

    gsutil rm gs://bucket/object

  To operate on a specific object version, use a version-specific URI.
  For example, suppose the output of the above gsutil ls -a command is:

    gs://bucket/object#1360035307075000.1
    gs://bucket/object#1360101007329000.1

  In this case, the command:

    gsutil cp gs://bucket/object#1360035307075000.1 ./dir

  will retrieve the second most recent version of the object.

  If an object has been deleted, it will not show up in a normal gsutil ls
  listing (i.e., ls without the -a option). You can restore a deleted object by
  running gsutil ls -a to find the available versions, and then copying one of
  the version-specific URIs to the version-less URI, for example:

    gsutil cp gs://bucket/object#1360101007329000.1 gs://bucket/object

  Note that when you do this it creates a new object version, which will incur
  additional charges. You can get rid of the extra copy by deleting the older
  version-specfic object:

    gsutil rm gs://bucket/object#1360101007329000.1

  Or you can combine the two steps by using the gsutil mv command:

    gsutil mv gs://bucket/object#1360101007329000.1 gs://bucket/object

  If you want to remove all versions of an object use the gsutil rm -a option:

    gsutil rm -a gs://bucket/object


<B>CONCURRENCY CONTROL</B>

  The other use of version-specific URIs is in support of concurrency control.
  For example, suppose you want to implement a "rolling update" system using
  gsutil, where a periodic job computes some data and uploads it to the cloud.
  On each run, the job starts with the data that it computed from last run, and
  computes a new value. To make this system robust, you need to have multiple
  machines on which the job can run, which raises the possibliity that two
  simultaneous runs could attempt to update an object at the same time. This
  leads to the following potential race condition:
    - job 1 computes the new value to be written
    - job 2 computes the new value to be written
    - job 2 writes the new value
    - job 1 writes the new value

  In this case, the value that job 1 read is no longer current by the time
  it goes to write the updated object, and writing at this point would result
  in stale (or, depending on the application, corrupt) data.

  To prevent this, you can find the version-specific name of the object that was
  created, and then use the information contained in that URI to set concurrency
  control preconditions on future object writes.  You can use the gsutil cp -v
  option at upload time to get the version-specific name of the object that was
  created, for example:

    gsutil cp -v file gs://bucket/object

  might output:

    Created: gs://bucket/object#1360432179236000.1

  You can extract the generation and meta_generation fields from this name and
  use these values in the x-goog-if-generation-match and
  x-goog-if-metageneration-match headers to implement concurrency control. For
  example, you could request that gsutil update this object only if the current
  live version has the same generation as the one created above by doing:

    gsutil -h x-goog-if-generation-match:1360432179236000 cp newfile \\
        gs://bucket/object

  You could request that gsutil update this object only if the current live
  version has both the same generation and the same meta_generation by doing:

    gsutil -h x-goog-if-generation-match:1360432179236000 \\
        -h x-goog-if-metageneration-match:1 cp newfile \\
        gs://bucket/object


<B>FOR MORE INFORMATION</B>
  For more details on how to use versioning and preconditions, see
  https://developers.google.com/storage/docs/object-versioning
""")


class CommandOptions(HelpProvider):
  """Additional help about object versioning."""

  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'versioning',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['concurrency', 'concurrency control', 'versioning',
                         'versions'],
    # Type of help:
    HELP_TYPE : HelpType.ADDITIONAL_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Working with object versions; concurrency control',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }
