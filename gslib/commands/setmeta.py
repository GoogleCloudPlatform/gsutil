# Copyright 2012 Google Inc. All Rights Reserved.
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
"""Implementation of setmeta command for setting cloud object metadata."""

from gslib.cloud_api import AccessDeniedException
from gslib.cloud_api import PreconditionException
from gslib.cloud_api import Preconditions
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
from gslib.name_expansion import NameExpansionIterator
from gslib.storage_url import StorageUrlFromString
from gslib.translation_helper import CopyObjectMetadata
from gslib.translation_helper import ObjectMetadataFromHeaders
from gslib.util import GetCloudApiInstance
from gslib.util import NO_MAX
from gslib.util import Retry


_detailed_help_text = ("""
<B>SYNOPSIS</B>
    gsutil setmeta [-n] -h [header:value|header] ... url...


<B>DESCRIPTION</B>
  The gsutil setmeta command allows you to set or remove the metadata on one
  or more objects. It takes one or more header arguments followed by one or
  more URLs, where each header argument is in one of two forms:

  - if you specify header:value, it will set the given header on all
    named objects.

  - if you specify header (with no value), it will remove the given header
    from all named objects.

  For example, the following command would set the Content-Type and
  Cache-Control and remove the Content-Disposition on the specified objects:

    gsutil setmeta -h "Content-Type:text/html" \\
      -h "Cache-Control:public, max-age=3600" \\
      -h "Content-Disposition" gs://bucket/*.html

  If you have a large number of objects to update you might want to use the
  gsutil -m option, to perform a parallel (multi-threaded/multi-processing)
  update:

    gsutil -m setmeta -h "Content-Type:text/html" \\
      -h "Cache-Control:public, max-age=3600" \\
      -h "Content-Disposition" gs://bucket/*.html

  See "gsutil help metadata" for details about how you can set metadata
  while uploading objects, what metadata fields can be set and the meaning of
  these fields, use of custom metadata, and how to view currently set metadata.

  NOTE: By default, publicly readable objects are served with a Cache-Control
  header allowing such objects to be cached for 3600 seconds. If you need to
  ensure that updates become visible immediately, you should set a Cache-Control
  header of "Cache-Control:private, max-age=0, no-transform" on such objects.
  You can do this with the command:

    gsutil setmeta -h "Content-Type:text/html" \\
      -h "Cache-Control:private, max-age=0, no-transform" gs://bucket/*.html


<B>OPERATION COST</B>
  This command uses four operations per URL (one to read the ACL, one to read
  the current metadata, one to set the new metadata, and one to set the ACL).

  For cases where you want all objects to have the same ACL you can avoid half
  these operations by setting a default ACL on the bucket(s) containing the
  named objects, and using the setmeta -n option. See "help gsutil defacl".


<B>OPTIONS</B>
  -h          Specifies a header:value to be added, or header to be removed,
              from each named object.
  -n          Causes the operations for reading and writing the ACL to be
              skipped. This halves the number of operations performed per
              request, improving the speed and reducing the cost of performing
              the operations. This option makes sense for cases where you want
              all objects to have the same ACL, for which you have set a default
              ACL on the bucket(s) containing the objects. See "help gsutil
              defacl".
""")

# Setmeta assumes a header-like model which doesn't line up with the JSON way
# of doing things. This list comes from functionality that was supported by
# gsutil3 at the time gsutil4 was released.
SETTABLE_FIELDS = ['cache-control', 'content-disposition',
                   'content-encoding', 'content-language',
                   'content-md5', 'content-type']


def _SetMetadataExceptionHandler(cls, e):
  """Exception handler that maintains state about post-completion status."""
  cls.logger.error(e)
  cls.everything_set_okay = False


def _SetMetadataFuncWrapper(cls, name_expansion_result, thread_state=None):
  cls.SetMetadataFunc(name_expansion_result, thread_state=thread_state)


class SetMetaCommand(Command):
  """Implementation of gsutil setmeta command."""

  # Command specification (processed by parent class).
  command_spec = {
      # Name of command.
      COMMAND_NAME: 'setmeta',
      # List of command name aliases.
      COMMAND_NAME_ALIASES: ['setheader'],
      # Min number of args required by this command.
      MIN_ARGS: 1,
      # Max number of args required by this command, or NO_MAX.
      MAX_ARGS: NO_MAX,
      # Getopt-style string specifying acceptable sub args.
      SUPPORTED_SUB_ARGS: 'h:nrR',
      # True if file URLs acceptable for this command.
      FILE_URLS_OK: False,
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
      HELP_NAME: 'setmeta',
      # List of help name aliases.
      HELP_NAME_ALIASES: ['setheader'],
      # Type of help:
      HELP_TYPE: HelpType.COMMAND_HELP,
      # One line summary of this help.
      HELP_ONE_LINE_SUMMARY: 'Set metadata on already uploaded objects',
      # The full help text.
      HELP_TEXT: _detailed_help_text,
  }

  def RunCommand(self):
    """Command entry point for the setmeta command."""
    headers = []
    if self.sub_opts:
      for o, a in self.sub_opts:
        if o == '-n':
          self.logger.warning(
              'Warning: gsutil setmeta -n is now on by default, and will be '
              'removed in the future.\nPlease use gsutil acl set ... to set '
              'canned ACLs.')
        elif o == '-h':
          if 'x-goog-acl' in a:
            raise CommandException(
                'gsutil setmeta no longer allows canned ACLs. Use gsutil acl '
                'set ... to set canned ACLs.')
          headers.append(a)

    (metadata_minus, metadata_plus) = self._ParseMetadataHeaders(headers)

    self.metadata_change = metadata_plus
    for header in metadata_minus:
      self.metadata_change[header] = ''

    if len(self.args) == 1 and not self.recursion_requested:
      url = StorageUrlFromString(self.args[0])
      if not (url.IsCloudUrl() and url.IsObject()):
        raise CommandException('URL (%s) must name an object' % self.args[0])

    # Used to track if any objects' metadata failed to be set.
    self.everything_set_okay = True

    name_expansion_iterator = NameExpansionIterator(
        self.command_name, self.debug, self.logger, self.gsutil_api,
        self.args, self.recursion_requested, all_versions=self.all_versions)

    try:
      # Perform requests in parallel (-m) mode, if requested, using
      # configured number of parallel processes and threads. Otherwise,
      # perform requests with sequential function calls in current process.
      self.Apply(_SetMetadataFuncWrapper, name_expansion_iterator,
                 _SetMetadataExceptionHandler, fail_on_error=True)
    except AccessDeniedException as e:
      if e.status == 403:
        self._WarnServiceAccounts()
      raise

    if not self.everything_set_okay:
      raise CommandException('Metadata for some objects could not be set.')

    return 0

  @Retry(PreconditionException, tries=3, timeout_secs=1)
  def SetMetadataFunc(self, name_expansion_result, thread_state=None):
    """Sets metadata on an object.

    Args:
      name_expansion_result: NameExpansionResult describing target object.
      thread_state: gsutil Cloud API instance to use for the operation.
    """
    gsutil_api = GetCloudApiInstance(self, thread_state=thread_state)

    exp_src_url = StorageUrlFromString(
        name_expansion_result.GetExpandedUrlStr())
    self.logger.info('Setting metadata on %s...', exp_src_url)

    fields = ['generation', 'metadata', 'metageneration']
    cloud_obj_metadata = gsutil_api.GetObjectMetadata(
        exp_src_url.bucket_name, exp_src_url.object_name,
        generation=exp_src_url.generation, provider=exp_src_url.scheme,
        fields=fields)

    preconditions = Preconditions(
        gen_match=cloud_obj_metadata.generation,
        meta_gen_match=cloud_obj_metadata.metageneration)

    # Patch handles the patch semantics for most metadata, but we need to
    # merge the custom metadata field manually.
    patch_obj_metadata = ObjectMetadataFromHeaders(self.metadata_change)

    api = gsutil_api.GetApiSelector(provider=exp_src_url.scheme)
    # For XML we only want to patch through custom metadata that has
    # changed.  For JSON we need to build the complete set.
    if api == ApiSelector.XML:
      pass
    elif api == ApiSelector.JSON:
      CopyObjectMetadata(patch_obj_metadata, cloud_obj_metadata,
                         override=True)
      patch_obj_metadata = cloud_obj_metadata

    gsutil_api.PatchObjectMetadata(
        exp_src_url.bucket_name, exp_src_url.object_name, patch_obj_metadata,
        generation=exp_src_url.generation, preconditions=preconditions,
        provider=exp_src_url.scheme)

  def _ParseMetadataHeaders(self, headers):
    """Validates and parses metadata changes from the headers argument.

    Args:
      headers: Header dict to validate and parse.

    Returns:
      (metadata_plus, metadata_minus): Tuple of header sets to add and remove.
    """
    metadata_minus = set()
    cust_metadata_minus = set()
    metadata_plus = {}
    cust_metadata_plus = {}
    # Build a count of the keys encountered from each plus and minus arg so we
    # can check for dupe field specs.
    num_metadata_plus_elems = 0
    num_cust_metadata_plus_elems = 0
    num_metadata_minus_elems = 0
    num_cust_metadata_minus_elems = 0

    for md_arg in headers:
      parts = md_arg.split(':')
      if len(parts) not in (1, 2):
        raise CommandException(
            'Invalid argument: must be either header or header:value (%s)' %
            md_arg)
      if len(parts) == 2:
        (header, value) = parts
      else:
        (header, value) = (parts[0], None)
      _InsistAsciiHeader(header)
      # Translate headers to lowercase to match the casing assumed by our
      # sanity-checking operations.
      header = header.lower()
      if value:
        if _IsCustomMeta(header):
          # Allow non-ASCII data for custom metadata fields.
          cust_metadata_plus[header] = value
          num_cust_metadata_plus_elems += 1
        else:
          # Don't unicode encode other fields because that would perturb their
          # content (e.g., adding %2F's into the middle of a Cache-Control
          # value).
          _InsistAsciiHeaderValue(header, value)
          value = str(value)
          metadata_plus[header] = value
          num_metadata_plus_elems += 1
      else:
        if _IsCustomMeta(header):
          cust_metadata_minus.add(header)
          num_cust_metadata_minus_elems += 1
        else:
          metadata_minus.add(header)
          num_metadata_minus_elems += 1

    if (num_metadata_plus_elems != len(metadata_plus)
        or num_cust_metadata_plus_elems != len(cust_metadata_plus)
        or num_metadata_minus_elems != len(metadata_minus)
        or num_cust_metadata_minus_elems != len(cust_metadata_minus)
        or metadata_minus.intersection(set(metadata_plus.keys()))):
      raise CommandException('Each header must appear at most once.')
    other_than_base_fields = (set(metadata_plus.keys())
                              .difference(SETTABLE_FIELDS))
    other_than_base_fields.update(
        metadata_minus.difference(SETTABLE_FIELDS))
    for f in other_than_base_fields:
      # This check is overly simple; it would be stronger to check, for each
      # URL argument, whether f.startswith the
      # provider metadata_prefix, but here we just parse the spec
      # once, before processing any of the URLs. This means we will not
      # detect if the user tries to set an x-goog-meta- field on an another
      # provider's object, for example.
      if not _IsCustomMeta(f):
        raise CommandException(
            'Invalid or disallowed header (%s).\nOnly these fields (plus '
            'x-goog-meta-* fields) can be set or unset:\n%s' % (
                f, sorted(list(SETTABLE_FIELDS))))
    metadata_plus.update(cust_metadata_plus)
    metadata_minus.update(cust_metadata_minus)
    return (metadata_minus, metadata_plus)


def _InsistAscii(string, message):
  if not all(ord(c) < 128 for c in string):
    raise CommandException(message)


def _InsistAsciiHeader(header):
  _InsistAscii(header, 'Invalid non-ASCII header (%s).' % header)


def _InsistAsciiHeaderValue(header, value):
  _InsistAscii(
      value, ('Invalid non-ASCII value (%s) was provided for header %s.'
              % (value, header)))


def _IsCustomMeta(header):
  return header.startswith('x-goog-meta-') or header.startswith('x-amz-meta-')
