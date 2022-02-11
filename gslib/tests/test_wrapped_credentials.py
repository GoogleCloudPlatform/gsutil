# -*- coding: utf-8 -*-
# Copyright 2022 Google Inc. All Rights Reserved.
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
"""Tests for wrapped_credentials.py."""

import json
import httplib2

from google.auth import credentials
from google.auth import external_account
from google.auth import identity_pool
from gslib.tests import testcase
from gslib.utils.wrapped_credentials import WrappedCredentials
import oauth2client

from six import add_move, MovedModule

add_move(MovedModule("mock", "mock", "unittest.mock"))
from six.moves import mock

ACCESS_TOKEN = "foo"
CONTENT = "content"
RESPONSE = httplib2.Response({
    "content-type": "text/plain",
    "status": "200",
    "content-length": len(CONTENT),
})


class MockCredentials(credentials.Credentials):
  refresh = mock.Mock()
  _audience = None

  def __init__(self, token=None, expiry=None, *args, **kwargs):
    super(*args, **kwargs)
    self.expiry = expiry
    self.token = None

    def side_effect(*args, **kwargs):
      self.token = token

    self.refresh.side_effect = side_effect

  @property
  def info(self):
    return {}


class HeadersWithAuth(dict):
  """A utility class to use to make sure a set of headers includes specific authentication"""

  def __init__(self, token):
    self.token = token or ""

  def __eq__(self, headers):
    return headers[b"Authorization"] == bytes("Bearer " + self.token, "utf-8")


class TestStorage(oauth2client.client.Storage):
  """Store and retrieve one set of credentials."""

  def __init__(self):
    super(TestStorage, self).__init__()
    self._str = None

  def locked_get(self):
    if self._str is None:
      return None

    credentials = oauth2client.client.Credentials.new_from_json(self._str)
    credentials.set_store(self)

    return credentials

  def locked_put(self, credentials):
    self._str = credentials.to_json()

  def locked_delete(self):
    self._str = None


def initialize_mock_creds(credentials, token):

  def side_effect(arg):
    credentials.token = token

  credentials.token = None
  credentials.expiry = None
  credentials._audience = "foo"
  credentials.refresh.side_effect = side_effect


class TestWrappedCredentials(testcase.GsUtilUnitTestCase):
  """Test logic for interacting with Wrapped Credentials the way we intend to use them."""

  @mock.patch.object(external_account, "Credentials", autospec=True)
  @mock.patch.object(httplib2, "Http", autospec=True)
  def testWrappedCredentialUsage(self, http, ea_creds):
    http.return_value.request.return_value = (RESPONSE, CONTENT)
    req = http.return_value.request
    initialize_mock_creds(ea_creds.return_value, ACCESS_TOKEN)

    creds = WrappedCredentials(
        external_account.Credentials(audience="foo",
                                     subject_token_type="bar",
                                     token_url="baz",
                                     credential_source="qux"))

    http = oauth2client.transport.get_http_object()
    creds.authorize(http)
    response, content = http.request(uri="www.google.com")
    self.assertEquals(content, CONTENT)
    ea_creds.return_value.refresh.assert_called_once()

    # Make sure the default request gets called with the correct token
    req.assert_called_once_with("www.google.com",
                                method="GET",
                                headers=HeadersWithAuth(ACCESS_TOKEN),
                                body=None,
                                connection_type=mock.ANY,
                                redirections=mock.ANY)

  def testWrappedCredentialSerialization(self):
    """Test logic for converting Wrapped Credentials to and from JSON for serialization."""
    creds = WrappedCredentials(
        identity_pool.Credentials(audience="foo",
                                  subject_token_type="bar",
                                  token_url="baz",
                                  credential_source={"url": "www.google.com"}))
    creds_json = creds.to_json()
    json_values = json.loads(creds_json)
    self.assertEquals(json_values["client_id"], "foo")
    self.assertEquals(json_values["_base"]["audience"], "foo")
    self.assertEquals(json_values["_base"]["subject_token_type"], "bar")
    self.assertEquals(json_values["_base"]["token_url"], "baz")
    self.assertEquals(json_values["_base"]["credential_source"]["url"],
                      "www.google.com")

    creds2 = WrappedCredentials.from_json(creds_json)
    self.assertIsInstance(creds2, WrappedCredentials)
    self.assertIsInstance(creds2._base, identity_pool.Credentials)
    self.assertEquals(creds2.client_id, "foo")
