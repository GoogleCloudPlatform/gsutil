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
"""Integration tests for gsutil -D option."""

import gslib
from gslib.cs_api_map import ApiSelector
import gslib.tests.testcase as testcase
from gslib.tests.testcase.integration_testcase import SkipForS3
from gslib.tests.util import ObjectToURI as suri


@SkipForS3('-D output is implementation-specific.')
class TestCat(testcase.GsUtilIntegrationTestCase):
  """Integration tests for gsutil -D option."""

  def test_minus_D_cat(self):
    """Tests cat command with debug option."""
    key_uri = self.CreateObject(contents='0123456789')
    (stdout, stderr) = self.RunGsUtil(['-D', 'cat', suri(key_uri)],
                                      return_stdout=True, return_stderr=True)
    self.assertIn('You are running gsutil with debug output enabled.', stderr)
    self.assertIn("reply: 'HTTP/1.1 200 OK", stderr)
    self.assertIn('config: [', stderr)
    self.assertIn("reply: 'HTTP/1.1 200 OK", stderr)
    self.assertIn('header: Expires: ', stderr)
    self.assertIn('header: Date: ', stderr)
    self.assertIn('header: Content-Type: application/octet-stream', stderr)
    self.assertIn('header: Content-Length: 10', stderr)

    if self.test_api == ApiSelector.XML:
      self.assertRegexpMatches(
          stderr, '.*HEAD /%s/%s.*Content-Length: 0.*User-Agent: .*gsutil/%s' %
          (key_uri.bucket_name, key_uri.object_name, gslib.VERSION))

      self.assertIn('header: Cache-Control: private, max-age=0',
                    stderr)
      self.assertIn('header: Last-Modified: ', stderr)
      self.assertIn('header: ETag: "781e5e245d69b566979b86e28d23f2c7"', stderr)
      self.assertIn('header: x-goog-generation: ', stderr)
      self.assertIn('header: x-goog-metageneration: 1', stderr)
      self.assertIn('header: x-goog-hash: crc32c=KAwGng==', stderr)
      self.assertIn('header: x-goog-hash: md5=eB5eJF1ptWaXm4bijSPyxw==', stderr)
    elif self.test_api == ApiSelector.JSON:
      self.assertRegexpMatches(
          stderr, '.*GET.*b/%s/o/%s.*user-agent:.*gsutil/%s' %
          (key_uri.bucket_name, key_uri.object_name, gslib.VERSION))
      self.assertIn(('header: Cache-Control: private, max-age=0, '
                     'must-revalidate, no-transform'), stderr)
      self.assertIn("md5Hash: u'eB5eJF1ptWaXm4bijSPyxw=='", stderr)

    if gslib.IS_PACKAGE_INSTALL:
      self.assertIn('PACKAGED_GSUTIL_INSTALLS_DO_NOT_HAVE_CHECKSUMS', stdout)
    else:
      self.assertRegexpMatches(stdout, r'.*checksum [0-9a-f]{32}.*')
    self.assertIn('gsutil version %s' % gslib.VERSION, stdout)
    self.assertIn('boto version ', stdout)
    self.assertIn('python version ', stdout)
    self.assertIn('config path: ', stdout)
    self.assertIn('gsutil path: ', stdout)
    self.assertIn('compiled crcmod: ', stdout)
    self.assertIn('installed via package manager: ', stdout)
    self.assertIn('editable install: ', stdout)
      