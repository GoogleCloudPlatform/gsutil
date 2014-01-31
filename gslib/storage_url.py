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
"""File and Cloud URL representation classes."""
import os
import re

from gslib.exception import InvalidUrlError

# Matches provider strings of the form 'gs://'
PROVIDER_REGEX = re.compile(r'(?P<provider>[^:]*)://$')
# Matches bucket strings of the form 'gs://bucket'
BUCKET_REGEX = re.compile(r'(?P<provider>[^:]*)://(?P<bucket>[^/]*)/{0,1}$')
# Matches object strings of the form 'gs://bucket/obj'
OBJECT_REGEX = re.compile(
    r'(?P<provider>[^:]*)://(?P<bucket>[^/]*)/(?P<object>.*)')
# Matches versioned object strings of the form 'gs://bucket/obj#1234'
GS_GENERATION_REGEX = re.compile(r'(?P<object>.+)#(?P<generation>[0-9]+)$')
# Matches versioned object strings of the form 's3://bucket/obj#NULL'
S3_VERSION_REGEX = re.compile(r'(?P<object>.+)#(?P<version_id>.+)$')
# Matches file strings of the form 'file://dir/filename'
FILE_OBJECT_REGEX = re.compile(r'([^:]*://)(?P<filepath>.*)')
# Regex to disallow buckets violating charset or not [3..255] chars total.
BUCKET_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9\._-]{1,253}[a-zA-Z0-9]$')
# Regex to disallow buckets with individual DNS labels longer than 63.
TOO_LONG_DNS_NAME_COMP = re.compile(r'[-_a-z0-9]{64}')
# Regex to determine if a string contains any wildcards.
WILDCARD_REGEX = re.compile(r'[*?\[\]]')


class StorageUrl(object):
  """Abstract base class for file and Cloud Storage URLs."""

  def Clone(self):
    raise NotImplementedError('Clone not overridden')

  def IsFileUrl(self):
    raise NotImplementedError('IsFileUrl not overridden')

  def IsCloudUrl(self):
    raise NotImplementedError('IsCloudUrl not overridden')

  def IsStream(self):
    raise NotImplementedError('IsStream not overridden')

  def GetUrlString(self):
    raise NotImplementedError('GetUrlString not overridden')

  def GetVersionlessUrlStringStripOneSlash(self):
    """Returns a URL string with one slash right-stripped, if present.

    This helps avoid infinite looping when prefixes
    are iterated, but preserves other slashes so that objects with '/'
    in the name are handled properly.  The typical pattern for enumerating
    a bucket or subdir is to add '/*' to the end of the search string.

    For example, when recursively listing a bucket with the following contents:
    gs://bucket// <-- object named slash
    gs://bucket//one-dir-deep

    A top-level expansion with '/' as a delimiter will result in the following
    URL strings:
    'gs://bucket//' : OBJECT
    'gs://bucket//' : PREFIX
    'gs and 'temp' and the prefixes '/' and 'temp/'.  If we right-strip all
    slashes from the prefix entry and add '/*', we will get 'gs://bucket/*'
    which will produce identical results (and infinitely recurse).

    Example return values:
      'gs://bucket/subdir//' becomes 'gs://bucket/subdir/'
      'gs://bucket/subdir///' becomes 'gs://bucket/subdir//'
      'gs://bucket/' becomes 'gs://bucket'
      'gs://bucket/subdir/' where subdir/ is actually an object becomes
           'gs://bucket/subdir', but this is enumerated as a
           BucketListingRefType.OBJECT, so we will not recurse on it as a subdir
           during listing.

    Returns:
      URL string with one slash right-stripped, if present.
    """
    raise NotImplementedError(
        'GetVersionlessUrlStringStripOneSlash not overridden')


class _FileUrl(StorageUrl):
  """File URL class providing parsing and convenience methods.

    This class assists with usage and manipulation of an
    (optionally wildcarded) file URL string.  Depending on the string
    contents, this class represents one or more directories or files.

    For File URLs, scheme is always file, bucket_name is always blank,
    and object_name contains the file/directory path.
  """

  def __init__(self, url_string, is_stream=False):
    self.scheme = 'file'
    self.bucket_name = ''
    match = FILE_OBJECT_REGEX.match(url_string)
    if match and match.lastindex == 2:
      self.object_name = match.group(2)
    else:
      self.object_name = url_string
    self.generation = None
    self.is_stream = is_stream
    self.delim = os.sep

  def Clone(self):
    return _FileUrl(self.GetUrlString())

  def IsFileUrl(self):
    return True

  def IsCloudUrl(self):
    return False

  def IsStream(self):
    return self.is_stream

  def IsDirectory(self):
    return not self.IsStream() and os.path.isdir(self.object_name)

  def GetUrlString(self):
    return '%s://%s' % (self.scheme, self.object_name)

  def GetVersionlessUrlString(self):
    return self.GetUrlString()

  def GetVersionlessUrlStringStripOneSlash(self):
    return self.GetUrlString()

  def __str__(self):
    return self.GetUrlString()


class _CloudUrl(StorageUrl):
  """Cloud URL class providing parsing and convenience methods.

    This class assists with usage and manipulation of an
    (optionally wildcarded) cloud URL string.  Depending on the string
    contents, this class represents a provider, bucket(s), or object(s).

    This class operates only on strings.  No cloud storage API calls are
    made from this class.
  """

  def __init__(self, url_string):
    self.scheme = None
    self.bucket_name = None
    self.object_name = None
    self.generation = None
    self.delim = '/'
    provider_match = PROVIDER_REGEX.match(url_string)
    bucket_match = BUCKET_REGEX.match(url_string)
    if provider_match:
      self.scheme = provider_match.group('provider')
    elif bucket_match:
      self.scheme = bucket_match.group('provider')
      self.bucket_name = bucket_match.group('bucket')
      if (not ContainsWildcard(self.bucket_name) and
          (not BUCKET_NAME_RE.match(self.bucket_name) or
           TOO_LONG_DNS_NAME_COMP.search(self.bucket_name))):
        raise InvalidUrlError('Invalid bucket name in URL "%s"' % url_string)
    else:
      object_match = OBJECT_REGEX.match(url_string)
      if object_match:
        self.scheme = object_match.group('provider')
        self.bucket_name = object_match.group('bucket')
        self.object_name = object_match.group('object')
        if self.scheme == 'gs':
          generation_match = GS_GENERATION_REGEX.match(self.object_name)
          if generation_match:
            self.object_name = generation_match.group('object')
            self.generation = generation_match.group('generation')
        elif self.scheme == 's3':
          version_match = S3_VERSION_REGEX.match(self.object_name)
          if version_match:
            self.object_name = version_match.group('object')
            self.generation = version_match.group('version_id')
      else:
        raise InvalidUrlError(
            'CloudUrl: URL string %s did not match URL regex' % url_string)

  def Clone(self):
    return _CloudUrl(self.GetUrlString())

  def IsFileUrl(self):
    return False

  def IsCloudUrl(self):
    return True

  def IsStream(self):
    raise NotImplementedError('IsStream not supported on CloudUrl')

  def IsBucket(self):
    return bool(self.bucket_name and not self.object_name)

  def IsObject(self):
    return bool(self.bucket_name and self.object_name)

  def HasGeneration(self):
    return bool(self.generation)

  def IsProvider(self):
    return bool(self.scheme and not self.bucket_name)

  def GetBucketUrlString(self):
    return '%s://%s/' % (self.scheme, self.bucket_name)

  def GetUrlString(self):
    url_str = self.GetVersionlessUrlString()
    if self.HasGeneration():
      url_str += '#%s' % self.generation
    return url_str

  def GetVersionlessUrlString(self):
    if self.IsProvider():
      return '%s://' % self.scheme
    elif self.IsBucket():
      return self.GetBucketUrlString()
    else:
      return '%s://%s/%s' % (self.scheme, self.bucket_name, self.object_name)

  def GetVersionlessUrlStringStripOneSlash(self):
    return StripOneSlash(self.GetVersionlessUrlString())

  def __str__(self):
    return self.GetUrlString()


def StorageUrlFromString(url_str):
  """Static factory function for creating a StorageUrl from a string."""

  end_scheme_idx = url_str.find('://')
  if end_scheme_idx == -1:
    # File is the default scheme.
    scheme = 'file'
    path = url_str
  else:
    scheme = url_str[0:end_scheme_idx].lower()
    path = url_str[end_scheme_idx + 3:]

  if scheme not in ('file', 's3', 'gs'):
    raise InvalidUrlError('Unrecognized scheme "%s"' % scheme)
  if scheme == 'file':
    is_stream = (path == '-')
    return _FileUrl(url_str, is_stream=is_stream)
  else:
    return _CloudUrl(url_str)


def StripOneSlash(url_str):
  if url_str and url_str.endswith('/'):
    return url_str[:-1]
  else:
    return url_str


def ContainsWildcard(url_string):
  """Checks whether url_string contains a wildcard.

  Args:
    url_string: URL string to check.

  Returns:
    bool indicator.
  """
  return bool(WILDCARD_REGEX.search(url_string))
