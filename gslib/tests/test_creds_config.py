# -*- coding: utf-8 -*-
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
"""Tests for various combinations of configured credentials."""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

import boto

from apitools.base.py import exceptions as apitools_exceptions
from gslib.cred_types import CredTypes
from gslib.discard_messages_queue import DiscardMessagesQueue
from gslib.exception import CommandException
from gslib.gcs_json_api import GcsJsonApi
from gslib.tests.mock_logging_handler import MockLoggingHandler
import gslib.tests.testcase as testcase
from gslib.tests.testcase.integration_testcase import SkipForS3
from gslib.tests.testcase.integration_testcase import SkipForXML
from gslib.tests.util import ObjectToURI as suri
from gslib.tests.util import SetBotoConfigForTest
from gslib.tests.util import SetEnvironmentForTest
from gslib.tests.util import unittest

from six import add_move, MovedModule
add_move(MovedModule('mock', 'mock', 'unittest.mock'))
from six.moves import mock


def _LoadServiceAccount(account_field):
  return boto.config.get_value('GSUtil', account_field)


SERVICE_ACCOUNT = _LoadServiceAccount('test_impersonate_service_account')
FAILURE_ACCOUNT = _LoadServiceAccount('test_impersonate_failure_account')


class TestCredsConfig(testcase.GsUtilUnitTestCase):
  """Tests for various combinations of configured credentials."""

  def setUp(self):
    super(TestCredsConfig, self).setUp()
    self.log_handler = MockLoggingHandler()
    self.logger.addHandler(self.log_handler)

  def testMultipleConfiguredCreds(self):
    with SetBotoConfigForTest([
        ('Credentials', 'gs_oauth2_refresh_token', 'foo'),
        ('Credentials', 'gs_service_client_id', 'bar'),
        ('Credentials', 'gs_service_key_file', 'baz'),
        ('Credentials', 'gs_impersonate_service_account', None)
    ]):

      try:
        GcsJsonApi(None, self.logger, DiscardMessagesQueue())
        self.fail('Succeeded with multiple types of configured creds.')
      except CommandException as e:
        msg = str(e)
        self.assertIn('types of configured credentials', msg)
        self.assertIn(CredTypes.OAUTH2_USER_ACCOUNT, msg)
        self.assertIn(CredTypes.OAUTH2_SERVICE_ACCOUNT, msg)

  @mock.patch('gslib.iamcredentials_api.IamcredentailsApi.GenerateAccessToken')
  def testImpersonationBlockedByIamCredentialsApiErrors(
      self, mock_iam_creds_generate_access_token):
    with SetBotoConfigForTest([
        ('Credentials', 'gs_oauth2_refresh_token', 'foo'),
        ('Credentials', 'gs_service_client_id', None),
        ('Credentials', 'gs_service_key_file', None),
        ('Credentials', 'gs_impersonate_service_account', 'bar')
    ]):
      mock_iam_creds_generate_access_token.side_effect = (
          apitools_exceptions.HttpError({'status': 403}, {
              'code': 403,
              'message': 'IAM Service Account Credentials API has not been used'
          }, None))
      try:
        GcsJsonApi(None, self.logger, DiscardMessagesQueue())
        self.fail('Succeeded with multiple types of configured creds.')
      except apitools_exceptions.HttpError as e:
        msg = str(e)
        self.assertIn('IAM Service Account Credentials API has not been used',
            msg)


class TestCredsConfigIntegration(testcase.GsUtilIntegrationTestCase):

  @SkipForS3('Tests only uses gs credentials.')
  def testExactlyOneInvalid(self):
    bucket_uri = self.CreateBucket()
    with SetBotoConfigForTest(
        [('Credentials', 'gs_oauth2_refresh_token', 'foo'),
         ('Credentials', 'gs_service_client_id', None),
         ('Credentials', 'gs_service_key_file', None),
         ('Credentials', 'gs_impersonate_service_account', None)],
        use_existing_config=False):
      stderr = self.RunGsUtil(['ls', suri(bucket_uri)],
                              expected_status=1,
                              return_stderr=True)
      self.assertIn('credentials are invalid', stderr)

  @unittest.skipUnless(SERVICE_ACCOUNT,
                       'Test requires service account configuration.')
  @SkipForS3('Tests only uses gs credentials.')
  @SkipForXML('Tests only run on JSON API.')
  def testImpersonationCredentialsFromBotoConfig(self):
    with SetBotoConfigForTest([('Credentials', 'gs_impersonate_service_account',
                                SERVICE_ACCOUNT)]):
      with SetEnvironmentForTest({}):
        stderr = self.RunGsUtil(['ls', 'gs://pub'], return_stderr=True)
        self.assertIn('using service account impersonation', stderr)

  @unittest.skipUnless(SERVICE_ACCOUNT,
                       'Test requires service account configuration.')
  @SkipForS3('Tests only uses gs credentials.')
  @SkipForXML('Tests only run on JSON API.')
  def testImpersonationCredentialsFromGCloud(self):
    with SetBotoConfigForTest([('Credentials', 'gs_impersonate_service_account',
                                None)]):
      with SetEnvironmentForTest(
          {'CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT': SERVICE_ACCOUNT}):
        stderr = self.RunGsUtil(['ls', 'gs://pub'], return_stderr=True)
        self.assertIn('using service account impersonation', stderr)

  @unittest.skipUnless(SERVICE_ACCOUNT,
                       'Test requires service account configuration.')
  @SkipForS3('Tests only uses gs credentials.')
  @SkipForXML('Tests only run on JSON API.')
  def testImpersonationSuccess(self):
    with SetBotoConfigForTest([('Credentials', 'gs_impersonate_service_account',
                                SERVICE_ACCOUNT)]):
      stdout = self.RunGsUtil(['ls', 'gs://pub'], return_stderr=True)
      self.assertIn('API calls will be executed as [%s' % SERVICE_ACCOUNT,
                    stdout)

  @unittest.skipUnless(FAILURE_ACCOUNT,
                       'Test requires service account configuration.')
  @SkipForS3('Tests only uses gs credentials.')
  @SkipForXML('Tests only run on JSON API.')
  def testImpersonationFailure(self):
    with SetBotoConfigForTest([('Credentials', 'gs_impersonate_service_account',
                                FAILURE_ACCOUNT)]):
      stdout = self.RunGsUtil(['ls', 'gs://pub'],
                              expected_status=1,
                              return_stderr=True)
      self.assertIn('Service account impersonation failed.', stdout)
