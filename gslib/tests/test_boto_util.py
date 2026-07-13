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
"""Tests for boto_util.py."""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

import os
import boto.auth
from gslib import cloud_api
from gslib.utils import boto_util
from gslib import context_config
from gslib.tests import testcase
from gslib.tests.testcase import base
from gslib.tests.util import SetBotoConfigForTest
from gslib.tests.util import unittest

from six import add_move, MovedModule

add_move(MovedModule('mock', 'mock', 'unittest.mock'))
from six.moves import mock


class TestBotoUtil(testcase.GsUtilUnitTestCase):
  """Test utils that make use of the Boto dependency."""

  @mock.patch.object(context_config, 'get_context_config')
  def testSetsHostBaseToMtlsIfClientCertificateEnabled(self,
                                                       mock_get_context_config):
    mock_context_config = mock.Mock()
    mock_context_config.use_client_certificate = True
    mock_context_config.client_cert_path = 'path'
    mock_context_config.client_cert_password = 'password'
    mock_get_context_config.return_value = mock_context_config

    mock_http_class = mock.Mock(return_value=mock.Mock())
    mock_http = boto_util.GetNewHttp(mock_http_class)
    mock_http.add_certificate.assert_called_once_with(
        key='path',
        cert='path',
        domain='',
        password='password',
    )

  @mock.patch.object(boto.auth, 'get_auth_handler', return_value=None)
  def testHasConfiguredCredentialsNoCreds(self, _):
    with SetBotoConfigForTest([
        ('Credentials', 'gs_access_key_id', None),
        ('Credentials', 'gs_secret_access_key', None),
        ('Credentials', 'aws_access_key_id', None),
        ('Credentials', 'aws_secret_access_key', None),
        ('Credentials', 'gs_oauth2_refresh_token', None),
        ('Credentials', 'gs_external_account_file', None),
        ('Credentials', 'gs_external_account_authorized_user_file', None),
        ('Credentials', 'gs_service_client_id', None),
        ('Credentials', 'gs_service_key_file', None),
    ]):
      self.assertFalse(boto_util.HasConfiguredCredentials())

  @mock.patch.object(boto.auth, 'get_auth_handler', return_value=None)
  def testHasConfiguredCredentialsGoogCreds(self, _):
    with SetBotoConfigForTest([
        ('Credentials', 'gs_access_key_id', "?????"),
        ('Credentials', 'gs_secret_access_key', "?????"),
        ('Credentials', 'aws_access_key_id', None),
        ('Credentials', 'aws_secret_access_key', None),
        ('Credentials', 'gs_oauth2_refresh_token', None),
        ('Credentials', 'gs_external_account_file', None),
        ('Credentials', 'gs_external_account_authorized_user_file', None),
        ('Credentials', 'gs_service_client_id', None),
        ('Credentials', 'gs_service_key_file', None),
    ]):
      self.assertTrue(boto_util.HasConfiguredCredentials())

  @mock.patch.object(boto.auth, 'get_auth_handler', return_value=None)
  def testHasConfiguredCredentialsAmznCreds(self, _):
    with SetBotoConfigForTest([
        ('Credentials', 'gs_access_key_id', None),
        ('Credentials', 'gs_secret_access_key', None),
        ('Credentials', 'aws_access_key_id', "?????"),
        ('Credentials', 'aws_secret_access_key', "?????"),
        ('Credentials', 'gs_oauth2_refresh_token', None),
        ('Credentials', 'gs_external_account_file', None),
        ('Credentials', 'gs_external_account_authorized_user_file', None),
        ('Credentials', 'gs_service_client_id', None),
        ('Credentials', 'gs_service_key_file', None),
    ]):
      self.assertTrue(boto_util.HasConfiguredCredentials())

  @mock.patch.object(boto.auth, 'get_auth_handler', return_value=None)
  def testHasConfiguredCredentialsOauthCreds(self, _):
    with SetBotoConfigForTest([
        ('Credentials', 'gs_access_key_id', None),
        ('Credentials', 'gs_secret_access_key', None),
        ('Credentials', 'aws_access_key_id', None),
        ('Credentials', 'aws_secret_access_key', None),
        ('Credentials', 'gs_oauth2_refresh_token', "?????"),
        ('Credentials', 'gs_external_account_file', None),
        ('Credentials', 'gs_external_account_authorized_user_file', None),
        ('Credentials', 'gs_service_client_id', None),
        ('Credentials', 'gs_service_key_file', None),
    ]):
      self.assertTrue(boto_util.HasConfiguredCredentials())

  @mock.patch.object(boto.auth, 'get_auth_handler', return_value=None)
  def testHasConfiguredCredentialsExternalCreds(self, _):
    with SetBotoConfigForTest([
        ('Credentials', 'gs_access_key_id', None),
        ('Credentials', 'gs_secret_access_key', None),
        ('Credentials', 'aws_access_key_id', None),
        ('Credentials', 'aws_secret_access_key', None),
        ('Credentials', 'gs_oauth2_refresh_token', None),
        ('Credentials', 'gs_external_account_file', "?????"),
        ('Credentials', 'gs_external_account_authorized_user_file', None),
        ('Credentials', 'gs_service_client_id', None),
        ('Credentials', 'gs_service_key_file', None),
    ]):
      self.assertTrue(boto_util.HasConfiguredCredentials())

  @mock.patch.object(boto.auth, 'get_auth_handler', return_value=None)
  def testHasConfiguredCredentialsExternalAuthorizedUserCreds(self, _):
    with SetBotoConfigForTest([
        ('Credentials', 'gs_access_key_id', None),
        ('Credentials', 'gs_secret_access_key', None),
        ('Credentials', 'aws_access_key_id', None),
        ('Credentials', 'aws_secret_access_key', None),
        ('Credentials', 'gs_oauth2_refresh_token', None),
        ('Credentials', 'gs_external_account_file', None),
        ('Credentials', 'gs_external_account_authorized_user_file', "?????"),
        ('Credentials', 'gs_service_client_id', None),
        ('Credentials', 'gs_service_key_file', None),
    ]):
      self.assertTrue(boto_util.HasConfiguredCredentials())

  def testUsingGsHmacWithHmacAndServiceAccountCreds(self):
    with SetBotoConfigForTest([
        ('Credentials', 'gs_access_key_id', "?????"),
        ('Credentials', 'gs_secret_access_key', "?????"),
        ('Credentials', 'gs_external_account_file', None),
        ('Credentials', 'gs_external_account_authorized_user_file', None),
        ('Credentials', 'gs_oauth2_refresh_token', None),
        ('Credentials', 'gs_service_client_id', "?????"),
        ('Credentials', 'gs_service_key_file', "?????"),
    ]):
      self.assertFalse(boto_util.UsingGsHmac())

  def testUsingGsHmacWithHmacAndOauth2RefreshToken(self):
    with SetBotoConfigForTest([
        ('Credentials', 'gs_access_key_id', "?????"),
        ('Credentials', 'gs_secret_access_key', "?????"),
        ('Credentials', 'gs_external_account_file', None),
        ('Credentials', 'gs_external_account_authorized_user_file', None),
        ('Credentials', 'gs_oauth2_refresh_token', "?????"),
        ('Credentials', 'gs_service_client_id', None),
        ('Credentials', 'gs_service_key_file', None),
    ]):
      self.assertFalse(boto_util.UsingGsHmac())

  def testUsingGsHmacWithIncompleteHmacOnly(self):
    with SetBotoConfigForTest([
        ('Credentials', 'gs_access_key_id', "?????"),
        ('Credentials', 'gs_secret_access_key', None),
        ('Credentials', 'gs_external_account_file', None),
        ('Credentials', 'gs_external_account_authorized_user_file', None),
        ('Credentials', 'gs_oauth2_refresh_token', None),
        ('Credentials', 'gs_service_client_id', None),
        ('Credentials', 'gs_service_key_file', None),
    ]):
      self.assertFalse(boto_util.UsingGsHmac())

  def testUsingGsHmacWithHmacAndExternalAccountFile(self):
    with SetBotoConfigForTest([
        ('Credentials', 'gs_access_key_id', "?????"),
        ('Credentials', 'gs_secret_access_key', "?????"),
        ('Credentials', 'gs_external_account_file', "?????"),
        ('Credentials', 'gs_external_account_authorized_user_file', None),
        ('Credentials', 'gs_oauth2_refresh_token', None),
        ('Credentials', 'gs_service_client_id', None),
        ('Credentials', 'gs_service_key_file', None),
    ]):
      self.assertTrue(boto_util.UsingGsHmac())

  def testUsingGsHmacWithHmacAndExternalAccountAuthorizedUserFile(self):
    with SetBotoConfigForTest([
        ('Credentials', 'gs_access_key_id', "?????"),
        ('Credentials', 'gs_secret_access_key', "?????"),
        ('Credentials', 'gs_external_account_file', None),
        ('Credentials', 'gs_external_account_authorized_user_file', "?????"),
        ('Credentials', 'gs_oauth2_refresh_token', None),
        ('Credentials', 'gs_service_client_id', None),
        ('Credentials', 'gs_service_key_file', None),
    ]):
      self.assertTrue(boto_util.UsingGsHmac())

  def testUsingGsHmacWithHmacOnly(self):
    with SetBotoConfigForTest([
        ('Credentials', 'gs_access_key_id', "?????"),
        ('Credentials', 'gs_secret_access_key', "?????"),
        ('Credentials', 'gs_external_account_file', None),
        ('Credentials', 'gs_external_account_authorized_user_file', None),
        ('Credentials', 'gs_oauth2_refresh_token', None),
        ('Credentials', 'gs_service_client_id', None),
        ('Credentials', 'gs_service_key_file', None),
    ]):
      self.assertTrue(boto_util.UsingGsHmac())

  def testGetJsonResumableChunkSize(self):
    # Test default chunk size
    with SetBotoConfigForTest([]):
      self.assertEqual(boto_util.GetJsonResumableChunkSize(), 1024 * 1024 * 100)

    # Test chunk size set to 0 (should return minimum 256KiB)
    with SetBotoConfigForTest([('GSUtil', 'json_resumable_chunk_size', '0')]):
      self.assertEqual(boto_util.GetJsonResumableChunkSize(), 256 * 1024)

    # Test chunk size rounding up to 256KiB multiple (e.g. 300KiB -> 512KiB)
    with SetBotoConfigForTest([('GSUtil', 'json_resumable_chunk_size', str(300 * 1024))]):
      self.assertEqual(boto_util.GetJsonResumableChunkSize(), 512 * 1024)

    # Test chunk size exact multiple of 256KiB
    with SetBotoConfigForTest([('GSUtil', 'json_resumable_chunk_size', str(512 * 1024))]):
      self.assertEqual(boto_util.GetJsonResumableChunkSize(), 512 * 1024)

  def testJsonResumableChunkSizeDefined(self):
    with SetBotoConfigForTest([]):
      self.assertFalse(boto_util.JsonResumableChunkSizeDefined())
    with SetBotoConfigForTest([('GSUtil', 'json_resumable_chunk_size', '1048576')]):
      self.assertTrue(boto_util.JsonResumableChunkSizeDefined())

  @mock.patch.dict('os.environ', {}, clear=True)
  def testProxyInfoFromEnvironmentVar(self):
    # Verify environment variable not set
    proxy_info = boto_util.ProxyInfoFromEnvironmentVar('http_proxy')
    self.assertIsNone(proxy_info.proxy_host)

    # Verify environment variable with protocol
    os.environ['http_proxy'] = 'http://myproxy:8080'
    proxy_info = boto_util.ProxyInfoFromEnvironmentVar('http_proxy')
    self.assertEqual(proxy_info.proxy_host, 'myproxy')
    self.assertEqual(proxy_info.proxy_port, 8080)
    self.assertEqual(proxy_info.proxy_type, 3)  # HTTP

    # Verify environment variable without protocol
    os.environ['http_proxy'] = 'myproxy:8080'
    proxy_info = boto_util.ProxyInfoFromEnvironmentVar('http_proxy')
    self.assertEqual(proxy_info.proxy_host, 'myproxy')
    self.assertEqual(proxy_info.proxy_port, 8080)

  @mock.patch.dict('os.environ', {}, clear=True)
  def testSetProxyInfo(self):
    # Proxy from boto proxy config
    boto_proxy_config = {
        'proxy_host': 'botoproxy',
        'proxy_type': 'http',
        'proxy_port': 8080,
        'proxy_user': 'user',
        'proxy_pass': 'pass',
        'proxy_rdns': True
    }
    proxy_info = boto_util.SetProxyInfo(boto_proxy_config)
    self.assertEqual(proxy_info.proxy_host, 'botoproxy')
    self.assertEqual(proxy_info.proxy_port, 8080)
    self.assertEqual(proxy_info.proxy_user, 'user')
    self.assertEqual(proxy_info.proxy_pass, 'pass')

    # Fallback to environment variable if boto config is empty
    os.environ['http_proxy'] = 'http://envproxy:9090'
    empty_proxy_config = {
        'proxy_host': None,
        'proxy_type': 'http',
        'proxy_port': None,
        'proxy_user': None,
        'proxy_pass': None,
        'proxy_rdns': None
    }
    proxy_info = boto_util.SetProxyInfo(empty_proxy_config)
    self.assertEqual(proxy_info.proxy_host, 'envproxy')
    self.assertEqual(proxy_info.proxy_port, 9090)

  def testGetMaxConcurrentCompressedUploads(self):
    # By default, max buffer size is 2GiB, chunk size is 100MiB.
    # total_upload_size = 100MiB + 16MiB + metadata ~= 116MiB
    # 2GiB / 116MiB ~= 17.65 parallel uploads
    with SetBotoConfigForTest([]):
      self.assertAlmostEqual(boto_util.GetMaxConcurrentCompressedUploads(), 17.65, places=1)

    # If buffer size is smaller than chunk size, it returns the calculated ratio (e.g. 10MiB / 121.6MiB ~= 0.08)
    with SetBotoConfigForTest([
        ('GSUtil', 'json_resumable_chunk_size', '104857600'),  # 100MiB
        ('GSUtil', 'max_upload_compression_buffer_size', '10MiB')
    ]):
      self.assertAlmostEqual(boto_util.GetMaxConcurrentCompressedUploads(), 0.086, places=3)

  def testConfigureCertsFile(self):
    orig_configured_certs_file = boto_util.configured_certs_file
    orig_temp_certs_file = boto_util.temp_certs_file
    try:
      # Scenario 1: Boto ca_certificates_file is set to 'system' -> should return None
      with SetBotoConfigForTest([('Boto', 'ca_certificates_file', 'system')]):
        self.assertIsNone(boto_util.ConfigureCertsFile())

      # Scenario 2: Boto ca_certificates_file is set to a custom file -> should return that file path
      with SetBotoConfigForTest([('Boto', 'ca_certificates_file', '/custom/path/certs.txt')]):
        self.assertEqual(boto_util.ConfigureCertsFile(), '/custom/path/certs.txt')

      # Scenario 3: Boto ca_certificates_file is not set -> should fall back to configured_certs_file
      boto_util.configured_certs_file = '/fallback/path/certs.txt'
      with SetBotoConfigForTest([]):
        self.assertEqual(boto_util.ConfigureCertsFile(), '/fallback/path/certs.txt')
    finally:
      boto_util.configured_certs_file = orig_configured_certs_file
      boto_util.temp_certs_file = orig_temp_certs_file
