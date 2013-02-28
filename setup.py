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

'''Distutils setup.py script for Google Cloud Storage command line tool.'''

import glob
import sys
import os
import platform
from distutils.core import setup
from pkg_util import parse_manifest

print '''
NOTE: Enterprise mode (installing gsutil via setup.py) is no longer officially
supported - unpacking the zip file into a directory is the preferred method
for installing gsutil for both shared and private configurations. See README.md
and README.pkg for further details.
'''

# Command name and target directory.
NAME = 'gsutil'
TARGET = '/usr/share/gsutil'
BINDIR = '/usr/bin'

# Enterprise mode (shared/central) installation is not supported
# on Windows.
system = platform.system()
if system.lower().startswith('windows'):
  error = 'ERROR: enterprise (shared/central) installation is not ' \
          'supported on Windows.'
  exit(error)

def walk(dir, paths):
  '''Do a recursive file tree walk, adding files found to passed dict.'''
  for file in os.listdir(dir):
    # Skip "dot files".
    if file[0] == '.':
      continue
    path = dir + '/' + file
    if os.path.isdir(path):
      walk(path, paths)
    else:
      if dir not in paths:
        paths[dir] = []
      paths[dir].append(path)

def first_token(filename):
  '''Open file, read first line, parse & return first token to caller.'''
  token = None
  f = open(filename, 'r')
  line = f.readline().strip()
  tokens = line.split()
  token = tokens[0]
  f.close()
  return token

# Validate python version.
if sys.version_info <= (2, 6):
  error = 'ERROR: gsutil requires Python Version 2.6 or above...exiting.'
  exit(error)

# Rather than hard-coding package contents here, we read the manifest 
# file to obtain the list of files and directories to include.
files = []
dirs = []
parse_manifest(files, dirs)

# Build list of data files dynamically.
data_files = [(TARGET, files)]
paths = {}
for dir in dirs:
  walk(dir, paths)
for path in paths:
  data_files += (os.path.join(TARGET, path), paths[path]),

long_desc = '''
GSUtil is a Python application that lets you access Google Cloud Storage 
from the command line. You can use GSUtil to do a wide range of bucket and 
object management tasks, including:
- Creating and deleting buckets.
- Uploading, downloading, and deleting objects.
- Listing buckets and objects.
- Moving, copying, and renaming objects.
- Setting object and bucket ACLs.
'''

VERSION = first_token('VERSION')
if not VERSION:
  error = 'ERROR: can\'t find gsutil version...exiting.'
  exit(error)

# This is the main function call that installs the gsutil package. See
# distutil documentation for details on this function and its arguments.
setup(name = NAME,
      version = VERSION,
      license = 'Apache 2.0',
      author = 'Google',
      author_email = 'gs-team@google.com',
      url = 'http://code.google.com/apis/storage/docs/gsutil.html',
      description = 'gsutil - command line utility for Google Cloud Storage',
      long_description = long_desc,
      data_files = data_files,
      # Dependency on boto commented out for now because initially we plan to 
      # bundle boto with this package, however, when we're ready to depend on 
      # a separate boto rpm package, this line should be uncommented.
      #requires = ['boto (>=2.0)'],
      )

# Create symlink from /usr/bin/gsutil to /usr/share/gsutil/gsutil but
# only run directly in enterprise mode (see README.pkg). When run by
# rpmbuild we don't want to create this link because it's done by the 
# rpm spec file slightly differently (using a relative link). Same story 
# for permission setting, which is only needed if not run by rpmbuild.
if not os.environ.get('RPM_BUILD_ROOT'):
  link = os.path.join(BINDIR, NAME)
  dest = os.path.join(TARGET, NAME)
  if not os.path.exists(link):
    os.symlink(dest, link)
  # Make all files and dirs in install area readable by other
  # and make all directories executable by other. These steps
  # are performed in support of the enterprise (shared/central)
  # installation mode, in which users with different user/group
  # than the installation user/group must be able to run gsutil.
  os.system('chmod -R o+r ' + TARGET)
  os.system('find ' + TARGET + ' -type d | xargs chmod o+x')
  # Make main gsutil script readable and executable by other.
  os.system('chmod o+rx ' + os.path.join(TARGET, NAME))

