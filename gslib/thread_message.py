# -*- coding: utf-8 -*-
# Copyright 2016 Google Inc. All Rights Reserved.
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


class MetadataMessage(StatusMessage):
  """Creates a MetadataMessage.

  A MetadataMessage simply indicates that a metadata operation on a given object
  has been successfully done. The only passed argument is the time when such
  operation has finished.
  """

  def __init__(self, time):
    """Creates a MetadataMessage.

    Args:
      time: Float representing when message was created (seconds since Epoch).
    """
    super(MetadataMessage, self).__init__(time)


class FileMessage(StatusMessage):
  """Marks start or end of an operation for a file, cloud object or component.

  This class contains general information about each file/component. With that,
  information such as total size and estimated time remaining may be calculated
  beforehand.
  """

  # Enum message types
  FILE_DOWNLOAD = 1
  FILE_UPLOAD = 2
  FILE_CLOUD_COPY = 3
  FILE_LOCAL_COPY = 4
  FILE_DAISY_COPY = 5
  FILE_REWRITE = 6
  FILE_HASH = 7
  COMPONENT_TO_UPLOAD = 8
  # EXISTING_COMPONENT describes a component that already exists. The field
  # finished does not apply quite well for it, but the convention used by the UI
  # is to process the component alongside FileMessages from other components
  # when finished==False, and to ignore a FileMessage made for
  # EXISTING_COMPONENT when finished==True.
  EXISTING_COMPONENT = 9
  COMPONENT_TO_DOWNLOAD = 10
  EXISTING_OBJECT_TO_DELETE = 11

  def __init__(self, src_url, dst_url, time, size=None, finished=False,
               component_num=None, message_type=None,
               bytes_already_downloaded=None):
    """Creates a FileMessage.

    Args:
      src_url: FileUrl/CloudUrl representing the source file.
      dst_url: FileUrl/CloudUrl representing the destination file.
      time: Float representing when message was created (seconds since Epoch).
      size: Total size of this file/component, in bytes.
      finished: Boolean to indicate whether this is starting or finishing
        a file/component transfer.
      component_num: Component number, if dealing with a component.
      message_type: Type of the file/component.
      bytes_already_downloaded: Specific field for resuming downloads. When
        starting a component download, it tells how many bytes were already
        downloaded.
    """

    super(FileMessage, self).__init__(time)
    self.src_url = src_url
    self.dst_url = dst_url
    self.size = size
    self.component_num = component_num
    self.finished = finished
    self.message_type = message_type
    self.bytes_already_downloaded = bytes_already_downloaded


class ProgressMessage(StatusMessage):
  """Message class for a file/object/component progress.

  This class contains specific information about the current progress of a file,
  cloud object or single component.
  """

  def __init__(self, size, processed_bytes, src_url, time,
               dst_url=None, component_num=None, operation_name=None):
    """Creates a ProgressMessage.

    Args:
      size: Integer for total size of this file/component, in bytes.
      processed_bytes: Integer for number of bytes already processed from that
        specific component, which means processed_bytes <= size.
      src_url: FileUrl/CloudUrl representing the source file.
      time: Float representing when message was created (seconds since Epoch).
      dst_url: FileUrl/CloudUrl representing the destination file, or None
        for unary operations like hashing.
      component_num: Indicates the component number, if any.
      operation_name: Name of the operation that is being made over that
        component.
    """
    super(ProgressMessage, self).__init__(time)
    self.size = size
    self.processed_bytes = processed_bytes
    self.component_num = component_num
    self.src_url = src_url
    self.dst_url = dst_url
    self.finished = (size == processed_bytes)
    self.operation_name = operation_name


class SeekAheadMessage(StatusMessage):
  """Message class for results obtained by SeekAheadThread().

  It estimates the number of objects and total size in case the task_queue
  cannot hold all tasks at once (only used in large operations).
  This class contains information about all the objects yet to be processed.
  """

  def __init__(self, num_objects, size, time):
    """Creates a SeekAheadMessage.

    Args:
      num_objects: Number of total objects that the SeekAheadThread estimates.
      size: Total size corresponding to the sum of the size of objects iterated
       by SeekAheadThread.
      time: Float representing when message was created (seconds since Epoch).
    """
    super(SeekAheadMessage, self).__init__(time)
    self.num_objects = num_objects
    self.size = size


class ProducerThreadMessage(StatusMessage):
  """Message class for results obtained by calculations made on ProducerThread.

  It estimates the number of objects and total size currently dealty by
  task_queue. If the task_queue cannot support all objects at once, the
  SeekAheadThread will be responsible for sending an accurate message.
  """

  def __init__(self, num_objects, size, time, finished=False):
    """Creates a SeekAheadMessage.

    Args:
      num_objects: Number of total objects that the task_queue has.
      size: Total size corresponding to the sum of the size of objects iterated
       by the task_queue
      time: Float representing when message was created (seconds since Epoch).
      finished: Boolean to indicate whether this is the final message from the
                ProducerThread. The difference is that this message displays
                the correct total size and number of objects, whereas the
                previous ones were periodic (on the number of files) updates.
    """
    super(ProducerThreadMessage, self).__init__(time)
    self.num_objects = num_objects
    self.size = size
    self.finished = finished
