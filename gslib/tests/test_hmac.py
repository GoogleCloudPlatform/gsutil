# -*- coding: utf-8 -*-
# Copyright 2019 Google Inc. All Rights Reserved.
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
"""Integration tests for the hmac command."""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import gslib.tests.testcase as testcase
from gslib.tests.testcase.integration_testcase import SkipForS3
from gslib.tests.testcase.integration_testcase import SkipForXML


@SkipForS3('S3 does not have an equivalent API')
@SkipForXML('XML HMAC control is not supported.')
class TestHmacIntegration(testcase.GsUtilIntegrationTestCase):
  """Hmac integration test cases."""

  def test_malformed_commands(self):
    params = [
        ('hmac create', 'requires a service account'),
        ('hmac create -u email', 'requires a service account'),
        ('hmac create -p proj', 'requires a service account'),
        ('hmac delete', 'requires an Access ID'),
        ('hmac delete -p proj', 'requires an Access ID'),
        ('hmac get', 'requires an Access ID'),
        ('hmac get -p proj', 'requires an Access ID'),
        ('hmac list account1', 'unexpected arguments'),
        ('hmac update keyname', 'state flag must be supplied'),
        ('hmac update -s KENTUCKY', 'state flag value must be one of'),
        ('hmac update -s INACTIVE', 'requires an Access ID'),
        ('hmac update -s INACTIVE -p proj', 'requires an Access ID'),
        ]
    for command, error_substr in params:
      stderr = self.RunGsUtil(
          command.split(), return_stderr=True, expected_status=1)
      self.assertIn(error_substr, stderr)

  # TODO(tuckerkirven) temporary to show plumbing works. remove.
  def test_valid_commands(self):
    params = [
        'hmac create sa@sa.iam.com',
        'hmac create -p sa sa@sa.iam.com',
        'hmac delete GOOG123',
        'hmac delete -p proj GOOG123',
        'hmac get GOOG123',
        'hmac get -p proj GOOG123',
        'hmac list',
        'hmac list -p proj',
        'hmac list -p proj -u sa@sa.iam.com',
        'hmac list -u sa@sa.iam.com',
        'hmac update -s INACTIVE GOOG123',
        'hmac update -s INACTIVE -p proj GOOG123',
        ]
    for command in params:
      stderr = self.RunGsUtil(
          command.split(), return_stderr=True, expected_status=1)
      self.assertIn('NotImplementedError: Unimplemented', stderr)
