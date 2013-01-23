# Copyright 2013 Google Inc.
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

"""Contains gsutil base integration test case class."""

import random

import boto

import gslib.tests.util as util
from gslib.tests.util import unittest


@unittest.skipUnless(util.RUN_INTEGRATION_TESTS,
                     'Not running integration tests.')
class GsUtilIntegrationTestCase(unittest.TestCase):
  """Base class for gsutil integration tests."""

  def setUp(self):
    self.conn = boto.connect_gs()
    self.buckets = []

  def tearDown(self):
    for bucket in self.buckets:
      while list(bucket.list_versions()):
        for k in bucket.list_versions():
          bucket.delete_key(k.name, generation=k.generation)
      bucket.delete()

  def CreateBucket(self, bucket_name=None):
    bucket_name = bucket_name or ('gsutil-test-bucket-%s-%08x' %
                                  (self._testMethodName,
                                   random.randrange(256**4)))
    bucket = self.conn.create_bucket(bucket_name.lower())
    self.buckets.append(bucket)
    return bucket

  def CreateObject(self, bucket, object_name=None, contents=None):
    object_name = object_name or ('gsutil-test-obj-%s-%08x' %
                                  (self._testMethodName,
                                   random.randrange(256**4)))
    key = bucket.new_key(object_name)
    if contents is not None:
      key.set_contents_from_string(contents)
    return key
