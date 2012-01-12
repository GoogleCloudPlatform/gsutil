# Copyright 2011 Google Inc.
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
import platform
import shutil
import signal
import tarfile
import tempfile

from gslib.command import Command
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.command import CONFIG_REQUIRED
from gslib.command import FILE_URIS_OK
from gslib.command import MAX_ARGS
from gslib.command import MIN_ARGS
from gslib.command import PROVIDER_URIS_OK
from gslib.command import SUPPORTED_SUB_ARGS
from gslib.command import URIS_START_ARG
from gslib.exception import CommandException

class UpdateCommand(Command):
  """Implementation of gsutil update command."""

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'update',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : [],
    # Min number of args required by this command.
    MIN_ARGS : 0,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : 0,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : 'f',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : False,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 0,
    # True if must configure gsutil before running command.
    CONFIG_REQUIRED : True,
  }

  def _ExplainIfSudoNeeded(self, tf, dirs_to_remove):
    """Explains what to do if sudo needed to update gsutil software.

    Happens if gsutil was previously installed by a different user (typically if
    someone originally installed in a shared file system location, using sudo).

    Args:
      tf: opened TarFile.
      dirs_to_remove: list of directories to remove.

    Raises:
      CommandException: if errors encountered.
    """
    system = platform.system()
    # If running under Windows we don't need (or have) sudo.
    if system.lower().startswith('windows'):
      return

    user_id = os.getuid()
    if (os.stat(self.gsutil_bin_dir).st_uid == user_id and
        os.stat(self.boto_lib_dir).st_uid == user_id):
      return

    # Won't fail - this command runs after main startup code that insists on
    # having a config file.
    config_files = ' '.join(self.config_file_list)
    self._CleanUpUpdateCommand(tf, dirs_to_remove)
    raise CommandException(
        ('Since it was installed by a different user previously, you will need '
         'to update using the following commands.\nYou will be prompted for '
         'your password, and the install will run as "root". If you\'re unsure '
         'what this means please ask your system administrator for help:'
         '\n\tchmod 644 %s\n\tsudo env BOTO_CONFIG=%s gsutil update'
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
    use shutil.rmtree() it's prudent to add extra checks.)

    Args:
      dirs: list of directories to check.

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
      tf: opened TarFile.
      dirs_to_remove: list of directories to remove.

    """
    tf.close()
    self._EnsureDirsSafeForUpdate(dirs_to_remove)
    for directory in dirs_to_remove:
      shutil.rmtree(directory)

  # Command entry point.
  def RunCommand(self):
    installed_version_string = self.LoadVersionString()

    dirs_to_remove = []
    # Retrieve gsutil tarball and check if it's newer than installed code.
    # TODO: Store this version info as metadata on the tarball object and
    # change this command's implementation to check that metadata instead of
    # downloading the tarball to check the version info.
    tmp_dir = tempfile.mkdtemp()
    dirs_to_remove.append(tmp_dir)
    os.chdir(tmp_dir)
    print 'Checking for software update...'
    self.command_runner.RunNamedCommand('cp', ['gs://pub/gsutil.tar.gz',
                                          'file://gsutil.tar.gz'],
                                           self.headers, self.debug)
    # Note: tf is closed in _CleanUpUpdateCommand.
    tf = tarfile.open('gsutil.tar.gz')
    tf.errorlevel = 1  # So fatal tarball unpack errors raise exceptions.
    tf.extract('./gsutil/VERSION')

    ver_file = open('gsutil/VERSION', 'r')
    try:
      latest_version_string = ver_file.read().rstrip('\n')
    finally:
      ver_file.close()

    # The force_update option works around a problem with the way the
    # first gsutil "update" command exploded the gsutil and boto directories,
    # which didn't correctly install boto. People running that older code can
    # run "gsutil update" (to update to the newer gsutil update code) followed
    # by "gsutil update -f" (which will then update the boto code, even though
    # the VERSION is already the latest version).
    force_update = False
    if self.sub_opts:
      for o, unused_a in self.sub_opts:
        if o == '-f':
          force_update = True
    if not force_update and installed_version_string == latest_version_string:
      self._CleanUpUpdateCommand(tf, dirs_to_remove)
      raise CommandException('You have the latest version of gsutil installed.',
                             informational=True)

    print(('This command will update to the "%s" version of\ngsutil at %s') %
          (latest_version_string, self.gsutil_bin_dir))
    self._ExplainIfSudoNeeded(tf, dirs_to_remove)

    answer = raw_input('Proceed (Note: experimental command)? [y/N] ')
    if not answer or answer.lower()[0] != 'y':
      self._CleanUpUpdateCommand(tf, dirs_to_remove)
      raise CommandException('Not running update.', informational=True)

    # Ignore keyboard interrupts during the update to reduce the chance someone
    # hitting ^C leaves gsutil in a broken state.
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    # self.gsutil_bin_dir lists the path where the code should end up (like
    # /usr/local/gsutil), which is one level down from the relative path in the
    # tarball (since the latter creates files in ./gsutil). So, we need to
    # extract at the parent directory level.
    gsutil_bin_parent_dir = os.path.dirname(self.gsutil_bin_dir)

    # Extract tarball to a temporary directory in a sibling to gsutil_bin_dir.
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
    system = platform.system()
    if not system.lower().startswith('windows'):
      # Make all files and dirs in updated area readable by other
      # and make all directories executable by other. These steps
      os.system('chmod -R o+r ' + new_dir)
      os.system('find ' + new_dir + ' -type d | xargs chmod o+x')

      # Make main gsutil script readable and executable by other.
      os.system('chmod o+rx ' + os.path.join(new_dir, 'gsutil'))

    # Move old installation aside and new into place.
    os.rename(self.gsutil_bin_dir, old_dir + os.sep + 'old')
    os.rename(new_dir + os.sep + 'gsutil', self.gsutil_bin_dir)
    self._CleanUpUpdateCommand(tf, dirs_to_remove)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    print 'Update complete.'
