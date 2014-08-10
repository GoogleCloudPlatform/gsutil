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
from gslib.third_party.storage_apitools import util

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

# http: An httplib2.Http instance.
# http_request: A http_wrapper.Request.
# exc: Exception being raised.
# num_retries: Number of retries consumed; used for exponential backoff.
ExceptionRetryArgs = collections.namedtuple('ExceptionRetryArgs',
                                            ['http', 'http_request', 'exc',
                                             'num_retries'])


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
    return self.length

  @property
  def length(self):
    """Return the length of this response.

    We expose this as an attribute since using len() directly can fail
    for responses larger than sys.maxint.

    Returns:
      Response length (as int or long)
    """
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


def CheckResponse(response):
  if response is None:
    # Caller shouldn't call us if the response is None, but handle anyway.
    raise exceptions.RequestError('Request to url %s did not return a response.'
                                  % response.request_url)
  elif (response.status_code >= 500 or
        response.status_code == TOO_MANY_REQUESTS):
    raise exceptions.BadStatusCodeError.FromResponse(response)
  elif response.status_code == httplib.UNAUTHORIZED:
    # Sometimes we get a 401 after a connection break.
    # TODO: this shouldn't be a retryable exception, but for now we retry.
    raise exceptions.BadStatusCodeError.FromResponse(response)
  elif response.retry_after:
    raise exceptions.RetryAfterError.FromResponse(response)


def RebuildHttpConnections(http):
  """Rebuilds all http connections in the httplib2.Http instance.

  httplib2 overloads the map in http.connections to contain two different
  types of values:
  { scheme string:  connection class } and
  { scheme + authority string : actual http connection }
  Here we remove all of the entries for actual connections so that on the
  next request httplib2 will rebuild them from the connection types.

  Args:
    http: An httplib2.Http instance.
  """
  if getattr(http, 'connections', None):
    for conn_key in http.connections.keys():
      if ':' in conn_key:
        del http.connections[conn_key]


def RethrowExceptionHandler(*unused_args):
  raise


def HandleExceptionsAndRebuildHttpConnections(retry_args):
  """Exception handler for http failures.

  This catches known failures and rebuilds the underlying HTTP connections.

  Args:
    retry_args: An ExceptionRetryArgs tuple.
  """
  retry_after = None
  if isinstance(retry_args.exc, httplib.BadStatusLine):
    logging.error('Caught BadStatusLine from httplib, retrying: %s',
                  retry_args.exc)
  elif isinstance(retry_args.exc, socket.error):
    logging.error('Caught socket error, retrying: %s', retry_args.exc)
  elif isinstance(retry_args.exc, exceptions.BadStatusCodeError):
    logging.error('Response returned status %s, retrying',
                  retry_args.exc.status_code)
  elif isinstance(retry_args.exc, exceptions.RetryAfterError):
    logging.error('Response returned a retry-after header, retrying')
    retry_after = retry_args.exc.retry_after
  elif isinstance(retry_args.exc, ValueError):
    # oauth2_client tries to JSON-decode the response, which can result
    # in a ValueError if the response was invalid. Until that is fixed in
    # oauth2_client, need to handle it here.
    logging.error('Response content was invalid (%s), retrying',
                  retry_args.exc)
  elif isinstance(retry_args.exc, exceptions.RequestError):
    logging.error('Request returned no response, retrying')
  else:
    raise
  RebuildHttpConnections(retry_args.http)
  logging.error('Retrying request to url %s after exception %s',
                retry_args.http_request.url, retry_args.exc)
  time.sleep(retry_after or util.CalculateWaitForRetry(retry_args.num_retries))


def MakeRequest(http, http_request, retries=7, redirections=5,
                retry_func=HandleExceptionsAndRebuildHttpConnections,
                check_response_func=CheckResponse):
  """Send http_request via the given http, performing error/retry handling.

  Args:
    http: An httplib2.Http instance, or a http multiplexer that delegates to
        an underlying http, for example, HTTPMultiplexer.
    http_request: A Request to send.
    retries: (int, default 5) Number of retries to attempt on 5XX replies.
    redirections: (int, default 5) Number of redirects to follow.
    retry_func: Function to handle retries on exceptions. Arguments are
                (Httplib2.Http, Request, Exception, int num_retries).
    check_response_func: Function to validate the HTTP response. Arguments are
                         (Response, response content, url).

  Returns:
    A Response object.
  """
  retry = 0
  while True:
    try:
      return _MakeRequestNoRetry(http, http_request, redirections=redirections,
                                 check_response_func=check_response_func)
    # retry_func will consume the exception types it handles and raise.
    # pylint: disable=broad-except
    except Exception as e:
      retry += 1
      if retry >= retries:
        raise
      else:
        retry_func(ExceptionRetryArgs(http, http_request, e, retry))


def _MakeRequestNoRetry(http, http_request, redirections=5,
                        check_response_func=CheckResponse):
  """Send http_request via the given http.

  This wrapper exists to handle translation between the plain httplib2
  request/response types and the Request and Response types above.

  Args:
    http: An httplib2.Http instance, or a http multiplexer that delegates to
        an underlying http, for example, HTTPMultiplexer.
    http_request: A Request to send.
    redirections: (int, default 5) Number of redirects to follow.
    check_response_func: Function to validate the HTTP response. Arguments are
                         (Response, response content, url).

  Returns:
    Response object.

  Raises:
    RequestError if no response could be parsed.
  """
  connection_type = None
  if getattr(http, 'connections', None):
    url_scheme = urlparse.urlsplit(http_request.url).scheme
    if url_scheme and url_scheme in http.connections:
      connection_type = http.connections[url_scheme]

  info, content = http.request(
      str(http_request.url), method=str(http_request.http_method),
      body=http_request.body, headers=http_request.headers,
      redirections=redirections, connection_type=connection_type)

  if info is None:
    raise exceptions.RequestError()

  response = Response(info, content, http_request.url)
  check_response_func(response)
  return response


def GetHttp():
  return httplib2.Http()
