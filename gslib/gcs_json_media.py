# -*- coding: utf-8 -*-
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
"""Media helper functions and classes for Google Cloud Storage JSON API."""

from __future__ import absolute_import

import copy
import cStringIO
import httplib
import logging
import socket
import types
import urlparse

from apitools.base.py import exceptions as apitools_exceptions
import httplib2
from httplib2 import parse_uri

from gslib.cloud_api import BadRequestException
from gslib.progress_callback import ProgressCallbackWithBackoff
from gslib.util import SSL_TIMEOUT
from gslib.util import TRANSFER_BUFFER_SIZE


class BytesTransferredContainer(object):
  """Container class for passing number of bytes transferred to lower layers.

  For resumed transfers or connection rebuilds in the middle of a transfer, we
  need to rebuild the connection class with how much we've transferred so far.
  For uploads, we don't know the total number of bytes uploaded until we've
  queried the server, but we need to create the connection class to pass to
  httplib2 before we can query the server. This container object allows us to
  pass a reference into Upload/DownloadCallbackConnection.
  """

  def __init__(self):
    self.__bytes_transferred = 0

  @property
  def bytes_transferred(self):
    return self.__bytes_transferred

  @bytes_transferred.setter
  def bytes_transferred(self, value):
    self.__bytes_transferred = value


class UploadCallbackConnectionClassFactory(object):
  """Creates a class that can override an httplib2 connection.

  This is used to provide progress callbacks and disable dumping the upload
  payload during debug statements. It can later be used to provide on-the-fly
  hash digestion during upload.
  """

  def __init__(self, bytes_uploaded_container,
               buffer_size=TRANSFER_BUFFER_SIZE,
               total_size=0, progress_callback=None):
    self.bytes_uploaded_container = bytes_uploaded_container
    self.buffer_size = buffer_size
    self.total_size = total_size
    self.progress_callback = progress_callback

  def GetConnectionClass(self):
    """Returns a connection class that overrides send."""
    outer_bytes_uploaded_container = self.bytes_uploaded_container
    outer_buffer_size = self.buffer_size
    outer_total_size = self.total_size
    outer_progress_callback = self.progress_callback

    class UploadCallbackConnection(httplib2.HTTPSConnectionWithTimeout):
      """Connection class override for uploads."""
      bytes_uploaded_container = outer_bytes_uploaded_container
      # After we instantiate this class, apitools will check with the server
      # to find out how many bytes remain for a resumable upload.  This allows
      # us to update our progress once based on that number.
      processed_initial_bytes = False
      GCS_JSON_BUFFER_SIZE = outer_buffer_size
      callback_processor = None
      size = outer_total_size

      def __init__(self, *args, **kwargs):
        kwargs['timeout'] = SSL_TIMEOUT
        httplib2.HTTPSConnectionWithTimeout.__init__(self, *args, **kwargs)

      def send(self, data):
        """Overrides HTTPConnection.send."""
        if not self.processed_initial_bytes:
          self.processed_initial_bytes = True
          if outer_progress_callback:
            self.callback_processor = ProgressCallbackWithBackoff(
                outer_total_size, outer_progress_callback)
            self.callback_processor.Progress(
                self.bytes_uploaded_container.bytes_transferred)
        # httplib.HTTPConnection.send accepts either a string or a file-like
        # object (anything that implements read()).
        if isinstance(data, basestring):
          full_buffer = cStringIO.StringIO(data)
        else:
          full_buffer = data
        partial_buffer = full_buffer.read(self.GCS_JSON_BUFFER_SIZE)
        while partial_buffer:
          httplib2.HTTPSConnectionWithTimeout.send(self, partial_buffer)
          send_length = len(partial_buffer)
          if self.callback_processor:
            # This is the only place where gsutil has control over making a
            # callback, but here we can't differentiate the metadata bytes
            # (such as headers and OAuth2 refreshes) sent during an upload
            # from the actual upload bytes, so we will actually report
            # slightly more bytes than desired to the callback handler.
            #
            # One considered/rejected alternative is to move the callbacks
            # into the HashingFileUploadWrapper which only processes reads on
            # the bytes. This has the disadvantages of being removed from
            # where we actually send the bytes and unnecessarily
            # multi-purposing that class.
            self.callback_processor.Progress(send_length)
          partial_buffer = full_buffer.read(self.GCS_JSON_BUFFER_SIZE)

    return UploadCallbackConnection


def WrapUploadHttpRequest(upload_http):
  """Wraps upload_http so we only use our custom connection_type on PUTs.

  POSTs are used to refresh oauth tokens, and we don't want to process the
  data sent in those requests.

  Args:
    upload_http: httplib2.Http instance to wrap
  """
  request_orig = upload_http.request
  def NewRequest(uri, method='GET', body=None, headers=None,
                 redirections=httplib2.DEFAULT_MAX_REDIRECTS,
                 connection_type=None):
    if method == 'PUT' or method == 'POST':
      override_connection_type = connection_type
    else:
      override_connection_type = None
    return request_orig(uri, method=method, body=body,
                        headers=headers, redirections=redirections,
                        connection_type=override_connection_type)
  # Replace the request method with our own closure.
  upload_http.request = NewRequest


class DownloadCallbackConnectionClassFactory(object):
  """Creates a class that can override an httplib2 connection.

  This is used to provide progress callbacks, disable dumping the download
  payload during debug statements, and provide on-the-fly hash digestion during
  download. On-the-fly digestion is particularly important because httplib2
  will decompress gzipped content on-the-fly, thus this class provides our
  only opportunity to calculate the correct hash for an object that has a
  gzip hash in the cloud.
  """

  def __init__(self, bytes_downloaded_container,
               buffer_size=TRANSFER_BUFFER_SIZE, total_size=0,
               progress_callback=None, digesters=None):
    self.buffer_size = buffer_size
    self.total_size = total_size
    self.progress_callback = progress_callback
    self.digesters = digesters
    self.bytes_downloaded_container = bytes_downloaded_container

  def GetConnectionClass(self):
    """Returns a connection class that overrides getresponse."""

    class DownloadCallbackConnection(httplib2.HTTPSConnectionWithTimeout):
      """Connection class override for downloads."""
      outer_total_size = self.total_size
      outer_digesters = self.digesters
      outer_progress_callback = self.progress_callback
      outer_bytes_downloaded_container = self.bytes_downloaded_container
      processed_initial_bytes = False
      callback_processor = None

      def __init__(self, *args, **kwargs):
        kwargs['timeout'] = SSL_TIMEOUT
        httplib2.HTTPSConnectionWithTimeout.__init__(self, *args, **kwargs)

      def getresponse(self, buffering=False):
        """Wraps an HTTPResponse to perform callbacks and hashing.

        In this function, self is a DownloadCallbackConnection.

        Args:
          buffering: Unused. This function uses a local buffer.

        Returns:
          HTTPResponse object with wrapped read function.
        """
        orig_response = httplib.HTTPConnection.getresponse(self)
        if orig_response.status not in (httplib.OK, httplib.PARTIAL_CONTENT):
          return orig_response
        orig_read_func = orig_response.read

        def read(amt=None):  # pylint: disable=invalid-name
          """Overrides HTTPConnection.getresponse.read.

          This function only supports reads of TRANSFER_BUFFER_SIZE or smaller.

          Args:
            amt: Integer n where 0 < n <= TRANSFER_BUFFER_SIZE. This is a
                 keyword argument to match the read function it overrides,
                 but it is required.

          Returns:
            Data read from HTTPConnection.
          """
          if not amt or amt > TRANSFER_BUFFER_SIZE:
            raise BadRequestException(
                'Invalid HTTP read size %s during download, expected %s.' %
                (amt, TRANSFER_BUFFER_SIZE))
          else:
            amt = amt or TRANSFER_BUFFER_SIZE

          if not self.processed_initial_bytes:
            self.processed_initial_bytes = True
            if self.outer_progress_callback:
              self.callback_processor = ProgressCallbackWithBackoff(
                  self.outer_total_size, self.outer_progress_callback)
              self.callback_processor.Progress(
                  self.outer_bytes_downloaded_container.bytes_transferred)

          data = orig_read_func(amt)
          read_length = len(data)
          if self.callback_processor:
            self.callback_processor.Progress(read_length)
          if self.outer_digesters:
            for alg in self.outer_digesters:
              self.outer_digesters[alg].update(data)
          return data
        orig_response.read = read

        return orig_response
    return DownloadCallbackConnection


def WrapDownloadHttpRequest(download_http):
  """Overrides download request functions for an httplib2.Http object.

  Args:
    download_http: httplib2.Http.object to wrap / override.

  Returns:
    Wrapped / overridden httplib2.Http object.
  """

  # httplib2 has a bug https://code.google.com/p/httplib2/issues/detail?id=305
  # where custom connection_type is not respected after redirects.  This
  # function is copied from httplib2 and overrides the request function so that
  # the connection_type is properly passed through.
  # pylint: disable=protected-access,g-inconsistent-quotes,unused-variable
  # pylint: disable=g-equals-none,g-doc-return-or-yield
  # pylint: disable=g-short-docstring-punctuation,g-doc-args
  # pylint: disable=too-many-statements
  def OverrideRequest(self, conn, host, absolute_uri, request_uri, method,
                      body, headers, redirections, cachekey):
    """Do the actual request using the connection object.

    Also follow one level of redirects if necessary.
    """

    auths = ([(auth.depth(request_uri), auth) for auth in self.authorizations
              if auth.inscope(host, request_uri)])
    auth = auths and sorted(auths)[0][1] or None
    if auth:
      auth.request(method, request_uri, headers, body)

    (response, content) = self._conn_request(conn, request_uri, method, body,
                                             headers)

    if auth:
      if auth.response(response, body):
        auth.request(method, request_uri, headers, body)
        (response, content) = self._conn_request(conn, request_uri, method,
                                                 body, headers)
        response._stale_digest = 1

    if response.status == 401:
      for authorization in self._auth_from_challenge(
          host, request_uri, headers, response, content):
        authorization.request(method, request_uri, headers, body)
        (response, content) = self._conn_request(conn, request_uri, method,
                                                 body, headers)
        if response.status != 401:
          self.authorizations.append(authorization)
          authorization.response(response, body)
          break

    if (self.follow_all_redirects or (method in ["GET", "HEAD"])
        or response.status == 303):
      if self.follow_redirects and response.status in [300, 301, 302,
                                                       303, 307]:
        # Pick out the location header and basically start from the beginning
        # remembering first to strip the ETag header and decrement our 'depth'
        if redirections:
          if not response.has_key('location') and response.status != 300:
            raise httplib2.RedirectMissingLocation(
                "Redirected but the response is missing a Location: header.",
                response, content)
          # Fix-up relative redirects (which violate an RFC 2616 MUST)
          if response.has_key('location'):
            location = response['location']
            (scheme, authority, path, query, fragment) = parse_uri(location)
            if authority == None:
              response['location'] = urlparse.urljoin(absolute_uri, location)
          if response.status == 301 and method in ["GET", "HEAD"]:
            response['-x-permanent-redirect-url'] = response['location']
            if not response.has_key('content-location'):
              response['content-location'] = absolute_uri
            httplib2._updateCache(headers, response, content, self.cache,
                                  cachekey)
          if headers.has_key('if-none-match'):
            del headers['if-none-match']
          if headers.has_key('if-modified-since'):
            del headers['if-modified-since']
          if ('authorization' in headers and
              not self.forward_authorization_headers):
            del headers['authorization']
          if response.has_key('location'):
            location = response['location']
            old_response = copy.deepcopy(response)
            if not old_response.has_key('content-location'):
              old_response['content-location'] = absolute_uri
            redirect_method = method
            if response.status in [302, 303]:
              redirect_method = "GET"
              body = None
            (response, content) = self.request(
                location, redirect_method, body=body, headers=headers,
                redirections=redirections-1,
                connection_type=conn.__class__)
            response.previous = old_response
        else:
          raise httplib2.RedirectLimit(
              "Redirected more times than redirection_limit allows.",
              response, content)
      elif response.status in [200, 203] and method in ["GET", "HEAD"]:
        # Don't cache 206's since we aren't going to handle byte range
        # requests
        if not response.has_key('content-location'):
          response['content-location'] = absolute_uri
        httplib2._updateCache(headers, response, content, self.cache,
                              cachekey)

    return (response, content)

  # Wrap download_http so we do not use our custom connection_type
  # on POSTS, which are used to refresh oauth tokens. We don't want to
  # process the data received in those requests.
  request_orig = download_http.request
  def NewRequest(uri, method='GET', body=None, headers=None,
                 redirections=httplib2.DEFAULT_MAX_REDIRECTS,
                 connection_type=None):
    if method == 'POST':
      return request_orig(uri, method=method, body=body,
                          headers=headers, redirections=redirections,
                          connection_type=None)
    else:
      return request_orig(uri, method=method, body=body,
                          headers=headers, redirections=redirections,
                          connection_type=connection_type)

  # Replace the request methods with our own closures.
  download_http._request = types.MethodType(OverrideRequest, download_http)
  download_http.request = NewRequest

  return download_http


class HttpWithNoRetries(httplib2.Http):
  """httplib2.Http variant that does not retry.

  httplib2 automatically retries requests according to httplib2.RETRIES, but
  in certain cases httplib2 ignores the RETRIES value and forces a retry.
  Because httplib2 does not handle the case where the underlying request body
  is a stream, a retry may cause a non-idempotent write as the stream is
  partially consumed and not reset before the retry occurs.

  Here we override _conn_request to disable retries unequivocally, so that
  uploads may be retried at higher layers that properly handle stream request
  bodies.
  """

  def _conn_request(self, conn, request_uri, method, body, headers):  # pylint: disable=too-many-statements

    try:
      if hasattr(conn, 'sock') and conn.sock is None:
        conn.connect()
      conn.request(method, request_uri, body, headers)
    except socket.timeout:
      raise
    except socket.gaierror:
      conn.close()
      raise httplib2.ServerNotFoundError(
          'Unable to find the server at %s' % conn.host)
    except httplib2.ssl_SSLError:
      conn.close()
      raise
    except socket.error, e:
      err = 0
      if hasattr(e, 'args'):
        err = getattr(e, 'args')[0]
      else:
        err = e.errno
      if err == httplib2.errno.ECONNREFUSED:  # Connection refused
        raise
    except httplib.HTTPException:
      conn.close()
      raise
    try:
      response = conn.getresponse()
    except (socket.error, httplib.HTTPException):
      conn.close()
      raise
    else:
      content = ''
      if method == 'HEAD':
        conn.close()
      else:
        content = response.read()
      response = httplib2.Response(response)
      if method != 'HEAD':
        # pylint: disable=protected-access
        content = httplib2._decompressContent(response, content)
    return (response, content)


class HttpWithDownloadStream(httplib2.Http):
  """httplib2.Http variant that only pushes bytes through a stream.

  httplib2 handles media by storing entire chunks of responses in memory, which
  is undesirable particularly when multiple instances are used during
  multi-threaded/multi-process copy. This class copies and then overrides some
  httplib2 functions to use a streaming copy approach that uses small memory
  buffers.

  Also disables httplib2 retries (for reasons stated in the HttpWithNoRetries
  class doc).
  """

  def __init__(self, stream=None, *args, **kwds):
    if stream is None:
      raise apitools_exceptions.InvalidUserInputError(
          'Cannot create HttpWithDownloadStream with no stream')
    self._stream = stream
    self._logger = logging.getLogger()
    super(HttpWithDownloadStream, self).__init__(*args, **kwds)

  @property
  def stream(self):
    return self._stream

  def _conn_request(self, conn, request_uri, method, body, headers):  # pylint: disable=too-many-statements
    try:
      if hasattr(conn, 'sock') and conn.sock is None:
        conn.connect()
      conn.request(method, request_uri, body, headers)
    except socket.timeout:
      raise
    except socket.gaierror:
      conn.close()
      raise httplib2.ServerNotFoundError(
          'Unable to find the server at %s' % conn.host)
    except httplib2.ssl_SSLError:
      conn.close()
      raise
    except socket.error, e:
      err = 0
      if hasattr(e, 'args'):
        err = getattr(e, 'args')[0]
      else:
        err = e.errno
      if err == httplib2.errno.ECONNREFUSED:  # Connection refused
        raise
    except httplib.HTTPException:
      # Just because the server closed the connection doesn't apparently mean
      # that the server didn't send a response.
      conn.close()
      raise
    try:
      response = conn.getresponse()
    except (socket.error, httplib.HTTPException):
      conn.close()
      raise
    else:
      content = ''
      if method == 'HEAD':
        conn.close()
        response = httplib2.Response(response)
      else:
        if response.status in (httplib.OK, httplib.PARTIAL_CONTENT):
          content_length = None
          if hasattr(response, 'msg'):
            content_length = response.getheader('content-length')
          http_stream = response
          bytes_read = 0
          while True:
            new_data = http_stream.read(TRANSFER_BUFFER_SIZE)
            if new_data:
              self.stream.write(new_data)
              bytes_read += len(new_data)
            else:
              break

          if (content_length is not None and
              long(bytes_read) != long(content_length)):
            # The input stream terminated before we were able to read the
            # entire contents, possibly due to a network condition. Set
            # content-length to indicate how many bytes we actually read.
            self._logger.log(
                logging.DEBUG, 'Only got %s bytes out of content-length %s '
                'for request URI %s. Resetting content-length to match '
                'bytes read.', bytes_read, content_length, request_uri)
            response.msg['content-length'] = str(bytes_read)
          response = httplib2.Response(response)
        else:
          # We fall back to the current httplib2 behavior if we're
          # not processing bytes (eg it's a redirect).
          content = response.read()
          response = httplib2.Response(response)
          # pylint: disable=protected-access
          content = httplib2._decompressContent(response, content)
    return (response, content)
