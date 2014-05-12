# Copyright 2013 Google Inc. All Rights Reserved.
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
"""Base test case class for unit and integration tests."""
import os.path
import random
import shutil
import tempfile

import boto
import gslib.tests.util as util
from gslib.tests.util import unittest

MAX_BUCKET_LENGTH = 63


class GsUtilTestCase(unittest.TestCase):
  """Base test case class for unit and integration tests."""

  def setUp(self):
    if util.RUN_S3_TESTS:
      self.test_api = 'XML'
      self.default_provider = 's3'
    else:
      self.test_api = boto.config.get('GSUtil', 'prefer_api', 'JSON').upper()
      self.default_provider = 'gs'
    self.tempdirs = []

  def tearDown(self):
    while self.tempdirs:
      tmpdir = self.tempdirs.pop()
      shutil.rmtree(tmpdir, ignore_errors=True)

  def assertNumLines(self, text, numlines):
    self.assertEqual(text.count('\n'), numlines)

  def MakeRandomTestString(self):
    """Creates a random string of hex characters 8 characters long."""
    return '%08x' % random.randrange(256**4)

  def MakeTempName(self, kind, prefix=''):
    """Creates a temporary name that is most-likely unique.

    Args:
      kind: A string indicating what kind of test name this is.
      prefix: Prefix string to be used in the temporary name.

    Returns:
      The temporary name.
    """
    name = '%sgsutil-test-%s-%s' % (prefix, self._testMethodName, kind)
    name = name[:MAX_BUCKET_LENGTH-9]
    name = '%s-%s' % (name, self.MakeRandomTestString())
    return name

  def CreateTempDir(self, test_files=0):
    """Creates a temporary directory on disk.

    The directory and all of its contents will be deleted after the test.

    Args:
      test_files: The number of test files to place in the directory or a list
                  of test file names.

    Returns:
      The path to the new temporary directory.
    """
    tmpdir = tempfile.mkdtemp(prefix=self.MakeTempName('directory'))
    self.tempdirs.append(tmpdir)
    try:
      iter(test_files)
    except TypeError:
      test_files = [self.MakeTempName('file') for _ in range(test_files)]
    for i, name in enumerate(test_files):
      self.CreateTempFile(tmpdir=tmpdir, file_name=name, contents='test %d' % i)
    return tmpdir

  def CreateTempFile(self, tmpdir=None, contents=None,
                     file_name=None, open_wb=False):
    """Creates a temporary file on disk.

    Args:
      tmpdir: The temporary directory to place the file in. If not specified, a
              new temporary directory is created.
      contents: The contents to write to the file. If not specified, a test
                string is constructed and written to the file.
      file_name: The name to use for the file. If not specified, a temporary
                 test file name is constructed. This can also be a tuple, where
                 ('dir', 'foo') means to create a file named 'foo' inside a
                 subdirectory named 'dir'.
      open_wb: Boolean, should the temporary file be opened in binary mode

    Returns:
      The path to the new temporary file.
    """
    tmpdir = tmpdir or self.CreateTempDir()
    file_name = file_name or self.MakeTempName('file')
    if isinstance(file_name, basestring):
      fpath = os.path.join(tmpdir, file_name)
    else:
      fpath = os.path.join(tmpdir, *file_name)
    if not os.path.isdir(os.path.dirname(fpath)):
      os.makedirs(os.path.dirname(fpath))

    mode = 'wb' if open_wb else 'w'

    with open(fpath, mode) as f:
      contents = contents or self.MakeTempName('contents')
      f.write(contents)
    return fpath
