"""Small helper class to provide a small slice of a stream."""

from gslib.third_party.storage_apitools import exceptions

class StreamSlice(object):

  def __init__(self, stream, max_bytes):
    self.__stream = stream
    self.__remaining_bytes = max_bytes
    self.__max_bytes = max_bytes

  def __str__(self):
    return 'Slice of stream %s with %s/%s bytes not yet read' % (
        self.__stream, self.__remaining_bytes, self.__max_bytes)

  def __len__(self):
    return self.__max_bytes

  def read(self, size=None):
    if size is not None:
      size = min(size, self.__remaining_bytes)
    else:
      size = self.__remaining_bytes
    data = self.__stream.read(size)
    if not data and self.__remaining_bytes:
      raise exceptions.TransferInvalidError(
        'Not enough bytes in stream; expected %d, stream exhasted after %d' % (
          self.__max_bytes, self.__remaining_bytes))
    self.__remaining_bytes -= len(data)
    return data
