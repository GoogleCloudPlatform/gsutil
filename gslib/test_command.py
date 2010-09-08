#!/usr/bin/env python
#
# Copyright 2010 Google Inc.
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

"""Unit tests for gsutil command methods."""

import os
import shutil
import sys
import tempfile
import time
import unittest
import boto

sys.path.insert(0, '.')
sys.path.insert(0, 'gslib')
from boto.exception import InvalidUriError
from gslib.command import Command
from gslib.exception import CommandException
from wildcard_iterator import ResultType
from wildcard_iterator import wildcard_iterator
from wildcard_iterator import WildcardException

command_inst = Command('.', '.', '')


class GsutilCpTests(unittest.TestCase):
  """gsutil command method test suite."""

  def GetSuiteDescription(self):
    return 'gsutil command method test suite'

  @classmethod
  def tearDown(cls):
    """Deletes any objects or files created by last test run."""
    try:
      for key_uri in wildcard_iterator('%s*' % cls.dst_bucket_uri,
                                       ResultType.URIS):
        key_uri.delete_key()
    except WildcardException:
      # Ignore cleanup failures.
      pass
    # Recursively delete dst dir and then re-create it, so in effect we
    # remove all dirs and files under that directory.
    shutil.rmtree(cls.dst_dir_root)
    os.mkdir(cls.dst_dir_root)

  @classmethod
  def SrcFile(cls, fname):
    """Returns path for given test src file."""
    for path in cls.all_src_file_paths:
      if path.find(fname) != -1:
        return path
    raise Exception('SrcFile(%s): no match' % fname)

  @classmethod
  def CreateEmptyObject(cls, uri):
    """Creates an empty object for the given StorageUri."""
    key = uri.new_key()
    key.set_contents_from_string('')

  @classmethod
  def SetUpClass(cls):
    """Initializes test suite.

    Creates a source bucket containing 3 objects;
    a source directory containing a subdirectory and file;
    and a destination bucket and directory.
    """
    cls.uri_base_str = 'gs://gsutil_test_%s' % int(time.time())

    # Create the test buckets.
    cls.src_bucket_uri = boto.storage_uri('%s_src' % cls.uri_base_str)
    cls.dst_bucket_uri = boto.storage_uri('%s_dst' % cls.uri_base_str)
    cls.src_bucket_uri.create_bucket()
    cls.dst_bucket_uri.create_bucket()

    # Create the test objects in src bucket.
    cls.all_src_obj_uris = []
    for i in range(3):
      obj_uri = boto.storage_uri('%sobj%s' % (cls.src_bucket_uri, i))
      cls.CreateEmptyObject(obj_uri)
      cls.all_src_obj_uris.append(obj_uri)

    # Create the test directories.
    cls.src_dir_root = '%s%s' % (tempfile.mkdtemp(), os.sep)
    nested_subdir = '%sdir0%sdir1' % (cls.src_dir_root, os.sep)
    os.makedirs(nested_subdir)
    cls.dst_dir_root = '%s%s' % (tempfile.mkdtemp(), os.sep)

    # Create the test files in src directory.
    cls.all_src_file_paths = []
    cls.nested_child_file_paths = ['f0', 'f1', 'f2', 'dir0/dir1/nested']
    file_names = ['f0', 'f1', 'f2', 'dir0%sdir1%snested' % (os.sep, os.sep)]
    file_paths = ['%s%s' % (cls.src_dir_root, f)
                  for f in file_names]
    for file_path in file_paths:
      open(file_path, 'w')
      cls.all_src_file_paths.append(file_path)

    cls.created_test_data = True

  @classmethod
  def TearDownClass(cls):
    """Cleans up buckets and directories created by SetUpClass."""

    if not hasattr(cls, 'created_test_data'):
      return
    # Call cls.tearDown() in case the tests got interrupted, to ensure
    # dst objects and files get deleted.
    cls.tearDown()
    # Now delete src objects and files, and all buckets and dirs.
    try:
      for key_uri in wildcard_iterator('%s*' % cls.src_bucket_uri,
                                       ResultType.URIS):
        key_uri.delete_key()
    except WildcardException:
      # Ignore cleanup failures.
      pass
    try:
      for key_uri in wildcard_iterator('%s**' % cls.src_dir_root,
                                       ResultType.URIS):
        key_uri.delete_key()
    except WildcardException:
      # Ignore cleanup failures.
      pass
    cls.src_bucket_uri.delete_bucket()
    cls.dst_bucket_uri.delete_bucket()
    shutil.rmtree(cls.src_dir_root)
    shutil.rmtree(cls.dst_dir_root)

  def TestCopyingTopLevelFileToBucket(self):
    """Tests copying one top-level file to a bucket."""
    src_file = self.SrcFile('f0')
    command_inst.CopyObjsCommand([src_file, self.dst_bucket_uri.uri])
    actual = list(wildcard_iterator('%s*' % self.dst_bucket_uri.uri,
                                    ResultType.URIS))
    self.assertEqual(1, len(actual))
    self.assertEqual('f0', actual[0].object_name)

  def TestCopyingNestedFileToBucket(self):
    """Tests copying one nested file to a bucket."""
    src_file = self.SrcFile('nested')
    command_inst.CopyObjsCommand([src_file, self.dst_bucket_uri.uri])
    actual = list(wildcard_iterator('%s*' % self.dst_bucket_uri.uri,
                                    ResultType.URIS))
    self.assertEqual(1, len(actual))
    # File should be final comp ('nested'), w/o nested path (dir0/...).
    self.assertEqual('nested', actual[0].object_name)

  def TestCopyingDirToBucket(self):
    """Tests copying top-level directory to a bucket."""
    command_inst.CopyObjsCommand([self.src_dir_root, self.dst_bucket_uri.uri])
    actual = set(str(u) for u in
                 wildcard_iterator('%s*' % self.dst_bucket_uri.uri,
                                   ResultType.URIS))
    expected = set()
    for file_path in self.all_src_file_paths:
      file_path_sans_top_tmp_dir = file_path[5:]
      expected.add('%s%s' % (self.dst_bucket_uri.uri,
                             file_path_sans_top_tmp_dir))
    self.assertEqual(expected, actual)

  def TestCopyingDirContainingOneFileToBucket(self):
    """Tests copying a directory containing 1 file to a bucket.

    We test this case to ensure that correct bucket handling isn't dependent
    on the copy being treated as a multi-source copy.
    """
    command_inst.CopyObjsCommand(['%sdir0%sdir1' % (self.src_dir_root, os.sep),
                                  self.dst_bucket_uri.uri])
    actual = list((str(u) for u in
                   wildcard_iterator('%s*' % self.dst_bucket_uri.uri,
                                     ResultType.URIS)))
    self.assertEqual(1, len(actual))
    self.assertEqual('%sdir1%snested' % (self.dst_bucket_uri.uri, os.sep),
                     actual[0])

  def TestCopyingBucketToDir(self):
    """Tests copying from a bucket to a directory."""
    command_inst.CopyObjsCommand([self.src_bucket_uri.uri,
                                  self.dst_dir_root])
    actual = set(str(u) for u in
                 wildcard_iterator('%s**' % self.dst_dir_root, ResultType.URIS))
    expected = set()
    for uri in self.all_src_obj_uris:
      expected.add('file://%s%s/%s' % (self.dst_dir_root, uri.bucket_name,
                                       uri.object_name))
    self.assertEqual(expected, actual)

  def TestCopyingBucketToBucket(self):
    """Tests copying from a bucket-only URI to a bucket."""
    command_inst.CopyObjsCommand([self.src_bucket_uri.uri,
                                  self.dst_bucket_uri.uri])
    actual = set(str(u) for u in
                 wildcard_iterator('%s*' % self.dst_bucket_uri.uri,
                                   ResultType.URIS))
    expected = set()
    for uri in self.all_src_obj_uris:
      expected.add('%s%s' % (self.dst_bucket_uri.uri, uri.object_name))
    self.assertEqual(expected, actual)

  def TestCopyingDirToDir(self):
    """Tests copying from a directory to a directory."""
    command_inst.CopyObjsCommand([self.src_dir_root, self.dst_dir_root])
    actual = set(str(u) for u in
                 wildcard_iterator('%s**' % self.dst_dir_root, ResultType.URIS))
    expected = set()
    for file_path in self.all_src_file_paths:
      file_path_sans_top_tmp_dir = file_path[5:]
      expected.add('file://%s%s' % (self.dst_dir_root,
                                    file_path_sans_top_tmp_dir))
    self.assertEqual(expected, actual)

  def TestCopyingFileToDir(self):
    """Tests copying one file to a directory."""
    src_file = self.SrcFile('nested')
    command_inst.CopyObjsCommand([src_file, self.dst_dir_root])
    actual = list(wildcard_iterator('%s*' % self.dst_dir_root, ResultType.URIS))
    self.assertEqual(1, len(actual))
    self.assertEqual('file://%s%s' % (self.dst_dir_root, 'nested'),
                     actual[0].uri)

  def TestCopyingObjectToObject(self):
    """Tests copying an object to an object."""
    command_inst.CopyObjsCommand(['%sobj1' % self.src_bucket_uri.uri,
                                  self.dst_bucket_uri.uri])
    actual = list(wildcard_iterator('%s*' % self.dst_bucket_uri.uri,
                                    ResultType.URIS))
    self.assertEqual(1, len(actual))
    self.assertEqual('obj1', actual[0].object_name)

  def TestCopyingObjsAndFilesToDir(self):
    """Tests copying objects and files to a directory."""
    command_inst.CopyObjsCommand(['%s*' % self.src_bucket_uri.uri,
                                  '%s*' % self.src_dir_root,
                                  self.dst_dir_root])
    actual = set(str(u) for u in
                 wildcard_iterator('%s**' % self.dst_dir_root, ResultType.URIS))
    expected = set()
    for uri in self.all_src_obj_uris:
      expected.add('file://%s%s' % (self.dst_dir_root, uri.object_name))
    for file_path in self.nested_child_file_paths:
      expected.add('file://%s%s' % (self.dst_dir_root, file_path))
    self.assertEqual(expected, actual)

  def TestCopyingObjsAndFilesToBucket(self):
    """Tests copying objects and files to a bucket."""
    command_inst.CopyObjsCommand(['%s*' % self.src_bucket_uri.uri,
                                  '%s*' % self.src_dir_root,
                                  self.dst_bucket_uri.uri])
    actual = set(str(u) for u in
                 wildcard_iterator('%s*' % self.dst_bucket_uri.uri,
                                   ResultType.URIS))
    expected = set()
    for uri in self.all_src_obj_uris:
      expected.add('%s%s' % (self.dst_bucket_uri.uri, uri.object_name))
    for file_path in self.nested_child_file_paths:
      expected.add('%s%s' % (self.dst_bucket_uri.uri, file_path))
    self.assertEqual(expected, actual)

  def TestAttemptCopyingProviderOnlySrc(self):
    """Attempts to copy a src specified as a provider-only URI."""
    try:
      command_inst.CopyObjsCommand(['gs://', self.src_bucket_uri.uri])
      self.fail('Did not get expected CommandException')
    except InvalidUriError, e:
      self.assertNotEqual(e.message.find('bucket-less URI'), -1)

  def TestAttemptCopyingOverlappingSrcDst(self):
    """Attempts to copy a set of objects atop themselves."""
    try:
      command_inst.CopyObjsCommand(['%s*' % self.src_bucket_uri.uri,
                                    self.src_bucket_uri.uri])
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find('Overlap'), -1)

  def TestAttemptCopyingToMultiMatchWildcard(self):
    """Attempts to copy where dst wildcard matches >1 obj."""
    try:
      command_inst.CopyObjsCommand(['%sobj0' % self.src_bucket_uri.uri,
                                    '%s*' % self.src_bucket_uri.uri])
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find('matches more than 1'), -1)

  def TestAttemptCopyingMultiObjsToFile(self):
    """Attempts to copy multiple objects to a file."""
    # Use src_dir_root so we can point to an existing file for this test.
    try:
      command_inst.CopyObjsCommand(['%s*' % self.src_bucket_uri.uri,
                                    '%sf0' % self.src_dir_root])
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find('must name a bucket or '), -1)

  def TestAttemptCopyingWithFileDirConflict(self):
    """Attempts to copy objects that cause a file/directory conflict."""
    # Create objects with name conflicts (a/b and a). Use 'dst' bucket because
    # it gets cleared after each test.
    self.CreateEmptyObject(boto.storage_uri('%sa/b' % self.dst_bucket_uri))
    self.CreateEmptyObject(boto.storage_uri('%sa' % self.dst_bucket_uri))
    try:
      command_inst.CopyObjsCommand([self.dst_bucket_uri.uri,
                                    self.dst_dir_root])
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find(
          'exists where a directory needs to be created'), -1)

  def TestAttemptCopyingWithDirFileConflict(self):
    """Attempts to copy objects that cause a directory/file conflict."""
    # Create subdir in dest dir.
    os.mkdir('%ssubdir' % self.dst_dir_root)
    # Create an object that conflicts with this dest subdir. Use 'dst' bucket
    # because it gets cleared after each test.
    self.CreateEmptyObject(boto.storage_uri('%ssubdir' % self.dst_bucket_uri))
    try:
      command_inst.CopyObjsCommand([self.dst_bucket_uri.uri,
                                    self.dst_dir_root])
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find(
          'where the file needs to be created'), -1)

  def TestWildcardMoveWithinBucket(self):
    """Attempts to move using src wildcard that overlaps dest object.

    We want to ensure that this doesn't stomp the result data. See the
    comment starting with "Expand wildcards before" in MoveObjsCommand
    for details.
    """
    # Create a single object; use 'dst' bucket because it gets cleared after
    # each test.
    self.CreateEmptyObject(boto.storage_uri('%sold' % self.dst_bucket_uri))
    command_inst.MoveObjsCommand(['%s*' % self.dst_bucket_uri.uri,
                                  '%snew' % self.dst_bucket_uri.uri])
    actual = list(wildcard_iterator('%s*' % self.dst_bucket_uri.uri,
                                    ResultType.URIS))
    self.assertEqual(1, len(actual))
    self.assertEqual('new', actual[0].object_name)


if __name__ == '__main__':
  python_version = float('%d.%d%d' %(sys.version_info[0], sys.version_info[1],
                                     sys.version_info[2]))
  if python_version < 2.51:
    sys.stderr.write('These tests must be run on at least Python 2.5.1\n')
    sys.exit(1)
  test_loader = unittest.TestLoader()
  test_loader.testMethodPrefix = 'Test'
  suite = test_loader.loadTestsFromTestCase(GsutilCpTests)
  # Seems like there should be a cleaner way to find the test_class.
  test_class = suite.__getattribute__('_tests')[0]
  # We call SetUpClass() and TearDownClass() ourselves because we
  # don't assume the user has Python 2.7 (which supports classmethods
  # that do it, with camelCase versions of these names).
  try:
    print 'Setting up %s...' % test_class.GetSuiteDescription()
    test_class.SetUpClass()
    print 'Running %s...' % test_class.GetSuiteDescription()
    unittest.TextTestRunner(verbosity=2).run(suite)
  finally:
    print 'Cleaning up after %s...' % test_class.GetSuiteDescription()
    test_class.TearDownClass()
    print ''
