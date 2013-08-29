# -*- coding: utf-8 -*-
#
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
import re
import subprocess
import sys

import gslib
import gslib.tests.testcase as testcase
from gslib.tests.util import ObjectToURI as suri
from gslib.wildcard_iterator import ContainsWildcard

class TestStat(testcase.GsUtilIntegrationTestCase):
  """Integration tests for stat command."""

  def test_stat_output(self):
    object_uri = self.CreateObject(contents='z')
    stdout = self.RunGsUtil(['stat', suri(object_uri)], return_stdout=True)
    self.assertIn(object_uri.uri, stdout)
    self.assertIn('Creation time:', stdout)
    self.assertIn('Cache-Control:', stdout)
    self.assertIn('Content-Encoding:', stdout)
    self.assertIn('Content-Length:', stdout)
    self.assertIn('Content-Type:', stdout)
    self.assertIn('Hash (crc32c):', stdout)
    self.assertIn('Hash (md5):', stdout)
    self.assertIn('ETag:', stdout)

  def test_minus_q_stat(self):
    object_uri = self.CreateObject(contents='z')
    stdout = self.RunGsUtil(['-q', 'stat', suri(object_uri)],
                            return_stdout=True)
    self.assertEquals(0, len(stdout))
    stdout = self.RunGsUtil(['-q', 'stat', suri(object_uri, 'junk')],
                            return_stdout=True, expected_status=1)
    self.assertEquals(0, len(stdout))

  def test_stat_of_non_object_uri(self):
    self.RunGsUtil(['-q', 'stat', 'gs://'], expected_status=1)
    self.RunGsUtil(['-q', 'stat', 'gs://bucket/object'], expected_status=1)
    self.RunGsUtil(['-q', 'stat', 'file://tmp/abc'], expected_status=1)
