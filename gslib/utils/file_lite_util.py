# -*- coding: utf-8 -*-
# Copyright 2018 Google Inc. All Rights Reserved.
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
"""Shared utility structures and methods for interacting with the filesystem.

The methods in this module should be limited to simple tasks like creating
directories, getting information about existing files, etc.
"""

import errno
import os


def CreateDirIfNeeded(dir_path, mode=0777):
  """Creates a directory, suppressing already-exists errors."""
  if not os.path.exists(dir_path):
    try:
      # Unfortunately, even though we catch and ignore EEXIST, this call will
      # output a (needless) error message (no way to avoid that in Python).
      os.makedirs(dir_path, mode)
    # Ignore 'already exists' in case user tried to start up several
    # resumable uploads concurrently from a machine where no tracker dir had
    # yet been created.
    except OSError as e:
      if e.errno != errno.EEXIST:
        raise



