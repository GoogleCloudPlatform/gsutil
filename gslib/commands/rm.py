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
"""Implementation of Unix-like rm command for cloud storage providers."""

from gslib.cloud_api import NotEmptyException
from gslib.cloud_api import ServiceException
from gslib.command import Command
from gslib.cs_api_map import ApiSelector
from gslib.exception import CommandException
from gslib.name_expansion import NameExpansionIterator
from gslib.storage_url import StorageUrlFromString
from gslib.util import GetCloudApiInstance
from gslib.util import NO_MAX
from gslib.util import Retry


_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil rm [-f] [-R] url...


<B>DESCRIPTION</B>
  The gsutil rm command removes objects.
  For example, the command:

    gsutil rm gs://bucket/subdir/*

  will remove all objects in gs://bucket/subdir, but not in any of its
  sub-directories. In contrast:

    gsutil rm gs://bucket/subdir/**

  will remove all objects under gs://bucket/subdir or any of its
  subdirectories.

  You can also use the -R option to specify recursive object deletion. Thus, for
  example, either of the following two commands will remove gs://bucket/subdir
  and all objects and subdirectories under it:

    gsutil rm gs://bucket/subdir**
    gsutil rm -R gs://bucket/subdir

  Running gsutil rm -R on a bucket will delete all objects in the bucket, and
  then delete the bucket:

    gsutil rm -R gs://bucket

  If you want to delete all objects in the bucket, but not the bucket itself,
  this command will work:

    gsutil rm gs://bucket/**

  If you have a large number of objects to remove you might want to use the
  gsutil -m option, to perform a parallel (multi-threaded/multi-processing)
  removes:

    gsutil -m rm -R gs://my_bucket/subdir

  Note that gsutil rm will refuse to remove files from the local
  file system. For example this will fail:

    gsutil rm *.txt

  WARNING: Object removal cannot be undone. Google Cloud Storage is designed
  to give developers a high amount of flexibility and control over their data,
  and Google maintains strict controls over the processing and purging of
  deleted data. To protect yourself from mistakes, you can configure object
  versioning on your bucket(s). See 'gsutil help versions' for details.


<B>OPTIONS</B>
  -f          Continues silently (without printing error messages) despite
              errors when removing multiple objects. With this option the gsutil
              exit status will be 0 even if some objects couldn't be removed.

  -R, -r      Causes bucket contents to be removed recursively (i.e., including
              all objects and subdirectories). If used with a bucket-only URL
              (like gs://bucket), after deleting objects and subdirectories
              gsutil will delete the bucket.

  -a          Delete all versions of an object.
""")


def _RemoveExceptionHandler(cls, e):
  """Simple exception handler to allow post-completion status."""
  cls.logger.error(str(e))
  cls.everything_removed_okay = False


# pylint: disable=unused-argument
def _RemoveFoldersExceptionHandler(cls, e):
  """When removing folders, we don't mind if none exist."""
  if (isinstance(e, CommandException.__class__) and
      'No URLs matched' in e.message):
    pass
  else:
    raise e


def _RemoveFuncWrapper(cls, name_expansion_result, thread_state=None):
  cls.RemoveFunc(name_expansion_result, thread_state=thread_state)


class RmCommand(Command):
  """Implementation of gsutil rm command."""

  # Command specification. See base class for documentation.
  command_spec = Command.CreateCommandSpec(
      'rm',
      command_name_aliases=['del', 'delete', 'remove'],
      min_args=1,
      max_args=NO_MAX,
      supported_sub_args='afrRv',
      file_url_ok=False,
      provider_url_ok=False,
      urls_start_arg=0,
      gs_api_support=[ApiSelector.XML, ApiSelector.JSON],
      gs_default_api=ApiSelector.JSON,
  )
  # Help specification. See help_provider.py for documentation.
  help_spec = Command.HelpSpec(
      help_name='rm',
      help_name_aliases=['del', 'delete', 'remove'],
      help_type='command_help',
      help_one_line_summary='Remove objects',
      help_text=_detailed_help_text,
      subcommand_help_text={},
  )

  def RunCommand(self):
    """Command entry point for the rm command."""
    # self.recursion_requested is initialized in command.py (so it can be
    # checked in parent class for all commands).
    self.continue_on_error = False
    self.all_versions = False
    if self.sub_opts:
      for o, unused_a in self.sub_opts:
        if o == '-a':
          self.all_versions = True
        elif o == '-f':
          self.continue_on_error = True
        elif o == '-r' or o == '-R':
          self.recursion_requested = True
        elif o == '-v':
          self.logger.info('WARNING: The %s -v option is no longer'
                           ' needed, and will eventually be removed.\n'
                           % self.command_name)

    bucket_urls_to_delete = []
    if self.recursion_requested:
      bucket_fields = ['id']
      # Note that this is inefficient when using the XML API with bucket
      # wildcards. We make a separate versioning-get call for all buckets, even
      # those that don't match the wildcard filter.  This can be worked around
      # by just specifying the -a flag.
      if not self.all_versions:
        bucket_fields.append('versioning')
      for url_str in self.args:
        url = StorageUrlFromString(url_str)
        if url.IsBucket() or url.IsProvider():
          for blr in self.WildcardIterator(url_str).IterBuckets(
              bucket_fields=bucket_fields):
            bucket = blr.root_object
            if (not self.all_versions and bucket.versioning and
                bucket.versioning.enabled):
              raise CommandException(
                  'Running gsutil rm -R on a bucket-only URL (%s)\nwith '
                  'versioning enabled will not work without specifying the -a '
                  'flag. Please try\nagain, using:\n\tgsutil rm -Ra %s'
                  % (url_str, ' '.join(self.args)))
            bucket_urls_to_delete.append(
                StorageUrlFromString(blr.GetUrlString()))

    # Used to track if any files failed to be removed.
    self.everything_removed_okay = True

    try:
      # Expand wildcards, dirs, buckets, and bucket subdirs in URLs.
      name_expansion_iterator = NameExpansionIterator(
          self.command_name, self.debug,
          self.logger, self.gsutil_api,
          self.args, self.recursion_requested,
          project_id=self.project_id,
          all_versions=self.all_versions)

      # Perform remove requests in parallel (-m) mode, if requested, using
      # configured number of parallel processes and threads. Otherwise,
      # perform requests with sequential function calls in current process.
      self.Apply(_RemoveFuncWrapper, name_expansion_iterator,
                 _RemoveExceptionHandler,
                 fail_on_error=(not self.continue_on_error))

    # Assuming the bucket has versioning enabled, url's that don't map to
    # objects should throw an error even with all_versions, since the prior
    # round of deletes only sends objects to a history table.
    # This assumption that rm -a is only called for versioned buckets should be
    # corrected, but the fix is non-trivial.
    except CommandException as e:
      # Don't raise if there are buckets to delete -- it's valid to say:
      #   gsutil rm -r gs://some_bucket
      # if the bucket is empty.
      if not bucket_urls_to_delete and not self.continue_on_error:
        raise
    except ServiceException, e:
      if not self.continue_on_error:
        raise

    if not self.everything_removed_okay and not self.continue_on_error:
      raise CommandException('Some files could not be removed.')

    # If this was a gsutil rm -r command covering any bucket subdirs,
    # remove any dir_$folder$ objects (which are created by various web UI
    # tools to simulate folders).
    if self.recursion_requested:
      folder_object_wildcards = []
      for url_str in self.args:
        url = StorageUrlFromString(url_str)
        if url.IsObject():
          folder_object_wildcards.append('%s**_$folder$' % url_str)
      if folder_object_wildcards:
        self.continue_on_error = True
        try:
          name_expansion_iterator = NameExpansionIterator(
              self.command_name, self.debug,
              self.logger, self.gsutil_api,
              folder_object_wildcards, self.recursion_requested,
              project_id=self.project_id,
              all_versions=self.all_versions)
          # When we're removing folder objects, always continue on error
          self.Apply(_RemoveFuncWrapper, name_expansion_iterator,
                     _RemoveFoldersExceptionHandler,
                     fail_on_error=False)
        except CommandException as e:
          # Ignore exception from name expansion due to an absent folder file.
          if not e.reason.startswith('No URLs matched:'):
            raise

    # Now that all data has been deleted, delete any bucket URLs.
    for url in bucket_urls_to_delete:
      self.logger.info('Removing %s...', url)

      @Retry(NotEmptyException, tries=3, timeout_secs=1)
      def BucketDeleteWithRetry():
        self.gsutil_api.DeleteBucket(url.bucket_name, provider=url.scheme)

      BucketDeleteWithRetry()

    return 0

  def RemoveFunc(self, name_expansion_result, thread_state=None):
    gsutil_api = GetCloudApiInstance(self, thread_state=thread_state)

    exp_src_url = StorageUrlFromString(
        name_expansion_result.GetExpandedUrlStr())
    self.logger.info('Removing %s...',
                     name_expansion_result.GetExpandedUrlStr())
    gsutil_api.DeleteObject(
        exp_src_url.bucket_name, exp_src_url.object_name,
        generation=exp_src_url.generation, provider=exp_src_url.scheme)

