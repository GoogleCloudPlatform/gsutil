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


class TestCors(testcase.GsUtilIntegrationTestCase):
  """Integration tests for cors command."""
  
  _set_cmd_prefix = ['cors', 'set']
  _get_cmd_prefix = ['cors', 'get']

  empty_doc1 = parseString('<CorsConfig/>').toprettyxml(indent='    ')

  empty_doc2 = parseString(
      '<CorsConfig></CorsConfig>').toprettyxml(indent='    ')

  empty_doc3 = parseString(
      '<CorsConfig><Cors/></CorsConfig>').toprettyxml(indent='    ')

  empty_doc4 = parseString(
      '<CorsConfig><Cors></Cors></CorsConfig>').toprettyxml(indent='    ')

  cors_bad1 = ('<?xml version="1.0" ?><CorsConfig><Cors><Methods><Method>GET'
               '</ResponseHeader></Methods></Cors></CorsConfig>')

  cors_bad2 = ('<?xml version="1.0" ?><CorsConfig><Cors><Methods><Cors>GET'
               '</Cors></Methods></Cors></CorsConfig>')

  cors_bad3 = ('<?xml version="1.0" ?><CorsConfig><Methods><Method>GET'
               '</Method></Methods></Cors></CorsConfig>')

  cors_bad4 = ('<?xml version="1.0" ?><CorsConfig><Cors><Method>GET'
               '</Method></Cors></CorsConfig>')

  cors_doc = parseString(
      '<CorsConfig><Cors><Origins>'
      '<Origin>http://origin1.example.com</Origin>'
      '<Origin>http://origin2.example.com</Origin>'
      '</Origins><Methods><Method>GET</Method>'
      '<Method>PUT</Method><Method>POST</Method></Methods>'
      '<ResponseHeaders><ResponseHeader>foo</ResponseHeader>'
      '<ResponseHeader>bar</ResponseHeader></ResponseHeaders>'
      '<MaxAgeSec>3600</MaxAgeSec></Cors>'
      '<Cors><Origins><Origin>http://origin3.example.com</Origin></Origins>'
      '<Methods><Method>GET</Method><Method>DELETE</Method></Methods>'
      '<ResponseHeaders><ResponseHeader>foo2</ResponseHeader>'
      '<ResponseHeader>bar2</ResponseHeader></ResponseHeaders>'
      '</Cors></CorsConfig>').toprettyxml(indent='    ')

  def test_default_cors(self):
    bucket_uri = self.CreateBucket()
    stdout = self.RunGsUtil(self._get_cmd_prefix + [suri(bucket_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.empty_doc1)

  def test_set_empty_cors1(self):
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents=self.empty_doc1)
    self.RunGsUtil(self._set_cmd_prefix + [fpath, suri(bucket_uri)])
    stdout = self.RunGsUtil(self._get_cmd_prefix + [suri(bucket_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.empty_doc1)

  def test_set_empty_cors2(self):
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents=self.empty_doc2)
    self.RunGsUtil(self._set_cmd_prefix + [fpath, suri(bucket_uri)])
    stdout = self.RunGsUtil(self._get_cmd_prefix + [suri(bucket_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.empty_doc1)

  def test_set_empty_cors3(self):
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents=self.empty_doc3)
    self.RunGsUtil(self._set_cmd_prefix + [fpath, suri(bucket_uri)])
    stdout = self.RunGsUtil(self._get_cmd_prefix + [suri(bucket_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.empty_doc3)

  def test_set_empty_cors4(self):
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents=self.empty_doc4)
    self.RunGsUtil(self._set_cmd_prefix + [fpath, suri(bucket_uri)])
    stdout = self.RunGsUtil(self._get_cmd_prefix + [suri(bucket_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.empty_doc3)

  def test_non_null_cors(self):
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents=self.cors_doc)
    self.RunGsUtil(self._set_cmd_prefix + [fpath, suri(bucket_uri)])
    stdout = self.RunGsUtil(self._get_cmd_prefix + [suri(bucket_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.cors_doc)

  def test_bad_cors1(self):
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents=self.cors_bad1)
    self.RunGsUtil(self._set_cmd_prefix + [fpath, suri(bucket_uri)],
                   expected_status=1)

  def test_bad_cors2(self):
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents=self.cors_bad2)
    self.RunGsUtil(self._set_cmd_prefix + [fpath, suri(bucket_uri)],
                   expected_status=1)

  def test_bad_cors3(self):
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents=self.cors_bad3)
    self.RunGsUtil(self._set_cmd_prefix + [fpath, suri(bucket_uri)],
                   expected_status=1)

  def test_bad_cors4(self):
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents=self.cors_bad4)
    self.RunGsUtil(self._set_cmd_prefix + [fpath, suri(bucket_uri)],
                   expected_status=1)

  def set_cors_and_reset(self):
    bucket_uri = self.CreateBucket()
    tmpdir = self.CreateTempDir()
    fpath = self.CreateTempFile(tmpdir=tmpdir, contents=self.cors_doc)
    self.RunGsUtil(self._set_cmd_prefix + [fpath, suri(bucket_uri)])
    stdout = self.RunGsUtil(self._get_cmd_prefix + [suri(bucket_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.cors_doc)

    fpath = self.CreateTempFile(tmpdir=tmpdir, contents=self.empty_doc1)
    self.RunGsUtil(self._set_cmd_prefix + [fpath, suri(bucket_uri)])
    stdout = self.RunGsUtil(self._get_cmd_prefix + [suri(bucket_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.empty_doc1)

  def set_multi_non_null_cors(self):
    bucket1_uri = self.CreateBucket()
    bucket2_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents=self.cors_doc)
    self.RunGsUtil(
        self._set_cmd_prefix + [fpath, suri(bucket1_uri), suri(bucket2_uri)])
    stdout = self.RunGsUtil(self._get_cmd_prefix + [suri(bucket1_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.cors_doc)
    stdout = self.RunGsUtil(self._get_cmd_prefix + [suri(bucket2_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.cors_doc)

  def test_set_wildcard_non_null_cors(self):
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
        'gs://%sgsutil-test-test_set_wildcard_non_null_cors-' % random_prefix))
    wildcard = '%s*' % common_prefix

    fpath = self.CreateTempFile(contents=self.cors_doc)

    # Use @Retry as hedge against bucket listing eventual consistency.
    expected = set(['Setting CORS on %s/...' % suri(bucket1_uri),
                    'Setting CORS on %s/...' % suri(bucket2_uri)])
    actual = set()
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stderr = self.RunGsUtil(self._set_cmd_prefix + [fpath, wildcard],
                              return_stderr=True)
      outlines = stderr.splitlines()
      for line in outlines:
        # Ignore the deprecation warnings from running the old cors command.
        if ('You are using a deprecated alias' in line or
            'gsutil help cors' in line or
            'Please use "cors" with the appropriate sub-command' in line):
          continue
        actual.add(line)
      self.assertEqual(expected, actual)
      self.assertEqual(stderr.count('Setting CORS'), 2)
    _Check1()

    stdout = self.RunGsUtil(self._get_cmd_prefix + [suri(bucket1_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.cors_doc)
    stdout = self.RunGsUtil(self._get_cmd_prefix + [suri(bucket2_uri)],
                            return_stdout=True)
    self.assertEqual(stdout, self.cors_doc)

class TestCorsOldAlias(TestCors):
  _set_cmd_prefix = ['setcors']
  _get_cmd_prefix = ['getcors']
