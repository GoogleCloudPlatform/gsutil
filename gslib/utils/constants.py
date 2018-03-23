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
"""Shared, hard-coded constants.

A constant should not be placed in this file if:
- it requires complicated or conditional logic to initialize.
- it requires importing any modules outside of the Python standard library. This
  helps reduce dependency graph complexity and the chance of cyclic deps.
- it is only used in one file (in which case it should be defined within that
  module).
- it semantically belongs somewhere else (e.g. 'BYTES_PER_KIB' would belong in
  unit_util.py).
"""

import sys

GSUTIL_PUB_TARBALL = 'gs://pub/gsutil.tar.gz'
NO_MAX = sys.maxint
RELEASE_NOTES_URL = 'https://pub.storage.googleapis.com/gsutil_ReleaseNotes.txt'
# By default, the timeout for SSL read errors is infinite. This could
# cause gsutil to hang on network disconnect, so pick a more reasonable
# timeout.
SSL_TIMEOUT_SEC = 60
UTF8 = 'utf-8'
WINDOWS_1252 = 'cp1252'
