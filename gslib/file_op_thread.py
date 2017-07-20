"""Creates a file operation thread which maintains a request queue to process
requests from the file wrapper objects to read from the disk.
"""

import threading

class FileOperationThread(threading.Thread):
  """Manages the read request queue."""

  global file_op_manager
  global disk_lock

  def __init__(self, file_obj_queue, command_manager, command_disk_lock, timeout=None):
    super(FileOperationThread, self).__init__()
    self.daemon = True
    self._read_queue = file_obj_queue
    self.cancel_event = threading.Event()
    self._timeout = 0.1
    global file_op_manager, disk_lock
    file_op_manager = command_manager
    disk_lock = command_disk_lock

  def run(self):
    while True:
      """Processes items from the read queue until it is empty."""

      if self.cancel_event.isSet():
        break

      try:
        while True:
          # Attempt to get the next read request from read request queue.
          if self._timeout is None:
            (file_object, size, _) = self._read_queue.get_nowait()
          else:
            (file_object, size, _) = self._read_queue.get(timeout=self._timeout)

          file_op_manager.available.acquire()
          while not file_op_manager.requestMemory(size):
            file_op_manager.available.wait()

          with disk_lock:
            file_object.ReadFromDisk(size)

          file_op_manager.available.release()

      except Queue.Empty:
        pass

    return
