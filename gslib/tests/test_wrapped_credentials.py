# -*- coding: utf-8 -*-
# Copyright 2022 Google LLC. All Rights Reserved.
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

import datetime
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


class MockCredentials(external_account.Credentials):

  def __init__(self, token=None, expiry=None, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._audience = None
    self.expiry = expiry
    self.token = None

    def side_effect(*args, **kwargs):
      self.token = token

    self.refresh = mock.Mock(side_effect=side_effect)

  def retrieve_subject_token():
    pass


class HeadersWithAuth(dict):
  """A utility class to use to make sure a set of headers includes specific authentication"""

  def __init__(self, token):
    self.token = token or ""

  def __eq__(self, headers):
    return headers[b"Authorization"] == bytes("Bearer " + self.token, "utf-8")


class TestWrappedCredentials(testcase.GsUtilUnitTestCase):
  """Test logic for interacting with Wrapped Credentials the way we intend to use them."""

  @mock.patch.object(httplib2, "Http", autospec=True)
  def testWrappedCredentialUsage(self, http):
    http.return_value.request.return_value = (RESPONSE, CONTENT)
    req = http.return_value.request

    creds = WrappedCredentials(
        MockCredentials(token=ACCESS_TOKEN,
                        audience="foo",
                        subject_token_type="bar",
                        token_url="baz",
                        credential_source="qux"))

    http = oauth2client.transport.get_http_object()
    creds.authorize(http)
    response, content = http.request(uri="www.google.com")
    self.assertEquals(content, CONTENT)
    creds._base.refresh.assert_called_once_with(mock.ANY)

    # Make sure the default request gets called with the correct token.
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
    creds.access_token = ACCESS_TOKEN
    creds.token_expiry = datetime.datetime(2001, 12, 5, 0, 0)
    creds_json = creds.to_json()
    json_values = json.loads(creds_json)
    self.assertEquals(json_values["client_id"], "foo")
    self.assertEquals(json_values['access_token'], ACCESS_TOKEN)
    self.assertEquals(json_values['token_expiry'], "2001-12-05T00:00:00Z")
    self.assertEquals(json_values["_base"]["audience"], "foo")
    self.assertEquals(json_values["_base"]["subject_token_type"], "bar")
    self.assertEquals(json_values["_base"]["token_url"], "baz")
    self.assertEquals(json_values["_base"]["credential_source"]["url"],
                      "www.google.com")

    creds2 = WrappedCredentials.from_json(creds_json)
    self.assertIsInstance(creds2, WrappedCredentials)
    self.assertIsInstance(creds2._base, identity_pool.Credentials)
    self.assertEquals(creds2.client_id, "foo")
    self.assertEquals(creds2.access_token, ACCESS_TOKEN)
    self.assertEquals(creds2.token_expiry, creds.token_expiry)

  def testWrappedCredentialSerializationMissingKeywords(self):
    """Test logic for creating a Wrapped Credentials using keywords that exist in IdentityPool but not AWS."""
    creds = WrappedCredentials.from_json(
        json.dumps({
            "client_id": "foo",
            "access_token": ACCESS_TOKEN,
            "token_expiry": "2001-12-05T00:00:00Z",
            "_base": {
                "audience": "foo",
                "subject_token_type": "bar",
                "token_url": "baz",
                "credential_source": {
                    "url": "www.google.com",
                    "workforce_pool_user_project": "1234567890"
                }
            }
        }))

    self.assertIsInstance(creds, WrappedCredentials)
    self.assertIsInstance(creds._base, identity_pool.Credentials)
