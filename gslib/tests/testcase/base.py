import os.path
import random
import shutil
import tempfile

from gslib.tests.util import unittest


MAX_BUCKET_LENGTH = 63


class GsUtilTestCase(unittest.TestCase):
  """Base test case class for unit and integration tests."""

  def setUp(self):
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

  def CreateTempFile(self, tmpdir=None, contents=None, file_name=None):
    """Creates a temporary file on disk.

    Args:
      tmpdir: The temporary directory to place the file in. If not specified, a
              new temporary directory is created.
      file_name: The name to use for the file. If not specified, a temporary
                 test file name is constructed. This can also be a tuple, where
                 ('dir', 'foo') means to create a file named 'foo' inside a
                 subdirectory named 'dir'.
      contents: The contents to write to the file. If not specified, a test
                string is constructed and written to the file.

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
    with open(fpath, 'w') as f:
      contents = contents or self.MakeTempName('contents')
      f.write(contents)
    return fpath
