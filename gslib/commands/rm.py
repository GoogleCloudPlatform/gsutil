# Copyright 2011 Google Inc.
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

import boto

from gslib.command import Command
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.command import CONFIG_REQUIRED
from gslib.command import FILE_URIS_OK
from gslib.command import MAX_ARGS
from gslib.command import MIN_ARGS
from gslib.command import PROVIDER_URIS_OK
from gslib.command import SUPPORTED_SUB_ARGS
from gslib.command import URIS_START_ARG
from gslib.exception import CommandException
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HelpType
from gslib.help_provider import HELP_TYPE
from gslib.util import NO_MAX

_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil rm [-f] [-R] uri...


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
  example, the following two commands will both remove all objects in a bucket:

    gsutil rm gs://bucket/**
    gsutil rm -R gs://bucket

  If you have a large number of objects to remove you might want to use the
  gsutil -m option, to perform a parallel (multi-threaded/multi-processing)
  removes:

    gsutil -m rm -R gs://my_bucket/subdir

  Note that gsutil rm will refuse to remove files from the local
  file system. For example this will fail:

    gsutil rm *.txt


<B>OPTIONS</B>
  -f          Continues silently (without printing error messages) despite
              errors when removing multiple objects.

  -R, -r      Causes bucket contents to be removed recursively (i.e., including
              all objects and subdirectories). Will not delete the bucket
              itself; you need to run the gsutil rb command separately to do
              that.
""")


class RmCommand(Command):
  """Implementation of gsutil rm command."""

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'rm',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : ['del', 'delete', 'remove'],
    # Min number of args required by this command.
    MIN_ARGS : 1,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : NO_MAX,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : 'frR',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : False,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 0,
    # True if must configure gsutil before running command.
    CONFIG_REQUIRED : True,
  }
  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'rm',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['del', 'delete', 'remove'],
    # Type of help:
    HELP_TYPE : HelpType.COMMAND_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Remove objects',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }

  # Command entry point.
  def RunCommand(self):
    # self.recursion_requested initialized in command.py (so can be checked
    # in parent class for all commands).
    continue_on_error = False
    if self.sub_opts:
      for o, unused_a in self.sub_opts:
        if o == '-f':
          continue_on_error = True
        elif o == '-r' or o == '-R':
          self.recursion_requested = True

    # Used to track if any files failed to be removed.
    self.everything_removed_okay = True

    def _RemoveExceptionHandler(e):
      """Simple exception handler to allow post-completion status."""
      self.THREADED_LOGGER.error(str(e))
      self.everything_removed_okay = False

    def _RemoveFunc(src_uri, exp_src_uri, _unused_src_uri_names_container,
                    _unused_src_uri_expands_to_multi,
                    _unused_have_multiple_srcs,
                    _unused_have_existing_dest_subdir):
      if exp_src_uri.names_container():
        if exp_src_uri.is_cloud_uri():
          # Before offering advice about how to do rm + rb, ensure those
          # commands won't fail because of bucket naming problems.
          boto.s3.connection.check_lowercase_bucketname(exp_src_uri.bucket_name)
        uri_str = exp_src_uri.object_name.rstrip('/')
        raise CommandException('"rm" command will not remove buckets. To '
                               'delete this/these bucket(s) do:\n\tgsutil rm '
                               '%s/*\n\tgsutil rb %s' % (uri_str, uri_str))
      self.THREADED_LOGGER.info('Removing %s...', exp_src_uri)
      try:
        exp_src_uri.delete_key(validate=False, headers=self.headers)
      except:
        if continue_on_error:
          self.everything_removed_okay = False
        else:
          raise

    # Expand wildcards, dirs, buckets, and bucket subdirs in URIs.
    src_uri_expansion = self.exp_handler.ExpandWildcardsAndContainers(
        self.args, self.recursion_requested, flat=self.recursion_requested)
    if src_uri_expansion.IsEmpty():
      raise CommandException('No URIs matched')

    # Perform remove requests in parallel (-m) mode, if requested, using
    # configured number of parallel processes and threads. Otherwise,
    # perform requests with sequential function calls in current process.
    self.Apply(_RemoveFunc, src_uri_expansion, _RemoveExceptionHandler)

    if not self.everything_removed_okay:
      raise CommandException('Some files could not be removed.')
