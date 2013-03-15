# Copyright 2010 Google Inc. All Rights Reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish, dis-
# tribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the fol-
# lowing conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABIL-
# ITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT
# SHALL THE AUTHOR BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.

"""Package marker file."""

import os
import sys

import gslib.exception

# Directory containing the gslib module.
GSLIB_DIR = os.path.abspath(os.path.dirname(__file__))
# Path to gsutil executable. This assumes gsutil is the running script.
GSUTIL_PATH = os.path.normpath(os.path.abspath(sys.argv[0]))
# The directory that contains the gsutil executable.
GSUTIL_DIR = os.path.dirname(GSUTIL_PATH)

# Whether or not this was installed via a package manager like pip, deb, rpm,
# etc. If installed by just extracting a tarball or zip file, this will be
# False.
IS_PACKAGE_INSTALL = True

# Directory where program files like VERSION and CHECKSUM will be. When
# installed via tarball, this is the gsutil directory, but the files are moved
# to the gslib directory when installed via setup.py.
PROGRAM_FILES_DIR = GSLIB_DIR

# The gslib directory will be underneath the gsutil directory when installed
# from a tarball, but somewhere else on the machine if installed via setup.py.
if os.path.commonprefix((GSUTIL_DIR, GSLIB_DIR)) == GSUTIL_DIR:
  IS_PACKAGE_INSTALL = False
  PROGRAM_FILES_DIR = GSUTIL_DIR

# Get the version file and store it.
VERSION_FILE = os.path.join(PROGRAM_FILES_DIR, 'VERSION')
if not os.path.isfile(VERSION_FILE):
  raise gslib.exception.CommandException(
      'VERSION file not found. Please reinstall gsutil from scratch')
with open(VERSION_FILE, 'r') as f:
  VERSION = f.read().strip()
__version__ = VERSION

# Get the checksum file and store it.
CHECKSUM_FILE = os.path.join(PROGRAM_FILES_DIR, 'CHECKSUM')
if not os.path.isfile(CHECKSUM_FILE):
  raise gslib.exception.CommandException(
      'CHECKSUM file not found. Please reinstall gsutil from scratch')
with open(CHECKSUM_FILE, 'r') as f:
  CHECKSUM = f.read().strip()
