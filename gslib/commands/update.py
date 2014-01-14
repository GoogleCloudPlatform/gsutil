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

import os
import shutil
import signal
import tarfile
import tempfile
import textwrap

import gslib
from gslib.command import Command
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.command import FILE_URIS_OK
from gslib.command import MAX_ARGS
from gslib.command import MIN_ARGS
from gslib.command import PROVIDER_URIS_OK
from gslib.command import SUPPORTED_SUB_ARGS
from gslib.command import URIS_START_ARG
from gslib.exception import CommandException
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HELP_TYPE
from gslib.help_provider import HelpType
from gslib.storage_uri_builder import StorageUriBuilder
from gslib.util import BOTO_IS_SECURE
from gslib.util import CompareVersions
from gslib.util import GSUTIL_PUB_TARBALL
from gslib.util import IS_CYGWIN
from gslib.util import IS_WINDOWS
from gslib.util import LookUpGsutilVersion
from gslib.util import LookUpGsutilVersion
from gslib.util import RELEASE_NOTES_URL


_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil update [-f] [-n] [uri]


<B>DESCRIPTION</B>
  The gsutil update command downloads the latest gsutil release, checks its
  version, and offers to let you update to it if it differs from the version
  you're currently running.

  Once you say "Y" to the prompt of whether to install the update, the gsutil
  update command locates where the running copy of gsutil is installed,
  unpacks the new version into an adjacent directory, moves the previous version
  aside, moves the new version to where the previous version was installed,
  and removes the moved-aside old version. Because of this, users are cautioned
  not to store data in the gsutil directory, since that data will be lost
  when you update gsutil. (Some users change directories into the gsutil
  directory to run the command. We advise against doing that, for this reason.)
  Note also that the gsutil update command will refuse to run if it finds user
  data in the gsutil directory.

  By default gsutil update will retrieve the new code from
  %s, but you can optionally specify a URI to use
  instead. This is primarily used for distributing pre-release versions of
  the code to a small group of early test users.

  Note: gustil periodically checks whether a more recent software update is
  available. By default this check is performed every 30 days; you can change
  (or disable) this check by editing the software_update_check_period variable
  in the .boto config file. Note also that gsutil will only check for software
  updates if stdin, stdout, and stderr are all connected to a TTY, to avoid
  interfering with cron jobs, streaming transfers, and other cases where gsutil
  input or output are redirected from/to files or pipes. Software update
  periodic checks are also disabled by the gsutil -q option (see
  'gsutil help options')


<B>OPTIONS</B>
  -f          Forces the update command to offer to let you update, even if you
              have the most current copy already. This can be useful if you have
              a corrupted local copy.

  -n          Causes update command to run without prompting [Y/n] whether to
              continue if an update is available.
""" % GSUTIL_PUB_TARBALL)


class UpdateCommand(Command):
  """Implementation of gsutil update command."""

  # Command specification (processed by parent class).
  command_spec = {
      # Name of command.
      COMMAND_NAME: 'update',
      # List of command name aliases.
      COMMAND_NAME_ALIASES: ['refresh'],
      # Min number of args required by this command.
      MIN_ARGS: 0,
      # Max number of args required by this command, or NO_MAX.
      MAX_ARGS: 1,
      # Getopt-style string specifying acceptable sub args.
      SUPPORTED_SUB_ARGS: 'fn',
      # True if file URIs acceptable for this command.
      FILE_URIS_OK: True,
      # True if provider-only URIs acceptable for this command.
      PROVIDER_URIS_OK: False,
      # Index in args of first URI arg.
      URIS_START_ARG: 0,
  }
  help_spec = {
      # Name of command or auxiliary help info for which this help applies.
      HELP_NAME: 'update',
      # List of help name aliases.
      HELP_NAME_ALIASES: ['refresh'],
      # Type of help:
      HELP_TYPE: HelpType.COMMAND_HELP,
      # One line summary of this help.
      HELP_ONE_LINE_SUMMARY: 'Update to the latest gsutil release',
      # The full help text.
      HELP_TEXT: _detailed_help_text,
  }

  def _DisallowUpdataIfDataInGsutilDir(self):
    """
    Disallows the update command from running if files other than those
    distributed with gsutil are found. This prevents users from losing data if
    they are in the habit of running gsutil from the gsutil directory, and
    leaving data in that directory.

    This will also detect someone attempting to run gsutil update from a git
    repo, since the top-level directory will contain git files and dirs (like
    .git) that are not distributed with gsutil.

    Raises:
      CommandException: if files other than those distributed with gsutil found.
    """
    # Manifest includes recursive-includes of gslib and scripts. Directly add
    # those to the list here so we will skip them in os.listdir() loop without
    # having to build deeper handling of the MANIFEST file here. Also include
    # 'third_party', which isn't present in manifest but gets added to the
    # gsutil distro by the gsutil submodule configuration; and the MANIFEST.in
    # and CHANGES.md files.
    manifest_lines = ['gslib', 'scripts', 'third_party', 'MANIFEST.in',
                      'CHANGES.md']
    
    try:
      with open(os.path.join(gslib.GSUTIL_DIR, 'MANIFEST.in'), 'r') as fp:
        for line in fp.readlines():
          if line.startswith('include '):
            manifest_lines.append(line.split()[-1])
    except IOError:
      self.logger.warn('MANIFEST.in not found in %s.\nSkipping user data '
                       'check.\n', gslib.GSUTIL_DIR)
      return

    # Look just at top-level directory. We don't try to catch data dropped into
    # subdirs (like gslib) because that would require deeper parsing of
    # MANFFEST.in, and most users who drop data into gsutil dir do so at the top
    # level directory.
    for file in os.listdir(gslib.GSUTIL_DIR):
      if file[-4:] == '.pyc':
        # Ignore compiled code.
        continue
      if file not in manifest_lines:
        raise CommandException('\n'.join(textwrap.wrap(
            'A file (%s) that is not distributed with gsutil was found in '
            'the gsutil directory. The update command cannot run with user '
            'data in the gsutil directory.' %
            os.path.join(gslib.GSUTIL_DIR, file))))

  def _ExplainIfSudoNeeded(self, tf, dirs_to_remove):
    """Explains what to do if sudo needed to update gsutil software.

    Happens if gsutil was previously installed by a different user (typically if
    someone originally installed in a shared file system location, using sudo).

    Args:
      tf: Opened TarFile.
      dirs_to_remove: List of directories to remove.

    Raises:
      CommandException: if errors encountered.
    """
    # If running under Windows or Cygwin we don't need (or have) sudo.
    if IS_CYGWIN or IS_WINDOWS:
      return

    user_id = os.getuid()
    if os.stat(gslib.GSUTIL_DIR).st_uid == user_id:
      return

    # Won't fail - this command runs after main startup code that insists on
    # having a config file.
    config_files = ' '.join(self.config_file_list)
    self._CleanUpUpdateCommand(tf, dirs_to_remove)
    raise CommandException('\n'.join(textwrap.wrap(
        'Since it was installed by a different user previously, you will need '
        'to update using the following commands. You will be prompted for your '
        'password, and the install will run as "root". If you\'re unsure what '
        'this means please ask your system administrator for help:'))
         + ('\n\tchmod 644 %s\n\tsudo env BOTO_CONFIG=%s gsutil update'
            '\n\tchmod 600 %s') % (config_files, config_files, config_files),
        informational=True)

  # This list is checked during gsutil update by doing a lowercased
  # slash-left-stripped check. For example "/Dev" would match the "dev" entry.
  unsafe_update_dirs = [
      'applications', 'auto', 'bin', 'boot', 'desktop', 'dev',
      'documents and settings', 'etc', 'export', 'home', 'kernel', 'lib',
      'lib32', 'library', 'lost+found', 'mach_kernel', 'media', 'mnt', 'net',
      'null', 'network', 'opt', 'private', 'proc', 'program files', 'python',
      'root', 'sbin', 'scripts', 'srv', 'sys', 'system', 'tmp', 'users', 'usr',
      'var', 'volumes', 'win', 'win32', 'windows', 'winnt',
  ]

  def _EnsureDirsSafeForUpdate(self, dirs):
    """Throws Exception if any of dirs is known to be unsafe for gsutil update.

    This provides a fail-safe check to ensure we don't try to overwrite
    or delete any important directories. (That shouldn't happen given the
    way we construct tmp dirs, etc., but since the gsutil update cleanup
    uses shutil.rmtree() it's prudent to add extra checks.)

    Args:
      dirs: List of directories to check.

    Raises:
      CommandException: If unsafe directory encountered.
    """
    for d in dirs:
      if not d:
        d = 'null'
      if d.lstrip(os.sep).lower() in self.unsafe_update_dirs:
        raise CommandException('EnsureDirsSafeForUpdate: encountered unsafe '
                               'directory (%s); aborting update' % d)

  def _CleanUpUpdateCommand(self, tf, dirs_to_remove):
    """Cleans up temp files etc. from running update command.

    Args:
      tf: Opened TarFile, or None if none currently open.
      dirs_to_remove: List of directories to remove.

    """
    if tf:
      tf.close()
    self._EnsureDirsSafeForUpdate(dirs_to_remove)
    for directory in dirs_to_remove:
      try:
        shutil.rmtree(directory)
      except OSError:
        # Ignore errors while attempting to remove old dirs under Windows. They
        # happen because of Windows exclusive file locking, and the update
        # actually succeeds but just leaves the old versions around in the
        # user's temp dir.
        if not IS_WINDOWS:
          raise

  # Command entry point.
  def RunCommand(self):

    if gslib.IS_PACKAGE_INSTALL:
      raise CommandException(
          'Update command is only available for gsutil installed from a '
          'tarball. If you installed gsutil via another method, use the same '
          'method to update it.')

    is_secure = BOTO_IS_SECURE
    if not is_secure[0]:
      raise CommandException(
          'Your boto configuration has %s = False. The update command\n'
          'cannot be run this way, for security reasons.' % is_secure[1])

    self._DisallowUpdataIfDataInGsutilDir()

    force_update = False
    no_prompt = False
    if self.sub_opts:
      for o, unused_a in self.sub_opts:
        if o == '-f':
          force_update = True
        if o == '-n':
          no_prompt = True

    dirs_to_remove = []
    tmp_dir = tempfile.mkdtemp()
    dirs_to_remove.append(tmp_dir)
    os.chdir(tmp_dir)

    if not no_prompt:
      self.logger.info('Checking for software update...')
    if self.args:
      update_from_uri_str = self.args[0]
      if not update_from_uri_str.endswith('.tar.gz'):
        raise CommandException(
            'The update command only works with tar.gz files.')
      for i, result in enumerate(self.WildcardIterator(update_from_uri_str)):
        if i > 0:
          raise CommandException(
              'Invalid update URI. Must name a single .tar.gz file.')
        if result.uri.names_file():
          if not force_update:
            raise CommandException(
                ('"update" command does not support "file://" URIs without the '
                 '-f option.'))
        elif not result.uri.names_object():
          raise CommandException(
              'Invalid update object URI. Must name a single .tar.gz file.')
    else:
      update_from_uri_str = GSUTIL_PUB_TARBALL

    # Try to retrieve version info from tarball metadata; failing that; download
    # the tarball and extract the VERSION file. The version lookup will fail
    # when running the update system test, because it retrieves the tarball from
    # a temp file rather than a cloud URI (files lack the version metadata).
    suri_builder = StorageUriBuilder(self.debug, self.bucket_storage_uri_class)
    tarball_version = LookUpGsutilVersion(
        self.suri_builder.StorageUri(update_from_uri_str))
    if tarball_version:
      tf = None
    else:
      tf = self._FetchAndOpenGsutilTarball(update_from_uri_str)
      tf.extractall()
      with open(os.path.join('gsutil', 'VERSION'), 'r') as ver_file:
        tarball_version = ver_file.read().strip()

    if not force_update and gslib.VERSION == tarball_version:
      self._CleanUpUpdateCommand(tf, dirs_to_remove)
      if self.args:
        raise CommandException('You already have %s installed.' %
                               update_from_uri_str, informational=True)
      else:
        raise CommandException('You already have the latest gsutil release '
                               'installed.', informational=True)

    if not no_prompt:
      (g, m) = CompareVersions(tarball_version, gslib.VERSION)
      if m:
        print('\n'.join(textwrap.wrap(
            'This command will update to the "%s" version of gsutil at %s. '
            'NOTE: This a major new version, so it is strongly recommended '
            'that you review the release note details at %s before updating to '
            'this version, especially if you use gsutil in scripts.'
            % (tarball_version, gslib.GSUTIL_DIR, RELEASE_NOTES_URL))))
      else:
        print('This command will update to the "%s" version of\ngsutil at %s'
              % (tarball_version, gslib.GSUTIL_DIR))
    self._ExplainIfSudoNeeded(tf, dirs_to_remove)

    if no_prompt:
      answer = 'y'
    else:
      answer = raw_input('Proceed? [y/N] ')
    if not answer or answer.lower()[0] != 'y':
      self._CleanUpUpdateCommand(tf, dirs_to_remove)
      raise CommandException('Not running update.', informational=True)

    if not tf:
      tf = self._FetchAndOpenGsutilTarball(update_from_uri_str)

    # Ignore keyboard interrupts during the update to reduce the chance someone
    # hitting ^C leaves gsutil in a broken state.
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    # gslib.GSUTIL_DIR lists the path where the code should end up (like
    # /usr/local/gsutil), which is one level down from the relative path in the
    # tarball (since the latter creates files in ./gsutil). So, we need to
    # extract at the parent directory level.
    gsutil_bin_parent_dir = os.path.normpath(
        os.path.join(gslib.GSUTIL_DIR, '..'))

    # Extract tarball to a temporary directory in a sibling to GSUTIL_DIR.
    old_dir = tempfile.mkdtemp(dir=gsutil_bin_parent_dir)
    new_dir = tempfile.mkdtemp(dir=gsutil_bin_parent_dir)
    dirs_to_remove.append(old_dir)
    dirs_to_remove.append(new_dir)
    self._EnsureDirsSafeForUpdate(dirs_to_remove)
    try:
      tf.extractall(path=new_dir)
    except Exception, e:
      self._CleanUpUpdateCommand(tf, dirs_to_remove)
      raise CommandException('Update failed: %s.' % e)

    # For enterprise mode (shared/central) installation, users with
    # different user/group than the installation user/group must be
    # able to run gsutil so we need to do some permissions adjustments
    # here. Since enterprise mode is not not supported for Windows
    # users, we can skip this step when running on Windows, which
    # avoids the problem that Windows has no find or xargs command.
    if not IS_WINDOWS:
      # Make all files and dirs in updated area readable by other
      # and make all directories executable by other.
      os.system('chmod -R o+r ' + new_dir)
      os.system('find ' + new_dir + ' -type d | xargs chmod o+x')

      # Make main gsutil script readable and executable by other.
      os.system('chmod o+rx ' + os.path.join(new_dir, 'gsutil'))

    # Move old installation aside and new into place.
    os.rename(gslib.GSUTIL_DIR, os.path.join(old_dir, 'old'))
    os.rename(os.path.join(new_dir, 'gsutil'), gslib.GSUTIL_DIR)
    self._CleanUpUpdateCommand(tf, dirs_to_remove)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    self.logger.info('Update complete.')
    return 0

  def _FetchAndOpenGsutilTarball(self, update_from_uri_str):
    self.command_runner.RunNamedCommand(
        'cp', [update_from_uri_str, 'file://gsutil.tar.gz'], self.headers,
        self.debug, skip_update_check=True)
    # Note: tf is closed in _CleanUpUpdateCommand.
    tf = tarfile.open('gsutil.tar.gz')
    tf.errorlevel = 1  # So fatal tarball unpack errors raise exceptions.
    return tf
