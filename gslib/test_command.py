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

"""Unit tests for gsutil command methods"""

import os
import shutil
import sys
import tempfile
import time
import unittest

# Put local libs at front of path so tests will run latest lib code rather
# than whatever code is found on user's PYTHONPATH.
sys.path.insert(0, '.')
sys.path.insert(0, 'boto')
import boto
from tests.s3 import mock_storage_service
from gslib import test_util
from gslib.command import Command
from gslib.exception import CommandException
import wildcard_iterator

command_inst = Command(
    '.', '.', '', '',
    bucket_storage_uri_class=mock_storage_service.MockBucketStorageUri)

# Constant option for specifying a recursive copy.
RECURSIVE = [('-r', '')]


class GsutilCpTests(unittest.TestCase):
  """gsutil command method test suite"""

  def GetSuiteDescription(self):
    return 'gsutil command method test suite'

  @classmethod
  def tearDown(cls):
    """Deletes any objects or files created by last test run"""
    try:
      for key_uri in test_util.test_wildcard_iterator('%s*' %
                                                      cls.dst_bucket_uri):
        key_uri.delete_key()
    # For some reason trying to catch except
    # wildcard_iterator.WildcardException doesn't work here.
    except Exception:
      # Ignore cleanup failures.
      pass
    # Recursively delete dst dir and then re-create it, so in effect we
    # remove all dirs and files under that directory.
    shutil.rmtree(cls.dst_dir_root)
    os.mkdir(cls.dst_dir_root)

  @classmethod
  def SrcFile(cls, fname):
    """Returns path for given test src file"""
    for path in cls.all_src_file_paths:
      if path.find(fname) != -1:
        return path
    raise Exception('SrcFile(%s): no match' % fname)

  @classmethod
  def CreateEmptyObject(cls, uri):
    """Creates an empty object for the given StorageUri"""
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
    # Use a designated tmpdir prefix to make it easy to find the end of
    # the tmp path.
    cls.tmpdir_prefix = 'tmp_gstest'

    # Create the test buckets.
    cls.src_bucket_uri = test_util.test_storage_uri('%s_src' % cls.uri_base_str)
    cls.dst_bucket_uri = test_util.test_storage_uri('%s_dst' % cls.uri_base_str)
    cls.src_bucket_uri.create_bucket()
    cls.dst_bucket_uri.create_bucket()

    # Create the test objects in src bucket.
    cls.all_src_obj_uris = []
    for i in range(3):
      obj_uri = test_util.test_storage_uri('%sobj%d' % (cls.src_bucket_uri, i))
      cls.CreateEmptyObject(obj_uri)
      cls.all_src_obj_uris.append(obj_uri)

    # Create the test directories.
    cls.src_dir_root = '%s%s' % (tempfile.mkdtemp(prefix=cls.tmpdir_prefix),
                                 os.sep)
    nested_subdir = '%sdir0%sdir1' % (cls.src_dir_root, os.sep)
    os.makedirs(nested_subdir)
    cls.dst_dir_root = '%s%s' % (tempfile.mkdtemp(prefix=cls.tmpdir_prefix),
                                 os.sep)

    # Create the test files in src directory.
    cls.all_src_file_paths = []
    cls.nested_child_file_paths = ['f0', 'f1', 'f2.txt', 'dir0/dir1/nested']
    cls.non_nested_file_names = ['f0', 'f1', 'f2.txt']
    file_names = ['f0', 'f1', 'f2.txt', 'dir0%sdir1%snested' % (os.sep, os.sep)]
    file_paths = ['%s%s' % (cls.src_dir_root, f) for f in file_names]
    for file_path in file_paths:
      open(file_path, 'w')
      cls.all_src_file_paths.append(file_path)

    cls.created_test_data = True

  @classmethod
  def TearDownClass(cls):
    """Cleans up buckets and directories created by SetUpClass"""

    if not hasattr(cls, 'created_test_data'):
      return
    # Call cls.tearDown() in case the tests got interrupted, to ensure
    # dst objects and files get deleted.
    cls.tearDown()
    # Now delete src objects and files, and all buckets and dirs.
    try:
      for key_uri in test_util.test_wildcard_iterator('%s*' %
                                                      cls.src_bucket_uri):
        key_uri.delete_key()
    except wildcard_iterator.WildcardException:
      # Ignore cleanup failures.
      pass
    try:
      for key_uri in test_util.test_wildcard_iterator('%s**' %
                                                      cls.src_dir_root):
        key_uri.delete_key()
    except wildcard_iterator.WildcardException:
      # Ignore cleanup failures.
      pass
    cls.src_bucket_uri.delete_bucket()
    cls.dst_bucket_uri.delete_bucket()
    shutil.rmtree(cls.src_dir_root)
    shutil.rmtree(cls.dst_dir_root)

  def TestCopyingTopLevelFileToBucket(self):
    """Tests copying one top-level file to a bucket"""
    src_file = self.SrcFile('f0')
    command_inst.CopyObjsCommand([src_file, self.dst_bucket_uri.uri],
                                 headers={})
    actual = list(test_util.test_wildcard_iterator('%s*' %
                                                   self.dst_bucket_uri.uri))
    self.assertEqual(1, len(actual))
    self.assertEqual('f0', actual[0].object_name)

  def TestCopyingNestedFileToBucket(self):
    """Tests copying one nested file to a bucket"""
    src_file = self.SrcFile('nested')
    command_inst.CopyObjsCommand([src_file, self.dst_bucket_uri.uri],
                                 headers={})
    actual = list(test_util.test_wildcard_iterator('%s*' %
                                                   self.dst_bucket_uri.uri))
    self.assertEqual(1, len(actual))
    # File should be final comp ('nested'), w/o nested path (dir0/...).
    self.assertEqual('nested', actual[0].object_name)

  def TestCopyingDirToBucket(self):
    """Tests copying top-level directory to a bucket"""
    command_inst.CopyObjsCommand([self.src_dir_root, self.dst_bucket_uri.uri],
                                 RECURSIVE, headers={})
    actual = set(str(u) for u in
                 test_util.test_wildcard_iterator('%s*' %
                                                  self.dst_bucket_uri.uri))
    expected = set()
    for file_path in self.all_src_file_paths:
      start_tmp_pos = file_path.find(self.tmpdir_prefix)
      file_path_sans_top_tmp_dir = file_path[start_tmp_pos:]
      expected.add('%s%s' % (self.dst_bucket_uri.uri,
                             file_path_sans_top_tmp_dir))
    self.assertEqual(expected, actual)

  def TestCopyingDirContainingOneFileToBucket(self):
    """Tests copying a directory containing 1 file to a bucket

    We test this case to ensure that correct bucket handling isn't dependent
    on the copy being treated as a multi-source copy.
    """
    command_inst.CopyObjsCommand(['%sdir0%sdir1' % (self.src_dir_root, os.sep),
                                  self.dst_bucket_uri.uri],
                                 RECURSIVE, headers={})
    actual = list((str(u) for u in
                   test_util.test_wildcard_iterator('%s*' %
                                                    self.dst_bucket_uri.uri)))
    self.assertEqual(1, len(actual))
    self.assertEqual('%sdir1%snested' % (self.dst_bucket_uri.uri, os.sep),
                     actual[0])

  def TestCopyingBucketToDir(self):
    """Tests copying from a bucket to a directory"""
    command_inst.CopyObjsCommand([self.src_bucket_uri.uri,
                                  self.dst_dir_root],
                                 RECURSIVE, headers={})
    actual = set(
        str(u) for u in test_util.test_wildcard_iterator('%s**' %
                                                         self.dst_dir_root))
    expected = set()
    for uri in self.all_src_obj_uris:
      expected.add('file://%s%s/%s' % (self.dst_dir_root, uri.bucket_name,
                                       uri.object_name))
    self.assertEqual(expected, actual)

  def TestCopyingBucketToBucket(self):
    """Tests copying from a bucket-only URI to a bucket"""
    command_inst.CopyObjsCommand([self.src_bucket_uri.uri,
                                  self.dst_bucket_uri.uri],
                                 RECURSIVE, headers={})
    actual = set(str(u) for u in
                 test_util.test_wildcard_iterator('%s*' %
                                                  self.dst_bucket_uri.uri))
    expected = set()
    for uri in self.all_src_obj_uris:
      expected.add('%s%s' % (self.dst_bucket_uri.uri, uri.object_name))
    self.assertEqual(expected, actual)

  def TestCopyingDirToDir(self):
    """Tests copying from a directory to a directory"""
    command_inst.CopyObjsCommand([self.src_dir_root, self.dst_dir_root],
                                 RECURSIVE, headers={})
    actual = set(
        str(u) for u in test_util.test_wildcard_iterator('%s**' %
                                                         self.dst_dir_root))
    expected = set()
    for file_path in self.all_src_file_paths:
      start_tmp_pos = file_path.find(self.tmpdir_prefix)
      file_path_sans_top_tmp_dir = file_path[start_tmp_pos:]
      expected.add('file://%s%s' % (self.dst_dir_root,
                                    file_path_sans_top_tmp_dir))
    self.assertEqual(expected, actual)

  def TestCopyingFilesAndDirNonRecursive(self):
    """Tests copying containing files and a directory without -r"""
    command_inst.CopyObjsCommand(['%s*' % self.src_dir_root, self.dst_dir_root],
                                 headers={})
    actual = set(
        str(u) for u in test_util.test_wildcard_iterator('%s**' %
                                                         self.dst_dir_root))
    expected = set(['file://%s%s' % (self.dst_dir_root, f)
                    for f in self.non_nested_file_names])
    self.assertEqual(expected, actual)

  def TestCopyingFileToDir(self):
    """Tests copying one file to a directory"""
    src_file = self.SrcFile('nested')
    command_inst.CopyObjsCommand([src_file, self.dst_dir_root], headers={})
    actual = list(test_util.test_wildcard_iterator('%s*' % self.dst_dir_root))
    self.assertEqual(1, len(actual))
    self.assertEqual('file://%s%s' % (self.dst_dir_root, 'nested'),
                     actual[0].uri)

  def TestCopyingCompressedFileToBucket(self):
    """Tests copying one file with compression to a bucket"""
    src_file = self.SrcFile('f2.txt')
    command_inst.CopyObjsCommand([src_file, self.dst_bucket_uri.uri],
                                 sub_opts=[('-z', 'txt')], headers={})
    actual = list(
        str(u) for u in test_util.test_wildcard_iterator(
            '%s*' % self.dst_bucket_uri.uri))
    self.assertEqual(1, len(actual))
    expected_dst_uri = self.dst_bucket_uri.clone_replace_name('f2.txt')
    self.assertEqual(expected_dst_uri.uri, actual[0])
    dst_key = expected_dst_uri.get_key()
    dst_key.open_read()
    self.assertEqual('gzip', dst_key.content_encoding)

  def TestCopyingObjectToObject(self):
    """Tests copying an object to an object"""
    command_inst.CopyObjsCommand(['%sobj1' % self.src_bucket_uri.uri,
                                  self.dst_bucket_uri.uri], headers={})
    actual = list(test_util.test_wildcard_iterator('%s*' %
                                                   self.dst_bucket_uri.uri))
    self.assertEqual(1, len(actual))
    self.assertEqual('obj1', actual[0].object_name)

  def TestCopyingObjsAndFilesToDir(self):
    """Tests copying objects and files to a directory"""
    command_inst.CopyObjsCommand(['%s*' % self.src_bucket_uri.uri,
                                  '%s*' % self.src_dir_root,
                                  self.dst_dir_root],
                                 RECURSIVE, headers={})
    actual = set(str(u) for u in test_util.test_wildcard_iterator(
        '%s**' % self.dst_dir_root))
    expected = set()
    for uri in self.all_src_obj_uris:
      expected.add('file://%s%s' % (self.dst_dir_root, uri.object_name))
    for file_path in self.nested_child_file_paths:
      expected.add('file://%s%s' % (self.dst_dir_root, file_path))
    self.assertEqual(expected, actual)

  def TestCopyingObjsAndFilesToBucket(self):
    """Tests copying objects and files to a bucket"""
    command_inst.CopyObjsCommand(['%s*' % self.src_bucket_uri.uri,
                                  '%s*' % self.src_dir_root,
                                  self.dst_bucket_uri.uri],
                                 RECURSIVE, headers={})
    actual = set(str(u) for u in
                 test_util.test_wildcard_iterator(
                     '%s*' % self.dst_bucket_uri.uri))
    expected = set()
    for uri in self.all_src_obj_uris:
      expected.add('%s%s' % (self.dst_bucket_uri.uri, uri.object_name))
    for file_path in self.nested_child_file_paths:
      expected.add('%s%s' % (self.dst_bucket_uri.uri, file_path))
    self.assertEqual(expected, actual)

  def TestAttemptDirCopyWithoutRecursion(self):
    """Tests copying a directory without -r"""
    try:
      command_inst.CopyObjsCommand([self.src_dir_root, self.dst_dir_root],
                                   headers={})
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find('Nothing to copy'), -1)

  def TestAttemptCopyingProviderOnlySrc(self):
    """Attempts to copy a src specified as a provider-only URI"""
    try:
      command_inst.CopyObjsCommand(['gs://', self.src_bucket_uri.uri],
                                   headers={})
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find('Provider-only'), -1)

  def TestAttemptCopyingOverlappingSrcDst(self):
    """Attempts to an object atop itself"""
    obj_uri = test_util.test_storage_uri('%sobj' % self.dst_bucket_uri)
    self.CreateEmptyObject(obj_uri)
    try:
      command_inst.CopyObjsCommand(['%s*' % self.dst_bucket_uri.uri,
                                    self.dst_bucket_uri.uri], headers={})
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find('are the same object - abort'), -1)

  def TestAttemptCopyingToMultiMatchWildcard(self):
    """Attempts to copy where dst wildcard matches >1 obj"""
    try:
      command_inst.CopyObjsCommand(['%sobj0' % self.src_bucket_uri.uri,
                                    '%s*' % self.src_bucket_uri.uri],
                                   headers={})
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find('matches more than 1'), -1)

  def TestAttemptCopyingMultiObjsToFile(self):
    """Attempts to copy multiple objects to a file"""
    # Use src_dir_root so we can point to an existing file for this test.
    try:
      command_inst.CopyObjsCommand(['%s*' % self.src_bucket_uri.uri,
                                    '%sf0' % self.src_dir_root],
                                    RECURSIVE, headers={})
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find('must name a bucket or '), -1)

  def TestAttemptCopyingWithFileDirConflict(self):
    """Attempts to copy objects that cause a file/directory conflict"""
    # Create objects with name conflicts (a/b and a). Use 'dst' bucket because
    # it gets cleared after each test.
    self.CreateEmptyObject(test_util.test_storage_uri(
        '%sa/b' % self.dst_bucket_uri))
    self.CreateEmptyObject(test_util.test_storage_uri(
        '%sa' % self.dst_bucket_uri))
    try:
      command_inst.CopyObjsCommand([self.dst_bucket_uri.uri, self.dst_dir_root],
                                   RECURSIVE, headers={})
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find(
          'exists where a directory needs to be created'), -1)

  def TestAttemptCopyingWithDirFileConflict(self):
    """Attempts to copy objects that cause a directory/file conflict"""
    # Create subdir in dest dir.
    os.mkdir('%ssubdir' % self.dst_dir_root)
    # Create an object that conflicts with this dest subdir. Use 'dst' bucket
    # because it gets cleared after each test.
    self.CreateEmptyObject(test_util.test_storage_uri(
        '%ssubdir' % self.dst_bucket_uri))
    try:
      command_inst.CopyObjsCommand([self.dst_bucket_uri.uri, self.dst_dir_root],
                                   RECURSIVE, headers={})
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
    self.CreateEmptyObject(
        test_util.test_storage_uri('%sold' % self.dst_bucket_uri))
    command_inst.MoveObjsCommand(['%s*' % self.dst_bucket_uri.uri,
                                  '%snew' % self.dst_bucket_uri.uri],
                                 headers={})
    actual = list(
        test_util.test_wildcard_iterator('%s*' % self.dst_bucket_uri.uri))
    self.assertEqual(1, len(actual))
    self.assertEqual('new', actual[0].object_name)

  # The remaining tests are pretty minimal - most just ensure a
  # basic use of each command runs, without checking more detailed
  # conditions/expectations.

  def TestCatCommmandRuns(self):
    """Test that the cat command basically runs"""
    command_inst.CatCommand(['%sobj1' % self.src_bucket_uri.uri], headers={})

  def TestGetAclCommmandRuns(self):
    """Test that the GetAcl command basically runs"""
    command_inst.GetAclCommand([self.src_bucket_uri.uri], headers={})

  def TestListCommandRuns(self):
    """Test that the ListCommand basically runs"""
    command_inst.ListCommand([self.src_bucket_uri.uri], headers={})

  def TestMakeBucketsCommand(self):
    """Test MakeBucketsCommand on existing bucket"""
    try:
      command_inst.MakeBucketsCommand([self.dst_bucket_uri.uri], headers={})
      self.fail('Did not get expected StorageCreateError')
    except boto.exception.StorageCreateError, e:
      self.assertEqual(e.status, 409)

  def TestRemoveBucketsCommand(self):
    """Test RemoveBucketsCommand on non-existent bucket"""
    try:
      command_inst.RemoveBucketsCommand(
          ['gs://non_existent_%s' % self.dst_bucket_uri.bucket_name],
          headers={})
      self.fail('Did not get expected StorageResponseError')
    except boto.exception.StorageResponseError, e:
      self.assertEqual(e.status, 404)

  def TestRemoveObjsCommand(self):
    """Test RemoveObjsCommand on non-existent object"""
    try:
      command_inst.RemoveObjsCommand(['%snon_existent' %
                                      self.dst_bucket_uri.uri],
                                     headers={})
      self.fail('Did not get expected WildcardException')
    # For some reason if we catch this as "WildcardException" it doesn't
    # work right. Python bug?
    except Exception, e:
      self.assertNotEqual(e.reason.find('Not Found'), -1)

  def TestSetAclCommmandRuns(self):
    """Test that the SetAcl command basically runs"""
    command_inst.SetAclCommand(['private', self.src_bucket_uri.uri], headers={})

  def TestVerCommmandRuns(self):
    """Test that the Ver command basically runs"""
    command_inst.VerCommand([])

if __name__ == '__main__':
  if sys.version_info[:3] < (2, 5, 1):
    sys.exit('These tests must be run on at least Python 2.5.1\n')
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
