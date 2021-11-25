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
"""Tests for shim_util.py."""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

import os
import subprocess
from unittest import mock

from gslib import command
from gslib import command_argument
from gslib import exception
from gslib.tests import testcase
from gslib.utils import constants
from gslib.utils import shim_util
from gslib.tests import util


class FakeCommandWithGcloudStorageMap(command.Command):
  """Implementation of a fake gsutil command."""
  command_spec = command.Command.CreateCommandSpec('fake_shim',
                                                   min_args=1,
                                                   max_args=constants.NO_MAX,
                                                   supported_sub_args='irz:',
                                                   file_url_ok=True)
  gcloud_storage_map = shim_util.GcloudStorageMap(
      gcloud_command='objects fake',
      flag_map={
          '-r': shim_util.GcloudStorageFlag(gcloud_flag='-x'),
          '-z': shim_util.GcloudStorageFlag(gcloud_flag='--zip'),
      })
  help_spec = command.Command.HelpSpec(
      help_name='fake_shim',
      help_name_aliases=[],
      help_type='command_help',
      help_one_line_summary='Fake one line summary for the command.',
      help_text='Help text for fake command.',
      subcommand_help_text={},
  )

  def RunCommand(self):
    print('FakeCommandWithGcloudStorageMap called')


class FakeCommandWithSubCommandWithGcloudStorageMap(command.Command):
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
  help_spec = command.Command.HelpSpec(
      help_name='fake_with_sub',
      help_name_aliases=[],
      help_type='command_help',
      help_one_line_summary='Fake one line summary for the command.',
      help_text='Help text for fake command with sub commands.',
      subcommand_help_text={},
  )


class TestGetGCloudStorageArgs(testcase.GsUtilUnitTestCase):
  """Test Command.get_gcloud_storage_args method."""

  def setUp(self):
    super().setUp()
    self._fake_command = FakeCommandWithGcloudStorageMap(
        command_runner=mock.ANY,
        args=['-z', 'opt1', '-r', 'arg1', 'arg2'],
        headers=mock.ANY,
        debug=mock.ANY,
        trace_token=mock.ANY,
        parallel_operations=mock.ANY,
        bucket_storage_uri_class=mock.ANY,
        gsutil_api_class_map_factory=mock.MagicMock())

  def test_get_gcloud_storage_args_parses_command_and_flags(self):

    gcloud_args = self._fake_command.get_gcloud_storage_args()
    self.assertEqual(gcloud_args,
                     ['objects', 'fake', '--zip', 'opt1', '-x', 'arg1', 'arg2'])

  def test_get_gcloud_storage_args_parses_subcommands(self):
    fake_with_subcommand = FakeCommandWithSubCommandWithGcloudStorageMap(
        command_runner=mock.ANY,
        args=['set', '-y', 'opt1', '-a', 'arg1', 'arg2'],
        headers=mock.ANY,
        debug=mock.ANY,
        trace_token=mock.ANY,
        parallel_operations=mock.ANY,
        bucket_storage_uri_class=mock.ANY,
        gsutil_api_class_map_factory=mock.MagicMock())
    gcloud_args = fake_with_subcommand.get_gcloud_storage_args()
    self.assertEqual(
        gcloud_args,
        ['buckets', 'update', '--yyy', 'opt1', '-x', 'arg1', 'arg2'])

  def test_raises_error_if_gcloud_storage_map_is_missing(self):
    self._fake_command.gcloud_storage_map = None
    with self.assertRaisesRegex(
        exception.GcloudStorageTranslationError,
        'Command "fake_shim" cannot be translated to gcloud storage'
        ' because the translation mapping is missing'):
      self._fake_command.get_gcloud_storage_args()

  def test_raises_error_if_gcloud_command_is_of_incorrect_type(self):
    self._fake_command.gcloud_storage_map = shim_util.GcloudStorageMap(
        gcloud_command=['incorrect', 'command'], flag_map={})
    with self.assertRaisesRegex(
        ValueError, 'Incorrect mapping found for "fake_shim" command'):
      self._fake_command.get_gcloud_storage_args()

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
      self._fake_command.get_gcloud_storage_args()

  def test_raises_error_if_sub_command_mapping_is_missing(self):
    fake_with_subcommand = FakeCommandWithSubCommandWithGcloudStorageMap(
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
      fake_with_subcommand.get_gcloud_storage_args()


class TestTranslateToGcloudStorageIfRequested(testcase.GsUtilUnitTestCase):
  """Test Command.translate_to_gcloud_storage_if_requested method."""

  def setUp(self):
    super().setUp()
    self._fake_command = FakeCommandWithGcloudStorageMap(
        command_runner=mock.ANY,
        args=['-z', 'opt1', '-r', 'arg1', 'arg2'],
        headers=mock.ANY,
        debug=mock.ANY,
        trace_token=mock.ANY,
        parallel_operations=mock.ANY,
        bucket_storage_uri_class=mock.ANY,
        gsutil_api_class_map_factory=mock.MagicMock())

  def test_returns_false_with_use_gcloud_storage_never(self):
    """Should not attempt translation."""
    with util.SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'never')]):
      with mock.patch.object(self._fake_command,
                             'get_gcloud_storage_args',
                             autospec=True) as mock_get_gcloud_storage_args:
        self.assertFalse(
            self._fake_command.translate_to_gcloud_storage_if_requested())
        self.assertFalse(mock_get_gcloud_storage_args.called)

  def test_returns_true_with_valid_gcloud_storage_map(self):
    """Should return True and perform the translation."""
    with util.SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'always')
                                   ]):
      with util.SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        self.assertTrue(
            self._fake_command.translate_to_gcloud_storage_if_requested())
        # Verify translation.
        expected_gcloud_path = os.path.join('fake_dir', 'bin', 'gcloud')
        self.assertEqual(self._fake_command._translated_gcloud_storage_command,
                         [
                             expected_gcloud_path, 'objects', 'fake', '--zip',
                             'opt1', '-x', 'arg1', 'arg2'
                         ])
        # TODO(b/206149936) Verify translated boto config.

  def test_raises_error_if_invalid_use_gcloud_storage_value(self):
    with util.SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'invalid')
                                   ]):
      with self.assertRaisesRegex(
          exception.CommandException,
          'CommandException: Invalid option specified for'
          ' GSUtil:use_gcloud_storage config setting. Should be one of:'
          ' never | if_available_else_skip | always | dry_run'):
        self._fake_command.translate_to_gcloud_storage_if_requested()

  def test_raises_error_if_cloudsdk_root_dir_is_none(self):
    with util.SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'always')
                                   ]):
      with util.SetEnvironmentForTest({
          'CLOUDSDK_ROOT_DIR': None,
      }):
        with self.assertRaisesRegex(
            exception.CommandException,
            'CommandException: Gcloud binary path cannot be found'):
          self._fake_command.translate_to_gcloud_storage_if_requested()

  def test_raises_error_if_pass_credentials_to_gsutil_is_missing(self):
    with util.SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'always')
                                   ]):
      with util.SetEnvironmentForTest({'CLOUDSDK_ROOT_DIR': 'fake_dir'}):
        with self.assertRaisesRegex(
            exception.CommandException,
            'CommandException: Gsutil is not using the same credentials as'
            ' gcloud. You can make gsutil use the same credentials by running:'
            '[\r\n]+{} config set pass_credentials_to_gsutil True'.format(
                os.path.join('fake_dir', 'bin', 'gcloud'))):
          self._fake_command.translate_to_gcloud_storage_if_requested()

  def test_raises_error_if_gcloud_storage_map_missing(self):
    self._fake_command.gcloud_storage_map = None
    with util.SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'always')
                                   ]):
      with util.SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        with self.assertRaisesRegex(
            exception.CommandException,
            'CommandException: Command "fake_shim" cannot be translated to'
            ' gcloud storage because the translation mapping is missing.'):
          self._fake_command.translate_to_gcloud_storage_if_requested()

  def test_use_gcloud_storage_set_to_if_available_else_skip(self):
    """Should not raise error."""
    with util.SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage',
                                     'if_available_else_skip')]):
      with util.SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        # return_stderr does not work here. Probably because we have
        # defined the FakeCommand in the same module.
        stdout, mock_log_handler = self.RunCommand('fake_shim',
                                                   args=['-i', 'arg1'],
                                                   return_stdout=True,
                                                   return_log_handler=True)
        self.assertIn(
            'Cannot translate gsutil command to gcloud storage.'
            ' Going to run gsutil command. Error: Command option "-i"'
            ' cannot be translated to gcloud storage',
            mock_log_handler.messages['error'])
        self.assertIn('FakeCommandWithGcloudStorageMap called', stdout)

  def test_dry_run_mode_prints_translated_commands(self):
    """Should print the gcloud command and run gsutil."""
    with util.SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'dry_run')
                                   ]):
      with util.SetEnvironmentForTest({'CLOUDSDK_ROOT_DIR': 'fake_dir'}):
        stdout = self.RunCommand('fake_shim', args=['arg1'], return_stdout=True)
        self.assertIn(
            'Gcloud Storage Command: {} objects fake arg1'
            '\nEnviornment variables for Gcloud Storage: {{}}\n'
            'FakeCommandWithGcloudStorageMap called'.format(
                os.path.join('fake_dir', 'bin', 'gcloud')), stdout)


class TestRunGcloudStorage(testcase.GsUtilUnitTestCase):
  """Test Command.run_gcloud_storage method."""

  @mock.patch.object(os.environ, 'copy', return_value={'old_key': 'old_value'})
  @mock.patch.object(subprocess, 'run', autospec=True)
  def test_calls_subprocess_with_translated_command_and_env_vars(
      self, mock_run, mock_environ_copy):
    command_instance = FakeCommandWithGcloudStorageMap(
        command_runner=mock.ANY,
        args=['-z', 'opt1', '-r', 'arg1', 'arg2'],
        headers=mock.ANY,
        debug=mock.ANY,
        trace_token=mock.ANY,
        parallel_operations=mock.ANY,
        bucket_storage_uri_class=mock.ANY,
        gsutil_api_class_map_factory=mock.MagicMock())
    with util.SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'always')
                                   ]):
      with util.SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        command_instance._translated_boto_config_to_env_vars = {
            'new_key': 'new_value',
        }
        command_instance._translated_gcloud_storage_command = ['gcloud', 'foo']
        actual_return_code = command_instance.run_gcloud_storage()
        mock_run.assert_called_once_with(['gcloud', 'foo'],
                                         env={
                                             'old_key': 'old_value',
                                             'new_key': 'new_value'
                                         })
        mock_environ_copy.assert_called_once_with()
        self.assertEqual(actual_return_code, mock_run.return_value.returncode)
