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

"""Emulates some functionality of the GNU head command.

Reads text from stdin. Currently implemented functionality:
  -n will print the first n lines

Examples:
  $ echo -e "foo\nbar\nbaz" | python head.py -n 1
  foo
  $ echo -e "foo\nbar\nbaz" | python head.py -n 2
  foo
  bar
"""

import getopt
import sys


def Usage():
  print
  print 'usage: head.py -n N'
  print
  print '   Emulates some functionality of the GNU head command.'
  print
  sys.exit(1)


def main():
  """Main method for head.py program."""
  try:
    opts, args = getopt.getopt(sys.argv[1:], 'hn:', ['help'])
  except getopt.GetoptError as err:
    print str(err)
    sys.exit(2)

  if args == 'help' or not opts:
    Usage()

  numlines = None
  for o, a in opts:
    if o == '-n':
      numlines = int(a)

  for i, line in enumerate(sys.stdin):
    if i < numlines:
      # Strip newline.
      line = line[:-1]
      print line

if __name__ == '__main__':
  main()
