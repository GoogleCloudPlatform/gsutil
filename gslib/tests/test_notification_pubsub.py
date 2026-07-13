# -*- coding: utf-8 -*-
# Copyright 2017 Google Inc. All Rights Reserved.
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
"""Integration tests for notification command."""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

import logging
import unittest

from six import add_move, MovedModule
add_move(MovedModule('mock', 'mock', 'unittest.mock'))
from six.moves import mock

from gslib.commands import notification
from gslib.cs_api_map import ApiSelector
from gslib.project_id import PopulateProjectId
from gslib.pubsub_api import PubsubApi
import gslib.tests.testcase as testcase
from gslib.tests.testcase.integration_testcase import SkipForS3
from gslib.tests.util import ObjectToURI as suri
from gslib.tests.util import SetBotoConfigForTest
from gslib.tests.util import SetEnvironmentForTest
from gslib.utils import shim_util


@SkipForS3('gsutil doesn\'t support S3 notifications')
class TestNotificationPubSub(testcase.GsUtilIntegrationTestCase):
  """Integration tests for notification command (the Cloud Pub/Sub parts)."""

  def setUp(self):
    super(TestNotificationPubSub, self).setUp()
    self.pubsub_api = PubsubApi(logger=logging.getLogger())
    self.created_topic = None

  def tearDown(self):
    super(TestNotificationPubSub, self).tearDown()
    # Cleanup any created topics.
    if self.created_topic:
      self.pubsub_api.DeleteTopic(self.created_topic)
      self.created_topic = None

  def _RegisterDefaultTopicCreation(self, bucket_name):
    """Records the name of a topic we expect to create, for cleanup."""
    if self.test_api == ApiSelector.XML:
      return unittest.skip('Notifications only work with the JSON API.')

    expected_topic_name = 'projects/%s/topics/%s' % (PopulateProjectId(None),
                                                     bucket_name)
    self.created_topic = expected_topic_name
    return expected_topic_name

  def test_list_new_bucket(self):
    """Tests listing notification configs on a new bucket."""
    if self.test_api == ApiSelector.XML:
      return unittest.skip('Notifications only work with the JSON API.')

    bucket_uri = self.CreateBucket()
    stdout = self.RunGsUtil(
        ['notification', 'list', suri(bucket_uri)], return_stdout=True)
    self.assertFalse(stdout)

  def test_delete_with_no_notifications(self):
    """Tests deleting all notification configs when there are none."""
    if self.test_api == ApiSelector.XML:
      return unittest.skip('Notifications only work with the JSON API.')

    bucket_uri = self.CreateBucket()
    stdout = self.RunGsUtil(
        ['notification', 'delete', suri(bucket_uri)], return_stdout=True)
    self.assertFalse(stdout)

  def test_create_basic(self):
    """Tests the create command succeeds in normal circumstances."""
    if self.test_api == ApiSelector.XML:
      return unittest.skip('Notifications only work with the JSON API.')

    bucket_uri = self.CreateBucket()
    topic_name = self._RegisterDefaultTopicCreation(bucket_uri.bucket_name)

    stdout, stderr = self.RunGsUtil(
        ['notification', 'create', '-f', 'json',
         suri(bucket_uri)],
        return_stdout=True,
        return_stderr=True)

    if self._use_gcloud_storage:
      self.assertIn('kind: storage#notification', stdout)
      self.assertIn(topic_name, stdout)
    else:
      self.assertIn('Created notification', stderr)
      self.assertIn(topic_name, stderr)

  def test_list_one_entry(self):
    """Tests notification config listing with one entry."""
    if self.test_api == ApiSelector.XML:
      return unittest.skip('Notifications only work with the JSON API.')

    bucket_uri = self.CreateBucket()
    bucket_name = bucket_uri.bucket_name
    topic_name = self._RegisterDefaultTopicCreation(bucket_uri.bucket_name)

    self.RunGsUtil([
        'notification', 'create', '-f', 'json', '-e', 'OBJECT_FINALIZE', '-e',
        'OBJECT_DELETE', '-m', 'someKey:someValue', '-p', 'somePrefix',
        suri(bucket_uri)
    ],
                   return_stderr=True)
    stdout = self.RunGsUtil(
        ['notification', 'list', suri(bucket_uri)], return_stdout=True)

    if self._use_gcloud_storage:
      # gcloud and gsutil look the same in the terminal, but, for some reason,
      # the shim test script detects an extra newline.
      trailing_space = '\n'
    else:
      trailing_space = ''
    self.assertEqual(
        stdout,
        ('projects/_/buckets/{bucket_name}/notificationConfigs/1\n'
         '\tCloud Pub/Sub topic: {topic_name}\n'
         '\tCustom attributes:\n'
         '\t\tsomeKey: someValue\n'
         '\tFilters:\n'
         '\t\tEvent Types: OBJECT_FINALIZE, OBJECT_DELETE\n'
         '\t\tObject name prefix: \'somePrefix\'\n{trailing_space}'.format(
             bucket_name=bucket_name,
             topic_name=topic_name,
             trailing_space=trailing_space)))

  def test_delete(self):
    """Tests the create command succeeds in normal circumstances."""
    if self.test_api == ApiSelector.XML:
      return unittest.skip('Notifications only work with the JSON API.')

    bucket_uri = self.CreateBucket()
    self._RegisterDefaultTopicCreation(bucket_uri.bucket_name)
    self.RunGsUtil(['notification', 'create', '-f', 'json', suri(bucket_uri)])
    self.RunGsUtil(['notification', 'delete', suri(bucket_uri)])

  def test_create_object_fails(self):
    bucket_uri = self.CreateBucket()
    stderr = self.RunGsUtil(['notification', 'create', '-f', 'json', suri(bucket_uri, 'obj')],
                            expected_status=1,
                            return_stderr=True)
    self.assertIn('requires a GCS bucket name', stderr)

  def test_create_s3_bucket_fails(self):
    stderr = self.RunGsUtil(['notification', 'create', '-f', 'json', 's3://somebucket'],
                            expected_status=1,
                            return_stderr=True)
    self.assertIn('only be used with gs:// bucket URLs', stderr)

  def test_missing_arguments_fails(self):
    stderr = self.RunGsUtil(['notification'],
                            expected_status=1,
                            return_stderr=True)
    self.assertIn('command requires at least', stderr)

    stderr = self.RunGsUtil(['notification', 'create'],
                            expected_status=1,
                            return_stderr=True)
    self.assertIn('command requires at least', stderr)

  def test_list_object_fails(self):
    bucket_uri = self.CreateBucket()
    stderr = self.RunGsUtil(
        ['notification', 'list', suri(bucket_uri, 'obj')],
        expected_status=1,
        return_stderr=True)
    self.assertIn('cannot be used on cloud objects, only buckets', stderr)

  def test_delete_object_fails(self):
    bucket_uri = self.CreateBucket()
    stderr = self.RunGsUtil(
        ['notification', 'delete', suri(bucket_uri, 'obj')],
        expected_status=1,
        return_stderr=True)
    self.assertIn('cannot be used on cloud objects, only buckets', stderr)


class TestNotificationShim(testcase.ShimUnitTestBase):

  @mock.patch.object(notification.NotificationCommand, 'RunCommand', new=mock.Mock())
  def test_shim_translates_create(self):
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand('notification',
                                           ['create', '-f', 'json', '-t', 'mytopic', '-p', 'prefix', '-m', 'key:value', 'gs://bucket'],
                                           return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(('Gcloud Storage Command: {} storage buckets notifications create'
                       ' --payload-format json --topic mytopic --object-prefix prefix'
                       ' gs://bucket --custom-attributes=key=value').format(
                           shim_util._get_gcloud_binary_path('fake_dir')),
                      info_lines)

  @mock.patch.object(notification.NotificationCommand, 'RunCommand', new=mock.Mock())
  def test_shim_translates_list(self):
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand('notification', ['list', 'gs://bucket'],
                                           return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(('Gcloud Storage Command: {} storage buckets notifications list'
                       ' --human-readable gs://bucket').format(
                           shim_util._get_gcloud_binary_path('fake_dir')),
                      info_lines)

  @mock.patch.object(notification.NotificationCommand, 'RunCommand', new=mock.Mock())
  def test_shim_translates_delete(self):
    with SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                               ('GSUtil', 'hidden_shim_mode', 'dry_run')]):
      with SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        mock_log_handler = self.RunCommand('notification', ['delete', 'gs://bucket'],
                                           return_log_handler=True)
        info_lines = '\n'.join(mock_log_handler.messages['info'])
        self.assertIn(('Gcloud Storage Command: {} storage buckets notifications delete'
                       ' gs://bucket').format(
                           shim_util._get_gcloud_binary_path('fake_dir')),
                      info_lines)

