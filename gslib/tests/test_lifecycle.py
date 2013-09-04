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

import posixpath
from xml.dom.minidom import parseString

from gslib.util import Retry
import gslib.tests.testcase as testcase
from gslib.tests.util import ObjectToURI as suri


class TestSetLifecycle(testcase.GsUtilIntegrationTestCase):
  """Integration tests for lifecycle command."""

  empty_doc1 = parseString(
      '<LifecycleConfiguration/>').toprettyxml(indent='    ')

  empty_doc2 = parseString(
      '<LifecycleConfiguration>'
      '</LifecycleConfiguration>').toprettyxml(indent='    ')

  bad_doc1 = ('<?xml version="1.0" ?><LifecycleConfiguration><Rule>'
              '<Action><Delete/></Action></Rule></LifecycleConfiguration>')

  bad_doc2 = ('<?xml version="1.0" ?><LifecycleConfiguration><Rule>'
              '<Condition><Age>365</Age></Condition></Rule>'
              '</LifecycleConfiguration>')

  bad_doc3 = ('<?xml version="1.0" ?><LifecycleConfiguration><Rule>'
              '<Delete/><Condition><Age>365</Age></Condition></Rule>'
              '</LifecycleConfiguration>')

  bad_doc4 = ('<?xml version="1.0" ?><LifecycleConfiguration><Rule>'
              '<Action><Delete/></Action><Age>365</Age></Rule>'
              '</LifecycleConfiguration>')

  valid_doc = parseString(
      '<LifecycleConfiguration><Rule>'
      '<Action><Delete/></Action>'
      '<Condition><Age>365</Age></Condition>'
      '</Rule></LifecycleConfiguration>').toprettyxml(indent='    ')

  def test_default_lifecycle(self):
    bucket_uri = self.CreateBucket()
    stdout = self.RunGsUtil(['lifecycle', 'get', suri(bucket_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.empty_doc1)

  def test_set_empty_lifecycle1(self):
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents=self.empty_doc1)
    self.RunGsUtil(['lifecycle', 'set', fpath, suri(bucket_uri)])
    stdout = self.RunGsUtil(['lifecycle', 'get', suri(bucket_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.empty_doc1)

  def test_set_empty_lifecycle2(self):
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents=self.empty_doc2)
    self.RunGsUtil(['lifecycle', 'set', fpath, suri(bucket_uri)])
    stdout = self.RunGsUtil(['lifecycle', 'get', suri(bucket_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.empty_doc1)

  def test_valid_lifecycle(self):
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents=self.valid_doc)
    self.RunGsUtil(['lifecycle', 'set', fpath, suri(bucket_uri)])
    stdout = self.RunGsUtil(['lifecycle', 'get', suri(bucket_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.valid_doc)

  def test_bad_lifecycle1(self):
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents=self.bad_doc1)
    self.RunGsUtil(['lifecycle', 'set', fpath, suri(bucket_uri)],
                   expected_status=1)

  def test_bad_lifecycle2(self):
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents=self.bad_doc2)
    self.RunGsUtil(['lifecycle', 'set', fpath, suri(bucket_uri)],
                   expected_status=1)

  def test_bad_lifecycle3(self):
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents=self.bad_doc3)
    self.RunGsUtil(['lifecycle', 'set', fpath, suri(bucket_uri)],
                   expected_status=1)

  def test_bad_lifecycle4(self):
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents=self.bad_doc4)
    self.RunGsUtil(['lifecycle', 'set', fpath, suri(bucket_uri)],
                   expected_status=1)

  def test_set_lifecycle_and_reset(self):
    bucket_uri = self.CreateBucket()
    tmpdir = self.CreateTempDir()
    fpath = self.CreateTempFile(tmpdir=tmpdir, contents=self.valid_doc)
    self.RunGsUtil(['lifecycle', 'set', fpath, suri(bucket_uri)])
    stdout = self.RunGsUtil(['lifecycle', 'get', suri(bucket_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.valid_doc)

    fpath = self.CreateTempFile(tmpdir=tmpdir, contents=self.empty_doc1)
    self.RunGsUtil(['lifecycle', 'set', fpath, suri(bucket_uri)])
    stdout = self.RunGsUtil(['lifecycle', 'get', suri(bucket_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.empty_doc1)

  def test_set_lifecycle_multi_buckets(self):
    bucket1_uri = self.CreateBucket()
    bucket2_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents=self.valid_doc)
    self.RunGsUtil(
        ['lifecycle', 'set', fpath, suri(bucket1_uri), suri(bucket2_uri)])
    stdout = self.RunGsUtil(['lifecycle', 'get', suri(bucket1_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.valid_doc)
    stdout = self.RunGsUtil(['lifecycle', 'get', suri(bucket2_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.valid_doc)

  def test_set_lifecycle_wildcard(self):
    random_prefix = self.MakeRandomTestString()
    bucket1_name = self.MakeTempName('bucket', prefix=random_prefix)
    bucket2_name = self.MakeTempName('bucket', prefix=random_prefix)
    bucket1_uri = self.CreateBucket(bucket_name=bucket1_name)
    bucket2_uri = self.CreateBucket(bucket_name=bucket2_name)
    # This just double checks that the common prefix of the two buckets is what
    # we think it should be (based on implementation detail of CreateBucket).
    # We want to be careful when setting a wildcard on buckets to make sure we
    # don't step outside the test buckets to affect other buckets.
    common_prefix = posixpath.commonprefix([suri(bucket1_uri),
                                            suri(bucket2_uri)])
    self.assertTrue(common_prefix.startswith(
        'gs://%sgsutil-test-test_set_lifecycle_wildcard-' % random_prefix))
    wildcard = '%s*' % common_prefix

    fpath = self.CreateTempFile(contents=self.valid_doc)

    # Use @Retry as hedge against bucket listing eventual consistency.
    expected = set([
        'Setting lifecycle configuration on %s/...' % suri(bucket1_uri),
        'Setting lifecycle configuration on %s/...' % suri(bucket2_uri)])
    actual = set()
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stderr = self.RunGsUtil(['lifecycle', 'set', fpath, wildcard],
                              return_stderr=True)
      actual.update(stderr.splitlines())
      self.assertEqual(expected, actual)
      self.assertEqual(stderr.count('Setting lifecycle configuration'), 2)
    _Check1()

    stdout = self.RunGsUtil(['lifecycle', 'get', suri(bucket1_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.valid_doc)
    stdout = self.RunGsUtil(['lifecycle', 'get', suri(bucket2_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.valid_doc)
