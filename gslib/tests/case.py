import random
import unittest

import boto


class GsUtilIntegrationTestCase(unittest.TestCase):

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
