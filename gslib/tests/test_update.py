# -*- coding: utf-8 -*-
# Copyright 2013 Google Inc. All Rights Reserved.
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
"""Tests for the update command."""

from __future__ import absolute_import

import os.path
import shutil
import subprocess
import sys
import tarfile

import gslib
import gslib.tests.testcase as testcase
from gslib.tests.util import ObjectToURI as suri
from gslib.tests.util import unittest
from gslib.util import CERTIFICATE_VALIDATION_ENABLED


TESTS_DIR = os.path.abspath(os.path.dirname(__file__))
GSUTIL_DIR = os.path.join(TESTS_DIR, '..', '..')


class UpdateTest(testcase.GsUtilIntegrationTestCase):
  """Update command test suite."""

  @unittest.skipUnless(CERTIFICATE_VALIDATION_ENABLED,
                       'Test requires https certificate validation enabled.')
  def test_update(self):
    """Tests that the update command works or raises proper exceptions."""
    if os.environ.get('CLOUDSDK_WRAPPER') == '1':
      stderr = self.RunGsUtil(['update'], stdin='n',
                              return_stderr=True, expected_status=1)
      self.assertIn('update command is disabled for Cloud SDK', stderr)
      return

    if gslib.IS_PACKAGE_INSTALL:
      # The update command is not present when installed via package manager.
      stderr = self.RunGsUtil(['update'], return_stderr=True, expected_status=1)
      self.assertIn('Invalid command', stderr)
      return

    # Create two temp directories, one of which we will run 'gsutil update' in
    # to pull the changes from the other.
    tmpdir_src = self.CreateTempDir()
    tmpdir_dst = self.CreateTempDir()

    # Copy gsutil to both source and destination directories.
    gsutil_src = os.path.join(tmpdir_src, 'gsutil')
    gsutil_dst = os.path.join(tmpdir_dst, 'gsutil')
    # Path when executing from tmpdir (Windows doesn't support in-place rename)
    gsutil_relative_dst = os.path.join('gsutil', 'gsutil')

    shutil.copytree(GSUTIL_DIR, gsutil_src)
    # Copy specific files rather than all of GSUTIL_DIR so we don't pick up temp
    # working files left in top-level directory by gsutil developers (like tags,
    # .git*, etc.)
    os.makedirs(gsutil_dst)
    for comp in ('CHANGES.md', 'CHECKSUM', 'COPYING', 'gslib', 'gsutil',
                 'gsutil.py', 'MANIFEST.in', 'README.md', 'setup.py',
                 'third_party', 'VERSION'):
      if os.path.isdir(os.path.join(GSUTIL_DIR, comp)):
        func = shutil.copytree
      else:
        func = shutil.copyfile
      func(os.path.join(GSUTIL_DIR, comp), os.path.join(gsutil_dst, comp))

    # Create a fake version number in the source so we can verify it in the
    # destination.
    expected_version = '17.25'
    src_version_file = os.path.join(gsutil_src, 'VERSION')
    self.assertTrue(os.path.exists(src_version_file))
    with open(src_version_file, 'w') as f:
      f.write(expected_version)

    # Create a tarball out of the source directory and copy it to a bucket.
    src_tarball = os.path.join(tmpdir_src, 'gsutil.test.tar.gz')

    normpath = os.path.normpath
    try:
      # We monkey patch os.path.normpath here because the tarfile module
      # normalizes the ./gsutil path, but the update command expects the tar
      # file to be prefixed with . This preserves the ./gsutil path.
      os.path.normpath = lambda fname: fname
      tar = tarfile.open(src_tarball, 'w:gz')
      tar.add(gsutil_src, arcname='./gsutil')
      tar.close()
    finally:
      os.path.normpath = normpath

    prefix = [sys.executable] if sys.executable else []

    # Run with an invalid gs:// URI.
    p = subprocess.Popen(prefix + ['gsutil', 'update', 'gs://pub'],
                         cwd=gsutil_dst, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    (_, stderr) = p.communicate()
    p.stdout.close()
    p.stderr.close()
    self.assertEqual(p.returncode, 1)
    self.assertIn('update command only works with tar.gz', stderr)

    # Run with non-existent gs:// URI.
    p = subprocess.Popen(
        prefix + ['gsutil', 'update', 'gs://pub/Jdjh38)(;.tar.gz'],
        cwd=gsutil_dst, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (_, stderr) = p.communicate()
    p.stdout.close()
    p.stderr.close()
    self.assertEqual(p.returncode, 1)
    self.assertIn('NotFoundException', stderr)

    # Run with file:// URI wihout -f option.
    p = subprocess.Popen(prefix + ['gsutil', 'update', suri(src_tarball)],
                         cwd=gsutil_dst, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    (_, stderr) = p.communicate()
    p.stdout.close()
    p.stderr.close()
    self.assertEqual(p.returncode, 1)
    self.assertIn('command does not support', stderr)

    # Run with a file present that was not distributed with gsutil.
    with open(os.path.join(gsutil_dst, 'userdata.txt'), 'w') as fp:
      fp.write('important data\n')
    p = subprocess.Popen(prefix + ['gsutil', 'update', '-f', suri(src_tarball)],
                         cwd=gsutil_dst, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, stdin=subprocess.PIPE)
    (_, stderr) = p.communicate()
    p.stdout.close()
    p.stderr.close()
    # Clean up before next test, and before assertions so failure doesn't leave
    # this file around.
    os.unlink(os.path.join(gsutil_dst, 'userdata.txt'))
    self.assertEqual(p.returncode, 1)
    self.assertIn(
        'The update command cannot run with user data in the gsutil directory',
        stderr.replace(os.linesep, ' '))

    # Now do the real update, which should succeed.
    p = subprocess.Popen(prefix + [gsutil_relative_dst, 'update', '-f',
                                   suri(src_tarball)],
                         cwd=tmpdir_dst, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, stdin=subprocess.PIPE)
    (_, stderr) = p.communicate(input='y\r\n')
    p.stdout.close()
    p.stderr.close()
    self.assertEqual(p.returncode, 0, msg=(
        'Non-zero return code (%d) from gsutil update. stderr = \n%s' %
        (p.returncode, stderr)))

    # Verify that version file was updated.
    dst_version_file = os.path.join(tmpdir_dst, 'gsutil', 'VERSION')
    with open(dst_version_file, 'r') as f:
      self.assertEqual(f.read(), expected_version)


class UpdateUnitTest(testcase.GsUtilUnitTestCase):

  def test_repo_matches_manifest(self):
    """Ensure any new top-level files are present in the manifest."""
    p = subprocess.Popen(['git', 'branch'], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    p.communicate()
    if p.returncode != 0:
      unittest.skip('Test only runs from git repository.')

    manifest_lines = ['gslib', 'third_party', 'MANIFEST.in']

    gsutil_dir = os.path.dirname(os.path.realpath(sys.argv[0]))
    manifest_file = os.path.join(gsutil_dir, 'MANIFEST.in')
    if not os.path.exists(manifest_file):
      unittest.skip('Test requires manifest file present (not for Travis CI).')
      
    with open(manifest_file, 'r') as fp:
      for line in fp:
        if line.startswith('include '):
          manifest_lines.append(line.split()[-1])

    p = subprocess.Popen(['git', 'ls-tree', '--name-only', 'HEAD'],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (stdout, _) = p.communicate()
    git_top_level_files = stdout.splitlines()

    for filename in git_top_level_files:
      if filename.endswith('.pyc'):
        # Ignore compiled code.
        continue
      if filename in ('.gitmodules', '.gitignore', '.travis.yml'):
        # We explicitly drop these files when building the gsutil tarball.
        # If we add any other files to this list, the tarball script must
        # also be updated or we could break the gsutil update command.
        continue
      if filename not in manifest_lines:
        self.fail('Found file %s not present in MANIFEST.in, which would '
                  'break gsutil update.' % filename)

  
