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

import base64
import binascii
from hashlib import md5
import re
import sys

from boto import config
import crcmod

from gslib.exception import CommandException
from gslib.util import DEFAULT_FILE_BUFFER_SIZE
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
checks, see the "check_hashes" option in your boto config file.
NOTE: It is strongly recommended that you not disable integrity checks. Doing so
could allow data corruption to go undetected during uploading/downloading."""

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
%s has no server-supplied hash for performing integrity checks. To skip
integrity checking for such objects, see the "check_hashes" option in your boto
config file."""

NO_SERVER_HASH_WARNING = """
WARNING: This object has no server-supplied hash for performing integrity
checks. To force integrity checking, see the "check_hashes" option in your
boto config file.
"""

MD5_REGEX = re.compile(r'^"*[a-fA-F0-9]{32}"*$')


def CalculateB64EncodedCrc32cFromContents(fp):
  return CalculateB64EncodedHashFromContents(
      fp, crcmod.predefined.Crc('crc-32c'))


def CalculateB64EncodedMd5FromContents(fp):
  return CalculateB64EncodedHashFromContents(fp, md5())


def CalculateB64EncodedHashFromContents(fp, hash_alg):
  return base64.encodestring(binascii.unhexlify(
      CalculateHashFromContents(fp, hash_alg))).rstrip('\n')


def _CalculateCrc32cFromContents(fp):
  """Calculates the Crc32c hash of the contents of a file.

  This function resets the file pointer to position 0.

  Args:
    fp: An already-open file object.

  Returns:
    CRC32C digest of the file in hex string format.
  """
  return CalculateHashFromContents(fp, crcmod.predefined.Crc('crc-32c'))


def CalculateMd5FromContents(fp):
  """Calculates the MD5 hash of the contents of a file.

  This function resets the file pointer to position 0.

  Args:
    fp: An already-open file object.

  Returns:
    MD5 digest of the file in hex string format.
  """
  return CalculateHashFromContents(fp, md5())


def CalculateHashFromContents(fp, hash_alg):
  """Calculates the MD5 hash of the contents of a file.

  This function resets the file pointer to position 0.

  Args:
    fp: An already-open file object.
    hash_alg: Instance of hashing class initialized to start state.

  Returns:
    Hash of the file in hex string format.
  """
  fp.seek(0)
  while True:
    data = fp.read(DEFAULT_FILE_BUFFER_SIZE)
    if not data:
      break
    hash_alg.update(data)
  fp.seek(0)
  return hash_alg.hexdigest()


def GetHashAlgs(src_md5=False, src_crc32c=False, src_url_str=None):
  """Returns a dict of hash algorithms for validating an object.

  Args:
    src_md5: If True, source object has an md5 hash.
    src_crc32c: If True, source object has a crc32c hash.
    src_url_str: URL string of object being hashed.

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
      sys.stderr.write(NO_SERVER_HASH_WARNING % src_url_str)
    else:
      raise CommandException(NO_SERVER_HASH_EXCEPTION_TEXT % src_url_str)
  return hash_algs
