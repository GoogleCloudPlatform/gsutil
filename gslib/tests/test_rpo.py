# -*- coding: utf-8 -*-
# Copyright 2018 Google Inc. All Rights Reserved.
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
"""Integration tests for rpo command."""

from __future__ import absolute_import

import textwrap

from gslib.commands.rpo import RpoCommand
from gslib.exception import CommandException
from gslib.gcs_json_api import GcsJsonApi
from gslib.storage_url import StorageUrlFromString
import gslib.tests.testcase as testcase
from gslib.tests.testcase.integration_testcase import SkipForGS
from gslib.tests.testcase.integration_testcase import SkipForJSON
from gslib.tests.testcase.integration_testcase import SkipForXML
from gslib.tests.util import ObjectToURI as suri
from gslib.tests.util import SetBotoConfigForTest

from six import add_move, MovedModule

add_move(MovedModule('mock', 'mock', 'unittest.mock'))
from six.moves import mock


class TestLsUnit(testcase.GsUtilUnitTestCase):

  def test_get_for_multiple_bucket_calls_api(self):
    bucket_uri1 = self.CreateBucket(bucket_name='foo')
    bucket_uri2 = self.CreateBucket(bucket_name='bar')
    stdout = self.RunCommand(
        'rpo',
        ['get', suri(bucket_uri1), suri(bucket_uri2)],
        return_stdout=True)
    expected_string = textwrap.dedent("""\
      gs://foo: None
      gs://bar: None
      """)
    self.assertEqual(expected_string, stdout)

  def test_get_with_wildcard(self):
    self.CreateBucket(bucket_name='boo1')
    self.CreateBucket(bucket_name='boo2')
    stdout = self.RunCommand('rpo', ['get', 'gs://boo*'], return_stdout=True)
    expected_string = textwrap.dedent("""\
      gs://boo1: None
      gs://boo2: None
      """)
    self.assertEqual(expected_string, stdout)

  def test_get_with_wrong_url_raises_error(self):
    with self.assertRaisesRegex(CommandException, 'No URLs matched'):
      self.RunCommand('rpo', ['get', 'gs://invalid*'])

  def test_set_called_with_incorrect_value(self):
    with self.assertRaisesRegex(CommandException, 'Invalid value for rpo set.'):
      self.RunCommand('rpo', ['set', 'random', 'gs://boo*'])

  def test_invalid_subcommand_raises_error(self):
    with self.assertRaisesRegex(
        CommandException, r'Invalid subcommand "blah", use get|set instead'):
      self.RunCommand('rpo', ['blah', 'random', 'gs://boo*'])


class TestRpo(testcase.GsUtilIntegrationTestCase):
  """Integration tests for rpo command."""

  @SkipForXML('RPO only runs on GCS JSON API')
  def test_get_returns_default_for_dual_region_bucket(self):
    bucket_uri = self.CreateBucket(location='us')
    self.VerifyCommandGet(bucket_uri, 'rpo', 'DEFAULT')

  @SkipForXML('RPO only runs on GCS JSON API')
  def test_get_returns_none_for_regional_bucket(self):
    bucket_uri = self.CreateBucket(location='us-central1')
    self.VerifyCommandGet(bucket_uri, 'rpo', 'None')

  @SkipForXML('RPO only runs on GCS JSON API')
  def test_set_and_get_async_turbo(self):
    bucket_uri = self.CreateBucket(location='nam4')
    self.VerifyCommandGet(bucket_uri, 'rpo', 'DEFAULT')
    self.RunGsUtil(['rpo', 'set', 'ASYNC_TURBO', suri(bucket_uri)])
    self.VerifyCommandGet(bucket_uri, 'rpo', 'ASYNC_TURBO')

  @SkipForXML('RPO only runs on GCS JSON API')
  def test_set_default(self):
    bucket_uri = self.CreateBucket(location='nam4')
    self.RunGsUtil(['rpo', 'set', 'ASYNC_TURBO', suri(bucket_uri)])
    self.VerifyCommandGet(bucket_uri, 'rpo', 'ASYNC_TURBO')
    self.RunGsUtil(['rpo', 'set', 'DEFAULT', suri(bucket_uri)])
    self.VerifyCommandGet(bucket_uri, 'rpo', 'DEFAULT')

  @SkipForXML('RPO only runs on GCS JSON API')
  def test_set_async_turbo_fails_for_regional_buckets(self):
    bucket_uri = self.CreateBucket(location='us-central1')
    stderr = self.RunGsUtil(['rpo', 'set', 'ASYNC_TURBO',
                             suri(bucket_uri)],
                            expected_status=1,
                            return_stderr=True)
    self.assertIn('Invalid argument', stderr)

  @SkipForJSON('Testing XML only behavior')
  def test_xml_fails_for_set(self):
    # use HMAC for force XML API
    boto_config_hmac_auth_only = [
        # Overwrite other credential types.
        ('Credentials', 'gs_oauth2_refresh_token', None),
        ('Credentials', 'gs_service_client_id', None),
        ('Credentials', 'gs_service_key_file', None),
        ('Credentials', 'gs_service_key_file_password', None),
        # Add hmac credentials.
        ('Credentials', 'gs_access_key_id', 'dummykey'),
        ('Credentials', 'gs_secret_access_key', 'dummysecret'),
    ]
    with SetBotoConfigForTest(boto_config_hmac_auth_only):
      bucket_uri = 'gs://any-bucket-name'
      stderr = self.RunGsUtil(['rpo', 'set', 'default', bucket_uri],
                              return_stderr=True,
                              expected_status=1)
      self.assertIn('command can only be with the Cloud Storage JSON API',
                    stderr)

  @SkipForJSON('Testing XML only behavior')
  def test_xml_fails_for_get(self):
    # use HMAC for force XML API
    boto_config_hmac_auth_only = [
        # Overwrite other credential types.
        ('Credentials', 'gs_oauth2_refresh_token', None),
        ('Credentials', 'gs_service_client_id', None),
        ('Credentials', 'gs_service_key_file', None),
        ('Credentials', 'gs_service_key_file_password', None),
        # Add hmac credentials.
        ('Credentials', 'gs_access_key_id', 'dummykey'),
        ('Credentials', 'gs_secret_access_key', 'dummysecret'),
    ]
    with SetBotoConfigForTest(boto_config_hmac_auth_only):
      bucket_uri = 'gs://any-bucket-name'
      stderr = self.RunGsUtil(['rpo', 'get', bucket_uri],
                              return_stderr=True,
                              expected_status=1)
      self.assertIn('command can only be with the Cloud Storage JSON API',
                    stderr)

  @SkipForGS('Testing S3 only behavior')
  def test_s3_fails_for_set(self):
    bucket_uri = self.CreateBucket()
    stderr = self.RunGsUtil(['rpo', 'set', 'default', bucket_uri],
                            return_stderr=True,
                            expected_status=1)
    self.assertIn('command can only be used for GCS Buckets', stderr)

  @SkipForGS('Testing S3 only behavior')
  def test_s3_fails_for_get(self):
    bucket_uri = self.CreateBucket()
    stderr = self.RunGsUtil(['rpo', 'get', bucket_uri],
                            return_stderr=True,
                            expected_status=1)
    self.assertIn('command can only be used for GCS Buckets', stderr)
