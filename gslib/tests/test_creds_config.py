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

import logging

from gslib.cred_types import CredTypes
from gslib.exception import CommandException
from gslib.gcs_json_api import GcsJsonApi
import gslib.tests.testcase as testcase
from gslib.tests.util import SetBotoConfigForTest


class MockLoggingHandler(logging.Handler):
  """Mock logging handler to check for expected logs."""

  def __init__(self, *args, **kwargs):
    self.reset()
    logging.Handler.__init__(self, *args, **kwargs)

  def emit(self, record):
    self.messages[record.levelname.lower()].append(record.getMessage())

  def reset(self):
    self.messages = {
        'debug': [],
        'info': [],
        'warning': [],
        'error': [],
        'critical': [],
    }


class TestCredsConfig(testcase.GsUtilUnitTestCase):
  """Tests for various combinations of configured credentials."""

  def setUp(self):
    super(TestCredsConfig, self).setUp()
    self.log_handler = MockLoggingHandler()
    self.logger.addHandler(self.log_handler)

  def testMultipleConfiguredCreds(self):
    with SetBotoConfigForTest([
        ('Credentials', 'gs_oauth2_refresh_token', 'foo'),
        ('GoogleCompute', 'service_account', 'foo')]):

      try:
        GcsJsonApi(None, self.logger)
        self.fail('Succeeded with multiple types of configured creds.')
      except CommandException, e:
        msg = str(e)
        self.assertIn('types of configured credentials', msg)
        self.assertIn(CredTypes.OAUTH2_USER_ACCOUNT, msg)
        self.assertIn(CredTypes.GCE, msg)

  def testExactlyOneInvalid(self):
    with SetBotoConfigForTest([
        ('Credentials', 'gs_oauth2_refresh_token', 'foo')]):
      succeeded = False
      try:
        GcsJsonApi(None, self.logger)
        succeeded = True  # If we self.fail() here, the except below will catch
      except:  # pylint: disable=bare-except
        warning_messages = self.log_handler.messages['warning']
        self.assertEquals(1, len(warning_messages))
        self.assertIn('credentials are invalid', warning_messages[0])
        self.assertIn(CredTypes.OAUTH2_USER_ACCOUNT, warning_messages[0])
      if succeeded:
        self.fail('Succeeded with invalid credentials, one configured.')
