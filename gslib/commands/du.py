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

import fnmatch
import sys

from boto.s3.deletemarker import DeleteMarker
from gslib.bucket_listing_ref import BucketListingRef
from gslib.command import Command
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.command import FILE_URIS_OK
from gslib.command import MAX_ARGS
from gslib.command import MIN_ARGS
from gslib.command import PROVIDER_URIS_OK
from gslib.command import SUPPORTED_SUB_ARGS
from gslib.command import URIS_START_ARG
from gslib.commands.ls import UriOnlyBlrExpansionIterator
from gslib.commands.ls import UriStrForObj
from gslib.exception import CommandException
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HelpType
from gslib.help_provider import HELP_TYPE
from gslib.plurality_checkable_iterator import PluralityCheckableIterator
from gslib.util import MakeHumanReadable
from gslib.util import NO_MAX
from gslib.wildcard_iterator import ContainsWildcard

_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil du uri...


<B>DESCRIPTION</B>
  The du command displays the amount of space (in bytes) being used by the
  objects for a given URI. The syntax emulates the Linux du command (which
  stands for disk usage).


<B>OPTIONS</B>
  -0          Ends each output line with a 0 byte rather than a newline. This
              can be useful to make the output more easily machine-readable.

  -a          Includes non-current object versions / generations in the listing
              (only useful with a versioning-enabled bucket). Also prints
              generation and metageneration for each listed object.

  -c          Produce a grand total.

  -e          A pattern to exclude from reporting. Example: -e "*.o" would
              exclude any object that ends in ".o". Can be specified multiple
              times.

  -h          Prints object sizes in human-readable format (e.g., 1KB, 234MB,
              2GB, etc.)

  -s          Display only a summary total for each argument.

  -X          Similar to -e, but excludes patterns from the given file. The
              patterns to exclude should be one per line.


<B>EXAMPLES</B>
  To list the size of all objects in a bucket:

    gsutil du gs://bucketname

  To list the size of all objects underneath a prefix:

    gsutil du gs://bucketname/prefix/*

  To print the total number of bytes in a bucket, in human-readable form:

    gsutil du -ch gs://bucketname

  To see a summary of the total bytes in the two given buckets:

    gsutil du -s gs://bucket1 gs://bucket2

  To list the size of all objects in a versioned bucket, including objects that
  are not the latest:

    gsutil du -a gs://bucketname

  To list all objects in a bucket, except objects that end in ".bak",
  with each object printed ending in a null byte:

    gsutil du -e "*.bak" -0 gs://bucketname

""")

class DuCommand(Command):
  """Implementation of gsutil du command."""

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'du',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : [],
    # Min number of args required by this command.
    MIN_ARGS : 0,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : NO_MAX,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : '0ace:hsX:',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : False,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : True,
    # Index in args of first URI arg.
    URIS_START_ARG : 0,
  }
  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'du',
    # List of help name aliases.
    HELP_NAME_ALIASES : [],
    # Type of help:
    HELP_TYPE : HelpType.COMMAND_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Display object size usage',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }

  def _PrintSummaryLine(self, num_bytes, name):
    size_string = (MakeHumanReadable(num_bytes)
                   if self.human_readable else str(num_bytes))
    sys.stdout.write('%(size)-10s  %(name)s%(ending)s' % {
        'size': size_string,  'name': name, 'ending': self.line_ending})

  def _PrintInfoAboutBucketListingRef(self, bucket_listing_ref):
    """Print listing info for given bucket_listing_ref.

    Args:
      bucket_listing_ref: BucketListing being listed.

    Returns:
      Tuple (number of objects, object size)

    Raises:
      Exception: if calling bug encountered.
    """
    uri = bucket_listing_ref.GetUri()
    obj = bucket_listing_ref.GetKey()
    uri_str = UriStrForObj(uri, obj, self.all_versions)

    if isinstance(obj, DeleteMarker):
      size_string = '0'
      numobjs = 0
      numbytes = 0
    else:
      size_string = (MakeHumanReadable(obj.size)
                     if self.human_readable else str(obj.size))
      numobjs = 1
      numbytes = obj.size

    if not self.summary_only:
      sys.stdout.write('%(size)-10s  %(uri)s%(ending)s' % {
          'size': size_string,
          'uri': uri_str.encode('utf-8'),
          'ending': self.line_ending})

    return numobjs, numbytes

  def _RecursePrint(self, blr):
    """
    Expands a bucket listing reference and recurses to its children, calling
    _PrintInfoAboutBucketListingRef for each expanded object found.

    Args:
      blr: An instance of BucketListingRef.

    Returns:
      Tuple containing (number of object, total number of bytes)
    """
    num_bytes = 0
    num_objs = 0

    if blr.HasKey():
      blr_iterator = iter([blr])
    elif blr.HasPrefix():
      blr_iterator = self.WildcardIterator(
          '%s/*' % blr.GetRStrippedUriString(), all_versions=self.all_versions)
    elif blr.NamesBucket():
      blr_iterator = self.WildcardIterator(
          '%s*' % blr.GetUriString(), all_versions=self.all_versions)
    else:
      # This BLR didn't come from a bucket listing. This case happens for
      # BLR's instantiated from a user-provided URI.
      blr_iterator = PluralityCheckableIterator(
          UriOnlyBlrExpansionIterator(
              self, blr, all_versions=self.all_versions))
      if blr_iterator.is_empty() and not ContainsWildcard(blr.GetUriString()):
        raise CommandException('No such object %s' % blr.GetUriString())

    for cur_blr in blr_iterator:
      if self.exclude_patterns:
        tomatch = cur_blr.GetUriString()
        skip = False
        for pattern in self.exclude_patterns:
          if fnmatch.fnmatch(tomatch, pattern):
            skip = True
            break
        if skip:
          continue
      if cur_blr.HasKey():
        # Object listing.
        no, nb = self._PrintInfoAboutBucketListingRef(cur_blr)
      else:
        # Subdir listing.
        if cur_blr.GetUriString().endswith('//'):
          # Expand gs://bucket// into gs://bucket//* so we don't infinite
          # loop. This case happens when user has uploaded an object whose
          # name begins with a /.
          cur_blr = BucketListingRef(self.suri_builder.StorageUri(
              '%s*' % cur_blr.GetUriString()), None, None, cur_blr.headers)
        no, nb = self._RecursePrint(cur_blr)
      num_bytes += nb
      num_objs += no

    if blr.HasPrefix() and not self.summary_only:
      self._PrintSummaryLine(num_bytes, blr.GetUriString().encode('utf-8'))

    return num_objs, num_bytes

  # Command entry point.
  def RunCommand(self):
    self.line_ending = '\n'
    self.all_versions = False
    self.produce_total = False
    self.human_readable = False
    self.summary_only = False
    self.exclude_patterns = []
    if self.sub_opts:
      for o, a in self.sub_opts:
        if o == '-0':
          self.line_ending = '\0'
        elif o == '-a':
          self.all_versions = True
        elif o == '-c':
          self.produce_total = True
        elif o == '-e':
          self.exclude_patterns.append(a)
        elif o == '-h':
          self.human_readable = True
        elif o == '-s':
          self.summary_only = True
        elif o == '-X':
          if a == '-':
            f = sys.stdin
          else:
            f = open(a, 'r')
          try:
            for line in f:
              line = line.strip()
              if line:
                self.exclude_patterns.append(line)
          finally:
            f.close()

    if not self.args:
      # Default to listing all gs buckets.
      self.args = ['gs://']

    total_objs = 0
    total_bytes = 0
    got_nomatch_errors = False

    for uri_str in self.args:
      uri = self.suri_builder.StorageUri(uri_str)

      # Treat this as the ls command for this function.
      self.proj_id_handler.FillInProjectHeaderIfNeeded('ls', uri, self.headers)

      iter_bytes = 0
      if uri.names_provider():
        # Provider URI: use bucket wildcard to list buckets.
        for uri in self.WildcardIterator('%s://*' % uri.scheme).IterUris():
          exp_objs, exp_bytes = self._RecursePrint(BucketListingRef(uri))
          iter_bytes += exp_bytes
          total_objs += exp_objs
      else:
        exp_objs, exp_bytes = self._RecursePrint(BucketListingRef(uri))
        if (exp_objs == 0 and ContainsWildcard(uri) and
            not self.exclude_patterns):
          got_nomatch_errors = True
        iter_bytes += exp_bytes
        total_objs += exp_objs

      total_bytes += iter_bytes
      if self.summary_only:
        self._PrintSummaryLine(iter_bytes, uri_str)

    if self.produce_total:
      self._PrintSummaryLine(total_bytes, 'total')

    if got_nomatch_errors:
      raise CommandException('One or more URIs matched no objects.')

    return 0
