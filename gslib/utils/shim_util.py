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
import os
import subprocess

from boto import config
from gslib import exception

VALID_USE_GCLOUD_STORAGE_VALUES = (
    'never',
    'if_available_else_skip',
    'always',
    'dry_run',
)


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
