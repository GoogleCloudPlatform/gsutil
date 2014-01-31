# -*- coding: utf-8 -*-
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
"""Integration tests for setmeta command."""

import gslib.tests.testcase as testcase
from gslib.tests.util import ObjectToURI as suri
from gslib.util import Retry
from gslib.util import UTF8


class TestSetMeta(testcase.GsUtilIntegrationTestCase):
  """Integration tests for setmeta command."""

  def test_initial_metadata(self):
    """Tests copying file to an object with metadata."""
    objuri = suri(self.CreateObject(contents='foo'))
    inpath = self.CreateTempFile()
    ct = 'image/gif'
    self.RunGsUtil(['-h', 'x-goog-meta-xyz:abc', '-h', 'Content-Type:%s' % ct,
                    'cp', inpath, objuri])
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-L', objuri], return_stdout=True)
      self.assertRegexpMatches(stdout, r'Content-Type:\s+%s' % ct)
      self.assertRegexpMatches(stdout, r'xyz:\s+abc')
    _Check1()

  def test_overwrite_existing(self):
    """Tests overwriting an object's metadata."""
    objuri = suri(self.CreateObject(contents='foo'))
    inpath = self.CreateTempFile()
    self.RunGsUtil(['-h', 'x-goog-meta-xyz:abc', '-h', 'Content-Type:image/gif',
                    'cp', inpath, objuri])
    self.RunGsUtil(['setmeta', '-n', '-h', 'Content-Type:text/html', '-h',
                    'x-goog-meta-xyz', objuri])
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-L', objuri], return_stdout=True)
      self.assertRegexpMatches(stdout, r'Content-Type:\s+text/html')
      self.assertNotIn('xyz', stdout)
    _Check1()

  def test_duplicate_header_removal(self):
    stderr = self.RunGsUtil(
        ['setmeta', '-h', 'Content-Type:text/html', '-h', 'Content-Type',
         'gs://foo/bar'], expected_status=1, return_stderr=True)
    self.assertIn('Each header must appear at most once', stderr)

  def test_duplicate_header(self):
    stderr = self.RunGsUtil(
        ['setmeta', '-h', 'Content-Type:text/html', '-h', 'Content-Type:foobar',
         'gs://foo/bar'], expected_status=1, return_stderr=True)
    self.assertIn('Each header must appear at most once', stderr)

  def test_recursion_works(self):
    bucket_uri = self.CreateBucket()
    object1_uri = self.CreateObject(bucket_uri=bucket_uri, contents='foo')
    object2_uri = self.CreateObject(bucket_uri=bucket_uri, contents='foo')
    self.RunGsUtil(['setmeta', '-R', '-h', 'content-type:footype',
                    suri(bucket_uri)])

    for obj_uri in [object1_uri, object2_uri]:
      stdout = self.RunGsUtil(['stat', suri(obj_uri)], return_stdout=True)
      self.assertIn('footype', stdout)

  def test_invalid_non_ascii_custom_header(self):
    unicode_header = u'x-goog-meta-soufflé:5'
    unicode_header_bytes = unicode_header.encode(UTF8)
    stderr = self.RunGsUtil(
        ['setmeta', '-h', unicode_header_bytes, 'gs://foo/bar'],
        expected_status=1, return_stderr=True)
    self.assertIn('Invalid non-ASCII header', stderr)

  def test_valid_non_ascii_custom_header(self):
    """Tests setting custom metadata with a non-ASCII content."""
    objuri = self.CreateObject(contents='foo')
    unicode_header = u'x-goog-meta-dessert:soufflé'
    unicode_header_bytes = unicode_header.encode(UTF8)
    self.RunGsUtil(['setmeta', '-h', unicode_header_bytes, suri(objuri)])
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, timeout_secs=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-L', suri(objuri)], return_stdout=True)
      stdout = stdout.decode(UTF8)
      self.assertIn(u'dessert:\t\tsoufflé', stdout)
    _Check1()

  def test_disallowed_header(self):
    stderr = self.RunGsUtil(
        ['setmeta', '-h', 'Content-Length:5', 'gs://foo/bar'],
        expected_status=1, return_stderr=True)
    self.assertIn('Invalid or disallowed header', stderr)

  def test_setmeta_bucket(self):
    bucket_uri = self.CreateBucket()
    stderr = self.RunGsUtil(
        ['setmeta', '-h', 'x-goog-meta-foo:5', suri(bucket_uri)],
        expected_status=1, return_stderr=True)
    self.assertIn('must name an object', stderr)

  def test_setmeta_invalid_arg(self):
    stderr = self.RunGsUtil(
        ['setmeta', '-h', 'foo:bar:baz', 'gs://foo/bar'], expected_status=1,
        return_stderr=True)
    self.assertIn('must be either header or header:value', stderr)

  def test_setmeta_with_canned_acl(self):
    stderr = self.RunGsUtil(
        ['setmeta', '-h', 'x-goog-acl:public-read', 'gs://foo/bar'],
        expected_status=1, return_stderr=True)
    self.assertIn('gsutil setmeta no longer allows canned ACLs', stderr)

  def test_invalid_non_ascii_header_value(self):
    unicode_header = u'Content-Type:dessert/soufflé'
    unicode_header_bytes = unicode_header.encode(UTF8)
    stderr = self.RunGsUtil(
        ['setmeta', '-h', unicode_header_bytes, 'gs://foo/bar'],
        expected_status=1, return_stderr=True)
    self.assertIn('Invalid non-ASCII header', stderr)
