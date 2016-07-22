# -*- coding: utf-8 -*-
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
"""Unit tests for gsutil wildcard_iterator."""

from __future__ import absolute_import

import os
import tempfile

from gslib import wildcard_iterator
from gslib.exception import InvalidUrlError
from gslib.storage_url import ContainsWildcard
import gslib.tests.testcase as testcase
from gslib.tests.util import ObjectToURI as suri
from gslib.tests.util import SetDummyProjectForUnitTest


class CloudWildcardIteratorTests(testcase.GsUtilUnitTestCase):
  """Unit tests for CloudWildcardIterator."""

  def setUp(self):
    """Creates 2 mock buckets, each containing 4 objects, including 1 nested."""
    super(CloudWildcardIteratorTests, self).setUp()
    self.immed_child_obj_names = ['abcd', 'abdd', 'ade$']
    self.all_obj_names = ['abcd', 'abdd', 'ade$', 'nested1/nested2/xyz1',
                          'nested1/nested2/xyz2', 'nested1/nfile_abc']

    self.base_bucket_uri = self.CreateBucket()
    self.prefix_bucket_name = '%s_' % self.base_bucket_uri.bucket_name[:61]
    self.base_uri_str = suri(self.base_bucket_uri)
    self.base_uri_str = self.base_uri_str.replace(
        self.base_bucket_uri.bucket_name, self.prefix_bucket_name)

    self.test_bucket0_uri = self.CreateBucket(
        bucket_name='%s0' % self.prefix_bucket_name)
    self.test_bucket0_obj_uri_strs = set()
    for obj_name in self.all_obj_names:
      obj_uri = self.CreateObject(bucket_uri=self.test_bucket0_uri,
                                  object_name=obj_name, contents='')
      self.test_bucket0_obj_uri_strs.add(suri(obj_uri))

    self.test_bucket1_uri = self.CreateBucket(
        bucket_name='%s1' % self.prefix_bucket_name)
    self.test_bucket1_obj_uri_strs = set()
    for obj_name in self.all_obj_names:
      obj_uri = self.CreateObject(bucket_uri=self.test_bucket1_uri,
                                  object_name=obj_name, contents='')
      self.test_bucket1_obj_uri_strs.add(suri(obj_uri))

  def testNoOpObjectIterator(self):
    """Tests that bucket-only URI iterates just that one URI."""
    results = list(
        self._test_wildcard_iterator(self.test_bucket0_uri).IterBuckets(
            bucket_fields=['id']))
    self.assertEqual(1, len(results))
    self.assertEqual(str(self.test_bucket0_uri), str(results[0]))

  def testMatchingAllObjects(self):
    """Tests matching all objects, based on wildcard."""
    actual_obj_uri_strs = set(
        str(u) for u in self._test_wildcard_iterator(
            self.test_bucket0_uri.clone_replace_name('**')).IterAll(
                expand_top_level_buckets=True))
    self.assertEqual(self.test_bucket0_obj_uri_strs, actual_obj_uri_strs)

  def testMatchingObjectSubset(self):
    """Tests matching a subset of objects, based on wildcard."""
    exp_obj_uri_strs = set(
        [str(self.test_bucket0_uri.clone_replace_name('abcd')),
         str(self.test_bucket0_uri.clone_replace_name('abdd'))])
    actual_obj_uri_strs = set(
        str(u) for u in self._test_wildcard_iterator(
            self.test_bucket0_uri.clone_replace_name('ab??')).IterAll(
                expand_top_level_buckets=True))
    self.assertEqual(exp_obj_uri_strs, actual_obj_uri_strs)

  def testMatchingNonWildcardedUri(self):
    """Tests matching a single named object."""
    exp_obj_uri_strs = set([str(self.test_bucket0_uri.clone_replace_name('abcd')
                               )])
    actual_obj_uri_strs = set(
        str(u) for u in self._test_wildcard_iterator(
            self.test_bucket0_uri.clone_replace_name('abcd')).IterAll(
                expand_top_level_buckets=True))
    self.assertEqual(exp_obj_uri_strs, actual_obj_uri_strs)

  def testWildcardedObjectUriWithVsWithoutPrefix(self):
    """Tests that wildcarding w/ and w/o server prefix get same result."""
    # (It's just more efficient to query w/o a prefix; wildcard
    # iterator will filter the matches either way.)
    with_prefix_uri_strs = set(
        str(u) for u in self._test_wildcard_iterator(
            self.test_bucket0_uri.clone_replace_name('abcd')).IterAll(
                expand_top_level_buckets=True))
    # By including a wildcard at the start of the string no prefix can be
    # used in server request.
    no_prefix_uri_strs = set(
        str(u) for u in self._test_wildcard_iterator(
            self.test_bucket0_uri.clone_replace_name('?bcd')).IterAll(
                expand_top_level_buckets=True))
    self.assertEqual(with_prefix_uri_strs, no_prefix_uri_strs)

  def testWildcardedObjectUriNestedSubdirMatch(self):
    """Tests wildcarding with a nested subdir."""
    uri_strs = set()
    prefixes = set()
    for blr in self._test_wildcard_iterator(
        self.test_bucket0_uri.clone_replace_name('*')):
      if blr.IsPrefix():
        prefixes.add(blr.root_object)
      else:
        uri_strs.add(blr.url_string)
    exp_obj_uri_strs = set([suri(self.test_bucket0_uri, x)
                            for x in self.immed_child_obj_names])
    self.assertEqual(exp_obj_uri_strs, uri_strs)
    self.assertEqual(1, len(prefixes))
    self.assertTrue('nested1/' in prefixes)

  def testWildcardPlusSubdirMatch(self):
    """Tests gs://bucket/*/subdir matching."""
    actual_uri_strs = set()
    actual_prefixes = set()
    for blr in self._test_wildcard_iterator(
        self.test_bucket0_uri.clone_replace_name('*/nested1')):
      if blr.IsPrefix():
        actual_prefixes.add(blr.root_object)
      else:
        actual_uri_strs.add(blr.url_string)
    expected_uri_strs = set()
    expected_prefixes = set(['nested1/'])
    self.assertEqual(expected_prefixes, actual_prefixes)
    self.assertEqual(expected_uri_strs, actual_uri_strs)

  def testWildcardPlusSubdirSubdirMatch(self):
    """Tests gs://bucket/*/subdir/* matching."""
    actual_uri_strs = set()
    actual_prefixes = set()
    for blr in self._test_wildcard_iterator(
        self.test_bucket0_uri.clone_replace_name('*/nested2/*')):
      if blr.IsPrefix():
        actual_prefixes.add(blr.root_object)
      else:
        actual_uri_strs.add(blr.url_string)
    expected_uri_strs = set([
        self.test_bucket0_uri.clone_replace_name('nested1/nested2/xyz1').uri,
        self.test_bucket0_uri.clone_replace_name('nested1/nested2/xyz2').uri])
    expected_prefixes = set()
    self.assertEqual(expected_prefixes, actual_prefixes)
    self.assertEqual(expected_uri_strs, actual_uri_strs)

  def testNoMatchingWildcardedObjectUri(self):
    """Tests that get back an empty iterator for non-matching wildcarded URI."""
    res = list(self._test_wildcard_iterator(
        self.test_bucket0_uri.clone_replace_name('*x0')).IterAll(
            expand_top_level_buckets=True))
    self.assertEqual(0, len(res))

  def testWildcardedInvalidObjectUri(self):
    """Tests that we raise an exception for wildcarded invalid URI."""
    try:
      for unused_ in self._test_wildcard_iterator(
          'badscheme://asdf').IterAll(expand_top_level_buckets=True):
        self.assertFalse('Expected InvalidUrlError not raised.')
    except InvalidUrlError, e:
      # Expected behavior.
      self.assertTrue(e.message.find('Unrecognized scheme') != -1)

  def testSingleMatchWildcardedBucketUri(self):
    """Tests matching a single bucket based on a wildcarded bucket URI."""
    exp_obj_uri_strs = set([
        suri(self.test_bucket1_uri) + self.test_bucket1_uri.delim])
    with SetDummyProjectForUnitTest():
      actual_obj_uri_strs = set(
          str(u) for u in self._test_wildcard_iterator(
              '%s*1' % self.base_uri_str).IterBuckets(bucket_fields=['id']))
    self.assertEqual(exp_obj_uri_strs, actual_obj_uri_strs)

  def testMultiMatchWildcardedBucketUri(self):
    """Tests matching a multiple buckets based on a wildcarded bucket URI."""
    exp_obj_uri_strs = set([
        suri(self.test_bucket0_uri) + self.test_bucket0_uri.delim,
        suri(self.test_bucket1_uri) + self.test_bucket1_uri.delim])
    with SetDummyProjectForUnitTest():
      actual_obj_uri_strs = set(
          str(u) for u in self._test_wildcard_iterator(
              '%s*' % self.base_uri_str).IterBuckets(bucket_fields=['id']))
    self.assertEqual(exp_obj_uri_strs, actual_obj_uri_strs)

  def testWildcardBucketAndObjectUri(self):
    """Tests matching with both bucket and object wildcards."""
    exp_obj_uri_strs = set([str(self.test_bucket0_uri.clone_replace_name(
        'abcd'))])
    with SetDummyProjectForUnitTest():
      actual_obj_uri_strs = set(
          str(u) for u in self._test_wildcard_iterator(
              '%s0*/abc*' % self.base_uri_str).IterAll(
                  expand_top_level_buckets=True))
    self.assertEqual(exp_obj_uri_strs, actual_obj_uri_strs)

  def testWildcardUpToFinalCharSubdirPlusObjectName(self):
    """Tests wildcard subd*r/obj name."""
    exp_obj_uri_strs = set([str(self.test_bucket0_uri.clone_replace_name(
        'nested1/nested2/xyz1'))])
    actual_obj_uri_strs = set(
        str(u) for u in self._test_wildcard_iterator(
            '%snested1/nest*2/xyz1' % self.test_bucket0_uri.uri).IterAll(
                expand_top_level_buckets=True))
    self.assertEqual(exp_obj_uri_strs, actual_obj_uri_strs)

  def testPostRecursiveWildcard(self):
    """Tests wildcard containing ** followed by an additional wildcard."""
    exp_obj_uri_strs = set([str(self.test_bucket0_uri.clone_replace_name(
        'nested1/nested2/xyz2'))])
    actual_obj_uri_strs = set(
        str(u) for u in self._test_wildcard_iterator(
            '%s**/*y*2' % self.test_bucket0_uri.uri).IterAll(
                expand_top_level_buckets=True))
    self.assertEqual(exp_obj_uri_strs, actual_obj_uri_strs)

  def testWildcardFields(self):
    """Tests that wildcard w/fields specification returns correct fields."""
    blrs = set(
        u for u in self._test_wildcard_iterator(
            self.test_bucket0_uri.clone_replace_name('**')).IterAll(
                bucket_listing_fields=['timeCreated']))
    self.assertTrue(len(blrs))
    for blr in blrs:
      self.assertTrue(blr.root_object and blr.root_object.timeCreated)
    blrs = set(
        u for u in self._test_wildcard_iterator(
            self.test_bucket0_uri.clone_replace_name('**')).IterAll(
                bucket_listing_fields=['generation']))
    self.assertTrue(len(blrs))
    for blr in blrs:
      self.assertTrue(blr.root_object and not blr.root_object.timeCreated)


class FileIteratorTests(testcase.GsUtilUnitTestCase):
  """Unit tests for FileWildcardIterator."""

  def setUp(self):
    """Creates a test dir with 3 files and one nested subdirectory + file."""
    super(FileIteratorTests, self).setUp()

    self.test_dir = self.CreateTempDir(test_files=[
        'abcd', 'abdd', 'ade$', ('dir1', 'dir2', 'zzz')])

    self.root_files_uri_strs = set([
        suri(self.test_dir, 'abcd'),
        suri(self.test_dir, 'abdd'),
        suri(self.test_dir, 'ade$')])

    self.subdirs_uri_strs = set([suri(self.test_dir, 'dir1')])

    self.nested_files_uri_strs = set([
        suri(self.test_dir, 'dir1', 'dir2', 'zzz')])

    self.immed_child_uri_strs = self.root_files_uri_strs | self.subdirs_uri_strs
    self.all_file_uri_strs = (
        self.root_files_uri_strs | self.nested_files_uri_strs)

  def testContainsWildcard(self):
    """Tests ContainsWildcard call."""
    self.assertTrue(ContainsWildcard('a*.txt'))
    self.assertTrue(ContainsWildcard('a[0-9].txt'))
    self.assertFalse(ContainsWildcard('0-9.txt'))
    self.assertTrue(ContainsWildcard('?.txt'))

  def testNoOpDirectoryIterator(self):
    """Tests that directory-only URI iterates just that one URI."""
    results = list(
        self._test_wildcard_iterator(suri(tempfile.tempdir)).IterAll(
            expand_top_level_buckets=True))
    self.assertEqual(1, len(results))
    self.assertEqual(suri(tempfile.tempdir), str(results[0]))

  def testMatchingAllFiles(self):
    """Tests matching all files, based on wildcard."""
    uri = self._test_storage_uri(suri(self.test_dir, '*'))
    actual_uri_strs = set(str(u) for u in
                          self._test_wildcard_iterator(uri).IterAll(
                              expand_top_level_buckets=True))
    self.assertEqual(self.immed_child_uri_strs, actual_uri_strs)

  def testMatchingAllFilesWithSize(self):
    """Tests matching all files, based on wildcard."""
    uri = self._test_storage_uri(suri(self.test_dir, '*'))
    blrs = self._test_wildcard_iterator(uri).IterAll(
        expand_top_level_buckets=True, bucket_listing_fields=['size'])
    num_expected_objects = 3
    num_actual_objects = 0
    for blr in blrs:
      self.assertTrue(str(blr) in self.immed_child_uri_strs)
      if blr.IsObject():
        num_actual_objects += 1
        # Size is based on contents "Test N" as created by CreateTempDir.
        self.assertEqual(blr.root_object.size, 6)
    self.assertEqual(num_expected_objects, num_actual_objects)

  def testMatchingFileSubset(self):
    """Tests matching a subset of files, based on wildcard."""
    exp_uri_strs = set(
        [suri(self.test_dir, 'abcd'), suri(self.test_dir, 'abdd')])
    uri = self._test_storage_uri(suri(self.test_dir, 'ab??'))
    actual_uri_strs = set(str(u) for u in
                          self._test_wildcard_iterator(uri).IterAll(
                              expand_top_level_buckets=True))
    self.assertEqual(exp_uri_strs, actual_uri_strs)

  def testMatchingNonWildcardedUri(self):
    """Tests matching a single named file."""
    exp_uri_strs = set([suri(self.test_dir, 'abcd')])
    uri = self._test_storage_uri(suri(self.test_dir, 'abcd'))
    actual_uri_strs = set(
        str(u) for u in self._test_wildcard_iterator(uri).IterAll(
            expand_top_level_buckets=True))
    self.assertEqual(exp_uri_strs, actual_uri_strs)

  def testMatchingFilesIgnoringOtherRegexChars(self):
    """Tests ignoring non-wildcard regex chars (e.g., ^ and $)."""

    exp_uri_strs = set([suri(self.test_dir, 'ade$')])
    uri = self._test_storage_uri(suri(self.test_dir, 'ad*$'))
    actual_uri_strs = set(
        str(u) for u in self._test_wildcard_iterator(uri).IterAll(
            expand_top_level_buckets=True))
    self.assertEqual(exp_uri_strs, actual_uri_strs)

  def testRecursiveDirectoryOnlyWildcarding(self):
    """Tests recursive expansion of directory-only '**' wildcard."""
    uri = self._test_storage_uri(suri(self.test_dir, '**'))
    actual_uri_strs = set(
        str(u) for u in self._test_wildcard_iterator(uri).IterAll(
            expand_top_level_buckets=True))
    self.assertEqual(self.all_file_uri_strs, actual_uri_strs)

  def testRecursiveDirectoryPlusFileWildcarding(self):
    """Tests recursive expansion of '**' directory plus '*' wildcard."""
    uri = self._test_storage_uri(suri(self.test_dir, '**', '*'))
    actual_uri_strs = set(
        str(u) for u in self._test_wildcard_iterator(uri).IterAll(
            expand_top_level_buckets=True))
    self.assertEqual(self.all_file_uri_strs, actual_uri_strs)

  def testInvalidRecursiveDirectoryWildcard(self):
    """Tests that wildcard containing '***' raises exception."""
    try:
      uri = self._test_storage_uri(suri(self.test_dir, '***', 'abcd'))
      for unused_ in self._test_wildcard_iterator(uri).IterAll(
          expand_top_level_buckets=True):
        self.fail('Expected WildcardException not raised.')
    except wildcard_iterator.WildcardException, e:
      # Expected behavior.
      self.assertTrue(str(e).find('more than 2 consecutive') != -1)

  def testNotFollowingDirectorySymbolicLinksByDefault(self):
    """Tests that it follows non-recursive symlinks."""
    helper = _FileWildcardIteratorTestHelper(self.CreateTempDir())
    helper.mk_file('a1/f1')
    helper.mk_file('a2/f2')
    helper.symlink('a1/a2', '../a2')
    helper.symlink('a1/a2_bis', '../a2')

    self.assertItemsEqual(helper.run_wildcard_iterator(), [
        'a1/f1',
        'a2/f2',
    ])

  def testFollowsDirectorySymbolicLinks1(self):
    """Tests that it follows non-recursive symlinks."""
    helper = _FileWildcardIteratorTestHelper(self.CreateTempDir())
    helper.mk_file('a1/f1')
    helper.mk_file('a2/f2')
    helper.symlink('a1/a2', '../a2')
    helper.symlink('a1/a2_bis', '../a2')

    self.assertItemsEqual(helper.run_wildcard_iterator(copy_links=True), [
        'a1/a2/f2',
        'a1/a2_bis/f2',
        'a1/f1',
        'a2/f2',
    ])

  def testFollowsDirectorySymbolicLinks2(self):
    """Tests that it ignore cycle pointing to same directory."""
    helper = _FileWildcardIteratorTestHelper(self.CreateTempDir())
    helper.symlink('1/t2', '../2')
    helper.symlink('2/t3', '../3')
    helper.symlink('3/t1-cyclic', '../1')
    helper.mk_file('2/f1')
    helper.mk_file('3/f2')

    self.assertItemsEqual(helper.run_wildcard_iterator('1', copy_links=True), [
        '1/t2/f1',
        '1/t2/t3/f2',
    ])

  def testFollowsDirectorySymbolicLinks3(self):
    """Test that it ignores cycles."""
    helper = _FileWildcardIteratorTestHelper(self.CreateTempDir())
    helper.symlink('1/a1/cycle1', '..')
    helper.symlink('1/a1/b1/cycle2', '../../a2')
    helper.mk_file('1/a1/b1/f1')
    helper.symlink('1/a2/b2/cycle2', '../../a1')
    helper.symlink('1/a3/b3', '../../2')
    helper.mk_file('1/a2/b2/f2')
    helper.symlink('2/cycle3', '..')
    helper.symlink('2/cycle4', '../1')
    helper.symlink('2/a4', '../1/a1')
    helper.mk_file('2/f3')

    self.assertItemsEqual(helper.run_wildcard_iterator('1', copy_links=True), [
        '1/a1/b1/f1',
        '1/a2/b2/f2',
        '1/a2/b2/cycle2/b1/f1',
        '1/a3/b3/f3',
        '1/a3/b3/a4/b1/f1',
    ])

  def testFollowsDirectorySymbolicLinks4(self):
    """Test it does include symlinks starting by the same path."""
    helper = _FileWildcardIteratorTestHelper(self.CreateTempDir())
    helper.symlink('1/a', '../1b/a')
    helper.symlink('1/b', '../1b')
    helper.mk_file('1b/f1')
    helper.mk_file('1b/a/f2')

    self.assertItemsEqual(helper.run_wildcard_iterator('1', copy_links=True), [
        '1/a/f2',
        '1/b/f1',
        '1/b/a/f2',
    ])

  def testFollowsDirectorySymbolicLinks5(self):
    """Test complex symlinks pointing to more and more base directory."""
    helper = _FileWildcardIteratorTestHelper(self.CreateTempDir())
    helper.symlink('1/1', '../2/a/b')
    helper.symlink('1/2', '../2/a')
    helper.symlink('1/3', '../3')
    helper.mk_file('2/f1')
    helper.mk_file('2/a/f2')
    helper.mk_file('2/a/b/f3')
    helper.symlink('3/4', '../2')

    self.assertItemsEqual(helper.run_wildcard_iterator('1', copy_links=True), [
        '1/1/f3',
        '1/2/b/f3',
        '1/2/f2',
        '1/3/4/a/b/f3',
        '1/3/4/a/f2',
        '1/3/4/f1',
    ])

  def testFollowsDirectorySymbolicLinks6(self):
    """Test symlink pointing to symlink from symlink basedir."""
    helper = _FileWildcardIteratorTestHelper(self.CreateTempDir())
    helper.symlink('1', '2')
    helper.symlink('2/3', '../3')
    helper.mk_file('2/f1')
    helper.symlink('3', '4')
    helper.symlink('4/cycle1', '../3')
    helper.symlink('4/cycle2', '..')
    helper.symlink('4/cycle3', '../2')
    helper.symlink('4/cycle4', '../2/3')
    helper.mk_file('4/f2')

    self.assertItemsEqual(helper.run_wildcard_iterator('1', copy_links=True), [
        '1/f1',
        '1/3/f2',
    ])

  def testFollowsDirectorySymbolicLinkToNotExisting(self):
    """Test invalid symlinks."""
    helper = _FileWildcardIteratorTestHelper(self.CreateTempDir())
    helper.symlink('a', 'not/existing')
    helper.mk_file('f1')

    self.assertItemsEqual(helper.run_wildcard_iterator(copy_links=True), [
        'a',
        'f1',
    ])

  def testFollowsDirectorySymbolicLinkToSelf(self):
    """Test invalid symlinks."""
    helper = _FileWildcardIteratorTestHelper(self.CreateTempDir())
    helper.symlink('a', '../b')
    helper.symlink('b', 'b')

    self.assertItemsEqual(helper.run_wildcard_iterator('a', copy_links=True), [
    ])

  def testMissingDir(self):
    """Tests that wildcard gets empty iterator when directory doesn't exist."""
    res = list(
        self._test_wildcard_iterator(suri('no_such_dir', '*')).IterAll(
            expand_top_level_buckets=True))
    self.assertEqual(0, len(res))

  def testExistingDirNoFileMatch(self):
    """Tests that wildcard returns empty iterator when there's no match."""
    uri = self._test_storage_uri(
        suri(self.test_dir, 'non_existent*'))
    res = list(self._test_wildcard_iterator(uri).IterAll(
        expand_top_level_buckets=True))
    self.assertEqual(0, len(res))


class _FileWildcardIteratorTestHelper(object):
  """Test helper to create some local files and check iterator results."""

  def __init__(self, tmp):
    self.tmp = tmp

  def symlink(self, path, dst):
    """Creates a symbolic link and parent folders if necessary."""
    path = os.path.join(self.tmp, path)
    if not os.path.exists(os.path.dirname(path)):
      os.makedirs(os.path.dirname(path))
    if os.path.exists(path):
      os.remove(path)
    os.symlink(dst, path)

  def mk_file(self, path):
    """Creates an empty file and parent folders if necessary.

    Note: The name has been selected to match the length of other methods
    for readability in tests.

    Args:
      path: Relative path to the file to create (related to the temp directory).
    """
    path = os.path.join(self.tmp, path)
    if not os.path.exists(os.path.dirname(path)):
      os.makedirs(os.path.dirname(path))
    open(path, 'a').close()

  def run_wildcard_iterator(self, path='', copy_links=False):
    """Run the FileWildcardIterator.

    Args:
      path: Relative path to the base directory to iterate (related to temp).
      copy_links: Set to true ask to recursively copy symlinks.

    Returns:
      All relative paths returned by FileWildcardIterator
    """
    file_wildcard_iterator = wildcard_iterator.CreateWildcardIterator(
        suri(os.path.join(self.tmp, path), '**'),
        None,
        copy_links=copy_links)
    return [
        str(u)[len(suri(self.tmp)) + 1:]
        for u in file_wildcard_iterator.IterAll()
    ]
