# Copyright 2014 Google Inc. All Rights Reserved.
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
"""HTTP wrapper for apitools.

This library wraps the underlying http library we use, which is
currently httplib2.
"""

import collections
import httplib
import logging
import socket
import time
import urlparse

import httplib2

from gslib.third_party.storage_apitools import exceptions

__all__ = [
    'GetHttp',
    'MakeRequest',
]


# 308 and 429 don't have names in httplib.
RESUME_INCOMPLETE = 308
TOO_MANY_REQUESTS = 429
_REDIRECT_STATUS_CODES = (
    httplib.MOVED_PERMANENTLY,
    httplib.FOUND,
    httplib.SEE_OTHER,
    httplib.TEMPORARY_REDIRECT,
    RESUME_INCOMPLETE,
)


class Request(object):
  """Class encapsulating the data for an HTTP request."""

  def __init__(self, url='', http_method='GET', headers=None, body=''):
    self.url = url
    self.http_method = http_method
    self.headers = headers or {}
    self.__body = None
    self.body = body

  @property
  def body(self):
    return self.__body

  @body.setter
  def body(self, value):
    self.__body = value
    if value is not None:
      self.headers['content-length'] = str(len(self.__body))
    else:
      self.headers.pop('content-length', None)


# Note: currently the order of fields here is important, since we want
# to be able to pass in the result from httplib2.request.
class Response(collections.namedtuple(
    'HttpResponse', ['info', 'content', 'request_url'])):
  """Class encapsulating data for an HTTP response."""
  __slots__ = ()

  def __len__(self):
    def ProcessContentRange(content_range):
      _, _, range_spec = content_range.partition(' ')
      byte_range, _, _ = range_spec.partition('/')
      start, _, end = byte_range.partition('-')
      return int(end) - int(start) + 1

    if '-content-encoding' in self.info and 'content-range' in self.info:
      # httplib2 rewrites content-length in the case of a compressed
      # transfer; we can't trust the content-length header in that
      # case, but we *can* trust content-range, if it's present.
      return ProcessContentRange(self.info['content-range'])
    elif 'content-length' in self.info:
      return int(self.info.get('content-length'))
    elif 'content-range' in self.info:
      return ProcessContentRange(self.info['content-range'])
    return len(self.content)

  @property
  def status_code(self):
    return int(self.info['status'])

  @property
  def retry_after(self):
    if 'retry-after' in self.info:
      return int(self.info['retry-after'])

  @property
  def is_redirect(self):
    return (self.status_code in _REDIRECT_STATUS_CODES and
            'location' in self.info)


def MakeRequest(http, http_request, retries=7, redirections=5):
  """Send http_request via the given http.

  This wrapper exists to handle translation between the plain httplib2
  request/response types and the Request and Response types above.
  This will also be the hook for error/retry handling.

  Args:
    http: An httplib2.Http instance, or a http multiplexer that delegates to
        an underlying http, for example, HTTPMultiplexer.
    http_request: A Request to send.
    retries: (int, default 5) Number of retries to attempt on 5XX replies.
    redirections: (int, default 5) Number of redirects to follow.

  Returns:
    A Response object.

  Raises:
    InvalidDataFromServerError: if there is no response after retries.
  """
  response = None
  exc = None
  connection_type = None
  # Handle overrides for connection types.  This is used if the caller
  # wants control over the underlying connection for managing callbacks
  # or hash digestion.
  if getattr(http, 'connections', None):
    url_scheme = urlparse.urlsplit(http_request.url).scheme
    if url_scheme and url_scheme in http.connections:
      connection_type = http.connections[url_scheme]
  for retry in xrange(retries + 1):
    # Note that the str() calls here are important for working around
    # some funny business with message construction and unicode in
    # httplib itself. See, eg,
    #   http://bugs.python.org/issue11898
    info = None
    try:
      info, content = http.request(
          str(http_request.url), method=str(http_request.http_method),
          body=http_request.body, headers=http_request.headers,
          redirections=redirections, connection_type=connection_type)
    except httplib.BadStatusLine as e:
      logging.error('Caught BadStatusLine from httplib, retrying: %s', e)
      exc = e
    except socket.error as e:
      if http_request.http_method != 'GET':
        raise
      logging.error('Caught socket error, retrying: %s', e)
      exc = e
    except httplib.IncompleteRead as e:
      if http_request.http_method != 'GET':
        raise
      logging.error('Caught IncompleteRead error, retrying: %s', e)
      exc = e
    if info is not None:
      response = Response(info, content, http_request.url)
      if (response.status_code < 500 and
          response.status_code != TOO_MANY_REQUESTS and
          not response.retry_after):
        break
      logging.info('Retrying request to url <%s> after status code %s',
                   response.request_url, response.status_code)
    elif isinstance(exc, httplib.IncompleteRead):
      logging.info('Retrying request to url <%s> after incomplete read.',
                   str(http_request.url))
    else:
      logging.info('Retrying request to url <%s> after connection break.',
                   str(http_request.url))
    # TODO: Make this timeout configurable.
    if response:
      time.sleep(response.retry_after or 2 ** retry)
    else:
      time.sleep(2 ** retry)
  if response is None:
    raise exceptions.InvalidDataFromServerError(
        'HTTP error on final retry: %s' % exc)
  return response


def GetHttp():
  return httplib2.Http()
