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

import logging

from gslib.project_id import PopulateProjectId
from gslib.pubsub_api import PubsubApi
import gslib.tests.testcase as testcase
from gslib.tests.util import ObjectToURI as suri


class TestNotificationPubSub(testcase.GsUtilIntegrationTestCase):
  """Integration tests for notification command (the Cloud Pub/Sub parts)."""

  def __init__(self, arg):
    super(TestNotificationPubSub, self).__init__(arg)
    self.pubsub_api = PubsubApi(logger=logging.getLogger())

  def setUp(self):
    self.created_topic = None

  def tearDown(self):
    # Cleanup any created topics.
    if self.created_topic:
      self.pubsub_api.DeleteTopic(self.created_topic)
      self.created_topic = None

  def _RegisterDefaultTopicCreation(self, bucket_name):
    """Records the name of a topic we expect to create, for cleanup."""
    expected_topic_name = 'projects/%s/topics/%s' % (
        PopulateProjectId(None), bucket_name)
    self.created_topic = expected_topic_name
    return expected_topic_name

  def test_list_new_bucket(self):
    """Tests listing notification configs on a new bucket."""
    bucket_uri = self.CreateBucket()
    stdout = self.RunGsUtil([
        'notification', 'list', suri(bucket_uri)], return_stdout=True)
    self.assertFalse(stdout)

  def test_delete_with_no_notifications(self):
    """Tests deleting all notification configs when there are none."""
    bucket_uri = self.CreateBucket()
    stdout = self.RunGsUtil([
        'notification', 'delete', suri(bucket_uri)], return_stdout=True)
    self.assertFalse(stdout)

  def test_create_basic(self):
    """Tests the create command succeeds in normal circumstances."""
    bucket_uri = self.CreateBucket()
    topic_name = self._RegisterDefaultTopicCreation(bucket_uri.bucket_name)

    stderr = self.RunGsUtil(
        ['notification', 'create', '-f', 'json', suri(bucket_uri)],
        return_stderr=True)
    self.assertIn('Created notification', stderr)
    self.assertIn(topic_name, stderr)

  def test_list_one_entry(self):
    """Tests notification config listing with one entry."""
    bucket_uri = self.CreateBucket()
    bucket_name = bucket_uri.bucket_name
    topic_name = self._RegisterDefaultTopicCreation(bucket_uri.bucket_name)

    self.RunGsUtil(
        ['notification', 'create',
         '-f', 'json',
         '-e', 'OBJECT_FINALIZE',
         '-e', 'OBJECT_DELETE',
         '-m', 'someKey:someValue',
         '-p', 'somePrefix',
         suri(bucket_uri)],
        return_stderr=True)
    stdout = self.RunGsUtil(['notification', 'list', suri(bucket_uri)],
                            return_stdout=True)
    self.assertEquals(
        stdout,
        ('projects/_/buckets/{bucket_name}/notificationConfigs/1\n'
         '\tCloud Pub/Sub topic: {topic_name}\n'
         '\tCustom attributes:\n'
         '\t\tsomeKey: someValue\n'
         '\tFilters:\n'
         '\t\tEvent Types: OBJECT_FINALIZE, OBJECT_DELETE\n'
         '\t\tObject name prefix: \'somePrefix\'\n'.format(
             bucket_name=bucket_name, topic_name=topic_name)))

  def test_delete(self):
    """Tests the create command succeeds in normal circumstances."""
    bucket_uri = self.CreateBucket()
    self._RegisterDefaultTopicCreation(bucket_uri.bucket_name)
    self.RunGsUtil(['notification', 'create', '-f', 'json', suri(bucket_uri)])
    self.RunGsUtil(['notification', 'delete', suri(bucket_uri)])
