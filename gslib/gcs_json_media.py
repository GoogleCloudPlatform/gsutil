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

import copy
import cStringIO
import httplib
import types
import urlparse

import httplib2
from httplib2 import parse_uri

# Upload/download 8KB chunks over the HTTP connection.
TRANSFER_BUFFER_SIZE = 1024*8


class BytesUploadedContainer(object):
  """Container class for passing number of bytes uploaded to lower layers.

  We don't know the total number of bytes uploaded until we've queried
  the server, but we need to create the connection class to pass to httplib2
  before we can query the server. This container object allows us to pass a
  reference into UploadCallbackConnection.
  """

  def __init__(self):
    self.__bytes_uploaded = 0

  @property
  def bytes_uploaded(self):
    return self.__bytes_uploaded

  @bytes_uploaded.setter
  def bytes_uploaded(self, value):
    self.__bytes_uploaded = value


class UploadCallbackConnectionClassFactory(object):
  """Creates a class that can override an httplib2 connection.

  This is used to provide progress callbacks and disable dumping the upload
  payload during debug statements. It can later be used to provide on-the-fly
  hash digestion during upload.
  """

  def __init__(self, bytes_uploaded_container,
               buffer_size=TRANSFER_BUFFER_SIZE,
               total_size=0, callback_count=0, progress_callback=None):
    self.bytes_uploaded_container = bytes_uploaded_container
    self.buffer_size = buffer_size
    self.total_size = total_size
    self.callback_count = callback_count
    self.progress_callback = progress_callback

  def GetConnectionClass(self):
    """Returns a connection class that overrides send."""
    outer_bytes_uploaded_container = self.bytes_uploaded_container
    outer_buffer_size = self.buffer_size
    outer_total_size = self.total_size
    outer_callback_count = self.callback_count
    outer_progress_callback = self.progress_callback

    class UploadCallbackConnection(httplib2.HTTPSConnectionWithTimeout):
      bytes_uploaded_container = outer_bytes_uploaded_container
      GCS_JSON_BUFFER_SIZE = outer_buffer_size
      send_iterations = 0
      cb_count = outer_callback_count
      size = outer_total_size

      def send(self, data):
        """Overrides HTTPConnection.send."""
        self.total_bytes_uploaded = self.bytes_uploaded_container.bytes_uploaded
        full_buffer = cStringIO.StringIO(data)
        partial_buffer = full_buffer.read(self.GCS_JSON_BUFFER_SIZE)
        old_debug = self.debuglevel
        try:
          self.set_debuglevel(0)
          while partial_buffer:
            httplib2.HTTPSConnectionWithTimeout.send(self, partial_buffer)
            # TODO: gsutil-beta: Likely need to insert a test hook here
            # to simulate connection breaks.
            # TODO: Hash computation on the fly can occur here, but at present
            # there is no server-side support as the hash needs to be present in
            # the initial POST for resumable uploads.
            self.total_bytes_uploaded += len(partial_buffer)
            if outer_progress_callback:
              self.send_iterations += 1
              if self.send_iterations == self.cb_count:
                outer_progress_callback(self.total_bytes_uploaded, self.size)
                self.send_iterations = 0
            partial_buffer = full_buffer.read(self.GCS_JSON_BUFFER_SIZE)
        finally:
          self.set_debuglevel(old_debug)

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
    connection_type = connection_type if method == 'PUT' else None
    return request_orig(uri, method=method, body=body,
                        headers=headers, redirections=redirections,
                        connection_type=connection_type)
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

  def __init__(self, buffer_size=TRANSFER_BUFFER_SIZE,
               total_size=0, callback_count=0, progress_callback=None,
               digesters=None):
    self.buffer_size = buffer_size
    self.total_size = total_size
    self.callback_count = callback_count
    self.progress_callback = progress_callback
    self.digesters = digesters

  def GetConnectionClass(self):
    """Returns a connection class that overrides getresponse."""

    class DownloadCallbackConnection(httplib2.HTTPSConnectionWithTimeout):
      read_iterations = 0
      outer_callback_count = self.callback_count
      outer_total_size = self.total_size
      total_bytes_downloaded = 0
      outer_digesters = self.digesters
      outer_progress_callback = self.progress_callback

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
          """Overrides HTTPConnection.getresponse.read."""
          old_debug = self.debuglevel
          try:
            self.set_debuglevel(0)
            bytes_read = 0
            all_data = cStringIO.StringIO()
            data = orig_read_func(TRANSFER_BUFFER_SIZE)
            while data and (amt is None or bytes_read < amt):
              if self.outer_progress_callback:
                self.read_iterations += 1
                if self.read_iterations == self.outer_callback_count:
                  self.outer_progress_callback(self.total_bytes_downloaded,
                                               self.outer_total_size)
                  self.read_iterations = 0
              all_data.write(data)
              bytes_read += len(data)
              if self.outer_digesters:
                for alg in self.outer_digesters:
                  self.outer_digesters[alg].update(data)
              # TODO: gsutil-beta: Likely need to insert a test hook here
              # to simulate connection breaks.
              data = orig_read_func(TRANSFER_BUFFER_SIZE)
            return all_data.getvalue()
          finally:
            self.set_debuglevel(old_debug)
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


