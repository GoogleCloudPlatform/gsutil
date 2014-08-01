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
"""Helper functions for hashing functionality."""

import base64
import binascii
from hashlib import md5
import os

from boto import config
import crcmod

from gslib.exception import CommandException
from gslib.progress_callback import ProgressCallbackWithBackoff
from gslib.util import DEFAULT_FILE_BUFFER_SIZE
from gslib.util import MIN_SIZE_COMPUTE_LOGGING
from gslib.util import TRANSFER_BUFFER_SIZE
from gslib.util import UsingCrcmodExtension


SLOW_CRCMOD_WARNING = """
WARNING: You have requested checksumming but your crcmod installation isn't
using the module's C extension, so checksumming will run very slowly. For help
installing the extension, please see:
  $ gsutil help crcmod"""


_SLOW_CRCMOD_DOWNLOAD_WARNING = """
WARNING: Downloading this composite object requires integrity checking with
CRC32c, but your crcmod installation isn't using the module's C extension,
so the hash computation will likely throttle download performance. For help
installing the extension, please see:
  $ gsutil help crcmod
To disable slow integrity checking, see the "check_hashes" option in your
boto config file.
"""

_SLOW_CRC_EXCEPTION_TEXT = """
Downloading this composite object requires integrity checking with CRC32c,
but your crcmod installation isn't using the module's C extension, so the
hash computation will likely throttle download performance. For help
installing the extension, please see:
  $ gsutil help crcmod
To download regardless of crcmod performance or to skip slow integrity
checks, see the "check_hashes" option in your boto config file.
NOTE: It is strongly recommended that you not disable integrity checks. Doing so
could allow data corruption to go undetected during uploading/downloading."""

_SLOW_CRC_EXCEPTION = CommandException(_SLOW_CRC_EXCEPTION_TEXT)

_NO_HASH_CHECK_WARNING = """
WARNING: This download will not be validated since your crcmod installation
doesn't use the module's C extension, so the hash computation would likely
throttle download performance. For help in installing the extension, please
see:
  $ gsutil help crcmod
To force integrity checking, see the "check_hashes" option in your boto config
file.
"""


def CalculateB64EncodedCrc32cFromContents(fp):
  return _CalculateB64EncodedHashFromContents(
      fp, crcmod.predefined.Crc('crc-32c'))


def CalculateB64EncodedMd5FromContents(fp):
  return _CalculateB64EncodedHashFromContents(fp, md5())


def CalculateMd5FromContents(fp):
  """Calculates the MD5 hash of the contents of a file.

  This function resets the file pointer to position 0.

  Args:
    fp: An already-open file object.

  Returns:
    MD5 digest of the file in hex string format.
  """
  return _CalculateHashFromContents(fp, md5())


def Base64EncodeHash(digest_value):
  return base64.encodestring(binascii.unhexlify(digest_value)).rstrip('\n')


def _CalculateB64EncodedHashFromContents(fp, hash_alg):
  return Base64EncodeHash(_CalculateHashFromContents(fp, hash_alg))


def _CalculateHashFromContents(fp, hash_alg):
  """Calculates a hash of the contents of a file.

  This function resets the file pointer to position 0.

  Args:
    fp: An already-open file object.
    hash_alg: Instance of hashing class initialized to start state.

  Returns:
    Hash of the file in hex string format.
  """
  hash_dict = {'placeholder': hash_alg}
  fp.seek(0)
  CalculateHashesFromContents(fp, hash_dict)
  fp.seek(0)
  return hash_dict['placeholder'].hexdigest()


def CalculateHashesFromContents(fp, hash_dict, size=None, progress_func=None):
  """Calculates hashes of the contents of a file.

  Args:
    fp: An already-open file object (stream will be consumed).
    hash_dict: Dict of (string alg_name: initialized hashing class)
               Hashing class will be populated with digests upon return.
    size: Size of fp, if known, for outputting progress.
    progress_func: Function with arguments (int bytes_processed,
                                            int total_size).
                   If present, called to report progress.
  """
  callback_processor = None
  if progress_func:
    callback_processor = ProgressCallbackWithBackoff(size, progress_func)
  while True:
    data = fp.read(DEFAULT_FILE_BUFFER_SIZE)
    if not data:
      break
    for hash_alg in hash_dict.itervalues():
      hash_alg.update(data)
    if callback_processor:
      callback_processor.Progress(len(data))


def GetUploadHashAlgs():
  """Returns a dict of hash algorithms for validating an uploaded object.

  This is for use only with single object uploads, not compose operations
  such as those used by parallel composite uploads (though it can be used to
  validate the individual components).

  Returns:
    dict of (algorithm_name: hash_algorithm)
  """
  check_hashes_config = config.get(
      'GSUtil', 'check_hashes', 'if_fast_else_fail')
  if check_hashes_config == 'never':
    return {}
  return {'md5': md5}


def GetDownloadHashAlgs(logger, src_md5=False, src_crc32c=False):
  """Returns a dict of hash algorithms for validating an object.

  Args:
    logger: For outputting log messages.
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
  if src_md5:
    hash_algs['md5'] = md5
  # If the cloud provider supplies a CRC, we'll compute a checksum to
  # validate if we're using a native crcmod installation and MD5 isn't
  # offered as an alternative.
  elif src_crc32c:
    if UsingCrcmodExtension(crcmod):
      hash_algs['crc32c'] = lambda: crcmod.predefined.Crc('crc-32c')
    elif not hash_algs:
      if check_hashes_config == 'if_fast_else_fail':
        raise _SLOW_CRC_EXCEPTION
      elif check_hashes_config == 'if_fast_else_skip':
        logger.warn(_NO_HASH_CHECK_WARNING)
      elif check_hashes_config == 'always':
        logger.warn(_SLOW_CRCMOD_DOWNLOAD_WARNING)
        hash_algs['crc32c'] = lambda: crcmod.predefined.Crc('crc-32c')
      else:
        raise CommandException(
            'Your boto config \'check_hashes\' option is misconfigured.')

  return hash_algs


class HashingFileUploadWrapper(object):
  """Wraps an input stream in a hash digester and exposes a stream interface.

  This class provides integrity checking during file uploads via the
  following properties:

  Calls to read will appropriately update digesters with all bytes read.
  Calls to seek (assuming it is supported by the underlying stream) using
      os.SEEK_SET will catch up / reset the digesters to the specified
      position. If seek is called with a different os.SEEK mode, the caller
      must return to the original position using os.SEEK_SET before further
      reads.
  Calls to seek are fast if the desired position is equal to the position at
      the beginning of the last read call (we only need to re-hash bytes
      from that point on).
  """

  def __init__(self, stream, digesters, hash_algs, src_url, logger):
    """Initializes the wrapper.

    Args:
      stream: Input stream.
      digesters: dict of {string, hash digester} containing digesters.
      hash_algs: dict of {string, hash algorithm} for use if digesters need
                 to be reset.
      src_url: Source FileUrl that is being copied.
      logger: For outputting log messages.
    """
    self.orig_fp = stream
    self.digesters = digesters
    self.src_url = src_url
    self.logger = logger
    if self.digesters:
      self.digesters_previous = {}
      for alg in self.digesters:
        self.digesters_previous[alg] = self.digesters[alg].copy()
      self.digesters_previous_mark = 0
      self.digesters_current_mark = 0
      self.hash_algs = hash_algs
      self.seek_away = None

  def read(self, size=-1):  # pylint: disable=invalid-name
    """"Reads from the wrapped file pointer and calculates hash digests."""
    data = self.orig_fp.read(size)
    if self.digesters:
      if self.seek_away is not None:
        raise CommandException('Read called on hashing file pointer in an '
                               'unknown position, cannot correctly compute '
                               'digest.')
      self.digesters_previous_mark = self.digesters_current_mark
      for alg in self.digesters:
        self.digesters_previous[alg] = self.digesters[alg].copy()
        if len(data) >= MIN_SIZE_COMPUTE_LOGGING:
          self.logger.info('Catching up %s for %s...', alg,
                           self.src_url.GetUrlString())
        self.digesters[alg].update(data)
      self.digesters_current_mark += len(data)
    return data

  def tell(self):  # pylint: disable=invalid-name
    return self.orig_fp.tell()

  def seekable(self):  # pylint: disable=invalid-name
    return self.orig_fp.seekable()

  def seek(self, offset, whence=os.SEEK_SET):  # pylint: disable=invalid-name
    """"Seeks in the wrapped file pointer and catches up hash digests."""
    if self.digesters:
      if whence != os.SEEK_SET:
        # We do not catch up hashes for non-absolute seeks, and rely on the
        # caller to seek to an absolute position before reading.
        self.seek_away = self.orig_fp.tell()
      else:
        # Hashes will be correct and it's safe to call read().
        self.seek_away = None
        if offset < self.digesters_previous_mark:
          # This is earlier than our earliest saved digest, so we need to
          # reset the digesters and scan from the beginning.
          for alg in self.digesters:
            self.digesters[alg] = self.hash_algs[alg]()
          self.digesters_current_mark = 0
          self.orig_fp.seek(0)
          self._CatchUp(offset)
        elif offset == self.digesters_previous_mark:
          # Just load the saved digests.
          self.digesters_current_mark = self.digesters_previous_mark
          for alg in self.digesters:
            self.digesters[alg] = self.digesters_previous[alg]
        elif offset < self.digesters_current_mark:
          # Reset the position to our previous digest and scan forward.
          self.digesters_current_mark = self.digesters_previous_mark
          for alg in self.digesters:
            self.digesters[alg] = self.digesters_previous[alg]
          self.orig_fp.seek(self.digesters_previous_mark)
          self._CatchUp(offset - self.digesters_previous_mark)
        else:
          # Scan forward from our current digest and position.
          self._CatchUp(offset - self.digesters_current_mark)
    return self.orig_fp.seek(offset, whence)

  def _CatchUp(self, bytes_to_read):
    """Catches up hashes, but does not return data and uses little memory.

    Before calling this function, digesters_current_mark should be updated
    to the current location of the original stream and the self.digesters
    should be current to that point (but no further).

    Args:
      bytes_to_read: Number of bytes to catch up from the original stream.
    """
    if self.digesters:
      for alg in self.digesters:
        if bytes_to_read >= MIN_SIZE_COMPUTE_LOGGING:
          self.logger.info('Catching up %s for %s...', alg,
                           self.src_url.GetUrlString())
        self.digesters_previous[alg] = self.digesters[alg].copy()
      self.digesters_previous_mark = self.digesters_current_mark
      bytes_remaining = bytes_to_read
      bytes_this_round = min(bytes_remaining, TRANSFER_BUFFER_SIZE)
      while bytes_this_round:
        data = self.orig_fp.read(bytes_this_round)
        bytes_remaining -= bytes_this_round
        for alg in self.digesters:
          self.digesters[alg].update(data)
        bytes_this_round = min(bytes_remaining, TRANSFER_BUFFER_SIZE)
      self.digesters_current_mark += bytes_to_read
