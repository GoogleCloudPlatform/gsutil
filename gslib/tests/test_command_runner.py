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

import logging
import os
import time

import boto

import gslib
from gslib import command_runner
import gslib.tests.testcase as testcase
from gslib.util import SECONDS_PER_DAY


class TestSoftwareUpdateCheck(testcase.unit_testcase.GsUtilUnitTestCase):
  """Unit tests for gsutil update check in command_runner module."""

  def setUp(self):
    super(TestSoftwareUpdateCheck, self).setUp()

    # Mock out the timestamp file so we can manipulate it.
    self.previous_update_file = (
        command_runner.LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE)
    self.timestamp_file = self.CreateTempFile()
    command_runner.LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE = (
        self.timestamp_file)

    # Mock out the gsutil version checker.
    command_runner.LookUpGsutilVersion = lambda u: float(gslib.VERSION) + 1

    # Mock out raw_input to trigger yes prompt.
    command_runner.raw_input = lambda p: 'y'

    # Create a fake pub tarball that will be used to check for gsutil version.
    self.pub_bucket_uri = self.CreateBucket('pub')
    self.gsutil_tarball_uri = self.CreateObject(
        bucket_uri=self.pub_bucket_uri, object_name='gsutil.tar.gz',
        contents='foo')

    # Stores list of boto configs to set back to what they were.
    self.boto_configs = []

  def tearDown(self):
    super(TestSoftwareUpdateCheck, self).tearDown()

    command_runner.LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE = (
        self.previous_update_file)
    command_runner.LookUpGsutilVersion = gslib.util.LookUpGsutilVersion
    command_runner.raw_input = raw_input

    self.gsutil_tarball_uri.delete_key()
    self.pub_bucket_uri.delete_bucket()

    for section, name, value in self.boto_configs:
      if value is None:
        boto.config.remove_option(section, name)
      else:
        boto.config.set(section, name, value)

  def _SetBotoConfig(self, section, name, value):
    prev_value = boto.config.get(section, name, None)
    self.boto_configs.append((section, name, prev_value))
    boto.config.set(section, name, value)

  def test_no_tracker_file(self):
    """Tests when no timestamp file exists."""
    if os.path.exists(self.timestamp_file):
      os.remove(self.timestamp_file)
    self.assertFalse(os.path.exists(self.timestamp_file))
    self.assertEqual(
        False,
        self.command_runner._MaybeCheckForAndOfferSoftwareUpdate('ls', 0))

  def test_invalid_commands(self):
    """Tests that update is not triggered for certain commands."""
    self.assertEqual(
        False,
        self.command_runner._MaybeCheckForAndOfferSoftwareUpdate('update', 0))

  def test_invalid_file_contents(self):
    """Tests no update if timestamp file has invalid value."""
    with open(self.timestamp_file, 'w') as f:
      f.write('NaN')
    self.assertEqual(
        False,
        self.command_runner._MaybeCheckForAndOfferSoftwareUpdate('ls', 0))

  def test_should_trigger(self):
    """Tests update should be triggered if time is up."""
    self._SetBotoConfig('GSUtil', 'software_update_check_period', '1')
    with open(self.timestamp_file, 'w') as f:
      f.write(str(int(time.time() - 2 * SECONDS_PER_DAY)))
    self.assertEqual(
        True,
        self.command_runner._MaybeCheckForAndOfferSoftwareUpdate('ls', 0))

  def test_not_time_yet(self):
    """Tests update not triggered if not time yet."""
    self._SetBotoConfig('GSUtil', 'software_update_check_period', '3')
    with open(self.timestamp_file, 'w') as f:
      f.write(str(int(time.time() - 2 * SECONDS_PER_DAY)))
    self.assertEqual(
        False,
        self.command_runner._MaybeCheckForAndOfferSoftwareUpdate('ls', 0))

  def test_user_says_no(self):
    """Tests no update triggered if user says no at the prompt."""
    self._SetBotoConfig('GSUtil', 'software_update_check_period', '1')
    with open(self.timestamp_file, 'w') as f:
      f.write(str(int(time.time() - 2 * SECONDS_PER_DAY)))
    command_runner.raw_input = lambda p: 'n'
    self.assertEqual(
        False,
        self.command_runner._MaybeCheckForAndOfferSoftwareUpdate('ls', 0))

  def test_quiet(self):
    """Tests that update isn't triggered when loglevel is in quiet mode."""

    self._SetBotoConfig('GSUtil', 'software_update_check_period', '1')
    with open(self.timestamp_file, 'w') as f:
      f.write(str(int(time.time() - 2 * SECONDS_PER_DAY)))

    # With regular loglevel, should return True.
    self.assertEqual(
      True,
      self.command_runner._MaybeCheckForAndOfferSoftwareUpdate('ls', 0))

    prev_loglevel = logging.getLogger().getEffectiveLevel()
    try:
      logging.getLogger().setLevel(logging.ERROR)
      # With reduced loglevel, should return False.
      self.assertEqual(
        False,
        self.command_runner._MaybeCheckForAndOfferSoftwareUpdate('ls', 0))
    finally:
      logging.getLogger().setLevel(prev_loglevel)
