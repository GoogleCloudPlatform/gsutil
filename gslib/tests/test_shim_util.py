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

import collections
from contextlib import contextmanager
import os
import subprocess
from unittest import mock

from boto import config

from gslib import command
from gslib import command_argument
from gslib import exception
from gslib.commands import version
from gslib.commands import test
from gslib.tests import testcase
from gslib.utils import constants
from gslib.utils import shim_util
from gslib.tests import util


@contextmanager
def _mock_boto_config(boto_config_dict):
  """"Mock boto config replacing any exiting config.
  
  The util.SetBotoConfigForTest has a use_existing_config flag that can be
  set to False, but it does not work if the config has been already loaded,
  which is the case for all unit tests that do not use RunCommand method.

  Args:
    boto_config_dict. A dict with key=<boto section name> and value=<a dict
      of boto field name and the value for that field>.
  """

  def _config_get_side_effect(section, key, default_value=None):
    return boto_config_dict.get(section, {}).get(key, default_value)

  with mock.patch.object(config, 'get', autospec=True) as mock_get:
    with mock.patch.object(config, 'getbool', autospec=True) as mock_getbool:
      with mock.patch.object(config, 'items', autospec=True) as mock_items:
        mock_get.side_effect = _config_get_side_effect
        mock_getbool.side_effect = _config_get_side_effect
        mock_items.return_value = boto_config_dict.items()
        yield


class FakeCommandWithGcloudStorageMap(command.Command):
  """Implementation of a fake gsutil command."""
  command_spec = command.Command.CreateCommandSpec('fake_shim',
                                                   min_args=1,
                                                   max_args=constants.NO_MAX,
                                                   supported_sub_args='irz:',
                                                   file_url_ok=True)
  gcloud_storage_map = shim_util.GcloudStorageMap(
      gcloud_command=['objects', 'fake'],
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
              gcloud_command=['buckets', 'update'],
              flag_map={
                  '-a': shim_util.GcloudStorageFlag(gcloud_flag='-x'),
                  '-y': shim_util.GcloudStorageFlag(gcloud_flag='--yyy'),
              }),
      'get':
          shim_util.GcloudStorageMap(gcloud_command=['buckets', 'describe'],
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
        headers={},
        debug=1,
        trace_token=mock.ANY,
        parallel_operations=mock.ANY,
        bucket_storage_uri_class=mock.ANY,
        gsutil_api_class_map_factory=mock.MagicMock())

  def test_get_gcloud_storage_args_parses_command_and_flags(self):

    gcloud_args = self._fake_command.get_gcloud_storage_args()
    self.assertEqual(gcloud_args,
                     ['objects', 'fake', '--zip', 'opt1', '-x', 'arg1', 'arg2'])

  def test_get_gcloud_storage_args_parses_command_in_list_format(self):
    self._fake_command.gcloud_command = ['objects', 'fake']
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
        gcloud_command='some fake command as a string', flag_map={})
    with self.assertRaisesRegex(
        ValueError, 'Incorrect mapping found for "fake_shim" command'):
      self._fake_command.get_gcloud_storage_args()

  def test_raises_error_if_command_option_mapping_is_missing(self):
    self._fake_command.gcloud_storage_map = shim_util.GcloudStorageMap(
        gcloud_command=['fake'],
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

  def test_raises_error_if_flags_mapping_at_top_level_for_subcommand(self):
    fake_with_subcommand = FakeCommandWithSubCommandWithGcloudStorageMap(
        command_runner=mock.ANY,
        args=['set', '-y', 'opt1', '-a', 'arg1', 'arg2'],
        headers=mock.ANY,
        debug=mock.ANY,
        trace_token=mock.ANY,
        parallel_operations=mock.ANY,
        bucket_storage_uri_class=mock.ANY,
        gsutil_api_class_map_factory=mock.MagicMock())
    fake_with_subcommand.gcloud_storage_map.flag_map = {'a': 'b'}
    with self.assertRaisesRegex(
        ValueError,
        'Flags mapping should not be present at the top-level command'
        ' if a sub-command is used. Command: fake_with_sub'):
      fake_with_subcommand.get_gcloud_storage_args()


class TestTranslateToGcloudStorageIfRequested(testcase.GsUtilUnitTestCase):
  """Test Command.translate_to_gcloud_storage_if_requested method."""

  def setUp(self):
    super().setUp()
    self._fake_command = FakeCommandWithGcloudStorageMap(
        command_runner=mock.ANY,
        args=['-z', 'opt1', '-r', 'arg1', 'arg2'],
        headers={},
        debug=0,
        trace_token=None,
        parallel_operations=True,
        bucket_storage_uri_class=mock.ANY,
        gsutil_api_class_map_factory=mock.MagicMock())

  def test_returns_false_with_use_gcloud_storage_never(self):
    """Should not attempt translation."""
    with util.SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'False')]):
      with mock.patch.object(self._fake_command,
                             'get_gcloud_storage_args',
                             autospec=True) as mock_get_gcloud_storage_args:
        self.assertFalse(
            self._fake_command.translate_to_gcloud_storage_if_requested())
        self.assertFalse(mock_get_gcloud_storage_args.called)

  def test_returns_true_with_valid_gcloud_storage_map(self):
    """Should return True and perform the translation."""
    with _mock_boto_config({
        'GSUtil': {
            'use_gcloud_storage': 'always',
            'hidden_shim_mode': 'no_fallback'
        }
    }):
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

  def test_with_cloudsdk_root_dir_unset_and_gcloud_binary_path_set(self):
    """Should return True and perform the translation."""
    gcloud_path = os.path.join('fake_dir', 'bin', 'gcloud')
    with _mock_boto_config({
        'GSUtil': {
            'use_gcloud_storage': 'always',
            'hidden_shim_mode': 'no_fallback'
        }
    }):
      with util.SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': None,
          'GCLOUD_BINARY_PATH': gcloud_path,
      }):
        self.assertTrue(
            self._fake_command.translate_to_gcloud_storage_if_requested())
        # Verify translation.
        self.assertEqual(self._fake_command._translated_gcloud_storage_command,
                         [
                             gcloud_path, 'objects', 'fake', '--zip', 'opt1',
                             '-x', 'arg1', 'arg2'
                         ])

  def test_returns_false_if_invalid_use_gcloud_storage_value(self):
    with util.SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'invalid')
                                   ]):
      self.assertFalse(
          self._fake_command.translate_to_gcloud_storage_if_requested())

  def test_raises_error_if_invalid_hidden_shim_mode_value(self):
    with util.SetBotoConfigForTest([('GSUtil', 'hidden_shim_mode', 'invalid')]):
      with self.assertRaisesRegex(
          exception.CommandException,
          'CommandException: Invalid option specified for'
          ' GSUtil:use_gcloud_storage config setting. Should be one of:'
          ' no_fallback | dry_run | none'):
        self._fake_command.translate_to_gcloud_storage_if_requested()

  def test_raises_error_if_cloudsdk_root_dir_is_none(self):
    with util.SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                                    ('GSUtil', 'hidden_shim_mode',
                                     'no_fallback')]):
      with util.SetEnvironmentForTest({
          'CLOUDSDK_ROOT_DIR': None,
      }):
        with self.assertRaisesRegex(
            exception.CommandException,
            'CommandException: Requested to use "gcloud storage" but the '
            'gcloud binary path cannot be found. This might happen if you'
            ' attempt to use gsutil that was not installed via Cloud SDK.'
            ' You can manually set the `CLOUDSDK_ROOT_DIR` environment variable'
            ' to point to the google-cloud-sdk installation directory to'
            ' resolve the issue. Alternatively, you can set'
            ' `use_gcloud_storage=False` to disable running the command'
            ' using gcloud storage.'):
          self._fake_command.translate_to_gcloud_storage_if_requested()

  def test_raises_error_if_pass_credentials_to_gsutil_is_missing(self):
    with util.SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                                    ('GSUtil', 'hidden_shim_mode',
                                     'no_fallback')]):
      with util.SetEnvironmentForTest({
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': None
      }):
        with self.assertRaisesRegex(
            exception.CommandException,
            'CommandException: Requested to use "gcloud storage" but gsutil'
            ' is not using the same credentials as'
            ' gcloud. You can make gsutil use the same credentials'
            ' by running:\n'
            'fake_dir.bin.gcloud config set pass_credentials_to_gsutil True'):
          self._fake_command.translate_to_gcloud_storage_if_requested()

  def test_raises_error_if_gcloud_storage_map_missing(self):
    self._fake_command.gcloud_storage_map = None
    with util.SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                                    ('GSUtil', 'hidden_shim_mode',
                                     'no_fallback')]):
      with util.SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        with self.assertRaisesRegex(
            exception.CommandException,
            'CommandException: Command "fake_shim" cannot be translated to'
            ' gcloud storage because the translation mapping is missing.'):
          self._fake_command.translate_to_gcloud_storage_if_requested()

  def test_use_gcloud_storage_true_with_hidden_shim_mode_not_set(self):
    """Should not raise error."""
    with util.SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True')]):
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

  def test_dry_run_mode_prints_translated_command(self):
    """Should print the gcloud command and run gsutil."""
    with _mock_boto_config({
        'GSUtil': {
            'use_gcloud_storage': 'True',
            'hidden_shim_mode': 'dry_run'
        }
    }):
      with util.SetEnvironmentForTest({'CLOUDSDK_ROOT_DIR': 'fake_dir'}):
        stdout, mock_log_handler = self.RunCommand('fake_shim',
                                                   args=['arg1'],
                                                   return_stdout=True,
                                                   return_log_handler=True)
        self.assertIn(
            'Gcloud Storage Command: {} objects fake arg1'.format(
                os.path.join('fake_dir', 'bin', 'gcloud')),
            mock_log_handler.messages['info'])
        self.assertIn(
            'FakeCommandWithGcloudStorageMap called'.format(
                os.path.join('fake_dir', 'bin', 'gcloud')), stdout)

  def test_non_dry_mode_logs_translated_command_to_debug_logs(self):
    with _mock_boto_config({
        'GSUtil': {
            'use_gcloud_storage': 'always',
            'hidden_shim_mode': 'no_fallback'
        }
    }):
      with util.SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        with mock.patch.object(self._fake_command, 'logger',
                               autospec=True) as mock_logger:
          self._fake_command.translate_to_gcloud_storage_if_requested()
          # Verify translation.
          mock_logger.debug.assert_called_once_with(
              'Gcloud Storage Command: {} objects'
              ' fake --zip opt1 -x arg1 arg2'.format(
                  os.path.join('fake_dir', 'bin', 'gcloud')))

  def test_print_gcloud_storage_env_vars_in_dry_run_mode(self):
    """Should log the command and env vars to logger.info"""
    with mock.patch.object(self._fake_command, 'logger',
                           autospec=True) as mock_logger:
      self._fake_command._print_gcloud_storage_command_info(
          ['fake', 'gcloud', 'command'], {'fake_env_var': 'val'}, dry_run=True)
      expected_calls = [
          mock.call('Gcloud Storage Command: fake gcloud command'),
          mock.call('Environment variables for Gcloud Storage:'),
          mock.call('%s=%s', 'fake_env_var', 'val'),
      ]
      self.assertEqual(mock_logger.info.mock_calls, expected_calls)

  def test_top_level_flags_get_translated(self):
    """Should return True and perform the translation."""
    boto_config = {
        'GSUtil': {
            'use_gcloud_storage': 'always',
            'hidden_shim_mode': 'no_fallback'
        }
    }
    with _mock_boto_config(boto_config):
      with util.SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        fake_command = FakeCommandWithGcloudStorageMap(
            command_runner=mock.ANY,
            args=['arg1', 'arg2'],
            headers={},  # Headers will be tested separately.
            debug=3,  # -D option
            trace_token='fake_trace_token',
            user_project='fake_user_project',
            parallel_operations=False,  # Without the -m option.
            bucket_storage_uri_class=mock.ANY,
            gsutil_api_class_map_factory=mock.MagicMock())

        self.assertTrue(fake_command.translate_to_gcloud_storage_if_requested())
        # Verify translation.
        expected_gcloud_path = os.path.join('fake_dir', 'bin', 'gcloud')
        self.assertEqual(fake_command._translated_gcloud_storage_command, [
            expected_gcloud_path, 'objects', 'fake', 'arg1', 'arg2',
            '--verbosity', 'debug', '--billing-project=fake_user_project',
            '--trace-token=fake_trace_token'
        ])
        self.assertCountEqual(
            fake_command._translated_env_variables, {
                'CLOUDSDK_STORAGE_PROCESS_COUNT': '1',
                'CLOUDSDK_STORAGE_THREAD_COUNT': '1',
            })

  def test_parallel_operations_true_does_not_add_process_count_env_vars(self):
    with util.SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                                    ('GSUtil', 'hidden_shim_mode',
                                     'no_fallback')]):
      with util.SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        self._fake_command.parallel_operations = True
        self._fake_command.translate_to_gcloud_storage_if_requested()
        self.assertNotIn('CLOUDSDK_STORAGE_PROCESS_COUNT',
                         self._fake_command._translated_env_variables)
        self.assertNotIn('CLOUDSDK_STORAGE_THREAD_COUNT',
                         self._fake_command._translated_env_variables)

  def test_debug_value_4_adds_log_http_flag(self):
    # Debug level 4 represents the -DD option.
    with _mock_boto_config({
        'GSUtil': {
            'use_gcloud_storage': 'always',
            'hidden_shim_mode': 'no_fallback'
        }
    }):
      with util.SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        self._fake_command.debug = 4
        self._fake_command.translate_to_gcloud_storage_if_requested()
        self.assertEqual(self._fake_command._translated_gcloud_storage_command,
                         [
                             os.path.join('fake_dir', 'bin', 'gcloud'),
                             'objects', 'fake', '--zip', 'opt1', '-x', 'arg1',
                             'arg2', '--verbosity', 'debug', '--log-http'
                         ])

  @mock.patch.object(constants,
                     'IMPERSONATE_SERVICE_ACCOUNT',
                     new='fake_service_account')
  def test_impersonate_service_account_translation(self):
    """Should add the --impersonate-service-account flag."""
    with _mock_boto_config({
        'GSUtil': {
            'use_gcloud_storage': 'always',
            'hidden_shim_mode': 'no_fallback'
        }
    }):
      with util.SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        self._fake_command.translate_to_gcloud_storage_if_requested()
        self.assertEqual(
            self._fake_command._translated_gcloud_storage_command, [
                os.path.join('fake_dir', 'bin', 'gcloud'), 'objects', 'fake',
                '--zip', 'opt1', '-x', 'arg1', 'arg2',
                '--impersonate-service-account=fake_service_account'
            ])

  def test_quiet_mode_translation_adds_no_user_output_enabled_flag(self):
    with _mock_boto_config({
        'GSUtil': {
            'use_gcloud_storage': 'always',
            'hidden_shim_mode': 'no_fallback'
        }
    }):
      with util.SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        self._fake_command.quiet_mode = True
        self._fake_command.translate_to_gcloud_storage_if_requested()
        self.assertEqual(self._fake_command._translated_gcloud_storage_command,
                         [
                             os.path.join('fake_dir', 'bin', 'gcloud'),
                             'objects', 'fake', '--zip', 'opt1', '-x', 'arg1',
                             'arg2', '--no-user-output-enabled'
                         ])

  def test_returns_false_for_version_command(self):
    command = version.VersionCommand(
        command_runner=mock.ANY,
        args=[],
        headers={},
        debug=0,
        trace_token=None,
        parallel_operations=True,
        bucket_storage_uri_class=mock.ANY,
        gsutil_api_class_map_factory=mock.MagicMock())
    with util.SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                                    ('GSUtil', 'hidden_shim_mode',
                                     'no_fallback')]):
      with mock.patch.object(command, 'get_gcloud_storage_args',
                             autospec=True) as mock_get_gcloud_storage_args:
        self.assertFalse(command.translate_to_gcloud_storage_if_requested())
        self.assertFalse(mock_get_gcloud_storage_args.called)

  def test_returns_false_for_test_command(self):
    command = test.TestCommand(command_runner=mock.ANY,
                               args=[],
                               headers={},
                               debug=0,
                               trace_token=None,
                               parallel_operations=True,
                               bucket_storage_uri_class=mock.ANY,
                               gsutil_api_class_map_factory=mock.MagicMock())
    with util.SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                                    ('GSUtil', 'hidden_shim_mode',
                                     'no_fallback')]):
      with mock.patch.object(command, 'get_gcloud_storage_args',
                             autospec=True) as mock_get_gcloud_storage_args:
        self.assertFalse(command.translate_to_gcloud_storage_if_requested())
        self.assertFalse(mock_get_gcloud_storage_args.called)


class TestHeaderTranslation(testcase.GsUtilUnitTestCase):
  """Test gsutil header  translation."""

  def setUp(self):
    super().setUp()
    self._fake_command = FakeCommandWithGcloudStorageMap(
        command_runner=mock.ANY,
        args=['-z', 'opt1', '-r', 'arg1', 'arg2'],
        headers={},
        debug=0,
        trace_token=None,
        parallel_operations=True,
        bucket_storage_uri_class=mock.ANY,
        gsutil_api_class_map_factory=mock.MagicMock())

  @mock.patch.object(shim_util, 'DATA_TRANSFER_COMMANDS', new={'fake_shim'})
  def test_translated_headers_get_added_to_final_command(self):
    with _mock_boto_config({
        'GSUtil': {
            'use_gcloud_storage': 'always',
            'hidden_shim_mode': 'no_fallback'
        }
    }):
      with util.SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        fake_command = FakeCommandWithGcloudStorageMap(
            command_runner=mock.ANY,
            args=['arg1', 'arg2'],
            headers={'Content-Type': 'fake_val'},
            debug=1,
            trace_token=None,
            parallel_operations=mock.ANY,
            bucket_storage_uri_class=mock.ANY,
            gsutil_api_class_map_factory=mock.MagicMock())

        self.assertTrue(fake_command.translate_to_gcloud_storage_if_requested())
        self.assertEqual(fake_command._translated_gcloud_storage_command, [
            os.path.join('fake_dir', 'bin', 'gcloud'), 'objects', 'fake',
            'arg1', 'arg2', '--content-type=fake_val'
        ])

  @mock.patch.object(shim_util, 'DATA_TRANSFER_COMMANDS', new={'fake_shim'})
  def test_translate_headers_returns_correct_flags_for_data_transfer_command(
      self):
    self._fake_command.headers = {
        # Data tranfer related headers.
        'Cache-Control': 'fake_Cache_Control',
        'Content-Disposition': 'fake_Content-Disposition',
        'Content-Encoding': 'fake_Content-Encoding',
        'Content-Language': 'fake_Content-Language',
        'Content-Type': 'fake_Content-Type',
        'Content-MD5': 'fake_Content-MD5',
        'custom-time': 'fake_time',
        # Precondition headers.
        'x-goog-if-generation-match': 'fake_gen_match',
        'x-goog-if-metageneration-match': 'fake_metagen_match',
        # Custom metadata.
        'x-goog-meta-foo': 'fake_goog_meta',
        'x-amz-meta-foo': 'fake_amz_meta',
        'x-amz-foo': 'fake_amz_custom_header',
    }
    flags = self._fake_command._translate_headers()
    self.assertCountEqual(flags, [
        '--cache-control=fake_Cache_Control',
        '--content-disposition=fake_Content-Disposition',
        '--content-encoding=fake_Content-Encoding',
        '--content-language=fake_Content-Language',
        '--content-type=fake_Content-Type',
        '--content-md5=fake_Content-MD5',
        '--custom-time=fake_time',
        '--if-generation-match=fake_gen_match',
        '--if-metageneration-match=fake_metagen_match',
        '--add-custom-metadata=foo=fake_goog_meta',
        '--add-custom-metadata=foo=fake_amz_meta',
        '--add-custom-headers=x-amz-foo=fake_amz_custom_header',
    ])

  @mock.patch.object(shim_util, 'DATA_TRANSFER_COMMANDS', new={'fake_shim'})
  def test_translate_headers_for_data_transfer_command_with_invalid_header(
      self):
    """Should raise error."""
    self._fake_command.headers = {'invalid': 'value'}
    with self.assertRaisesRegex(
        exception.GcloudStorageTranslationError,
        'Header cannot be translated to a gcloud storage equivalent flag.'
        ' Invalid header: invalid:value'):
      self._fake_command._translate_headers()

  @mock.patch.object(shim_util,
                     'PRECONDITONS_ONLY_SUPPORTED_COMMANDS',
                     new={'fake_shim'})
  def test_translate_headers_for_precondition_supported_command_with_valid_header(
      self):
    self._fake_command.headers = {
        'x-goog-if-generation-match': 'fake_gen_match',
        'x-goog-if-metageneration-match': 'fake_metagen_match',
        # Custom metadata. These should be ignored.
        'x-goog-meta-foo': 'fake_goog_meta',
    }
    flags = self._fake_command._translate_headers()
    self.assertCountEqual(flags, [
        '--if-generation-match=fake_gen_match',
        '--if-metageneration-match=fake_metagen_match',
    ])

  @mock.patch.object(shim_util,
                     'PRECONDITONS_ONLY_SUPPORTED_COMMANDS',
                     new={'fake_shim'})
  def test_translate_headers_for_precondition_supported_command_with_invalid_header(
      self):
    """Should be ignored and not raise any error."""
    self._fake_command.headers = {'invalid': 'value'}
    self.assertEqual(self._fake_command._translate_headers(), [])

  def test_translate_headers_ignores_headers_for_commands_not_in_allowlist(
      self):
    # Allowlist is defined by the shim_util.DATA_TRANSFER_COMMANDS and
    # the shim_util.PRECONDITONS_ONLY_SUPPORTED_COMMANDS list.
    # The fake_shim command defined by self._fake_command is not part of
    # either of the list, and hence the headers must be ignored.
    self._fake_command.headers = {
        # Header from the DATA_TRANSFER_HEADERS list.
        'Cache-Control': 'fake_Cache_Control',
        # Header from the PRECONDITIONS_HEADERS list.
        'x-goog-if-generation-match': 'fake_gen_match',
        # Custom metadata. These should be ignored.
        'x-goog-meta-foo': 'fake_goog_meta',
    }
    self.assertEqual(self._fake_command._translate_headers(), [])

  @mock.patch.object(shim_util,
                     'PRECONDITONS_ONLY_SUPPORTED_COMMANDS',
                     new={'fake_shim'})
  def test_translate_headers_ignores_x_goog_api_version_header(self):
    self._fake_command.headers = {
        'x-goog-if-generation-match': 'fake_gen_match',
        'x-goog-api-version': '2',  # Should be ignored.
    }
    self.assertEqual(self._fake_command._translate_headers(),
                     ['--if-generation-match=fake_gen_match'])


class TestGetFlagFromHeader(testcase.GsUtilUnitTestCase):
  """Test Command.get_flag_from_header function.
  
  We only test the unset functionality because rest of the workflows have been
  already tested indirectly in TestHeaderTranslation.
  """

  def test_get_flag_from_header_with_unset_true_for_data_transfer_headers(self):
    # Ideally we should use parameterized, but avoiding adding a new dependency
    # just for the shim.
    headers_to_expected_flag_map = {
        'Cache-Control': '--clear-cache-control',
        'Content-Disposition': '--clear-content-disposition',
        'Content-Encoding': '--clear-content-encoding',
        'Content-Language': '--clear-content-language',
        'Content-Type': '--clear-content-type',
        'custom-time': '--clear-custom-time',
    }
    for header, expected_flag in headers_to_expected_flag_map.items():
      result = shim_util.get_flag_from_header(header, 'fake_val', unset=True)
      self.assertEqual(result, expected_flag)

  def test_get_flag_from_header_with_unset_true_for_precondition_headers(self):
    """Should return None."""
    # Ideally we should use parameterized, but avoiding adding a new dependency
    # just for the shim.
    for header in [
        'x-goog-if-generation-match',
        'x-goog-if-metageneration-match',
    ]:
      result = shim_util.get_flag_from_header(header, 'fake_val', unset=True)
      self.assertIsNone(result)

  def test_get_flag_from_header_with_unset_true_for_content_md5(self):
    """Should return None."""
    result = shim_util.get_flag_from_header('Content-MD5',
                                            'fake_val',
                                            unset=True)
    self.assertIsNone(result)

  def test_get_flag_from_header_with_unset_true_for_invalid_header(self):
    """Should return None."""
    result = shim_util.get_flag_from_header('invalid_header',
                                            'fake_val',
                                            unset=True)
    self.assertIsNone(result)

  def test_get_flag_from_header_with_unset_true_for_metadata_headers(self):
    """Should return --remove-custom-metadata flag."""
    headers_to_expected_flag_map = {
        'x-goog-meta-foo': '--remove-custom-metadata=foo',
        'x-amz-meta-foo': '--remove-custom-metadata=foo',
        'x-amz-foo': '--remove-custom-headers=x-amz-foo',
    }
    for header, expected_flag in headers_to_expected_flag_map.items():
      result = shim_util.get_flag_from_header(header, 'fake_val', unset=True)
      self.assertEqual(result, expected_flag)


class TestBotoTranslation(testcase.GsUtilUnitTestCase):
  """Test gsutil header  translation."""

  def setUp(self):
    super().setUp()
    self._fake_command = FakeCommandWithGcloudStorageMap(
        command_runner=mock.ANY,
        args=['-z', 'opt1', '-r', 'arg1', 'arg2'],
        headers={},
        debug=0,
        trace_token=None,
        parallel_operations=True,
        bucket_storage_uri_class=mock.ANY,
        gsutil_api_class_map_factory=mock.MagicMock())

  @mock.patch.object(shim_util, 'DATA_TRANSFER_COMMANDS', new={'fake_shim'})
  def test_translated_boto_config_gets_added(self):
    """Should add translated env vars as well flags."""
    with _mock_boto_config({
        'GSUtil': {
            'use_gcloud_storage': 'True',
            'hidden_shim_mode': 'no_fallback',
            'content_language': 'foo',
            'default_project_id': 'fake_project',
        }
    }):
      with util.SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        self.assertTrue(
            self._fake_command.translate_to_gcloud_storage_if_requested())
        # Verify translation.
        expected_gcloud_path = os.path.join('fake_dir', 'bin', 'gcloud')
        self.assertEqual(
            self._fake_command._translated_gcloud_storage_command, [
                expected_gcloud_path, 'objects', 'fake', '--zip', 'opt1', '-x',
                'arg1', 'arg2', '--content-language=foo'
            ])
        self.assertEqual(self._fake_command._translated_env_variables,
                         {'CLOUDSDK_CORE_PROJECT': 'fake_project'})

  def test_gcs_json_endpoint_translation(self):
    with _mock_boto_config({
        'Credentials': {
            'gs_json_host': 'foo_host',
            'gs_json_port': '1234',
            'json_api_version': 'v2',
        }
    }):
      flags, env_vars = self._fake_command._translate_boto_config()
      self.assertEqual(flags, [])
      self.assertEqual(
          env_vars, {
              'CLOUDSDK_API_ENDPOINT_OVERRIDES_STORAGE':
                  'https://foo_host:1234/storage/v2',
          })

  def test_gcs_json_endpoint_translation_with_missing_port(self):
    with _mock_boto_config({
        'Credentials': {
            'gs_json_host': 'foo_host',
            'json_api_version': 'v2',
        }
    }):
      flags, env_vars = self._fake_command._translate_boto_config()
      self.assertEqual(flags, [])
      self.assertEqual(env_vars, {
          'CLOUDSDK_API_ENDPOINT_OVERRIDES_STORAGE':
              'https://foo_host/storage/v2',
      })

  def test_gcs_json_endpoint_translation_usees_default_version_v1(self):
    with _mock_boto_config(
        {'Credentials': {
            'gs_json_host': 'foo_host',
            'gs_json_port': '1234',
        }}):
      flags, env_vars = self._fake_command._translate_boto_config()
      self.assertEqual(flags, [])
      self.assertEqual(
          env_vars, {
              'CLOUDSDK_API_ENDPOINT_OVERRIDES_STORAGE':
                  'https://foo_host:1234/storage/v1'
          })

  def test_s3_endpoint_translation(self):
    with _mock_boto_config(
        {'Credentials': {
            's3_host': 's3_host',
            's3_port': '1234',
        }}):
      flags, env_vars = self._fake_command._translate_boto_config()
      self.assertEqual(flags, [])
      self.assertEqual(
          env_vars,
          {'CLOUDSDK_STORAGE_S3_ENDPOINT_URL': 'https://s3_host:1234'})

  def test_s3_endpoint_translation_with_missing_port(self):
    with _mock_boto_config({'Credentials': {'s3_host': 's3_host',}}):
      flags, env_vars = self._fake_command._translate_boto_config()
      self.assertEqual(flags, [])
      self.assertEqual(env_vars,
                       {'CLOUDSDK_STORAGE_S3_ENDPOINT_URL': 'https://s3_host'})

  @mock.patch.object(shim_util,
                     'ENCRYPTION_SUPPORTED_COMMANDS',
                     new={'fake_shim'})
  def test_encryption_key_gets_converted_to_flag(self):
    with _mock_boto_config({'GSUtil': {'encryption_key': 'fake_key'}}):
      flags, _ = self._fake_command._translate_boto_config()
      self.assertEqual(flags, ['--encryption-key=fake_key'])

  @mock.patch.object(shim_util,
                     'ENCRYPTION_SUPPORTED_COMMANDS',
                     new={'fake_shim'})
  def test_decryption_key_gets_converted_to_flag(self):
    with _mock_boto_config({
        'GSUtil':
            collections.OrderedDict([
                ('decryption_key1', 'key1'),
                ('decryption_key12', 'key12'),
                ('decryption_key100', 'key100'),
            ])
    }):
      flags, _ = self._fake_command._translate_boto_config()
      self.assertEqual(flags, ['--decryption-keys=key1,key12,key100'])

  def test_boto_config_translation_for_supported_fields(self):
    with _mock_boto_config({
        'Credentials': {
            'aws_access_key_id': 'AWS_ACCESS_KEY_ID_value',
            'aws_secret_access_key': 'AWS_SECRET_ACCESS_KEY_value',
            'use_client_certificate': True,
        },
        'Boto': {
            'proxy': 'CLOUDSDK_PROXY_ADDRESS_value',
            'proxy_type': 'CLOUDSDK_PROXY_TYPE_value',
            'proxy_port': 'CLOUDSDK_PROXY_PORT_value',
            'proxy_user': 'CLOUDSDK_PROXY_USERNAME_value',
            'proxy_pass': 'CLOUDSDK_PROXY_PASSWORD_value',
            'proxy_rdns': 'CLOUDSDK_PROXY_RDNS_value',
            'http_socket_timeout': 'HTTP_TIMEOUT_value',
            'ca_certificates_file': 'CA_CERTS_FILE_value',
            'https_validate_certificates': False,
            'max_retry_delay': 'BASE_RETRY_DELAY_value',
            'num_retries': 'MAX_RETRIES_value',
        },
        'GSUtil': {
            'check_hashes': 'CHECK_HASHES_value',
            'default_project_id': 'CLOUDSDK_CORE_PROJECT_value',
            'disable_analytics_prompt': 'USAGE_REPORTING_value',
            'use_magicfile': 'USE_MAGICFILE_value',
            'parallel_composite_upload_threshold': '100M',
        },
        'OAuth2': {
            'client_id': 'CLOUDSDK_AUTH_CLIENT_ID_value',
            'client_secret': 'AUTH_CLIENT_SECRET_value',
            'provider_authorization_uri': 'CLOUDSDK_AUTH_AUTH_HOST_value',
            'provider_token_uri': 'CLOUDSDK_AUTH_TOKEN_HOST_value',
        },
    }):
      flags, env_vars = self._fake_command._translate_boto_config()
      self.assertEqual(flags, [])
      self.maxDiff = None
      self.assertDictEqual(
          env_vars, {
              'AWS_ACCESS_KEY_ID': 'AWS_ACCESS_KEY_ID_value',
              'AWS_SECRET_ACCESS_KEY': 'AWS_SECRET_ACCESS_KEY_value',
              'CLOUDSDK_CONTEXT_AWARE_USE_CLIENT_CERTIFICATE': True,
              'CLOUDSDK_PROXY_ADDRESS': 'CLOUDSDK_PROXY_ADDRESS_value',
              'CLOUDSDK_PROXY_ADDRESS': 'CLOUDSDK_PROXY_ADDRESS_value',
              'CLOUDSDK_PROXY_TYPE': 'CLOUDSDK_PROXY_TYPE_value',
              'CLOUDSDK_PROXY_PORT': 'CLOUDSDK_PROXY_PORT_value',
              'CLOUDSDK_PROXY_USERNAME': 'CLOUDSDK_PROXY_USERNAME_value',
              'CLOUDSDK_PROXY_PASSWORD': 'CLOUDSDK_PROXY_PASSWORD_value',
              'CLOUDSDK_PROXY_RDNS': 'CLOUDSDK_PROXY_RDNS_value',
              'CLOUDSDK_CORE_HTTP_TIMEOUT': 'HTTP_TIMEOUT_value',
              'CLOUDSDK_CORE_CUSTOM_CA_CERTS_FILE': 'CA_CERTS_FILE_value',
              'CLOUDSDK_AUTH_DISABLE_SSL_VALIDATION': True,
              'CLOUDSDK_STORAGE_BASE_RETRY_DELAY': 'BASE_RETRY_DELAY_value',
              'CLOUDSDK_STORAGE_MAX_RETRIES': 'MAX_RETRIES_value',
              'CLOUDSDK_STORAGE_CHECK_HASHES': 'CHECK_HASHES_value',
              'CLOUDSDK_CORE_PROJECT': 'CLOUDSDK_CORE_PROJECT_value',
              'CLOUDSDK_CORE_DISABLE_USAGE_REPORTING': 'USAGE_REPORTING_value',
              'CLOUDSDK_STORAGE_USE_MAGICFILE': 'USE_MAGICFILE_value',
              'CLOUDSDK_STORAGE_PARALLEL_COMPOSITE_UPLOAD_THRESHOLD': '100M',
              'CLOUDSDK_AUTH_CLIENT_ID': 'CLOUDSDK_AUTH_CLIENT_ID_value',
              'CLOUDSDK_AUTH_CLIENT_SECRET': 'AUTH_CLIENT_SECRET_value',
              'CLOUDSDK_AUTH_AUTH_HOST': 'CLOUDSDK_AUTH_AUTH_HOST_value',
              'CLOUDSDK_AUTH_TOKEN_HOST': 'CLOUDSDK_AUTH_TOKEN_HOST_value',
          })

  def test_missing_mappging_gets_ignored(self):
    with _mock_boto_config({'GSUtil': {'unsupported_field': 'foo'}}):
      flags, env_vars = self._fake_command._translate_boto_config()
      self.assertEqual(flags, [])
      self.assertEqual(env_vars, {})

  def test_truthy_https_validate_certificates(self):
    """Should not set CLOUDSDK_AUTH_DISABLE_SSL_VALIDATION"""
    with _mock_boto_config({'GSUtil': {'https_validate_certificates': True}}):
      flags, env_vars = self._fake_command._translate_boto_config()
      self.assertEqual(flags, [])
      self.assertEqual(env_vars, {})

  def test_missing_required_fields_log_error(self):
    with _mock_boto_config({
        'GSUtil': {
            'stet_binary_path': 'foo_bin',
            'stet_config_path': 'foo_config'
        }
    }):
      with mock.patch.object(self._fake_command.logger, 'error',
                             autospec=True) as mock_logger:
        flags, env_vars = self._fake_command._translate_boto_config()
        self.assertEqual(flags, [])
        self.assertEqual(env_vars, {})
        self.assertCountEqual(mock_logger.mock_calls, [
            mock.call('The boto config field GSUtil:stet_binary_path cannot be'
                      ' translated to gcloud storage equivalent.'),
            mock.call('The boto config field GSUtil:stet_config_path cannot be'
                      ' translated to gcloud storage equivalent.')
        ])


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
    with util.SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                                    ('GSUtil', 'hidden_shim_mode',
                                     'no_fallback')]):
      with util.SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': 'fake_dir',
      }):
        command_instance._translated_env_variables = {
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


class TestShimE2E(testcase.GsUtilIntegrationTestCase):

  def test_runs_gcloud_storage_if_use_gcloud_storage_true(self):
    with util.SetBotoConfigForTest([('GSUtil', 'use_gcloud_storage', 'True'),
                                    ('GSUtil', 'hidden_shim_mode',
                                     'no_fallback')]):
      with util.SetEnvironmentForTest({
          'CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL': 'True',
          'CLOUDSDK_ROOT_DIR': None,
      }):
        stderr = self.RunGsUtil(['-D', 'ls'],
                                return_stderr=True,
                                expected_status=1)

        # This is a proxy to ensure that the test attempted to call
        # gcloud binary.
        self.assertIn('gcloud binary path cannot be found', stderr)
