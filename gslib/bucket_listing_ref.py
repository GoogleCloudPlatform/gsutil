# Copyright 2012 Google Inc. All Rights Reserved.
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
"""Classes for cloud/file references yielded by gsutil iterators."""

from __future__ import absolute_import


class BucketListingRefType(object):
  """Enum class for describing BucketListingRefs."""
  BUCKET = 'bucket'  # Cloud bucket
  OBJECT = 'object'  # Cloud object or filesystem file
  PREFIX = 'prefix'  # Cloud bucket subdir or filesystem directory


class BucketListingRef(object):
  """A reference to one fully expanded iterator result.

  This allows polymorphic iteration over wildcard-iterated URLs.  The
  reference contains a fully expanded URL string containing no wildcards and
  referring to exactly one entity (if a wildcard is contained, it is assumed
  this is part of the raw string and should never be treated as a wildcard).

  Each reference represents a Bucket, Object, or Prefix.  For filesystem URLs,
  Objects represent files and Prefixes represent directories.

  The root_object member contains the underlying object as it was retrieved.
  It is populated by the calling iterator, which may only request certain
  fields to reduce the number of server requests.

  For filesystem URLs, root_object is not populated.
  """

  def __init__(self, url_string, ref_type, root_object=None):
    """Instantiates a BucketListingRef from the URL string and object metadata.

    Args:
      url_string: String describing the referenced object.
      ref_type: BucketListingRefType for the underlying object.
      root_object: Underlying object metadata, if available.

    Raises:
      BucketListingRefException: If reference type is invalid.
    """
    if ref_type not in (BucketListingRefType.BUCKET,
                        BucketListingRefType.OBJECT,
                        BucketListingRefType.PREFIX):
      raise BucketListingRefException('Invalid ref_type %s' % ref_type)
    self.url_string = url_string
    self.ref_type = ref_type
    self.root_object = root_object

  def GetUrlString(self):
    return self.url_string

  def __str__(self):
    return self.url_string


class BucketListingRefException(StandardError):
  """Exception raised for invalid BucketListingRef requests."""

  def __init__(self, reason):
    StandardError.__init__(self)
    self.reason = reason

  def __repr__(self):
    return 'BucketListingRefException: %s' % self.reason

  def __str__(self):
    return 'BucketListingRefException: %s' % self.reason
