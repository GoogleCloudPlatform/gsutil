# -*- coding: utf-8 -*-
# Copyright 2021 Google LLC. All Rights Reserved.
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
"""Tests for command.py."""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals
from multiprocessing import Value

import unittest
from unittest import mock

from gslib import command
from gslib import command_argument
from gslib import exception
from gslib.tests import testcase
from gslib.utils import constants
from gslib.utils import shim_util


class FakeCommand(command.Command):
  """Implementation of a fake gsutil command."""
  command_spec = command.Command.CreateCommandSpec('fake',
                                                   min_args=1,
                                                   max_args=constants.NO_MAX,
                                                   supported_sub_args='rz:',
                                                   file_url_ok=True)
  gcloud_storage_map = shim_util.GcloudStorageMap(
      gcloud_command='objects fake',
      flag_map={
          '-r': shim_util.GcloudStorageFlag(gcloud_flag='-x'),
          '-z': shim_util.GcloudStorageFlag(gcloud_flag='--zip'),
      })


class FakeCommandWithSubCommand(command.Command):
  """Implementation of a fake gsutil command."""
  command_spec = command.Command.CreateCommandSpec(
      'fake_with_sub',
      min_args=1,
      max_args=constants.NO_MAX,
      supported_sub_args='ay:',
      file_url_ok=True,
      argparse_arguments={
          'set': [
              command_argument.CommandArgument.
              MakeZeroOrMoreCloudBucketURLsArgument()
          ],
          'get': [
              command_argument.CommandArgument.MakeNCloudBucketURLsArgument(1)
          ],
      })
  gcloud_storage_map = shim_util.GcloudStorageMap(gcloud_command={
      'set':
          shim_util.GcloudStorageMap(
              gcloud_command='buckets update',
              flag_map={
                  '-a': shim_util.GcloudStorageFlag(gcloud_flag='-x'),
                  '-y': shim_util.GcloudStorageFlag(gcloud_flag='--yyy'),
              }),
      'get':
          shim_util.GcloudStorageMap(gcloud_command='buckets describe',
                                     flag_map={})
  },
                                                  flag_map={})


class TestGetGCloudStorageArgs(testcase.GsUtilUnitTestCase):
  """Test Command.GetGCloudStorageArgs method."""

  def setUp(self):
    super().setUp()
    self._fake_command = FakeCommand(
        command_runner=mock.ANY,
        args=['-z', 'opt1', '-r', 'arg1', 'arg2'],
        headers=mock.ANY,
        debug=mock.ANY,
        trace_token=mock.ANY,
        parallel_operations=mock.ANY,
        bucket_storage_uri_class=mock.ANY,
        gsutil_api_class_map_factory=mock.MagicMock())

  def test_get_gcloud_storage_args_parses_command_and_flags(self):

    gcloud_args = self._fake_command.GetGcloudStorageArgs()
    self.assertEqual(gcloud_args,
                     ['objects fake', '--zip', 'opt1', '-x', 'arg1', 'arg2'])

  def test_get_gcloud_storage_args_parses_subcommands(self):
    fake_with_subcommand = FakeCommandWithSubCommand(
        command_runner=mock.ANY,
        args=['set', '-y', 'opt1', '-a', 'arg1', 'arg2'],
        headers=mock.ANY,
        debug=mock.ANY,
        trace_token=mock.ANY,
        parallel_operations=mock.ANY,
        bucket_storage_uri_class=mock.ANY,
        gsutil_api_class_map_factory=mock.MagicMock())
    gcloud_args = fake_with_subcommand.GetGcloudStorageArgs()
    self.assertEqual(gcloud_args,
                     ['buckets update', '--yyy', 'opt1', '-x', 'arg1', 'arg2'])

  def test_raises_error_if_gcloud_storage_map_is_missing(self):
    self._fake_command.gcloud_storage_map = None
    with self.assertRaisesRegex(
        exception.GcloudStorageTranslationError,
        'Command "fake" cannot be translated to gcloud storage'
        ' because the translation mapping is missing'):
      self._fake_command.GetGcloudStorageArgs()

  def test_raises_error_if_gcloud_command_is_of_incorrect_type(self):
    self._fake_command.gcloud_storage_map = shim_util.GcloudStorageMap(
        gcloud_command=['incorrect', 'command'], flag_map={})
    with self.assertRaisesRegex(ValueError,
                                'Incorrect mapping found for "fake" command'):
      self._fake_command.GetGcloudStorageArgs()

  def test_raises_error_if_command_option_mapping_is_missing(self):
    self._fake_command.gcloud_storage_map = shim_util.GcloudStorageMap(
        gcloud_command='fake',
        flag_map={
            '-z': shim_util.GcloudStorageFlag('-a')
            # Mapping for -r is missing.
        })
    with self.assertRaisesRegex(
        exception.GcloudStorageTranslationError,
        'Command option "-r" cannot be translated to gcloud storage'):
      self._fake_command.GetGcloudStorageArgs()

  def test_raises_error_if_sub_command_mapping_is_missing(self):
    fake_with_subcommand = FakeCommandWithSubCommand(
        command_runner=mock.ANY,
        args=['set', '-y', 'opt1', '-a', 'arg1', 'arg2'],
        headers=mock.ANY,
        debug=mock.ANY,
        trace_token=mock.ANY,
        parallel_operations=mock.ANY,
        bucket_storage_uri_class=mock.ANY,
        gsutil_api_class_map_factory=mock.MagicMock())
    fake_with_subcommand.gcloud_storage_map = shim_util.GcloudStorageMap(
        gcloud_command={},  # Missing mapping for set.
        flag_map={})
    with self.assertRaisesRegex(
        exception.GcloudStorageTranslationError,
        'Command "fake_with_sub" cannot be translated to gcloud storage'
        ' because the translation mapping is missing.'):
      fake_with_subcommand.GetGcloudStorageArgs()


class TestParseSubOpts(testcase.GsUtilUnitTestCase):
  """Test Command.ParseSubOpts method.
  
  Only testing cases which are not tested indirectly by other tests.
  """

  def setUp(self):
    super().setUp()
    self._fake_command = FakeCommand(
        command_runner=mock.ANY,
        args=['-z', 'opt1', '-r', 'arg1', 'arg2'],
        headers=mock.ANY,
        debug=mock.ANY,
        trace_token=mock.ANY,
        parallel_operations=mock.ANY,
        bucket_storage_uri_class=mock.ANY,
        gsutil_api_class_map_factory=mock.MagicMock())

  def test_raises_error_with_check_args_set_and_update_sub_opts_and_args_unset(
      self):
    with self.assertRaisesRegex(
        TypeError,
        'Cannot check arguments if sub_opts and args are not updated.'):
      self._fake_command.ParseSubOpts(check_args=True,
                                      update_sub_opts_and_args=False)

  def test_uses_self_args_if_args_passed_is_None(self):
    args_list = ['fake', 'args']
    self._fake_command.args = args_list
    _, parsed_args = self._fake_command.ParseSubOpts(
        update_sub_opts_and_args=False)
    self.assertEqual(parsed_args, args_list)
