# -*- coding: utf-8 -*-
# Copyright 2026 Google LLC. All Rights Reserved.
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
"""Unit tests for boto_translation.py."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import binascii
import io
import json
import logging
import pickle

from boto.gs.bucket import Bucket as GSBucket
from boto.gs.key import Key as GSKey
from boto.s3.bucket import Bucket as S3Bucket
from boto.s3.key import Key as S3Key
from boto.storage_uri import BucketStorageUri
import six
from six import MovedModule
from six import add_move

from gslib.boto_translation import BotoTranslation
from gslib.cloud_api import ArgumentException
from gslib.tests import testcase
from gslib.tests.util import GSMockBucketStorageUri
from gslib.utils.cloud_api_helper import GetDownloadSerializationData

add_move(MovedModule('mock', 'mock', 'unittest.mock'))
from six.moves import mock  # pylint: disable=g-import-not-at-top

_REDUCE_CALLED = []


def _RecordReduceCall():
  _REDUCE_CALLED.append(True)
  return 'unexpected'


class _SentinelPayload(object):

  def __reduce__(self):
    return (_RecordReduceCall, ())


class TestBotoTranslationSerialization(testcase.GsUtilUnitTestCase):
  """Tests JSON serialization of XML boto keys in BotoTranslation."""

  def _CreateTranslator(self, provider='gs', uri_class=GSMockBucketStorageUri):
    return BotoTranslation(
        uri_class,
        logging.getLogger('test_boto_translation'),
        mock.MagicMock(),
        provider=provider,
    )

  def test_gs_key_roundtrip_without_head_call(self):
    translator = self._CreateTranslator('gs', BucketStorageUri)
    gs_bucket = GSBucket(connection=mock.MagicMock(debug=0), name='gs-bucket')
    src_key = GSKey(bucket=gs_bucket, name='dir/obj.txt', generation='1234567')
    src_key.size = 42

    obj_metadata = translator._BotoKeyToObject(
        src_key, fields=['bucket', 'name', 'size', 'generation', 'mediaLink'])
    serialization_data = GetDownloadSerializationData(obj_metadata)

    mock_uri = mock.MagicMock()
    mock_uri.get_bucket.return_value = gs_bucket
    captured = []
    with mock.patch.object(translator, '_StorageUriForBucket',
                           return_value=mock_uri), \
        mock.patch.object(gs_bucket, 'get_key') as mock_get_key, \
        mock.patch.object(translator, '_PerformSimpleDownload',
                          side_effect=lambda s, key, **kw: captured.append(key)):
      translator.GetObjectMedia('gs-bucket', 'dir/obj.txt', io.BytesIO(),
                                serialization_data=serialization_data)

    mock_uri.get_bucket.assert_called_once_with(validate=False)
    mock_get_key.assert_not_called()
    self.assertEqual(captured[0].bucket.name, 'gs-bucket')
    self.assertEqual(captured[0].name, 'dir/obj.txt')
    self.assertEqual(captured[0].size, 42)
    self.assertEqual(captured[0].generation, '1234567')

  def test_s3_key_roundtrip_preserves_version_id(self):
    translator = self._CreateTranslator('s3', BucketStorageUri)
    s3_bucket = S3Bucket(connection=mock.MagicMock(debug=0), name='s3-bucket')
    src_key = S3Key(bucket=s3_bucket, name='s3-obj.bin')
    src_key.size = 99
    src_key.version_id = 'v-abc-999'

    obj_metadata = translator._BotoKeyToObject(
        src_key, fields=['bucket', 'name', 'size', 'mediaLink'])
    serialization_data = GetDownloadSerializationData(obj_metadata)

    mock_uri = mock.MagicMock()
    mock_uri.get_bucket.return_value = s3_bucket
    captured = []
    with mock.patch.object(translator, '_StorageUriForBucket',
                           return_value=mock_uri), \
        mock.patch.object(s3_bucket, 'get_key') as mock_get_key, \
        mock.patch.object(translator, '_PerformSimpleDownload',
                          side_effect=lambda s, key, **kw: captured.append(key)):
      translator.GetObjectMedia('s3-bucket', 's3-obj.bin', io.BytesIO(),
                                serialization_data=serialization_data)

    mock_get_key.assert_not_called()
    self.assertEqual(captured[0].size, 99)
    self.assertEqual(captured[0].version_id, 'v-abc-999')

  def test_mock_storage_uri_roundtrip_with_user_project(self):
    bucket_uri = self.CreateBucket()
    self.CreateObject(bucket_uri=bucket_uri,
                      object_name='sample.txt',
                      contents=b'hello mock world')
    translator = self._CreateTranslator('gs', GSMockBucketStorageUri)
    obj_metadata = translator.GetObjectMetadata(
        bucket_uri.bucket_name, 'sample.txt',
        fields=['bucket', 'name', 'size', 'mediaLink'])
    serialization_data = GetDownloadSerializationData(
        obj_metadata, user_project='billing-proj')

    out_stream = io.BytesIO()
    translator.GetObjectMedia(bucket_uri.bucket_name, 'sample.txt', out_stream,
                              serialization_data=serialization_data)
    self.assertEqual(out_stream.getvalue(), b'hello mock world')

  def test_pickled_and_invalid_serialization_data_rejected(self):
    del _REDUCE_CALLED[:]
    translator = self._CreateTranslator()
    legacy_blob = binascii.b2a_base64(
        pickle.dumps(_SentinelPayload(), pickle.HIGHEST_PROTOCOL))
    if six.PY3:
      legacy_blob = legacy_blob.decode('ascii')

    bad_payloads = [
        json.dumps({'url': legacy_blob, 'total_size': 0}),
        'not-json',
        json.dumps({'url': '[]', 'total_size': 0}),
        json.dumps({'url': json.dumps({'bucket': '', 'name': 'obj'})}),
    ]
    for payload in bad_payloads:
      with self.assertRaises(ArgumentException):
        translator.GetObjectMedia('b', 'obj', io.BytesIO(),
                                  serialization_data=payload)
    self.assertEqual(_REDUCE_CALLED, [])
