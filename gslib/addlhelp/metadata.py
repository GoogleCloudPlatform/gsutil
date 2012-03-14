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
<B>CONTENT TYPE</B>
  Objects can have associated metadata. The most common use is setting
  the Content-Type (also known as MIME type) for an object, which allows
  browsers to render the object properly. gsutil sets the Content-Type
  automatically at upload time, based on each file's name and/or content. For
  example, uploading files with names ending in .txt will set Content-Type
  to text/plain. If you're running gsutil on Linux or MacOS and would prefer
  to have content type set based on naming plus content examination, see the
  use_magicfile configuration variable in the gsutil/boto configuration file
  (See also "gsutil help config"). In general, using use_magicfile is more
  robust and configurable, but is not available on Windows.

  You can override the above Content-Type setting procedure by specifying a
  Content-Type header on the gsutil command line. For example, this command
  would cause gsutil to set a Content-Type of "image/jpg" for all the files
  being uploaded:

    gsutil -h 'Content-Type:image/jpg' cp -r images gs://bucket/images

  Note that -h is an option on the gsutil command, not the cp sub-command.

  You can also completely suppress content type detection in gsutil, by
  specifying an empty string on the Content-Type header:

    gsutil -h 'Content-Type:' cp -r images gs://bucket/images

  In this case, the Google Cloud Storage service will attempt to detect
  the content type. In general this approach will work better than using
  filename extension-based content detection in gsutil, because the list of
  filename extensions is kept more current in the server-side content detection
  system than in the Python library upon which gsutil content type detection
  depends. (For example, at the time of writing this, the filename extension
  ".webp" was recognized by the server-side content detection system, but
  not by gsutil.)

<B>CACHE-CONTROL</B>
  Another commonly set piece of metadata is Cache-Control, which allows
  you to control whether and for how long browser and Internet caches are
  allowed to cache your objects. Cache-Control only applies to objects with
  a public-read ACL. Non-public data are not cacheable.

  Here's an example of uploading an object set to allow caching:

    gsutil -h "Cache-Control:public,max-age=3600" \\
      cp -a public-read -r html gs://bucket/html

  This command would upload all files in the html directory (and subdirectories)
  and make them publicly readable and cacheable, with cache expiration of
  one hour.

  Note that if you allow caching, at download time you may see older versions
  of objects after uploading a newer replacement object. Note also that because
  objects can be cached at various places on the Internet there is no way to
  force a cached object to expire globally (unlike the way you can force your
  browser to refresh its cache).


<B>CONTENT-ENCODING</B>
  You could specify Content-Encoding to indicate that an object is compressed,
  using a command like:

    gsutil -h "Content-Encoding:gzip" cp *.gz gs://bucket/compressed

  Note that Google Cloud Storage does not compress or decompress
  objects. If you use this header to specify a compression type or
  compression algorithm (for example, deflate), Google Cloud Storage
  preserves the header but does not compress or decompress the object.

  Note also that if you are uploading a large file with compressible content
  (such as a .js, .css, or .html file), an easier way is available: see the
  -z option in "gsutil help cp".


<B>CONTENT-DISPOSITION</B>
  You can set Content-Disposition on your objects, to specify presentation
  information about the data being transmitted. Here's an example:

    gsutil -h 'Content-Disposition:attachment; filename=filename.ext' \\
      cp -r attachments gs://bucket/attachments

  See http://www.w3.org/Protocols/rfc2616/rfc2616-sec19.html#sec19.5.1
  for details about the meaning of Content-Disposition.


<B>CUSTOM METADATA</B>
  You can add your own custom metadata (e.g,. for use by your application)
  to an object by setting a header that starts with "x-goog-meta", for example:

    gsutil -h x-goog-meta-reviewer:jane cp mycode.java gs://bucket/reviews

  Note that custom headers and their associated values must contain only
  printable US-ASCII characters. If you want to store other data (such as
  binary values or Unicode) you need to encode them as ASCII.


<B>VIEWING OBJECT METADATA</B>
  You can view the metadata on an object using the gsutil ls -L command:

    gsutil ls -L gs://bucket/images/*
""")



class CommandOptions(HelpProvider):
  """Additional help about object metadata."""

  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'metadata',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['content type', 'mime type', 'mime', 'type'],
    # Type of help:
    HELP_TYPE : HelpType.ADDITIONAL_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Setting object metadata (Content-Type, etc.)',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }
