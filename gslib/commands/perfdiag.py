# Copyright 2012 Google Inc. All Rights Reserved.
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

"""Contains the perfdiag gsutil command."""

# Get the system logging module, not our local logging module.
from __future__ import absolute_import

import base64
import binascii
import calendar
from collections import defaultdict
import contextlib
import cStringIO
import datetime
import json
import logging
import math
import multiprocessing
import os
import random
import re
import socket
import string
import subprocess
import tempfile
import time

from apiclient import errors as apiclient_errors
import boto
import boto.gs.connection
import gslib
from gslib.cloud_api import NotFoundException
from gslib.cloud_api import ServiceException
from gslib.command import Command
from gslib.command import DummyArgChecker
from gslib.commands import config
from gslib.cp_helper import GetDownloadSerializationDict
from gslib.cs_api_map import ApiSelector
from gslib.exception import CommandException
from gslib.storage_url import StorageUrlFromString
from gslib.third_party.storage_apitools import storage_v1beta2_messages as apitools_messages
from gslib.util import CalculateMd5FromContents
from gslib.util import HumanReadableToBytes
from gslib.util import IS_LINUX
from gslib.util import MakeBitsHumanReadable
from gslib.util import MakeHumanReadable
from gslib.util import Percentile

_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil perfdiag [-i in.json] [-o out.json] [-n iterations] [-c processes]
  [-k threads] [-s size] [-t tests] url...


<B>DESCRIPTION</B>
  The perfdiag command runs a suite of diagnostic tests for a given Google
  Storage bucket.

  The 'url' parameter must name an existing bucket (e.g. gs://foo) to which
  the user has write permission. Several test files will be uploaded to and
  downloaded from this bucket. All test files will be deleted at the completion
  of the diagnostic if it finishes successfully.

  gsutil performance can be impacted by many factors at the client, server,
  and in-between, such as: CPU speed; available memory; the access path to the
  local disk; network bandwidth; contention and error rates along the path
  between gsutil and Google; operating system buffering configuration; and
  firewalls and other network elements. The perfdiag command is provided so
  that customers can run a known measurement suite when troubleshooting
  performance problems.


<B>PROVIDING DIAGNOSTIC OUTPUT TO GOOGLE CLOUD STORAGE TEAM</B>
  If the Google Cloud Storage Team asks you to run a performance diagnostic
  please use the following command, and email the output file (output.json)
  to gs-team@google.com:

    gsutil perfdiag -o output.json gs://your-bucket


<B>OPTIONS</B>
  -n          Sets the number of iterations performed when downloading and
              uploading files during latency and throughput tests. Defaults to
              5.

  -c          Sets the number of processes to use while running throughput
              experiments. The default value is 1.

  -k          Sets the number of threads per process to use while running
              throughput experiments. Each process will receive an equal number
              of threads. The default value is 1.

  -s          Sets the size (in bytes) of the test file used to perform read
              and write throughput tests. The default is 1 MiB. This can also
              be specified using byte suffixes. Examples: 1M, 500KB, etc.

  -t          Sets the list of diagnostic tests to perform. The default is to
              run all diagnostic tests. Must be a comma-separated list
              containing one or more of the following:

              lat
                 Runs N iterations (set with -n) of writing the file,
                 retrieving its metadata, reading the file, and deleting
                 the file. Records the latency of each operation.

              rthru
                 Runs N (set with -n) read operations, with at most C
                 (set with -c) reads outstanding at any given time.

              wthru
                 Runs N (set with -n) write operations, with at most C
                 (set with -c) writes outstanding at any given time.

  -m          Adds metadata to the result JSON file. Multiple -m values can be
              specified. Example:

                  gsutil perfdiag -m "key1:value1" -m "key2:value2" \
                                  gs://bucketname/

              Each metadata key will be added to the top-level "metadata"
              dictionary in the output JSON file.

  -o          Writes the results of the diagnostic to an output file. The output
              is a JSON file containing system information and performance
              diagnostic results. The file can be read and reported later using
              the -i option.

  -i          Reads the JSON output file created using the -o command and prints
              a formatted description of the results.


<B>MEASURING AVAILABILITY</B>
  The perfdiag command ignores the boto num_retries configuration parameter.
  Instead, it always retries on HTTP errors in the 500 range and keeps track of
  how many 500 errors were encountered during the test. The availability
  measurement is reported at the end of the test.

  Note that HTTP responses are only recorded when the request was made in a
  single process. When using multiple processes or threads, read and write
  throughput measurements are performed in an external process, so the
  availability numbers reported won't include the throughput measurements.


<B>NOTE</B>
  The perfdiag command collects system information. It collects your IP address,
  executes DNS queries to Google servers and collects the results, and collects
  network statistics information from the output of netstat -s. None of this
  information will be sent to Google unless you choose to send it.
""")


def _DownloadWrapper(cls, download_tuple, thread_state=None):
  cls.Download(download_tuple, thread_state=thread_state)


def _UploadWrapper(cls, thru_tuple, thread_state=None):
  cls.Upload(thru_tuple, thread_state=thread_state)


def _PerfdiagExceptionHandler(cls, e):
  """Simple exception handler to allow post-completion status."""
  cls.logger.error(str(e))


class DummyFile(object):
  """A dummy, file-like object that throws away everything written to it."""

  def write(self, *args, **kwargs):  # pylint: disable=invalid-name
    pass


class PerfDiagCommand(Command):
  """Implementation of gsutil perfdiag command."""

  # Command specification. See base class for documentation.
  command_spec = Command.CreateCommandSpec(
      'perfdiag',
      command_name_aliases=['diag', 'diagnostic', 'perf', 'performance'],
      min_args=0,
      max_args=1,
      supported_sub_args='n:c:k:s:t:m:i:o:',
      file_url_ok=False,
      provider_url_ok=False,
      urls_start_arg=0,
      gs_api_support=[ApiSelector.XML, ApiSelector.JSON],
      gs_default_api=ApiSelector.JSON,
  )
  # Help specification. See help_provider.py for documentation.
  help_spec = Command.HelpSpec(
      help_name='perfdiag',
      help_name_aliases=[],
      help_type='command_help',
      help_one_line_summary='Run performance diagnostic',
      help_text=_detailed_help_text,
      subcommand_help_text={},
  )

  # Byte sizes to use for latency testing files.
  # TODO: Consider letting the user specify these sizes with a configuration
  # parameter.
  test_file_sizes = (
      0,  # 0 bytes
      1024,  # 1 KB
      102400,  # 100 KB
      1048576,  # 1MB
  )

  # List of all diagnostic tests.
  ALL_DIAG_TESTS = ('rthru', 'wthru', 'lat')

  # Google Cloud Storage API endpoint host.
  GOOGLE_API_HOST = boto.gs.connection.GSConnection.DefaultHost

  # Maximum number of times to retry requests on 5xx errors.
  MAX_SERVER_ERROR_RETRIES = 5
  # Maximum number of times to retry requests on more serious errors like
  # the socket breaking.
  MAX_TOTAL_RETRIES = 10

  # The default buffer size in boto's Key object is set to 8KB. This becomes a
  # bottleneck at high throughput rates, so we increase it.
  KEY_BUFFER_SIZE = 16384

  # The maximum number of bytes to generate pseudo-randomly before beginning
  # to repeat bytes. This number was chosen as the next prime larger than 5 MB.
  MAX_UNIQUE_RANDOM_BYTES = 5242883

  def _Exec(self, cmd, raise_on_error=True, return_output=False,
            mute_stderr=False):
    """Executes a command in a subprocess.

    Args:
      cmd: List containing the command to execute.
      raise_on_error: Whether or not to raise an exception when a process exits
          with a non-zero return code.
      return_output: If set to True, the return value of the function is the
          stdout of the process.
      mute_stderr: If set to True, the stderr of the process is not printed to
          the console.

    Returns:
      The return code of the process or the stdout if return_output is set.

    Raises:
      Exception: If raise_on_error is set to True and any process exits with a
      non-zero return code.
    """
    self.logger.debug('Running command: %s', cmd)
    stderr = subprocess.PIPE if mute_stderr else None
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=stderr)
    (stdoutdata, _) = p.communicate()
    if raise_on_error and p.returncode:
      raise CommandException("Received non-zero return code (%d) from "
                             "subprocess '%s'." % (p.returncode, ' '.join(cmd)))
    return stdoutdata if return_output else p.returncode

  def _SetUp(self):
    """Performs setup operations needed before diagnostics can be run."""

    # Stores test result data.
    self.results = {}
    # List of test files in a temporary location on disk for latency ops.
    self.latency_files = []
    # Maps each test file path to its size in bytes.
    self.file_sizes = {}
    # Maps each test file to its contents as a string.
    self.file_contents = {}
    # Maps each test file to its MD5 hash.
    self.file_md5s = {}
    # Total number of HTTP requests made.
    self.total_requests = 0
    # Total number of HTTP 5xx errors.
    self.request_errors = 0
    # Number of responses, keyed by response code.
    self.error_responses_by_code = defaultdict(int)
    # Total number of socket errors.
    self.connection_breaks = 0

    def _MakeFile(file_size):
      """Creates a temporary file of the given size and returns its path."""
      fd, fpath = tempfile.mkstemp(suffix='.bin', prefix='gsutil_test_file',
                                   text=False)
      self.file_sizes[fpath] = file_size
      random_bytes = os.urandom(min(file_size, self.MAX_UNIQUE_RANDOM_BYTES))
      total_bytes = 0
      file_contents = ''
      while total_bytes < file_size:
        num_bytes = min(self.MAX_UNIQUE_RANDOM_BYTES, file_size - total_bytes)
        file_contents += random_bytes[:num_bytes]
        total_bytes += num_bytes
      self.file_contents[fpath] = file_contents
      with os.fdopen(fd, 'wb') as f:
        f.write(self.file_contents[fpath])
      with open(fpath, 'rb') as f:
        self.file_md5s[fpath] = base64.encodestring(
            binascii.unhexlify(CalculateMd5FromContents(f))).rstrip('\n')
      return fpath

    # Create files for latency tests.
    for file_size in self.test_file_sizes:
      fpath = _MakeFile(file_size)
      self.latency_files.append(fpath)

    # Creating a file for warming up the TCP connection.
    self.tcp_warmup_file = _MakeFile(5 * 1024 * 1024)  # 5 Megabytes.
    # Remote file to use for TCP warmup.
    self.tcp_warmup_remote_file = (str(self.bucket_url) +
                                   os.path.basename(self.tcp_warmup_file))

    # Local file on disk for write throughput tests.
    self.thru_local_file = _MakeFile(self.thru_filesize)
    # Remote file to write/read from during throughput tests.
    self.thru_remote_file = (str(self.bucket_url) +
                             os.path.basename(self.thru_local_file))
    # Dummy file buffer to use for downloading that goes nowhere.
    self.discard_sink = DummyFile()

  def _TearDown(self):
    """Performs operations to clean things up after performing diagnostics."""
    for fpath in self.latency_files + [self.thru_local_file,
                                       self.tcp_warmup_file]:
      try:
        os.remove(fpath)
      except OSError:
        pass

    cleanup_files = [self.thru_local_file, self.tcp_warmup_file]
    for f in cleanup_files:

      def _Delete():
        try:
          self.gsutil_api.DeleteObject(self.bucket_url.bucket_name,
                                       os.path.basename(f),
                                       provider=self.provider)
        except NotFoundException as e:
          if e.status != 404:
            raise

      self._RunOperation(_Delete)

  @contextlib.contextmanager
  def _Time(self, key, bucket):
    """A context manager that measures time.

    A context manager that prints a status message before and after executing
    the inner command and times how long the inner command takes. Keeps track of
    the timing, aggregated by the given key.

    Args:
      key: The key to insert the timing value into a dictionary bucket.
      bucket: A dictionary to place the timing value in.

    Yields:
      For the context manager.
    """
    self.logger.info('%s starting...', key)
    t0 = time.time()
    yield
    t1 = time.time()
    bucket[key].append(t1 - t0)
    self.logger.info('%s done.', key)

  def _RunOperation(self, func):
    """Runs an operation with retry logic.

    Args:
      func: The function to run.

    Returns:
      True if the operation succeeds, False if aborted.
    """
    # We retry on httplib exceptions that can happen if the socket was closed
    # by the remote party or the connection broke because of network issues.
    # Only the BotoServerError is counted as a 5xx error towards the retry
    # limit.
    success = False
    server_error_retried = 0
    total_retried = 0
    i = 0
    return_val = None
    while not success:
      next_sleep = random.random() * (2 ** i) + 1
      try:
        return_val = func()
        self.total_requests += 1
        success = True
      except tuple(self.exceptions) as e:
        total_retried += 1
        if total_retried > self.MAX_TOTAL_RETRIES:
          self.logger.info('Reached maximum total retries. Not retrying.')
          break
        if (isinstance(e, apiclient_errors.HttpError) or
            isinstance(e, ServiceException)):
          if isinstance(e, apiclient_errors.HttpError):
            status = e.resp.status
          else:
            status = e.status
          if status >= 500:
            self.error_responses_by_code[status] += 1
            self.total_requests += 1
            self.request_errors += 1
            server_error_retried += 1
            time.sleep(next_sleep)
          else:
            raise
          if server_error_retried > self.MAX_SERVER_ERROR_RETRIES:
            self.logger.info(
                'Reached maximum server error retries. Not retrying.')
            break
        else:
          self.connection_breaks += 1
    return return_val

  def _RunLatencyTests(self):
    """Runs latency tests."""
    # Stores timing information for each category of operation.
    self.results['latency'] = defaultdict(list)

    for i in range(self.num_iterations):
      self.logger.info('\nRunning latency iteration %d...', i+1)
      for fpath in self.latency_files:
        basename = os.path.basename(fpath)
        url = StorageUrlFromString(str(self.bucket_url))
        url.object_name = basename
        file_size = self.file_sizes[fpath]
        readable_file_size = MakeHumanReadable(file_size)

        self.logger.info(
            "\nFile of size %(size)s located on disk at '%(fpath)s' being "
            "diagnosed in the cloud at '%(url)s'."
            % {'size': readable_file_size, 'fpath': fpath, 'url': url})

        upload_target = StorageUrlToUploadObjectMetadata(url)

        def _Upload():
          io_fp = cStringIO.StringIO(self.file_contents[fpath])
          with self._Time('UPLOAD_%d' % file_size, self.results['latency']):
            self.gsutil_api.UploadObject(
                io_fp, upload_target, size=file_size, provider=self.provider,
                fields=['name'])
        self._RunOperation(_Upload)

        def _Metadata():
          with self._Time('METADATA_%d' % file_size, self.results['latency']):
            return self.gsutil_api.GetObjectMetadata(
                url.bucket_name, url.object_name,
                provider=self.provider, fields=['name', 'contentType',
                                                'mediaLink', 'size'])
        # Download will get the metadata first if we don't pass it in.
        download_metadata = self._RunOperation(_Metadata)
        serialization_dict = GetDownloadSerializationDict(download_metadata)
        serialization_data = json.dumps(serialization_dict)

        def _Download():
          with self._Time('DOWNLOAD_%d' % file_size, self.results['latency']):
            self.gsutil_api.GetObjectMedia(
                url.bucket_name, url.object_name, self.discard_sink,
                provider=self.provider, serialization_data=serialization_data)
        self._RunOperation(_Download)

        def _Delete():
          with self._Time('DELETE_%d' % file_size, self.results['latency']):
            self.gsutil_api.DeleteObject(url.bucket_name, url.object_name,
                                         provider=self.provider)
        self._RunOperation(_Delete)

  class _CpFilter(logging.Filter):
    def filter(self, record):
      # Used to prevent cp._LogCopyOperation from spewing output from
      # subprocesses about every iteration.
      msg = record.getMessage()
      return not (('Copying file:///' in msg) or ('Copying gs://' in msg) or
                  ('Computing CRC' in msg))

  def _PerfdiagExceptionHandler(self, e):
    """Simple exception handler to allow post-completion status."""
    self.logger.error(str(e))

  def _RunReadThruTests(self):
    """Runs read throughput tests."""
    self.results['read_throughput'] = {'file_size': self.thru_filesize,
                                       'num_times': self.num_iterations,
                                       'processes': self.processes,
                                       'threads': self.threads}

    # Copy the TCP warmup file.
    warmup_url = StorageUrlFromString(str(self.bucket_url))
    warmup_url.object_name = os.path.basename(self.tcp_warmup_file)
    warmup_target = StorageUrlToUploadObjectMetadata(warmup_url)

    # TODO: gsutil-beta: Need to disable dumping payloads at debuglevel==2
    # for JSON API, because it dumps the entire warmup file.
    def _Upload1():
      self.gsutil_api.UploadObject(
          cStringIO.StringIO(self.file_contents[self.tcp_warmup_file]),
          warmup_target, provider=self.provider, fields=['name'])
    self._RunOperation(_Upload1)

    # Copy the file to remote location before reading.
    thru_url = StorageUrlFromString(str(self.bucket_url))
    thru_url.object_name = self.thru_local_file
    thru_target = StorageUrlToUploadObjectMetadata(thru_url)
    thru_target.md5Hash = self.file_md5s[self.thru_local_file]

    # Get the mediaLink here so that we can pass it to download.
    def _Upload2():
      return self.gsutil_api.UploadObject(
          cStringIO.StringIO(self.file_contents[self.thru_local_file]),
          thru_target, provider=self.provider, size=self.thru_filesize,
          fields=['name', 'mediaLink', 'size'])

    # Get the metadata for the object so that we are just measuring performance
    # on the actual bytes transfer.
    download_metadata = self._RunOperation(_Upload2)
    serialization_dict = GetDownloadSerializationDict(download_metadata)
    serialization_data = json.dumps(serialization_dict)

    if self.processes == 1 and self.threads == 1:

      # Warm up the TCP connection.
      def _Warmup():
        self.gsutil_api.GetObjectMedia(warmup_url.bucket_name,
                                       warmup_url.object_name,
                                       self.discard_sink,
                                       provider=self.provider)
      self._RunOperation(_Warmup)

      times = []

      def _Download():
        t0 = time.time()
        self.gsutil_api.GetObjectMedia(
            thru_url.bucket_name, thru_url.object_name, self.discard_sink,
            provider=self.provider, serialization_data=serialization_data)
        t1 = time.time()
        times.append(t1 - t0)
      for _ in range(self.num_iterations):
        self._RunOperation(_Download)
      time_took = sum(times)
    else:
      args = ([(thru_url.bucket_name, thru_url.object_name, serialization_data)]
              * self.num_iterations)
      self.logger.addFilter(self._CpFilter())

      t0 = time.time()
      self.Apply(_DownloadWrapper,
                 args,
                 _PerfdiagExceptionHandler,
                 arg_checker=DummyArgChecker,
                 parallel_operations_override=True,
                 process_count=self.processes,
                 thread_count=self.threads)
      t1 = time.time()
      time_took = t1 - t0

    total_bytes_copied = self.thru_filesize * self.num_iterations
    bytes_per_second = total_bytes_copied / time_took

    self.results['read_throughput']['time_took'] = time_took
    self.results['read_throughput']['total_bytes_copied'] = total_bytes_copied
    self.results['read_throughput']['bytes_per_second'] = bytes_per_second

  def _RunWriteThruTests(self):
    """Runs write throughput tests."""
    self.results['write_throughput'] = {'file_size': self.thru_filesize,
                                        'num_copies': self.num_iterations,
                                        'processes': self.processes,
                                        'threads': self.threads}

    warmup_url = StorageUrlFromString(str(self.bucket_url))
    warmup_url.object_name = os.path.basename(self.tcp_warmup_file)
    warmup_target = StorageUrlToUploadObjectMetadata(warmup_url)

    thru_url = StorageUrlFromString(str(self.bucket_url))
    thru_url.object_name = self.thru_local_file
    thru_target = StorageUrlToUploadObjectMetadata(thru_url)
    thru_target.md5Hash = self.file_md5s[self.thru_local_file]

    thru_tuple = UploadObjectTuple(thru_target.bucket, thru_target.name,
                                   md5=thru_target.md5Hash)

    if self.processes == 1 and self.threads == 1:
      # Warm up the TCP connection.
      def _Warmup():
        self.gsutil_api.UploadObject(
            cStringIO.StringIO(self.file_contents[self.tcp_warmup_file]),
            warmup_target, provider=self.provider, size=self.thru_filesize,
            fields=['name'])
      self._RunOperation(_Warmup)

      times = []

      def _Upload():
        """Uploads the write throughput measurement object."""
        upload_target = apitools_messages.Object(bucket=thru_tuple.bucket_name,
                                                 name=thru_tuple.object_name,
                                                 md5Hash=thru_tuple.md5)
        io_fp = cStringIO.StringIO(self.file_contents[self.thru_local_file])
        t0 = time.time()
        self.gsutil_api.UploadObject(
            io_fp, upload_target, provider=self.provider,
            size=self.thru_filesize, fields=['name'])
        t1 = time.time()
        times.append(t1 - t0)
      for _ in range(self.num_iterations):
        self._RunOperation(_Upload)
      time_took = sum(times)

    else:
      args = [thru_tuple] * self.num_iterations
      t0 = time.time()
      self.Apply(_UploadWrapper,
                 args,
                 _PerfdiagExceptionHandler,
                 arg_checker=DummyArgChecker,
                 parallel_operations_override=True,
                 process_count=self.processes,
                 thread_count=self.threads)
      t1 = time.time()
      time_took = t1 - t0

    total_bytes_copied = self.thru_filesize * self.num_iterations
    bytes_per_second = total_bytes_copied / time_took

    self.results['write_throughput']['time_took'] = time_took
    self.results['write_throughput']['total_bytes_copied'] = total_bytes_copied
    self.results['write_throughput']['bytes_per_second'] = bytes_per_second

  def Upload(self, thru_tuple, thread_state=None):
    if thread_state:
      gsutil_api = thread_state
    else:
      gsutil_api = self.gsutil_api
    upload_target = apitools_messages.Object(bucket=thru_tuple.bucket_name,
                                             name=thru_tuple.object_name,
                                             md5Hash=thru_tuple.md5)
    gsutil_api.UploadObject(
        cStringIO.StringIO(self.file_contents[self.thru_local_file]),
        upload_target, provider=self.provider, size=self.thru_filesize,
        fields=['name'])

  def Download(self, download_tuple, thread_state=None):
    """Downloads a file.

    Args:
      download_tuple: (bucket name, object name, serialization data for object).
      thread_state: gsutil Cloud API instance to use for the download.
    """
    if thread_state:
      gsutil_api = thread_state
    else:
      gsutil_api = self.gsutil_api
    gsutil_api.GetObjectMedia(
        download_tuple[0], download_tuple[1], self.discard_sink,
        provider=self.provider, serialization_data=download_tuple[2])

  def _GetDiskCounters(self):
    """Retrieves disk I/O statistics for all disks.

    Adapted from the psutil module's psutil._pslinux.disk_io_counters:
      http://code.google.com/p/psutil/source/browse/trunk/psutil/_pslinux.py

    Originally distributed under under a BSD license.
    Original Copyright (c) 2009, Jay Loden, Dave Daeschler, Giampaolo Rodola.

    Returns:
      A dictionary containing disk names mapped to the disk counters from
      /disk/diskstats.
    """
    # iostat documentation states that sectors are equivalent with blocks and
    # have a size of 512 bytes since 2.4 kernels. This value is needed to
    # calculate the amount of disk I/O in bytes.
    sector_size = 512

    partitions = []
    with open('/proc/partitions', 'r') as f:
      lines = f.readlines()[2:]
      for line in lines:
        _, _, _, name = line.split()
        if name[-1].isdigit():
          partitions.append(name)

    retdict = {}
    with open('/proc/diskstats', 'r') as f:
      for line in f:
        values = line.split()[:11]
        _, _, name, reads, _, rbytes, rtime, writes, _, wbytes, wtime = values
        if name in partitions:
          rbytes = int(rbytes) * sector_size
          wbytes = int(wbytes) * sector_size
          reads = int(reads)
          writes = int(writes)
          rtime = int(rtime)
          wtime = int(wtime)
          retdict[name] = (reads, writes, rbytes, wbytes, rtime, wtime)
    return retdict

  def _GetTcpStats(self):
    """Tries to parse out TCP packet information from netstat output.

    Returns:
       A dictionary containing TCP information
    """
    # netstat return code is non-zero for -s on Linux, so don't raise on error.
    netstat_output = self._Exec(['netstat', '-s'], return_output=True,
                                raise_on_error=False)
    netstat_output = netstat_output.strip().lower()
    found_tcp = False
    tcp_retransmit = None
    tcp_received = None
    tcp_sent = None
    for line in netstat_output.split('\n'):
      # Header for TCP section is "Tcp:" in Linux/Mac and
      # "TCP Statistics for" in Windows.
      if 'tcp:' in line or 'tcp statistics' in line:
        found_tcp = True

      # Linux == "segments retransmited" (sic), Mac == "retransmit timeouts"
      # Windows == "segments retransmitted".
      if (found_tcp and tcp_retransmit is None and
          ('segments retransmited' in line or 'retransmit timeouts' in line or
           'segments retransmitted' in line)):
        tcp_retransmit = ''.join(c for c in line if c in string.digits)

      # Linux+Windows == "segments received", Mac == "packets received".
      if (found_tcp and tcp_received is None and
          ('segments received' in line or 'packets received' in line)):
        tcp_received = ''.join(c for c in line if c in string.digits)

      # Linux == "segments send out" (sic), Mac+Windows == "packets sent".
      if (found_tcp and tcp_sent is None and
          ('segments send out' in line or 'packets sent' in line or
           'segments sent' in line)):
        tcp_sent = ''.join(c for c in line if c in string.digits)

    result = {}
    try:
      result['tcp_retransmit'] = int(tcp_retransmit)
      result['tcp_received'] = int(tcp_received)
      result['tcp_sent'] = int(tcp_sent)
    except (ValueError, TypeError):
      result['tcp_retransmit'] = None
      result['tcp_received'] = None
      result['tcp_sent'] = None

    return result

  def _CollectSysInfo(self):
    """Collects system information."""
    sysinfo = {}

    # All exceptions that might be raised from socket module calls.
    socket_errors = (
        socket.error, socket.herror, socket.gaierror, socket.timeout)

    # Find out whether HTTPS is enabled in Boto.
    sysinfo['boto_https_enabled'] = boto.config.get('Boto', 'is_secure', True)
    # Get the local IP address from socket lib.
    try:
      sysinfo['ip_address'] = socket.gethostbyname(socket.gethostname())
    except socket_errors:
      sysinfo['ip_address'] = ''
    # Record the temporary directory used since it can affect performance, e.g.
    # when on a networked filesystem.
    sysinfo['tempdir'] = tempfile.gettempdir()

    # Produces an RFC 2822 compliant GMT timestamp.
    sysinfo['gmt_timestamp'] = time.strftime('%a, %d %b %Y %H:%M:%S +0000',
                                             time.gmtime())

    # Execute a CNAME lookup on Google DNS to find what Google server
    # it's routing to.
    cmd = ['nslookup', '-type=CNAME', self.GOOGLE_API_HOST]
    try:
      nslookup_cname_output = self._Exec(cmd, return_output=True)
      m = re.search(r' = (?P<googserv>[^.]+)\.', nslookup_cname_output)
      sysinfo['googserv_route'] = m.group('googserv') if m else None
    except OSError:
      sysinfo['googserv_route'] = ''

    # Look up IP addresses for Google Server.
    try:
      (hostname, _, ipaddrlist) = socket.gethostbyname_ex(self.GOOGLE_API_HOST)
      sysinfo['googserv_ips'] = ipaddrlist
    except socket_errors:
      sysinfo['googserv_ips'] = []

    # Reverse lookup the hostnames for the Google Server IPs.
    sysinfo['googserv_hostnames'] = []
    for googserv_ip in ipaddrlist:
      try:
        (hostname, _, ipaddrlist) = socket.gethostbyaddr(googserv_ip)
        sysinfo['googserv_hostnames'].append(hostname)
      except socket_errors:
        pass

    # Query o-o to find out what the Google DNS thinks is the user's IP.
    try:
      cmd = ['nslookup', '-type=TXT', 'o-o.myaddr.google.com.']
      nslookup_txt_output = self._Exec(cmd, return_output=True)
      m = re.search(r'text\s+=\s+"(?P<dnsip>[\.\d]+)"', nslookup_txt_output)
      sysinfo['dns_o-o_ip'] = m.group('dnsip') if m else None
    except OSError:
      sysinfo['dns_o-o_ip'] = ''

    # Try and find the number of CPUs in the system if available.
    try:
      sysinfo['cpu_count'] = multiprocessing.cpu_count()
    except NotImplementedError:
      sysinfo['cpu_count'] = None

    # For *nix platforms, obtain the CPU load.
    try:
      sysinfo['load_avg'] = list(os.getloadavg())
    except (AttributeError, OSError):
      sysinfo['load_avg'] = None

    # Try and collect memory information from /proc/meminfo if possible.
    mem_total = None
    mem_free = None
    mem_buffers = None
    mem_cached = None

    try:
      with open('/proc/meminfo', 'r') as f:
        for line in f:
          if line.startswith('MemTotal'):
            mem_total = (int(''.join(c for c in line if c in string.digits))
                         * 1000)
          elif line.startswith('MemFree'):
            mem_free = (int(''.join(c for c in line if c in string.digits))
                        * 1000)
          elif line.startswith('Buffers'):
            mem_buffers = (int(''.join(c for c in line if c in string.digits))
                           * 1000)
          elif line.startswith('Cached'):
            mem_cached = (int(''.join(c for c in line if c in string.digits))
                          * 1000)
    except (IOError, ValueError):
      pass

    sysinfo['meminfo'] = {'mem_total': mem_total,
                          'mem_free': mem_free,
                          'mem_buffers': mem_buffers,
                          'mem_cached': mem_cached}

    # Get configuration attributes from config module.
    sysinfo['gsutil_config'] = {}
    for attr in dir(config):
      attr_value = getattr(config, attr)
      # Filter out multiline strings that are not useful.
      if attr.isupper() and not (isinstance(attr_value, basestring) and
                                 '\n' in attr_value):
        sysinfo['gsutil_config'][attr] = attr_value

    sysinfo['tcp_proc_values'] = {}
    stats_to_check = [
        '/proc/sys/net/core/rmem_default',
        '/proc/sys/net/core/rmem_max',
        '/proc/sys/net/core/wmem_default',
        '/proc/sys/net/core/wmem_max',
        '/proc/sys/net/ipv4/tcp_timestamps',
        '/proc/sys/net/ipv4/tcp_sack',
        '/proc/sys/net/ipv4/tcp_window_scaling',
    ]
    for fname in stats_to_check:
      try:
        with open(fname, 'r') as f:
          value = f.read()
        sysinfo['tcp_proc_values'][os.path.basename(fname)] = value.strip()
      except IOError:
        pass

    self.results['sysinfo'] = sysinfo

  def _DisplayStats(self, trials):
    """Prints out mean, standard deviation, median, and 90th percentile."""
    n = len(trials)
    mean = float(sum(trials)) / n
    stdev = math.sqrt(sum((x - mean)**2 for x in trials) / n)

    print str(n).rjust(6), '',
    print ('%.1f' % (mean * 1000)).rjust(9), '',
    print ('%.1f' % (stdev * 1000)).rjust(12), '',
    print ('%.1f' % (Percentile(trials, 0.5) * 1000)).rjust(11), '',
    print ('%.1f' % (Percentile(trials, 0.9) * 1000)).rjust(11), ''

  def _DisplayResults(self):
    """Displays results collected from diagnostic run."""
    print
    print '=' * 78
    print 'DIAGNOSTIC RESULTS'.center(78)
    print '=' * 78

    if 'latency' in self.results:
      print
      print '-' * 78
      print 'Latency'.center(78)
      print '-' * 78
      print ('Operation       Size  Trials  Mean (ms)  Std Dev (ms)  '
             'Median (ms)  90th % (ms)')
      print ('=========  =========  ======  =========  ============  '
             '===========  ===========')
      for key in sorted(self.results['latency']):
        trials = sorted(self.results['latency'][key])
        op, numbytes = key.split('_')
        numbytes = int(numbytes)
        if op == 'METADATA':
          print 'Metadata'.rjust(9), '',
          print MakeHumanReadable(numbytes).rjust(9), '',
          self._DisplayStats(trials)
        if op == 'DOWNLOAD':
          print 'Download'.rjust(9), '',
          print MakeHumanReadable(numbytes).rjust(9), '',
          self._DisplayStats(trials)
        if op == 'UPLOAD':
          print 'Upload'.rjust(9), '',
          print MakeHumanReadable(numbytes).rjust(9), '',
          self._DisplayStats(trials)
        if op == 'DELETE':
          print 'Delete'.rjust(9), '',
          print MakeHumanReadable(numbytes).rjust(9), '',
          self._DisplayStats(trials)

    if 'write_throughput' in self.results:
      print
      print '-' * 78
      print 'Write Throughput'.center(78)
      print '-' * 78
      write_thru = self.results['write_throughput']
      print 'Copied a %s file %d times for a total transfer size of %s.' % (
          MakeHumanReadable(write_thru['file_size']),
          write_thru['num_copies'],
          MakeHumanReadable(write_thru['total_bytes_copied']))
      print 'Write throughput: %s/s.' % (
          MakeBitsHumanReadable(write_thru['bytes_per_second'] * 8))

    if 'read_throughput' in self.results:
      print
      print '-' * 78
      print 'Read Throughput'.center(78)
      print '-' * 78
      read_thru = self.results['read_throughput']
      print 'Copied a %s file %d times for a total transfer size of %s.' % (
          MakeHumanReadable(read_thru['file_size']),
          read_thru['num_times'],
          MakeHumanReadable(read_thru['total_bytes_copied']))
      print 'Read throughput: %s/s.' % (
          MakeBitsHumanReadable(read_thru['bytes_per_second'] * 8))

    if 'sysinfo' in self.results:
      print
      print '-' * 78
      print 'System Information'.center(78)
      print '-' * 78
      info = self.results['sysinfo']
      print 'IP Address: \n  %s' % info['ip_address']
      print 'Temporary Directory: \n  %s' % info['tempdir']
      print 'Bucket URI: \n  %s' % self.results['bucket_uri']
      print 'gsutil Version: \n  %s' % self.results.get('gsutil_version',
                                                        'Unknown')
      print 'boto Version: \n  %s' % self.results.get('boto_version', 'Unknown')

      if 'gmt_timestamp' in info:
        ts_string = info['gmt_timestamp']
        timetuple = None
        try:
          # Convert RFC 2822 string to Linux timestamp.
          timetuple = time.strptime(ts_string, '%a, %d %b %Y %H:%M:%S +0000')
        except ValueError:
          pass

        if timetuple:
          # Converts the GMT time tuple to local Linux timestamp.
          localtime = calendar.timegm(timetuple)
          localdt = datetime.datetime.fromtimestamp(localtime)
          print 'Measurement time: \n %s' % localdt.strftime(
              '%Y-%m-%d %I-%M-%S %p %Z')

      print 'Google Server: \n  %s' % info['googserv_route']
      print ('Google Server IP Addresses: \n  %s' %
             ('\n  '.join(info['googserv_ips'])))
      print ('Google Server Hostnames: \n  %s' %
             ('\n  '.join(info['googserv_hostnames'])))
      print 'Google DNS thinks your IP is: \n  %s' % info['dns_o-o_ip']
      print 'CPU Count: \n  %s' % info['cpu_count']
      print 'CPU Load Average: \n  %s' % info['load_avg']
      try:
        print ('Total Memory: \n  %s' %
               MakeHumanReadable(info['meminfo']['mem_total']))
        # Free memory is really MemFree + Buffers + Cached.
        print 'Free Memory: \n  %s' % MakeHumanReadable(
            info['meminfo']['mem_free'] +
            info['meminfo']['mem_buffers'] +
            info['meminfo']['mem_cached'])
      except TypeError:
        pass

      netstat_after = info['netstat_end']
      netstat_before = info['netstat_start']
      for tcp_type in ('sent', 'received', 'retransmit'):
        try:
          delta = (netstat_after['tcp_%s' % tcp_type] -
                   netstat_before['tcp_%s' % tcp_type])
          print 'TCP segments %s during test:\n  %d' % (tcp_type, delta)
        except TypeError:
          pass

      if 'disk_counters_end' in info and 'disk_counters_start' in info:
        print 'Disk Counter Deltas:\n',
        disk_after = info['disk_counters_end']
        disk_before = info['disk_counters_start']
        print '', 'disk'.rjust(6),
        for colname in ['reads', 'writes', 'rbytes', 'wbytes', 'rtime',
                        'wtime']:
          print colname.rjust(8),
        print
        for diskname in sorted(disk_after):
          before = disk_before[diskname]
          after = disk_after[diskname]
          (reads1, writes1, rbytes1, wbytes1, rtime1, wtime1) = before
          (reads2, writes2, rbytes2, wbytes2, rtime2, wtime2) = after
          print '', diskname.rjust(6),
          deltas = [reads2-reads1, writes2-writes1, rbytes2-rbytes1,
                    wbytes2-wbytes1, rtime2-rtime1, wtime2-wtime1]
          for delta in deltas:
            print str(delta).rjust(8),
          print

      if 'tcp_proc_values' in info:
        print 'TCP /proc values:\n',
        for item in info['tcp_proc_values'].iteritems():
          print '   %s = %s' % item

      if 'boto_https_enabled' in info:
        print 'Boto HTTPS Enabled: \n  %s' % info['boto_https_enabled']

    if 'request_errors' in self.results and 'total_requests' in self.results:
      print
      print '-' * 78
      print 'In-Process HTTP Statistics'.center(78)
      print '-' * 78
      total = int(self.results['total_requests'])
      numerrors = int(self.results['request_errors'])
      numbreaks = int(self.results['connection_breaks'])
      availability = (((total - numerrors) / float(total)) * 100
                      if total > 0 else 100)
      print 'Total HTTP requests made: %d' % total
      print 'HTTP 5xx errors: %d' % numerrors
      print 'HTTP connections broken: %d' % numbreaks
      print 'Availability: %.7g%%' % availability
      if 'error_responses_by_code' in self.results:
        sorted_codes = sorted(
            self.results['error_responses_by_code'].iteritems())
        if sorted_codes:
          print 'Error responses by code:'
          print '\n'.join('  %s: %s' % c for c in sorted_codes)

    if self.output_file:
      with open(self.output_file, 'w') as f:
        json.dump(self.results, f, indent=2)
      print
      print "Output file written to '%s'." % self.output_file

    print

  def _ParsePositiveInteger(self, val, msg):
    """Tries to convert val argument to a positive integer.

    Args:
      val: The value (as a string) to convert to a positive integer.
      msg: The error message to place in the CommandException on an error.

    Returns:
      A valid positive integer.

    Raises:
      CommandException: If the supplied value is not a valid positive integer.
    """
    try:
      val = int(val)
      if val < 1:
        raise CommandException(msg)
      return val
    except ValueError:
      raise CommandException(msg)

  def _ParseArgs(self):
    """Parses arguments for perfdiag command."""
    # From -n.
    self.num_iterations = 5
    # From -c.
    self.processes = 1
    # From -k.
    self.threads = 1
    # From -s.
    self.thru_filesize = 1048576
    # From -t.
    self.diag_tests = self.ALL_DIAG_TESTS
    # From -o.
    self.output_file = None
    # From -i.
    self.input_file = None
    # From -m.
    self.metadata_keys = {}

    if self.sub_opts:
      for o, a in self.sub_opts:
        if o == '-n':
          self.num_iterations = self._ParsePositiveInteger(
              a, 'The -n parameter must be a positive integer.')
        if o == '-c':
          self.processes = self._ParsePositiveInteger(
              a, 'The -c parameter must be a positive integer.')
        if o == '-k':
          self.threads = self._ParsePositiveInteger(
              a, 'The -k parameter must be a positive integer.')
        if o == '-s':
          try:
            self.thru_filesize = HumanReadableToBytes(a)
          except ValueError:
            raise CommandException('Invalid -s parameter.')
          if self.thru_filesize > (20 * 1024 ** 3):  # Max 20 GB.
            raise CommandException(
                'Maximum throughput file size parameter (-s) is 20GB.')
        if o == '-t':
          self.diag_tests = []
          for test_name in a.strip().split(','):
            if test_name.lower() not in self.ALL_DIAG_TESTS:
              raise CommandException("List of test names (-t) contains invalid "
                                     "test name '%s'." % test_name)
            self.diag_tests.append(test_name)
        if o == '-m':
          pieces = a.split(':')
          if len(pieces) != 2:
            raise CommandException(
                "Invalid metadata key-value combination '%s'." % a)
          key, value = pieces
          self.metadata_keys[key] = value
        if o == '-o':
          self.output_file = os.path.abspath(a)
        if o == '-i':
          self.input_file = os.path.abspath(a)
          if not os.path.isfile(self.input_file):
            raise CommandException("Invalid input file (-i): '%s'." % a)
          try:
            with open(self.input_file, 'r') as f:
              self.results = json.load(f)
              self.logger.info("Read input file: '%s'.", self.input_file)
          except ValueError:
            raise CommandException("Could not decode input file (-i): '%s'." %
                                   a)
          return

    if not self.args:
      raise CommandException('Wrong number of arguments for "perfdiag" '
                             'command.')

    self.provider = StorageUrlFromString(self.args[0]).scheme
    self.bucket_url = StorageUrlFromString(self.args[0])
    if not (self.bucket_url.IsCloudUrl() and self.bucket_url.IsBucket()):
      raise CommandException('The perfdiag command requires a URL that '
                             'specifies a bucket.\n"%s" is not '
                             'valid.' % self.args[0])
    # Ensure the bucket exists.
    self.gsutil_api.GetBucket(self.bucket_url.bucket_name,
                              provider=self.bucket_url.scheme,
                              fields=['id'])
    self.exceptions = []
    self.exceptions.append(ServiceException)

  # Command entry point.
  def RunCommand(self):
    """Called by gsutil when the command is being invoked."""
    self._ParseArgs()

    if self.input_file:
      self._DisplayResults()
      return 0

    # We turn off retries in the underlying boto library because the
    # _RunOperation function handles errors manually so it can count them.
    boto.config.set('Boto', 'num_retries', '0')

    self.logger.info(
        'Number of iterations to run: %d\n'
        'Base bucket URI: %s\n'
        'Number of processes: %d\n'
        'Number of threads: %d\n'
        'Throughput file size: %s\n'
        'Diagnostics to run: %s',
        self.num_iterations,
        self.bucket_url,
        self.processes,
        self.threads,
        MakeHumanReadable(self.thru_filesize),
        (', '.join(self.diag_tests)))

    try:
      self._SetUp()

      # Collect generic system info.
      self._CollectSysInfo()
      # Collect netstat info and disk counters before tests (and again later).
      self.results['sysinfo']['netstat_start'] = self._GetTcpStats()
      if IS_LINUX:
        self.results['sysinfo']['disk_counters_start'] = self._GetDiskCounters()
      # Record bucket URL.
      self.results['bucket_uri'] = str(self.bucket_url)
      self.results['json_format'] = 'perfdiag'
      self.results['metadata'] = self.metadata_keys

      if 'lat' in self.diag_tests:
        self._RunLatencyTests()
      if 'rthru' in self.diag_tests:
        self._RunReadThruTests()
      if 'wthru' in self.diag_tests:
        self._RunWriteThruTests()

      # Collect netstat info and disk counters after tests.
      self.results['sysinfo']['netstat_end'] = self._GetTcpStats()
      if IS_LINUX:
        self.results['sysinfo']['disk_counters_end'] = self._GetDiskCounters()

      self.results['total_requests'] = self.total_requests
      self.results['request_errors'] = self.request_errors
      self.results['error_responses_by_code'] = self.error_responses_by_code
      self.results['connection_breaks'] = self.connection_breaks
      self.results['gsutil_version'] = gslib.VERSION
      self.results['boto_version'] = boto.__version__

      self._DisplayResults()
    finally:
      self._TearDown()

    return 0


class UploadObjectTuple(object):
  """Picklable tuple with necessary metadata for an insert object call."""

  def __init__(self, bucket_name, object_name, md5=None):
    self.bucket_name = bucket_name
    self.object_name = object_name
    self.md5 = md5


def StorageUrlToUploadObjectMetadata(storage_url):
  if storage_url.IsCloudUrl() and storage_url.IsObject():
    upload_target = apitools_messages.Object()
    upload_target.name = storage_url.object_name
    upload_target.bucket = storage_url.bucket_name
    return upload_target
  else:
    raise CommandException('Non-cloud URL upload target %s was created in '
                           'perfdiag implemenation.' % storage_url)
