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

import gslib


class TestCp(gslib.tests.testcase.unit_testcase.GsUtilUnitTestCase):
  """Unit tests for functions in cp command."""

  def test_hash_filename(self):
    # Tests that _hash_filename function works for both string and unicode
    # filenames (without raising any Unicode encode/decode errors).
    gslib.commands.cp._hash_filename('file1')
    gslib.commands.cp._hash_filename(u'file1')
