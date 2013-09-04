# Copyright 2012 Google Inc. All Rights Reserved.
#coding=utf8
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
import csv
import random
import StringIO
import time

from boto.exception import GSResponseError
from boto.s3.key import Key
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.command import Command
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
from gslib.help_provider import HELP_TYPE
from gslib.help_provider import HelpType
from gslib.name_expansion import NameExpansionIterator
from gslib.util import NO_MAX
from gslib.util import Retry

_detailed_help_text = ("""
<B>SYNOPSIS</B>
    gsutil setmeta [-n] -h [header:value|header] ... uri...


<B>DESCRIPTION</B>
  The gsutil setmeta command allows you to set or remove the metadata on one
  or more objects. It takes one or more header arguments followed by one or
  more URIs, where each header argument is in one of two forms:

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
  This command uses four operations per URI (one to read the ACL, one to read
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


class SetMetaCommand(Command):
  """Implementation of gsutil setmeta command."""

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'setmeta',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : ['setheader'],
    # Min number of args required by this command.
    MIN_ARGS : 1,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : NO_MAX,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : 'h:n',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : False,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 1,
  }
  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'setmeta',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['setheader'],
    # Type of help:
    HELP_TYPE : HelpType.COMMAND_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Set metadata on already uploaded objects',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }

  # Command entry point.
  def RunCommand(self):
    headers = []
    preserve_acl = True
    if self.sub_opts:
      for o, a in self.sub_opts:
        if o == '-n':
          preserve_acl = False
        elif o == '-h':
          headers.append(a)

    (metadata_minus, metadata_plus) = self._ParseMetadataHeaders(headers)

    if (len(self.args) == 1
        and not self.suri_builder.StorageUri(self.args[0]).names_object()):
      raise CommandException('URI (%s) must name an object' % self.args[0])

    # Used to track if any objects' metadata failed to be set.
    self.everything_set_okay = True

    def _SetMetadataExceptionHandler(e):
      """Simple exception handler to allow post-completion status."""
      self.logger.error(str(e))
      self.everything_set_okay = False

    @Retry(GSResponseError, tries=3, timeout_secs=1)
    def _SetMetadataFunc(name_expansion_result):
      exp_src_uri = self.suri_builder.StorageUri(
          name_expansion_result.GetExpandedUriStr())
      self.logger.info('Setting metadata on %s...', exp_src_uri)

      key = exp_src_uri.get_key()
      metageneration = getattr(key, 'metageneration', None)
      generation = getattr(key, 'generation', None)

      headers = {}
      if generation:
        headers['x-goog-if-generation-match'] = generation
      if metageneration:
        headers['x-goog-if-metageneration-match'] = metageneration

      # If this fails because of a precondition, it will raise a
      # GSResponseError for @Retry to handle.
      exp_src_uri.set_metadata(metadata_plus, metadata_minus, preserve_acl,
                                 headers=headers)

    name_expansion_iterator = NameExpansionIterator(
        self.command_name, self.proj_id_handler, self.headers, self.debug,
        self.logger, self.bucket_storage_uri_class, self.args,
        self.recursion_requested, self.recursion_requested)

    try:
      # Perform requests in parallel (-m) mode, if requested, using
      # configured number of parallel processes and threads. Otherwise,
      # perform requests with sequential function calls in current process.
      self.Apply(_SetMetadataFunc, name_expansion_iterator,
                 _SetMetadataExceptionHandler)
    except GSResponseError as e:
      if e.code == 'AccessDenied' and e.reason == 'Forbidden' \
          and e.status == 403:
        self._WarnServiceAccounts()
      raise

    if not self.everything_set_okay:
      raise CommandException('Metadata for some objects could not be set.')

    return 0

  def _ParseMetadataHeaders(self, headers):
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
        .difference(Key.base_user_settable_fields))
    other_than_base_fields.update(
        metadata_minus.difference(Key.base_user_settable_fields))
    for f in other_than_base_fields:
      # This check is overly simple; it would be stronger to check, for each
      # URI argument, whether f.startswith the
      # uri.get_provider().metadata_prefix, but here we just parse the spec
      # once, before processing any of the URIs. This means we will not
      # detect if the user tries to set an x-goog-meta- field on an another
      # provider's object, for example.
      if not _IsCustomMeta(f):
        raise CommandException('Invalid or disallowed header (%s).\n'
                               'Only these fields (plus x-goog-meta-* fields)'
                               ' can be set or unset:\n%s' % (f,
                               sorted(list(Key.base_user_settable_fields))))
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
