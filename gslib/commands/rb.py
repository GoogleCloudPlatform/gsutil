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
from gslib.cs_api_map import ApiSelector
from gslib.exception import CommandException
from gslib.storage_url import StorageUrlFromString
from gslib.util import NO_MAX


_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil [-f] rb url...

<B>DESCRIPTION</B>
  The rb command deletes new bucket. Buckets must be empty before you can delete
  them.

  Be certain you want to delete a bucket before you do so, as once it is
  deleted the name becomes available and another user may create a bucket with
  that name. (But see also "DOMAIN NAMED BUCKETS" under "gsutil help naming"
  for help carving out parts of the bucket name space.)


<B>OPTIONS</B>
  -f          Continues silently (without printing error messages) despite
              errors when removing buckets. With this option the gsutil
              exit status will be 0 even if some buckets couldn't be removed.
""")


class RbCommand(Command):
  """Implementation of gsutil rb command."""

  # Command specification. See base class for documentation.
  command_spec = Command.CreateCommandSpec(
      'rb',
      command_name_aliases=[
          'deletebucket', 'removebucket', 'removebuckets', 'rmdir'],
      min_args=1,
      max_args=NO_MAX,
      supported_sub_args='f',
      file_url_ok=False,
      provider_url_ok=False,
      urls_start_arg=0,
      gs_api_support=[ApiSelector.XML, ApiSelector.JSON],
      gs_default_api=ApiSelector.JSON,
  )
  # Help specification. See help_provider.py for documentation.
  help_spec = Command.HelpSpec(
      help_name='rb',
      help_name_aliases=[
          'deletebucket', 'removebucket', 'removebuckets', 'rmdir'],
      help_type='command_help',
      help_one_line_summary='Remove buckets',
      help_text=_detailed_help_text,
      subcommand_help_text={},
  )

  def RunCommand(self):
    """Command entry point for the rb command."""
    self.continue_on_error = False
    if self.sub_opts:
      for o, unused_a in self.sub_opts:
        if o == '-f':
          self.continue_on_error = True

    did_some_work = False
    for url_str in self.args:
      wildcard_url = StorageUrlFromString(url_str)
      if wildcard_url.IsObject():
        raise CommandException('"rb" command requires a provider or '
                               'bucket URL')
      # Wrap WildcardIterator call in try/except so we can avoid printing errors
      # with -f option if a non-existent URL listed, permission denial happens
      # while listing, etc.
      try:
        # Need to materialize iterator results into a list to catch exceptions.
        # Since this is listing buckets this list shouldn't be too large to fit
        # in memory at once.
        blrs = list(self.WildcardIterator(url_str).IterBuckets())
      except:
        if self.continue_on_error:
          continue
        else:
          raise
      for blr in blrs:
        url = StorageUrlFromString(blr.GetUrlString())
        self.logger.info('Removing %s...', url)
        try:
          self.gsutil_api.DeleteBucket(url.bucket_name, provider=url.scheme)
        except NotEmptyException as e:
          if self.continue_on_error:
            continue
          elif 'VersionedBucketNotEmpty' in e.reason:
            raise CommandException('Bucket is not empty. Note: this is a '
                                   'versioned bucket, so to delete all '
                                   'objects\nyou need to use:'
                                   '\n\tgsutil rm -r %s' % url)
          else:
            raise
        except: # pylint: disable=broad-except
          if not self.continue_on_error:
            raise
        did_some_work = True
    if not did_some_work:
      raise CommandException('No URLs matched')
    return 0

