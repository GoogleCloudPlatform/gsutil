#!/usr/bin/env python
#
# Copyright 2019 Google Inc.
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
#

"""JSON support for python 2 and 3.

Public classes:
  MessageJSONEncoder: JSON encoder for message objects.

Public functions:
  encode_message: Encodes a message in to a JSON string.
  decode_message: Merge from a JSON string in to a message.
"""

import json
from six import PY3
from six import binary_type

# used for including both loads and dumps methods for ease of importing
from json import dumps

def loads(json_data):
  """
  Converts a string OR bytes into a json structure
  """
  if PY3 and isinstance(json_data, binary_type):
    json_data = str(json_data, "utf-8")
  return json.loads(json_data)
