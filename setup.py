#!/usr/bin/env python
# -*- coding: utf-8 -*-
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

"""Setup installation module for gsutil."""

import os
from setuptools import setup, find_packages
from setuptools.command import build_py
from setuptools.command import sdist

long_desc = """
gsutil is a Python application that lets you access Google Cloud Storage from
the command line. You can use gsutil to do a wide range of bucket and object
management tasks, including:
 * Creating and deleting buckets.
 * Uploading, downloading, and deleting objects.
 * Listing buckets and objects.
 * Moving, copying, and renaming objects.
 * Editing object and bucket ACLs.
"""

requires = [
    'boto==2.9.8',
    'httplib2>=0.8',
    'python-gflags>=2.0',
    'google-api-python-client>=1.1',
    'pyOpenSSL>=0.13',
    'crcmod>=1.7',
    # Not using 1.02 because of:
    #   https://code.google.com/p/socksipy-branch/issues/detail?id=3
    'SocksiPy-branch==1.01',
    'retry_decorator>=0.1.0',
]

dependency_links = [
    # Note: this commit ID should be kept in sync with the 'third_party/boto'
    # entry in 'git submodule status'.
    'https://github.com/boto/boto/archive/12f3c1bd2e943bdf22571c0e61f3c12789f63ce9.tar.gz#egg=boto-2.9.8',
]

CURDIR = os.path.abspath(os.path.dirname(__file__))
BOTO_DIR = os.path.join(CURDIR, 'third_party', 'boto')

with open(os.path.join(CURDIR, 'VERSION'), 'r') as f:
  VERSION = f.read().strip()

with open(os.path.join(CURDIR, 'CHECKSUM'), 'r') as f:
  CHECKSUM = f.read()


def PlaceNeededFiles(self, target_dir):
  target_dir = os.path.join(target_dir, 'gslib')
  self.mkpath(target_dir)

  # Copy the gsutil root VERSION file into gslib module.
  with open(os.path.join(target_dir, 'VERSION'), 'w') as f:
    f.write(VERSION)

  # Copy the gsutil root CHECKSUM file into gslib module.
  with open(os.path.join(target_dir, 'CHECKSUM'), 'w') as f:
    f.write(CHECKSUM)

  # Copy the Boto test module required by gsutil unit tests.
  tests_dir = os.path.join(target_dir, 'tests')
  self.mkpath(tests_dir)
  mock_storage_dst = os.path.join(tests_dir, 'mock_storage_service.py')
  mock_storage_src1 = os.path.join(
      BOTO_DIR, 'tests', 'integration', 's3', 'mock_storage_service.py')
  mock_storage_src2 = os.path.join(
      CURDIR, 'gslib', 'tests', 'mock_storage_service.py')
  mock_storage_src = (
      mock_storage_src1
      if os.path.isfile(mock_storage_src1) else mock_storage_src2)
  if not os.path.isfile(mock_storage_src):
    raise Exception('Unable to find required boto test source file at %s or %s.'
                    % (mock_storage_src1, mock_storage_src2))
  with open(mock_storage_src, 'r') as f:
    mock_storage_contents = f.read()
  with open(mock_storage_dst, 'w') as f:
    f.write('#\n'
            '# This file was copied during gsutil package generation from\n'
            '# the Boto test suite, originally located at:\n'
            '#   tests/integration/s3/mock_storage_service.py\n'
            '# DO NOT MODIFY\n'
            '#\n\n')
    f.write(mock_storage_contents)


class CustomBuildPy(build_py.build_py):

  def byte_compile(self, files):
    for filename in files:
      # Note: we exclude the update command here because binary distributions
      # (built via setup.py bdist command) don't abide by the MANIFEST file.
      # For source distributions (built via setup.py sdist), the update command
      # will be excluded by the MANIFEST file.
      if 'gslib/commands/update.py' in filename:
        os.unlink(filename)
    build_py.build_py.byte_compile(self, files)

  def run(self):
    if not self.dry_run:
      PlaceNeededFiles(self, self.build_lib)
      build_py.build_py.run(self)


class CustomSDist(sdist.sdist):

  def make_release_tree(self, base_dir, files):
    sdist.sdist.make_release_tree(self, base_dir, files)
    PlaceNeededFiles(self, base_dir)


setup(
    name='gsutil',
    version=VERSION,
    url='https://developers.google.com/storage/docs/gsutil',
    download_url='https://developers.google.com/storage/docs/gsutil_install',
    license='Apache 2.0',
    author='Google Inc.',
    author_email='gs-team@google.com',
    description=('A command line tool for interacting with cloud storage '
                 'services.'),
    long_description=long_desc,
    zip_safe=False,
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: Apache Software License',
        'Natural Language :: English',
        'Topic :: System :: Filesystems',
        'Topic :: Utilities',
    ],
    platforms='any',
    packages=find_packages(exclude=['third_party']),
    include_package_data=True,
    entry_points={
        'console_scripts': [
            'gsutil = gslib.__main__:main',
        ],
    },
    install_requires=requires,
    dependency_links=dependency_links,
    cmdclass={
        'build_py': CustomBuildPy,
        'sdist': CustomSDist,
    }
)
