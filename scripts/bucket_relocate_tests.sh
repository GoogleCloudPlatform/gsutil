#!/usr/bin/python
# Copyright 2013 Google Inc. All Rights Reserved.
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

import random
import string
import subprocess
import tempfile
import time
import unittest

class BucketRelocateTests(unittest.TestCase):

  def setUp(self):
    self.buckets = []
    print '\n\n\n'
    print 'creating test buckets'
    self.buckets.append('gs://relocate_test_%s' % (
        ''.join(random.choice(string.ascii_lowercase) for x in range(10))))
    self.buckets.append('gs://relocate_test_%s' % (
        ''.join(random.choice(string.ascii_lowercase) for x in range(10))))
    self._GSUtil('mb %s' % self.buckets[0])
    self._GSUtil('mb %s' % self.buckets[1])
    self._GSUtil('-m cp -R gs://relotestdata/* %s' % self.buckets[0])

  def tearDown(self):
    print 'deleting test buckets'
    for bucket in self.buckets:
      if self._GSUtil('ls -a %s' % bucket, raiseError=False):
        self._GSUtil('-m rm -Ra %s/*' % bucket)
      self._GSUtil('rb %s' % bucket)

  def _GSUtil(self, paramstr, raiseError=True):
    cmd = 'gsutil %s' % paramstr
    print cmd
    p = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT,
                         close_fds=True)
    code = p.wait()
    output = p.stdout.read()
    if code:
      if raiseError:
        raise Exception('gsutil return code=%d stdout=%s' % (code, output))
      else:
        return None
    return output

  def _Relocate(self, stage=None, storage_class=None, location=None,
      buckets=None):
    params = ['./bucket_relocate.sh']
    if stage:
      params.append(stage)
    if storage_class:
      params.append(storage_class)
    if location:
      params.append(location)
    if buckets:
      params.extend(buckets)
    code = subprocess.call(params)
    if code:
      raise Exception('Return code=%d' % code)

  def _DeleteBucketWithRetry(self, bucket):
    self._GSUtil('-m rm -Ra %s/*' % bucket)
    count = 0
    while count < 5:
      count += 1
      try:
        self._GSUtil('rb %s' % bucket)
        return
      except Exception as ex:
        if count == 5 or not 'BucketNotEmpty' in ex.message:
          raise
        time.sleep(5)

  def test_SimpleAll(self):
    bucket = self.buckets[0]
    self._Relocate(stage='-A', buckets=[bucket])

  def test_SimpleStage1(self):
    bucket = self.buckets[0]
    self._Relocate(stage='-1', buckets=[bucket])
    self._DeleteBucketWithRetry('%s-relocate' % bucket)

  def test_SimpleStage2(self):
    bucket = self.buckets[0]
    self._Relocate(stage='-1', buckets=[bucket])
    self._Relocate(stage='-2', buckets=[bucket])

  def test_RelocateToDRA(self):
    bucket = self.buckets[0]
    self._Relocate(stage='-A', storage_class='-c DRA', buckets=[bucket])

  def test_RelocateToEU(self):
    bucket = self.buckets[0]
    self._Relocate(stage='-A', location='-l EU', buckets=[bucket])

  def test_RelocateClassAndLocation(self):
    bucket = self.buckets[0]
    self._Relocate(stage='-A', location='-l EU', storage_class='-c DRA',
                     buckets=[bucket])

  def test_ConfigDefacl(self):
    bucket = self.buckets[0]
    self._GSUtil('defacl set public-read %s' % bucket)
    cfg_before = self._GSUtil('defacl get %s' % bucket)
    self._Relocate(stage='-A', buckets=[bucket])
    cfg_after = self._GSUtil('defacl get %s' % bucket)
    self.assertEqual(cfg_before, cfg_after)

  def test_ConfigWebcfg(self):
    bucket = self.buckets[0]
    self._GSUtil('web set -m main.html -e error.html %s' % bucket)
    cfg_before = self._GSUtil('web get %s' % bucket)
    self._Relocate(stage='-A', buckets=[bucket])
    cfg_after = self._GSUtil('web get %s' % bucket)
    self.assertEqual(cfg_before, cfg_after)

  def test_ConfigLogging(self):
    bucket = self.buckets[0]
    log_bucket = self.buckets[1]
    self._GSUtil('logging set on -b %s -o tstlog %s' % (log_bucket, bucket))
    cfg_before = self._GSUtil('logging get %s' % bucket)
    self._Relocate(stage='-A', buckets=[bucket])
    cfg_after = self._GSUtil('logging get %s' % bucket)
    self.assertEqual(cfg_before, cfg_after)

  def test_ConfigCors(self):
    bucket = self.buckets[0]
    cors="""<?xml version="1.0" ?>
<CorsConfig><Cors><Origins><Origin>http://origin1.example.com</Origin>
</Origins><Methods><Method>GET</Method></Methods><ResponseHeaders>
<ResponseHeader>Content-Type</ResponseHeader></ResponseHeaders>
</Cors></CorsConfig>"""
    f = tempfile.NamedTemporaryFile()
    f.write(cors)
    f.flush()
    self._GSUtil('cors set %s %s' % (f.name, bucket))
    cfg_before = self._GSUtil('cors get %s' % bucket)
    self._Relocate(stage='-A', buckets=[bucket])
    cfg_after = self._GSUtil('cors get %s' % bucket)
    self.assertEqual(cfg_before, cfg_after)
    f.close()

  def test_ConfigVersioning(self):
    bucket = self.buckets[0]
    self._GSUtil('versioning set on %s' % bucket)
    cfg_before = self._GSUtil('versioning get %s' % bucket)
    self._Relocate(stage='-A', buckets=[bucket])
    cfg_after = self._GSUtil('versioning get %s' % bucket)
    self.assertEqual(cfg_before, cfg_after)

  def test_VersionedObjects(self):
    bucket = self.buckets[0]
    obj1 = '/tjp.dat'
    obj2 = '/yjux.dat'
    # enable versioning
    self._GSUtil('versioning set on %s' % bucket)
    # force another version
    self._GSUtil('cp %s%s %s%s' % (bucket, obj1, bucket, obj2))
    versions_before = self._GSUtil('ls -a %s%s' % (bucket, obj2))
    self._Relocate(stage='-A', buckets=[bucket])
    versions_after = self._GSUtil('ls -a %s%s' % (bucket, obj2))
    version_count = len(versions_before.splitlines())
    self.assertEqual(version_count, 2)
    self.assertEqual(version_count, len(versions_after.splitlines()))


if __name__ == "__main__":
  unittest.main()
