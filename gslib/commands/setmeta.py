# Copyright 2012 Google Inc.
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
import StringIO

from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.command import CONFIG_REQUIRED
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

    gsutil setmeta -h "Content-Type:text/html" -h "Cache-Control:public, max-age=3600" -h "Content-Disposition" gs://bucket/*.html

  If you have a large number of objects to update you might want to use the
  gsutil -m option, to perform a parallel (multi-threaded/multi-processing)
  update:

    gsutil -m setmeta -h "Content-Type:text/html" -h "Cache-Control:public, max-age=3600" -h "Content-Disposition" gs://bucket/*.html


<B>SETTABLE FIELDS; FIELD VALUES</B>
  You can't set some metadata fields, such as ETag and Content-Length. The
  fields you can set are:
    - Cache-Control
    - Content-Disposition
    - Content-Encoding
    - Content-Language
    - Content-MD5
    - Content-Type
    - Any field starting with X-GOOG-META- (i.e., custom metadata).

  Header names are case-insensitive.

  X-GOOG-META- fields can have data set to arbitrary Unicode values. All
  other fields must have ASCII values.


<B>VIEWING CURRENTLY SET METADATA</B>
  You can see what metadata is currently set on an object by using:

    gsutil ls -L gs://the_bucket/the_object


<B>OPERATION COST</B>
  This command uses four operations per URI (one to read the ACL, one to read
  the current metadata, one to set the new metadata, and one to set the ACL).

  For cases where you want all objects to have the same ACL you can avoid half
  these operations by setting a default ACL on the bucket(s) containing the
  named objects, and using the setmeta -n option. See "help gsutil setdefacl".


<B>OPTIONS</B>
  -h          Specifies a header:value to be added, or header to be removed,
              from each named object.
  -n          Causes the operations for reading and writing the ACL to be
	      skipped. This halves the number of operations performed per
	      request, improving the speed and reducing the cost of performing
	      the operations. This option makes sense for cases where you want
	      all objects to have the same ACL, for which you have set a default
	      ACL on the bucket(s) containing the objects. See "help gsutil
	      setdefacl".


<B>OLDER SYNTAX (DEPRECATED)</B>
  The first version of the setmeta command used more complicated syntax
  (described below). gsutil still supports this syntax, to avoid breaking
  existing customer uses, but it is now deprecated and will eventually
  be removed.

  With this older syntax, the setmeta command accepts a single metadata
  argument in one of two forms:

    gsutil setmeta [-n] header:value uri...

  or

    gsutil setmeta [-n] '"header:value","-header",...' uri...

  The first form allows you to specify a single header name and value to
  set. For example, the following command would set the Content-Type and
  Cache-Control and remove the Content-Disposition on the specified objects:

    gsutil setmeta -h "Content-Type:text/html" -h "Cache-Control:public, max-age=3600" -h "Content-Disposition" gs://bucket/*.html

  This form only works if the header name and value don't contain double
  quotes or commas, and only works for setting the header value (not for
  removing it).

  The more general form of the first argument allows both setting and removing
  multiple fields, without any of the content restrictions noted above. For
  this variant the first argument is a CSV-formatted list of headers to add
  or remove. Getting the CSV-formatted list to be passed correctly into gsutil
  requires different syntax on Linux or MacOS than it does on Windows.

  On Linux or MacOS you need to surround the entire argument in single quotes
  to avoid having the shell interpret/strip out the double-quotes in the CSV
  data. For example, the following command would set the Content-Type and
  Cache-Control and remove the Content-Disposition on the specified objects:

    gsutil setmeta '"Content-Type:text/html","Cache-Control:public, max-age=3600","-Content-Disposition"' gs://bucket/*.html

  To pass CSV data on Windows you need two sets of double quotes around
  each header/value pair, and one set of double quotes around the entire
  expression. For example, the following command would set the Content-Type
  and Cache-Control and remove the Content-Disposition on the specified objects:

    gsutil setmeta "\""Content-Type:text/html"",""Cache-Control:public, max-age=3600"",""-Content-Disposition""\" gs://bucket/*.html
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
    # True if must configure gsutil before running command.
    CONFIG_REQUIRED : True,
  }
  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'setmeta',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['setheader'],
    # Type of help:
    HELP_TYPE : HelpType.COMMAND_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Set object metadata',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }

  # The fields a user can set, other than custom metadata fields (i.e., those
  # beginning with a provider-specific prefix like x-goog-meta).
  _base_user_settable_fields = set(["cache-control", "content-disposition",
                                    "content-encoding", "content-language",
                                    "content-md5", "content-type"])
  _underscore_base_user_settable_fields = set()
  for f in _base_user_settable_fields:
    _underscore_base_user_settable_fields.add(f.replace('-', '_'))

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

    if headers:
      (metadata_minus, metadata_plus) = self._ParseMetadataHeaders(headers)
      uri_args = self.args
    else:
      (metadata_minus, metadata_plus) = self._ParseMetadataSpec(self.args[0])
      uri_args = self.args[1:]

    if (len(uri_args) == 1
        and not self.suri_builder.StorageUri(uri_args[0]).names_object()):
      raise CommandException('URI (%s) must name an object' % uri_args[0])

    # Used to track if any objects' metaadata failed to be set.
    self.everything_set_okay = True

    def _SetMetadataExceptionHandler(e):
      """Simple exception handler to allow post-completion status."""
      self.THREADED_LOGGER.error(str(e))
      self.everything_set_okay = False

    def _SetMetadataFunc(name_expansion_result):
      exp_src_uri = self.suri_builder.StorageUri(
          name_expansion_result.GetExpandedUriStr())
      self.THREADED_LOGGER.info('Setting metadata on %s...' % exp_src_uri)
      metadata = self._ExtractMetadata(exp_src_uri)
      metadata.update(metadata_plus)
      for h in metadata_minus:
        if h in metadata:
          del metadata[h]
      src_bucket = exp_src_uri.get_bucket()
      # Boto prepends the meta prefix when adding headers, so strip prefix in
      # metadata before sending back in to copy_key() call.
      rewritten_metadata = {}
      for h in metadata:
        if _IsCustomMeta(h):
          h_pref_stripped = (
              h.replace('x-goog-meta-', '').replace('x-amz-meta-', ''))
          rewritten_metadata[h_pref_stripped] = metadata[h]
        else:
          rewritten_metadata[h] = metadata[h]
      metadata = rewritten_metadata
      src_bucket.copy_key(exp_src_uri.object_name, exp_src_uri.bucket_name,
          exp_src_uri.object_name, metadata=metadata, preserve_acl=preserve_acl)

    name_expansion_iterator = NameExpansionIterator(
        self.command_name, self.proj_id_handler, self.headers, self.debug,
        self.bucket_storage_uri_class, uri_args, self.recursion_requested,
        self.recursion_requested)

    # Perform requests in parallel (-m) mode, if requested, using
    # configured number of parallel processes and threads. Otherwise,
    # perform requests with sequential function calls in current process.
    self.Apply(_SetMetadataFunc, name_expansion_iterator,
               _SetMetadataExceptionHandler)

    if not self.everything_set_okay:
      raise CommandException('Metadata for some objects could not be set.')

  # Test specification. See definition of test_steps in base class for
  # details on how to populate these fields.
  test_steps = [
    # (test name, cmd line, ret code, (result_file, expect_file))
    ('upload', 'gsutil -h "x-goog-meta-xyz:abc" '
     '-h "Content-Type:image/gif" cp $F1 gs://$B1/$O1', 0, None),
    ('setup gif CT', 'echo image/gif >test_gif.ct', 0, None),
    ('setup html CT', 'echo text/html >test_html.ct', 0, None),
    ('setup META', 'echo "abc" >test.meta', 0, None),
    ('retrieve initial metadata', 'gsutil ls -L gs://$B1/$O1 >$F1', 0, None),
    ('verify initial Content-Type', 'grep Content-Type $F1 | cut -f3 >$F2',
      0, ('$F2', 'test_gif.ct')),
    ('verify initial x-goog-meta-xyz',
     'grep x-goog-meta-xyz $F1 | cut -f3 > $F2', 0, ('$F2', 'test.meta')),
    ('run setmeta',
     'gsutil setmeta -n -h Content-Type:text/html -h x-goog-meta-xyz '
     'gs://$B1/$O1', 0, None),
    ('retrieve new metadata', 'gsutil ls -L gs://$B1/$O1 >$F1', 0, None),
    ('verify new Content-Type', 'grep Content-Type $F1 | cut -f3 >$F2',
      0, ('$F2', 'test_html.ct')),
    ('verify new x-goog-meta-xyz', 'grep -q xyz $F1', 1, None),
    # Test handling of various illegal setmeta commands.
    ('test missing header value',
     'gsutil setmeta \'"Content-Type"\' gs://$B1/$O1', 1, None),
    ('test value included with minus header',
     'gsutil setmeta \'"-Content-Type:text/html"\' gs://$B1/$O1', 1, None),
    ('test header included as both plus and minus header',
     'gsutil setmeta \'"Content-Type:text/html","-Content-Type"\' gs://$B1/$O1',
     1, None),
    ('test non-ASCII custom header',
     'gsutil setmeta \'"x-goog-meta-soufflé:5"\' gs://$B1/$O1', 1, None),
    ('test disallowed header',
     'gsutil setmeta \'"Content-Length:5"\' gs://$B1/$O1', 1, None),
     #
     # Older (deprecated) syntax tests:
    ('upload', 'gsutil -h "x-goog-meta-xyz:abc" '
     '-h "Content-Type:image/gif" cp $F1 gs://$B1/$O1', 0, None),
    ('setup gif CT', 'echo image/gif >test_gif.ct', 0, None),
    ('setup html CT', 'echo text/html >test_html.ct', 0, None),
    ('setup META', 'echo "abc" >test.meta', 0, None),
    ('retrieve initial metadata', 'gsutil ls -L gs://$B1/$O1 >$F1', 0, None),
    ('verify initial Content-Type', 'grep Content-Type $F1 | cut -f3 >$F2',
      0, ('$F2', 'test_gif.ct')),
    ('verify initial x-goog-meta-xyz',
     'grep x-goog-meta-xyz $F1 | cut -f3 > $F2', 0, ('$F2', 'test.meta')),
    ('run setmeta (deprecated syntax)',
     'gsutil setmeta -n \'"Content-Type:text/html","-x-goog-meta-xyz"\' '
     'gs://$B1/$O1', 0, None),
    ('retrieve new metadata', 'gsutil ls -L gs://$B1/$O1 >$F1', 0, None),
    ('verify new Content-Type', 'grep Content-Type $F1 | cut -f3 >$F2',
      0, ('$F2', 'test_html.ct')),
    ('verify new x-goog-meta-xyz', 'grep -q xyz $F1', 1, None),
    # Test handling of various illegal setmeta commands.
    ('test missing header value',
     'gsutil setmeta \'"Content-Type"\' gs://$B1/$O1', 1, None),
    ('test value included with minus header',
     'gsutil setmeta \'"-Content-Type:text/html"\' gs://$B1/$O1', 1, None),
    ('test header included as both plus and minus header',
     'gsutil setmeta \'"Content-Type:text/html","-Content-Type"\' gs://$B1/$O1',
     1, None),
    ('test non-ASCII custom header',
     'gsutil setmeta \'"x-goog-meta-soufflé:5"\' gs://$B1/$O1', 1, None),
    ('test disallowed header',
     'gsutil setmeta \'"Content-Length:5"\' gs://$B1/$O1', 1, None),
     #
    ('remove test files', 'rm -f test_gif.ct test_html.ct test.meta', 0, None),
  ]

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
      # Translate headers to lowercase to match the casing that comes back
      # from self._ExtractMetadata().
      header = header.lower()
      if value:
        if _IsCustomMeta(header):
          # Allow non-ASCII data for custom metadata fields. Don't unicode
          # encode other fields because that would perturb their content
          # (e.g., adding %2F's into the middle of a Cache-Control value).
          value = unicode(value, 'utf-8')
          cust_metadata_plus[header] = value
          num_cust_metadata_plus_elems += 1
        else:
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
        .difference(self._base_user_settable_fields))
    other_than_base_fields.update(
        metadata_minus.difference(self._base_user_settable_fields))
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
                               sorted(list(self._base_user_settable_fields))))
    metadata_plus.update(cust_metadata_plus)
    metadata_minus.update(cust_metadata_minus)
    return (metadata_minus, metadata_plus)

  def _ParseMetadataSpec(self, spec):
    self.THREADED_LOGGER.info('WARNING: metadata spec syntax (%s)\nis '
                              'deprecated and will eventually be removed.\n'
                              'Please see "gsutil help setmeta" for current '
                              'syntax' % spec)
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

    mdf = StringIO.StringIO(spec)
    for md_arg in csv.reader(mdf).next():
      if not md_arg:
        raise CommandException(
            'Invalid empty metadata specification component.')
      if md_arg[0] == '-':
        header = md_arg[1:]
        if header.find(':') != -1:
          raise CommandException('Removal spec may not contain ":" (%s).' %
                                 header)
        _InsistAsciiHeader(header)
        # Translate headers to lowercase to match the casing that comes back
        # from self._ExtractMetadata().
        header = header.lower()
        if _IsCustomMeta(header):
          cust_metadata_minus.add(header)
          num_cust_metadata_minus_elems += 1
        else:
          metadata_minus.add(header)
          num_metadata_minus_elems += 1
      else:
        parts = md_arg.split(':', 1)
        if len(parts) != 2:
          raise CommandException(
              'Fields being added must include values (%s).' % md_arg)
        (header, value) = parts
        _InsistAsciiHeader(header)
        header = header.lower()
        if _IsCustomMeta(header):
          # Allow non-ASCII data for custom metadata fields. Don't unicode
          # encode other fields because that would perturb their content
          # (e.g., adding %2F's into the middle of a Cache-Control value).
          value = unicode(value, 'utf-8')
          cust_metadata_plus[header] = value
          num_cust_metadata_plus_elems += 1
        else:
          metadata_plus[header] = value
          num_metadata_plus_elems += 1
    mdf.close()
    if (num_metadata_plus_elems != len(metadata_plus)
        or num_cust_metadata_plus_elems != len(cust_metadata_plus)
        or num_metadata_minus_elems != len(metadata_minus)
        or num_cust_metadata_minus_elems != len(cust_metadata_minus)
        or metadata_minus.intersection(set(metadata_plus.keys()))):
      raise CommandException('Each header must appear at most once.')
    other_than_base_fields = (set(metadata_plus.keys())
        .difference(self._base_user_settable_fields))
    other_than_base_fields.update(
        metadata_minus.difference(self._base_user_settable_fields))
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
                               sorted(list(self._base_user_settable_fields))))
    metadata_plus.update(cust_metadata_plus)
    metadata_minus.update(cust_metadata_minus)
    return (metadata_minus, metadata_plus)

  def _ExtractMetadata(self, uri):
    """
    Extracts metadata from existing URI into a dict, so we can overwrite/delete
    from it to form the new set of metadata to apply to a key.
    """
    key = uri.get_key(False)
    metadata = {}
    for underscore_name in self._underscore_base_user_settable_fields:
      if hasattr(key, underscore_name):
        value = getattr(key, underscore_name)
        if value:
          # Generate HTTP field name corresponding to "_" named field.
          field_name = underscore_name.replace('_', '-')
          metadata[field_name.lower()] = value
    # key.metadata contains custom metadata, which are all user-settable.
    prefix = uri.get_provider().metadata_prefix
    for underscore_name in key.metadata:
      field_name = underscore_name.replace('_', '-')
      metadata['%s%s' % (prefix, field_name.lower())] = (
          key.metadata[underscore_name])
    return metadata

def _InsistAsciiHeader(header):
    if not all(ord(c) < 128 for c in header):
      raise CommandException('Invalid non-ASCII header (%s).' % header)

def _IsCustomMeta(header):
  return header.startswith('x-goog-meta-') or header.startswith('x-amz-meta-')
