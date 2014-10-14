# -*- coding: utf-8 -*-
# Copyright 2014 Google Inc.  All Rights Reserved.
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
"""Integration tests for tab completion."""

from __future__ import absolute_import

import os
from unittest.case import skipUnless

from gslib.command import CreateGsutilLogger
import gslib.tests.testcase as testcase
from gslib.tests.util import ARGCOMPLETE_AVAILABLE


@skipUnless(ARGCOMPLETE_AVAILABLE, 'Tab completion requires argcomplete')
class TestTabComplete(testcase.GsUtilIntegrationTestCase):
  """Integration tests for tab completion."""

  def setUp(self):
    super(TestTabComplete, self).setUp()
    self.logger = CreateGsutilLogger('tab_complete')

  def test_single_bucket(self):
    """Tests tab completion matching a single bucket."""

    bucket_base_name = self.MakeTempName('bucket')
    bucket_name = bucket_base_name + '-suffix'
    self.CreateBucket(bucket_name)

    request = '%s://%s' % (self.default_provider, bucket_base_name)
    expected_result = '//%s/' % bucket_name

    self.RunGsUtilTabCompletion(['ls', request],
                                expected_results=[expected_result])

  def test_single_subdirectory(self):
    """Tests tab completion matching a single subdirectory."""

    object_base_name = self.MakeTempName('obj')
    object_name = object_base_name + '/subobj'
    object_uri = self.CreateObject(object_name=object_name, contents='data')

    request = '%s://%s/' % (self.default_provider, object_uri.bucket_name)
    expected_result = '//%s/%s/' % (object_uri.bucket_name, object_base_name)

    self.RunGsUtilTabCompletion(['ls', request],
                                expected_results=[expected_result])

  def test_multiple_buckets(self):
    """Tests tab completion matching multiple buckets."""

    bucket_base_name = self.MakeTempName('bucket')
    bucket1_name = bucket_base_name + '-suffix1'
    self.CreateBucket(bucket1_name)
    bucket2_name = bucket_base_name + '-suffix2'
    self.CreateBucket(bucket2_name)

    request = '%s://%s' % (self.default_provider, bucket_base_name)
    expected_result1 = '//%s/' % bucket1_name
    expected_result2 = '//%s/' % bucket2_name

    self.RunGsUtilTabCompletion(['ls', request], expected_results=[
        expected_result1, expected_result2])

  def test_single_object(self):
    """Tests tab completion matching a single object."""

    object_base_name = self.MakeTempName('obj')
    object_name = object_base_name + '-suffix'
    object_uri = self.CreateObject(object_name=object_name, contents='data')

    request = '%s://%s/%s' % (
        self.default_provider, object_uri.bucket_name, object_base_name)
    expected_result = '//%s/%s ' % (object_uri.bucket_name, object_name)

    self.RunGsUtilTabCompletion(['ls', request],
                                expected_results=[expected_result])

  def test_multiple_objects(self):
    """Tests tab completion matching multiple objects."""

    bucket_uri = self.CreateBucket()

    object_base_name = self.MakeTempName('obj')
    object1_name = object_base_name + '-suffix1'
    self.CreateObject(
        bucket_uri=bucket_uri, object_name=object1_name, contents='data')
    object2_name = object_base_name + '-suffix2'
    self.CreateObject(
        bucket_uri=bucket_uri, object_name=object2_name, contents='data')

    request = '%s://%s/%s' % (
        self.default_provider, bucket_uri.bucket_name, object_base_name)
    expected_result1 = '//%s/%s' % (bucket_uri.bucket_name, object1_name)
    expected_result2 = '//%s/%s' % (bucket_uri.bucket_name, object2_name)

    self.RunGsUtilTabCompletion(['ls', request], expected_results=[
        expected_result1, expected_result2])

  def test_subcommands(self):
    """Tests tab completion for commands with subcommands."""

    bucket_base_name = self.MakeTempName('bucket')
    bucket_name = bucket_base_name + '-suffix'
    self.CreateBucket(bucket_name)

    bucket_request = '%s://%s' % (self.default_provider, bucket_base_name)
    expected_bucket_result = '//%s/' % bucket_name

    local_file = 'a_local_file'
    local_dir = self.CreateTempDir(test_files=[local_file])

    local_file_request = '%s%s' % (local_dir, os.sep)
    expected_local_file_result = '%s ' % os.path.join(local_dir, local_file)

    # Should invoke Cloud URL completer.
    self.RunGsUtilTabCompletion(['cors', 'get', bucket_request],
                                expected_results=[expected_bucket_result])

    # Should invoke File URL completer which should match the local file.
    self.RunGsUtilTabCompletion(['cors', 'set', local_file_request],
                                expected_results=[expected_local_file_result])

    # Should invoke Cloud URL completer.
    self.RunGsUtilTabCompletion(['cors', 'set', 'some_file', bucket_request],
                                expected_results=[expected_bucket_result])
