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
"""Wrapper for use in daisy-chained copies."""

from collections import deque
import os
import threading
import time

from gslib.cloud_api import BadRequestException
from gslib.cloud_api import CloudApi
from gslib.util import CreateLock
from gslib.util import TRANSFER_BUFFER_SIZE


class BufferWrapper(object):
  """Wraps the download file pointer to use our in-memory buffer."""

  def __init__(self, daisy_chain_wrapper):
    """Provides a buffered write interface for a file download.

    Args:
      daisy_chain_wrapper: DaisyChainWrapper instance to use for buffer and
                           locking.
    """
    self.daisy_chain_wrapper = daisy_chain_wrapper
    self.total_bytes = 0
    self.seek_position = 0

  def write(self, data):  # pylint: disable=invalid-name
    """Waits for space in the buffer, then writes data to the buffer."""
    while True:
      with self.daisy_chain_wrapper.lock:
        if (self.daisy_chain_wrapper.bytes_buffered <
            self.daisy_chain_wrapper.max_buffer_size):
          break
      # Buffer was full, yield thread priority so the upload can pull from it.
      time.sleep(0)
    data_len = len(data)
    with self.daisy_chain_wrapper.lock:
      self.daisy_chain_wrapper.buffer.append(data)
      self.daisy_chain_wrapper.bytes_buffered += data_len
      self.total_bytes += data_len

  def tell(self):  # pylint: disable=invalid-name
    # Return how much we've read so far.
    with self.daisy_chain_wrapper.lock:
      return self.total_bytes

  def seek(self, offset, whence=os.SEEK_SET):  # pylint: disable=invalid-name
    # We don't actually support moving the file pointer; a new BufferWrapper
    # needs to be created to restart the download. However, we respond to seek
    # and tell calls so that GetFileSize() can interact as if this were an
    # on-disk file.
    with self.daisy_chain_wrapper.lock:
      if whence == os.SEEK_END:
        self.seek_position = self.total_bytes
        return
      elif whence == os.SEEK_SET:
        if offset == self.seek_position or offset == self.total_bytes:
          return
      raise BadRequestException('Invalid seek to position %s on daisy chain '
                                'buffer wrapper, expected %s or %s.' %
                                (offset, self.seek_position, self.total_bytes))


class DaisyChainWrapper(object):
  """Wrapper class for daisy-chaining a cloud download to an upload.

  This class instantiates a BufferWrapper object to buffer the download into
  memory, consuming a maximum of max_buffer_size. It implements intelligent
  behavior around read and seek that allow for all of the operations necessary
  to copy a file.

  This class is coupled with the XML and JSON implementations in that it
  expects that small buffers (maximum of TRANSFER_BUFFER_SIZE) in size will be
  used.
  """

  def __init__(self, src_url, src_obj_size, gsutil_api, logger):
    """Initializes the daisy chain wrapper.

    Args:
      src_url: Source CloudUrl to copy from.
      src_obj_size: Size of source object.
      gsutil_api: gsutil Cloud API to use for the copy.
      logger: for outputting log messages.
    """
    # Current read position for the upload file pointer.
    self.position = 0
    self.buffer = deque()

    self.bytes_buffered = 0
    self.max_buffer_size = 1024 * 1024  # 1 MB

    # We save one buffer's worth of data as a special case for boto,
    # which seeks back one buffer and rereads to compute hashes. This is
    # unnecessary because we can just compare cloud hash digests at the end,
    # but it allows this to work without modfiying boto.
    self.last_position = 0
    self.last_data = None

    # Protects buffer, position, bytes_buffered, last_position, and last_data.
    self.lock = CreateLock()

    self.src_obj_size = src_obj_size
    self.src_url = src_url

    # This is safe to use the upload and download thread because the download
    # thread calls only GetObjectMedia, which creates a new HTTP connection
    # independent of gsutil_api. Thus, it will not share an HTTP connection
    # with the upload.
    self.gsutil_api = gsutil_api
    self.logger = logger

    self.download_thread = None
    self.StartDownloadThread()

  def StartDownloadThread(self, start_byte=0):
    """Starts the download of the source object."""
    def PerformDownload():
      self.gsutil_api.GetObjectMedia(
          self.src_url.bucket_name, self.src_url.object_name,
          BufferWrapper(self), start_byte=start_byte,
          generation=self.src_url.generation, object_size=self.src_obj_size,
          download_strategy=CloudApi.DownloadStrategy.RESUMABLE,
          provider=self.src_url.scheme)

    # TODO: If we do gzip encoding transforms mid-transfer, this will fail.
    self.logger.info('DaisyChainWrapper starting download thread with '
                     'offset %s' % start_byte)
    self.download_thread = threading.Thread(target=PerformDownload)
    self.download_thread.start()

  def read(self, amt=None):  # pylint: disable=invalid-name
    """Exposes a stream from the in-memory buffer to the upload."""
    if self.position == self.src_obj_size:
      # No data left, return nothing so callers can call still call len().
      return ''
    if amt is None or amt > TRANSFER_BUFFER_SIZE:
      raise BadRequestException(
          'Invalid HTTP read size %s during daisy chain operation, '
          'expected <= %s.' % (amt, TRANSFER_BUFFER_SIZE))
    while True:
      with self.lock:
        if self.buffer:
          break
      # Buffer was empty, yield thread priority so the download thread can fill.
      time.sleep(0)
    with self.lock:
      data = self.buffer.popleft()
      self.last_position = self.position
      self.last_data = data
      data_len = len(data)
      self.position += data_len
      self.bytes_buffered -= data_len
    if data_len > amt:
      raise BadRequestException(
          'Invalid read during daisy chain operation, got data of size '
          '%s, expected size %s.' % (data_len, amt))
    return data

  def tell(self):  # pylint: disable=invalid-name
    with self.lock:
      return self.position

  def seek(self, offset, whence=os.SEEK_SET):  # pylint: disable=invalid-name
    restart_download = False
    if whence == os.SEEK_END:
      with self.lock:
        self.last_position = self.position
        self.last_data = None
        # Safe because we check position against src_obj_size in read.
        self.position = self.src_obj_size
    elif whence == os.SEEK_SET:
      with self.lock:
        if offset == self.position:
          pass
        elif offset == self.last_position:
          self.position = self.last_position
          if self.last_data:
            # If we seek to end and then back, we won't have last_data; we'll
            # get it on the next call to read.
            self.buffer.appendleft(self.last_data)
            self.bytes_buffered += len(self.last_data)
        elif self.download_thread:
          # Once a download is complete, boto seeks to 0 and re-reads to
          # compute the hash if an md5 isn't already present (for example a GCS
          # composite object), so we have to re-download the whole object.
          restart_download = True
        else:
          raise BadRequestException(
              'Invalid seek during daisy chain operation, seek only allowed to '
              'position %s or %s.' % (self.last_position, self.position))
      if restart_download:
        with self.lock:
          self.position = 0
          self.buffer = deque()
          self.bytes_buffered = 0
          self.last_position = 0
          self.last_data = None
        self.StartDownloadThread(start_byte=offset)
    else:
      raise IOError('Daisy-chain download wrapper does not support '
                    'seek mode %s' % whence)

  def seekable(self):  # pylint: disable=invalid-name
    return True
