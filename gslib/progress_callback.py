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
"""Helper functions for progress callbacks."""

import logging
import sys

from gslib.util import MakeHumanReadable
from gslib.util import UTF8

# Default upper and lower bounds for progress callback frequency.
_START_BYTES_PER_CALLBACK = 1024*64
_MAX_BYTES_PER_CALLBACK = 1024*1024*100

# Max width of URL to display in progress indicator. Wide enough to allow
# 15 chars for x/y display on an 80 char wide terminal.
MAX_PROGRESS_INDICATOR_COLUMNS = 65


class ProgressCallbackWithBackoff(object):
  """Makes progress callbacks with exponential backoff to a maximum value.

  This prevents excessive log message output.
  """

  def __init__(self, total_size, callback_func,
               start_bytes_per_callback=_START_BYTES_PER_CALLBACK,
               max_bytes_per_callback=_MAX_BYTES_PER_CALLBACK,
               calls_per_exponent=10):
    """Initializes the callback with backoff.

    Args:
      total_size: Total bytes to process.
      callback_func: Func of (int: processed_so_far, int: total_bytes)
                     used to make callbacks.
      start_bytes_per_callback: Lower bound of bytes per callback.
      max_bytes_per_callback: Upper bound of bytes per callback.
      calls_per_exponent: Number of calls to make before reducing rate.
    """
    self.callbacks_made = 0
    self.bytes_per_callback = start_bytes_per_callback
    self.max_bytes_per_callback = max_bytes_per_callback
    self.bytes_processed_since_callback = 0
    self.total_bytes_processed = 0
    self.total_size = total_size
    self.callback_func = callback_func
    self.calls_per_exponent = calls_per_exponent
    self.final_callback = False

  def Progress(self, bytes_processed):
    """Tracks byte processing progress, making a callback if necessary."""
    self.bytes_processed_since_callback += bytes_processed
    # We check if >= total_size and truncate because JSON uploads count
    # metadata during their send progress; only make the final callback once.
    if self.final_callback: return
    if (self.total_bytes_processed + self.bytes_processed_since_callback >=
        self.total_size):
      self.final_callback = True
    if (self.bytes_processed_since_callback > self.bytes_per_callback or
        self.final_callback):
      self.total_bytes_processed += self.bytes_processed_since_callback
      self.callback_func(min(self.total_bytes_processed, self.total_size),
                         self.total_size)
      self.bytes_processed_since_callback = 0
      self.callbacks_made += 1
      if self.callbacks_made > self.calls_per_exponent:
        self.bytes_per_callback = min(self.bytes_per_callback * 2,
                                      self.max_bytes_per_callback)
        self.callbacks_made = 0


class FileProgressCallbackHandler(object):
  """Outputs progress info for large operations like file copy or hash."""

  def __init__(self, op_string, display_url, logger):
    """Initializes the callback handler.

    Args:
      op_string: String describing the progress operation, i.e.
                 'Uploading' or 'Hashing'.
      display_url: StorageUrl describe the file/object being processed.
      logger: For outputting log messages.
    """
    # Use fixed-width announce text so concurrent output (gsutil -m) leaves
    # progress counters in readable (fixed) position.
    justified_op_string = op_string[:11].ljust(12)
    start_len = len(justified_op_string)
    display_urlstr = display_url.GetUrlString()
    end_len = len(': ')
    elip_len = len('... ')
    if (start_len + len(display_urlstr) + end_len >
        MAX_PROGRESS_INDICATOR_COLUMNS):
      display_urlstr = '...%s' % display_urlstr[
          -(MAX_PROGRESS_INDICATOR_COLUMNS - start_len - end_len - elip_len):]
    base_announce_text = '%s%s:' % (justified_op_string, display_urlstr)
    format_str = '{0:%ds}' % MAX_PROGRESS_INDICATOR_COLUMNS
    self.announce_text = format_str.format(base_announce_text.encode(UTF8))
    self.logger = logger

  # Function signature is in boto callback format, which cannot be changed.
  def call(self, total_bytes_transferred, total_size):  # pylint: disable=invalid-name
    # Handle streaming case specially where we don't know the total size:
    if total_size:
      total_size_string = '/%s' % MakeHumanReadable(total_size)
    else:
      total_size_string = ''
    if self.logger.isEnabledFor(logging.INFO):
      # Use sys.stderr.write instead of self.logger.info so progress messages
      # output on a single continuously overwriting line.
      sys.stderr.write('%s%s%s    \r' % (
          self.announce_text,
          MakeHumanReadable(total_bytes_transferred),
          total_size_string))
      if total_size and total_bytes_transferred == total_size:
        sys.stderr.write('\n')
