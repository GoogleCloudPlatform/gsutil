# Copyright 2010 Google Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish, dis-
# tribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the fol-
# lowing conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABIL-
# ITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT
# SHALL THE AUTHOR BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.

"""Implementation of wildcarding over StorageUris.

StorageUri is an abstraction that Google introduced in the boto library,
for representing storage provider-independent bucket and object names with
a shorthand URI-like syntax (see boto/boto/storage_uri.py) The current
class provides wildcarding support for StorageUri objects (including both
bucket and file system objects), allowing one to express collections of
objects with syntax like the following:
  gs://mybucket/images/*.png
  file:///tmp/???abc???

We provide wildcarding support as part of gsutil rather than as part
of boto because wildcarding is really part of shell command-like
functionality.

A comment about wildcard semantics: In a hierarchical file system it's common
to distinguish recursive from single path component wildcards (e.g., using
'**' for the former and '*' for the latter). For example,
  /opt/eclipse/*/*.html
would enumerate HTML files one directory down from /opt/eclipse, while
  /opt/eclipse/**/*.html
would enumerate HTML files in all subdirectories of /opt/eclipse. We provide
'**' wildcarding support for file system directories but '*' and '**' behave
the same for bucket URIs because the bucket namespace is flat (i.e.,
there's no meaningful distinction between '*' and '**' for buckets).
Thus, for example, if you were to upload data using the following command:
  % gsutil cp /opt/eclipse/**/*.sh gs://bucket/eclipse
it would create a set of objects mirroring the filename hierarchy, and
the following two commands would yield identical results:
  % gsutil ls gs://bucket/eclipse/*/*.html
  % gsutil ls gs://bucket/eclipse/**/*.html

Note also that if you use file system wildcards it's likely your shell
interprets the wildcarding before passing the command to gsutil. For example:
  % gsutil cp /opt/eclipse/*/*.html gs://bucket/eclipse
would likely be expanded by the shell into the following before running gsutil:
  % gsutil cp /opt/eclipse/RUNNING.html gs://bucket/eclipse

Note also that some shells (e.g., bash) don't support '**' wildcarding. If
you want to use '**' wildcarding with such a shell you can single quote
each wildcarded string, so it gets passed uninterpreted by the shell to
gsutil (at which point gsutil will perform the wildcarding expansion):
  % gsutil cp '/opt/eclipse/**/*.html' gs://bucket/eclipse
"""

import fnmatch
import glob
import os
import re
import boto
from boto.storage_uri import StorageUri


# Enum class for specifying what to return from each iteration.
class ResultType(object):
  KEYS = 'KEYS'
  URIS = 'URIS'


class WildcardIterator(object):
  """Base class for wildcarding over StorageUris.

  This class implements support for iterating over StorageUris that
  contain wildcards, such as 'gs://bucket/abc*' and 'file://directory/abc*'.

  The base class is abstract; you should instantiate using the
  wildcard_iterator() static factory method, which chooses the right
  implementation depending on the StorageUri.
  """

  def __init__(self, uri, result_type, headers=None, debug=False):
    """Instantiate an iterator over keys matching given wildcard URI.

    Args:
      uri: StorageUri naming wildcard objects to iterate.
      result_type: ResultType object specifying what to iterate.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: flag indicating whether to include debug output.

    Raises:
      WildcardException: for invalid result_type.
    """
    self.uri = uri
    self.result_type = result_type
    if result_type != ResultType.KEYS and result_type != ResultType.URIS:
      raise WildcardException('Invalid ResultType (%s)' % result_type)
    self.headers = headers
    self.debug = debug

  def __repr__(self):
    """Returns string representation of WildcardIterator."""
    return 'WildcardIterator(%s, %s)' % (self.uri, self.result_type)


class BucketWildcardIterator(WildcardIterator):
  """WildcardIterator subclass for buckets and objects.

  Iterates over Keys or URIs matching the StorageUri wildcard. It's more
  efficient to use this method to iterate keys if you want to get metadata
  that's available in the Bucket (for example to get the name and size of
  each object), because that information is available in the bucket GET
  results. If you were to iterate over URIs for such cases and then get
  the name and size info from each resulting StorageUri, it would cause
  an additional object GET request for each of the result URIs.
  """

  def __NeededResultType(self, obj, uri):
    """Helper function to generate needed ResultType, per constructor param.

    Args:
      obj: Key form of object to return, or None if not available.
      uri: StorageUri form of object to return.

    Returns:
      StorageUri or subclass of boto.s3.key.Key, depending on constructor param.

    Raises:
      WildcardException: for bucket-only uri with ResultType.KEYS.
      Exception: for object-level uri with ResultType.KEYS and obj=None.
    """
    if self.result_type == ResultType.KEYS:
      if not obj:
        if not uri.object_name:
          raise WildcardException('Bucket-only URI (%s) with ResultType.KEYS '
                                  'iteration request' % uri)
        else:
          # Raise Exception (not CommandException) in this case because
          # this represents a code bug and we want to be able to see a
          # stack trace (using gsutil -D) in this case.
          raise Exception('__NeededResultType: Got ResultType.KEYS '
                          'iteration request with no obj for uri %s.' % uri)
      return obj
    else:
      # ResultType.URIS:
      return uri

  def __iter__(self):
    some_matched = False
    # First handle bucket wildcarding, if any.
    if ContainsWildcard(self.uri.bucket_name):
      regex = fnmatch.translate(self.uri.bucket_name)
      bucket_uris = []
      for b in self.uri.get_all_buckets():
        if re.match(regex, b.name):
          # Use str(b.name) because get_all_buckets() returns Unicode
          # string, which when used to construct x-goog-copy-src metadata
          # requests for object-to-object copies, causes pathname '/' chars
          # to be entity-encoded (bucket%2Fdir instead of bucket/dir),
          # which causes the request to fail.
          bucket_uris.append(boto.storage_uri('%s://%s' %
                                              (self.uri.scheme, str(b.name))))
    else:
      bucket_uris = [self.uri.clone_replace_name('')]

    # Now iterate over bucket(s), and handle object wildcarding, if any.
    for bucket_uri in bucket_uris:
      if not self.uri.object_name:
        # Bucket-only URI.
        some_matched = True
        yield self.__NeededResultType(None, bucket_uri)
      else:
        # URI contains an object name. If there's no wildcard just yield
        # the needed URI.
        if not ContainsWildcard(self.uri.object_name):
          some_matched = True
          yield self.__NeededResultType(None, self.uri)
        else:
          # Add the input URI's object name part to the bucket we're
          # currently listing. For example if the request was to iterate
          # gs://*/*.txt, bucket_uris will contain a list of all the user's
          # buckets, and for each we'll add *.txt to the end so we iterate
          # the matching files from each bucket in turn.
          uri_to_list = bucket_uri.clone_replace_name(self.uri.object_name)
          # URI contains an object wildcard.
          for obj in self.__ListObjsInBucket(uri_to_list):
            regex = fnmatch.translate(self.uri.object_name)
            if re.match(regex, obj.name):
              some_matched = True
              expanded_uri = uri_to_list.clone_replace_name(obj.name)
              yield self.__NeededResultType(obj, expanded_uri)

    if not some_matched:
      raise WildcardException('No matches for "%s"' % self.uri)

  def __ListObjsInBucket(self, uri):
    """Helper function to get a list of objects in a bucket.

    This function does not provide the complete wildcard match; instead
    it uses the server request prefix (if applicable) to reduce server
    and network load and returns the underlying boto bucket iterator,
    against which remaining wildcard filtering must be applied by the
    caller. For example, for StorageUri('gs://bucket/abc*xyz') this
    method returns the iterator from doing a prefix='abc' bucket GET
    request; and subsequently a regex needs to be applied to subset the
    'abc'-prefix matches down to the subset matching 'abc*xyz'.

    Args:
      uri: StorageUri to list.

    Returns:
      An instance of a boto.s3.BucketListResultSet that handles paging, etc.
    """

    # Generate a request prefix if the object name part of the
    # wildcard starts with a non-regex string (e.g., that's true for
    # 'gs://bucket/abc*xyz').
    match = ContainsWildcard(uri.object_name)
    if match and match.start() > 0:
      # Glob occurs at beginning of object name, so construct a prefix
      # string to send to server.
      prefix = uri.object_name[:match.start()]
    else:
      prefix = None
    return uri.get_bucket(validate=False,
                          headers=self.headers).list(prefix=prefix,
                                                     headers=self.headers)


class FileWildcardIterator(WildcardIterator):
  """WildcardIterator subclass for files and directories."""

  def __iter__(self):
    wildcard = self.uri.object_name
    match = re.search('\*\*', wildcard)
    if match:
      # Recursive wildcarding request ('.../**/...').
      # Example input: wildcard = '/tmp/tmp2pQJAX/**/*'
      base_dir = wildcard[:match.start()-1]
      remaining_wildcard = wildcard[match.start()+2:]
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
      remaining_wildcard = remaining_wildcard.lstrip('/')
      filepaths = []
      for dirpath, unused_dirnames, filenames in os.walk(base_dir):
        filepaths.extend(
            os.path.join(dirpath, f) for f in fnmatch.filter(filenames,
                                                             remaining_wildcard)
        )
    else:
      # Not a recursive wildcarding request.
      filepaths = glob.glob(wildcard)
    if not filepaths:
      raise WildcardException('No matches for "%s"' % wildcard)
    for filename in filepaths:
      expanded_uri = self.uri.clone_replace_name(filename)
      yield expanded_uri


class WildcardException(StandardError):
  """Exception thrown for invalid wildcard URIs."""

  def __init__(self, reason):
    StandardError.__init__(self)
    self.reason = reason

  def __repr__(self):
    return 'WildcardException: %s' % self.reason

  def __str__(self):
    return 'WildcardException: %s' % self.reason


def wildcard_iterator(uri_or_str, result_type, headers=None, debug=False):
  """Instantiate a WildCardIterator for the given StorageUri.

  Args:
    uri_or_str: StorageUri or URI string naming wildcard objects to iterate.
    result_type: ResultType object specifying what to iterate.
    headers: dictionary containing optional HTTP headers to pass to boto.
    debug: flag indicating whether to include debug output.

  Returns:
    A WildcardIterator that handles the requested iteration.

  Raises:
    WildcardException: if invalid result_type.
  """

  if isinstance(uri_or_str, StorageUri):
    uri = uri_or_str
  else:
    # Disable enforce_bucket_naming, to allow bucket names containing
    # wildcard chars.
    uri = boto.storage_uri(uri_or_str, debug=debug, validate=False)

  if uri.is_cloud_uri():
    return BucketWildcardIterator(uri, result_type, headers=headers,
                                  debug=debug)
  elif uri.is_file_uri():
    return FileWildcardIterator(uri, result_type, headers=headers, debug=debug)
  else:
    raise WildcardException('Unexpected type of StorageUri (%s)' % uri)


def ContainsWildcard(uri_str):
  """Checks whether given URI contains a wildcard.

  Args:
    uri_str: string to check.

  Returns:
    True or False.
  """

  return re.search('[*?\[\]]', uri_str)
