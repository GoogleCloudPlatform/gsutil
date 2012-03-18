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

"""Unit tests for gslib wildcard_iterator"""

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
from boto import InvalidUriError
from gslib import test_util
from gslib import wildcard_iterator
from gslib.project_id import ProjectIdHandler
from tests.s3 import mock_storage_service
from wildcard_iterator import ContainsWildcard


class CloudWildcardIteratorTests(unittest.TestCase):
  """CloudWildcardIterator test suite"""

  def GetSuiteDescription(self):
    return 'CloudWildcardIterator test suite'

  @classmethod
  def SetUpClass(cls):
    """Creates 2 mock buckets, each containing 4 objects, including 1 nested."""
    cls.immed_child_obj_names = ['abcd', 'abdd', 'ade$']
    cls.all_obj_names = ['abcd', 'abdd', 'ade$', 'nested1/nested2/xyz1',
                         'nested1/nested2/xyz2']
    cls.base_uri_str = 'gs://gslib_test_%d' % int(time.time())
    cls.test_bucket0_uri, cls.test_bucket0_obj_uri_strs = (
        cls.__SetUpOneMockBucket(0)
    )
    cls.test_bucket1_uri, cls.test_bucket1_obj_uri_strs = (
        cls.__SetUpOneMockBucket(1)
    )
    cls.created_test_data = True

  @classmethod
  def __SetUpOneMockBucket(cls, bucket_num):
    """Creates a mock bucket containing 4 objects, including 1 nested.
    Args:
      bucket_num: Number for building bucket name.

    Returns:
      tuple: (bucket name, set of object URI strings).
    """
    bucket_uri = test_util.test_storage_uri(
        '%s_%s' % (cls.base_uri_str, bucket_num))
    bucket_uri.create_bucket()
    obj_uri_strs = set()
    for obj_name in cls.all_obj_names:
      obj_uri = test_util.test_storage_uri('%s%s' % (bucket_uri, obj_name))
      key = obj_uri.new_key()
      key.set_contents_from_string('')
      obj_uri_strs.add(str(obj_uri))
    return (bucket_uri, obj_uri_strs)

  @classmethod
  def TearDownClass(cls):
    """Cleans up bucket and objects created by SetUpClass"""
    if hasattr(cls, 'created_test_data'):
      for test_obj_uri_str in cls.test_bucket0_obj_uri_strs:
        test_util.test_storage_uri(test_obj_uri_str).delete_key()
      for test_obj_uri_str in cls.test_bucket1_obj_uri_strs:
        test_util.test_storage_uri(test_obj_uri_str).delete_key()
      cls.test_bucket0_uri.delete_bucket()
      cls.test_bucket1_uri.delete_bucket()

  def TestNoOpObjectIterator(self):
    """Tests that bucket-only URI iterates just that one URI"""
    results = list(
        test_util.test_wildcard_iterator(self.test_bucket0_uri).IterUris())
    self.assertEqual(1, len(results))
    self.assertEqual(str(self.test_bucket0_uri), str(results[0]))

  def TestMatchingAllObjects(self):
    """Tests matching all objects, based on wildcard"""
    actual_obj_uri_strs = set(
        str(u) for u in test_util.test_wildcard_iterator(
            self.test_bucket0_uri.clone_replace_name('**')).IterUris())
    self.assertEqual(self.test_bucket0_obj_uri_strs, actual_obj_uri_strs)

  def TestMatchingObjectSubset(self):
    """Tests matching a subset of objects, based on wildcard"""
    exp_obj_uri_strs = set(
        [str(self.test_bucket0_uri.clone_replace_name('abcd')),
         str(self.test_bucket0_uri.clone_replace_name('abdd'))])
    actual_obj_uri_strs = set(
        str(u) for u in test_util.test_wildcard_iterator(
            self.test_bucket0_uri.clone_replace_name('ab??')).IterUris())
    self.assertEqual(exp_obj_uri_strs, actual_obj_uri_strs)

  def TestMatchingNonWildcardedUri(self):
    """Tests matching a single named object"""
    exp_obj_uri_strs = set([str(self.test_bucket0_uri.clone_replace_name('abcd')
                               )])
    actual_obj_uri_strs = set(
        str(u) for u in test_util.test_wildcard_iterator(
            self.test_bucket0_uri.clone_replace_name('abcd')).IterUris())
    self.assertEqual(exp_obj_uri_strs, actual_obj_uri_strs)

  def TestWildcardedObjectUriWithVsWithoutPrefix(self):
    """Tests that wildcarding w/ and w/o server prefix get same result"""
    # (It's just more efficient to query w/o a prefix; wildcard
    # iterator will filter the matches either way.)
    with_prefix_uri_strs = set(
        str(u) for u in test_util.test_wildcard_iterator(
            self.test_bucket0_uri.clone_replace_name('abcd')).IterUris())
    # By including a wildcard at the start of the string no prefix can be
    # used in server request.
    no_prefix_uri_strs = set(
        str(u) for u in test_util.test_wildcard_iterator(
            self.test_bucket0_uri.clone_replace_name('?bcd')).IterUris())
    self.assertEqual(with_prefix_uri_strs, no_prefix_uri_strs)

  def TestWildcardedObjectUriNestedSubdirMatch(self):
    """Tests wildcarding with a nested subdir"""
    uri_strs = set()
    prefixes = set()
    for blr in test_util.test_wildcard_iterator(
        self.test_bucket0_uri.clone_replace_name('*')):
      if blr.HasPrefix():
        prefixes.add(blr.GetPrefix().name)
      else:
        uri_strs.add(blr.GetUri().uri)
    exp_obj_uri_strs = set(['%s_0/%s' % (self.base_uri_str, x)
        for x in self.immed_child_obj_names])
    self.assertEqual(exp_obj_uri_strs, uri_strs)
    self.assertEqual(1, len(prefixes))
    self.assertTrue('nested1/' in prefixes)

  def TestWildcardedObjectUriNestedSubSubdirMatch(self):
    """Tests wildcarding with a nested sub-subdir"""
    for final_char in ('', '/'):
      uri_strs = set()
      prefixes = set()
      for blr in test_util.test_wildcard_iterator(
          self.test_bucket0_uri.clone_replace_name('nested1/*%s' % final_char)):
        if blr.HasPrefix():
          prefixes.add(blr.GetPrefix().name)
        else:
          uri_strs.add(blr.GetUri().uri)
      self.assertEqual(0, len(uri_strs))
      self.assertEqual(1, len(prefixes))
      self.assertTrue('nested1/nested2/' in prefixes)

  def TestNoMatchingWildcardedObjectUri(self):
    """Tests that get back an empty iterator for non-matching wildcarded URI"""
    res = list(test_util.test_wildcard_iterator(
        self.test_bucket0_uri.clone_replace_name('*x0')).IterUris())
    self.assertEqual(0, len(res))

  def TestWildcardedInvalidObjectUri(self):
    """Tests that we raise an exception for wildcarded invalid URI"""
    try:
      for unused_ in test_util.test_wildcard_iterator(
          'badscheme://asdf').IterUris():
        self.assertFalse('Expected InvalidUriError not raised.')
    except InvalidUriError, e:
      # Expected behavior.
      self.assertTrue(e.message.find('Unrecognized scheme') != -1)

  def TestSingleMatchWildcardedBucketUri(self):
    """Tests matching a single bucket based on a wildcarded bucket URI"""
    exp_obj_uri_strs = set(['%s_1/' % self.base_uri_str])
    actual_obj_uri_strs = set(
        str(u) for u in test_util.test_wildcard_iterator(
            '%s*1' % self.base_uri_str).IterUris())
    self.assertEqual(exp_obj_uri_strs, actual_obj_uri_strs)

  def TestMultiMatchWildcardedBucketUri(self):
    """Tests matching a multiple buckets based on a wildcarded bucket URI"""
    exp_obj_uri_strs = set(['%s_%s/' %
                            (self.base_uri_str, i) for i in range(2)])
    actual_obj_uri_strs = set(
        str(u) for u in test_util.test_wildcard_iterator(
            '%s*' % self.base_uri_str).IterUris())
    self.assertEqual(exp_obj_uri_strs, actual_obj_uri_strs)

  def TestWildcardBucketAndObjectUri(self):
    """Tests matching with both bucket and object wildcards"""
    exp_obj_uri_strs = set([str(self.test_bucket0_uri.clone_replace_name(
        'abcd'))])
    actual_obj_uri_strs = set(
        str(u) for u in test_util.test_wildcard_iterator(
            '%s_0*/abc*' % self.base_uri_str).IterUris())
    self.assertEqual(exp_obj_uri_strs, actual_obj_uri_strs)

  def TestWildcardUpToFinalCharSubdirPlusObjectName(self):
    """Tests wildcard subd*r/obj name"""
    exp_obj_uri_strs = set([str(self.test_bucket0_uri.clone_replace_name(
        'nested1/nested2/xyz1'))])
    x=list(test_util.test_wildcard_iterator(
        '%s**' % self.test_bucket0_uri.uri).IterUris())
    actual_obj_uri_strs = set(
        str(u) for u in test_util.test_wildcard_iterator(
            '%snested1/nest*2/xyz1' % self.test_bucket0_uri.uri).IterUris())
    self.assertEqual(exp_obj_uri_strs, actual_obj_uri_strs)

  def TestPostRecursiveWildcard(self):
    """Tests that wildcard containing ** followed by an additional wildcard works"""
    exp_obj_uri_strs = set([str(self.test_bucket0_uri.clone_replace_name(
        'nested1/nested2/xyz2'))])
    actual_obj_uri_strs = set(
        str(u) for u in test_util.test_wildcard_iterator(
            '%s**/*y*2' % self.test_bucket0_uri.uri).IterUris())
    self.assertEqual(exp_obj_uri_strs, actual_obj_uri_strs)

  def TestCallingGetKeyOnProviderOnlyWildcardIteration(self):
    """Tests that attempting iterating provider-only wildcard raises"""
    try:
      from gslib.bucket_listing_ref import BucketListingRefException
      for iter_result in wildcard_iterator.wildcard_iterator(
          'gs://', ProjectIdHandler(),
          bucket_storage_uri_class=mock_storage_service.MockBucketStorageUri):
        iter_result.GetKey()
        self.fail('Expected BucketListingRefException not raised.')
    except BucketListingRefException, e:
      self.assertTrue(str(e).find(
          'Attempt to call GetKey() on Key-less BucketListingRef') != -1)


class FileIteratorTests(unittest.TestCase):
  """FileWildcardIterator test suite"""

  def GetSuiteDescription(self):
    return 'FileWildcardIterator test suite'

  @classmethod
  def SetUpClass(cls):
    """
    Creates a test dir containing 3 files and one nested subdirectory + file.
    """

    # Create the test directories.
    cls.test_dir = tempfile.mkdtemp()
    nested_subdir = '%s%sdir1%sdir2' % (cls.test_dir, os.sep, os.sep)
    os.makedirs(nested_subdir)

    # Create the test files.
    immed_child_filenames = ['abcd', 'abdd', 'ade$', 'dir1']
    immed_child_filepaths = ['%s%s%s' % (cls.test_dir, os.sep, f)
                             for f in immed_child_filenames]
    filenames = ['abcd', 'abdd', 'ade$', 'dir1%sdir2%szzz' % (os.sep, os.sep)]
    filepaths = ['%s%s%s' % (cls.test_dir, os.sep, f) for f in filenames]
    for filepath in filepaths:
      open(filepath, 'w')

    # Set up global test variables.
    cls.immed_child_uri_strs = set(
        os.path.join('file://%s' % f) for f in immed_child_filepaths
    )

    cls.all_file_uri_strs = set(
        [('file://%s' % o) for o in filepaths]
    )

    cls.all_uri_strs = set(
        ['file://%s' % nested_subdir]
    ).union(cls.all_file_uri_strs)

  @classmethod
  def TearDownClass(cls):
    """Cleans up test dir and file created by SetUpClass"""
    if hasattr(cls, 'test_dir'):
      shutil.rmtree(cls.test_dir)

  def TestContainsWildcard(self):
    """Tests ContainsWildcard call"""
    self.assertTrue(ContainsWildcard('a*.txt'))
    self.assertTrue(ContainsWildcard('a[0-9].txt'))
    self.assertFalse(ContainsWildcard('0-9.txt'))
    self.assertTrue(ContainsWildcard('?.txt'))

  def TestNoOpDirectoryIterator(self):
    """Tests that directory-only URI iterates just that one URI"""
    results = list(test_util.test_wildcard_iterator('file:///tmp/').IterUris())
    self.assertEqual(1, len(results))
    self.assertEqual('file:///tmp/', str(results[0]))

  def TestMatchingAllFiles(self):
    """Tests matching all files, based on wildcard"""
    uri = test_util.test_storage_uri('file://%s/*' % self.test_dir)
    actual_uri_strs = set(str(u) for u in
                          test_util.test_wildcard_iterator(uri).IterUris()
                         )
    self.assertEqual(self.immed_child_uri_strs, actual_uri_strs)

  def TestMatchingFileSubset(self):
    """Tests matching a subset of files, based on wildcard"""
    exp_uri_strs = set(
        ['file://%s/abcd' % self.test_dir, 'file://%s/abdd' % self.test_dir]
    )
    uri = test_util.test_storage_uri('file://%s/ab??' % self.test_dir)
    actual_uri_strs = set(str(u) for u in
                          test_util.test_wildcard_iterator(uri).IterUris()
                         )
    self.assertEqual(exp_uri_strs, actual_uri_strs)

  def TestMatchingNonWildcardedUri(self):
    """Tests matching a single named file"""
    exp_uri_strs = set(['file://%s/abcd' % self.test_dir])
    uri = test_util.test_storage_uri('file://%s/abcd' % self.test_dir)
    actual_uri_strs = set(
        str(u) for u in test_util.test_wildcard_iterator(uri).IterUris())
    self.assertEqual(exp_uri_strs, actual_uri_strs)

  def TestMatchingFilesIgnoringOtherRegexChars(self):
    """Tests ignoring non-wildcard regex chars (e.g., ^ and $)"""

    exp_uri_strs = set(['file://%s/ade$' % self.test_dir])
    uri = test_util.test_storage_uri('file://%s/ad*$' % self.test_dir)
    actual_uri_strs = set(
        str(u) for u in test_util.test_wildcard_iterator(uri).IterUris())
    self.assertEqual(exp_uri_strs, actual_uri_strs)

  def TestRecursiveDirectoryOnlyWildcarding(self):
    """Tests recusive expansion of directory-only '**' wildcard"""
    uri = test_util.test_storage_uri('file://%s/**' % self.test_dir)
    actual_uri_strs = set(
        str(u) for u in test_util.test_wildcard_iterator(uri).IterUris())
    self.assertEqual(self.all_file_uri_strs, actual_uri_strs)

  def TestRecursiveDirectoryPlusFileWildcarding(self):
    """Tests recusive expansion of '**' directory plus '*' wildcard"""
    uri = test_util.test_storage_uri('file://%s/**/*' % self.test_dir)
    actual_uri_strs = set(
        str(u) for u in test_util.test_wildcard_iterator(uri).IterUris())
    self.assertEqual(self.all_file_uri_strs, actual_uri_strs)

  def TestInvalidRecursiveDirectoryWildcard(self):
    """Tests that wildcard containing '***' raises exception"""
    try:
      uri = test_util.test_storage_uri('file://%s/***/abcd' % self.test_dir)
      for unused_ in test_util.test_wildcard_iterator(uri).IterUris():
        self.fail('Expected WildcardException not raised.')
    except wildcard_iterator.WildcardException, e:
      # Expected behavior.
      self.assertTrue(str(e).find('more than 2 consecutive') != -1)

  def TestMissingDir(self):
    """Tests that wildcard gets empty iterator when directory doesn't exist"""
    res = list(
        test_util.test_wildcard_iterator('file://no_such_dir/*').IterUris())
    self.assertEqual(0, len(res))

  def TestExistingDirNoFileMatch(self):
    """Tests that wildcard returns empty iterator when there's no match"""
    uri = test_util.test_storage_uri(
        'file://%s/non_existent*' % self.test_dir)
    res = list(test_util.test_wildcard_iterator(uri).IterUris())
    self.assertEqual(0, len(res))


if __name__ == '__main__':
  if sys.version_info[:3] < (2, 5, 1):
    sys.exit('These tests must be run on at least Python 2.5.1\n')
  test_loader = unittest.TestLoader()
  test_loader.testMethodPrefix = 'Test'
  for suite in (test_loader.loadTestsFromTestCase(CloudWildcardIteratorTests),
                test_loader.loadTestsFromTestCase(FileIteratorTests)):
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
