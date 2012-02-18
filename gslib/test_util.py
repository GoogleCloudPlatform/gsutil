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

"""Utility class for gslib unit tests"""

import sys
import wildcard_iterator
# Put local libs at front of path so tests will run latest lib code rather
# than whatever code is found on user's PYTHONPATH.
sys.path.insert(0, '.')
sys.path.insert(0, 'boto')
import boto
from gslib.project_id import ProjectIdHandler
from tests.s3 import mock_storage_service

proj_id_handler = ProjectIdHandler()


def test_wildcard_iterator(uri_or_str, debug=0):
  """
  Convenience method for instantiating a testing instance of
  WildCardIterator, without having to specify all the params of that class
  (like bucket_storage_uri_class=mock_storage_service.MockBucketStorageUri).
  Also naming the factory method this way makes it clearer in the test code
  that WildcardIterator needs to be set up for testing.

  Args are same as for wildcard_iterator.wildcard_iterator(), except there's
  no bucket_storage_uri_class arg.

  Returns:
    WildcardIterator.IterUris(), over which caller can iterate.
  """
  return wildcard_iterator.wildcard_iterator(
      uri_or_str, proj_id_handler,
      mock_storage_service.MockBucketStorageUri, debug=debug)


def test_storage_uri(uri_str, default_scheme='file', debug=0, validate=True):
  """
  Convenience method for instantiating a testing
  instance of StorageUri, without having to specify
  bucket_storage_uri_class=mock_storage_service.MockBucketStorageUri.
  Also naming the factory method this way makes it clearer in the test
  code that StorageUri needs to be set up for testing.

  Args, Returns, and Raises are same as for boto.storage_uri(), except there's
  no bucket_storage_uri_class arg.
  """
  return boto.storage_uri(uri_str, default_scheme, debug, validate,
                          mock_storage_service.MockBucketStorageUri)
