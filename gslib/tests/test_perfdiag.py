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
from gslib.tests.util import ObjectToURI as suri


class TestPerfDiag(testcase.GsUtilIntegrationTestCase):
  """Integration tests for perfdiag command."""

  def test_latency(self):
    bucket_uri = self.CreateBucket()
    self.RunGsUtil(['perfdiag', '-n', '1', '-t', 'lat', suri(bucket_uri)])

  def _run_basic_wthru_or_rthru(self, test_name, num_processes, num_threads):
    bucket_uri = self.CreateBucket()
    self.RunGsUtil(['perfdiag', '-n', str(num_processes * num_threads),
                    '-s', '1024', '-c', str(num_processes),
                    '-k', str(num_threads), '-t', test_name, suri(bucket_uri)])

  def test_write_throughput_single_process_multi_thread(self):
    self._run_basic_wthru_or_rthru('wthru', 1, 2)

  def test_write_throughput_multi_process_single_thread(self):
    self._run_basic_wthru_or_rthru('wthru', 2, 1)

  def test_write_throughput_multi_process_multi_thread(self):
    self._run_basic_wthru_or_rthru('wthru', 2, 2)

  def test_read_throughput_single_process_multi_thread(self):
    self._run_basic_wthru_or_rthru('rthru', 1, 2)

  def test_read_throughput_multi_process_single_thread(self):
    self._run_basic_wthru_or_rthru('rthru', 2, 1)

  def test_read_throughput_multi_process_multi_thread(self):
    self._run_basic_wthru_or_rthru('rthru', 2, 2)

  def test_input_output(self):
    outpath = self.CreateTempFile()
    bucket_uri = self.CreateBucket()
    self.RunGsUtil(['perfdiag', '-o', outpath, '-n', '1', '-t', 'lat',
                    suri(bucket_uri)])
    self.RunGsUtil(['perfdiag', '-i', outpath])

  def test_invalid_size(self):
    stderr = self.RunGsUtil(
        ['perfdiag', '-n', '1', '-s', 'foo', '-t', 'wthru', 'gs://foobar'],
        expected_status=1, return_stderr=True)
    self.assertIn('Invalid -s', stderr)

  def test_toobig_size(self):
    stderr = self.RunGsUtil(
        ['perfdiag', '-n', '1', '-s', '3pb', '-t', 'wthru', 'gs://foobar'],
        expected_status=1, return_stderr=True)
    self.assertIn('Maximum throughput file size', stderr)
