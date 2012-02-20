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
from gslib.bucket_listing_ref import BucketListingRef
from gslib.util import ListingStyle
from gslib.util import MakeHumanReadable
from gslib.util import NO_MAX
from gslib.wildcard_iterator import ContainsWildcard


class LsCommand(Command):
  """Implementation of gsutil ls command."""

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'ls',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : ['dir', 'list'],
    # Min number of args required by this command.
    MIN_ARGS : 0,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : NO_MAX,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : 'blLp:rR',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : False,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : True,
    # Index in args of first URI arg.
    URIS_START_ARG : 0,
    # True if must configure gsutil before running command.
    CONFIG_REQUIRED : True,
  }

  def _PrintBucketInfo(self, bucket_uri, listing_style):
    """Print listing info for given bucket.

    Args:
      bucket_uri: StorageUri being listed.
      listing_style: ListingStyle enum describing type of output desired.

    Returns:
      Tuple (total objects, total bytes) in the bucket.
    """
    bucket_objs = 0
    bucket_bytes = 0
    if listing_style == ListingStyle.SHORT:
      print bucket_uri
    else:
      for obj in self.exp_handler.WildcardIterator(
          bucket_uri.clone_replace_name('**')).IterKeys():
        bucket_objs += 1
        bucket_bytes += obj.size
      if listing_style == ListingStyle.LONG:
        print '%s : %s objects, %s' % (
            bucket_uri, bucket_objs, MakeHumanReadable(bucket_bytes))
      else:  # listing_style == ListingStyle.LONG_LONG:
        location_constraint = bucket_uri.get_location(validate=False,
                                                      headers=self.headers)
        location_output = ''
        if location_constraint:
          location_output = '\n\tLocationConstraint: %s' % location_constraint
        self.proj_id_handler.FillInProjectHeaderIfNeeded(
            'get_acl', bucket_uri, self.headers)
        print '%s :\n\t%d objects, %s%s\n\tACL: %s\n\tDefault ACL: %s' % (
            bucket_uri, bucket_objs, MakeHumanReadable(bucket_bytes),
            location_output, bucket_uri.get_acl(False, self.headers),
            bucket_uri.get_def_acl(False, self.headers))
    return (bucket_objs, bucket_bytes)

  def _UriStrForObj(self, uri, obj):
    """Constructs a URI string for the given object.

    For example if we were iterating gs://*, obj could be an object in one
    of the user's buckets enumerated by the ls command.

    Args:
      uri: base StorageUri being iterated.
      obj: object (Key) being listed.

    Returns:
      URI string.
    """
    return '%s://%s/%s' % (uri.scheme, obj.bucket.name, obj.name)

  def _PrintInfoAboutBucketListingRef(self, bucket_listing_ref, listing_style):
    """Print listing info for given bucket_listing_ref.

    Args:
      bucket_listing_ref: BucketListing being listed.
      listing_style: ListingStyle enum describing type of output desired.

    Returns:
      Tuple (number of objects,
             object length, if listing_style is one of the long listing formats)

    Raises:
      Exception: if calling bug encountered.
    """
    uri = bucket_listing_ref.GetUri()
    obj = bucket_listing_ref.GetKey()
    if listing_style == ListingStyle.SHORT:
      print self._UriStrForObj(uri, obj)
      return (0, 0)
    elif listing_style == ListingStyle.LONG:
      # Exclude timestamp fractional secs (example: 2010-08-23T12:46:54.187Z).
      timestamp = obj.last_modified[:19].decode('utf8').encode('ascii')
      print '%10s  %s  %s' % (obj.size, timestamp, self._UriStrForObj(uri, obj))
      return (1, obj.size)
    elif listing_style == ListingStyle.LONG_LONG:
      uri_str = self._UriStrForObj(uri, obj)
      print '%s:' % uri_str
      obj.open_read()
      print '\tObject size:\t%s' % obj.size
      print '\tLast mod:\t%s' % obj.last_modified
      if obj.cache_control:
        print '\tCache control:\t%s' % obj.cache_control
      print '\tMIME type:\t%s' % obj.content_type
      if obj.content_encoding:
        print '\tContent-Encoding:\t%s' % obj.content_encoding
      if obj.metadata:
        for name in obj.metadata:
          print '\tMetadata:\t%s = %s' % (name, obj.metadata[name])
      print '\tEtag:\t%s' % obj.etag.strip('"\'')
      print '\tACL:\t%s' % (
          self.suri_builder.StorageUri(uri_str).get_acl(False, self.headers))
      return (1, obj.size)
    else:
      raise Exception('Unexpected ListingStyle(%s)' % listing_style)

  def _ExpandUriAndPrintInfo(self, uri, listing_style, should_recurse=False):
    """
    Expands wildcards and directories/buckets for uri as needed, and
    calls _PrintInfoAboutBucketListingRef() on each.

    Args:
      uri: StorageUri being listed.
      listing_style: ListingStyle enum describing type of output desired.
      should_recurse: bool indicator of whether to expand recursively.

    Returns:
      Tuple (number of matching objects, number of bytes across these objects).
    """
    # We do a two-level loop, with the outer loop iterating level-by-level from
    # blrs_to_expand, and the inner loop iterating the matches at the current
    # level, printing them, and adding any new subdirs that need expanding to
    # blrs_to_expand (to be picked up in the next outer loop iteration).
    blrs_to_expand = [BucketListingRef(uri)]
    num_objs = 0
    num_bytes = 0
    expanding_top_level = True
    printed_one = False
    while len(blrs_to_expand):
      if printed_one:
        print
      blr = blrs_to_expand.pop(0)
      if blr.HasKey():
        blr_expansion = [blr]
      elif blr.HasPrefix():
        # Bucket subdir from a previous iteration. Print "header" line.
        print '%s:' % blr.GetUriString()
        blr_expansion = list(self.exp_handler.WildcardIterator(
            '%s/*' % blr.GetRStrippedUriString()))
        printed_one = True
      elif blr.NamesBucket():
        blr_expansion = list(self.exp_handler.WildcardIterator(
            '%s*' % blr.GetUriString()))
        printed_one = True
      else:
        # Do a delimited wildcard expansion so we get any matches along with
        # whether they are keys or prefixes. That way if bucket contains a key
        # 'abcd' and another key 'abce/x.txt' the expansion will return two
        # BLRs, the first with HasKey()=True and the second with
        # HasPrefix()=True. Note that we need to ensure there's a wildcard so
        # CloudWildcardIterator will not just treat it as a key and yield the
        # result without doing a bucket listing.
        wildcard_to_expand = blr.GetRStrippedUriString()
        if not ContainsWildcard(wildcard_to_expand):
          wildcard_to_expand = '%s*' % wildcard_to_expand
        blr_expansion = list(self.exp_handler.WildcardIterator(
            wildcard_to_expand))
      for cur_blr in blr_expansion:
        if cur_blr.HasKey():
          # Object listing.
          (no, nb) = self._PrintInfoAboutBucketListingRef(
              cur_blr, listing_style)
          num_objs += no
          num_bytes += nb
        else:
          # Subdir listing. If we're at the top level of a bucket subdir
          # listing don't print the list here (corresponding to how UNIX ls
          # dir just prints its contents, not the name followed by its
          # contents).
          if (expanding_top_level and not uri.names_bucket()) or should_recurse:
            blrs_to_expand.append(cur_blr)
          else:
            print cur_blr.GetUriString()
      expanding_top_level = False
    return (num_objs, num_bytes)

  # Command entry point.
  def RunCommand(self):
    listing_style = ListingStyle.SHORT
    get_bucket_info = False
    self.recursion_requested = False
    if self.sub_opts:
      for o, a in self.sub_opts:
        if o == '-b':
          get_bucket_info = True
        elif o == '-l':
          listing_style = ListingStyle.LONG
        elif o == '-L':
          listing_style = ListingStyle.LONG_LONG
        elif o == '-p':
          self.proj_id_handler.SetProjectId(a)
        elif o == '-r' or o == '-R':
          self.recursion_requested = True

    if not self.args:
      # default to listing all gs buckets
      self.args = ['gs://']

    total_objs = 0
    total_bytes = 0
    for uri_str in self.args:
      uri = self.suri_builder.StorageUri(uri_str)
      self.proj_id_handler.FillInProjectHeaderIfNeeded('ls', uri, self.headers)

      if uri.names_provider():
        # Provider URI: use bucket wildcard to list buckets.
        for uri in self.exp_handler.WildcardIterator(
            '%s://*' % uri.scheme).IterUris():
          (bucket_objs, bucket_bytes) = self._PrintBucketInfo(uri,
                                                              listing_style)
          total_bytes += bucket_bytes
          total_objs += bucket_objs
      elif uri.names_bucket():
        # Bucket URI -> list the object(s) in that bucket.
        if get_bucket_info:
          # ls -b bucket listing request: List info about bucket(s).
          for uri in self.exp_handler.WildcardIterator(uri).IterUris():
            (bucket_objs, bucket_bytes) = self._PrintBucketInfo(uri,
                                                                listing_style)
            total_bytes += bucket_bytes
            total_objs += bucket_objs
        else:
          # ls request on provider+bucket URI: List objects in the bucket(s).
          (no, nb) = self._ExpandUriAndPrintInfo(uri, listing_style,
              should_recurse=self.recursion_requested)
          total_objs += no
          total_bytes += nb
      else:
        # URI names an object or object subdir -> list matching object(s) /
        # subdirs.
        (exp_objs, exp_bytes) = self._ExpandUriAndPrintInfo(uri, listing_style,
            should_recurse=self.recursion_requested)
        total_bytes += exp_bytes
        total_objs += exp_objs

    if total_objs and listing_style != ListingStyle.SHORT:
      print ('TOTAL: %d objects, %d bytes (%s)' %
             (total_objs, total_bytes, MakeHumanReadable(float(total_bytes))))

  # test specification, see definition of test_steps in base class for
  # details on how to populate these fields
  test_steps = [
    # (test name, cmd line, ret code, (result_file, expect_file))
    ('gen bucket expect', 'echo gs://$B0/ >$F9', 0, None),
    ('gen obj expect', 'echo gs://$B1/$O0 >$F8', 0, None),
    ('simple ls', 'gsutil ls', 0, None),
    ('list empty bucket', 'gsutil ls gs://$B0', 0, None),
    ('list empty bucket w/ -b', 'gsutil ls -b gs://$B0 >$F7', 0, 
                                                        ('$F7', '$F9')),
    ('list bucket contents', 'gsutil ls gs://$B1 >$F7', 0, ('$F7', '$F8')),
    ('list object', 'gsutil ls gs://$B1/$O0 >$F7', 0, ('$F7', '$F8')),
  ]
