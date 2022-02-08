# -*- coding: utf-8 -*-
# Copyright 2020 Google Inc. All Rights Reserved.
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

from google.auth import credentials
from gslib.tests import testcase
from gslib.utils.wrapped_credentials import WrappedCredentials
import httplib2
import oauth2client
from oauth2client.contrib import dictionary_storage

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
    self.token = token

  @property
  def info(self):
    return {}


class TestWrappedCredentials(testcase.GsUtilUnitTestCase):
  """Test logic for interacting with Wrapped Credentials."""

  @mock.patch("oauth2client.transport.httplib2.Http", autospec=True)
  def testWrappedCredentialUsage(self, http):
    http.return_value.request.return_value = (RESPONSE, CONTENT)

    creds = WrappedCredentials(MockCredentials(token=ACCESS_TOKEN))

    http = oauth2client.transport.get_http_object()
    creds.authorize(http)
    response, content = http.request(uri="www.google.com")
    self.assertEquals(content, CONTENT)

  @mock.patch("oauth2client.transport.httplib2.Http", autospec=True)
  def testWrappedCredentialUsageFromCache(self, http):
    http.return_value.request.return_value = (RESPONSE, CONTENT)

    base_creds = WrappedCredentials(MockCredentials(token=ACCESS_TOKEN))
    storage = dictionary_storage.DictionaryStorage({}, "")
    storage.put(base_creds)
    creds = storage.get()

    http = oauth2client.transport.get_http_object()
    creds.authorize(http)
    response, content = http.request(uri="www.google.com")
    self.assertEquals(content, CONTENT)
