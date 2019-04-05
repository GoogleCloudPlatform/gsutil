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
"""Utility functions to ensure the correct version of Python is used."""

import sys
from sys import version_info as SYS_VER

from gslib.utils import constants


def check_python_version_support():
  """Exit if gsutil is being run in an incompatible version of Python.

  This function compares the running version of cPython and against the list
  of supported python versions maintained in the constants file. If the running
  version is less than any of the supported versions, exit.

  Versions of Python greater than those listed in the currently supported
  versions are implicitly allowed.
  """
  supported = constants.SUPPORTED_PYTHON_VERSIONS

  def _get_supported_version_strings():
    versions = []
    for major, minor_tuple in supported.items():
      for minor in minor_tuple:
        versions.append('.'.join([str(major), str(minor)]))
    return versions

  def _get_error_string():
    versions = '\n'.join(_get_supported_versions())
    current_version_str = '.'.join([SYS_VER.major, SYS_VER.minor])
    error = ('{sys_ver} is not a supported version of Python. gsutil must be'
             'run by one of the following verions of Python or greater:\n'
             '{versions}'
             )
    return error.format(sys_ver=current_version_str, versions=versions)

  def _exit_unsupported():
    error = _get_error_string()
    sys.stderr.write(error)
    exit(1)


  if SYS_VER.major not in supported:
    exit_unsupported()
  if SYS_VER.minor < supported[SYS_VER.major][0]:
    exit_unsupported()
  if SYS_VER.minor > supported[SYS_VER.major][-1]:
    return True
  if SYS_VER.minor in supported[SYS_VER.major]:
    return True

