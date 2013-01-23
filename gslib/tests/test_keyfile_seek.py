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

import gslib.commands.cp as cp
import gslib.tests.testcase as testcase


class KeyfileTest(testcase.GsUtilIntegrationTestCase):
  """Tests gslib.commands.cp.KeyFile."""

  def testReadFull(self):
    bucket = self.CreateBucket()
    contents = '0123456789'
    k = self.CreateObject(bucket, contents=contents)
    keyfile = cp.KeyFile(k)
    self.assertEqual(keyfile.read(len(contents)), contents)
    keyfile.close()

  def testReadPartial(self):
    bucket = self.CreateBucket()
    contents = '0123456789'
    k = self.CreateObject(bucket, contents=contents)
    keyfile = cp.KeyFile(k)
    self.assertEqual(keyfile.read(5), contents[:5])
    self.assertEqual(keyfile.read(5), contents[5:])

  def testTell(self):
    bucket = self.CreateBucket()
    contents = '0123456789'
    k = self.CreateObject(bucket, contents=contents)
    keyfile = cp.KeyFile(k)
    self.assertEqual(keyfile.tell(), 0)
    keyfile.read(4)
    self.assertEqual(keyfile.tell(), 4)
    keyfile.read(6)
    self.assertEqual(keyfile.tell(), 10)
    keyfile.close()
    with self.assertRaisesRegexp(ValueError, 'operation on closed file'):
      keyfile.tell()

  def testSeek(self):
    bucket = self.CreateBucket()
    contents = '0123456789'
    k = self.CreateObject(bucket, contents=contents)
    keyfile = cp.KeyFile(k)
    self.assertEqual(keyfile.read(4), contents[:4])
    keyfile.seek(0)
    self.assertEqual(keyfile.read(4), contents[:4])
    keyfile.seek(5)
    self.assertEqual(keyfile.read(5), contents[5:])

    # Seeking negative should raise.
    with self.assertRaisesRegexp(IOError, 'Invalid argument'):
      keyfile.seek(-5)

    # Reading past end of file is supposed to return empty string.
    self.assertEqual(keyfile.read(20), '')

    # Seeking past end of file is supposed to silently work.
    keyfile.seek(50)
    self.assertEqual(keyfile.tell(), 50)
    self.assertEqual(keyfile.read(1), '')
