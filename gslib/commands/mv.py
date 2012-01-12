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
from gslib.exception import ProjectIdException
from gslib import wildcard_iterator
from gslib.util import NO_MAX
from gslib.wildcard_iterator import ContainsWildcard

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
    SUPPORTED_SUB_ARGS : 'p',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : True,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 0,
    # True if must configure gsutil before running command.
    CONFIG_REQUIRED : True,
  }

  # Command entry point.
  def RunCommand(self):
    # Refuse to delete a bucket or directory src URI (force users to explicitly
    # do that as a separate operation).
    src_uri_to_check = self.StorageUri(self.args[0])
    if src_uri_to_check.names_container():
      raise CommandException('Will not remove source buckets or directories. '
                             'You must separately copy and remove for that '
                             'purpose.')

    if len(self.args) > 2:
      self.InsistUriNamesContainer(self.StorageUri(self.args[-1]),
                                   self.command_name)

    # Expand wildcards before calling CopyObjsCommand and RemoveObjsCommand,
    # to prevent the following problem: starting with a bucket containing
    # only the object gs://bucket/obj, say the user does:
    #   gsutil mv gs://bucket/* gs://bucket/d.txt
    # If we didn't expand the wildcard first, the CopyObjsCommand would
    # first copy gs://bucket/obj to gs://bucket/d.txt, and the
    # RemoveObjsCommand would then remove that object.
    exp_arg_list = []
    for uri_str in self.args:
      uri = self.StorageUri(uri_str)
      if ContainsWildcard(uri_str):
        exp_arg_list.extend(str(u) for u in list(self.CmdWildcardIterator(uri)))
      else:
        exp_arg_list.append(uri.uri)

    self.command_runner.RunNamedCommand('cp', exp_arg_list, self.headers,
                                          self.debug, self.parallel_operations)
    self.command_runner.RunNamedCommand('rm', exp_arg_list[0:-1],
                                          self.headers, self.debug,
                                          self.parallel_operations)
