# -*- coding: utf-8 -*-
# Copyright 2016 Google Inc. All Rights Reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish, dis-
# tribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the fol-
# lowing conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABIL-
# ITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT
# SHALL THE AUTHOR BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.
"""Tests for gsutil UI functions."""

from __future__ import absolute_import


from hashlib import md5
import os
import pickle
import Queue
import StringIO

import crcmod
from gslib.copy_helper import PARALLEL_UPLOAD_STATIC_SALT
from gslib.copy_helper import PARALLEL_UPLOAD_TEMP_NAMESPACE
from gslib.cs_api_map import ApiSelector
from gslib.parallel_tracker_file import ObjectFromTracker
from gslib.parallel_tracker_file import WriteParallelUploadTrackerFile
from gslib.parallelism_framework_util import ZERO_TASKS_TO_DO_ARGUMENT
from gslib.storage_url import StorageUrlFromString
import gslib.tests.testcase as testcase
from gslib.tests.testcase.integration_testcase import SkipForS3
from gslib.tests.util import HaltingCopyCallbackHandler
from gslib.tests.util import HaltOneComponentCopyCallbackHandler
from gslib.tests.util import ObjectToURI as suri
from gslib.tests.util import SetBotoConfigForTest
from gslib.tests.util import TEST_ENCRYPTION_KEY1
from gslib.tests.util import TEST_ENCRYPTION_KEY2
from gslib.tests.util import unittest
from gslib.thread_message import FileMessage
from gslib.thread_message import ProducerThreadMessage
from gslib.thread_message import ProgressMessage
from gslib.thread_message import SeekAheadMessage
from gslib.tracker_file import DeleteTrackerFile
from gslib.tracker_file import GetSlicedDownloadTrackerFilePaths
from gslib.tracker_file import GetTrackerFilePath
from gslib.tracker_file import TrackerFileType
from gslib.ui_controller import MainThreadUIQueue
from gslib.ui_controller import UIController
from gslib.ui_controller import UIThread
from gslib.util import HumanReadableWithDecimalPlaces
from gslib.util import MakeHumanReadable
from gslib.util import ONE_KIB
from gslib.util import START_CALLBACK_PER_BYTES
from gslib.util import UsingCrcmodExtension
from gslib.util import UTF8

DOWNLOAD_SIZE = 300
UPLOAD_SIZE = 400
# Ensures at least one progress callback is made
HALT_SIZE = START_CALLBACK_PER_BYTES * 2
# After waiting this long, assume the UIThread is hung.
THREAD_WAIT_TIME = 5


def JoinThreadAndRaiseOnTimeout(ui_thread, thread_wait_time=THREAD_WAIT_TIME):
  """Joins the ui_thread and ensures it has not timed out.

  Args:
    ui_thread: the UIThread to be joined.
    thread_wait_time: the time to wait to join
  Raises:
    Exception: Warns UIThread is still alive.
  """
  ui_thread.join(thread_wait_time)
  if ui_thread.isAlive():
    raise Exception('UIThread is still alive')


def CheckUiOutputWithMFlag(test_case, content, num_objects, total_size):
  """Checks if the UI output behaves as expected with the -m flag enabled.

  Args:
    test_case: Testcase used to maintain the same assert structure.
    content: The output provided by the UI.
    num_objects: The number of objects processed.
    total_size: The total size transferred in the operation.
  """
  # We must have transferred 100% of our data.
  test_case.assertIn('100% Done', content)
  # All files should be completed.
  files_completed_string = str(num_objects) + '/' + str(num_objects)
  test_case.assertIn(files_completed_string + ' files', content)
  # The total_size must also been successfully transferred.
  total_size_string = HumanReadableWithDecimalPlaces(total_size)
  test_case.assertIn(total_size_string + '/' + total_size_string, content)


def CheckUiOutputWithNoMFlag(test_case, content, num_objects, total_size):
  """Checks if the UI output behaves as expected with the -m flag not enabled.

  Args:
    test_case: Testcase used to maintain the same assert structure.
    content: The output provided by the UI.
    num_objects: The number of objects processed.
    total_size: The total size transferred in the operation.
  """
  # All files should be completed.
  files_completed_string = str(num_objects)
  test_case.assertIn(files_completed_string + ' files', content)
  # The total_size must also been successfully transferred.
  total_size_string = HumanReadableWithDecimalPlaces(total_size)
  test_case.assertIn(total_size_string + '/' + total_size_string, content)


def CheckBrokenUiOutputWithMFlag(test_case, content, num_objects, total_size):
  """Checks if the UI output fails as expected with the -m flag enabled.

  Args:
    test_case: Testcase used to maintain the same assert structure.
    content: The output provided by the UI.
    num_objects: The number of objects processed.
    total_size: The total size transferred in the operation.
  """
  # We must not have begun our UI with 0% of our data transferred.
  test_case.assertIn('0% Done', content)
  # We must not have transferred 100% of our data.
  test_case.assertNotIn('100% Done', content)
  # 0 files should be completed.
  no_files_string = str(0) + '/' + str(num_objects)
  test_case.assertIn(no_files_string + ' files', content)
  # We cannot have completed a file.
  files_completed_string = str(num_objects) + '/' + str(num_objects)
  test_case.assertNotIn(files_completed_string + ' files', content)

  total_size_string = HumanReadableWithDecimalPlaces(total_size)
  zero = HumanReadableWithDecimalPlaces(0)
  # Zero bytes must have been transferred in the beginning.
  test_case.assertIn(zero + '/' + total_size_string, content)
  # The total_size must have not been successfully transferred.
  test_case.assertNotIn(total_size_string + '/' + total_size_string, content)


def CheckBrokenUiOutputWithNoMFlag(test_case, content, num_objects, total_size):
  """Checks if the UI output fails as expected with the -m flag not enabled.

  Args:
    test_case: Testcase used to maintain the same assert structure.
    content: The output provided by the UI.
    num_objects: The number of objects processed.
    total_size: The total size transferred in the operation.
  """
  # 0 files should be completed.
  no_files_string = str(0)
  test_case.assertIn(no_files_string + ' files', content)
  # We cannot have completed a file.
  files_completed_string = str(num_objects)
  test_case.assertNotIn(files_completed_string + ' files', content)

  total_size_string = HumanReadableWithDecimalPlaces(total_size)
  zero = HumanReadableWithDecimalPlaces(0)
  # Zero bytes must have been transferred in the beginning.
  test_case.assertIn(zero + '/' + total_size_string, content)
  # The total_size must have not been successfully transferred.
  test_case.assertNotIn(total_size_string + '/' + total_size_string, content)


class TestUi(testcase.GsUtilIntegrationTestCase):
  """Integration tests for UI functions."""

  def test_ui_download_single_objects_with_m_flag(self):
    """Tests UI for a single object download with the -m flag enabled.

    This test indirectly tests the correctness of ProducerThreadMessage in the
    UIController.
    """
    bucket_uri = self.CreateBucket()
    file_contents = 'd' * DOWNLOAD_SIZE
    object_uri = self.CreateObject(bucket_uri=bucket_uri, object_name='foo',
                                   contents=file_contents)
    fpath = self.CreateTempFile()
    stderr = self.RunGsUtil(['-m', 'cp', suri(object_uri), fpath],
                            return_stderr=True)
    CheckUiOutputWithMFlag(self, stderr, 1, DOWNLOAD_SIZE)

  def test_ui_download_single_objects_with_no_m_flag(self):
    """Tests UI for a single object download with the -m flag not enabled.

    The UI should behave differently from the -m flag option because in the
    latter we have a ProducerThreadMessage that allows us to know our progress
    percentage and total number of files.
    """
    bucket_uri = self.CreateBucket()
    file_contents = 'd' * DOWNLOAD_SIZE
    object_uri = self.CreateObject(bucket_uri=bucket_uri, object_name='foo',
                                   contents=file_contents)
    fpath = self.CreateTempFile()
    stderr = self.RunGsUtil(['cp', suri(object_uri), fpath],
                            return_stderr=True)
    CheckUiOutputWithNoMFlag(self, stderr, 1, DOWNLOAD_SIZE)

  def test_ui_upload_single_object_with_m_flag(self):
    """Tests UI for a single object upload with -m flag enabled.

    This test indirectly tests the correctness of ProducerThreadMessage in the
    UIController.
    """
    bucket_uri = self.CreateBucket()
    file_contents = 'u' * UPLOAD_SIZE
    fpath = self.CreateTempFile(file_name='sample-file.txt',
                                contents=file_contents)
    stderr = self.RunGsUtil(['-m', 'cp', suri(fpath), suri(bucket_uri)],
                            return_stderr=True)

    CheckUiOutputWithMFlag(self, stderr, 1, UPLOAD_SIZE)

  def test_ui_upload_single_object_with_no_m_flag(self):
    """Tests UI for a single object upload with -m flag not enabled.

    The UI should behave differently from the -m flag option because in the
    latter we have a ProducerThreadMessage that allows us to know our progress
    percentage and total number of files.
    """
    bucket_uri = self.CreateBucket()
    file_contents = 'u' * UPLOAD_SIZE
    fpath = self.CreateTempFile(file_name='sample-file.txt',
                                contents=file_contents)
    stderr = self.RunGsUtil(['cp', suri(fpath), suri(bucket_uri)],
                            return_stderr=True)

    CheckUiOutputWithNoMFlag(self, stderr, 1, UPLOAD_SIZE)

  def test_ui_download_mutliple_objects_with_m_flag(self):
    """Tests UI for a multiple object download with the -m flag enabled.

    This test indirectly tests the correctness of ProducerThreadMessage in the
    UIController.
    """
    bucket_uri = self.CreateBucket()
    num_objects = 7
    argument_list = ['-m', 'cp']
    total_size = 0
    for i in range(num_objects):
      file_size = DOWNLOAD_SIZE / 3
      file_contents = 'd' * file_size
      object_uri = self.CreateObject(bucket_uri=bucket_uri,
                                     object_name='foo' + str(i),
                                     contents=file_contents)
      total_size += file_size
      argument_list.append(suri(object_uri))

    fpath = self.CreateTempDir()
    argument_list.append(fpath)
    stderr = self.RunGsUtil(argument_list,
                            return_stderr=True)

    CheckUiOutputWithMFlag(self, stderr, num_objects, total_size)

  def test_ui_download_mutliple_objects_with_no_m_flag(self):
    """Tests UI for a multiple object download with the -m flag not enabled.

    The UI should behave differently from the -m flag option because in the
    latter we have a ProducerThreadMessage that allows us to know our progress
    percentage and total number of files.
    """
    bucket_uri = self.CreateBucket()
    num_objects = 7
    argument_list = ['cp']
    total_size = 0
    for i in range(num_objects):
      file_size = DOWNLOAD_SIZE / 3
      file_contents = 'd' * file_size
      object_uri = self.CreateObject(bucket_uri=bucket_uri,
                                     object_name='foo' + str(i),
                                     contents=file_contents)
      total_size += file_size
      argument_list.append(suri(object_uri))

    fpath = self.CreateTempDir()
    argument_list.append(fpath)
    stderr = self.RunGsUtil(argument_list,
                            return_stderr=True)

    CheckUiOutputWithNoMFlag(self, stderr, num_objects, total_size)

  def test_ui_upload_mutliple_objects_with_m_flag(self):
    """Tests UI for a multiple object upload with -m flag enabled.

    This test indirectly tests the correctness of ProducerThreadMessage in the
    UIController.
    """
    bucket_uri = self.CreateBucket()
    num_objects = 7
    argument_list = ['-m', 'cp']
    total_size = 0
    for i in range(num_objects):
      file_size = UPLOAD_SIZE / 3
      file_contents = 'u' * file_size
      fpath = self.CreateTempFile(file_name='foo' + str(i),
                                  contents=file_contents)
      total_size += file_size
      argument_list.append(suri(fpath))

    argument_list.append(suri(bucket_uri))
    stderr = self.RunGsUtil(argument_list,
                            return_stderr=True)

    CheckUiOutputWithMFlag(self, stderr, num_objects, total_size)

  def test_ui_upload_mutliple_objects_with_no_m_flag(self):
    """Tests UI for a multiple object upload with -m flag not enabled.

    The UI should behave differently from the -m flag option because in the
    latter we have a ProducerThreadMessage that allows us to know our progress
    percentage and total number of files.
    """
    bucket_uri = self.CreateBucket()
    num_objects = 7
    argument_list = ['cp']
    total_size = 0
    for i in range(num_objects):
      file_size = UPLOAD_SIZE / 3
      file_contents = 'u' * file_size
      fpath = self.CreateTempFile(file_name='foo' + str(i),
                                  contents=file_contents)
      total_size += file_size
      argument_list.append(suri(fpath))

    argument_list.append(suri(bucket_uri))
    stderr = self.RunGsUtil(argument_list,
                            return_stderr=True)

    CheckUiOutputWithNoMFlag(self, stderr, num_objects, total_size)

  @SkipForS3('No resumable upload support for S3.')
  def test_ui_resumable_upload_break_with_m_flag(self):
    """Tests UI for upload resumed after a connection break with -m flag.

    This was adapted from test_cp_resumable_upload_break.
    """
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents='a' * HALT_SIZE)
    boto_config_for_test = [
        ('GSUtil', 'resumable_threshold', str(ONE_KIB)),
        ('GSUtil', 'parallel_composite_upload_component_size', str(ONE_KIB))]
    test_callback_file = self.CreateTempFile(
        contents=pickle.dumps(HaltingCopyCallbackHandler(True, 5)))

    with SetBotoConfigForTest(boto_config_for_test):
      stderr = self.RunGsUtil(['-m', 'cp', '--testcallbackfile',
                               test_callback_file,
                               fpath, suri(bucket_uri)],
                              expected_status=1, return_stderr=True)
      self.assertIn('Artifically halting upload', stderr)
      CheckBrokenUiOutputWithMFlag(self, stderr, 1, HALT_SIZE)
      stderr = self.RunGsUtil(['-m', 'cp', fpath, suri(bucket_uri)],
                              return_stderr=True)
      self.assertIn('Resuming upload', stderr)
      CheckUiOutputWithMFlag(self, stderr, 1, HALT_SIZE)

  @SkipForS3('No resumable upload support for S3.')
  def test_ui_resumable_upload_break_with_no_m_flag(self):
    """Tests UI for upload resumed after a connection break with no -m flag.

    This was adapted from test_cp_resumable_upload_break.
    """
    bucket_uri = self.CreateBucket()
    fpath = self.CreateTempFile(contents='a' * HALT_SIZE)
    boto_config_for_test = [
        ('GSUtil', 'resumable_threshold', str(ONE_KIB)),
        ('GSUtil', 'parallel_composite_upload_component_size', str(ONE_KIB))]
    test_callback_file = self.CreateTempFile(
        contents=pickle.dumps(HaltingCopyCallbackHandler(True, 5)))

    with SetBotoConfigForTest(boto_config_for_test):
      stderr = self.RunGsUtil(['cp', '--testcallbackfile', test_callback_file,
                               fpath, suri(bucket_uri)],
                              expected_status=1, return_stderr=True)
      self.assertIn('Artifically halting upload', stderr)
      CheckBrokenUiOutputWithNoMFlag(self, stderr, 1, HALT_SIZE)
      stderr = self.RunGsUtil(['cp', fpath, suri(bucket_uri)],
                              return_stderr=True)
      self.assertIn('Resuming upload', stderr)
      CheckUiOutputWithNoMFlag(self, stderr, 1, HALT_SIZE)

  def _test_ui_resumable_download_break_helper(self, boto_config,
                                               gsutil_flags=None):
    """Helper function for testing UI on a resumable download break.

    This was adapted from _test_cp_resumable_download_break_helper.

    Args:
      boto_config: List of boto configuration tuples for use with
          SetBotoConfigForTest.
      gsutil_flags: List of flags to run gsutil with, or None.
    """
    if not gsutil_flags:
      gsutil_flags = []
    bucket_uri = self.CreateBucket()
    file_contents = 'a' * HALT_SIZE
    object_uri = self.CreateObject(bucket_uri=bucket_uri, object_name='foo',
                                   contents=file_contents)
    fpath = self.CreateTempFile()
    test_callback_file = self.CreateTempFile(
        contents=pickle.dumps(HaltingCopyCallbackHandler(False, 5)))

    with SetBotoConfigForTest(boto_config):
      gsutil_args = (gsutil_flags + ['cp', '--testcallbackfile',
                                     test_callback_file,
                                     suri(object_uri), fpath])
      stderr = self.RunGsUtil(gsutil_args, expected_status=1,
                              return_stderr=True)
      self.assertIn('Artifically halting download.', stderr)
      if '-m' in gsutil_args:
        CheckBrokenUiOutputWithMFlag(self, stderr, 1, HALT_SIZE)
      else:
        CheckBrokenUiOutputWithNoMFlag(self, stderr, 1, HALT_SIZE)

      tracker_filename = GetTrackerFilePath(
          StorageUrlFromString(fpath), TrackerFileType.DOWNLOAD, self.test_api)
      self.assertTrue(os.path.isfile(tracker_filename))
      gsutil_args = gsutil_flags + ['cp', suri(object_uri), fpath]
      stderr = self.RunGsUtil(gsutil_args, return_stderr=True)
      self.assertIn('Resuming download', stderr)
    with open(fpath, 'r') as f:
      self.assertEqual(f.read(), file_contents, 'File contents differ')
    if '-m' in gsutil_flags:
      CheckUiOutputWithMFlag(self, stderr, 1, HALT_SIZE)
    else:
      CheckUiOutputWithNoMFlag(self, stderr, 1, HALT_SIZE)

  def test_ui_resumable_download_break_with_m_flag(self):
    """Tests UI on a resumable download break with -m flag.

    This was adapted from test_cp_resumable_download_break.
    """
    self._test_ui_resumable_download_break_helper(
        [('GSUtil', 'resumable_threshold', str(ONE_KIB))], gsutil_flags=['-m'])

  def test_ui_resumable_download_break_with_no_m_flag(self):
    """Tests UI on a resumable download break with no -m flag.

    This was adapted from test_cp_resumable_download_break.
    """
    self._test_ui_resumable_download_break_helper(
        [('GSUtil', 'resumable_threshold', str(ONE_KIB))])

  def _test_ui_composite_upload_resume_helper(self, gsutil_flags=None):
    """Helps testing UI on a resumable upload with finished components.

    Args:
      gsutil_flags: List of flags to run gsutil with, or None.
    """
    if not gsutil_flags:
      gsutil_flags = []
    bucket_uri = self.CreateBucket()
    dst_url = StorageUrlFromString(suri(bucket_uri, 'foo'))

    file_contents = 'foobar'
    source_file = self.CreateTempFile(
        contents=file_contents, file_name=file_contents)
    src_url = StorageUrlFromString(source_file)

    # Simulate an upload that had occurred by writing a tracker file
    # that points to a previously uploaded component.
    tracker_file_name = GetTrackerFilePath(
        dst_url, TrackerFileType.PARALLEL_UPLOAD, self.test_api, src_url)
    tracker_prefix = '123'

    # Create component 0 to be used in the resume; it must match the name
    # that will be generated in copy_helper, so we use the same scheme.
    encoded_name = (PARALLEL_UPLOAD_STATIC_SALT + source_file).encode(UTF8)
    content_md5 = md5()
    content_md5.update(encoded_name)
    digest = content_md5.hexdigest()
    component_object_name = (tracker_prefix + PARALLEL_UPLOAD_TEMP_NAMESPACE +
                             digest + '_0')

    component_size = 3
    object_uri = self.CreateObject(
        bucket_uri=bucket_uri, object_name=component_object_name,
        contents=file_contents[:component_size])
    existing_component = ObjectFromTracker(component_object_name,
                                           str(object_uri.generation))
    existing_components = [existing_component]

    WriteParallelUploadTrackerFile(
        tracker_file_name, tracker_prefix, existing_components)

    try:
      # Now "resume" the upload.
      with SetBotoConfigForTest([
          ('GSUtil', 'parallel_composite_upload_threshold', '1'),
          ('GSUtil', 'parallel_composite_upload_component_size',
           str(component_size))]):
        gsutil_args = (gsutil_flags +
                       ['cp', source_file, suri(bucket_uri, 'foo')])
        stderr = self.RunGsUtil(gsutil_args,
                                return_stderr=True)
        self.assertIn('Found 1 existing temporary components to reuse.', stderr)
        self.assertFalse(
            os.path.exists(tracker_file_name),
            'Tracker file %s should have been deleted.' % tracker_file_name)
        read_contents = self.RunGsUtil(['cat', suri(bucket_uri, 'foo')],
                                       return_stdout=True)
        self.assertEqual(read_contents, file_contents)
        if '-m' in gsutil_flags:
          CheckUiOutputWithMFlag(self, stderr, 1, len(file_contents))
        else:
          CheckUiOutputWithNoMFlag(self, stderr, 1, len(file_contents))
    finally:
      # Clean up if something went wrong.
      DeleteTrackerFile(tracker_file_name)

  @SkipForS3('No resumable upload support for S3.')
  def test_ui_composite_upload_resume_with_m_flag(self):
    """Tests UI on a resumable upload with finished components and -m flag."""
    self._test_ui_composite_upload_resume_helper(gsutil_flags=['-m'])

  @SkipForS3('No resumable upload support for S3.')
  def test_ui_composite_upload_resume_with_no_m_flag(self):
    """Tests UI on a resumable upload with finished components and no -m flag.
    """
    self._test_ui_composite_upload_resume_helper()

  @unittest.skipUnless(UsingCrcmodExtension(crcmod),
                       'Sliced download requires fast crcmod.')
  @SkipForS3('No sliced download support for S3.')
  def _test_ui_sliced_download_partial_resume_helper(self, gsutil_flags=None):
    """Helps testing UI for sliced download with some finished components.

    This was adapted from test_sliced_download_partial_resume_helper.

    Args:
      gsutil_flags: List of flags to run gsutil with, or None.
    """
    if not gsutil_flags:
      gsutil_flags = []
    bucket_uri = self.CreateBucket()
    object_uri = self.CreateObject(bucket_uri=bucket_uri, object_name='foo',
                                   contents='abc' * HALT_SIZE)
    fpath = self.CreateTempFile()
    test_callback_file = self.CreateTempFile(
        contents=pickle.dumps(HaltOneComponentCopyCallbackHandler(5)))

    boto_config_for_test = [
        ('GSUtil', 'resumable_threshold', str(HALT_SIZE)),
        ('GSUtil', 'sliced_object_download_threshold', str(HALT_SIZE)),
        ('GSUtil', 'sliced_object_download_max_components', '3')]

    with SetBotoConfigForTest(boto_config_for_test):
      gsutil_args = gsutil_flags + ['cp', '--testcallbackfile',
                                    test_callback_file, suri(object_uri),
                                    suri(fpath)]

      stderr = self.RunGsUtil(gsutil_args, return_stderr=True,
                              expected_status=1)
      if '-m' in gsutil_args:
        CheckBrokenUiOutputWithMFlag(self, stderr, 1, len('abc') * HALT_SIZE)
      else:
        CheckBrokenUiOutputWithNoMFlag(self, stderr, 1, len('abc') * HALT_SIZE)
      # Each tracker file should exist.
      tracker_filenames = GetSlicedDownloadTrackerFilePaths(
          StorageUrlFromString(fpath), self.test_api)
      for tracker_filename in tracker_filenames:
        self.assertTrue(os.path.isfile(tracker_filename))
      gsutil_args = gsutil_flags + ['cp', suri(object_uri), fpath]

      stderr = self.RunGsUtil(gsutil_args, return_stderr=True)
      self.assertIn('Resuming download', stderr)
      self.assertIn('Download already complete', stderr)

      # Each tracker file should have been deleted.
      tracker_filenames = GetSlicedDownloadTrackerFilePaths(
          StorageUrlFromString(fpath), self.test_api)
      for tracker_filename in tracker_filenames:
        self.assertFalse(os.path.isfile(tracker_filename))

      with open(fpath, 'r') as f:
        self.assertEqual(f.read(), 'abc' * HALT_SIZE,
                         'File contents differ')
      if '-m' in gsutil_args:
        CheckUiOutputWithMFlag(self, stderr, 1, len('abc') * HALT_SIZE)
      else:
        CheckUiOutputWithNoMFlag(self, stderr, 1, len('abc') * HALT_SIZE)

  @SkipForS3('No resumable upload support for S3.')
  def test_ui_sliced_download_partial_resume_helper_with_m_flag(self):
    """Tests UI on a resumable download with finished components and -m flag.
    """
    self._test_ui_sliced_download_partial_resume_helper(gsutil_flags=['-m'])

  @SkipForS3('No resumable upload support for S3.')
  def _test_ui_sliced_download_partial_resume_helper_with_no_m_flag(self):
    """Tests UI on a resumable upload with finished components and no -m flag.
    """
    self._test_ui_sliced_download_partial_resume_helper()

  def test_ui_hash_mutliple_objects_with_no_m_flag(self):
    """Tests UI for a multiple object hashing with no -m flag enabled.

    This test indirectly tests the correctness of ProducerThreadMessage in the
    UIController.
    """
    num_objects = 7
    argument_list = ['hash']
    total_size = 0
    for i in range(num_objects):
      file_size = UPLOAD_SIZE / 3
      file_contents = 'u' * file_size
      fpath = self.CreateTempFile(file_name='foo' + str(i),
                                  contents=file_contents)
      total_size += file_size
      argument_list.append(suri(fpath))

    stderr = self.RunGsUtil(argument_list,
                            return_stderr=True)
    CheckUiOutputWithNoMFlag(self, stderr, num_objects, total_size)

  def test_ui_rewrite_with_m_flag(self):
    """Tests UI output for rewrite and -m flag enabled.

    Adapted from test_rewrite_stdin_args.
    """
    if self.test_api == ApiSelector.XML:
      return unittest.skip('Rewrite API is only supported in JSON.')
    object_uri = self.CreateObject(contents='bar',
                                   encryption_key=TEST_ENCRYPTION_KEY1)
    stdin_arg = suri(object_uri)

    boto_config_for_test = [
        ('GSUtil', 'encryption_key', TEST_ENCRYPTION_KEY2),
        ('GSUtil', 'decryption_key1', TEST_ENCRYPTION_KEY1)]
    with SetBotoConfigForTest(boto_config_for_test):
      stderr = self.RunGsUtil(['-m', 'rewrite', '-k', '-I'], stdin=stdin_arg,
                              return_stderr=True)
    self.AssertObjectUsesEncryptionKey(stdin_arg, TEST_ENCRYPTION_KEY2)
    num_objects = 1
    total_size = len('bar')
    CheckUiOutputWithMFlag(self, stderr, num_objects, total_size)

  def test_ui_rewrite_with_no_m_flag(self):
    """Tests UI output for rewrite and -m flag not enabled.

    Adapted from test_rewrite_stdin_args.
    """
    if self.test_api == ApiSelector.XML:
      return unittest.skip('Rewrite API is only supported in JSON.')
    object_uri = self.CreateObject(contents='bar',
                                   encryption_key=TEST_ENCRYPTION_KEY1)
    stdin_arg = suri(object_uri)

    boto_config_for_test = [
        ('GSUtil', 'encryption_key', TEST_ENCRYPTION_KEY2),
        ('GSUtil', 'decryption_key1', TEST_ENCRYPTION_KEY1)]
    with SetBotoConfigForTest(boto_config_for_test):
      stderr = self.RunGsUtil(['rewrite', '-k', '-I'], stdin=stdin_arg,
                              return_stderr=True)
    self.AssertObjectUsesEncryptionKey(stdin_arg, TEST_ENCRYPTION_KEY2)
    num_objects = 1
    total_size = len('bar')
    CheckUiOutputWithNoMFlag(self, stderr, num_objects, total_size)


class TestUiUnitTests(testcase.GsUtilUnitTestCase):
  """Unit tests for UI functions."""

  upload_size = UPLOAD_SIZE
  start_time = 10000

  def test_ui_seek_ahead_message(self):
    """Tests if a seek ahead message is correctly printed."""
    status_queue = Queue.Queue()
    stream = StringIO.StringIO()
    # No time constraints for displaying messages.
    start_time = self.start_time
    ui_controller = UIController(0, 0, 0, 0, start_time)
    ui_thread = UIThread(status_queue, stream, ui_controller)
    num_objects = 10
    total_size = 1024**3
    status_queue.put(SeekAheadMessage(num_objects, total_size, start_time))

    # Adds a file. Because this message was already theoretically processed
    # by the SeekAheadThread, the number of files reported by the UIController
    # should not change.
    fpath = self.CreateTempFile(file_name='sample-file.txt',
                                contents='foo')
    status_queue.put(
        FileMessage(StorageUrlFromString(suri(fpath)), None, start_time + 10,
                    size=UPLOAD_SIZE, message_type=FileMessage.FILE_UPLOAD,
                    finished=False))
    status_queue.put(
        FileMessage(StorageUrlFromString(suri(fpath)), None, start_time + 20,
                    size=UPLOAD_SIZE, message_type=FileMessage.FILE_UPLOAD,
                    finished=True))

    status_queue.put(ZERO_TASKS_TO_DO_ARGUMENT)
    JoinThreadAndRaiseOnTimeout(ui_thread)
    content = stream.getvalue()
    expected_message = (
        'Estimated work for this command: objects: %s, total size: %s\n' %
        (num_objects, MakeHumanReadable(total_size)))
    self.assertIn(expected_message, content)
    # This ensures the SeekAheadMessage did its job.
    self.assertIn('/' + str(num_objects), content)
    # This ensures a FileMessage did not affect the total number of files
    # obtained by the SeekAheadMessage.
    self.assertNotIn('/' + str(num_objects + 1), content)

  def test_ui_empty_list(self):
    """Tests if status queue is empty after processed by UIThread."""
    status_queue = Queue.Queue()
    stream = StringIO.StringIO()
    ui_controller = UIController()
    ui_thread = UIThread(status_queue, stream, ui_controller)
    for i in range(10000):  # pylint: disable=unused-variable
      status_queue.put('foo')
    status_queue.put(ZERO_TASKS_TO_DO_ARGUMENT)
    JoinThreadAndRaiseOnTimeout(ui_thread)
    self.assertEqual(0, status_queue.qsize())

  def test_ui_controller_shared_states(self):
    """Tests that UIController correctly integrates messages.

    This test ensures UIController correctly shares its state, which is used by
    both UIThread and MainThreadUIQueue. There are multiple ways of checking
    that. One such way is to create a ProducerThreadMessage on the
    MainThreadUIQueue, simulate a upload with messages coming from the UIThread,
    and check if the output has the percentage done and number of files
    (both happen only when a ProducerThreadMessage or SeekAheadMessage is
    called).
    """
    ui_thread_status_queue = Queue.Queue()
    stream = StringIO.StringIO()
    # No time constraints for displaying messages.
    start_time = self.start_time
    ui_controller = UIController(0, 0, 0, 0, start_time)
    main_thread_ui_queue = MainThreadUIQueue(stream, ui_controller)
    ui_thread = UIThread(ui_thread_status_queue, stream, ui_controller)
    main_thread_ui_queue.put(ProducerThreadMessage(1, UPLOAD_SIZE,
                                                   start_time, finished=True))
    fpath = self.CreateTempFile(file_name='sample-file.txt',
                                contents='foo')
    ui_thread_status_queue.put(
        FileMessage(StorageUrlFromString(suri(fpath)), None, start_time + 10,
                    size=UPLOAD_SIZE, message_type=FileMessage.FILE_UPLOAD,
                    finished=False))
    ui_thread_status_queue.put(
        FileMessage(StorageUrlFromString(suri(fpath)), None, start_time + 20,
                    size=UPLOAD_SIZE, message_type=FileMessage.FILE_UPLOAD,
                    finished=True))

    ui_thread_status_queue.put(ZERO_TASKS_TO_DO_ARGUMENT)
    JoinThreadAndRaiseOnTimeout(ui_thread)
    content = stream.getvalue()
    CheckUiOutputWithMFlag(self, content, 1, UPLOAD_SIZE)

  def test_ui_throughput_calculation_with_components(self):
    """Tests throughput calculation in the UI.

    This test takes two different values, both with a different size and
    different number of components, and see if throughput behaves as expected.
    """
    status_queue = Queue.Queue()
    stream = StringIO.StringIO()
    # Creates a UIController that has no time constraints for updating info,
    # except for having to wait at least 2 seconds (considering the time
    # informed by the messages) to update the throughput. We use a value
    # slightly smaller than 2 to ensure messages that are 2 seconds apart from
    # one another will be enough to calculate throughput.
    start_time = self.start_time
    ui_controller = UIController(0, 0, 1.99, 0, start_time)
    # We use start_time to have a reasonable set of values for the time messages
    # processed by the UIController. However, the start_time does not influence
    # this test, as the throughput is calculated based on the time
    # difference between two messages, which is fixed in this test.

    ui_thread = UIThread(status_queue, stream, ui_controller)
    fpath1 = self.CreateTempFile(file_name='sample-file.txt',
                                 contents='foo')
    fpath2 = self.CreateTempFile(file_name='sample-file2.txt',
                                 contents='FOO')

    def _CreateFileVariables(alpha, component_number, src_url):
      """Creates size and component_size for a given file."""
      size = 1024**2 * 60 * alpha  # this is 60*alpha MiB
      component_size = size / component_number
      return (size, component_number, component_size, src_url)

    # Note: size1 and size2 do not actually correspond to the actual sizes of
    # fpath1 and fpath2. However, the UIController only uses the size sent on
    # the message, so we should be able to pretend they are much larger on size.
    (size1, component_num_file1, component_size_file1, src_url1) = (
        _CreateFileVariables(1, 3, StorageUrlFromString(suri(fpath1))))

    (size2, component_num_file2, component_size_file2, src_url2) = (
        _CreateFileVariables(10, 4, StorageUrlFromString(suri(fpath2))))

    for file_message_type, component_message_type, operation_name in (
        (FileMessage.FILE_UPLOAD, FileMessage.COMPONENT_TO_UPLOAD, 'Uploading'),
        (FileMessage.FILE_DOWNLOAD, FileMessage.COMPONENT_TO_DOWNLOAD,
         'Downloading')):
      # Testing for uploads and downloads
      status_queue.put(FileMessage(src_url1, None, start_time + 100, size=size1,
                                   message_type=file_message_type))
      status_queue.put(FileMessage(src_url2, None, start_time + 150, size=size2,
                                   message_type=file_message_type))

      for i in range(component_num_file1):
        status_queue.put(
            FileMessage(src_url1, None, start_time + 200 + i,
                        size=component_size_file1, component_num=i,
                        message_type=component_message_type))
      for i in range(component_num_file2):
        status_queue.put(
            FileMessage(src_url2, None, start_time + 250 + i,
                        size=component_size_file2, component_num=i,
                        message_type=component_message_type))

      progress_calls_number = 4
      for j in range(1, progress_calls_number + 1):
        # We will send progress_calls_number ProgressMessages for each
        # component.
        base_start_time = (start_time + 300 +
                           j * (component_num_file1 + component_num_file2))
        for i in range(component_num_file1):
          # Each component has size equal to
          # component_size_file1/progress_calls_number
          status_queue.put(
              ProgressMessage(
                  size1, j * component_size_file1 / progress_calls_number,
                  src_url1, base_start_time + i, component_num=i,
                  operation_name=operation_name))

        for i in range(component_num_file2):
          # Each component has size equal to
          # component_size_file2/progress_calls_number
          status_queue.put(
              ProgressMessage(
                  size2, j * component_size_file2 / progress_calls_number,
                  src_url2, base_start_time + component_num_file1 + i,
                  component_num=i, operation_name=operation_name))

      # Time to finish the components and files.
      for i in range(component_num_file1):
        status_queue.put(
            FileMessage(src_url1, None, start_time + 500 + i,
                        finished=True, size=component_size_file1,
                        component_num=i, message_type=component_message_type))
      for i in range(component_num_file2):
        status_queue.put(
            FileMessage(src_url2, None, start_time + 600 + i,
                        finished=True, size=component_size_file2,
                        component_num=i, message_type=component_message_type))

      status_queue.put(FileMessage(src_url1, None, start_time + 700, size=size1,
                                   finished=True,
                                   message_type=file_message_type))
      status_queue.put(FileMessage(src_url2, None, start_time + 800, size=size2,
                                   finished=True,
                                   message_type=file_message_type))

      status_queue.put(ZERO_TASKS_TO_DO_ARGUMENT)
      JoinThreadAndRaiseOnTimeout(ui_thread)
      content = stream.getvalue()
      # There were 2-second periods when no progress was reported. The
      # throughput here will be 0. We will use HumanReadableWithDecimalPlaces(0)
      # to ensure that any changes to the function are applied here as well.
      zero = HumanReadableWithDecimalPlaces(0)
      self.assertIn(zero + '/s', content)
      file1_progress = (size1 / (component_num_file1*progress_calls_number))
      file2_progress = (size2 / (component_num_file2*progress_calls_number))
      # There were 2-second periods when only two progresses from file1
      # were reported. The throughput here will be file1_progress.
      self.assertIn(HumanReadableWithDecimalPlaces(file1_progress) + '/s',
                    content)
      # There were 2-second periods when only two progresses from file2
      # were reported. The throughput here will be file2_progress.
      self.assertIn(HumanReadableWithDecimalPlaces(file2_progress) + '/s',
                    content)
      # There were 2-second periods when one progress from each file was
      # reported. The throughput here will be
      # (file1_progress + file2_progress) / 2.
      average_progress = (file1_progress + file2_progress) / 2
      self.assertIn(HumanReadableWithDecimalPlaces(average_progress) + '/s',
                    content)

  def test_ui_throughput_calculation_with_no_components(self):
    """Tests throughput calculation in the UI.

    This test takes two different values, both with a different size and
    different number of components, and see if throughput behaves as expected.
    """
    status_queue = Queue.Queue()
    stream = StringIO.StringIO()
    # Creates a UIController that has no time constraints for updating info,
    # except for having to wait at least 2 seconds(considering the time informed
    # by the messages) to update the throughput. We use a value slightly smaller
    # than 2 to ensure messages that are 2 seconds apart from one another will
    # be enough to calculate throughput.
    start_time = self.start_time
    ui_controller = UIController(0, 0, 1.99, 0, start_time)
    # We use start_time to have a reasonable set of values for the time messages
    # processed by the UIController. However, the start_time does not influence
    # much this test, as the throughput is calculated based on the time
    # difference between two messages, which is fixed in this text.

    ui_thread = UIThread(status_queue, stream, ui_controller)
    fpath1 = self.CreateTempFile(file_name='sample-file.txt',
                                 contents='foo')
    fpath2 = self.CreateTempFile(file_name='sample-file2.txt',
                                 contents='FOO')

    # Note: size1 and size2 do not actually correspond to the actual sizes of
    # fpath1 and fpath2. However, the UIController only uses the size sent on
    # the message, so we should be able to pretend they are much larger on size.
    size1 = 1024**2 * 60
    src_url1 = StorageUrlFromString(suri(fpath1))
    size2 = 1024**2 * 600
    src_url2 = StorageUrlFromString(suri(fpath2))

    for file_message_type, operation_name in (
        (FileMessage.FILE_UPLOAD, 'Uploading'),
        (FileMessage.FILE_DOWNLOAD, 'Downloading')):
      # Testing for uploads and downloads
      status_queue.put(FileMessage(src_url1, None, start_time + 100, size=size1,
                                   message_type=file_message_type))
      status_queue.put(FileMessage(src_url2, None, start_time + 150, size=size2,
                                   message_type=file_message_type))

      progress_calls_number = 4
      for j in range(1, progress_calls_number + 1):
        # We will send progress_calls_number ProgressMessages for each file.
        status_queue.put(
            ProgressMessage(
                size1, j * size1 / 4, src_url1,
                start_time + 300 + j * 2,
                operation_name=operation_name))
        status_queue.put(
            ProgressMessage(
                size2, j * size2 / 4, src_url2,
                start_time + 300 + j * 2 + 1,
                operation_name=operation_name))

      # Time to finish the files.
      status_queue.put(FileMessage(src_url1, None, start_time + 700, size=size1,
                                   finished=True,
                                   message_type=file_message_type))
      status_queue.put(FileMessage(src_url2, None, start_time + 800, size=size2,
                                   finished=True,
                                   message_type=file_message_type))

      status_queue.put(ZERO_TASKS_TO_DO_ARGUMENT)
      JoinThreadAndRaiseOnTimeout(ui_thread)
      content = stream.getvalue()
      # There were 2-second periods when no progress was reported. The
      # throughput here will be 0. We will use HumanReadableWithDecimalPlaces(0)
      # to ensure that any changes to the function are applied here as well.
      zero = HumanReadableWithDecimalPlaces(0)
      self.assertIn(zero + '/s', content)
      file1_progress = (size1 / progress_calls_number)
      file2_progress = (size2 / progress_calls_number)
      # There were 2-second periods when one progress from each file was
      # reported. The throughput here will be
      # (file1_progress + file2_progress) / 2.
      average_progress = (file1_progress + file2_progress) / 2
      self.assertIn(HumanReadableWithDecimalPlaces(average_progress) + '/s',
                    content)
