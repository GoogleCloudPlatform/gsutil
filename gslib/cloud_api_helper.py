# Copyright 2014 Google Inc. All Rights Reserved.
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
"""Helper functions for Cloud API implementations."""

from gslib.cloud_api import ArgumentException


def ValidateDstObjectMetadata(dst_obj_metadata):
  """Ensures dst_obj_metadata supplies the needed fields for copy and insert.

  Args:
    dst_obj_metadata: Metadata to validate.

  Raises:
    ArgumentException if metadata is invalid.
  """
  if not dst_obj_metadata:
    raise ArgumentException(
        "No object metadata supplied for destination object.")
  if not dst_obj_metadata.name:
    raise ArgumentException(
        "Object metadata supplied for destination object had no object name.")
  if not dst_obj_metadata.bucket:
    raise ArgumentException(
        "Object metadata supplied for destination object had no bucket name.")


  