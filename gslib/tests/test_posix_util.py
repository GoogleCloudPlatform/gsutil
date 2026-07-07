# -*- coding: utf-8 -*-
# Copyright 2022 Google LLC All Rights Reserved.
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
"""Tests for posix_util.py."""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

import os

from gslib.tests import testcase
from gslib.tests.util import unittest
from gslib.utils import posix_util
from gslib.utils.system_util import IS_WINDOWS

from six import add_move, MovedModule

add_move(MovedModule('mock', 'mock', 'unittest.mock'))
from six.moves import mock


import logging
import time

class TestPosixUtil(testcase.GsUtilUnitTestCase):
  """Unit tests for POSIX utils."""

  @mock.patch.object(posix_util, 'InitializeUserGroups', autospec=True)
  @mock.patch.object(posix_util, 'InitializeDefaultMode', autospec=True)
  def test_initialize_preserve_posix_data_calls_correct_functions(
      self, mock_initialize_default_mode, mock_initialize_user_groups):
    posix_util.InitializePreservePosixData()
    mock_initialize_default_mode.assert_called_once_with()
    mock_initialize_user_groups.assert_called_once_with()

  @unittest.skipIf(IS_WINDOWS, 'os.umask always returns 0 on Windows.')
  @mock.patch.object(os, 'umask', autospec=True)
  def test_initialize_mode_sets_umask_to_correct_temporary_value_not_windows(
      self, mock_umask):
    # Abort before setting SYSTEM_POSIX_MODE to avoid side effects.
    mock_umask.side_effect = ValueError
    with self.assertRaises(ValueError):
      posix_util.InitializeDefaultMode()
    mock_umask.assert_called_once_with(0o177)

  def test_convert_mode_to_base8(self):
    self.assertEqual(posix_util.ConvertModeToBase8(33188), 644)
    self.assertEqual(posix_util.ConvertModeToBase8(33261), 755)

  def test_validate_posix_mode(self):
    self.assertTrue(posix_util.ValidatePOSIXMode(0o644))
    self.assertTrue(posix_util.ValidatePOSIXMode(0o755))
    self.assertTrue(posix_util.ValidatePOSIXMode(0o604))
    self.assertFalse(posix_util.ValidatePOSIXMode(0o000))
    self.assertFalse(posix_util.ValidatePOSIXMode(0o300))

  def test_serialize_deserialize_attributes(self):
    from gslib.third_party.storage_apitools import storage_v1_messages as apitools_messages

    # Create POSIXAttributes
    posix_attrs = posix_util.POSIXAttributes(
        atime=1000, mtime=2000, uid=100, gid=200, mode=644)

    # Serialize
    custom_metadata = apitools_messages.Object.MetadataValue(additionalProperties=[])
    posix_util.SerializeFileAttributesToObjectMetadata(
        posix_attrs, custom_metadata, preserve_posix=True)

    # Mock GCS object metadata message containing the serialized custom metadata
    obj_metadata = apitools_messages.Object(metadata=custom_metadata)

    # Deserialize
    deserialized = posix_util.DeserializeFileAttributesFromObjectMetadata(
        obj_metadata, 'gs://bucket/obj')

    # Assertions
    self.assertEqual(deserialized.atime, 1000)
    self.assertEqual(deserialized.mtime, posix_util.NA_TIME)
    self.assertEqual(deserialized.uid, 100)
    self.assertEqual(deserialized.gid, 200)
    self.assertEqual(deserialized.mode.permissions, 644)

  @mock.patch.object(logging.Logger, 'warning')
  @mock.patch.object(logging.Logger, 'warn', create=True)
  def test_deserialize_invalid_attributes(self, mock_warn, mock_warning):
    # Some logging versions/configurations call .warning instead of .warn
    from gslib.third_party.storage_apitools import storage_v1_messages as apitools_messages

    # Case 1: Negative UID/GID
    custom_metadata = apitools_messages.Object.MetadataValue(additionalProperties=[])
    posix_util.CreateCustomMetadata(
        entries={posix_util.UID_ATTR: -10, posix_util.GID_ATTR: -20},
        custom_metadata=custom_metadata)
    obj_metadata = apitools_messages.Object(metadata=custom_metadata)

    deserialized = posix_util.DeserializeFileAttributesFromObjectMetadata(
        obj_metadata, 'gs://bucket/obj')
    self.assertEqual(deserialized.uid, posix_util.NA_ID)
    self.assertEqual(deserialized.gid, posix_util.NA_ID)
    self.assertEqual(mock_warn.call_count + mock_warning.call_count, 2)
    mock_warn.reset_mock()
    mock_warning.reset_mock()

    # Case 2: Future Timestamp
    custom_metadata = apitools_messages.Object.MetadataValue(additionalProperties=[])
    future_time = int(time.time()) + 1000000
    posix_util.CreateCustomMetadata(
        entries={posix_util.ATIME_ATTR: future_time},
        custom_metadata=custom_metadata)
    obj_metadata = apitools_messages.Object(metadata=custom_metadata)

    deserialized = posix_util.DeserializeFileAttributesFromObjectMetadata(
        obj_metadata, 'gs://bucket/obj')
    self.assertEqual(deserialized.atime, posix_util.NA_TIME)
    self.assertEqual(mock_warn.call_count + mock_warning.call_count, 1)
    mock_warn.reset_mock()
    mock_warning.reset_mock()

    # Case 3: Invalid Non-Integer Value
    custom_metadata = apitools_messages.Object.MetadataValue(additionalProperties=[])
    posix_util.CreateCustomMetadata(
        entries={posix_util.UID_ATTR: 'abc'},
        custom_metadata=custom_metadata)
    obj_metadata = apitools_messages.Object(metadata=custom_metadata)

    deserialized = posix_util.DeserializeFileAttributesFromObjectMetadata(
        obj_metadata, 'gs://bucket/obj')
    self.assertEqual(deserialized.uid, posix_util.NA_ID)
    self.assertEqual(mock_warn.call_count + mock_warning.call_count, 1)

  def test_needs_posix_attribute_update(self):
    # Case 1: Source has atime, dest does not
    posix_attrs, needs_update = posix_util.NeedsPOSIXAttributeUpdate(
        src_atime=1000, dst_atime=posix_util.NA_TIME,
        src_mtime=posix_util.NA_TIME, dst_mtime=posix_util.NA_TIME,
        src_uid=posix_util.NA_ID, dst_uid=posix_util.NA_ID,
        src_gid=posix_util.NA_ID, dst_gid=posix_util.NA_ID,
        src_mode=posix_util.NA_MODE, dst_mode=posix_util.NA_MODE)
    self.assertTrue(needs_update)
    self.assertEqual(posix_attrs.atime, 1000)

    # Case 2: Source has same attributes as dest
    _, needs_update = posix_util.NeedsPOSIXAttributeUpdate(
        src_atime=1000, dst_atime=1000,
        src_mtime=2000, dst_mtime=2000,
        src_uid=100, dst_uid=100,
        src_gid=200, dst_gid=200,
        src_mode=0o644, dst_mode=0o644)
    self.assertFalse(needs_update)

