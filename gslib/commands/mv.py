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
"""Implementation of Unix-like mv command for cloud storage providers."""

from gslib.command import Command
from gslib.commands.cp import CP_SUB_ARGS
from gslib.cs_api_map import ApiSelector
from gslib.exception import CommandException
from gslib.storage_url import StorageUrlFromString
from gslib.util import NO_MAX

_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil mv [-p] src_url dst_url
  gsutil mv [-p] url... dst_url


<B>DESCRIPTION</B>
  The gsutil mv command allows you to move data between your local file
  system and the cloud, move data within the cloud, and move data between
  cloud storage providers. For example, to move all objects from a
  bucket to a local directory you could use:

    gsutil mv gs://my_bucket dir

  Similarly, to move all objects from a local directory to a bucket you could
  use:

    gsutil mv ./dir gs://my_bucket


<B>RENAMING BUCKET SUBDIRECTORIES</B>
  You can use the gsutil mv command to rename subdirectories. For example,
  the command:

    gsutil mv gs://my_bucket/olddir gs://my_bucket/newdir

  would rename all objects and subdirectories under gs://my_bucket/olddir to be
  under gs://my_bucket/newdir, otherwise preserving the subdirectory structure.

  If you do a rename as specified above and you want to preserve ACLs, you
  should use the -p option (see OPTIONS).

  Note that when using mv to rename bucket subdirectories you cannot specify
  the source URL using wildcards. You need to spell out the complete name:

    gsutil mv gs://my_bucket/olddir gs://my_bucket/newdir

  If you have a large number of files to move you might want to use the
  gsutil -m option, to perform a multi-threaded/multi-processing move:

    gsutil -m mv gs://my_bucket/olddir gs://my_bucket/newdir


<B>NON-ATOMIC OPERATION</B>
  Unlike the case with many file systems, the gsutil mv command does not
  perform a single atomic operation. Rather, it performs a copy from source
  to destination followed by removing the source for each object.


<B>OPTIONS</B>
  All options that are available for the gsutil cp command are also available
  for the gsutil mv command (except for the -R flag, which is implied by the
  gsutil mv command). Please see the OPTIONS sections of "gsutil help cp"
  for more information.

""")


class MvCommand(Command):
  """Implementation of gsutil mv command.

     Note that there is no atomic rename operation - this command is simply
     a shorthand for 'cp' followed by 'rm'.
  """

  # Command specification. See base class for documentation.
  command_spec = Command.CreateCommandSpec(
      'mv',
      command_name_aliases=['move', 'ren', 'rename'],
      min_args=2,
      max_args=NO_MAX,
      # Flags for mv are passed through to cp.
      supported_sub_args=CP_SUB_ARGS,
      file_url_ok=True,
      provider_url_ok=False,
      urls_start_arg=0,
      gs_api_support=[ApiSelector.XML, ApiSelector.JSON],
      gs_default_api=ApiSelector.JSON,
  )
  # Help specification. See help_provider.py for documentation.
  help_spec = Command.HelpSpec(
      help_name='mv',
      help_name_aliases=['move', 'rename'],
      help_type='command_help',
      help_one_line_summary='Move/rename objects and/or subdirectories',
      help_text=_detailed_help_text,
      subcommand_help_text={},
  )

  def RunCommand(self):
    """Command entry point for the mv command."""
    # Check each source arg up, refusing to delete a bucket src URL (force users
    # to explicitly do that as a separate operation).
    for arg_to_check in self.args[0:-1]:
      url = StorageUrlFromString(arg_to_check)
      if url.IsCloudUrl() and (url.IsBucket() or url.IsProvider()):
        raise CommandException('You cannot move a source bucket using the mv '
                               'command. If you meant to move\nall objects in '
                               'the bucket, you can use a command like:\n'
                               '\tgsutil mv %s/* %s' %
                               (arg_to_check, self.args[-1]))

    # Insert command-line opts in front of args so they'll be picked up by cp
    # and rm commands (e.g., for -p option). Use undocumented (internal
    # use-only) cp -M option, which causes each original object to be deleted
    # after successfully copying to its destination, and also causes naming
    # behavior consistent with Unix mv naming behavior (see comments in
    # ConstructDstUrl).
    unparsed_args = ['-M']
    if self.recursion_requested:
      unparsed_args.append('-R')
    unparsed_args.extend(self.unparsed_args)
    self.command_runner.RunNamedCommand('cp', unparsed_args, self.headers,
                                        self.debug, self.parallel_operations)

    return 0
