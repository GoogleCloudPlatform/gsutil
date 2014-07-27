# Copyright 2011 Google Inc. All Rights Reserved.
# coding=utf8
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
"""Unit and integration tests for gsutil command_runner module."""

from __future__ import absolute_import

import logging
import os
import time

import gslib
from gslib import command_runner
from gslib.command_runner import HandleArgCoding
from gslib.exception import CommandException
import gslib.tests.testcase as testcase
import gslib.tests.util as util
from gslib.tests.util import SetBotoConfigFileForTest
from gslib.tests.util import SetBotoConfigForTest
from gslib.tests.util import unittest
from gslib.util import GSUTIL_PUB_TARBALL
from gslib.util import SECONDS_PER_DAY


class TestCommandRunnerUnitTests(
    testcase.unit_testcase.GsUtilUnitTestCase):
  """Unit tests for gsutil update check in command_runner module."""

  # TODO: Many tests in this file increment the version number, and output
  # a message to stderr claiming this version is available.  When mixed with
  # some failures in the tests, this can be misleading, particularly when
  # a new version number is under development but not yet released.

  def setUp(self):
    """Sets up the command runner mock objects."""
    super(TestCommandRunnerUnitTests, self).setUp()

    # Mock out the timestamp file so we can manipulate it.
    self.previous_update_file = (
        command_runner.LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE)
    self.timestamp_file = self.CreateTempFile()
    command_runner.LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE = (
        self.timestamp_file)

    # Mock out the gsutil version checker.
    base_version = unicode(gslib.VERSION)
    while not base_version.isnumeric():
      if not base_version:
        raise CommandException(
            'Version number (%s) is not numeric.' % gslib.VERSION)
      base_version = base_version[:-1]
    command_runner.LookUpGsutilVersion = lambda u, v: float(base_version) + 1

    # Mock out raw_input to trigger yes prompt.
    command_runner.raw_input = lambda p: 'y'

    # Mock out TTY check to pretend we're on a TTY even if we're not.
    self.running_interactively = True
    command_runner.IsRunningInteractively = lambda: self.running_interactively

    # Mock out the modified time of the VERSION file.
    self.version_mod_time = 0
    self.previous_version_mod_time = command_runner.GetGsutilVersionModifiedTime
    command_runner.GetGsutilVersionModifiedTime = lambda: self.version_mod_time

    # Create a fake pub tarball that will be used to check for gsutil version.
    self.pub_bucket_uri = self.CreateBucket('pub')
    self.gsutil_tarball_uri = self.CreateObject(
        bucket_uri=self.pub_bucket_uri, object_name='gsutil.tar.gz',
        contents='foo')

  def tearDown(self):
    """Tears down the command runner mock objects."""
    super(TestCommandRunnerUnitTests, self).tearDown()

    command_runner.LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE = (
        self.previous_update_file)
    command_runner.LookUpGsutilVersion = gslib.util.LookUpGsutilVersion
    command_runner.raw_input = raw_input

    command_runner.GetGsutilVersionModifiedTime = self.previous_version_mod_time

    command_runner.IsRunningInteractively = gslib.util.IsRunningInteractively

    self.gsutil_tarball_uri.delete_key()
    self.pub_bucket_uri.delete_bucket()

  @unittest.skipUnless(not util.HAS_GS_HOST, 'gs_host is defined in config')
  def test_not_interactive(self):
    """Tests that update is not triggered if not running interactively."""
    with SetBotoConfigForTest([
        ('GSUtil', 'software_update_check_period', '1')]):
      with open(self.timestamp_file, 'w') as f:
        f.write(str(int(time.time() - 2 * SECONDS_PER_DAY)))
      self.running_interactively = False
      self.assertEqual(
          False,
          self.command_runner.MaybeCheckForAndOfferSoftwareUpdate('ls', 0))

  @unittest.skipUnless(not util.HAS_GS_HOST, 'gs_host is defined in config')
  def test_no_tracker_file_version_recent(self):
    """Tests when no timestamp file exists and VERSION file is recent."""
    if os.path.exists(self.timestamp_file):
      os.remove(self.timestamp_file)
    self.assertFalse(os.path.exists(self.timestamp_file))
    self.version_mod_time = time.time()
    self.assertEqual(
        False,
        self.command_runner.MaybeCheckForAndOfferSoftwareUpdate('ls', 0))

  @unittest.skipUnless(not util.HAS_GS_HOST, 'gs_host is defined in config')
  def test_no_tracker_file_version_old(self):
    """Tests when no timestamp file exists and VERSION file is old."""
    if os.path.exists(self.timestamp_file):
      os.remove(self.timestamp_file)
    self.assertFalse(os.path.exists(self.timestamp_file))
    self.version_mod_time = 0
    expect = not gslib.IS_PACKAGE_INSTALL
    self.assertEqual(
        expect,
        self.command_runner.MaybeCheckForAndOfferSoftwareUpdate('ls', 0))

  @unittest.skipUnless(not util.HAS_GS_HOST, 'gs_host is defined in config')
  def test_invalid_commands(self):
    """Tests that update is not triggered for certain commands."""
    self.assertEqual(
        False,
        self.command_runner.MaybeCheckForAndOfferSoftwareUpdate('update', 0))

  @unittest.skipUnless(not util.HAS_GS_HOST, 'gs_host is defined in config')
  def test_invalid_file_contents(self):
    """Tests no update if timestamp file has invalid value."""
    with open(self.timestamp_file, 'w') as f:
      f.write('NaN')
    self.assertEqual(
        False,
        self.command_runner.MaybeCheckForAndOfferSoftwareUpdate('ls', 0))

  @unittest.skipUnless(not util.HAS_GS_HOST, 'gs_host is defined in config')
  def test_update_should_trigger(self):
    """Tests update should be triggered if time is up."""
    with SetBotoConfigForTest([
        ('GSUtil', 'software_update_check_period', '1')]):
      with open(self.timestamp_file, 'w') as f:
        f.write(str(int(time.time() - 2 * SECONDS_PER_DAY)))
      # Update will not trigger for package installs.
      expect = not gslib.IS_PACKAGE_INSTALL
      self.assertEqual(
          expect,
          self.command_runner.MaybeCheckForAndOfferSoftwareUpdate('ls', 0))

  @unittest.skipUnless(not util.HAS_GS_HOST, 'gs_host is defined in config')
  def test_not_time_for_update_yet(self):
    """Tests update not triggered if not time yet."""
    with SetBotoConfigForTest([
        ('GSUtil', 'software_update_check_period', '3')]):
      with open(self.timestamp_file, 'w') as f:
        f.write(str(int(time.time() - 2 * SECONDS_PER_DAY)))
      self.assertEqual(
          False,
          self.command_runner.MaybeCheckForAndOfferSoftwareUpdate('ls', 0))

  def test_user_says_no_to_update(self):
    """Tests no update triggered if user says no at the prompt."""
    with SetBotoConfigForTest([
        ('GSUtil', 'software_update_check_period', '1')]):
      with open(self.timestamp_file, 'w') as f:
        f.write(str(int(time.time() - 2 * SECONDS_PER_DAY)))
      command_runner.raw_input = lambda p: 'n'
      self.assertEqual(
          False,
          self.command_runner.MaybeCheckForAndOfferSoftwareUpdate('ls', 0))

  @unittest.skipUnless(not util.HAS_GS_HOST, 'gs_host is defined in config')
  def test_update_check_skipped_with_quiet_mode(self):
    """Tests that update isn't triggered when loglevel is in quiet mode."""
    with SetBotoConfigForTest([
        ('GSUtil', 'software_update_check_period', '1')]):
      with open(self.timestamp_file, 'w') as f:
        f.write(str(int(time.time() - 2 * SECONDS_PER_DAY)))

      # With regular loglevel, should return True except for package installs.
      expect = not gslib.IS_PACKAGE_INSTALL
      self.assertEqual(
          expect,
          self.command_runner.MaybeCheckForAndOfferSoftwareUpdate('ls', 0))

      prev_loglevel = logging.getLogger().getEffectiveLevel()
      try:
        logging.getLogger().setLevel(logging.ERROR)
        # With reduced loglevel, should return False.
        self.assertEqual(
            False,
            self.command_runner.MaybeCheckForAndOfferSoftwareUpdate('ls', 0))
      finally:
        logging.getLogger().setLevel(prev_loglevel)

  # pylint: disable=invalid-encoded-data
  def test_valid_arg_coding(self):
    """Tests that gsutil encodes valid args correctly."""
    # Args other than -h and -p should be utf-8 decoded.
    args = HandleArgCoding(['ls', '-l'])
    self.assertIs(type(args[0]), unicode)
    self.assertIs(type(args[1]), unicode)

    # -p and -h args other than x-goog-meta should not be decoded.
    args = HandleArgCoding(['ls', '-p', 'abc:def', 'gs://bucket'])
    self.assertIs(type(args[0]), unicode)
    self.assertIs(type(args[1]), unicode)
    self.assertIsNot(type(args[2]), unicode)
    self.assertIs(type(args[3]), unicode)

    args = HandleArgCoding(['gsutil', '-h', 'content-type:text/plain', 'cp',
                            'a', 'gs://bucket'])
    self.assertIs(type(args[0]), unicode)
    self.assertIs(type(args[1]), unicode)
    self.assertIsNot(type(args[2]), unicode)
    self.assertIs(type(args[3]), unicode)
    self.assertIs(type(args[4]), unicode)
    self.assertIs(type(args[5]), unicode)

    # -h x-goog-meta args should be decoded.
    args = HandleArgCoding(['gsutil', '-h', 'x-goog-meta-abc', '1234'])
    self.assertIs(type(args[0]), unicode)
    self.assertIs(type(args[1]), unicode)
    self.assertIs(type(args[2]), unicode)
    self.assertIs(type(args[3]), unicode)

    # -p and -h args with non-ASCII content should raise CommandException.
    try:
      HandleArgCoding(['ls', '-p', '碼'])
      # Ensure exception is raised.
      self.assertTrue(False)
    except CommandException as e:
      self.assertIn('Invalid non-ASCII header', e.reason)
    try:
      HandleArgCoding(['-h', '碼', 'ls'])
      # Ensure exception is raised.
      self.assertTrue(False)
    except CommandException as e:
      self.assertIn('Invalid non-ASCII header', e.reason)


class TestCommandRunnerIntegrationTests(
    testcase.GsUtilIntegrationTestCase):
  """Integration tests for gsutil update check in command_runner module."""

  def setUp(self):
    """Sets up the command runner mock objects."""
    super(TestCommandRunnerIntegrationTests, self).setUp()

    # Mock out the timestamp file so we can manipulate it.
    self.previous_update_file = (
        command_runner.LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE)
    self.timestamp_file = self.CreateTempFile(contents='0')
    command_runner.LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE = (
        self.timestamp_file)

    # Mock out raw_input to trigger yes prompt.
    command_runner.raw_input = lambda p: 'y'

  def tearDown(self):
    """Tears down the command runner mock objects."""
    super(TestCommandRunnerIntegrationTests, self).tearDown()
    command_runner.LAST_CHECKED_FOR_GSUTIL_UPDATE_TIMESTAMP_FILE = (
        self.previous_update_file)
    command_runner.raw_input = raw_input

  @unittest.skipUnless(not util.HAS_GS_HOST, 'gs_host is defined in config')
  def test_lookup_version_without_credentials(self):
    """Tests that gsutil tarball version lookup works without credentials."""
    with SetBotoConfigFileForTest(self.CreateTempFile(
        contents='[GSUtil]\nsoftware_update_check_period=1')):
      self.command_runner = command_runner.CommandRunner()
      # Looking up software version shouldn't get auth failure exception.
      self.command_runner.RunNamedCommand('ls', [GSUTIL_PUB_TARBALL])
