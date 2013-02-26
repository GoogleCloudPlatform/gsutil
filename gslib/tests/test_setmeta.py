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

import gslib.tests.testcase as testcase
from gslib.util import Retry
from gslib.tests.util import ObjectToURI as suri


class TestSetMeta(testcase.GsUtilIntegrationTestCase):
  """Integration tests for setmeta command."""

  def test_initial_metadata(self):
    objuri = suri(self.CreateObject(contents='foo'))
    inpath = self.CreateTempFile()
    ct = 'image/gif'
    self.RunGsUtil(['-h', 'x-goog-meta-xyz:abc', '-h', 'Content-Type:%s' % ct,
                    'cp', inpath, objuri])
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, delay=1, backoff=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-L', objuri], return_stdout=True)
      self.assertRegexpMatches(stdout, 'Content-Type:\s+%s' % ct)
      self.assertRegexpMatches(stdout, 'x-goog-meta-xyz:\s+abc')
    _Check1()

  def test_overwrite_existing(self):
    objuri = suri(self.CreateObject(contents='foo'))
    inpath = self.CreateTempFile()
    self.RunGsUtil(['-h', 'x-goog-meta-xyz:abc', '-h', 'Content-Type:image/gif',
                    'cp', inpath, objuri])
    self.RunGsUtil(['setmeta', '-n', '-h', 'Content-Type:text/html', '-h',
                    'x-goog-meta-xyz', objuri])
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, delay=1, backoff=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-L', objuri], return_stdout=True)
      self.assertRegexpMatches(stdout, 'Content-Type:\s+text/html')
      self.assertNotIn('xyz', stdout)
    _Check1()

  def test_missing_header(self):
    stderr = self.RunGsUtil(['setmeta', '"Content-Type"', 'gs://foo/bar'],
                            expected_status=1, return_stderr=True)
    self.assertIn('Fields being added must include values', stderr)

  def test_minus_header_value(self):
    stderr = self.RunGsUtil(['setmeta', '"-Content-Type:text/html"',
                             'gs://foo/bar'], expected_status=1,
                            return_stderr=True)
    self.assertIn('Removal spec may not contain ":"', stderr)

  def test_plus_and_minus(self):
    stderr = self.RunGsUtil(['setmeta', ('"Content-Type:text/html",'
                                         '"-Content-Type"'), 'gs://foo/bar'],
                            expected_status=1, return_stderr=True)
    self.assertIn('Each header must appear at most once', stderr)

  def test_non_ascii_custom_header(self):
    stderr = self.RunGsUtil(['setmeta', '"x-goog-meta-soufflé:5"',
                             'gs://foo/bar'], expected_status=1,
                            return_stderr=True)
    self.assertIn('Invalid non-ASCII header', stderr)

  def test_disallowed_header(self):
    stderr = self.RunGsUtil(['setmeta', '"Content-Length:5"',
                             'gs://foo/bar'], expected_status=1,
                            return_stderr=True)
    self.assertIn('Invalid or disallowed header', stderr)

  def test_deprecated_syntax(self):
    objuri = suri(self.CreateObject(contents='foo'))
    inpath = self.CreateTempFile()
    self.RunGsUtil(['-h', 'x-goog-meta-xyz:abc', '-h', 'Content-Type:image/gif',
                    'cp', inpath, objuri])

    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, delay=1, backoff=1)
    def _Check1():
      stdout = self.RunGsUtil(['ls', '-L', objuri], return_stdout=True)
      self.assertRegexpMatches(stdout, 'Content-Type:\s+image/gif')
      self.assertRegexpMatches(stdout, 'x-goog-meta-xyz:\s+abc')
    _Check1()

    stderr = self.RunGsUtil(
        ['setmeta', '-n', '"Content-Type:text/html","-x-goog-meta-xyz"',
         objuri],
        return_stderr=True)
    self.assertIn('WARNING: metadata spec syntax', stderr)
    self.assertIn('is deprecated and will eventually be removed', stderr)
    # Use @Retry as hedge against bucket listing eventual consistency.
    @Retry(AssertionError, tries=3, delay=1, backoff=1)
    def _Check2():
      stdout = self.RunGsUtil(['ls', '-L', objuri], return_stdout=True)
      self.assertRegexpMatches(stdout, 'Content-Type:\s+text/html')
      self.assertNotIn('xyz', stdout)
    _Check2()
