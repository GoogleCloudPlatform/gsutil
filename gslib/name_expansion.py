# Copyright 2012 Google Inc.
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
import itertools
import wildcard_iterator

from gslib.storage_uri_builder import StorageUriBuilder
from wildcard_iterator import ContainsWildcard
from bucket_listing_ref import BucketListingRef

"""
Name expansion support for the various ways gsutil lets users refer to
collections of data (via explicit wildcarding as well as directory,
bucket, and bucket subdir implicit wildcarding). This class encapsulates
the various rules for determining how these expansions are done.
"""


class NameExpansionResult(object):
  """
  Holds results of calls to NameExpansionHandler.ExpandWildcardsAndContainers().
  """
  # Currently we build a dict (self._expansion_map) to hold the expansion
  # results instead of using a generator to iterate incrementally
  # because the caller needs to know the count before iterating and
  # performing copy operations (in order to determine if this is a
  # multi-source copy request). That limits the scalability of wildcard
  # iteration, since the entire expansion needs to fit in memory (see
  # http://code.google.com/p/gsutil/issues/detail?id=80).
  # TODO: Rework NameExpansionResult to save
  #   {StorageUri: generator of BucketListingRefs to which it expands}
  # and change the accessor functions to determine if expansion has
  # length > 1 without first
  # NameExpansionResult.IterExpandedBucketListingRefsFor() and
  # NameExpansionResult.SrcUriExpandsToMultipleSources() to work without ever
  # materializing the list.

  def __init__(self):
    # dict {StorageUri: [BucketListingRefs to which it expands]}
    # Note: in the future we'll change RHS to be an iterator from the
    # underlying generator supported by WildcardIterator, for scalabilty.
    self._expansion_map = {}
    # dict {StorageUri: bool indicator of whether src_uri names a container}
    #   where names_container is true if URI names a directory, bucket, or
    #   bucket subdir (vs how StorageUri.names_container() doesn't handle
    #   latter case).
    self._names_container_map = {}

  def __repr__(self):
    return self._expansion_map.__repr__()

  def _AddExpansion(self, src_uri, names_container,
                    expanded_bucket_listing_refs):
    """
    Args:
      src_uri: StorageUri.
      names_container: bool indicator whether src_uri names a container.
      expanded_bucket_listing_refs: [BucketListingRef] to which src_uri expands.
    """
    self._expansion_map[src_uri] = expanded_bucket_listing_refs
    self._names_container_map[src_uri] = names_container

  def IsEmpty(self):
    """Returns True if name expansion yielded no matches."""
    for v in self._expansion_map.values():
      if v:
        return False
    return True

  def NamesContainer(self, src_uri):
    """Returns bool indicator of whether src_uri names a directory, bucket, or
       bucket subdir.
    """
    return self._names_container_map[src_uri]

  def GetSrcUris(self):
    """Returns the list of src_uri's for which name expansion was requested."""
    return self._expansion_map.keys()

  # Note: We return iterators from the following functinos
  # instead of the underlying lists so we can later replace
  # this representation with a generator implementation to fix
  # http://code.google.com/p/gsutil/issues/detail?id=80.

  def IterExpandedBucketListingRefsFor(self, src_uri):
    """
    Returns an iterator of BucketListingRefs to which the given src_uri
    expanded.
    """
    return iter(self._expansion_map[src_uri])

  def IterExpandedBucketListingRefs(self):
    """
    Returns an iterator of all BucketListingRefs (across all src_uris that were
    expanded) from this NameExpansionResult.
    """
    #result = []
    #for exp_list in self._expansion_map.values():
    #  result.extend(exp_list)
    #  return iter(result)
    list_of_iters = []
    for src_uri in self._expansion_map:
      list_of_iters.extend(self._expansion_map[src_uri])
    return itertools.chain(list_of_iters)

  def __iter__(self):
    return self.IterExpandedBucketListingRefs()

  def IterExpandedUris(self):
    """
    Returns an iterator of all StorageUris (across all src_uris that were
    expanded) from this NameExpansionResult.
    """
    result = []
    for bucket_listing_ref in self.IterExpandedBucketListingRefs():
      result.append(bucket_listing_ref.GetUri())
    return iter(result)

  def IterExpandedUriStrings(self):
    """
    Returns an iterator of all URI strings (across all src_uris that were
    expanded) from this NameExpansionResult.
    """
    result = []
    for bucket_listing_ref in self.IterExpandedBucketListingRefs():
      result.append(bucket_listing_ref.GetUriString())
    return iter(result)

  def IterExpandedKeys(self):
    """
    Returns an iterator of all Keys (across all src_uris that were expanded)
    from this NameExpansionResult.
    """
    result = []
    for bucket_listing_ref in self.IterExpandedBucketListingRefs():
      result.append(bucket_listing_ref.GetKey())
    return iter(result)

  def IsMultiSrcRequest(self):
    """Returns True if this name expansion resulted in more than 1 URI."""
    if len(self._expansion_map) == 0:
      return False
    return (len(self._expansion_map) > 1
            or len(self._expansion_map.values()[0]) > 1)

  def SrcUriExpandsToMultipleSources(self, src_uri):
    """
    Checks that src_uri names a singleton (file or object) after
    dir/wildcard expansion. The decision is more nuanced than simply
    src_uri.names_singleton()) because of the possibility that an object path
    might name a bucket "sub-directory", which in turn depends on whether
    src_uri expanded to multiple URIs.  For example, when running the command:
      gsutil cp -R gs://bucket/abc ./dir
    gs://bucket/abc would be an object if nothing matches gs://bucket/abc/*;
    but would be a bucket subdir otherwise.

    Args:
      src_uri: StorageUri to check.

    Returns:
      bool indicator.
    """
    return len(self._expansion_map[src_uri]) > 1


class NameExpansionHandler(object):

  def __init__(self, command_name, proj_id_handler, headers, debug,
               bucket_storage_uri_class):
    """
    Args:
      command_name: name of command being run.
      proj_id_handler: ProjectIdHandler to use for current command.
      headers: Dictionary containing optional HTTP headers to pass to boto.
      debug: Debug level to pass in to boto connection (range 0..3).
      bucket_storage_uri_class: Class to instantiate for cloud StorageUris.
          Settable for testing/mocking.
    """
    self.command_name = command_name
    self.proj_id_handler = proj_id_handler
    self.headers = headers
    self.debug = debug
    self.bucket_storage_uri_class = bucket_storage_uri_class
    self.suri_builder = StorageUriBuilder(debug, bucket_storage_uri_class)

    # Map holding wildcard strings to use for flat vs subdir-by-subdir listings.
    # (A flat listing means show all objects expanded all the way down.)
    self._flatness_wildcard = {True: '**', False: '*'}

  def WildcardIterator(self, uri_or_str):
    """
    Helper to instantiate gslib.WildcardIterator. Args are same as
    gslib.WildcardIterator interface, but this method fills in most of the
    values from class state.

    Args:
      uri_or_str: StorageUri or URI string naming wildcard objects to iterate.
    """
    return wildcard_iterator.wildcard_iterator(
        uri_or_str, self.proj_id_handler,
        bucket_storage_uri_class=self.bucket_storage_uri_class,
        headers=self.headers, debug=self.debug)

  def ExpandWildcardsAndContainers(self, uri_strs, recursion_requested,
                                   flat=True):
    """
    Expands wildcards, object-less bucket names, subdir bucket names, and
    directory names, producing a flat listing of all the matching objects/files.

    Args:
      uri_strs: List of URI strings needing expansion.
      recursion_requested: True if -R specified on command-line.
      flat: Bool indicating whether bucket listings should be flattened, i.e.,
          so the mapped-to results contain objects spanning subdirectories.

    Returns:
      gslib.name_expansion.NameExpansionResult.

    Raises:
      CommandException: if errors encountered.

    Examples with flat=True:
      - Calling with one of the uri_strs being 'gs://bucket' will enumerate all
        top-level objects, as will 'gs://bucket/' and 'gs://bucket/*'.
      - 'gs://bucket/**' will enumerate all objects in the bucket.
      - 'gs://bucket/abc' will enumerate all next-level objects under directory
        abc (i.e., not including subdirectories of abc) if gs://bucket/abc/*
        matches any objects; otherwise it will enumerate the single name
        gs://bucket/abc
      - 'gs://bucket/abc/**' will enumerate all objects under abc or any of its
        subdirectories.
      - 'file:///tmp' will enumerate all files under /tmp, as will
        'file:///tmp/*'
      - 'file:///tmp/**' will enumerate all files under /tmp or any of its
        subdirectories.

    Example if flat=False: calling with gs://bucket/abc/* lists matching objects
    or subdirs, but not sub-subdirs or objects beneath subdirs.

    Note: In step-by-step comments below we give examples assuming there's a
    gs://bucket with object paths:
      abcd/o1.txt
      abcd/o2.txt
      xyz/o1.txt
      xyz/o2.txt
    and a directory file://dir with file paths:
      dir/a.txt
      dir/b.txt
      dir/c/
    """
    result = NameExpansionResult()
    for uri_str in uri_strs:

      # Step 1: Expand any explicitly specified wildcards.
      # Starting with gs://buck*/abc* this step would expand to gs://bucket/abcd
      if ContainsWildcard(uri_str):
        post_step1_bucket_listing_refs = list(self.WildcardIterator(uri_str))
      else:
        post_step1_bucket_listing_refs = [
            BucketListingRef(self.suri_builder.StorageUri(uri_str))]

      # Step 2: Expand subdirs.
      # Starting with gs://bucket/abcd this step would expand to:
      #   [abcd/o1.txt, abcd/o2.txt].
      uri_names_container = False
      if flat:
        if recursion_requested:
          post_step2_bucket_listing_refs = []
          for bucket_listing_ref in post_step1_bucket_listing_refs:
            (uri_names_container, bucket_listing_refs) = (
                self._DoImplicitBucketSubdirExpansionIfApplicable(
                    bucket_listing_ref.GetUri(), flat))
            post_step2_bucket_listing_refs.extend(bucket_listing_refs)
        else:
          uri_names_container = False
          post_step2_bucket_listing_refs = post_step1_bucket_listing_refs
      else:
        uri_names_container = False
        post_step2_bucket_listing_refs = post_step1_bucket_listing_refs

      # Step 3. Expand directories and buckets.
      # Starting with gs://bucket this step would expand to:
      #  [abcd/o1.txt, abcd/o2.txt, xyz/o1.txt, xyz/o2.txt]
      # Starting with file://dir this step would expand to:
      #  [dir/a.txt, dir/b.txt, dir/c/]
      exp_src_bucket_listing_refs = []
      wc = self._flatness_wildcard[flat]
      for bucket_listing_ref in post_step2_bucket_listing_refs:
        if (not bucket_listing_ref.GetUri().names_container()
            and (flat or not bucket_listing_ref.HasPrefix())):
          exp_src_bucket_listing_refs.append(bucket_listing_ref)
          continue
        if not recursion_requested:
          if bucket_listing_ref.GetUri().is_file_uri():
            desc = 'directory'
          else:
            desc = 'bucket'
          print 'Omitting %s "%s". (Did you mean to do %s -R?)' % (
              desc, bucket_listing_ref.GetUri(), self.command_name)
          continue
        uri_names_container = True
        if bucket_listing_ref.GetUri().is_file_uri():
          # Convert dir to implicit recursive wildcard.
          uri_to_iter = '%s/%s' % (bucket_listing_ref.GetUriString(), wc)
        else:
          # Convert bucket to implicit recursive wildcard.
          uri_to_iter = bucket_listing_ref.GetUri().clone_replace_name(wc)
        wildcard_result = list(self.WildcardIterator(uri_to_iter))
        if len(wildcard_result) > 0:
          exp_src_bucket_listing_refs.extend(wildcard_result)

      result._AddExpansion(self.suri_builder.StorageUri(uri_str),
                           uri_names_container,
                           exp_src_bucket_listing_refs)

    return result

  def _DoImplicitBucketSubdirExpansionIfApplicable(self, uri, flat):
    """
    Checks whether uri could be an implicit bucket subdir, and expands if so;
    else returns list containing uri. For example gs://abc would be an implicit
    bucket subdir if the -R option was specified and gs://abc/* matches
    anything.
    Can only be called for -R (recursion requested).

    Args:
      uri: StorageUri.
      flat: bool indicating whether bucket listings should be flattened, i.e.,
          so the mapped-to results contain objects spanning subdirectories.

    Returns:
      tuple (names_container, [BucketListingRefs to which uri expanded])
        where names_container is true if URI names a directory, bucket,
        or bucket subdir (vs how StorageUri.names_container() doesn't
        handle latter case).
    """
    names_container = False
    result_list = []
    if uri.names_object():
      # URI could be a bucket subdir.
      implicit_subdir_matches = list(self.WildcardIterator(
          self.suri_builder.StorageUri('%s/%s' % (uri.uri.rstrip('/'),
                                       self._flatness_wildcard[flat]))))
      if len(implicit_subdir_matches) > 0:
        names_container = True
        result_list.extend(implicit_subdir_matches)
      else:
        result_list.append(BucketListingRef(uri))
    else:
      result_list.append(BucketListingRef(uri))
    return (names_container, result_list)

  def StorageUri(self, uri_str):
    """
    Helper to instantiate boto.StorageUri with gsutil default flag values.
    Uses self.bucket_storage_uri_class to support mocking/testing.
    (Identical to the same-named function in command.py; that and this
    copy make it convenient to call StorageUri() with a single argument,
    from the respective classes.)

    Args:
      uri_str: StorageUri naming bucket + optional object.

    Returns:
      boto.StorageUri for given uri_str.

    Raises:
      InvalidUriError: if uri_str not valid.
    """
    return gslib.util.StorageUri(uri_str, self.bucket_storage_uri_class,
                                 self.debug)
