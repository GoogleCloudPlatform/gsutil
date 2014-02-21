# Copyright 2010 Google Inc. All Rights Reserved.
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
"""Wildcard iterator class and supporting functions."""

import fnmatch
import glob
import os
import re
import sys

from gslib.bucket_listing_ref import BucketListingRef
from gslib.bucket_listing_ref import BucketListingRefType
from gslib.cloud_api import AccessDeniedException
from gslib.cloud_api import CloudApi
from gslib.storage_url import ContainsWildcard
from gslib.storage_url import StorageUrlFromString
from gslib.storage_url import StripOneSlash
from gslib.storage_url import WILDCARD_REGEX
from gslib.translation_helper import GenerationFromUrlAndString


FLAT_LIST_REGEX = re.compile(r'(?P<before>.*?)\*\*(?P<after>.*)')


class WildcardIterator(object):
  """Class for iterating over Google Cloud Storage strings containing wildcards.

  The base class is abstract; you should instantiate using the
  wildcard_iterator() static factory method, which chooses the right
  implementation depending on the base string.
  """

  # TODO: Standardize on __str__ and __repr__ here and elsewhere.  Define both
  # and make one return the other.
  def __repr__(self):
    """Returns string representation of WildcardIterator."""
    return 'WildcardIterator(%s)' % self.wildcard_url.GetUrlString()


class CloudWildcardIterator(WildcardIterator):
  """WildcardIterator subclass for buckets, bucket subdirs and objects.

  Iterates over BucketListingRef matching the Url string wildcard. It's
  much more efficient to first get metadata that's available in the Bucket
  (for example to get the name and size of each object), because that
  information is available in the object list results.
  """

  def __init__(self, wildcard_url, gsutil_api, all_versions=False,
               debug=0, project_id=None):
    """Instantiates an iterator that matches the wildcard URL.

    Args:
      wildcard_url: CloudUrl that contains the wildcard to iterate.
      gsutil_api: Cloud storage interface.  Passed in for thread safety, also
                  settable for testing/mocking.
      all_versions: If true, the iterator yields all versions of objects
                    matching the wildcard.  If false, yields just the live
                    object version.
      debug: Debug level to control debug output for iterator.
      project_id: Project ID to use for bucket listings.
    """
    self.wildcard_url = wildcard_url
    self.all_versions = all_versions
    self.debug = debug
    self.gsutil_api = gsutil_api
    self.project_id = project_id

  def __iter__(self, bucket_listing_fields=None,
               expand_top_level_buckets=False):
    """Iterator that gets called when iterating over the cloud wildcard.

    In the case where no wildcard is present, returns a single matching object,
    single matching prefix, or one of each if both exist.

    Args:
      bucket_listing_fields: Iterable fields to include in bucket listings.
                             Ex. ['name', 'acl'].  Iterator is
                             responsible for converting these to list-style
                             format ['items/name', 'items/acl'] as well as
                             adding any fields necessary for listing such as
                             prefixes.  API implemenation is responsible for
                             adding pagination fields.  If this is None,
                             all fields are returned.
      expand_top_level_buckets: If true, yield no BUCKET references.  Instead,
                                expand buckets into top-level objects and
                                prefixes.

    Yields:
      BucketListingRef of type BUCKET, OBJECT or PREFIX.
    """
    single_version_request = self.wildcard_url.HasGeneration()

    # For wildcard expansion purposes, we need at a minimum the name of
    # each object and prefix.  If we're not using the default of requesting
    # all fields, make sure at least these are requested.  The Cloud API
    # tolerates specifying the same field twice.
    get_fields = None
    if bucket_listing_fields:
      get_fields = set()
      for field in bucket_listing_fields:
        get_fields.add(field)
      bucket_listing_fields = self._GetToListFields(
          get_fields=bucket_listing_fields)
      bucket_listing_fields.update(['items/name', 'prefixes'])
      get_fields.update(['name'])
      # If we're making versioned requests, ensure generation and
      # metageneration are also included.
      if single_version_request or self.all_versions:
        bucket_listing_fields.update(['items/generation',
                                      'items/metageneration'])
        get_fields.update(['generation', 'metageneration'])

    # Handle bucket wildcarding, if any, in _ExpandBucketWildcards. Then
    # iterate over the expanded bucket strings and handle any object
    # wildcarding.
    for bucket_listing_ref in self._ExpandBucketWildcards(bucket_fields=['id']):
      bucket_url_string = bucket_listing_ref.url_string
      if self.wildcard_url.IsBucket():
        # IsBucket() guarantees there are no prefix or object wildcards, and
        # thus this is a top-level listing of buckets.
        if expand_top_level_buckets:
          url = StorageUrlFromString(bucket_url_string)
          for obj_or_prefix in self.gsutil_api.ListObjects(
              url.bucket_name, delimiter='/', all_versions=self.all_versions,
              provider=self.wildcard_url.scheme,
              fields=bucket_listing_fields):
            if obj_or_prefix.datatype == CloudApi.CsObjectOrPrefixType.OBJECT:
              yield self._GetObjectRef(bucket_url_string, obj_or_prefix.data,
                                       with_version=self.all_versions)
            else:  # CloudApi.CsObjectOrPrefixType.PREFIX:
              yield self._GetPrefixRef(bucket_url_string, obj_or_prefix.data)
        else:
          yield BucketListingRef(bucket_url_string, BucketListingRefType.BUCKET)
      else:
        # Expand iteratively by building prefix/delimiter bucket listing
        # request, filtering the results per the current level's wildcard
        # (if present), and continuing with the next component of the
        # wildcard. See _BuildBucketFilterStrings() documentation for details.
        if single_version_request:
          url_string = '%s%s#%s' % (bucket_url_string,
                                    self.wildcard_url.object_name,
                                    self.wildcard_url.generation)
        else:
          # Rstrip any prefixes to correspond with rstripped prefix wildcard
          # from _BuildBucketFilterStrings().
          url_string = '%s%s' % (bucket_url_string,
                                 StripOneSlash(self.wildcard_url.object_name))
        urls_needing_expansion = [url_string]
        while urls_needing_expansion:
          url = StorageUrlFromString(urls_needing_expansion.pop(0))
          (prefix, delimiter, prefix_wildcard, suffix_wildcard) = (
              self._BuildBucketFilterStrings(url.object_name))
          prog = re.compile(fnmatch.translate(prefix_wildcard))

          # List bucket for objects matching prefix up to delimiter.
          try:
            for obj_or_prefix in self.gsutil_api.ListObjects(
                url.bucket_name, prefix=prefix, delimiter=delimiter,
                all_versions=self.all_versions or single_version_request,
                provider=self.wildcard_url.scheme,
                fields=bucket_listing_fields):
              if obj_or_prefix.datatype == CloudApi.CsObjectOrPrefixType.OBJECT:
                gcs_object = obj_or_prefix.data
                if prog.match(gcs_object.name):
                  if not suffix_wildcard or (
                      StripOneSlash(gcs_object.name) == suffix_wildcard):
                    if not single_version_request or (
                        self._SingleVersionMatches(gcs_object.generation)):
                      yield self._GetObjectRef(
                          bucket_url_string, gcs_object, with_version=(
                              self.all_versions or single_version_request))
              else:  # CloudApi.CsObjectOrPrefixType.PREFIX
                prefix = obj_or_prefix.data
                # If the prefix ends with a slash, remove it.  Note that we only
                # remove one slash so that we can successfully enumerate dirs
                # containing multiple slashes.
                rstripped_prefix = StripOneSlash(prefix)
                if prog.match(rstripped_prefix):
                  if suffix_wildcard and rstripped_prefix != suffix_wildcard:
                    # There's more wildcard left to expand.
                    url_append_string = '%s%s' % (
                        bucket_url_string, rstripped_prefix + '/' +
                        suffix_wildcard)
                    urls_needing_expansion.append(url_append_string)
                  else:
                    # No wildcard to expand, just yield the prefix
                    yield self._GetPrefixRef(bucket_url_string, prefix)
          except AccessDeniedException, e:
            # If we don't have permission to list the bucket and we're
            # attempting to iterate a single object, see if we have permission
            # to do a get on that object alone.
            if (not ContainsWildcard(self.wildcard_url.GetUrlString()) and
                self.wildcard_url.IsObject()):
              try:
                get_object = self.gsutil_api.GetObjectMetadata(
                    self.wildcard_url.bucket_name,
                    self.wildcard_url.object_name,
                    generation=self.wildcard_url.generation,
                    provider=self.wildcard_url.scheme,
                    fields=get_fields)
                yield self._GetObjectRef(
                    self.wildcard_url.GetBucketUrlString(), get_object,
                    with_version=(self.all_versions or single_version_request))
              except:
                raise e

  def _BuildBucketFilterStrings(self, wildcard):
    """Builds strings needed for querying a bucket and filtering results.

    This implements wildcard object name matching.

    Args:
      wildcard: The wildcard string to match to objects.

    Returns:
      (prefix, delimiter, prefix_wildcard, suffix_wildcard)
      where:
        prefix is the prefix to be sent in bucket GET request.
        delimiter is the delimiter to be sent in bucket GET request.
        prefix_wildcard is the wildcard to be used to filter bucket GET results.
        suffix_wildcard is wildcard to be appended to filtered bucket GET
          results for next wildcard expansion iteration.
      For example, given the wildcard gs://bucket/abc/d*e/f*.txt we
      would build prefix= abc/d, delimiter=/, prefix_wildcard=d*e, and
      suffix_wildcard=f*.txt. Using this prefix and delimiter for a bucket
      listing request will then produce a listing result set that can be
      filtered using this prefix_wildcard; and we'd use this suffix_wildcard
      to feed into the next call(s) to _BuildBucketFilterStrings(), for the
      next iteration of listing/filtering.

    Raises:
      AssertionError if wildcard doesn't contain any wildcard chars.
    """
    # Generate a request prefix if the object name part of the wildcard starts
    # with a non-wildcard string (e.g., that's true for 'gs://bucket/abc*xyz').
    match = WILDCARD_REGEX.search(wildcard)
    if not match:
      # Input "wildcard" has no wildcard chars, so just return tuple that will
      # cause a bucket listing to match the given input wildcard. Example: if
      # previous iteration yielded gs://bucket/dir/ with suffix_wildcard abc,
      # the next iteration will call _BuildBucketFilterStrings() with
      # gs://bucket/dir/abc, and we will return prefix ='dir/abc',
      # delimiter='/', prefix_wildcard='dir/abc', and suffix_wildcard=''.
      prefix = wildcard
      delimiter = '/'
      prefix_wildcard = wildcard
      suffix_wildcard = ''
    else:
      if match.start() > 0:
        # Wildcard does not occur at beginning of object name, so construct a
        # prefix string to send to server.
        prefix = wildcard[:match.start()]
        wildcard_part = wildcard[match.start():]
      else:
        prefix = None
        wildcard_part = wildcard
      end = wildcard_part.find('/')
      if end != -1:
        wildcard_part = wildcard_part[:end+1]
      # Remove trailing '/' so we will match gs://bucket/abc* as well as
      # gs://bucket/abc*/ with the same wildcard regex.
      prefix_wildcard = StripOneSlash((prefix or '') + wildcard_part)
      suffix_wildcard = wildcard[match.end():]
      end = suffix_wildcard.find('/')
      if end == -1:
        suffix_wildcard = ''
      else:
        suffix_wildcard = suffix_wildcard[end+1:]
      # To implement recursive (**) wildcarding, if prefix_wildcard
      # suffix_wildcard starts with '**' don't send a delimiter, and combine
      # suffix_wildcard at end of prefix_wildcard.
      if prefix_wildcard.find('**') != -1:
        delimiter = None
        prefix_wildcard += suffix_wildcard
        suffix_wildcard = ''
      else:
        delimiter = '/'
    # The following debug output is useful for tracing how the algorithm
    # walks through a multi-part wildcard like gs://bucket/abc/d*e/f*.txt
    if self.debug > 1:
      sys.stderr.write(
          'DEBUG: wildcard=%s, prefix=%s, delimiter=%s, '
          'prefix_wildcard=%s, suffix_wildcard=%s\n' %
          (wildcard, prefix, delimiter, prefix_wildcard, suffix_wildcard))
    return (prefix, delimiter, prefix_wildcard, suffix_wildcard)

  def _SingleVersionMatches(self, listed_generation):
    decoded_generation = GenerationFromUrlAndString(self.wildcard_url,
                                                    listed_generation)
    return str(self.wildcard_url.generation) == str(decoded_generation)

  def _ExpandBucketWildcards(self, bucket_fields=None):
    """Expands bucket and provider wildcards.

    Builds a list of bucket url strings that can be iterated on.

    Args:
      bucket_fields: If present, populate only these metadata fields for
                     buckets.  Example value: ['acl', 'defaultObjectAcl']

    Yields:
      BucketListingRefereneces of type BUCKET.
    """
    if (bucket_fields and set(bucket_fields) == set(['id']) and
        not ContainsWildcard(self.wildcard_url.bucket_name)):
      # If we just want the name of a non-wildcarded bucket URL,
      # don't make an RPC.
      yield BucketListingRef(self.wildcard_url.GetBucketUrlString(),
                             BucketListingRefType.BUCKET)
    elif(self.wildcard_url.IsBucket() and
         not ContainsWildcard(self.wildcard_url.bucket_name)):
      # If we have a non-wildcarded bucket URL, get just that bucket.
      yield BucketListingRef(
          self.wildcard_url.GetBucketUrlString(),
          BucketListingRefType.BUCKET, root_object=self.gsutil_api.GetBucket(
              self.wildcard_url.bucket_name, provider=self.wildcard_url.scheme,
              fields=bucket_fields))
    else:
      regex = fnmatch.translate(self.wildcard_url.bucket_name)
      prog = re.compile(regex)

      fields = self._GetToListFields(bucket_fields)
      if fields:
        fields.add('items/id')
      for bucket in self.gsutil_api.ListBuckets(
          fields=fields, project_id=self.project_id,
          provider=self.wildcard_url.scheme):
        if prog.match(bucket.id):
          url_str = '%s://%s/' % (self.wildcard_url.scheme, bucket.id)
          yield BucketListingRef(url_str, BucketListingRefType.BUCKET,
                                 root_object=bucket)

  def _GetToListFields(self, get_fields=None):
    """Prepends 'items/' to the input fields and converts it to a set.

    This way field sets requested for GetBucket can be used in ListBucket calls.
    Note that the input set must contain only bucket or object fields; listing
    fields such as prefixes or nextPageToken should be added after calling
    this function.

    Args:
      get_fields: Iterable fields usable in GetBucket/GetObject calls.

    Returns:
      Set of fields usable in ListBuckets/ListObjects calls.
    """
    if get_fields:
      list_fields = set()
      for field in get_fields:
        list_fields.add('items/' + field)
      return list_fields

  def _GetObjectRef(self, bucket_url_string, gcs_object, with_version=False):
    """Creates a BucketListingRef of type OBJECT from the arguments.

    Args:
      bucket_url_string: Wildcardless string describing the containing bucket.
      gcs_object: gsutil_api root Object for populating the BucketListingRef.
      with_version: If true, return a reference with a versioned string.

    Returns:
      BucketListingRef of type OBJECT.
    """
    # Generation can be None in test mocks, so just return the
    # live object for simplicity.
    if with_version and gcs_object.generation is not None:
      generation_str = GenerationFromUrlAndString(self.wildcard_url,
                                                  gcs_object.generation)
      object_string = '%s%s#%s' % (bucket_url_string, gcs_object.name,
                                   generation_str)
      return BucketListingRef(object_string,
                              ref_type=BucketListingRefType.OBJECT,
                              root_object=gcs_object)
    else:
      object_string = '%s%s' % (bucket_url_string, gcs_object.name)
      return BucketListingRef(object_string,
                              ref_type=BucketListingRefType.OBJECT,
                              root_object=gcs_object)

  def _GetPrefixRef(self, bucket_url_string, prefix):
    """Creates a BucketListingRef of type PREFIX from the arguments.

    Args:
      bucket_url_string: Wildcardless string describing the containing bucket.
      prefix: gsutil_api Prefix for populating the BucketListingRef

    Returns:
      BucketListingRef of type PREFIX.
    """
    prefix_string = '%s%s' % (bucket_url_string, prefix)
    return BucketListingRef(prefix_string, ref_type=BucketListingRefType.PREFIX,
                            root_object=prefix)

  def IterBuckets(self, bucket_fields=None):
    """Iterates over the wildcard, returning refs for each expanded bucket.

    This ignores the object part of the URL entirely and expands only the
    the bucket portion.  It will yield BucketListingRefs of type BUCKET only.

    Args:
      bucket_fields: Iterable fields to include in bucket listings.
                     Ex. ['defaultObjectAcl', 'logging'].  This function is
                     responsible for converting these to listing-style
                     format ['items/defaultObjectAcl', 'items/logging'], as
                     well as adding any fields necessary for listing such as
                     'items/id'.  API implemenation is responsible for
                     adding pagination fields.  If this is None, all fields are
                     returned.

    Yields:
      BucketListingRef of type BUCKET, or empty iterator if no matches.
    """
    for blr in self._ExpandBucketWildcards(bucket_fields=bucket_fields):
      yield blr

  def IterAll(self, bucket_listing_fields=None, expand_top_level_buckets=False):
    """Iterates over the wildcard, yielding bucket, prefix or object refs.

    Args:
      bucket_listing_fields: If present, populate only these metadata
                             fields for listed objects.
      expand_top_level_buckets: If true and the wildcard expands only to
                                Bucket(s), yields the expansion of each bucket
                                into a top-level listing of prefixes and objects
                                in that bucket instead of a BucketListingRef
                                to that bucket.

    Yields:
      BucketListingRef, or empty iterator if no matches.
    """
    for blr in self. __iter__(
        bucket_listing_fields=bucket_listing_fields,
        expand_top_level_buckets=expand_top_level_buckets):
      yield blr

  def IterObjects(self, bucket_listing_fields=None):
    """Iterates over the wildcard, yielding only object BucketListingRefs.

    Args:
      bucket_listing_fields: If present, populate only these metadata
                             fields for listed objects.

    Yields:
      BucketListingRefs of type OBJECT or empty iterator if no matches.
    """
    for blr in self. __iter__(bucket_listing_fields=bucket_listing_fields,
                              expand_top_level_buckets=True):
      if blr.ref_type == BucketListingRefType.OBJECT:
        yield blr


class FileWildcardIterator(WildcardIterator):
  """WildcardIterator subclass for files and directories.

  If you use recursive wildcards ('**') only a single such wildcard is
  supported. For example you could use the wildcard '**/*.txt' to list all .txt
  files in any subdirectory of the current directory, but you couldn't use a
  wildcard like '**/abc/**/*.txt' (which would, if supported, let you find .txt
  files in any subdirectory named 'abc').
  """

  def __init__(self, wildcard_url, debug=0):
    """Instantiates an iterator over BucketListingRefs matching wildcard URL.

    Args:
      wildcard_url: FileUrl that contains the wildcard to iterate.
      debug: Debug level (range 0..3).
    """
    self.wildcard_url = wildcard_url
    self.debug = debug

  def __iter__(self):
    """Iterator that gets called when iterating over the file wildcard.

    In the case where no wildcard is present, returns a single matching file
    or directory.

    Raises:
      WildcardException: if invalid wildcard found.

    Yields:
      BucketListingRef of type OBJECT (for files) or PREFIX (for directories)
    """
    wildcard = self.wildcard_url.object_name
    match = FLAT_LIST_REGEX.match(wildcard)
    if match:
      # Recursive wildcarding request ('.../**/...').
      # Example input: wildcard = '/tmp/tmp2pQJAX/**/*'
      base_dir = match.group('before')[:-1]
      remaining_wildcard = match.group('after')
      # At this point for the above example base_dir = '/tmp/tmp2pQJAX' and
      # remaining_wildcard = '/*'
      if remaining_wildcard.startswith('*'):
        raise WildcardException('Invalid wildcard with more than 2 consecutive '
                                '*s (%s)' % wildcard)
      # If there was no remaining wildcard past the recursive wildcard,
      # treat it as if it were a '*'. For example, file://tmp/** is equivalent
      # to file://tmp/**/*
      if not remaining_wildcard:
        remaining_wildcard = '*'
      # Skip slash(es).
      remaining_wildcard = remaining_wildcard.lstrip(os.sep)
      filepaths = self._IterDir(base_dir, remaining_wildcard)
    else:
      # Not a recursive wildcarding request.
      filepaths = glob.iglob(wildcard)
    for filepath in filepaths:
      expanded_url = StorageUrlFromString(filepath)
      if os.path.isdir(filepath):
        yield BucketListingRef(expanded_url.GetUrlString(),
                               ref_type=BucketListingRefType.PREFIX)
      else:
        yield BucketListingRef(expanded_url.GetUrlString(),
                               ref_type=BucketListingRefType.OBJECT)

  def _IterDir(self, directory, wildcard):
    """An iterator over the specified dir and wildcard."""
    for dirpath, unused_dirnames, filenames in os.walk(directory):
      for f in fnmatch.filter(filenames, wildcard):
        yield os.path.join(dirpath, f)

  # pylint: disable=unused-argument
  def IterObjects(self, bucket_listing_fields=None):
    """Iterates over the wildcard, yielding only object (file) refs.

    Args:
      bucket_listing_fields: Ignored as filesystems don't have buckets.

    Yields:
      BucketListingRefs of type OBJECT or empty iterator if no matches.
    """
    for bucket_listing_ref in self.IterAll():
      if bucket_listing_ref.ref_type == BucketListingRefType.OBJECT:
        yield bucket_listing_ref

  # pylint: disable=unused-argument
  def IterAll(self, bucket_listing_fields=None, expand_top_level_buckets=False):
    """Iterates over the wildcard, yielding BucketListingRefs.

    Args:
      bucket_listing_fields: Ignored; filesystems don't have buckets.
      expand_top_level_buckets: Ignored; filesystems don't have buckets.

    Yields:
      BucketListingRefs of type OBJECT (file) or PREFIX (directory),
      or empty iterator if no matches.
    """
    for bucket_listing_ref in self.__iter__():
      yield bucket_listing_ref

  def IterBuckets(self, unused_bucket_fields=None):
    """Placeholder to allow polymorphic use of WildcardIterator.

    Args:
      unused_bucket_fields: Ignored; filesystems don't have buckets.

    Raises:
      WildcardException: in all cases.
    """
    raise WildcardException(
        'Iterating over Buckets not possible for file wildcards')


class WildcardException(StandardError):
  """Exception raised for invalid wildcard URLs."""

  def __init__(self, reason):
    StandardError.__init__(self)
    self.reason = reason

  def __repr__(self):
    return 'WildcardException: %s' % self.reason

  def __str__(self):
    return 'WildcardException: %s' % self.reason


def CreateWildcardIterator(url_str, gsutil_api, all_versions=False, debug=0,
                           project_id=None):
  """Instantiate a WildcardIterator for the given URL string.

  Args:
    url_str: URL string naming wildcard object(s) to iterate.
    gsutil_api: Cloud storage interface.  Passed in for thread safety, also
                settable for testing/mocking.
    all_versions: If true, the iterator yields all versions of objects
                  matching the wildcard.  If false, yields just the live
                  object version.
    debug: Debug level to control debug output for iterator.
    project_id: Project id to use for bucket listings.

  Returns:
    A WildcardIterator that handles the requested iteration.
  """

  url = StorageUrlFromString(url_str)
  if url.IsFileUrl():
    return FileWildcardIterator(url, debug=debug)
  else:  # Cloud URL
    return CloudWildcardIterator(
        url, gsutil_api, all_versions=all_versions, debug=debug,
        project_id=project_id)
