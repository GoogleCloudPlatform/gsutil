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

import gslib.tests.testcase as testcase

from gslib.commands.compose import MAX_COMPOSE_ARITY
from gslib.tests.util import HAS_S3_CREDS
from gslib.tests.util import ObjectToURI as suri
from gslib.tests.util import unittest


class TestCompose(testcase.GsUtilIntegrationTestCase):
  """Integration tests for compose command."""

  def check_n_ary_compose(self, num_components):
    num_components = 2
    bucket_uri = self.CreateBucket()

    data_list = ['data-%d,' % i for i in xrange(num_components)]
    components = [self.CreateObject(bucket_uri=bucket_uri, contents=data).uri
                  for data in data_list]

    composite = bucket_uri.clone_replace_name(self.MakeTempName('obj'))

    self.RunGsUtil(['compose'] + components + [composite.uri])
    self.assertEqual(composite.get_contents_as_string(), ''.join(data_list))

  def test_compose_too_many_fails(self):
    components = ['gs://b/component-obj'] * (MAX_COMPOSE_ARITY + 1)
    stderr = self.RunGsUtil(['compose'] + components + ['gs://b/composite-obj'],
                            expected_status=1, return_stderr=True)
    self.assertEquals(
        'CommandException: Wrong number of arguments for "compose" command.\n',
        stderr)

  def test_compose_too_few_fails(self):
    stderr = self.RunGsUtil(
        ['compose', 'gs://b/component-obj', 'gs://b/composite-obj'],
        expected_status=1, return_stderr=True)
    self.assertEquals(
        'CommandException: "compose" requires at least 2 component objects.\n',
        stderr)

  def test_compose_between_buckets_fails(self):
    target = 'gs://b/composite-obj'
    offending_obj = 'gs://alt-b/obj2'
    components = ['gs://b/obj1', offending_obj]
    stderr = self.RunGsUtil(['compose'] + components + [target],
                            expected_status=1, return_stderr=True)
    expected_msg = (
        'Composing gs://b/composite-obj from 2 component objects.\n'
        'BotoClientError: GCS does not support inter-bucket composing.\n')
    self.assertEquals(expected_msg, stderr)

  @unittest.skipUnless(HAS_S3_CREDS, 'Test requires S3 credentials.')
  def test_compose_non_gcs_target(self):
    stderr = self.RunGsUtil(['compose', 'gs://b/o1', 'gs://b/o2', 's3://b/o3'],
                            expected_status=1, return_stderr=True)
    expected_msg = ('CommandException: "compose" called on URI with '
                    'unsupported provider (%s).\n' % 's3://b/o3')
    self.assertEquals(expected_msg, stderr)

  @unittest.skipUnless(HAS_S3_CREDS, 'Test requires S3 credentials.')
  def test_compose_non_gcs_component(self):
    stderr = self.RunGsUtil(['compose', 'gs://b/o1', 's3://b/o2', 'gs://b/o3'],
                            expected_status=1, return_stderr=True)
    expected_msg = ('CommandException: "compose" called on URI with '
                    'unsupported provider (%s).\n' % 's3://b/o2')
    self.assertEquals(expected_msg, stderr)

  def test_versioned_target_disallowed(self):
    stderr = self.RunGsUtil(
        ['compose', 'gs://b/o1', 'gs://b/o2', 'gs://b/o3#1234'],
        expected_status=1, return_stderr=True)
    expected_msg = ('CommandException: A version-specific URI\n(%s)\n'
                    'cannot be the destination for gsutil compose - abort.\n'
                    % 'gs://b/o3#1234')
    self.assertEquals(expected_msg, stderr)


  def test_simple_compose(self):
    self.check_n_ary_compose(2)

  def test_maximal_compose(self):
    self.check_n_ary_compose(MAX_COMPOSE_ARITY)

  def test_compose_with_wildcard(self):
    bucket_uri = self.CreateBucket()

    component1 = self.CreateObject(
        bucket_uri=bucket_uri, contents='hello ', object_name='component1')
    component2 = self.CreateObject(
        bucket_uri=bucket_uri, contents='world!', object_name='component2')

    composite = bucket_uri.clone_replace_name(self.MakeTempName('obj'))

    self.RunGsUtil(['compose', component1.uri, component2.uri, composite.uri])
    self.assertEqual(composite.get_contents_as_string(), 'hello world!')
