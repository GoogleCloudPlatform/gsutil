#!/usr/bin/env python
# coding=utf8
# Copyright 2012 Google Inc.
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

"""Emulates some functionality of the GNU cut command.

Reads text from stdin. Currently implemented functionality:
  -f can select fields with a single value or range
  -c can select character with a single value or range

Examples:
  $ echo -e "foo\tbar" | python cut.py -f2
  bar
  $ echo -e "foobar" | python cut.py -c2-5
  ooba
"""

import getopt
import sys


def Usage():
  print
  print 'usage: cut.py (-c N[-M] | -f N[-M])'
  print
  print '   Emulates some functionality of the GNU cut command.'
  print
  sys.exit(1)


def main():
  """Main method for cut.py program."""
  try:
    opts, args = getopt.getopt(sys.argv[1:], 'hf:c:', ['help'])
  except getopt.GetoptError as err:
    print str(err)
    sys.exit(2)

  if args == 'help' or not opts:
    Usage()

  mode = None
  parts = None
  delimiter = '\t'
  for o, a in opts:
    if o == '-c':
      mode = 'characters'
      parts = map(int, a.split('-'))
    if o == '-f':
      mode = 'fields'
      parts = map(int, a.split('-'))

  for line in sys.stdin:
    # Strip newline.
    line = line[:-1]
    if mode == 'characters':
      delimiter = ''
      pieces = line
    if mode == 'fields':
      pieces = line.split(delimiter)
    if len(parts) == 1:
      # Python is 0-based, but cut is 1-based.
      print pieces[parts[0]-1]
    else:
      print delimiter.join(pieces[parts[0]-1:parts[1]])

if __name__ == '__main__':
  main()
