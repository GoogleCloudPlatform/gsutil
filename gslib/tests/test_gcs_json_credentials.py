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
"""Tests for gcs_json_credentials.py."""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

from apitools.base.py import GceAssertionCredentials
from google_reauth import reauth_creds
from gslib import gcs_json_api
from gslib import gcs_json_credentials
from gslib.exception import CommandException
from gslib.tests import testcase
from gslib.tests.util import SetBotoConfigForTest
from gslib.utils.wrapped_credentials import WrappedCredentials
from oauth2client.service_account import ServiceAccountCredentials
import pkgutil

from six import add_move, MovedModule

add_move(MovedModule("mock", "mock", "unittest.mock"))
from six.moves import mock


class TestGcsJsonCredentials(testcase.GsUtilUnitTestCase):
  """Test logic for interacting with GCS JSON Credentials."""

  @staticmethod
  def botoCredentialsSet(
      service_account_creds=None,
      user_account_creds=None,
      gce_creds=None,
      external_account_creds=None,
  ):
    config = []
    if service_account_creds:
      config.append(("Credentials", "gs_service_key_file",
                     service_account_creds["keyfile"]))
      config.append(("Credentials", "gs_service_client_id",
                     service_account_creds["client_id"]))
    else:
      config.append(("Credentials", "gs_service_key_file", None))
    config.append(
        ("Credentials", "gs_oauth2_refresh_token", user_account_creds))
    config.append(("GoogleCompute", "service_account", gce_creds))
    config.append(
        ("Credentials", "gs_external_account_file", external_account_creds))
    return config

  def testOauth2ServiceAccountCredential(self):
    contents = pkgutil.get_data("gslib", "tests/test_data/test.p12")
    tmpfile = self.CreateTempFile(contents=contents)
    with SetBotoConfigForTest(
        self.botoCredentialsSet(service_account_creds={
            "keyfile": tmpfile,
            "client_id": "?"
        })):
      self.assertTrue(gcs_json_credentials._HasOauth2ServiceAccountCreds())
      client = gcs_json_api.GcsJsonApi(None, None, None, None)
      creds = gcs_json_credentials._CheckAndGetCredentials(None)
      self.assertIsInstance(creds, ServiceAccountCredentials)

  def testOauth2UserCredential(self):
    with SetBotoConfigForTest(self.botoCredentialsSet(user_account_creds="?")):
      self.assertTrue(gcs_json_credentials._HasOauth2UserAccountCreds())
      client = gcs_json_api.GcsJsonApi(None, None, None, None)
      self.assertIsInstance(client.credentials,
                            reauth_creds.Oauth2WithReauthCredentials)

  @mock.patch(
      "gslib.gcs_json_credentials.credentials_lib.GceAssertionCredentials",
      autospec=True,
  )
  def testGCECredential(self, mock_credentials):

    def set_store(store):
      mock_credentials.return_value.store = store

    mock_credentials.return_value.client_id = None
    mock_credentials.return_value.refresh_token = "rEfrEshtOkEn"
    mock_credentials.return_value.set_store = set_store
    with SetBotoConfigForTest(self.botoCredentialsSet(gce_creds="?")):
      self.assertTrue(gcs_json_credentials._HasGceCreds())
      client = gcs_json_api.GcsJsonApi(None, None, None, None)
      self.assertIsInstance(client.credentials, GceAssertionCredentials)

  def testExternalAccountCredential(self):
    contents = pkgutil.get_data("gslib",
                                "tests/test_data/test_credentials.json")
    tmpfile = self.CreateTempFile(contents=contents)
    with SetBotoConfigForTest(
        self.botoCredentialsSet(external_account_creds=tmpfile)):
      client = gcs_json_api.GcsJsonApi(None, None, None, None)
      self.assertIsInstance(client.credentials, WrappedCredentials)

  def testOauth2ServiceAccountAndOauth2UserCredential(self):
    with SetBotoConfigForTest(
        self.botoCredentialsSet(user_account_creds="?",
                                service_account_creds={
                                    "keyfile": "?",
                                    "client_id": "?",
                                })):
      with self.assertRaises(CommandException):
        gcs_json_api.GcsJsonApi(None, None, None, None)
