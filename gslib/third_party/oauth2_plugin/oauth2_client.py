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

"""An OAuth2 client library.

This library provides a client implementation of the OAuth2 protocol (see
https://developers.google.com/storage/docs/authentication.html#oauth).

**** Experimental API ****

This module is experimental and is subject to modification or removal without
notice.
"""

# This implementation is a wrapper around the oauth2client implementation
# that implements caching of access tokens independent of refresh
# tokens (in the python API client oauth2client, there is a single class that
# encapsulates both refresh and access tokens).


import cgi
import socks
import datetime
import errno
from hashlib import sha1
import httplib2
import logging
import multiprocessing
import os
import tempfile
import threading
import urllib
import urlparse
from boto import cacerts
from boto import config
from gslib.util import CreateLock
from gslib.util import Retry
from oauth2client.client import AccessTokenRefreshError
from oauth2client.client import HAS_CRYPTO
from oauth2client.client import OAuth2Credentials
if HAS_CRYPTO:
  from oauth2client.client import SignedJwtAssertionCredentials


try:
  import json
except ImportError:
  try:
    # Try to import from django, should work on App Engine
    from django.utils import simplejson as json
  except ImportError:
    # Try for simplejson
    import simplejson as json

global token_exchange_lock
def InitializeMultiprocessingVariables():
  """
  Perform necessary initialization - see
  gslib.command.InitializeMultiprocessingVariables for an explanation of why
  this is necessary.
  """
  global token_exchange_lock
  # Lock used for checking/exchanging refresh token so that a parallelized
  # operation doesn't attempt concurrent refreshes.
  token_exchange_lock = CreateLock()


LOG = logging.getLogger('oauth2_client')
# Lock used for checking/exchanging refresh token, so multithreaded
# operation doesn't attempt concurrent refreshes.
token_exchange_lock = threading.Lock()

GSUTIL_DEFAULT_SCOPE = 'https://www.googleapis.com/auth/devstorage.full_control'


class Error(Exception):
  """Base exception for the OAuth2 module."""
  pass


class AccessTokenRefreshError(Error):
  """Error trying to exchange a refresh token into an access token."""
  pass


class AuthorizationCodeExchangeError(Error):
  """Error trying to exchange an authorization code into a refresh token."""
  pass


class TokenCache(object):
  """Interface for OAuth2 token caches."""

  def PutToken(self, key, value):
    raise NotImplementedError

  def GetToken(self, key):
    raise NotImplementedError


class NoopTokenCache(TokenCache):
  """A stub implementation of TokenCache that does nothing."""

  def PutToken(self, key, value):
    pass

  def GetToken(self, key):
    return None


class InMemoryTokenCache(TokenCache):
  """An in-memory token cache.

  The cache is implemented by a python dict, and inherits the thread-safety
  properties of dict.
  """

  def __init__(self):
    super(InMemoryTokenCache, self).__init__()
    self.cache = dict()

  def PutToken(self, key, value):
    LOG.debug('InMemoryTokenCache.PutToken: key=%s', key)
    self.cache[key] = value

  def GetToken(self, key):
    value = self.cache.get(key, None)
    LOG.debug('InMemoryTokenCache.GetToken: key=%s%s present',
              key, ' not' if value is None else '')
    return value


class FileSystemTokenCache(TokenCache):
  """An implementation of a token cache that persists tokens on disk.

  Each token object in the cache is stored in serialized form in a separate
  file. The cache file's name can be configured via a path pattern that is
  parameterized by the key under which a value is cached and optionally the
  current processes uid as obtained by os.getuid().

  Since file names are generally publicly visible in the system, it is important
  that the cache key does not leak information about the token's value.  If
  client code computes cache keys from token values, a cryptographically strong
  one-way function must be used.
  """

  def __init__(self, path_pattern=None):
    """Creates a FileSystemTokenCache.

    Args:
      path_pattern: Optional string argument to specify the path pattern for
          cache files.  The argument should be a path with format placeholders
          '%(key)s' and optionally '%(uid)s'.  If the argument is omitted, the
          default pattern
            <tmpdir>/oauth2client-tokencache.%(uid)s.%(key)s
          is used, where <tmpdir> is replaced with the system temp dir as
          obtained from tempfile.gettempdir().
    """
    super(FileSystemTokenCache, self).__init__()
    self.path_pattern = path_pattern
    if not path_pattern:
      self.path_pattern = os.path.join(
          tempfile.gettempdir(), 'oauth2_client-tokencache.%(uid)s.%(key)s')

  def CacheFileName(self, key):
    uid = '_'
    try:
      # os.getuid() doesn't seem to work in Windows
      uid = str(os.getuid())
    except:
      pass
    return self.path_pattern % {'key': key, 'uid': uid}

  def PutToken(self, key, value):
    """Serializes the value to the key's filename.

    To ensure that written tokens aren't leaked to a different users, we
     a) unlink an existing cache file, if any (to ensure we don't fall victim
        to symlink attacks and the like),
     b) create a new file with O_CREAT | O_EXCL (to ensure nobody is trying to
        race us)
     If either of these steps fail, we simply give up (but log a warning). Not
     caching access tokens is not catastrophic, and failure to create a file
     can happen for either of the following reasons:
      - someone is attacking us as above, in which case we want to default to
        safe operation (not write the token);
      - another legitimate process is racing us; in this case one of the two
        will win and write the access token, which is fine;
      - we don't have permission to remove the old file or write to the
        specified directory, in which case we can't recover

    Args:
      key: the hash key to store.
      value: the access_token value to serialize.
    """

    cache_file = self.CacheFileName(key)
    LOG.debug('FileSystemTokenCache.PutToken: key=%s, cache_file=%s',
              key, cache_file)
    try:
      os.unlink(cache_file)
    except:
      # Ignore failure to unlink the file; if the file exists and can't be
      # unlinked, the subsequent open with O_CREAT | O_EXCL will fail.
      pass

    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL

    # Accommodate Windows; stolen from python2.6/tempfile.py.
    if hasattr(os, 'O_NOINHERIT'):
      flags |= os.O_NOINHERIT
    if hasattr(os, 'O_BINARY'):
      flags |= os.O_BINARY

    try:
      fd = os.open(cache_file, flags, 0600)
    except (OSError, IOError) as e:
      LOG.warning('FileSystemTokenCache.PutToken: '
                  'Failed to create cache file %s: %s', cache_file, e)
      return
    f = os.fdopen(fd, 'w+b')
    f.write(value.Serialize())
    f.close()

  def GetToken(self, key):
    """Returns a deserialized access token from the key's filename."""
    value = None
    cache_file = self.CacheFileName(key)
    
    try:
      f = open(cache_file)
      value = AccessToken.UnSerialize(f.read())
      f.close()
    except (IOError, OSError) as e:
      if e.errno != errno.ENOENT:
        LOG.warning('FileSystemTokenCache.GetToken: '
                    'Failed to read cache file %s: %s', cache_file, e)
    except Exception as e:
      LOG.warning('FileSystemTokenCache.GetToken: '
                  'Failed to read cache file %s (possibly corrupted): %s',
                  cache_file, e)

    LOG.debug('FileSystemTokenCache.GetToken: key=%s%s present (cache_file=%s)',
              key, ' not' if value is None else '', cache_file)
    return value

    
class OAuth2Client(object):
  """Common logic for OAuth2 clients."""
  
  def __init__(self, cache_key_base, access_token_cache=None,
               datetime_strategy=datetime.datetime, auth_uri=None,
               token_uri=None, disable_ssl_certificate_validation=False,
               proxy_host=None, proxy_port=None, ca_certs_file=None):
    # datetime_strategy is used to invoke utcnow() on; it is injected into the
    # constructor for unit testing purposes.
    self.auth_uri = auth_uri
    self.token_uri = token_uri
    self.cache_key_base = cache_key_base
    self.datetime_strategy = datetime_strategy
    self.access_token_cache = access_token_cache or InMemoryTokenCache()
    self.disable_ssl_certificate_validation = disable_ssl_certificate_validation
    self.ca_certs_file = ca_certs_file
    if proxy_host and proxy_port:
      self._proxy_info = httplib2.ProxyInfo(socks.PROXY_TYPE_HTTP,
                                            proxy_host,
                                            proxy_port,
                                            proxy_rdns=True)
    else:
      self._proxy_info = None
      
  def CreateHttpRequest(self):
    return httplib2.Http(
        ca_certs=self.ca_certs_file,
        disable_ssl_certificate_validation
            = self.disable_ssl_certificate_validation,
        proxy_info=self._proxy_info)

  def GetAccessToken(self):
    """Obtains an access token for this client.

    This client's access token cache is first checked for an existing,
    not-yet-expired access token. If none is found, the client obtains a fresh
    access token from the OAuth2 provider's token endpoint.

    Returns:
      The cached or freshly obtained AccessToken.
    Raises:
      AccessTokenRefreshError if an error occurs.
    """
    # Ensure only one thread at a time attempts to get (and possibly refresh)
    # the access token. This doesn't prevent concurrent refresh attempts across
    # multiple gsutil instances, but at least protects against multiple threads
    # simultaneously attempting to refresh when gsutil -m is used.
    token_exchange_lock.acquire()
    try:
      cache_key = self.CacheKey()
      LOG.debug('GetAccessToken: checking cache for key %s', cache_key)
      access_token = self.access_token_cache.GetToken(cache_key)
      LOG.debug('GetAccessToken: token from cache: %s', access_token)
      if access_token is None or access_token.ShouldRefresh():
        LOG.debug('GetAccessToken: fetching fresh access token...')
        access_token = self.FetchAccessToken()
        LOG.debug('GetAccessToken: fresh access token: %s', access_token)
        self.access_token_cache.PutToken(cache_key, access_token)
      return access_token
    finally:
      token_exchange_lock.release()

  def CacheKey(self):
    """Computes a cache key.

    The cache key is computed as the SHA1 hash of the refresh token for user
    accounts, or the hash of the gs_service_client_id for service accounts,
    which satisfies the FileSystemTokenCache requirement that cache keys do not
    leak information about token values.

    Returns:
      A hash key.
    """
    h = sha1()
    h.update(self.cache_key_base)
    return h.hexdigest()
  
  def GetAuthorizationHeader(self):
    """Gets the access token HTTP authorization header value.

    Returns:
      The value of an Authorization HTTP header that authenticates
      requests with an OAuth2 access token.
    """
    return 'Bearer %s' % self.GetAccessToken().token


class OAuth2ServiceAccountClient(OAuth2Client):

  def __init__(self, client_id, private_key, password,
               access_token_cache=None, auth_uri=None, token_uri=None,
               datetime_strategy=datetime.datetime,
               disable_ssl_certificate_validation=False,
               proxy_host=None, proxy_port=None, ca_certs_file=None):
    """Creates an OAuth2ServiceAccountClient.

    Args:
      client_id: The OAuth2 client ID of this client.
      private_key: The private key associated with this service account.
      password: The private key password used for the crypto signer.
      access_token_cache: An optional instance of a TokenCache. If omitted or
          None, an InMemoryTokenCache is used.
      auth_uri: The URI for OAuth2 authorization.
      token_uri: The URI used to refresh access tokens.
      datetime_strategy: datetime module strategy to use.
      disable_ssl_certificate_validation: True if certifications should not be
          validated.
      proxy_host: An optional string specifying the host name of an HTTP proxy
          to be used.
      proxy_port: An optional int specifying the port number of an HTTP proxy
          to be used.
      ca_certs_file: The cacerts.txt file to use.
    """
    super(OAuth2ServiceAccountClient, self).__init__(
        cache_key_base=client_id, auth_uri=auth_uri, token_uri=token_uri,
        access_token_cache=access_token_cache,
        datetime_strategy=datetime_strategy,
        disable_ssl_certificate_validation=disable_ssl_certificate_validation,
        proxy_host=proxy_host, proxy_port=proxy_port,
        ca_certs_file=ca_certs_file)
    self.client_id = client_id
    self.private_key = private_key
    self.password = password
  
  def FetchAccessToken(self):
    credentials = SignedJwtAssertionCredentials(self.client_id,
        self.private_key, scope=GSUTIL_DEFAULT_SCOPE,
        private_key_password=self.password)
    http = self.CreateHttpRequest()
    credentials.refresh(http)
    return AccessToken(credentials.access_token, 
        credentials.token_expiry, datetime_strategy=self.datetime_strategy)

  def GetCredentials(self):
    return SignedJwtAssertionCredentials(self.client_id,
        self.private_key, scope=GSUTIL_DEFAULT_SCOPE, 
        private_key_password=self.password)


class GsAccessTokenRefreshError(Exception):
  """Rate limiting error when exchanging refresh token for access token."""
  def __init__(self, e):
    super(Exception, self).__init__(e)


class GsInvalidRefreshTokenError(Exception):
  def __init__(self, e):
    super(Exception, self).__init__(e)


class OAuth2UserAccountClient(OAuth2Client):
  """An OAuth2 client."""

  def __init__(self, token_uri, client_id, client_secret, refresh_token,
               auth_uri=None, access_token_cache=None,
               datetime_strategy=datetime.datetime,
               disable_ssl_certificate_validation=False,
               proxy_host=None, proxy_port=None, ca_certs_file=None):
    """Creates an OAuth2UserAccountClient.

    Args:
      token_uri: The URI used to refresh access tokens.
      client_id: The OAuth2 client ID of this client.
      client_secret: The OAuth2 client secret of this client.
      refresh_token: The token used to refresh the access token.
      auth_uri: The URI for OAuth2 authorization.
      access_token_cache: An optional instance of a TokenCache. If omitted or
          None, an InMemoryTokenCache is used.
      datetime_strategy: datetime module strategy to use.
      disable_ssl_certificate_validation: True if certifications should not be
          validated.
      proxy_host: An optional string specifying the host name of an HTTP proxy
          to be used.
      proxy_port: An optional int specifying the port number of an HTTP proxy
          to be used.
      ca_certs_file: The cacerts.txt file to use.
    """
    super(OAuth2UserAccountClient, self).__init__(
        cache_key_base=refresh_token, auth_uri=auth_uri, token_uri=token_uri,
        access_token_cache=access_token_cache,
        datetime_strategy=datetime_strategy,
        disable_ssl_certificate_validation=disable_ssl_certificate_validation,
        proxy_host=proxy_host, proxy_port=proxy_port,
        ca_certs_file=ca_certs_file)
    self.token_uri = token_uri
    self.client_id = client_id
    self.client_secret = client_secret
    self.refresh_token = refresh_token

  def GetCredentials(self):
    """Fetches a credentials objects from the provider's token endpoint."""
    access_token = self.GetAccessToken()
    credentials = OAuth2Credentials(access_token.token, self.client_id,
        self.client_secret, self.refresh_token, access_token.expiry, self.token_uri, None)
    return credentials

  @Retry(GsAccessTokenRefreshError,
         tries=config.get('OAuth2', 'oauth2_refresh_retries', 6),
         timeout_secs=1)
  def FetchAccessToken(self):
    """Fetches an access token from the provider's token endpoint.

    Fetches an access token from this client's OAuth2 provider's token endpoint.

    Returns:
      The fetched AccessToken.
    """
    try:
      http = self.CreateHttpRequest()
      credentials = OAuth2Credentials(None, self.client_id, self.client_secret,
          self.refresh_token, None, self.token_uri, None)
      credentials.refresh(http)
      return AccessToken(credentials.access_token, 
          credentials.token_expiry, datetime_strategy=self.datetime_strategy)
    except AccessTokenRefreshError, e:
      if 'Invalid response 403' in e.message:
        # This is the most we can do at the moment to accurately detect rate
        # limiting errors since they come back as 403s with no further
        # information.
        raise GsAccessTokenRefreshError(e)
      elif 'invalid_grant' in e.message:
        LOG.info("""
Attempted to retrieve an access token from an invalid refresh token. Two common
cases in which you will see this error are:
1. Your refresh token was revoked.
2. Your refresh token was typed incorrectly.
""")
        raise GsInvalidRefreshTokenError(e)
      else:
        raise


class AccessToken(object):
  """Encapsulates an OAuth2 access token."""

  def __init__(self, token, expiry, datetime_strategy=datetime.datetime):
    self.token = token
    self.expiry = expiry
    self.datetime_strategy = datetime_strategy

  @staticmethod
  def UnSerialize(query):
    """Creates an AccessToken object from its serialized form."""

    def GetValue(d, key):
      return (d.get(key, [None]))[0]
    kv = cgi.parse_qs(query)
    if not kv['token']:
      return None
    expiry = None
    expiry_tuple = GetValue(kv, 'expiry')
    if expiry_tuple:
      try:
        expiry = datetime.datetime(
            *[int(n) for n in expiry_tuple.split(',')])
      except:
        return None
    return AccessToken(GetValue(kv, 'token'), expiry)

  def Serialize(self):
    """Serializes this object as URI-encoded key-value pairs."""
    # There's got to be a better way to serialize a datetime. Unfortunately,
    # there is no reliable way to convert into a unix epoch.
    kv = {'token': self.token}
    if self.expiry:
      t = self.expiry
      tupl = (t.year, t.month, t.day, t.hour, t.minute, t.second, t.microsecond)
      kv['expiry'] = ','.join([str(i) for i in tupl])
    return urllib.urlencode(kv)

  def ShouldRefresh(self, time_delta=300):
    """Whether the access token needs to be refreshed.

    Args:
      time_delta: refresh access token when it expires within time_delta secs.

    Returns:
      True if the token is expired or about to expire, False if the
      token should be expected to work.  Note that the token may still
      be rejected, e.g. if it has been revoked server-side.
    """
    if self.expiry is None:
      return False
    return (self.datetime_strategy.utcnow()
            + datetime.timedelta(seconds=time_delta) > self.expiry)

  def __eq__(self, other):
    return self.token == other.token and self.expiry == other.expiry

  def __ne__(self, other):
    return not self.__eq__(other)

  def __str__(self):
    return 'AccessToken(token=%s, expiry=%sZ)' % (self.token, self.expiry)

