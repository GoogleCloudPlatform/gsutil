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
"""Implementation of compose command for Google Cloud Storage."""

from gslib.bucket_listing_ref import BucketListingRef
from gslib.bucket_listing_ref import BucketListingRefType
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
from gslib.storage_url import ContainsWildcard
from gslib.storage_url import StorageUrlFromString
from gslib.third_party.storage_apitools import storage_v1beta2_messages as apitools_messages
from gslib.translation_helper import PreconditionsFromHeaders

MAX_COMPONENT_COUNT = 1024
MAX_COMPOSE_ARITY = 32

_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil compose gs://bucket/obj1 gs://bucket/obj2 ... gs://bucket/composite


<B>DESCRIPTION</B>
  The compose command creates a new object whose content is the concatenation
  of a given sequence of component objects under the same bucket. gsutil uses
  the content type of the first source object to determine the destination
  object's content type. For more information, please see:
  https://developers.google.com/storage/docs/composite-objects

  Note also that the gsutil cp command will automatically split uploads for
  large files into multiple component objects, upload them in parallel, and
  compose them into a final object (which will be subject to the component
  count limit). This will still perform all uploads from a single machine. For
  extremely large files and/or very low per-machine bandwidth, you may want to
  split the file and upload it from multiple machines, and later compose these
  parts of the file manually. See the 'PARALLEL COMPOSITE UPLOADS' section under
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
      COMMAND_NAME: 'compose',
      # List of command name aliases.
      COMMAND_NAME_ALIASES: ['concat'],
      # Min number of args required by this command.
      MIN_ARGS: 2,
      # Max number of args required by this command, or NO_MAX.
      MAX_ARGS: MAX_COMPOSE_ARITY + 1,
      # Getopt-style string specifying acceptable sub args.
      SUPPORTED_SUB_ARGS: '',
      # True if file URLs acceptable for this command.
      FILE_URLS_OK: False,  # Not files, just object names without gs:// prefix.
      # True if provider-only URLs acceptable for this command.
      PROVIDER_URLS_OK: False,
      # Index in args of first URL arg.
      URLS_START_ARG: 1,
      # List of supported APIs
      CommandSpecKey.GS_API_SUPPORT: [ApiSelector.XML, ApiSelector.JSON],
      # Default API to use for this command
      CommandSpecKey.GS_DEFAULT_API: ApiSelector.JSON,
  }
  help_spec = {
      # Name of command or auxiliary help info for which this help applies.
      HELP_NAME: 'compose',
      # List of help name aliases.
      HELP_NAME_ALIASES: ['concat'],
      # Type of help)
      HELP_TYPE: HelpType.COMMAND_HELP,
      # One line summary of this help.
      HELP_ONE_LINE_SUMMARY: (
          'Concatenate a sequence of objects into a new composite object.'),
      # The full help text.
      HELP_TEXT: _detailed_help_text,
  }

  def CheckProvider(self, uri):
    if uri.scheme != 'gs':
      raise CommandException(
          '"compose" called on URI with unsupported provider (%s).' % str(uri))

  # Command entry point.
  def RunCommand(self):
    """Command entry point for the compose command."""
    target_uri_str = self.args[-1]
    self.args = self.args[:-1]
    target_uri = StorageUrlFromString(target_uri_str)
    self.CheckProvider(target_uri)
    if target_uri.HasGeneration():
      raise CommandException('A version-specific URI (%s) cannot be '
                             'the destination for gsutil compose - abort.'
                             % target_uri)

    dst_obj_metadata = apitools_messages.Object(name=target_uri.object_name,
                                                bucket=target_uri.bucket_name)

    components = []
    # Remember the first source object so we can get its content type.
    first_src_uri = None
    for src_uri_str in self.args:
      if ContainsWildcard(src_uri_str):
        src_uri_iter = self.WildcardIterator(src_uri_str).IterObjects()
      else:
        src_uri_iter = [BucketListingRef(src_uri_str,
                                         BucketListingRefType.OBJECT)]
      for blr in src_uri_iter:
        src_uri = StorageUrlFromString(blr.GetUrlString())
        self.CheckProvider(src_uri)

        if src_uri.bucket_name != target_uri.bucket_name:
          raise CommandException(
              'GCS does not support inter-bucket composing.')

        if not first_src_uri:
          first_src_uri = src_uri
        src_obj_metadata = (
            apitools_messages.ComposeRequest.SourceObjectsValueListEntry(
                name=src_uri.object_name))
        if src_uri.HasGeneration():
          src_obj_metadata.generation = src_uri.generation
        components.append(src_obj_metadata)
        # Avoid expanding too many components, and sanity check each name
        # expansion result.
        if len(components) > MAX_COMPOSE_ARITY:
          raise CommandException('"compose" called with too many component '
                                 'objects. Limit is %d.' % MAX_COMPOSE_ARITY)

    if len(components) < 2:
      raise CommandException('"compose" requires at least 2 component objects.')

    dst_obj_metadata.contentType = self.gsutil_api.GetObjectMetadata(
        first_src_uri.bucket_name, first_src_uri.object_name,
        provider=first_src_uri.scheme, fields=['contentType']).contentType

    preconditions = PreconditionsFromHeaders(self.headers or {})

    self.logger.info(
        'Composing %s from %d component objects.' %
        (target_uri, len(components)))
    self.gsutil_api.ComposeObject(components, dst_obj_metadata,
                                  preconditions=preconditions,
                                  provider=target_uri.scheme)
