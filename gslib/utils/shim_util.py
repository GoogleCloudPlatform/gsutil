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
from posixpath import expanduser
import subprocess

from boto import config
from gslib import exception
from gslib.utils import constants


class USE_GCLOUD_STORAGE_VALUE(enum.Enum):
  NEVER = 'never'
  IF_AVAILABLE_ELSE_SKIP = 'if_available_else_skip'
  ALWAYS = 'always'
  DRY_RUN = 'dry_run'


# Required for headers translation.
DATA_TRANSFER_COMMANDS = frozenset(['cp', 'mv', 'rsync'])
PRECONDITONS_ONLY_SUPPORTED_COMMANDS = frozenset(
    ['compose', 'rewrite', 'rm', 'retention'])
DATA_TRANSFER_HEADERS = frozenset([
    'cache-control',
    'content-disposition',
    'content-encoding',
    'content-md5',
    'content-language',
    'content-type',
    'custom-time',
])
PRECONDITIONS_HEADERS = frozenset(
    ['x-goog-if-generation-match', 'x-goog-if-metageneration-match'])


def get_flag_from_header(header_key_raw, header_value, unset=False):
  """Returns the gcloud storage flag for the given gsutil header.
  
  Args:
    header_key_raw: The header key.
    header_value: The header value
    unset: If True, the equivalent clear/remove flag is returned instead of the
      setter flag. This only applies to setmeta.

  Returns:
    A string representing the equivalent gcloud storage flag and value, if
      translation is possible, else returns None.
    
  Examples:
    >> get_flag_from_header('Cache-Control', 'val')
    --cache-control=val

    >> get_flag_from_header('x-goog-meta-foo', 'val')
    --add-custom-metadata=foo=val

    >> get_flag_from_header('x-goog-meta-foo', 'val', unset=True)
    --remove-custom-metadata=foo

  """
  header = header_key_raw.lower()
  if header in PRECONDITIONS_HEADERS:
    flag_name = header.lstrip('x-goog-')
  elif header in DATA_TRANSFER_HEADERS:
    flag_name = header
  else:
    flag_name = None

  if flag_name is not None:
    if unset:
      if header in PRECONDITIONS_HEADERS or header == 'content-md5':
        # Precondition headers and content-md5 cannot be cleared.
        return None
      else:
        return '--clear-' + flag_name
    return '--{}={}'.format(flag_name, header_value)

  for header_prefix in ('x-goog-meta-', 'x-amz-meta-'):
    if header.startswith(header_prefix):
      metadata_key = header.lstrip(header_prefix)
      if unset:
        return '--remove-custom-metadata=' + metadata_key
      else:
        return '--add-custom-metadata={}={}'.format(metadata_key, header_value)

  if header.startswith('x-amz-'):
    # Send the entire header as it is.
    if unset:
      return '--remove-custom-headers=' + header
    else:
      return '--add-custom-headers={}={}'.format(header, header_value)

  return None


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

  def _translate_top_level_flags(self):
    """Translates gsutil's top level flags.

    Gsutil specifies the headers (-h) and boto config (-o) as top level flags
    as well, but we handle those separately.

    Returns:
      A tuple. The first item is a list of top level flags that can be appended
        to the gcloud storage command. The second item is a dict of environment
        variables that can be set for the gcloud storage command execution.
    """
    top_level_flags = []
    env_variables = {}
    if self.debug >= 3:
      top_level_flags.extend(['--verbosity', 'debug'])
    if self.debug == 4:
      top_level_flags.append('--log-http')
    if self.quiet_mode:
      top_level_flags.append('--no-user-output-enabled')
    if self.user_project:
      top_level_flags.append('--billing-project=' + self.user_project)
    if self.trace_token:
      top_level_flags.append('--trace-token=' + self.trace_token)
    if constants.IMPERSONATE_SERVICE_ACCOUNT:
      top_level_flags.append('--impersonate-service-account=' +
                             constants.IMPERSONATE_SERVICE_ACCOUNT)
    # TODO(b/208294509) Add --perf-trace-token translation.
    if not self.parallel_operations:
      # TODO(b/208301084) Set the --sequential flag instead.
      env_variables['CLOUDSDK_STORAGE_THREAD_COUNT'] = '1'
      env_variables['CLOUDSDK_STORAGE_PROCESS_COUNT'] = '1'
    return top_level_flags, env_variables

  def _translate_headers(self):
    """Translates gsutil headers to equivalent gcloud storage flags."""
    flags = []
    for header_key_raw, header_value in self.headers.items():
      header_key = header_key_raw.lower()
      if header_key == 'x-goog-api-version':
        # Gsutil adds this header. We don't have to translate it for gcloud.
        continue
      flag = get_flag_from_header(header_key, header_value)
      if self.command_name in DATA_TRANSFER_COMMANDS:
        if flag is None:
          raise exception.GcloudStorageTranslationError(
              'Header cannot be translated to a gcloud storage equivalent'
              ' flag. Invalid header: {}:{}'.format(header_key, header_value))
        else:
          flags.append(flag)
      elif (self.command_name in PRECONDITONS_ONLY_SUPPORTED_COMMANDS and
            header_key in PRECONDITIONS_HEADERS):
        flags.append(flag)
      # We ignore the headers for all other cases, so does gsutil.
    return flags

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
    if self.command_name == 'version':
      # Running any command in debug mode will lead to calling gsutil version
      # command. We don't want to translate the version command as this
      # should always reflect the version that gsutil is using.
      return False
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
        top_level_flags, env_variables = self._translate_top_level_flags()
        header_flags = self._translate_headers()

        gcloud_binary_path = _get_gcloud_binary_path()
        gcloud_storage_command = ([gcloud_binary_path] +
                                  self.get_gcloud_storage_args() +
                                  top_level_flags + header_flags)
        # TODO(b/206149936): Translate boto config to CLOUDSDK envs.
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
