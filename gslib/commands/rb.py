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
"""Implementation of rb command for deleting cloud storage buckets."""

from gslib.cloud_api import NotEmptyException
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
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HELP_TYPE
from gslib.help_provider import HelpType
from gslib.storage_url import StorageUrlFromString
from gslib.util import NO_MAX


_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil rb url...

<B>DESCRIPTION</B>
  The rb command deletes new bucket. Buckets must be empty before you can delete
  them.

  Be certain you want to delete a bucket before you do so, as once it is
  deleted the name becomes available and another user may create a bucket with
  that name. (But see also "DOMAIN NAMED BUCKETS" under "gsutil help naming"
  for help carving out parts of the bucket name space.)
""")


class RbCommand(Command):
  """Implementation of gsutil rb command."""

  # Command specification (processed by parent class).
  command_spec = {
      # Name of command.
      COMMAND_NAME: 'rb',
      # List of command name aliases.
      COMMAND_NAME_ALIASES: [
          'deletebucket', 'removebucket', 'removebuckets', 'rmdir'],
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
      HELP_NAME: 'rb',
      # List of help name aliases.
      HELP_NAME_ALIASES:
          ['deletebucket', 'removebucket', 'removebuckets', 'rmdir'],
      # Type of help:
      HELP_TYPE: HelpType.COMMAND_HELP,
      # One line summary of this help.
      HELP_ONE_LINE_SUMMARY: 'Remove buckets',
      # The full help text.
      HELP_TEXT: _detailed_help_text,
  }

  def RunCommand(self):
    """Command entry point for the rb command."""
    did_some_work = False
    for url_str in self.args:
      wildcard_url = StorageUrlFromString(url_str)
      if wildcard_url.IsObject():
        raise CommandException('"rb" command requires a provider or '
                               'bucket URL')
      for blr in self.WildcardIterator(url_str).IterBuckets():
        url = StorageUrlFromString(blr.GetUrlString())
        self.logger.info('Removing %s...', url)
        try:
          self.gsutil_api.DeleteBucket(url.bucket_name, provider=url.scheme)
        except NotEmptyException as e:
          if 'VersionedBucketNotEmpty' in e.reason:
            raise CommandException('Bucket is not empty. Note: this is a '
                                   'versioned bucket, so to delete all objects'
                                   '\nyou need to use:\n\tgsutil rm -ra %s'
                                   % url)
          else:
            raise
        did_some_work = True
    if not did_some_work:
      raise CommandException('No URLs matched')
    return 0

