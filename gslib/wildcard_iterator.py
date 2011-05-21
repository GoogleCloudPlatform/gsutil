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
  % gsutil cp -r /opt/eclipse gs://bucket/eclipse
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
import time
import urllib
import boto
from boto.storage_uri import BucketStorageUri

WILDCARD_REGEX = re.compile('[*?\[\]]')
WILDCARD_OBJECT_ITERATOR = 'wildcard_object_iterator'
WILDCARD_BUCKET_ITERATOR = 'wildcard_bucket_iterator'


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

  def __repr__(self):
    """Returns string representation of WildcardIterator."""
    return 'WildcardIterator(%s, %s)' % (self.wildcard_uri, self.result_type)


class CloudWildcardIterator(WildcardIterator):
  """WildcardIterator subclass for buckets and objects.

  Iterates over Keys or URIs matching the StorageUri wildcard. It's more
  efficient to use this method to iterate keys if you want to get metadata
  that's available in the Bucket (for example to get the name and size of
  each object), because that information is available in the bucket GET
  results. If you were to iterate over URIs for such cases and then get
  the name and size info from each resulting StorageUri, it would cause
  an additional object GET request for each of the result URIs.
  """

  def __init__(self, wildcard_uri, proj_id_handler, result_type,
               bucket_storage_uri_class=BucketStorageUri,
               headers=None, debug=0):
    """Instantiate an iterator over keys matching given wildcard URI.

    Args:
      wildcard_uri: StorageUri that contains the wildcard to iterate.
      proj_id_handler: ProjectIdHandler to use for current command.
      result_type: ResultType object specifying what to iterate.
      bucket_storage_uri_class: BucketStorageUri interface.
                                Settable for testing/mocking.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: debug level to pass in to boto connection (range 0..3).

    Raises:
      WildcardException: for invalid result_type.
    """
    self.wildcard_uri = wildcard_uri
    self.result_type = result_type
    if result_type != ResultType.KEYS and result_type != ResultType.URIS:
      raise WildcardException('Invalid ResultType (%s)' % result_type)
    # Make a copy of the headers so any updates we make during wildcard
    # expansion aren't left in the input params (specifically, so we don't
    # include the x-goog-project-id header needed by a subset of cases, in
    # the data returned to caller, which could then be used in other cases
    # where that header must not be passed).
    self.headers = headers.copy()
    self.proj_id_handler = proj_id_handler
    self.debug = debug
    self.bucket_storage_uri_class = bucket_storage_uri_class

  def __NeededResultType(self, obj, uri, headers):
    """Helper function to generate needed ResultType, per constructor param.

    Args:
      obj: Key form of object to return, or None if not available.
      uri: StorageUri form of object to return.
      headers: dictionary containing optional HTTP headers to pass to boto.

    Returns:
      StorageUri or subclass of boto.s3.key.Key, depending on constructor param.

    Raises:
      WildcardException: for bucket-only uri with ResultType.KEYS.
    """
    if self.result_type == ResultType.URIS:
      return uri
    # Else ResultType.KEYS.
    if not obj:
      if not uri.object_name:
        raise WildcardException('Bucket-only URI (%s) with ResultType.KEYS '
                                'iteration request' % uri)
      # This case happens when we do gsutil ls -l on a object name-ful
      # StorageUri with no object-name wildcard. Since the ListCommand
      # implementation only reads bucket info we need to read the object
      # for this case.
      obj = uri.get_key(validate=False, headers=headers)
      # When we retrieve the object this way its last_modified timestamp
      # is formatted in RFC 1123 format, which is different from when we
      # retrieve from the bucket listing (which uses ISO 8601 format), so
      # convert so we consistently return ISO 8601 format.
      tuple_time = (time.strptime(obj.last_modified, '%a, %d %b %Y %H:%M:%S %Z'))
      obj.last_modified = time.strftime('%Y-%m-%dT%H:%M:%S', tuple_time)
    return obj

  def __iter__(self):
    """Python iterator that gets called when iterating over cloud wildcard.

    Yields:
      StorageUri or Key, per constructor param.

    Raises:
      WildcardException: If there were no matches for the given wildcard.
    """
    some_matched = False
    # First handle bucket wildcarding, if any.
    if ContainsWildcard(self.wildcard_uri.bucket_name):
      regex = fnmatch.translate(self.wildcard_uri.bucket_name)
      bucket_uris = []
      prog = re.compile(regex)
      self.proj_id_handler.FillInProjectHeaderIfNeeded(WILDCARD_BUCKET_ITERATOR,
                                                       self.wildcard_uri,
                                                       self.headers)
      for b in self.wildcard_uri.get_all_buckets(headers=self.headers):
        if prog.match(b.name):
          # Use str(b.name) because get_all_buckets() returns Unicode
          # string, which when used to construct x-goog-copy-src metadata
          # requests for object-to-object copies, causes pathname '/' chars
          # to be entity-encoded (bucket%2Fdir instead of bucket/dir),
          # which causes the request to fail.
          uri_str = '%s://%s' % (self.wildcard_uri.scheme,
                                 urllib.quote_plus(str(b.name)))
          bucket_uris.append(
              boto.storage_uri(
                  uri_str, debug=self.debug,
                  bucket_storage_uri_class=self.bucket_storage_uri_class))
    else:
      bucket_uris = [self.wildcard_uri.clone_replace_name('')]

    # Now iterate over bucket(s), and handle object wildcarding, if any.
    self.proj_id_handler.FillInProjectHeaderIfNeeded(WILDCARD_OBJECT_ITERATOR,
                                                     self.wildcard_uri,
                                                     self.headers)
    for bucket_uri in bucket_uris:
      if not self.wildcard_uri.object_name:
        # Bucket-only URI.
        some_matched = True
        yield self.__NeededResultType(None, bucket_uri, self.headers)
      else:
        # URI contains an object name. If there's no wildcard just yield
        # the needed URI.
        if not ContainsWildcard(self.wildcard_uri.object_name):
          some_matched = True
          uri_to_yield = bucket_uri.clone_replace_name(
              self.wildcard_uri.object_name)
          yield self.__NeededResultType(None, uri_to_yield, self.headers)
        else:
          # Add the input URI's object name part to the bucket we're
          # currently listing. For example if the request was to iterate
          # gs://*/*.txt, bucket_uris will contain a list of all the user's
          # buckets, and for each we'll add *.txt to the end so we iterate
          # the matching files from each bucket in turn.
          uri_to_list = bucket_uri.clone_replace_name(
              self.wildcard_uri.object_name)
          # URI contains an object wildcard.
          for obj in self.__ListObjsInBucket(uri_to_list):
            regex = fnmatch.translate(self.wildcard_uri.object_name)
            prog = re.compile(regex)
            if prog.match(obj.name):
              some_matched = True
              expanded_uri = uri_to_list.clone_replace_name(obj.name)
              yield self.__NeededResultType(obj, expanded_uri, self.headers)

    if not some_matched:
      raise WildcardException('No matches for "%s"' % self.wildcard_uri)

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
    match = WILDCARD_REGEX.search(uri.object_name)
    if match and match.start() > 0:
      # Glob occurs at beginning of object name, so construct a prefix
      # string to send to server.
      prefix = uri.object_name[:match.start()]
    else:
      prefix = None
    return uri.get_bucket(validate=False, headers=self.headers).list(
        prefix=prefix, headers=self.headers)


class FileWildcardIterator(WildcardIterator):
  """WildcardIterator subclass for files and directories.

  If you use recursive wildcards ('**') only a single such wildcard is
  supported. For example you could use the wildcard '**/*.txt' to list all .txt
  files in any subdirectory of the current directory, but you couldn't use a
  wildcard like '**/abc/**/*.txt' (which would, if supported, let you find .txt
  files in any subdirectory named 'abc').
  """

  def __init__(self, wildcard_uri, result_type, headers=None, debug=0):
    """Instantiate an iterator over keys matching given wildcard URI.

    Args:
      wildcard_uri: StorageUri that contains the wildcard to iterate.
      result_type: ResultType object specifying what to iterate.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: debug level to pass in to boto connection (range 0..3).

    Raises:
      WildcardException: for invalid result_type.
    """
    self.wildcard_uri = wildcard_uri
    self.result_type = result_type
    if result_type != ResultType.KEYS and result_type != ResultType.URIS:
      raise WildcardException('Invalid ResultType (%s)' % result_type)
    self.headers = headers
    self.debug = debug

  def __iter__(self):
    wildcard = self.wildcard_uri.object_name
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
    for filepath in filepaths:
      expanded_uri = self.wildcard_uri.clone_replace_name(filepath)
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


def wildcard_iterator(uri_or_str, proj_id_handler,
                      result_type=ResultType.URIS,
                      bucket_storage_uri_class=BucketStorageUri,
                      headers=None, debug=0):
  """Instantiate a WildCardIterator for the given StorageUri.

  Args:
    uri_or_str: StorageUri or URI string naming wildcard objects to iterate.
    proj_id_handler: ProjectIdHandler to use for current command.
    result_type: ResultType object specifying what to iterate.
    bucket_storage_uri_class: BucketStorageUri interface.
        Settable for testing/mocking.
    headers: dictionary containing optional HTTP headers to pass to boto.
    debug: debug level to pass in to boto connection (range 0..3).

  Returns:
    A WildcardIterator that handles the requested iteration.

  Raises:
    WildcardException: if invalid result_type.
  """

  if isinstance(uri_or_str, basestring):
    # Disable enforce_bucket_naming, to allow bucket names containing
    # wildcard chars.
    uri = boto.storage_uri(
        uri_or_str, debug=debug, validate=False,
        bucket_storage_uri_class=bucket_storage_uri_class)
  else:
    uri = uri_or_str

  if uri.is_cloud_uri():
    return CloudWildcardIterator(uri, proj_id_handler, result_type, 
                                 bucket_storage_uri_class, headers, debug)
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

  return WILDCARD_REGEX.search(uri_str) is not None
