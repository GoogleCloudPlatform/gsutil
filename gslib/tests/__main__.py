# Copyright 2013 Google Inc.
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

"""Contains a main method to run the gsutil tests."""

import logging
import optparse
import os.path
import sys


CURDIR = os.path.abspath(os.path.dirname(__file__))
GSLIB_DIR = os.path.split(CURDIR)[0]
GSUTIL_DIR = os.path.split(GSLIB_DIR)[0]
BOTO_DIR = os.path.join(GSUTIL_DIR, 'boto')


def MungePath():
  try:
    import boto
  except ImportError:
    sys.path.append(BOTO_DIR)
  try:
    import boto
  except ImportError:
    sys.exit('The boto library was not found. Please follow the installation '
             'instructions in the README file.')

  try:
    import gslib
  except ImportError:
    sys.path.append(GSUTIL_DIR)
  try:
    import gslib
  except ImportError:
    sys.exit('The gslib library was not found. Please follow the installation '
             'instructions in the README file.')

  # Need to import oauth2_plugin to get OAuth2 authentication.
  try:
    from oauth2_plugin import oauth2_plugin
  except ImportError:
    pass


def main():
  MungePath()

  parser = optparse.OptionParser(description='Runs gsutil tests.')
  parser.add_option('-u', '--unit-only', action='store_true', default=False,
                    help='Run unit tests only. Unit tests will run quickly.')
  parser.add_option('-v', '--verbose', action='store_true', default=False,
                    help='Print more detailed test output.')
  (options, args) = parser.parse_args()

  import gslib.tests.util as util
  if options.unit_only:
    util.RUN_INTEGRATION_TESTS = False
  if options.verbose:
    util.VERBOSE_OUTPUT = True

  from gslib.tests.util import unittest
  suite = unittest.TestLoader().discover(CURDIR)
  verbosity = 2
  if not util.VERBOSE_OUTPUT:
    verbosity = 1
    logging.disable(logging.ERROR)
  ret = unittest.TextTestRunner(verbosity=verbosity).run(suite)
  if ret.wasSuccessful():
    sys.exit(0)
  sys.exit(1)


if __name__ == '__main__':
  main()
