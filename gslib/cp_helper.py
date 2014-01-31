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
"""Helper functions for copy functionality.

Currently, the cp command and boto_translation use this functionality.
"""

from hashlib import md5
import re
import sys

from boto import config
import crcmod

from gslib.exception import CommandException
from gslib.util import UsingCrcmodExtension


SLOW_CRC_WARNING = """
WARNING: Downloading this composite object requires integrity checking with
CRC32c, but your crcmod installation isn't using the module's C extension,
so the hash computation will likely throttle download performance. For help
installing the extension, please see:
  $ gsutil help crcmod
To disable slow integrity checking, see the "check_hashes" option in your
boto config file.
"""

SLOW_CRC_EXCEPTION_TEXT = """
Downloading this composite object requires integrity checking with CRC32c,
but your crcmod installation isn't using the module's C extension, so the
hash computation will likely throttle download performance. For help
installing the extension, please see:
  $ gsutil help crcmod
To download regardless of crcmod performance or to skip slow integrity
checks, see the "check_hashes" option in your boto config file."""

SLOW_CRC_EXCEPTION = CommandException(SLOW_CRC_EXCEPTION_TEXT)

NO_HASH_CHECK_WARNING = """
WARNING: This download will not be validated since your crcmod installation
doesn't use the module's C extension, so the hash computation would likely
throttle download performance. For help in installing the extension, please
see:
  $ gsutil help crcmod
To force integrity checking, see the "check_hashes" option in your boto config
file.
"""

NO_SERVER_HASH_EXCEPTION_TEXT = """
This object has no server-supplied hash for performing integrity
checks. To skip integrity checking for such objects, see the "check_hashes"
option in your boto config file."""

NO_SERVER_HASH_EXCEPTION = CommandException(NO_SERVER_HASH_EXCEPTION_TEXT)

NO_SERVER_HASH_WARNING = """
WARNING: This object has no server-supplied hash for performing integrity
checks. To force integrity checking, see the "check_hashes" option in your
boto config file.
"""


def GetMD5FromETag(src_etag):
  """Returns an MD5 from the etag iff the etag is a valid MD5 hash.

  Args:
    src_etag: Object etag for which to return the MD5.

  Returns:
    MD5 in hex string format, or None.
  """
  if src_etag:
    possible_md5 = src_etag.strip('"\'').lower()
    if re.match(r'^[0-9a-f]{32}$', possible_md5):
      return possible_md5


def GetHashAlgs(src_etag=None, src_md5=False, src_crc32c=False):
  """Returns a dict of hash algorithms for validating an object.

  Args:
    src_etag: Etag for the source object, if present - possibly an MD5.
    src_md5: If True, source object has an md5 hash.
    src_crc32c: If True, source object has a crc32c hash.

  Returns:
    Dict of (string, hash algorithm).

  Raises:
    CommandException if hash algorithms satisfying the boto config file
    cannot be returned.
  """
  hash_algs = {}
  check_hashes_config = config.get(
      'GSUtil', 'check_hashes', 'if_fast_else_fail')
  if check_hashes_config == 'never':
    return hash_algs
  if GetMD5FromETag(src_etag):
    hash_algs['md5'] = md5
  if src_md5:
    hash_algs['md5'] = md5
  # If the cloud provider supplies a CRC, we'll compute a checksum to
  # validate if we're using a native crcmod installation or MD5 isn't
  # offered as an alternative.
  if src_crc32c:
    if UsingCrcmodExtension(crcmod):
      hash_algs['crc32c'] = lambda: crcmod.predefined.Crc('crc-32c')
    elif not hash_algs:
      if check_hashes_config == 'if_fast_else_fail':
        raise SLOW_CRC_EXCEPTION
      elif check_hashes_config == 'if_fast_else_skip':
        sys.stderr.write(NO_HASH_CHECK_WARNING)
      elif check_hashes_config == 'always':
        sys.stderr.write(SLOW_CRC_WARNING)
        hash_algs['crc32c'] = lambda: crcmod.predefined.Crc('crc-32c')
      else:
        raise CommandException(
            'Your boto config \'check_hashes\' option is misconfigured.')

  if not hash_algs:
    if check_hashes_config == 'if_fast_else_skip':
      sys.stderr.write(NO_SERVER_HASH_WARNING)
    else:
      raise NO_SERVER_HASH_EXCEPTION
  return hash_algs


def GetDownloadSerializationDict(src_obj_metadata):
  """Returns a baseline serialization dict from the source object metadata.

  There are four entries:
    auto_transfer: JSON-specific field, always False.
    progress: How much of the download has already been completed. Caller
              should override this value if the download is being resumed.
    total_size: Total object size.
    url: Implementation-specific field used for saving a metadata get call.
         For JSON, this the download URL of the object.
         For XML, this is a pickled boto key.

  Args:
    src_obj_metadata: Object to be downloaded.

  Returns:
    Serialization dict for use with Cloud API GetObjectMedia.
  """
  return {
      'auto_transfer': 'False',
      'progress': 0,
      'total_size': src_obj_metadata.size,
      'url': src_obj_metadata.mediaLink
  }
