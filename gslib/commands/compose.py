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

from gslib.command import Command
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
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
from gslib.name_expansion import NameExpansionIterator
from boto import storage_uri_for_key

MAX_COMPONENT_COUNT = 1024
MAX_COMPOSE_ARITY = 32

_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil compose gs://bucket/obj1 gs://bucket/obj2 ... gs://bucket/composite


<B>DESCRIPTION</B>
  The compose command creates a new object whose content is the concatenation
  of a given sequence of component objects under the same bucket. This is useful
  for parallel uploading and limited append functionality. For more information,
  please see: https://developers.google.com/storage/docs/composite-objects

  To upload in parallel, split your file into smaller pieces, upload them using
  "gsutil -m cp", compose the results, and delete the pieces:

    $ split -n 10 big-file big-file-part-
    $ gsutil -m cp big-file-part-* gs://bucket/dir/
    $ rm big-file-part-*
    $ gsutil compose gs://bucket/dir/big-file-part-* gs://bucket/dir/big-file
    $ gsutil -m rm gs://bucket/dir/big-file-part-*

  Note: The above example causes all file parts to be uploaded from a single
  disk on a single machine, which could result in disk or CPU bottlenecks.
  Especially when working with very large files, you may be able to achieve
  higher performance by spreading the files across multiple disks and/or
  running the parallel upload from multiple machines.

  Note also that the gsutil cp command will automatically split uploads for
  large files into multiple component objects, upload them in parallel, and
  compose them into a final object (which will also be subject to the component
  count limit). See the 'PARALLEL COMPOSITE UPLOADS'" section under
  'gsutil help cp' for details.

  Appending simply entails uploading your new data to a temporary object,
  composing it with the growing append-target, and deleting the temporary
  object:

    $ echo 'new data' | gsutil cp - gs://bucket/data-to-append
    $ gsutil compose gs://bucket/append-target gs://bucket/data-to-append \\
        gs://bucket/append-target
    $ gsutil rm gs://bucket/data-to-append

  Note that there is a limit (currently %d) to the number of components for a
  given composite object. This means you can append to each object at most %d
  times.
""" % (MAX_COMPONENT_COUNT, MAX_COMPONENT_COUNT - 1))

class ComposeCommand(Command):
  """Implementation of gsutil compose command."""

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'compose',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : ['concat'],
    # Min number of args required by this command.
    MIN_ARGS : 2,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : MAX_COMPOSE_ARITY + 1,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : '',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : False,  # Not files, just object names without gs:// prefix.
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 1,
  }
  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'compose',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['concat'],
    # Type of help)
    HELP_TYPE : HelpType.COMMAND_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : (
        'Concatenate a sequence of objects into a new composite object.'),
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }

  def CheckSUriProvider(self, suri):
    if suri.get_provider().name != 'google':
      raise CommandException(
          '"compose" called on URI with unsupported provider (%s).' % str(suri))

  # Command entry point.
  def RunCommand(self):
    target_uri = self.args[-1]
    self.args = self.args[:-1]
    target_suri = self.suri_builder.StorageUri(target_uri)
    self.CheckSUriProvider(target_suri)
    if target_suri.is_version_specific:
      raise CommandException('A version-specific URI\n(%s)\ncannot be '
                             'the destination for gsutil compose - abort.'
                              % target_suri)

    name_expansion_iterator = NameExpansionIterator(
        self.command_name, self.proj_id_handler, self.headers, self.debug,
        self.logger, self.bucket_storage_uri_class, self.args, False,
        cmd_supports_recursion=False)
    components = []
    for ne_result in name_expansion_iterator:
      suri = self.suri_builder.StorageUri(ne_result.GetExpandedUriStr())
      self.CheckSUriProvider(suri)
      components.append(suri)
      # Avoid expanding too many components, and sanity check each name
      # expansion result.
      if len(components) > MAX_COMPOSE_ARITY:
        raise CommandException('"compose" called with too many component '
                               'objects. Limit is %d.' % MAX_COMPOSE_ARITY)
    if len(components) < 2:
      raise CommandException('"compose" requires at least 2 component objects.')

    self.logger.info(
        'Composing %s from %d component objects.' %
        (target_suri, len(components)))
    target_suri.compose(components, headers=self.headers)
