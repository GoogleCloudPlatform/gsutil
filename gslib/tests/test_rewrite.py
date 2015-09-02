# -*- coding: utf-8 -*-
# Copyright 2015 Google Inc. All Rights Reserved.
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
"""Integration tests for rewrite command."""

from __future__ import absolute_import

import logging
import os

from boto.storage_uri import BucketStorageUri

from gslib.cloud_api import CryptoTuple
from gslib.cs_api_map import ApiSelector
from gslib.gcs_json_api import GcsJsonApi
from gslib.tests.rewrite_helper import EnsureRewriteRestartCallbackHandler
from gslib.tests.rewrite_helper import EnsureRewriteResumeCallbackHandler
from gslib.tests.rewrite_helper import HaltingRewriteCallbackHandler
from gslib.tests.rewrite_helper import RewriteHaltException
import gslib.tests.testcase as testcase
from gslib.tests.testcase.integration_testcase import SkipForS3
from gslib.tests.util import ObjectToURI as suri
from gslib.tests.util import SetBotoConfigForTest
from gslib.tests.util import TEST_ENCRYPTION_KEY1
from gslib.tests.util import TEST_ENCRYPTION_KEY2
from gslib.tests.util import TEST_ENCRYPTION_KEY3
from gslib.tests.util import unittest
from gslib.tracker_file import DeleteTrackerFile
from gslib.tracker_file import GetRewriteTrackerFilePath
from gslib.util import ONE_MIB


@SkipForS3('gsutil doesn\'t support S3 customer-supplied encryption keys.')
class TestRewrite(testcase.GsUtilIntegrationTestCase):
  """Integration tests for rewrite command."""

  def test_rewrite_missing_flag(self):
    """Tests rewrite with no transformation flag."""
    stderr = self.RunGsUtil(
        ['rewrite', '%s://some_url' % self.default_provider],
        return_stderr=True, expected_status=1)
    self.assertIn('command requires at least one transformation flag', stderr)

  def test_rewrite_generation_url(self):
    """Tests that rewrite fails on a URL that includes a generation."""
    object_uri = self.CreateObject(contents='bar',
                                   encryption_key=TEST_ENCRYPTION_KEY1)
    generation = object_uri.generation
    stderr = self.RunGsUtil(
        ['rewrite', '-k', '%s#%s' % (suri(object_uri), generation)],
        return_stderr=True, expected_status=1)
    self.assertIn('"rewrite" called on URL with generation', stderr)

  def test_rewrite_missing_decryption_key(self):
    """Tests that rewrite fails when no decryption key matches."""
    object_uri = self.CreateObject(object_name='foo', contents='bar',
                                   encryption_key=TEST_ENCRYPTION_KEY1)
    boto_config_for_test = [
        ('GSUtil', 'encryption_key', TEST_ENCRYPTION_KEY2),
        ('GSUtil', 'decryption_key1', TEST_ENCRYPTION_KEY3)]
    with SetBotoConfigForTest(boto_config_for_test):
      stderr = self.RunGsUtil(['rewrite', '-k', suri(object_uri)],
                              return_stderr=True, expected_status=1)
      self.assertIn('No decryption key matches object %s' %
                    suri(object_uri), stderr)

  def test_rewrite_stdin_args(self):
    """Tests rewrite with arguments supplied on stdin."""
    object_uri = self.CreateObject(contents='bar',
                                   encryption_key=TEST_ENCRYPTION_KEY1)
    stdin_arg = suri(object_uri)

    boto_config_for_test = [
        ('GSUtil', 'encryption_key', TEST_ENCRYPTION_KEY2),
        ('GSUtil', 'decryption_key1', TEST_ENCRYPTION_KEY1)]
    with SetBotoConfigForTest(boto_config_for_test):
      self.RunGsUtil(['rewrite', '-k', '-I'], stdin=stdin_arg)
    self.AssertObjectUsesEncryptionKey(stdin_arg, TEST_ENCRYPTION_KEY2)

  def test_rewrite_overwrite_acl(self):
    """Tests rewrite with the -O flag."""
    object_uri = self.CreateObject(contents='bar',
                                   encryption_key=TEST_ENCRYPTION_KEY1)
    self.RunGsUtil(['acl', 'ch', '-u', 'AllUsers:R', suri(object_uri)])
    stdout = self.RunGsUtil(['acl', 'get', suri(object_uri)],
                            return_stdout=True)
    self.assertIn('allUsers', stdout)

    boto_config_for_test = [
        ('GSUtil', 'encryption_key', TEST_ENCRYPTION_KEY2),
        ('GSUtil', 'decryption_key1', TEST_ENCRYPTION_KEY1)]
    with SetBotoConfigForTest(boto_config_for_test):
      self.RunGsUtil(['rewrite', '-k', '-O', suri(object_uri)])
    self.AssertObjectUsesEncryptionKey(suri(object_uri), TEST_ENCRYPTION_KEY2)
    stdout = self.RunGsUtil('acl', 'get', suri(object_uri), return_stdout=True)
    self.assertNotIn('allUsers', stdout)

  def test_rewrite_bucket_recursive(self):
    """Tests rewrite command recursively on a bucket."""
    bucket_uri = self.CreateBucket()
    self._test_rewrite_key_rotation_bucket(
        bucket_uri, ['rewrite', '-k', '-r', suri(bucket_uri)])

  def test_parallel_rewrite_bucket_flat_wildcard(self):
    """Tests parallel rewrite command with a flat wildcard on a bucket."""
    bucket_uri = self.CreateBucket()
    self._test_rewrite_key_rotation_bucket(
        bucket_uri, ['-m', 'rewrite', '-k', suri(bucket_uri, '**')])

  def _test_rewrite_key_rotation_bucket(self, bucket_uri, command_args):
    """Helper function for testing key rotation on a bucket.

    Args:
      bucket_uri: bucket StorageUri to use for the test.
      command_args: list of args to gsutil command.
    """
    object_contents = 'bar'
    object_uri1 = self.CreateObject(bucket_uri=bucket_uri,
                                    object_name='foo/foo',
                                    contents=object_contents,
                                    encryption_key=TEST_ENCRYPTION_KEY1)
    object_uri2 = self.CreateObject(bucket_uri=bucket_uri,
                                    object_name='foo/bar',
                                    contents=object_contents,
                                    encryption_key=TEST_ENCRYPTION_KEY2)
    object_uri3 = self.CreateObject(bucket_uri=bucket_uri,
                                    object_name='foo/baz',
                                    contents=object_contents,
                                    encryption_key=TEST_ENCRYPTION_KEY3)
    object_uri4 = self.CreateObject(bucket_uri=bucket_uri,
                                    object_name='foo/qux',
                                    contents=object_contents)

    # Rotate all keys to TEST_ENCRYPTION_KEY1.
    boto_config_for_test = [
        ('GSUtil', 'encryption_key', TEST_ENCRYPTION_KEY1),
        ('GSUtil', 'decryption_key1', TEST_ENCRYPTION_KEY2),
        ('GSUtil', 'decryption_key2', TEST_ENCRYPTION_KEY3)]

    with SetBotoConfigForTest(boto_config_for_test):
      stderr = self.RunGsUtil(command_args, return_stdout=True)
      # Object one already has the correct key.
      self.assertIn('Skipping object %s' % suri(object_uri1), stderr)
      # Other objects should be rotated.
      self.assertIn('RotatingKey', stderr)
    for object_uri_str in (suri(object_uri1), suri(object_uri2),
                           suri(object_uri3), suri(object_uri4)):
      self.AssertObjectUsesEncryptionKey(object_uri_str,
                                         TEST_ENCRYPTION_KEY1)

    # Remove all encryption.
    boto_config_for_test2 = [
        ('GSUtil', 'decryption_key1', TEST_ENCRYPTION_KEY1)]

    with SetBotoConfigForTest(boto_config_for_test2):
      stderr = self.RunGsUtil(command_args, return_stderr=True)
      self.assertIn('Decrypting', stderr)

    for object_uri_str in (suri(object_uri1), suri(object_uri2),
                           suri(object_uri3), suri(object_uri4)):
      self._ensure_object_unencrypted(object_uri_str)

  def test_rewrite_key_rotation_single_object(self):
    object_uri = self.CreateObject(contents='bar',
                                   encryption_key=TEST_ENCRYPTION_KEY1)

    # Rotate key.
    boto_config_for_test = [
        ('GSUtil', 'encryption_key', TEST_ENCRYPTION_KEY2),
        ('GSUtil', 'decryption_key1', TEST_ENCRYPTION_KEY1)]

    with SetBotoConfigForTest(boto_config_for_test):
      stderr = self.RunGsUtil(['rewrite', '-k', suri(object_uri)],
                              return_stderr=True)
      self.assertIn('RotatingKey', stderr)

    self.AssertObjectUsesEncryptionKey(suri(object_uri),
                                       TEST_ENCRYPTION_KEY2)

    # Remove encryption.
    boto_config_for_test2 = [
        ('GSUtil', 'decryption_key1', TEST_ENCRYPTION_KEY2)]
    with SetBotoConfigForTest(boto_config_for_test2):
      stderr = self.RunGsUtil(['rewrite', '-k', suri(object_uri)],
                              return_stderr=True)
      self.assertIn('Decrypting', stderr)

    self._ensure_object_unencrypted(suri(object_uri))

  def test_rewrite_key_rotation_bucket_subdir(self):
    bucket_uri = self.CreateBucket()
    object_contents = 'bar'
    rotate_subdir = suri(bucket_uri, 'bar')
    object_uri1 = self.CreateObject(bucket_uri=bucket_uri,
                                    object_name='foo/bar',
                                    contents=object_contents,
                                    encryption_key=TEST_ENCRYPTION_KEY1)
    object_uri2 = self.CreateObject(bucket_uri=bucket_uri,
                                    object_name='bar/foo',
                                    contents=object_contents,
                                    encryption_key=TEST_ENCRYPTION_KEY2)
    object_uri3 = self.CreateObject(bucket_uri=bucket_uri,
                                    object_name='bar/baz',
                                    contents=object_contents,
                                    encryption_key=TEST_ENCRYPTION_KEY3)
    object_uri4 = self.CreateObject(bucket_uri=bucket_uri,
                                    object_name='bar/qux',
                                    contents=object_contents)

    # Rotate subdir keys to TEST_ENCRYPTION_KEY3.
    boto_config_for_test = [
        ('GSUtil', 'encryption_key', TEST_ENCRYPTION_KEY3),
        ('GSUtil', 'decryption_key1', TEST_ENCRYPTION_KEY2),
        ('GSUtil', 'decryption_key2', TEST_ENCRYPTION_KEY1)]

    with SetBotoConfigForTest(boto_config_for_test):
      stderr = self.RunGsUtil(['rewrite', '-r', '-k', rotate_subdir],
                              return_stderr=True)
      self.assertIn('RotatingKey', stderr)  # Object 2.
      self.assertIn('Skipping object %s' % suri(object_uri3), stderr)
      self.assertIn('Encrypting', stderr)  # Object 4.

    # First subdir should be unaffected.
    self.AssertObjectUsesEncryptionKey(suri(object_uri1),
                                       TEST_ENCRYPTION_KEY1)

    for object_uri_str in (suri(object_uri2), suri(object_uri3),
                           suri(object_uri4)):
      self.AssertObjectUsesEncryptionKey(object_uri_str,
                                         TEST_ENCRYPTION_KEY3)

    # Remove encryption in subdir.
    boto_config_for_test2 = [
        ('GSUtil', 'decryption_key1', TEST_ENCRYPTION_KEY3)]

    with SetBotoConfigForTest(boto_config_for_test2):
      stderr = self.RunGsUtil(['rewrite', '-r', '-k', rotate_subdir],
                              return_stderr=True)
      self.assertIn('Decrypting', stderr)

    # First subdir should be unaffected.
    self.AssertObjectUsesEncryptionKey(suri(object_uri1),
                                       TEST_ENCRYPTION_KEY1)
    self.AssertObjectUsesEncryptionKey(suri(object_uri2),
                                       TEST_ENCRYPTION_KEY2)

    for object_uri_str in (suri(object_uri3), suri(object_uri4)):
      self._ensure_object_unencrypted(object_uri_str)

  def test_rewrite_resume(self):
    """Tests that the rewrite command breaks and resumes via a tracker file."""
    if self.test_api == ApiSelector.XML:
      return unittest.skip('Rewrite API is only supported in JSON.')
    bucket_uri = self.CreateBucket()
    # maxBytesPerCall must be >= 1 MiB, so create an object > 2 MiB because we
    # need 2 response from the service: 1 success, 1 failure prior to
    # completion.
    object_uri = self.CreateObject(bucket_uri=bucket_uri, object_name='foo',
                                   contents=('12'*ONE_MIB) + 'bar',
                                   prefer_json_api=True,
                                   encryption_key=TEST_ENCRYPTION_KEY1)
    gsutil_api = GcsJsonApi(BucketStorageUri, logging.getLogger(),
                            self.default_provider)
    with SetBotoConfigForTest(
        [('GSUtil', 'decryption_key1', TEST_ENCRYPTION_KEY1)]):
      src_obj_metadata = gsutil_api.GetObjectMetadata(
          object_uri.bucket_name, object_uri.object_name,
          provider=self.default_provider, fields=['bucket', 'contentType',
                                                  'etag', 'name'])
    dst_obj_metadata = src_obj_metadata
    tracker_file_name = GetRewriteTrackerFilePath(
        src_obj_metadata.bucket, src_obj_metadata.name,
        dst_obj_metadata.bucket, dst_obj_metadata.name, self.test_api)
    decryption_tuple = CryptoTuple(TEST_ENCRYPTION_KEY1)
    encryption_tuple = CryptoTuple(TEST_ENCRYPTION_KEY2)

    with SetBotoConfigForTest(
        [('GSUtil', 'decryption_key1', TEST_ENCRYPTION_KEY1)]):
      original_md5 = gsutil_api.GetObjectMetadata(
          src_obj_metadata.bucket, src_obj_metadata.name,
          fields=['customerEncryption', 'md5Hash']).md5Hash

    try:
      try:
        gsutil_api.CopyObject(
            src_obj_metadata, dst_obj_metadata,
            progress_callback=HaltingRewriteCallbackHandler(ONE_MIB*2).call,
            max_bytes_per_call=ONE_MIB, decryption_tuple=decryption_tuple,
            encryption_tuple=encryption_tuple)
        self.fail('Expected RewriteHaltException.')
      except RewriteHaltException:
        pass

      # Tracker file should be left over.
      self.assertTrue(os.path.exists(tracker_file_name))

      # Now resume. Callback ensures we didn't start over.
      gsutil_api.CopyObject(
          src_obj_metadata, dst_obj_metadata,
          progress_callback=EnsureRewriteResumeCallbackHandler(ONE_MIB*2).call,
          max_bytes_per_call=ONE_MIB, decryption_tuple=decryption_tuple,
          encryption_tuple=encryption_tuple)

      # Copy completed; tracker file should be deleted.
      self.assertFalse(os.path.exists(tracker_file_name))

      # Key2 should be all that's necessary to decrypt the new object.
      with SetBotoConfigForTest([
          ('GSUtil', 'decryption_key', TEST_ENCRYPTION_KEY2)]):
        self.assertEqual(
            original_md5,
            gsutil_api.GetObjectMetadata(dst_obj_metadata.bucket,
                                         dst_obj_metadata.name,
                                         fields=['customerEncryption',
                                                 'md5Hash']).md5Hash,
            'Error: Rewritten object\'s hash doesn\'t match source object.')
    finally:
      # Clean up if something went wrong.
      DeleteTrackerFile(tracker_file_name)

  def test_rewrite_resume_restart(self):
    """Tests that the rewrite command restarts if the object's key changed."""
    if self.test_api == ApiSelector.XML:
      return unittest.skip('Rewrite API is only supported in JSON.')
    bucket_uri = self.CreateBucket()
    # maxBytesPerCall must be >= 1 MiB, so create an object > 2 MiB because we
    # need 2 response from the service: 1 success, 1 failure prior to
    # completion.
    object_uri = self.CreateObject(bucket_uri=bucket_uri, object_name='foo',
                                   contents=('12'*ONE_MIB) + 'bar',
                                   prefer_json_api=True,
                                   encryption_key=TEST_ENCRYPTION_KEY1)
    gsutil_api = GcsJsonApi(BucketStorageUri, logging.getLogger(),
                            self.default_provider)
    with SetBotoConfigForTest(
        [('GSUtil', 'decryption_key1', TEST_ENCRYPTION_KEY1)]):
      src_obj_metadata = gsutil_api.GetObjectMetadata(
          object_uri.bucket_name, object_uri.object_name,
          provider=self.default_provider, fields=['bucket', 'contentType',
                                                  'etag', 'name'])
    dst_obj_metadata = src_obj_metadata
    tracker_file_name = GetRewriteTrackerFilePath(
        src_obj_metadata.bucket, src_obj_metadata.name,
        dst_obj_metadata.bucket, dst_obj_metadata.name, self.test_api)
    decryption_tuple = CryptoTuple(TEST_ENCRYPTION_KEY1)
    encryption_tuple = CryptoTuple(TEST_ENCRYPTION_KEY2)
    decryption_tuple2 = CryptoTuple(TEST_ENCRYPTION_KEY3)

    try:
      try:
        gsutil_api.CopyObject(
            src_obj_metadata, dst_obj_metadata,
            progress_callback=HaltingRewriteCallbackHandler(ONE_MIB*2).call,
            max_bytes_per_call=ONE_MIB, decryption_tuple=decryption_tuple,
            encryption_tuple=encryption_tuple)
        self.fail('Expected RewriteHaltException.')
      except RewriteHaltException:
        pass

      # Tracker file should be left over.
      self.assertTrue(os.path.exists(tracker_file_name))

      # Recreate the object with a different encryption key.
      object_uri = self.CreateObject(bucket_uri=bucket_uri, object_name='foo',
                                     contents=('12'*ONE_MIB) + 'bar',
                                     prefer_json_api=True,
                                     encryption_key=TEST_ENCRYPTION_KEY3)

      with SetBotoConfigForTest([
          ('GSUtil', 'decryption_key1', TEST_ENCRYPTION_KEY3)]):
        original_md5 = gsutil_api.GetObjectMetadata(
            src_obj_metadata.bucket, src_obj_metadata.name,
            fields=['customerEncryption', 'md5Hash']).md5Hash

      # Now resume. Callback ensures we started over.
      gsutil_api.CopyObject(
          src_obj_metadata, dst_obj_metadata,
          progress_callback=EnsureRewriteRestartCallbackHandler(ONE_MIB).call,
          max_bytes_per_call=ONE_MIB, decryption_tuple=decryption_tuple2,
          encryption_tuple=encryption_tuple)

      # Copy completed; tracker file should be deleted.
      self.assertFalse(os.path.exists(tracker_file_name))

      with SetBotoConfigForTest([
          ('GSUtil', 'encryption_key', TEST_ENCRYPTION_KEY1)]):
        self.assertEqual(
            original_md5,
            gsutil_api.GetObjectMetadata(dst_obj_metadata.bucket,
                                         dst_obj_metadata.name,
                                         fields=['customerEncryption',
                                                 'md5Hash']).md5Hash,
            'Error: Rewritten object\'s hash doesn\'t match source object.')
    finally:
      # Clean up if something went wrong.
      DeleteTrackerFile(tracker_file_name)

