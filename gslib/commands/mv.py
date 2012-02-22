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
from gslib.wildcard_iterator import ContainsWildcard

_detailed_help_text = ("""
gsutil mv [-p] [-R] src_uri dst_uri
  - or -
gsutil mv [-p] [-R] uri... dst_uri

  -R Causes directories, buckets, and bucket subdirs to be moved recursively.

  -p option causes ACL to be preserved when copying in the cloud. Causes
  extra API calls.
""")


class MvCommand(Command):
  """Implementation of gsutil mv command.
     Note that there is no atomic rename operation - this command is simply
     a shorthand for 'cp' followed by 'rm'.
  """

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'mv',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : ['move', 'rename'],
    # Min number of args required by this command.
    MIN_ARGS : 2,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : NO_MAX,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : 'prR',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : True,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 0,
    # True if must configure gsutil before running command.
    CONFIG_REQUIRED : True,
  }
  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'mv',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['move', 'rename'],
    # Type of help)
    HELP_TYPE : HelpType.COMMAND_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Move/rename objects',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }

  # Command entry point.
  def RunCommand(self):
    # self.recursion_requested initialized in command.py (so can be checked
    # in parent class for all commands).
    if self.sub_opts:
      for o, unused_a in self.sub_opts:
        if o == '-r' or o == '-R':
          self.recursion_requested = True

    # Check each source arg up, refusing to delete a bucket or directory src
    # URI (force users to explicitly do that as a separate operation).
    for arg_to_check in self.args[0:-1]:
      if self.suri_builder.StorageUri(arg_to_check).names_container():
        raise CommandException('Will not remove source buckets or directories '
                               '(%s).\nYou must separately copy and remove for '
                               'that purpose.' % arg_to_check)

    # Disallow recursive request (-r) with a wildcard src URI. Allowing
    # this would make the name transformation too hairy and is too dangerous
    # (e.g., someone could accidentally move many objects to the wrong name,
    # or accidentally overwrite many objects).
    if self.recursion_requested:
      for src_uri in self.args[0:len(self.args)-1]:
        if ContainsWildcard(src_uri):
          raise CommandException(
              'source URI cannot contain wildcards with mv -r')

    # Expand wildcards, dirs, buckets, and bucket subdirs in StorageUris
    # before running cp and rm commands, to prevent the
    # following problem: starting with a bucket containing only the object
    # gs://bucket/obj, say the user does:
    #   gsutil mv gs://bucket/* gs://bucket/d.txt
    # If we didn't expand the wildcard first, the cp command would
    # first copy gs://bucket/obj to gs://bucket/d.txt, and the
    # rm command would then remove that object.
    # Note that this makes for somewhat less efficient operation, since we first
    # do bucket listing operations here, then again in the underlying cp
    # command.
    # TODO: consider adding an internal interface to cp command to allow this
    # expansion to be passed in.
    src_uri_expansion = self.exp_handler.ExpandWildcardsAndContainers(
        self.args[0:len(self.args)-1])
    exp_arg_list = list(src_uri_expansion.IterExpandedUriStrings())

    # Check whether exp_arg_list has any file:// URIs, and disallow it. Note
    # that we can't simply set FILE_URIS_OK to False in command_spec because
    # we *do* allow a file URI for the dest URI. (We allow users to move data
    # out of the cloud to the local disk, but we disallow commands that would
    # delete data off the local disk, and instead require the user to delete
    # data separately, using local commands/tools.)
    if self.HaveFileUris(exp_arg_list):
      raise CommandException('"mv" command does not support "file://" URIs for '
                             'source arguments.\nDid you mean to use a '
                             'gs:// URI?')

    if src_uri_expansion.IsEmpty():
      raise CommandException('No URIs matched')

    # Add command-line opts back in front of args so they'll be picked up by cp
    # and rm commands (e.g., for -r option). Use undocumented (internal
    # use-only) cp -M option to request move naming semantics (see
    # _ConstructDstUri in cp.py).
    unparsed_args = ['-M']
    unparsed_args.extend(self.unparsed_args)
    self.command_runner.RunNamedCommand('cp', unparsed_args, self.headers,
                                        self.debug, self.parallel_operations)
    # See comment above about why we're passing exp_arg_list instead of
    # unparsed_args here.
    self.command_runner.RunNamedCommand('rm', exp_arg_list,
                                        self.headers, self.debug,
                                        self.parallel_operations)

  # test specification, see definition of test_steps in base class for
  # details on how to populate these fields
  test_steps = [
    # (test name, cmd line, ret code, (result_file, expect_file))
    ('gen expect files', 'echo 0 >$F0; echo 1 >$F1; echo 2 >$F2', 0, None),
    ('verify 2 src objs', 'gsutil ls gs://$B2 | wc -l >$F9', 0, ('$F9', '$F2')),
    ('verify 0 dst objs', 'gsutil ls gs://$B0 | wc -l >$F9', 0, ('$F9', '$F0')),
    ('mv 2 objects',
       'gsutil -m mv gs://$B2/$O0 gs://$B2/$O1 gs://$B0 2>&1 | grep Removing',
       0, None),
    ('verify 0 src objs', 'gsutil ls gs://$B2 | wc -l >$F9', 0, ('$F9', '$F0')),
    ('verify 2 dst objs', 'gsutil ls gs://$B0 | wc -l >$F9', 0, ('$F9', '$F2')),
    ('rm 1 src object', 'gsutil rm gs://$B0/$O0', 0, None),
    ('verify 1 src obj', 'gsutil ls gs://$B0 | wc -l >$F9', 0, ('$F9', '$F1')),
    ('verify 0 dst objs', 'gsutil ls gs://$B2 | wc -l >$F9', 0, ('$F9', '$F0')),
    ('mv 2 objects',
       'gsutil -m mv gs://$B0/$O0 gs://$B0/$O1 gs://$B2 2>&1 | grep Removing',
       1, None),
  ]

