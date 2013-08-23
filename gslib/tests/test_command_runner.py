# Copyright 2011 Google Inc. All Rights Reserved.
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
from boto.pyami.config import Config, BotoConfigLocations
from gslib import command_runner
import gslib.tests.testcase as testcase
from gslib.util import GSUTIL_PUB_TARBALL
from gslib.util import SECONDS_PER_DAY


class TestSoftwareUpdateCheckUnitTests(
    testcase.unit_testcase.GsUtilUnitTestCase):
  """Unit tests for gsutil update check in command_runner module."""

  def setUp(self):
    super(TestSoftwareUpdateCheckUnitTests, self).setUp()

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

    # Mock out the modified time of the VERSION file.
    self.version_mod_time = 0
    self.previous_version_mod_time = command_runner.GetGsutilVersionModifiedTime
    command_runner.GetGsutilVersionModifiedTime = lambda: self.version_mod_time

    # Create a fake pub tarball that will be used to check for gsutil version.
    self.pub_bucket_uri = self.CreateBucket('pub')
    self.gsutil_tarball_uri = self.CreateObject(
        bucket_uri=self.pub_bucket_uri, object_name='gsutil.tar.gz',
        contents='foo')

    # Stores list of boto configs to set back to what they were.
    self.boto_configs = []

  def tearDown(self):
    super(TestSoftwareUpdateCheckUnitTests, self).tearDown()

    command_runner.LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE = (
        self.previous_update_file)
    command_runner.LookUpGsutilVersion = gslib.util.LookUpGsutilVersion
    command_runner.raw_input = raw_input

    command_runner.GetGsutilVersionModifiedTime = self.previous_version_mod_time

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

  def test_no_tracker_file_version_recent(self):
    """Tests when no timestamp file exists and VERSION file is recent."""
    if os.path.exists(self.timestamp_file):
      os.remove(self.timestamp_file)
    self.assertFalse(os.path.exists(self.timestamp_file))
    self.version_mod_time = time.time()
    self.assertEqual(
        False,
        self.command_runner._MaybeCheckForAndOfferSoftwareUpdate('ls', 0))

  def test_no_tracker_file_version_old(self):
    """Tests when no timestamp file exists and VERSION file is old."""
    if os.path.exists(self.timestamp_file):
      os.remove(self.timestamp_file)
    self.assertFalse(os.path.exists(self.timestamp_file))
    self.version_mod_time = 0
    self.assertEqual(
        True,
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

  def test_update_should_trigger(self):
    """Tests update should be triggered if time is up."""
    self._SetBotoConfig('GSUtil', 'software_update_check_period', '1')
    with open(self.timestamp_file, 'w') as f:
      f.write(str(int(time.time() - 2 * SECONDS_PER_DAY)))
    # Update will not trigger for package installs.
    expect = not gslib.IS_PACKAGE_INSTALL
    self.assertEqual(
        expect,
        self.command_runner._MaybeCheckForAndOfferSoftwareUpdate('ls', 0))

  def test_not_time_for_update_yet(self):
    """Tests update not triggered if not time yet."""
    self._SetBotoConfig('GSUtil', 'software_update_check_period', '3')
    with open(self.timestamp_file, 'w') as f:
      f.write(str(int(time.time() - 2 * SECONDS_PER_DAY)))
    self.assertEqual(
        False,
        self.command_runner._MaybeCheckForAndOfferSoftwareUpdate('ls', 0))

  def test_user_says_no_to_update(self):
    """Tests no update triggered if user says no at the prompt."""
    self._SetBotoConfig('GSUtil', 'software_update_check_period', '1')
    with open(self.timestamp_file, 'w') as f:
      f.write(str(int(time.time() - 2 * SECONDS_PER_DAY)))
    command_runner.raw_input = lambda p: 'n'
    self.assertEqual(
        False,
        self.command_runner._MaybeCheckForAndOfferSoftwareUpdate('ls', 0))

  def test_update_check_skipped_with_quiet_mode(self):
    """Tests that update isn't triggered when loglevel is in quiet mode."""
    self._SetBotoConfig('GSUtil', 'software_update_check_period', '1')
    with open(self.timestamp_file, 'w') as f:
      f.write(str(int(time.time() - 2 * SECONDS_PER_DAY)))

    # With regular loglevel, should return True except for package installs.
    expect = not gslib.IS_PACKAGE_INSTALL
    self.assertEqual(
      expect,
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

  def test_version_comparisons(self):
    self.assertTrue(self.command_runner._IsVersionGreater('3.37', '3.2'))
    self.assertTrue(self.command_runner._IsVersionGreater('7', '2'))
    self.assertTrue(self.command_runner._IsVersionGreater('3.32', '3.32pre'))
    self.assertTrue(self.command_runner._IsVersionGreater('3.32pre', '3.31'))
    self.assertTrue(self.command_runner._IsVersionGreater('3.4pre', '3.3pree'))

    self.assertFalse(self.command_runner._IsVersionGreater('3.2', '3.37'))
    self.assertFalse(self.command_runner._IsVersionGreater('2', '7'))
    self.assertFalse(self.command_runner._IsVersionGreater('3.32pre', '3.32'))
    self.assertFalse(self.command_runner._IsVersionGreater('3.31', '3.32pre'))
    self.assertFalse(self.command_runner._IsVersionGreater('3.3pre', '3.3pre'))

    self.assertTrue(self.command_runner._IsVersionGreater(3.37, 3.2))
    self.assertTrue(self.command_runner._IsVersionGreater(7, 2))
    self.assertFalse(self.command_runner._IsVersionGreater(3.2, 3.37))
    self.assertFalse(self.command_runner._IsVersionGreater(2, 7))

    self.assertFalse(self.command_runner._IsVersionGreater('foobar', 'baz'))
    self.assertFalse(self.command_runner._IsVersionGreater('3.32', 'baz'))

class TestSoftwareUpdateCheckIntegrationTests(
    testcase.GsUtilIntegrationTestCase):
  """Integration tests for gsutil update check in command_runner module."""


  def setUp(self):
    super(TestSoftwareUpdateCheckIntegrationTests, self).setUp()

    # Mock out the timestamp file so we can manipulate it.
    self.previous_update_file = (
        command_runner.LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE)
    self.timestamp_file = self.CreateTempFile(contents='0')
    command_runner.LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE = (
        self.timestamp_file)

    # Mock out raw_input to trigger yes prompt.
    command_runner.raw_input = lambda p: 'y'

    # Create a credential-less boto config file.
    self.orig_config = boto.config
    config_file = path=self.CreateTempFile(
        contents='[GSUtil]\nsoftware_update_check_period=1')
    boto.config = Config(path=config_file)
    # Need to copy config into boto.connection.config because it gets loaded
    # before tests run.
    boto.connection.config = boto.config
    self.command_runner = command_runner.CommandRunner(config_file)

  def tearDown(self):
    super(TestSoftwareUpdateCheckIntegrationTests, self).tearDown()

    command_runner.LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE = (
        self.previous_update_file)
    command_runner.raw_input = raw_input
    boto.config = self.orig_config
    boto.connection.config = boto.config

  def test_lookup_version_without_credentials(self):
    """
    Tests that gsutil tarball version lookup works without credentials.
    """
    self.command_runner = command_runner.CommandRunner(config_file_list=[])
    # Looking up software version shouldn't get auth failure exception.
    self.command_runner.RunNamedCommand('ls', [GSUTIL_PUB_TARBALL])
