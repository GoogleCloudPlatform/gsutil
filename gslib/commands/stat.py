# Copyright 2013 Google Inc. All Rights Reserved.
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
"""Implementation of Unix-like stat command for cloud storage providers."""

from __future__ import absolute_import

import logging

from gslib.bucket_listing_ref import BucketListingRef
from gslib.bucket_listing_ref import BucketListingRefType
from gslib.cloud_api import NotFoundException
from gslib.command import Command
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.command import CommandSpecKey
from gslib.command import FILE_URLS_OK
from gslib.command import MAX_ARGS
from gslib.command import MIN_ARGS
from gslib.command import PROVIDER_URLS_OK
from gslib.command import SUPPORTED_SUB_ARGS
from gslib.command import URLS_START_ARG
from gslib.cs_api_map import ApiSelector
from gslib.exception import CommandException
from gslib.exception import InvalidUrlError
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HELP_TYPE
from gslib.help_provider import HelpType
from gslib.storage_url import ContainsWildcard
from gslib.storage_url import StorageUrlFromString
from gslib.util import NO_MAX
from gslib.util import PrintFullInfoAboutObject


_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil stat uri...


<B>DESCRIPTION</B>
  The stat command will output details about the specified object URIs.
  It is similar to running:

    gsutil ls -L gs://some-bucket/some-object

  but is more efficient because it avoids performing bucket listings gets the
  minimum necessary amount of object metadata.

  The gsutil stat command will, however, perform bucket listings if you specify
  URIs using wildcards.

  If run with the gsutil -q option nothing will be printed, e.g.:

    gsutil -q stat gs://some-bucket/some-object

  This can be useful for writing scripts, because the exit status will be 0 for
  an existing object and 1 for a non-existent object.

  Note: Unlike the gsutil ls command, the stat command does not support
  operations on sub-directories. For example, if you run the command:

    gsutil -q stat gs://some-bucket/some-object/

  gsutil will look up information about the object "some-object/" (with a
  trailing slash) inside bucket "some-bucket", as opposed to operating on
  objects nested under gs://some-bucket/some-object. Unless you actually have an
  object with that name, the operation will fail.
""")


# TODO: Add ability to stat buckets.
class StatCommand(Command):
  """Implementation of gsutil stat command."""

  # Command specification (processed by parent class).
  command_spec = {
      # Name of command.
      COMMAND_NAME: 'stat',
      # List of command name aliases.
      COMMAND_NAME_ALIASES: [],
      # Min number of args required by this command.
      MIN_ARGS: 1,
      # Max number of args required by this command, or NO_MAX.
      MAX_ARGS: NO_MAX,
      # Getopt-style string specifying acceptable sub args.
      SUPPORTED_SUB_ARGS: '',
      # True if file URLs acceptable for this command.
      FILE_URLS_OK: False,
      # True if provider-only URLs acceptable for this command.
      PROVIDER_URLS_OK: False,
      # Index in args of first URL arg.
      URLS_START_ARG: 0,
      # List of supported APIs
      CommandSpecKey.GS_API_SUPPORT: [ApiSelector.XML, ApiSelector.JSON],
      # Default API to use for this command
      CommandSpecKey.GS_DEFAULT_API: ApiSelector.JSON,
  }
  help_spec = {
      # Name of command or auxiliary help info for which this help applies.
      HELP_NAME: 'stat',
      # List of help name aliases.
      HELP_NAME_ALIASES: [],
      # Type of help:
      HELP_TYPE: HelpType.COMMAND_HELP,
      # One line summary of this help.
      HELP_ONE_LINE_SUMMARY: 'Display object status',
      # The full help text.
      HELP_TEXT: _detailed_help_text,
  }

  def RunCommand(self):
    """Command entry point for stat command."""
    # List of fields we'll print for stat objects.
    stat_fields = ['updated', 'cacheControl', 'contentDisposition',
                   'contentEncoding', 'contentLanguage', 'size', 'contentType',
                   'componentCount', 'metadata', 'crc32c', 'md5Hash', 'etag',
                   'generation', 'metageneration']
    for uri_str in self.args:
      uri = StorageUrlFromString(uri_str)
      if not uri.IsObject():
        raise CommandException('The stat command only works with object URIs')
      matches = 0
      try:
        if ContainsWildcard(uri_str):
          blr_iter = self.WildcardIterator(uri_str,
                                           bucket_listing_fields=stat_fields)
        else:
          single_obj = self.gsutil_api.GetObjectMetadata(
              uri.bucket_name, uri.object_name, generation=uri.generation,
              provider=uri.scheme, fields=stat_fields)
          blr_iter = [BucketListingRef(uri_str,
                                       BucketListingRefType.OBJECT, single_obj)]
        for blr in blr_iter:
          matches += 1
          if logging.getLogger().isEnabledFor(logging.INFO):
            PrintFullInfoAboutObject(blr, incl_acl=False)
      except InvalidUrlError:
        return 1
      except NotFoundException:
        return 1
      if not matches:
        return 1
    return 0
