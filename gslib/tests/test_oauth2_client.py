import datetime
import gslib.tests.testcase as testcase
import gslib.third_party.oauth2_plugin.oauth2_client as oauth2_client
import logging
import os
from stat import S_IMODE
import unittest

LOG = logging.getLogger('test_oauth2_client')

ACCESS_TOKEN = 'abc123'
TOKEN_URI = 'https://provider.example.com/oauth/provider?mode=token'
AUTH_URI = 'https://provider.example.com/oauth/provider?mode=authorize'
DEFAULT_CA_CERTS_FILE = os.path.abspath(
    os.path.join('gslib', 'data', 'cacerts.txt'))

class MockDateTime:
  def __init__(self):
    self.mock_now = None

  def utcnow(self):
    return self.mock_now

class MockOAuth2ServiceAccountClient(oauth2_client.OAuth2ServiceAccountClient):
  def __init__(self, client_id, private_key, password, auth_uri, token_uri,
               datetime_strategy):
    super(MockOAuth2ServiceAccountClient, self).__init__(
        client_id, private_key, password, auth_uri=auth_uri,
        token_uri=token_uri, datetime_strategy=datetime_strategy,
        ca_certs_file=DEFAULT_CA_CERTS_FILE)
    self.Reset()

  def Reset(self):
    self.fetched_token = False

  def FetchAccessToken(self):
    self.fetched_token = True
    return oauth2_client.AccessToken(
        ACCESS_TOKEN,
        GetExpiry(self.datetime_strategy, 3600),
        datetime_strategy=self.datetime_strategy)


class MockOAuth2UserAccountClient(oauth2_client.OAuth2UserAccountClient):
  def __init__(self, token_uri, client_id, client_secret, refresh_token,
               auth_uri, datetime_strategy):
    super(MockOAuth2UserAccountClient, self).__init__(
        token_uri, client_id, client_secret, refresh_token, auth_uri=auth_uri,
        datetime_strategy=datetime_strategy,
        ca_certs_file=DEFAULT_CA_CERTS_FILE)
    self.Reset()

  def Reset(self):
    self.fetched_token = False

  def FetchAccessToken(self):
    self.fetched_token = True
    return oauth2_client.AccessToken(
        ACCESS_TOKEN,
        GetExpiry(self.datetime_strategy, 3600),
        datetime_strategy=self.datetime_strategy)

def GetExpiry(datetime_strategy, lengthInSeconds):
  token_expiry = (datetime_strategy.utcnow()
                  + datetime.timedelta(seconds=lengthInSeconds))
  return token_expiry

def CreateMockUserAccountClient(start_time, mock_datetime):
  return MockOAuth2UserAccountClient(
        TOKEN_URI, 'clid', 'clsecret', 'ref_token_abc123', AUTH_URI,
        mock_datetime)

def CreateMockServiceAccountClient(start_time, mock_datetime):
  return MockOAuth2ServiceAccountClient(
      'clid', 'private_key', 'password', AUTH_URI, TOKEN_URI,
      mock_datetime)


class OAuth2UserAccountClientTest(testcase.GsUtilUnitTestCase):

  def setUp(self):
    self.tempdirs = []
    self.mock_datetime = MockDateTime()
    self.start_time = datetime.datetime(2011, 3, 1, 10, 25, 13, 300826)
    self.mock_datetime.mock_now = self.start_time


  def testGetAccessTokenUserAccount(self):
    self.client = CreateMockUserAccountClient(self.start_time,
                                              self.mock_datetime)
    self._RunGetAccessTokenTest()


  def testGetAccessTokenServiceAccount(self):
    self.client = CreateMockServiceAccountClient(self.start_time,
                                                 self.mock_datetime)
    self._RunGetAccessTokenTest()


  def _RunGetAccessTokenTest(self):
    refresh_token = 'ref_token'
    access_token_1 = 'abc123'

    self.assertFalse(self.client.fetched_token)
    token_1 = self.client.GetAccessToken()

    # There's no access token in the cache; verify that we fetched a fresh
    # token.
    self.assertTrue(self.client.fetched_token)
    self.assertEquals(access_token_1, token_1.token)
    self.assertEquals(self.start_time + datetime.timedelta(minutes=60),
                      token_1.expiry)

    # Advance time by less than expiry time, and fetch another token.
    self.client.Reset()
    self.mock_datetime.mock_now = (
        self.start_time + datetime.timedelta(minutes=55))
    token_2 = self.client.GetAccessToken()

    # Since the access token wasn't expired, we get the cache token, and there
    # was no refresh request.
    self.assertEquals(token_1, token_2)
    self.assertEquals(access_token_1, token_2.token)
    self.assertFalse(self.client.fetched_token)

    # Advance time past expiry time, and fetch another token.
    self.client.Reset()
    self.mock_datetime.mock_now = (
        self.start_time + datetime.timedelta(minutes=55, seconds=1))
    self.client.datetime_strategy = self.mock_datetime
    access_token_2 = 'zyx456'
    token_3 = self.client.GetAccessToken()

    # This should have resulted in a refresh request and a fresh access token.
    self.assertTrue(self.client.fetched_token)
    self.assertEquals(
        self.mock_datetime.mock_now + datetime.timedelta(minutes=60),
        token_3.expiry)


class AccessTokenTest(unittest.TestCase):

  def testShouldRefresh(self):
    mock_datetime = MockDateTime()
    start = datetime.datetime(2011, 3, 1, 11, 25, 13, 300826)
    expiry = start + datetime.timedelta(minutes=60)
    token = oauth2_client.AccessToken(
        'foo', expiry, datetime_strategy=mock_datetime)

    mock_datetime.mock_now = start
    self.assertFalse(token.ShouldRefresh())

    mock_datetime.mock_now = start + datetime.timedelta(minutes=54)
    self.assertFalse(token.ShouldRefresh())

    mock_datetime.mock_now = start + datetime.timedelta(minutes=55)
    self.assertFalse(token.ShouldRefresh())

    mock_datetime.mock_now = start + datetime.timedelta(
        minutes=55, seconds=1)
    self.assertTrue(token.ShouldRefresh())

    mock_datetime.mock_now = start + datetime.timedelta(
        minutes=61)
    self.assertTrue(token.ShouldRefresh())

    mock_datetime.mock_now = start + datetime.timedelta(minutes=58)
    self.assertFalse(token.ShouldRefresh(time_delta=120))

    mock_datetime.mock_now = start + datetime.timedelta(
        minutes=58, seconds=1)
    self.assertTrue(token.ShouldRefresh(time_delta=120))

  def testShouldRefreshNoExpiry(self):
    mock_datetime = MockDateTime()
    start = datetime.datetime(2011, 3, 1, 11, 25, 13, 300826)
    token = oauth2_client.AccessToken(
        'foo', None, datetime_strategy=mock_datetime)

    mock_datetime.mock_now = start
    self.assertFalse(token.ShouldRefresh())

    mock_datetime.mock_now = start + datetime.timedelta(
        minutes=472)
    self.assertFalse(token.ShouldRefresh())

  def testSerialization(self):
    expiry = datetime.datetime(2011, 3, 1, 11, 25, 13, 300826)
    token = oauth2_client.AccessToken('foo', expiry)
    serialized_token = token.Serialize()
    LOG.debug('testSerialization: serialized_token=%s' % serialized_token)

    token2 = oauth2_client.AccessToken.UnSerialize(serialized_token)
    self.assertEquals(token, token2)

class FileSystemTokenCacheTest(unittest.TestCase):

  def setUp(self):
    self.cache = oauth2_client.FileSystemTokenCache()
    self.start_time = datetime.datetime(2011, 3, 1, 10, 25, 13, 300826)
    self.token_1 = oauth2_client.AccessToken('token1', self.start_time)
    self.token_2 = oauth2_client.AccessToken(
        'token2', self.start_time + datetime.timedelta(seconds=492))
    self.key = 'token1key'

  def tearDown(self):
    try:
      os.unlink(self.cache.CacheFileName(self.key))
    except:
      pass

  def testPut(self):
    self.cache.PutToken(self.key, self.token_1)
    # Assert that the cache file exists and has correct permissions.
    self.assertEquals(
        0600, S_IMODE(os.stat(self.cache.CacheFileName(self.key)).st_mode))

  def testPutGet(self):
    # No cache file present.
    self.assertEquals(None, self.cache.GetToken(self.key))

    # Put a token
    self.cache.PutToken(self.key, self.token_1)
    cached_token = self.cache.GetToken(self.key)
    self.assertEquals(self.token_1, cached_token)

    # Put a different token
    self.cache.PutToken(self.key, self.token_2)
    cached_token = self.cache.GetToken(self.key)
    self.assertEquals(self.token_2, cached_token)

  def testGetBadFile(self):
    f = open(self.cache.CacheFileName(self.key), 'w')
    f.write('blah')
    f.close()
    self.assertEquals(None, self.cache.GetToken(self.key))

  def testCacheFileName(self):
    cache = oauth2_client.FileSystemTokenCache(
        path_pattern='/var/run/ccache/token.%(uid)s.%(key)s')
    self.assertEquals('/var/run/ccache/token.%d.abc123' % os.getuid(),
                      cache.CacheFileName('abc123'))

    cache = oauth2_client.FileSystemTokenCache(
        path_pattern='/var/run/ccache/token.%(key)s')
    self.assertEquals('/var/run/ccache/token.abc123',
                      cache.CacheFileName('abc123'))


class RefreshTokenTest(unittest.TestCase):
  def setUp(self):
    self.mock_datetime = MockDateTime()
    self.start_time = datetime.datetime(2011, 3, 1, 10, 25, 13, 300826)
    self.mock_datetime.mock_now = self.start_time
    self.client = CreateMockUserAccountClient(self.start_time,
                                              self.mock_datetime)


  def testUniqeId(self):
    cred_id = self.client.CacheKey()
    self.assertEquals('0720afed6871f12761fbea3271f451e6ba184bf5', cred_id)

  def testGetAuthorizationHeader(self):
    self.assertEquals('Bearer %s' % ACCESS_TOKEN,
                      self.client.GetAuthorizationHeader())
