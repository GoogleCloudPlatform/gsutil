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

"""Unit tests for gsutil command code"""

import os
import shutil
import sys
import tempfile
import time
import unittest
import wildcard_iterator

# Put local libs at front of path so tests will run latest lib code rather
# than whatever code is found on user's PYTHONPATH.
sys.path.insert(0, '.')
sys.path.insert(0, 'boto')
import boto

from gslib.command import Command
from gslib.command_runner import CommandRunner
from gslib.exception import CommandException
from gslib import test_util
from tests.s3.mock_storage_service import MockBucketStorageUri


class GsutilCommandTests(unittest.TestCase):
  """gsutil command method test suite"""

  # We don't use the gsutil boto config discovery logic here, as it assumes
  # boto is a subdirectory of where the command is running, which is gslib
  # when running these tests. Instead we use a simplified setup:
  gsutil_bin_dir = '.'
  boto_lib_dir = os.path.join(gsutil_bin_dir, 'boto')
  config_file_list = boto.pyami.config.BotoConfigLocations
  command_runner = CommandRunner(gsutil_bin_dir, boto_lib_dir, config_file_list,
                                 MockBucketStorageUri)

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
      f = open(file_path, 'w')
      f.write('test data')
      f.close()
      cls.all_src_file_paths.append(file_path)
    cls.tmp_path = '%s%s' % (cls.src_dir_root, 'tmp0')

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
    self.command_runner.RunNamedCommand('cp',
                                        [src_file, self.dst_bucket_uri.uri])
    actual = list(test_util.test_wildcard_iterator('%s*' %
                                                   self.dst_bucket_uri.uri))
    self.assertEqual(1, len(actual))
    self.assertEqual('f0', actual[0].object_name)

  def TestCopyingTopLevelFileToBucketMulti(self):
    """Tests copying one top-level file to a bucket with -m option"""
    self.parallel_operations = True
    self.TestCopyingTopLevelFileToBucket()
    self.parallel_operations = False
    
  def TestCopyingNestedFileToBucket(self):
    """Tests copying one nested file to a bucket"""
    src_file = self.SrcFile('nested')
    self.command_runner.RunNamedCommand('cp', [src_file,
                                               self.dst_bucket_uri.uri])
    actual = list(test_util.test_wildcard_iterator('%s*' %
                                                   self.dst_bucket_uri.uri))
    self.assertEqual(1, len(actual))
    # File should be final comp ('nested'), w/o nested path (dir0/...).
    self.assertEqual('nested', actual[0].object_name)

  def TestCopyingNestedFileToBucketMulti(self):
    """Tests copying one nested file to a bucket with -m option"""
    self.parallel_operations = True
    self.TestCopyingNestedFileToBucket()
    self.parallel_operations = False

  def TestCopyingDirToBucket(self):
    """Tests copying top-level directory to a bucket"""
    self.command_runner.RunNamedCommand('cp', ['-r', self.src_dir_root,
                                               self.dst_bucket_uri.uri])
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

  def TestCopyingDirToBucketMulti(self):
    """Tests copying top-level directory to a bucket with -m option"""
    self.parallel_operations = True
    self.TestCopyingDirToBucket()
    self.parallel_operations = False

  def TestCopyingDirContainingOneFileToBucket(self):
    """Tests copying a directory containing 1 file to a bucket

    We test this case to ensure that correct bucket handling isn't dependent
    on the copy being treated as a multi-source copy.
    """
    self.command_runner.RunNamedCommand('cp', ['-r', '%sdir0%sdir1' %
                                        (self.src_dir_root, os.sep),
                                        self.dst_bucket_uri.uri])
    actual = list((str(u) for u in
                   test_util.test_wildcard_iterator('%s*' %
                                                    self.dst_bucket_uri.uri)))
    self.assertEqual(1, len(actual))
    self.assertEqual('%sdir1%snested' % (self.dst_bucket_uri.uri, os.sep),
                     actual[0])

  def TestCopyingDirContainingOneFileToBucketMulti(self):
    """Tests copying a directory containing 1 file to a bucket with -m option"""
    self.parallel_operations = True
    self.TestCopyingDirContainingOneFileToBucket()
    self.parallel_operations = False

  def TestCopyingBucketToDir(self):
    """Tests copying from a bucket to a directory"""
    self.command_runner.RunNamedCommand('cp', ['-r', self.src_bucket_uri.uri,
                                  self.dst_dir_root])
    actual = set(
        str(u) for u in test_util.test_wildcard_iterator('%s**' %
                                                         self.dst_dir_root))
    expected = set()
    for uri in self.all_src_obj_uris:
      expected.add('file://%s%s/%s' % (self.dst_dir_root, uri.bucket_name,
                                       uri.object_name))
    self.assertEqual(expected, actual)

  def TestCopyingBucketToDirMulti(self):
    """Tests copying from a bucket to a directory with -m option"""
    self.parallel_operations = True
    self.TestCopyingBucketToDir()
    self.parallel_operations = False

  def TestCopyingBucketToBucket(self):
    """Tests copying from a bucket-only URI to a bucket"""
    self.command_runner.RunNamedCommand('cp', ['-r', self.src_bucket_uri.uri,
                                  self.dst_bucket_uri.uri])
    actual = set(str(u) for u in
                 test_util.test_wildcard_iterator('%s*' %
                                                  self.dst_bucket_uri.uri))
    expected = set()
    for uri in self.all_src_obj_uris:
      expected.add('%s%s' % (self.dst_bucket_uri.uri, uri.object_name))
    self.assertEqual(expected, actual)

  def TestCopyingBucketToBucketMulti(self):
    """Tests copying from a bucket-only URI to a bucket with -m option"""
    self.parallel_operations = True
    self.TestCopyingBucketToDir()
    self.parallel_operations = False

  def TestCopyingDirToDir(self):
    """Tests copying from a directory to a directory"""
    self.command_runner.RunNamedCommand('cp', ['-r', self.src_dir_root,
                                               self.dst_dir_root])
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

  def TestCopyingDirToDirMulti(self):
    """Tests copying from a directory to a directory with -m option"""
    self.parallel_operations = True
    self.TestCopyingDirToDir()
    self.parallel_operations = False

  def TestCopyingFilesAndDirNonRecursive(self):
    """Tests copying containing files and a directory without -r"""
    self.command_runner.RunNamedCommand('cp', ['%s*' % self.src_dir_root,
                                               self.dst_dir_root])
    actual = set(
        str(u) for u in test_util.test_wildcard_iterator('%s**' %
                                                         self.dst_dir_root))
    expected = set(['file://%s%s' % (self.dst_dir_root, f)
                    for f in self.non_nested_file_names])
    self.assertEqual(expected, actual)

  def TestCopyingFilesAndDirNonRecursiveMulti(self):
    """Tests copying containing files and a directory without -r, with -m opt"""
    self.parallel_operations = True
    self.TestCopyingFilesAndDirNonRecursive()
    self.parallel_operations = False

  def TestCopyingFileToDir(self):
    """Tests copying one file to a directory"""
    src_file = self.SrcFile('nested')
    self.command_runner.RunNamedCommand('cp', [src_file, self.dst_dir_root])
    actual = list(test_util.test_wildcard_iterator('%s*' % self.dst_dir_root))
    self.assertEqual(1, len(actual))
    self.assertEqual('file://%s%s' % (self.dst_dir_root, 'nested'),
                     actual[0].uri)

  def TestCopyingFileToDirMulti(self):
    """Tests copying one file to a directory with -m option"""
    self.parallel_operations = True
    self.TestCopyingFileToDir()
    self.parallel_operations = False

  def TestCopyingCompressedFileToBucket(self):
    """Tests copying one file with compression to a bucket"""
    src_file = self.SrcFile('f2.txt')
    self.command_runner.RunNamedCommand('cp', ['-z', 'txt', src_file,
                                               self.dst_bucket_uri.uri],)
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
    self.command_runner.RunNamedCommand('cp',
                                        ['%sobj1' % self.src_bucket_uri.uri,
                                         self.dst_bucket_uri.uri])
    actual = list(test_util.test_wildcard_iterator('%s*' %
                                                   self.dst_bucket_uri.uri))
    self.assertEqual(1, len(actual))
    self.assertEqual('obj1', actual[0].object_name)

  def TestCopyingObjsAndFilesToDir(self):
    """Tests copying objects and files to a directory"""
    self.command_runner.RunNamedCommand('cp',
                                        ['-r', '%s*' % self.src_bucket_uri.uri,
                                         '%s*' % self.src_dir_root,
                                         self.dst_dir_root])
    actual = set(str(u) for u in test_util.test_wildcard_iterator(
        '%s**' % self.dst_dir_root))
    expected = set()
    for uri in self.all_src_obj_uris:
      expected.add('file://%s%s' % (self.dst_dir_root, uri.object_name))
    for file_path in self.nested_child_file_paths:
      expected.add('file://%s%s' % (self.dst_dir_root, file_path))
    self.assertEqual(expected, actual)

  def TestCopyingObjsAndFilesToDirMulti(self):
    """Tests copying objects and files to a directory with -m option"""
    self.parallel_operations = True
    self.TestCopyingObjsAndFilesToDir()
    self.parallel_operations = False

  def TestCopyingObjsAndFilesToBucket(self):
    """Tests copying objects and files to a bucket"""
    self.command_runner.RunNamedCommand('cp',
                                        ['-r', '%s*' % self.src_bucket_uri.uri,
                                         '%s*' % self.src_dir_root,
                                         self.dst_bucket_uri.uri])
    actual = set(str(u) for u in
                 test_util.test_wildcard_iterator(
                     '%s*' % self.dst_bucket_uri.uri))
    expected = set()
    for uri in self.all_src_obj_uris:
      expected.add('%s%s' % (self.dst_bucket_uri.uri, uri.object_name))
    for file_path in self.nested_child_file_paths:
      expected.add('%s%s' % (self.dst_bucket_uri.uri, file_path))
    self.assertEqual(expected, actual)

  def TestCopyingObjsAndFilesToBucketMulti(self):
    """Tests copying objects and files to a bucket with -m option"""
    self.parallel_operations = True
    self.TestCopyingObjsAndFilesToBucket()
    self.parallel_operations = False

  def TestAttemptDirCopyWithoutRecursion(self):
    """Tests copying a directory without -r"""
    try:
      self.command_runner.RunNamedCommand('cp', [self.src_dir_root,
                                                 self.dst_dir_root])
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find('Nothing to copy'), -1)

  def TestAttemptCopyingProviderOnlySrc(self):
    """Attempts to copy a src specified as a provider-only URI"""
    try:
      self.command_runner.RunNamedCommand('cp',
                                          ['gs://', self.src_bucket_uri.uri])
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find('provider-only'), -1)

  def TestAttemptCopyingOverlappingSrcDst(self):
    """Attempts to an object atop itself"""
    obj_uri = test_util.test_storage_uri('%sobj' % self.dst_bucket_uri)
    self.CreateEmptyObject(obj_uri)
    try:
      self.command_runner.RunNamedCommand('cp',
                                          ['%s*' % self.dst_bucket_uri.uri,
                                           self.dst_bucket_uri.uri])
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find('are the same object - abort'), -1)

  def TestAttemptCopyingToMultiMatchWildcard(self):
    """Attempts to copy where dst wildcard matches >1 obj"""
    try:
      self.command_runner.RunNamedCommand('cp',
                                          ['%sobj0' % self.src_bucket_uri.uri,
                                           '%s*' % self.src_bucket_uri.uri])
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find('matches more than 1'), -1)

  def TestAttemptCopyingMultiObjsToFile(self):
    """Attempts to copy multiple objects to a file"""
    # Use src_dir_root so we can point to an existing file for this test.
    try:
      self.command_runner.RunNamedCommand('cp',
                                          ['-r', '%s*'
                                           % self.src_bucket_uri.uri,
                                           '%sf0' % self.src_dir_root])
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
      self.command_runner.RunNamedCommand('cp', ['-r', self.dst_bucket_uri.uri,
                                                 self.dst_dir_root])
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
      self.command_runner.RunNamedCommand('cp', ['-r', self.dst_bucket_uri.uri,
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
    self.CreateEmptyObject(
        test_util.test_storage_uri('%sold' % self.dst_bucket_uri))
    self.command_runner.RunNamedCommand('mv', ['%s*' % self.dst_bucket_uri.uri,
                                  '%snew' % self.dst_bucket_uri.uri])
    actual = list(
        test_util.test_wildcard_iterator('%s*' % self.dst_bucket_uri.uri))
    self.assertEqual(1, len(actual))
    self.assertEqual('new', actual[0].object_name)

  # The remaining tests are pretty minimal - most just ensure a
  # basic use of each command runs, without checking more detailed
  # conditions/expectations.

  def TestCatCommmandRuns(self):
    """Test that the cat command basically runs"""
    self.command_runner.RunNamedCommand('cat',
                                        ['%sobj1' % self.src_bucket_uri.uri])

  def TestGetAclCommmandRuns(self):
    """Test that the GetAcl command basically runs"""
    self.command_runner.RunNamedCommand('getacl', [self.src_bucket_uri.uri])

  def TestGetDefAclCommmandRuns(self):
    """Test that the GetDefAcl command basically runs"""
    self.command_runner.RunNamedCommand('getacl', [self.src_bucket_uri.uri])

  def TestGetLoggingCommmandRuns(self):
    """Test that the GetLogging command basically runs"""
    self.command_runner.RunNamedCommand('getlogging', [self.src_bucket_uri.uri])

  def TestListCommandRuns(self):
    """Test that the ListCommand basically runs"""
    self.command_runner.RunNamedCommand('ls', [self.src_bucket_uri.uri])

  def TestMakeBucketsCommand(self):
    """Test MakeBucketsCommand on existing bucket"""
    try:
      self.command_runner.RunNamedCommand('mb', [self.dst_bucket_uri.uri])
      self.fail('Did not get expected StorageCreateError')
    except boto.exception.StorageCreateError, e:
      self.assertEqual(e.status, 409)

  def TestRemoveBucketsCommand(self):
    """Test RemoveBucketsCommand on non-existent bucket"""
    try:
      self.command_runner.RunNamedCommand('rb',
                                          ['gs://non_existent_%s' %
                                           self.dst_bucket_uri.bucket_name])
      self.fail('Did not get expected StorageResponseError')
    except boto.exception.StorageResponseError, e:
      self.assertEqual(e.status, 404)

  def TestRemoveObjsCommand(self):
    """Test RemoveObjsCommand on non-existent object"""
    try:
      self.command_runner.RunNamedCommand('rm', ['%snon_existent' %
                                      self.dst_bucket_uri.uri])
      self.fail('Did not get expected WildcardException')
    # For some reason if we catch this as "WildcardException" it doesn't
    # work right. Python bug?
    except Exception, e:
      self.assertNotEqual(e.reason.find('Not Found'), -1)

  def TestRemoveObjsCommandMulti(self):
    """Test RemoveObjsCommand on non-existent object with -m option"""
    self.parallel_operations = True
    self.TestRemoveObjsCommand()
    self.parallel_operations = False

  def TestSetAclCommmandRuns(self):
    """Test that the SetAcl command basically runs"""
    self.command_runner.RunNamedCommand('setacl', ['private',
                                                   self.src_bucket_uri.uri])

  def TestSetDefAclCommmandRuns(self):
    """Test that the SetDefAcl command basically runs"""
    self.command_runner.RunNamedCommand('setdefacl', ['private',
                                                      self.src_bucket_uri.uri])

  def TestDisableLoggingCommmandRuns(self):
    """Test that the DisableLogging command basically runs"""
    self.command_runner.RunNamedCommand('disablelogging',
                                        [self.src_bucket_uri.uri])

  def TestEnableLoggingCommmandRuns(self):
    """Test that the EnableLogging command basically runs"""
    self.command_runner.RunNamedCommand('enablelogging',
                                        ['-b', 'log_bucket',
                                         self.src_bucket_uri.uri])

  def TestVerCommmandRuns(self):
    """Test that the Ver command basically runs"""
    self.command_runner.RunNamedCommand('ver')

  def TestMinusDOptionWorks(self):
    """Tests using gsutil -D option"""
    src_file = self.SrcFile('f0')
    self.command_runner.RunNamedCommand('cp',
                                        [src_file, self.dst_bucket_uri.uri],
                                        debug=3)
    actual = list(test_util.test_wildcard_iterator('%s*' %
                                                   self.dst_bucket_uri.uri))
    self.assertEqual(1, len(actual))
    self.assertEqual('f0', actual[0].object_name)

  def DownloadTestHelper(self, func):
    """
    Test resumable download with custom test function to distort downloaded 
    data. We expect an exception to be raised and the dest file to be removed.
    """
    object_uri = self.all_src_obj_uris[0].uri
    try:
      self.command_runner.RunNamedCommand('cp', [object_uri, self.tmp_path], 
                                          test_method=func)
      self.fail('Did not get expected CommandException')
    except CommandException:
      self.assertFalse(os.path.exists(self.tmp_path))
    except:
      self.fail('Unexpected exception raised')

  def TestDownloadWithObjectSizeShange(self):
    """
    Test resumable download on an object that changes size before the 
    downloaded file's checksum is validated.
    """
    def append(fp):
      """Append a byte at end of an open file and flush contents."""
      fp.seek(0,2)
      fp.write('x')
      fp.flush()
    self.DownloadTestHelper(append)

  def TestDownloadWithFileContentChange(self):
    """
    Tests resumable download on an object where the file content changes
    before the downloaded file's checksum is validated.
    """
    def overwrite(fp):
      """Overwrite first byte in an open file and flush contents."""
      fp.seek(0)
      fp.write('x')
      fp.flush()
    self.DownloadTestHelper(overwrite)

if __name__ == '__main__':
  if sys.version_info[:3] < (2, 5, 1):
    sys.exit('These tests must be run on at least Python 2.5.1\n')
  test_loader = unittest.TestLoader()
  test_loader.testMethodPrefix = 'Test'
  suite = test_loader.loadTestsFromTestCase(GsutilCommandTests)
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
