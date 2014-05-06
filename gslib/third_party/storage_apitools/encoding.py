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
"""Common code for converting proto to other formats, such as JSON."""

import base64
import collections
import json


from gslib.third_party.protorpc import messages
from gslib.third_party.protorpc import protojson

from gslib.third_party.storage_apitools import exceptions

__all__ = [
    'CopyProtoMessage',
    'JsonToMessage',
    'MessageToJson',
    'DictToMessage',
    'MessageToDict',
    'PyValueToMessage',
    'MessageToPyValue',
]


_Codec = collections.namedtuple('_Codec', ['encoder', 'decoder'])
CodecResult = collections.namedtuple('CodecResult', ['value', 'complete'])


# TODO: Make these non-global.
_UNRECOGNIZED_FIELD_MAPPINGS = {}
_CUSTOM_MESSAGE_CODECS = {}
_CUSTOM_FIELD_CODECS = {}
_FIELD_TYPE_CODECS = {}


def MapUnrecognizedFields(field_name):
  """Register field_name as a container for unrecognized fields in message."""
  def Register(cls):
    _UNRECOGNIZED_FIELD_MAPPINGS[cls] = field_name
    return cls
  return Register


def RegisterCustomMessageCodec(encoder, decoder):
  """Register a custom encoder/decoder for this message class."""
  def Register(cls):
    _CUSTOM_MESSAGE_CODECS[cls] = _Codec(encoder=encoder, decoder=decoder)
    return cls
  return Register


def RegisterCustomFieldCodec(encoder, decoder):
  """Register a custom encoder/decoder for this field."""
  def Register(field):
    _CUSTOM_FIELD_CODECS[field] = _Codec(encoder=encoder, decoder=decoder)
    return field
  return Register


def RegisterFieldTypeCodec(encoder, decoder):
  """Register a custom encoder/decoder for all fields of this type."""
  def Register(field_type):
    _FIELD_TYPE_CODECS[field_type] = _Codec(encoder=encoder, decoder=decoder)
    return field_type
  return Register


# TODO: Delete this function with the switch to proto2.
def CopyProtoMessage(message):
  codec = protojson.ProtoJson()
  return codec.decode_message(type(message), codec.encode_message(message))


def MessageToJson(message, include_fields=None):
  """Convert the given message to JSON."""
  result = _ProtoJsonApiTools.Get().encode_message(message)
  return _IncludeFields(result, message, include_fields)


def JsonToMessage(message_type, message):
  """Convert the given JSON to a message of type message_type."""
  return _ProtoJsonApiTools.Get().decode_message(message_type, message)


# TODO: Do this directly, instead of via JSON.
def DictToMessage(d, message_type):
  """Convert the given dictionary to a message of type message_type."""
  return JsonToMessage(message_type, json.dumps(d))


def MessageToDict(message):
  """Convert the given message to a dictionary."""
  return json.loads(MessageToJson(message))


def PyValueToMessage(message_type, value):
  """Convert the given python value to a message of type message_type."""
  return JsonToMessage(message_type, json.dumps(value))


def MessageToPyValue(message):
  """Convert the given message to a python value."""
  return json.loads(MessageToJson(message))


def _IncludeFields(encoded_message, message, include_fields):
  """Add the requested fields to the encoded message."""
  if include_fields is None:
    return encoded_message
  result = json.loads(encoded_message)
  for field_name in include_fields:
    try:
      message.field_by_name(field_name)
    except KeyError:
      raise exceptions.InvalidDataError(
          'No field named %s in message of type %s' % (
              field_name, type(message)))
    result[field_name] = None
  return json.dumps(result)


def _GetFieldCodecs(field, attr):
  result = [
      getattr(_CUSTOM_FIELD_CODECS.get(field), attr, None),
      getattr(_FIELD_TYPE_CODECS.get(type(field)), attr, None),
  ]
  return [x for x in result if x is not None]


class _ProtoJsonApiTools(protojson.ProtoJson):
  """JSON encoder used by apitools clients."""
  _INSTANCE = None

  @classmethod
  def Get(cls):
    if cls._INSTANCE is None:
      cls._INSTANCE = cls()
    return cls._INSTANCE

  def decode_message(self, message_type, encoded_message):  # pylint: disable=invalid-name
    if message_type in _CUSTOM_MESSAGE_CODECS:
      return _CUSTOM_MESSAGE_CODECS[message_type].decoder(encoded_message)
    result = super(_ProtoJsonApiTools, self).decode_message(
        message_type, encoded_message)
    return _DecodeUnknownFields(result, encoded_message)

  def decode_field(self, field, value):  # pylint: disable=g-bad-name
    """Decode the given JSON value.

    Args:
      field: a messages.Field for the field we're decoding.
      value: a python value we'd like to decode.

    Returns:
      A value suitable for assignment to field.
    """
    for decoder in _GetFieldCodecs(field, 'decoder'):
      result = decoder(field, value)
      value = result.value
      if result.complete:
        return value
    if isinstance(field, messages.MessageField):
      field_value = self.decode_message(field.message_type, json.dumps(value))
    else:
      field_value = super(_ProtoJsonApiTools, self).decode_field(field, value)
    return field_value

  def encode_message(self, message):  # pylint: disable=invalid-name
    if isinstance(message, messages.FieldList):
      return '[%s]' % (', '.join(self.encode_message(x) for x in message))
    if type(message) in _CUSTOM_MESSAGE_CODECS:
      return _CUSTOM_MESSAGE_CODECS[type(message)].encoder(message)
    message = _EncodeUnknownFields(message)
    return super(_ProtoJsonApiTools, self).encode_message(message)

  def encode_field(self, field, value):  # pylint: disable=g-bad-name
    """Encode the given value as JSON.

    Args:
      field: a messages.Field for the field we're encoding.
      value: a value for field.

    Returns:
      A python value suitable for json.dumps.
    """
    for encoder in _GetFieldCodecs(field, 'encoder'):
      result = encoder(field, value)
      value = result.value
      if result.complete:
        return value
    if isinstance(field, messages.MessageField):
      value = json.loads(self.encode_message(value))
    return super(_ProtoJsonApiTools, self).encode_field(field, value)


# TODO: Fold this and _IncludeFields in as codecs.
def _DecodeUnknownFields(message, encoded_message):
  """Rewrite unknown fields in message into message.destination."""
  destination = _UNRECOGNIZED_FIELD_MAPPINGS.get(type(message))
  if destination is None:
    return message
  pair_field = message.field_by_name(destination)
  if not isinstance(pair_field, messages.MessageField):
    raise exceptions.InvalidDataFromServerError(
        'Unrecognized fields must be mapped to a compound '
        'message type.')
  pair_type = pair_field.message_type
  # TODO: Add more error checking around the pair
  # type being exactly what we suspect (field names, etc).
  if isinstance(pair_type.value, messages.MessageField):
    new_values = _DecodeUnknownMessages(
        message, json.loads(encoded_message), pair_type)
  else:
    new_values = _DecodeUnrecognizedFields(message, pair_type)
  setattr(message, destination, new_values)
  # We could probably get away with not setting this, but
  # why not clear it?
  setattr(message, '_Message__unrecognized_fields', {})
  return message


def _DecodeUnknownMessages(message, encoded_message, pair_type):
  """Process unknown fields in encoded_message of a message type."""
  field_type = pair_type.value.type
  new_values = []
  all_field_names = [x.name for x in message.all_fields()]
  for name, value_dict in encoded_message.iteritems():
    if name in all_field_names:
      continue
    value = PyValueToMessage(field_type, value_dict)
    new_pair = pair_type(key=name, value=value)
    new_values.append(new_pair)
  return new_values


def _DecodeUnrecognizedFields(message, pair_type):
  """Process unrecognized fields in message."""
  new_values = []
  for unknown_field in message.all_unrecognized_fields():
    # TODO: Consider validating the variant if
    # the assignment below doesn't take care of it. It may
    # also be necessary to check it in the case that the
    # type has multiple encodings.
    value, _ = message.get_unrecognized_field_info(unknown_field)
    value_type = pair_type.field_by_name('value')
    if isinstance(value_type, messages.MessageField):
      decoded_value = DictToMessage(value, pair_type.value.message_type)
    else:
      decoded_value = value
    new_pair = pair_type(key=str(unknown_field), value=decoded_value)
    new_values.append(new_pair)
  return new_values


def _EncodeUnknownFields(message):
  """Remap unknown fields in message out of message.source."""
  source = _UNRECOGNIZED_FIELD_MAPPINGS.get(type(message))
  if source is None:
    return message
  result = CopyProtoMessage(message)
  pairs_field = message.field_by_name(source)
  if not isinstance(pairs_field, messages.MessageField):
    raise exceptions.InvalidUserInputError(
        'Invalid pairs field %s' % pairs_field)
  pairs_type = pairs_field.message_type
  value_variant = pairs_type.field_by_name('value').variant
  pairs = getattr(message, source)
  for pair in pairs:
    if value_variant == messages.Variant.MESSAGE:
      encoded_value = MessageToDict(pair.value)
    else:
      encoded_value = pair.value
    result.set_unrecognized_field(pair.key, encoded_value, value_variant)
  setattr(result, source, [])
  return result


def _SafeEncodeBytes(field, value):
  """Encode the bytes in value as urlsafe base64."""
  try:
    if field.repeated:
      result = [base64.urlsafe_b64encode(byte) for byte in value]
    else:
      result = base64.urlsafe_b64encode(value)
    complete = True
  except TypeError:
    result = value
    complete = False
  return CodecResult(value=result, complete=complete)


def _SafeDecodeBytes(unused_field, value):
  """Decode the urlsafe base64 value into bytes."""
  try:
    result = base64.urlsafe_b64decode(str(value))
    complete = True
  except TypeError:
    result = value
    complete = False
  return CodecResult(value=result, complete=complete)


RegisterFieldTypeCodec(_SafeEncodeBytes, _SafeDecodeBytes)(messages.BytesField)
