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
"""Helper for shim used to translate gsutil command to gcloud storage."""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

import collections
import enum
import os
import subprocess

from boto import config
from gslib import exception


class USE_GCLOUD_STORAGE_VALUE(enum.Enum):
  NEVER = 'never'
  IF_AVAILABLE_ELSE_SKIP = 'if_available_else_skip'
  ALWAYS = 'always'
  DRY_RUN = 'dry_run'


class GcloudStorageFlag(object):

  def __init__(self, gcloud_flag, supports_output_translation=False):
    """Initializes GcloudStorageFlag.
    
    Args:
      gcloud_flag (str): The name of the gcloud flag.
      support_output_translation (bool): If True, this flag in gcloud storage
        supports printing gsutil formatted output.
    """
    self.gcloud_flag = gcloud_flag
    self.supports_output_translation = supports_output_translation


class GcloudStorageMap(object):
  """Mapping to translate gsutil command to its gcloud storage equivalent."""

  def __init__(self,
               gcloud_command,
               flag_map,
               supports_output_translation=False):
    """Intalizes GcloudStorageMap.
    
    Args:
      gcloud_command (dict|str): The corresponding name of the command to be
        called in gcloud. If this command supports sub-commands, then this 
        field must be a dict of sub-command-name:GcloudStorageMap pairs.
      flag_map (dict): A dict of str to GcloudStorageFlag. Mapping of gsutil
        flags to their equivalent gcloud storage flag names.
      supports_output_translation (bool): Indicates if the corresponding
        gcloud storage command supports the printing gsutil formatted output.
    """
    self.gcloud_command = gcloud_command
    self.flag_map = flag_map
    self.supports_output_translation = supports_output_translation


def _get_gcloud_binary_path():
  cloudsdk_root = os.environ.get('CLOUDSDK_ROOT_DIR')
  if cloudsdk_root is None:
    raise exception.GcloudStorageTranslationError(
        'Gcloud binary path cannot be found.')
  return os.path.join(cloudsdk_root, 'bin', 'gcloud')


class GcloudStorageCommandMixin(object):
  """Provides gcloud storage translation functionality.
  
  The command.Command class must inherit this class in order to support
  converting the gsutil command to it's gcloud storage equivalent.
  """
  # Mapping for translating gsutil command to gcloud storage.
  gcloud_storage_map = None

  def __init__(self):
    self._translated_gcloud_storage_command = None
    self._translated_env_variables = None

  def _get_gcloud_storage_args(self, sub_opts, gsutil_args, gcloud_storage_map):
    if gcloud_storage_map is None:
      raise exception.GcloudStorageTranslationError(
          'Command "{}" cannot be translated to gcloud storage because the'
          ' translation mapping is missing.'.format(self.command_name))
    args = []
    if isinstance(gcloud_storage_map.gcloud_command, str):
      args = gcloud_storage_map.gcloud_command.split()
    elif isinstance(gcloud_storage_map.gcloud_command, dict):
      # If a command has sub-commands, e.g gsutil pap set, gsutil pap get.
      # All the flags mapping must be present in the subcommand's map
      # because gsutil does not have command specific flags
      # if sub-commands are present.
      if gcloud_storage_map.flag_map:
        raise ValueError(
            'Flags mapping should not be present at the top-level command if '
            'a sub-command is used. Command: {}.'.format(self.command_name))
      sub_command = gsutil_args[0]
      sub_opts, parsed_args = self.ParseSubOpts(
          args=gsutil_args[1:], should_update_sub_opts_and_args=False)
      return self._get_gcloud_storage_args(
          sub_opts, parsed_args,
          gcloud_storage_map.gcloud_command.get(sub_command))
    else:
      raise ValueError('Incorrect mapping found for "{}" command'.format(
          self.command_name))

    if sub_opts:
      for option, value in sub_opts:
        if option not in gcloud_storage_map.flag_map:
          raise exception.GcloudStorageTranslationError(
              'Command option "{}" cannot be translated to'
              ' gcloud storage'.format(option))
        args.append(gcloud_storage_map.flag_map[option].gcloud_flag)
        if value != '':
          # Empty string represents that the user did not passed in a value
          # for the flag.
          args.append(value)
    return args + gsutil_args

  def get_gcloud_storage_args(self):
    """Translates the gsutil command flags to gcloud storage flags.

    It uses the command_spec.gcloud_storage_map field that provides the
    translation mapping for all the flags.
    
    Returns:
      A list of all the options and arguments that can be used with the
        equivalent gcloud storage command.
    Raises:
      GcloudStorageTranslationError: If a flag or command cannot be translated.
      ValueError: If there is any issue with the mapping provided by
        GcloudStorageMap.
    """
    return self._get_gcloud_storage_args(self.sub_opts, self.args,
                                         self.gcloud_storage_map)

  def _print_gcloud_storage_command_info(self,
                                         gcloud_command,
                                         env_variables,
                                         dry_run=False):
    logger_func = self.logger.info if dry_run else self.logger.debug
    logger_func('Gcloud Storage Command: {}'.format(' '.join(gcloud_command)))
    if env_variables:
      logger_func('Environment variables for Gcloud Storage:')
      for k, v in env_variables.items():
        logger_func('%s=%s', k, v)

  def translate_to_gcloud_storage_if_requested(self):
    """Translates the gsutil command to gcloud storage equivalent.

    The translated commands get stored at
    self._translated_gcloud_storage_command.
    This command also translate the boto config, which gets stored as a dict
    at self._translated_env_variables
    
    Returns:
      True if the command was successfully translated, else False.
    """
    try:
      use_gcloud_storage = USE_GCLOUD_STORAGE_VALUE(
          config.get('GSUtil', 'use_gcloud_storage', 'never'))
    except ValueError:
      raise exception.CommandException(
          'Invalid option specified for'
          ' GSUtil:use_gcloud_storage config setting. Should be one of: {}'.
          format(' | '.join([x.value for x in USE_GCLOUD_STORAGE_VALUE])))
    if use_gcloud_storage != USE_GCLOUD_STORAGE_VALUE.NEVER:
      try:
        # TODO(b/206143429) Get top level flags.
        top_level_flags = []

        gcloud_binary_path = _get_gcloud_binary_path()
        gcloud_storage_command = ([gcloud_binary_path] +
                                  self.get_gcloud_storage_args() +
                                  top_level_flags)
        # TODO(b/206149936): Translate boto config to CLOUDSDK envs.
        env_variables = {}
        if use_gcloud_storage == USE_GCLOUD_STORAGE_VALUE.DRY_RUN:
          self._print_gcloud_storage_command_info(gcloud_storage_command,
                                                  env_variables,
                                                  dry_run=True)
        elif not os.environ.get('CLOUDSDK_CORE_PASS_CREDENTIALS_TO_GSUTIL'):
          raise exception.GcloudStorageTranslationError(
              'Requested to use "gcloud storage" but gsutil is not using the'
              ' same credentials as gcloud.'
              ' You can make gsutil use the same credentials by running:\n'
              '{} config set pass_credentials_to_gsutil True'.format(
                  gcloud_binary_path))
        else:
          self._print_gcloud_storage_command_info(gcloud_storage_command,
                                                  env_variables)
          self._translated_gcloud_storage_command = gcloud_storage_command
          self._translated_env_variables = env_variables
          return True
      except exception.GcloudStorageTranslationError as e:
        if use_gcloud_storage == USE_GCLOUD_STORAGE_VALUE.ALWAYS:
          raise exception.CommandException(e)
        # For all other cases, we want to run gsutil.
        self.logger.error(
            'Cannot translate gsutil command to gcloud storage.'
            ' Going to run gsutil command. Error: %s', e)
    return False

  def run_gcloud_storage(self):
    subprocess_envs = os.environ.copy()
    subprocess_envs.update(self._translated_env_variables)
    process = subprocess.run(self._translated_gcloud_storage_command,
                             env=subprocess_envs)
    return process.returncode
