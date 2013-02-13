# Copyright 2013 Google Inc.
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

import posixpath
import os.path
import time
import urllib
import urlparse

import unittest
if not hasattr(unittest.TestCase, 'assertIsNone'):
  # external dependency unittest2 required for Python <= 2.6
  import unittest2 as unittest

# Flags for running different types of tests.
RUN_INTEGRATION_TESTS = True
RUN_UNIT_TESTS = True

# Whether the tests are running verbose or not.
VERBOSE_OUTPUT = False


def _NormalizeURI(uri):
  """Normalizes the path component of a URI.

  Examples:
    gs://foo//bar -> gs://foo/bar
    gs://foo/./bar -> gs://foo/bar
  """
  # Note: we have to do this dance of changing gs:// to file:// because on
  # Windows, the urlparse function won't work with URL schemes that are not
  # known. urlparse('gs://foo/bar') on Windows turns into:
  #     scheme='gs', netloc='', path='//foo/bar'
  # while on non-Windows platforms, it turns into:
  #     scheme='gs', netloc='foo', path='/bar'
  uri = uri.replace('gs://', 'file://')
  parsed = list(urlparse.urlparse(uri))
  parsed[2] = posixpath.normpath(parsed[2])
  if parsed[2].startswith('//'):
    # The normpath function doesn't change '//foo' -> '/foo' by design.
    parsed[2] = parsed[2][1:]
  unparsed = urlparse.urlunparse(parsed)
  unparsed = unparsed.replace('file://', 'gs://')
  return unparsed


def ObjectToURI(obj, *suffixes):
  """Returns the storage URI string for a given StorageUri or file object.

  Args:
    obj: The object to get the URI from. Can be a file object, a subclass of
         boto.storage_uri.StorageURI, or a string. If a string, it is assumed to
         be a local on-disk path.
    suffixes: Suffixes to append. For example, ObjectToUri(bucketuri, 'foo')
              would return the URI for a key name 'foo' inside the given bucket.
  """
  if isinstance(obj, file):
    return 'file://%s' % os.path.abspath(os.path.join(obj.name, *suffixes))
  if isinstance(obj, basestring):
    return 'file://%s' % os.path.join(obj, *suffixes)
  uri = obj.uri
  if suffixes:
    uri = _NormalizeURI('/'.join([uri] + list(suffixes)))

  # Storage URIs shouldn't contain a trailing slash.
  if uri.endswith('/'):
    uri = uri[:-1]
  return uri


def Retry(ExceptionToCheck, tries=4, delay=3, backoff=2, logger=None):
  """Retry calling the decorated function using an exponential backoff.

  Taken from:
    https://github.com/saltycrane/retry-decorator
  Licensed under BSD:
    https://github.com/saltycrane/retry-decorator/blob/master/LICENSE

  :param ExceptionToCheck: the exception to check. may be a tuple of
      exceptions to check
  :type ExceptionToCheck: Exception or tuple
  :param tries: number of times to try (not retry) before giving up
  :type tries: int
  :param delay: initial delay between retries in seconds
  :type delay: int
  :param backoff: backoff multiplier e.g. value of 2 will double the delay
      each retry
  :type backoff: int
  :param logger: logger to use. If None, print
  :type logger: logging.Logger instance
  """
  def deco_retry(f):
    def f_retry(*args, **kwargs):
      mtries, mdelay = tries, delay
      try_one_last_time = True
      while mtries > 1:
        try:
          return f(*args, **kwargs)
          try_one_last_time = False
          break
        except ExceptionToCheck, e:
          msg = "%s, Retrying in %d seconds..." % (str(e), mdelay)
          if logger:
              logger.warning(msg)
          else:
              print msg
          time.sleep(mdelay)
          mtries -= 1
          mdelay *= backoff
      if try_one_last_time:
        return f(*args, **kwargs)
      return
    return f_retry  # true decorator
  return deco_retry
