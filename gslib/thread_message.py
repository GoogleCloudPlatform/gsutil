# -*- coding: utf-8 -*-
# Copyright 2012 Google Inc. All Rights Reserved.
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
"""Thread message classes.

Messages are added to the status queue.
"""

import os
import threading
import time


class StatusMessage(object):
  """General StatusMessage class.

  All Message classes inherit this StatusMessage class.
  """

  def __init__(self, time):
    """Creates a Message.

    Args:
      time: Time that this message was created (since Epoch).
    """
    self.time = time
    self.process_id = os.getpid()
    self.thread_id = threading.current_thread().ident


class RetryableErrorMessage(StatusMessage):
  """Message class for retryable errors encountered by the JSON API.

  This class contains information about the retryable error encountered to
  report to analytics collection and to display in the UI.
  """

  def __init__(self, exception, num_retries=0,
               total_wait_sec=0, time=time.time()):
    """Creates a RetryableErrorMessage.

    Args:
      exception: The retryable error that was thrown.
      num_retries: The number of retries consumed so far.
      total_wait_sec: The total amount of time waited so far in retrying.
      time: Float representing when message was created (seconds since Epoch).
    """
    super(RetryableErrorMessage, self).__init__(time)

    self.error_type = exception.__class__.__name__
    # The socket module error class names aren't descriptive enough, so we
    # make the error_type more specific. Standard Python uses the module name
    # 'socket' while PyPy uses '_socket' instead.
    if exception.__class__.__module__ in ('socket', '_socket'):
      self.error_type = 'Socket' + exception.__class__.__name__.capitalize()

    # The number of retries consumed to display to the user.
    self.num_retries = num_retries

    # The total amount of time waited on the request to display to the user.
    self.total_wait_sec = total_wait_sec
