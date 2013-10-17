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

from gslib.commands.cp import _AppendComponentTrackerToParallelUploadTrackerFile
from gslib.commands.cp import _GetPartitionInfo
from gslib.commands.cp import _HashFilename
from gslib.commands.cp import _ParseParallelUploadTrackerFile
from gslib.commands.cp import _CreateParallelUploadTrackerFile
from gslib.commands.cp import ObjectFromTracker
from gslib.tests.testcase.unit_testcase import GsUtilUnitTestCase
from gslib.util import CreateLock


class TestCpFuncs(GsUtilUnitTestCase):
  """Unit tests for functions in cp command."""

  def test_HashFilename(self):
    # Tests that _HashFilename function works for both string and unicode
    # filenames (without raising any Unicode encode/decode errors).
    _HashFilename('file1')
    _HashFilename(u'file1')

  def test_GetPartitionInfo(self):
    # Simplest case - threshold divides file_size.
    (num_components, component_size) = _GetPartitionInfo(300, 200, 10)
    self.assertEqual(30, num_components)
    self.assertEqual(10, component_size)

    # Threshold = 1 (mod file_size).
    (num_components, component_size) = _GetPartitionInfo(301, 200, 10)
    self.assertEqual(31, num_components)
    self.assertEqual(10, component_size)

    # Threshold = -1 (mod file_size).
    (num_components, component_size) = _GetPartitionInfo(299, 200, 10)
    self.assertEqual(30, num_components)
    self.assertEqual(10, component_size)

    # Too many components needed.
    (num_components, component_size) = _GetPartitionInfo(301, 2, 10)
    self.assertEqual(2, num_components)
    self.assertEqual(151, component_size)

    # Test num_components with huge numbers.
    (num_components, component_size) = _GetPartitionInfo((10 ** 150) + 1,
                                                         10 ** 200,
                                                         10)
    self.assertEqual((10 ** 149) + 1, num_components)
    self.assertEqual(10, component_size)

    # Test component_size with huge numbers.
    (num_components, component_size) = _GetPartitionInfo((10 ** 150) + 1,       
                                                         10,
                                                         10)
    self.assertEqual(10, num_components)
    self.assertEqual((10 ** 149) + 1, component_size)

    # Test component_size > file_size (make sure we get at least two components.
    (num_components, component_size) = _GetPartitionInfo(100, 500, 51)
    self.assertEquals(2, num_components)
    self.assertEqual(50, component_size)

  def test_ParseParallelUploadTrackerFile(self):
    tracker_file_lock = CreateLock()
    random_prefix = '123'
    objects = ['obj1', '42', 'obj2', '314159']
    contents = '\n'.join([random_prefix] + objects)
    fpath = self.CreateTempFile(file_name='foo',
                                contents=contents)
    expected_objects = [ObjectFromTracker(objects[2 * i], objects[2 * i + 1])
                       for i in range(0, len(objects) / 2)]
    (actual_prefix, actual_objects) = _ParseParallelUploadTrackerFile(
        fpath, tracker_file_lock)
    self.assertEqual(random_prefix, actual_prefix)
    self.assertEqual(expected_objects, actual_objects)

  def test_CreateParallelUploadTrackerFile(self):
    tracker_file = self.CreateTempFile(file_name='foo', contents='asdf')
    tracker_file_lock = CreateLock()
    random_prefix = '123'
    objects = ['obj1', '42', 'obj2', '314159']
    expected_contents = [random_prefix] + objects
    objects = [ObjectFromTracker(objects[2 * i], objects[2 * i + 1])
                       for i in range(0, len(objects) / 2)]
    _CreateParallelUploadTrackerFile(tracker_file, random_prefix, objects,
                                     tracker_file_lock)
    with open(tracker_file, 'rb') as f:
      lines = f.read().splitlines()
    self.assertEqual(expected_contents, lines)

  def test_AppendComponentTrackerToParallelUploadTrackerFile(self):
    tracker_file = self.CreateTempFile(file_name='foo', contents='asdf')
    tracker_file_lock = CreateLock()
    random_prefix = '123'
    objects = ['obj1', '42', 'obj2', '314159']
    expected_contents = [random_prefix] + objects
    objects = [ObjectFromTracker(objects[2 * i], objects[2 * i + 1])
                       for i in range(0, len(objects) / 2)]
    _CreateParallelUploadTrackerFile(tracker_file, random_prefix, objects,
                                     tracker_file_lock)
    
    new_object = ['obj2', '1234']
    expected_contents += new_object
    new_object = ObjectFromTracker(new_object[0], new_object[1])
    _AppendComponentTrackerToParallelUploadTrackerFile(tracker_file, new_object,
                                                       tracker_file_lock)
    with open(tracker_file, 'rb') as f:
      lines = f.read().splitlines()
    self.assertEqual(expected_contents, lines)
