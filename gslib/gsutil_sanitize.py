#!/usr/bin/env python
# coding=utf8
# Copyright 2011 Google Inc.
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

"""Tool to hide user credentials data in gsutil debug traces.

   This script replaces user credentials (e.g. authentication tokens,
   secret keys, etc.) with a predefined string ("REDACTED").
   It's used by the gsutil front end to make sure debug traces 
   don't inadvertently include user credentials."""

import sys
import re

# The replacement string for hidden data.
repstr = 'REDACTED'

# This dictionary maps search strings to list of regexp substitution 
# tuples in the form 'search' : [ sequence of (from, to) tuples ].
# The top level key in this dictionary is used as a matching predicate
# against each line of input. When a line matches that key, the 
# corresponding value is a list of from/to string pairs to be 
# used as input for a sequence of regular expression replacements.
patterns = {
  '^send: ' : [
    (r'(Authorization: OAuth ).*(\\r\\nU)', r'\1%s\2'),
  ],
  '^DEBUG:oauth2_client:' : [
    (r'(token=)\S+(,)',                r'\1%s\2'),
    (r'(client_secret\': \')\S+(\',)', r'\1%s\2'),
    (r'(refresh_token\': \')\S+(\',)', r'\1%s\2'),
    (r'(access_token\': u\')\S+(\',)', r'\1%s\2'),
    (r'(client_id\': \')\S+(\')',      r'\1%s\2'),
    (r'(client_secret=)\S+(&g)',       r'\1%s\2'),
    (r'(refresh_token=)\S+(&c)',       r'\1%s\2'),
    (r'(client_id=)\S+',               r'\1%s'),
  ],
  '"access_token"' : [
    (r'(access_token" : ").*(")', r'\1%s\2'),
  ]
}

while True:
  # Get next line of input, quit on EOF.
  line = sys.stdin.readline()
  if not line: break

  for pattern in patterns:
    if re.search(pattern, line):
      # Selection pattern matched current line so apply corresponding
      # sequence of from/to regexp substitutions.
      for tup in patterns[pattern]: 
        line = re.sub(tup[0], (tup[1] % repstr), line)
  # These lines already have line endings so end print statement
  # with comma to avoid additional newline inserted by print 
  print line,
