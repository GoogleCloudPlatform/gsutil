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
"""Tests for gcs_json_credentials.py."""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

from apitools.base.py import GceAssertionCredentials
from google_reauth import reauth_creds
from gslib import gcs_json_api
from gslib import gcs_json_credentials
from gslib.cred_types import CredTypes
from gslib.exception import CommandException
from gslib.tests import testcase
from gslib.tests.util import SetBotoConfigForTest
from gslib.tests.util import unittest
from gslib.utils.wrapped_credentials import WrappedCredentials
import logging
from oauth2client.service_account import ServiceAccountCredentials
import pkgutil

from six import add_move, MovedModule

add_move(MovedModule("mock", "mock", "unittest.mock"))
from six.moves import mock

try:
  import cryptography
  HAS_CRYPTO = True
except ImportError:
  HAS_CRYPTO = False

ERROR_MESSAGE = "This is the error message"


def getBotoCredentialsConfig(
    service_account_creds=None,
    user_account_creds=None,
    gce_creds=None,
    external_account_creds=None,
    external_account_authorized_user_creds=None,
):
  config = []
  if service_account_creds:
    config.append(("Credentials", "gs_service_key_file",
                   service_account_creds["keyfile"]))
    config.append(("Credentials", "gs_service_client_id",
                   service_account_creds["client_id"]))
  else:
    config.append(("Credentials", "gs_service_key_file", None))
  config.extend([("Credentials", "gs_oauth2_refresh_token", user_account_creds),
                 ("GoogleCompute", "service_account", gce_creds),
                 ("Credentials", "gs_external_account_file",
                  external_account_creds),
                 ("Credentials", "gs_external_account_authorized_user_file",
                  external_account_authorized_user_creds)])
  return config


class TestGcsJsonCredentials(testcase.GsUtilUnitTestCase):
  """Test logic for interacting with GCS JSON Credentials."""

  @mock.patch.object(gcs_json_credentials.P12Credentials,
                     "from_service_account_pkcs12_keystring",
                     return_value=gcs_json_credentials.P12Credentials(mock.Mock(), token_uri='123', service_account_email='123', scopes=['a', 'b']))
  def testOauth2ServiceAccountCredential(self, _):
    contents = pkgutil.get_data("gslib", "tests/test_data/test.p12")
    tmpfile = self.CreateTempFile(contents=contents)
    with SetBotoConfigForTest(
        getBotoCredentialsConfig(service_account_creds={
            "keyfile": tmpfile,
            "client_id": "?",
        })):
      self.assertTrue(gcs_json_credentials._HasOauth2ServiceAccountCreds())
      client = gcs_json_api.GcsJsonApi(None, None, None, None)
      self.assertEqual(client.credentials.service_account_email, '123')
      self.assertIsInstance(client.credentials, gcs_json_credentials.P12Credentials)

  def testP12CredentialsthrowsErrorIfProvidedWithMissingFields(self):
    contents = pkgutil.get_data("gslib", "tests/test_data/test.p12")
    tmpfile = self.CreateTempFile(contents=contents)
    with self.assertRaises(Exception) as exc:
      gcs_json_credentials.CreateP12ServiceAccount(tmpfile)

  @unittest.skipUnless(HAS_CRYPTO, 'p12credentials requires cryptography.')
  @mock.patch.object(gcs_json_credentials.P12Credentials,
                     "__init__",
                     side_effect=ValueError(ERROR_MESSAGE))
  def testOauth2ServiceAccountFailure(self, _):
    contents = pkgutil.get_data("gslib", "tests/test_data/test.p12")
    tmpfile = self.CreateTempFile(contents=contents)
    with SetBotoConfigForTest(
        getBotoCredentialsConfig(service_account_creds={
            "keyfile": tmpfile,
            "client_id": "?",
        })):
      with self.assertLogs() as logger:
        with self.assertRaises(Exception) as exc:
          gcs_json_api.GcsJsonApi(None, logging.getLogger(), None, None)
        self.assertIn(ERROR_MESSAGE, str(exc.exception))
        self.assertIn(CredTypes.OAUTH2_SERVICE_ACCOUNT, logger.output[0])

  def testOauth2UserCredential(self):
    with SetBotoConfigForTest(getBotoCredentialsConfig(user_account_creds="?")):
      self.assertTrue(gcs_json_credentials._HasOauth2UserAccountCreds())
      client = gcs_json_api.GcsJsonApi(None, None, None, None)
      self.assertIsInstance(client.credentials,
                            reauth_creds.Oauth2WithReauthCredentials)

  @mock.patch.object(reauth_creds.Oauth2WithReauthCredentials,
                     "__init__",
                     side_effect=ValueError(ERROR_MESSAGE))
  def testOauth2UserFailure(self, _):
    with SetBotoConfigForTest(getBotoCredentialsConfig(user_account_creds="?")):
      with self.assertLogs() as logger:
        with self.assertRaises(Exception) as exc:
          gcs_json_api.GcsJsonApi(None, logging.getLogger(), None, None)
        self.assertIn(ERROR_MESSAGE, str(exc.exception))
        self.assertIn(CredTypes.OAUTH2_USER_ACCOUNT, logger.output[0])

  @mock.patch.object(gcs_json_credentials.credentials_lib,
                     'GceAssertionCredentials',
                     autospec=True)
  def testGCECredential(self, mock_credentials):

    def set_store(store):
      mock_credentials.return_value.store = store

    mock_credentials.return_value.client_id = None
    mock_credentials.return_value.refresh_token = "rEfrEshtOkEn"
    mock_credentials.return_value.set_store = set_store
    with SetBotoConfigForTest(getBotoCredentialsConfig(gce_creds="?")):
      self.assertTrue(gcs_json_credentials._HasGceCreds())
      client = gcs_json_api.GcsJsonApi(None, None, None, None)
      # Since we've patched the class, the returned object is a mock, 
      # but we can check if it was called.
      self.assertEqual(client.credentials, mock_credentials.return_value)
      self.assertEqual(client.credentials.refresh_token, "rEfrEshtOkEn")
      self.assertIs(client.credentials.client_id, None)

  @mock.patch.object(GceAssertionCredentials,
                     "__init__",
                     side_effect=ValueError(ERROR_MESSAGE))
  def testGCECredentialFailure(self, _):
    # We need to bypass the DetectGce check that happens before __init__ 
    # if it's called from apitools credentials_lib.
    with mock.patch('apitools.base.py.util.DetectGce', return_value=True):
      with SetBotoConfigForTest(getBotoCredentialsConfig(gce_creds="?")):
        with self.assertLogs() as logger:
          with self.assertRaises(Exception) as exc:
            gcs_json_api.GcsJsonApi(None, logging.getLogger(), None, None)
          self.assertIn(ERROR_MESSAGE, str(exc.exception))
          self.assertIn(CredTypes.GCE, logger.output[0])

  def testExternalAccountCredential(self):
    contents = pkgutil.get_data(
        "gslib", "tests/test_data/test_external_account_credentials.json")
    tmpfile = self.CreateTempFile(contents=contents)
    with SetBotoConfigForTest(
        getBotoCredentialsConfig(external_account_creds=tmpfile)):
      client = gcs_json_api.GcsJsonApi(None, None, None, None)
      self.assertIsInstance(client.credentials, WrappedCredentials)

  @mock.patch.object(WrappedCredentials,
                     "__init__",
                     side_effect=ValueError(ERROR_MESSAGE))
  def testExternalAccountFailure(self, _):
    contents = pkgutil.get_data(
        "gslib", "tests/test_data/test_external_account_credentials.json")
    tmpfile = self.CreateTempFile(contents=contents)
    with SetBotoConfigForTest(
        getBotoCredentialsConfig(external_account_creds=tmpfile)):
      with self.assertLogs() as logger:
        with self.assertRaises(Exception) as exc:
          gcs_json_api.GcsJsonApi(None, logging.getLogger(), None, None)
        self.assertIn(ERROR_MESSAGE, str(exc.exception))
        self.assertIn(CredTypes.EXTERNAL_ACCOUNT, logger.output[0])

  def testExternalAccountAuthorizedUserCredential(self):
    contents = pkgutil.get_data(
        "gslib",
        "tests/test_data/test_external_account_authorized_user_credentials.json"
    )
    tmpfile = self.CreateTempFile(contents=contents)
    with SetBotoConfigForTest(
        getBotoCredentialsConfig(
            external_account_authorized_user_creds=tmpfile)):
      client = gcs_json_api.GcsJsonApi(None, None, None, None)
      self.assertIsInstance(client.credentials, WrappedCredentials)

  @mock.patch.object(WrappedCredentials,
                     "__init__",
                     side_effect=ValueError(ERROR_MESSAGE))
  def testExternalAccountAuthorizedUserFailure(self, _):
    contents = pkgutil.get_data(
        "gslib",
        "tests/test_data/test_external_account_authorized_user_credentials.json"
    )
    tmpfile = self.CreateTempFile(contents=contents)
    with SetBotoConfigForTest(
        getBotoCredentialsConfig(
            external_account_authorized_user_creds=tmpfile)):
      with self.assertLogs() as logger:
        with self.assertRaises(Exception) as exc:
          gcs_json_api.GcsJsonApi(None, logging.getLogger(), None, None)
        self.assertIn(ERROR_MESSAGE, str(exc.exception))
        self.assertIn(CredTypes.EXTERNAL_ACCOUNT_AUTHORIZED_USER,
                      logger.output[0])

  def testOauth2ServiceAccountAndOauth2UserCredential(self):
    with SetBotoConfigForTest(
        getBotoCredentialsConfig(user_account_creds="?",
                                 service_account_creds={
                                     "keyfile": "?",
                                     "client_id": "?",
                                 })):
      with self.assertRaises(CommandException):
        gcs_json_api.GcsJsonApi(None, None, None, None)

  def testServiceAccountJsonInvalidJsonRaises(self):
    tmpfile = self.CreateTempFile(contents=b'{"invalid_json": ')
    with SetBotoConfigForTest(
        getBotoCredentialsConfig(service_account_creds={
            "keyfile": tmpfile,
            "client_id": "?",
        })):
      with self.assertRaisesRegex(Exception, 'Could not parse JSON keyfile'):
        gcs_json_api.GcsJsonApi(None, logging.getLogger(), None, None)

  def testServiceAccountJsonMissingFieldsRaises(self):
    import json
    required_fields = ['client_id', 'client_email', 'private_key_id', 'private_key']
    base_dict = {
        'client_id': '123',
        'client_email': 'a@b.com',
        'private_key_id': '456',
        'private_key': 'abc'
    }

    for missing_field in required_fields:
      test_dict = base_dict.copy()
      del test_dict[missing_field]

      tmpfile = self.CreateTempFile(contents=json.dumps(test_dict).encode('utf-8'))
      with SetBotoConfigForTest(
          getBotoCredentialsConfig(service_account_creds={
              "keyfile": tmpfile,
              "client_id": "?",
          })):
        with self.assertRaisesRegex(Exception, 'did not contain the required entry: %s' % missing_field):
          gcs_json_api.GcsJsonApi(None, logging.getLogger(), None, None)

  @unittest.skipUnless(HAS_CRYPTO, 'p12credentials requires cryptography.')
  def testPKCS12SignerInvalidKeyfileRaises(self):
    with self.assertRaisesRegex(CommandException, 'Unable to load the keyfile'):
      gcs_json_credentials.CreateP12ServiceAccount(b'invalid-p12-data', b'password')

  @unittest.skipUnless(HAS_CRYPTO, 'p12credentials requires cryptography.')
  def testPKCS12SignerInvalidPasswordRaises(self):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.hazmat.primitives import serialization
    import datetime

    # 1. Generate private key and self-signed certificate
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(private_key, hashes.SHA256())
    )

    # 2. Serialize to PKCS12 format with password b'correct-password'
    p12_data = pkcs12.serialize_key_and_certificates(
        b'test', private_key, cert, None,
        serialization.BestAvailableEncryption(b'correct-password')
    )

    # 3. Assert that attempting to create a signer/credentials with incorrect password fails
    with self.assertRaisesRegex(CommandException, 'Unable to load the keyfile'):
      gcs_json_credentials.CreateP12ServiceAccount(p12_data, b'incorrect-password')

