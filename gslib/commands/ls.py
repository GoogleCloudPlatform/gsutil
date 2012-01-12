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

import gslib

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
from gslib.util import ListingStyle
from gslib.util import MakeHumanReadable
from gslib.util import NO_MAX
from gslib.wildcard_iterator import ResultType
from gslib.wildcard_iterator import WildcardException


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
    SUPPORTED_SUB_ARGS : 'blLp:',
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
      try:
        for obj in self.CmdWildcardIterator(bucket_uri.clone_replace_name('*'),
                                            ResultType.KEYS):
          bucket_objs += 1
          bucket_bytes += obj.size
      except WildcardException, e:
        # Ignore non-matching wildcards, to allow empty bucket listings.
        if e.reason.find('No matches') == -1:
          raise e
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


  def _UriStrFor(self, iterated_uri, obj):
    """Constructs a StorageUri string for the given iterated_uri and object.

    For example if we were iterating gs://*, obj could be an object in one
    of the user's buckets enumerated by the ls command.

    Args:
      iterated_uri: base StorageUri being iterated.
      obj: object being listed.

    Returns:
      URI string.
    """
    return '%s://%s/%s' % (iterated_uri.scheme, obj.bucket.name, obj.name)

  def _PrintObjectInfo(self, iterated_uri, obj, listing_style):
    """Print listing info for given object.

    Args:
      iterated_uri: base StorageUri being listed (e.g., gs://abc/*).
      obj: object to be listed (or None if no associated object).
      listing_style: ListingStyle enum describing type of output desired.

    Returns:
      Object length (if listing_style is one of the long listing formats).

    Raises:
      Exception: if calling bug encountered.
    """
    if listing_style == ListingStyle.SHORT:
      print self._UriStrFor(iterated_uri, obj)
      return 0
    elif listing_style == ListingStyle.LONG:
      # Exclude timestamp fractional secs (example: 2010-08-23T12:46:54.187Z).
      timestamp = obj.last_modified[:19].decode('utf8').encode('ascii')
      print '%10s  %s  %s' % (obj.size, timestamp,
                              self._UriStrFor(iterated_uri, obj))
      return obj.size
    elif listing_style == ListingStyle.LONG_LONG:
      uri_str = self._UriStrFor(iterated_uri, obj)
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
          self.StorageUri(uri_str).get_acl(False, self.headers))
      return obj.size
    else:
      raise Exception('Unexpected ListingStyle(%s)' % listing_style)

  # Command entry point.
  def RunCommand(self):
    listing_style = ListingStyle.SHORT
    get_bucket_info = False
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

    if not self.args:
      # default to listing all gs buckets
      self.args = ['gs://']

    total_objs = 0
    total_bytes = 0
    for uri_str in self.args:
      uri = self.StorageUri(uri_str)
      self.proj_id_handler.FillInProjectHeaderIfNeeded('ls', uri, self.headers)

      if not uri.bucket_name:
        # Provider URI: add bucket wildcard to list buckets.
        for uri in self.CmdWildcardIterator('%s://*' % uri.scheme):
          (bucket_objs, bucket_bytes) = self._PrintBucketInfo(uri,
                                                              listing_style)
          total_bytes += bucket_bytes
          total_objs += bucket_objs

      elif not uri.object_name:
        if get_bucket_info:
          # ls -b request on provider+bucket URI: List info about bucket(s).
          for uri in self.CmdWildcardIterator(uri):
            (bucket_objs, bucket_bytes) = self._PrintBucketInfo(uri,
                                                               listing_style)
            total_bytes += bucket_bytes
            total_objs += bucket_objs
        else:
          # ls request on provider+bucket URI: List objects in the bucket(s).
          for obj in self.CmdWildcardIterator(uri.clone_replace_name('*'),
                                              ResultType.KEYS):
            total_bytes += self._PrintObjectInfo(uri, obj, listing_style)
            total_objs += 1

      else:
        # Provider+bucket+object URI -> list the object(s).
        for obj in self.CmdWildcardIterator(uri, ResultType.KEYS):
          total_bytes += self._PrintObjectInfo(uri, obj, listing_style)
          total_objs += 1
    if listing_style != ListingStyle.SHORT:
      print ('TOTAL: %d objects, %d bytes (%s)' %
             (total_objs, total_bytes, MakeHumanReadable(float(total_bytes))))

