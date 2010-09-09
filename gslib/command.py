#!/usr/bin/env python
# coding=utf8
# Copyright 2010 Google Inc.
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

"""Implementation of gsutil commands."""

import gzip
import mimetypes
import os
import platform
import shutil
import signal
import sys
import tarfile
import tempfile
import xml.dom.minidom
import xml.sax.xmlreader
import boto

from boto import handler
from boto.pyami.config import BotoConfigLocations
from exception import CommandException
from wildcard_iterator import ContainsWildcard
from wildcard_iterator import ResultType
from wildcard_iterator import wildcard_iterator
from wildcard_iterator import WildcardException


# Enum class for specifying listing style.
class ListingStyle(object):
  SHORT = 'SHORT'
  LONG = 'LONG'
  LONG_LONG = 'LONG_LONG'


# Binary exponentiation strings.
EXP_STRINGS = [
    (0, 'B'),
    (10, 'KB'),
    (20, 'MB'),
    (30, 'GB'),
    (40, 'TB'),
    (50, 'PB'),
]


def MakeHumanReadable(num):
  """Generates human readable string for a number.

  Args:
    num: the number

  Returns:
    A string form of the number using size abbreviations (KB, MB, etc.)
  """
  i = 0
  while i+1 < len(EXP_STRINGS) and num >= (2 ** EXP_STRINGS[i+1][0]):
    i += 1
  rounded_val = round(num / 2 ** EXP_STRINGS[i][0], 2)
  return '%s %s' % (rounded_val, EXP_STRINGS[i][1])


def StorageUri(uri_str, debug=False, validate=True):
  """Helper to instantiate boto.StorageUri with gsutil default flag values.

  Args:
    uri_str: StorageUri naming bucket + optional object.
    debug: Whether to enable debugging on StorageUri method calls.
    validate: Whether to check for bucket name validity.

  Returns:
    boto.StorageUri for given uri_str.

  Raises:
    InvalidUriError: if uri_str not valid.
  """
  uri = boto.storage_uri(uri_str, 'file', debug=debug, validate=validate)
  return uri


def UriStrFor(iterated_uri, obj):
  """Constructs a StorageUri string for the given iterated_uri and object.

  For example if we were iterating gs://*, obj could be an object in one
  of the user's buckets enumerated by the ls command.

  Args:
    iterated_uri: base StorageUri being iterated.
    obj: object being listed.

  Returns:
    URI string.
  """
  return '%s://%s/%s' % (iterated_uri.scheme, obj.bucket.name, obj.name)


class Command(object):
  """Class that contains all gsutil command code."""

  def __init__(self, gsutil_bin_dir, boto_lib_dir, usage_string,
               config_file_list):
    """Instantiates Command class.

    Args:
      gsutil_bin_dir: bin dir from which gsutil is running.
      boto_lib_dir: lib dir where boto runs.
      usage_string: usage string to print when user makes command error.
      config_file_list: config file list returned by GetBotoConfigFileList().
    """
    self.gsutil_bin_dir = gsutil_bin_dir
    self.usage_string = usage_string
    self.boto_lib_dir = boto_lib_dir
    self.config_file_list = config_file_list

  def OutputUsageAndExit(self):
    sys.stderr.write(self.usage_string)
    sys.exit(0)

  def InsistUriNamesContainer(self, command, uri):
    """Prints error and exists if URI doesn't name a directory or bucket.

    Args:
      command: command being run
      uri: StorageUri to check

    Raises:
      CommandException if any errors encountered.
    """
    if uri.names_singleton():
      raise CommandException('Destination StorageUri must name a bucket or '
                             'directory for the\nmultiple source form of the '
                             '"%s" command.' % command)

  def CatCommand(self, args, sub_opts=None, headers=None, debug=False):
    """Implementation of cat command.

    Args:
      args: command-line arguments
      sub_opts: command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: flag indicating whether to include debug output

    Raises:
      CommandException if any errors encountered.
    """
    show_header = False
    if sub_opts:
      for o, unused_a in sub_opts:
        if o == '-h':
          show_header = True

    printed_one = False
    for uri_str in args:
      for uri in wildcard_iterator(uri_str, ResultType.URIS, headers=headers,
                                   debug=debug):
        if not uri.object_name:
          raise CommandException('"cat" command must specify objects.')
        if show_header:
          if printed_one:
            print
          print '==> %s <==' % uri.__str__()
          printed_one = True
        tmp_file = tempfile.TemporaryFile()
        key = uri.get_key(False, headers)
        key.get_file(tmp_file, headers)
        tmp_file.seek(0)
        while True:
          # Use 8k buffer size.
          data = tmp_file.read(8192)
          if not data:
            break
          sys.stdout.write(data)
        tmp_file.close()

  def SetAclCommand(self, args, unused_sub_opts=None, headers=None,
                    debug=False):
    """Implementation of setacl command.

    Args:
      args: command-line arguments
      unused_sub_opts: command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: flag indicating whether to include debug output

    Raises:
      CommandException if any errors encountered.
    """
    acl_arg = args[0]
    uri_args = args[1:]
    provider = None
    first_uri = None
    # Do a first pass over all matched objects to disallow multi-provider
    # setacl requests, because there are differences in the ACL models.
    for uri_str in uri_args:
      for uri in wildcard_iterator(uri_str, ResultType.URIS, headers=headers,
                                   debug=debug):
        if not provider:
          provider = uri.scheme
        elif uri.scheme != provider:
          raise CommandException('"setacl" command spanning providers not '
                                 'allowed.')
        if not first_uri:
          first_uri = uri

    # Get ACL object from connection for the first URI, for interpreting the
    # ACL. This won't fail because the main startup code insists on 1 arg
    # for this command.
    storage_uri = first_uri
    acl_class = storage_uri.acl_class()
    canned_acls = storage_uri.canned_acls()

    # Determine whether acl_arg names a file containing XML ACL text vs. the
    # string name of a canned ACL.
    if os.path.isfile(acl_arg):
      acl_file = open(acl_arg, 'r')
      acl_txt = acl_file.read()
      acl_file.close()
      acl_obj = acl_class()
      h = handler.XmlHandler(acl_obj, storage_uri.get_bucket())
      try:
        xml.sax.parseString(acl_txt, h)
      except xml.sax._exceptions.SAXParseException, e:
        raise CommandException('Requested ACL is invalid: %s at line %s, '
                               'column %s' % (e.getMessage(), e.getLineNumber(),
                                              e.getColumnNumber()))
      acl_arg = acl_obj
    else:
      # No file exists, so expect a canned ACL string.
      if acl_arg not in canned_acls:
        raise CommandException('Invalid canned ACL "%s".' % acl_arg)

    # Now iterate over URIs and set the ACL on each.
    for uri_str in uri_args:
      for uri in wildcard_iterator(uri_str, ResultType.URIS, headers=headers,
                                   debug=debug):
        print 'Setting ACL on %s...' % uri
        uri.set_acl(acl_arg, uri.object_name, False, headers)

  def ExplainIfSudoNeeded(self, tf, dirs_to_remove):
    """Explains what to do if sudo needed to update gsutil software.

    Happens if gsutil was previously installed by a different user (typically if
    someone originally installed in a shared file system location, using sudo).

    Args:
      tf: opened TarFile.
      dirs_to_remove: list of directories to remove.

    Raises:
      CommandException if any errors encountered.
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
    config_file = self.config_file_list
    self.CleanUpUpdateCommand(tf, dirs_to_remove)
    raise CommandException(
        ('Since it was installed by a different user previously, you will need '
         'to update using the following commands.\nYou will be prompted for '
         'your password, and the install will run as "root". If you\'re unsure '
         'what this means please ask your system administrator for help:'
         '\n\tchmod 644 %s\n\tsudo env BOTO_CONFIG=%s gsutil update'
         '\n\tchmod 600 %s') % (config_file, config_file, config_file),
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

  def EnsureDirsSafeForUpdate(self, dirs):
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

  def CleanUpUpdateCommand(self, tf, dirs_to_remove):
    """Cleans up temp files etc. from running update command.

    Args:
      tf: opened TarFile.
      dirs_to_remove: list of directories to remove.

    """
    tf.close()
    self.EnsureDirsSafeForUpdate(dirs_to_remove)
    for directory in dirs_to_remove:
      shutil.rmtree(directory)

  def LoadVersionString(self):
    """Loads version string for currently installed gsutil command.

    Returns:
      Version string.

    Raises:
      CommandException if any errors encountered.
    """
    ver_file_path = self.gsutil_bin_dir + os.sep + 'VERSION'
    if not os.path.isfile(ver_file_path):
      raise CommandException(
          '%s not found. Did you install the\ncomplete gsutil software after '
          'the gsutil "update" command was implemented?' % ver_file_path)
    ver_file = open(ver_file_path, 'r')
    installed_version_string = ver_file.read().rstrip('\n')
    ver_file.close()
    return installed_version_string

  def UpdateCommand(self, unused_args, sub_opts=None, headers=None,
                    debug=False):
    """Implementation of experimental update command.

    Args:
      unused_args: command-line arguments
      sub_opts: command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: flag indicating whether to include debug output

    Raises:
      CommandException if any errors encountered.
    """
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
    self.CopyObjsCommand(['gs://pub/gsutil.tar.gz', 'file://gsutil.tar.gz'], [],
                         headers, debug)
    tf = tarfile.open('gsutil.tar.gz')
    tf.errorlevel = 1  # So fatal tarball unpack errors raise exceptions.
    tf.extract('./gsutil/VERSION')
    ver_file = open('gsutil/VERSION', 'r')
    latest_version_string = ver_file.read().rstrip('\n')
    ver_file.close()

    # The force_update option works around a problem with the way the
    # first gsutil "update" command exploded the gsutil and boto directories,
    # which didn't correctly install boto. People running that older code can
    # run "gsutil update" (to update to the newer gsutil update code) followed
    # by "gsutil update -f" (which will then update the boto code, even though
    # the VERSION is already the latest version).
    force_update = False
    if sub_opts:
      for o, unused_a in sub_opts:
        if o == '-f':
          force_update = True
    if not force_update and installed_version_string == latest_version_string:
      self.CleanUpUpdateCommand(tf, dirs_to_remove)
      raise CommandException('You have the latest version of gsutil installed.',
                             informational=True)

    print(('This command will update to the "%s" version of\ngsutil at %s') %
          (latest_version_string, self.gsutil_bin_dir))
    self.ExplainIfSudoNeeded(tf, dirs_to_remove)

    answer = raw_input('Proceed (Note: experimental command)? [y/N] ')
    if not answer or answer.lower()[0] != 'y':
      self.CleanUpUpdateCommand(tf, dirs_to_remove)
      raise CommandException('Not running update.', informational=True)

    # Ignore keyboard interrupts during the update to reduce the chance someone
    # hitting ^C leaves gsutil in a broken state.
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    # gsutil_bin_dir lists the path where the code should end up (like
    # /usr/local/gsutil), which is one level down from the relative path in the
    # tarball (since the latter creates files in ./gsutil). So, we need to
    # extract at the parent directory level.
    gsutil_bin_parent_dir = os.path.dirname(self.gsutil_bin_dir)

    # Extract tarball to a temporary directory in a sibling to gsutil_bin_dir.
    old_dir = tempfile.mkdtemp(dir=gsutil_bin_parent_dir)
    new_dir = tempfile.mkdtemp(dir=gsutil_bin_parent_dir)
    dirs_to_remove.append(old_dir)
    dirs_to_remove.append(new_dir)
    self.EnsureDirsSafeForUpdate(dirs_to_remove)
    try:
      tf.extractall(path=new_dir)
    except Exception, e:
      self.CleanUpUpdateCommand(tf, dirs_to_remove)
      raise CommandException('Update failed: %s.' % e)

    # Move old installation aside and new into place.
    os.rename(self.gsutil_bin_dir, old_dir + os.sep + 'old')
    os.rename(new_dir + os.sep + 'gsutil', self.gsutil_bin_dir)
    self.CleanUpUpdateCommand(tf, dirs_to_remove)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    print 'Update complete.'

  def CheckForDirFileConflict(self, src_uri, dst_path):
    """Checks whether copying src_uri into dst_path is not possible.

       This happens if a directory exists in local file system where a file
       needs to go or vice versa. In that case we print an error message and
       exits. Example: if the file "./x" exists and you try to do:
         gsutil cp gs://mybucket/x/y .
       the request can't succeed because it requires a directory where
       the file x exists.

    Args:
      src_uri: source StorageUri of copy
      dst_path: destination path.

    Raises:
      CommandException if any errors encountered.
    """
    final_dir = os.path.dirname(dst_path)
    if os.path.isfile(final_dir):
      raise CommandException('Cannot retrieve %s because it a file exists '
                             'where a directory needs to be created (%s).' %
                             (src_uri, final_dir))
    if os.path.isdir(dst_path):
      raise CommandException('Cannot retrieve %s because a directory exists '
                             '(%s) where the file needs to be created.' %
                             (src_uri, dst_path))

  def GetAclCommand(self, args, unused_sub_opts=None, headers=None,
                    debug=False):
    """Implementation of getacl command.

    Args:
      args: command-line arguments
      unused_sub_opts: command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: flag indicating whether to include debug output

    Raises:
      CommandException if any errors encountered.
    """
    # Wildcarding is allowed but must resolve to just one object.
    uris = list(wildcard_iterator(args[0], ResultType.URIS, headers=headers,
                                  debug=debug))
    if len(uris) != 1:
      raise CommandException('Wildcards must resolve to exactly one object for '
                             '"getacl" command.')
    uri = uris[0]
    if not uri.bucket_name:
      raise CommandException('"getacl" command must specify a bucket or '
                             'object.')
    acl = uri.get_acl(False, headers)
    # Pretty-print the XML to make it more easily human editable.
    parsed_xml = xml.dom.minidom.parseString(acl.to_xml().encode('utf-8'))
    print parsed_xml.toprettyxml(indent='    ')

  def PerformCopy(self, src_uri, dst_uri, sub_opts=None, headers=None):
    """Helper method for CopyObjsCommand.

    Args:
      src_uri: source StorageUri.
      dst_uri: destination StorageUri.
      sub_opts: command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.

    Raises:
      CommandException if any errors encountered.
    """
    # Make a copy of the input headers each time so we can set a different
    # MIME type for each object.
    if headers:
      metadata = headers.copy()
    else:
      metadata = {}
    gzip_exts = []
    canned_acl = None
    if sub_opts:
      for o, a in sub_opts:
        if o == '-a':
          canned_acls = dst_uri.canned_acls()
          if a not in canned_acls:
            raise CommandException('Invalid canned ACL "%s".' % a)
          canned_acl = a
        elif o == '-t':
          mimetype_tuple = mimetypes.guess_type(src_uri.object_name)
          mime_type = mimetype_tuple[0]
          content_encoding = mimetype_tuple[1]
          if mime_type:
            metadata['Content-Type'] = mime_type
            print '\t[Setting Content-Type=%s]' % mime_type
          else:
            print '\t[Unknown content type -> using application/octet stream]'
          if content_encoding:
            metadata['Content-Encoding'] = content_encoding
        elif o == '-z':
          gzip_exts = a.split(',')

    src_key = src_uri.get_key(False, headers)
    if not src_key:
      raise CommandException('"%s" does not exist.' % src_uri)

    # Separately handle cases to avoid extra file and network copying of
    # potentially very large files/objects.

    if (src_uri.is_cloud_uri() and dst_uri.is_cloud_uri() and
        src_uri.scheme == dst_uri.scheme):
      # Object -> object, within same provider (uses x-<provider>-copy-source
      # metadata HTTP header to request copying at the server). (Note: boto
      # does not currently provide a way to pass canned_acl when copying from
      # object-to-object through x-<provider>-copy-source):
      src_bucket = src_uri.get_bucket(False, headers)
      dst_bucket = dst_uri.get_bucket(False, headers)
      dst_bucket.copy_key(dst_uri.object_name, src_bucket.name,
                          src_uri.object_name, metadata)
      return

    dst_key = dst_uri.new_key(False, headers)
    if src_uri.is_file_uri() and dst_uri.is_cloud_uri():
      # File -> object:
      fname_parts = src_uri.object_name.split('.')
      if len(fname_parts) > 1 and fname_parts[-1] in gzip_exts:
        gzip_tmp = tempfile.mkstemp()
        gzip_path = gzip_tmp[1]
        the_gzip = gzip.open(gzip_path, 'wb')
        the_gzip.writelines(src_key.fp)
        the_gzip.close()
        metadata = headers.copy()
        metadata['Content-Length'] = str(os.path.getsize(gzip_path))
        metadata['Content-Encoding'] = 'gzip'
        dst_key.set_contents_from_file(open(gzip_path, 'rb'), headers=metadata,
                                       policy=canned_acl)
        os.unlink(gzip_path)
      else:
        dst_key.set_contents_from_file(src_key.fp, headers=headers,
                                       policy=canned_acl)
    elif src_uri.is_cloud_uri() and dst_uri.is_file_uri():
      # Object -> file:
      src_key.get_file(dst_key.fp, headers)
    elif src_uri.is_file_uri() and dst_uri.is_file_uri():
      # File -> file:
      dst_key.set_contents_from_file(src_key.fp, metadata)
    else:
      # We implement cross-provider object copy through a local temp file:
      tmp = tempfile.TemporaryFile()
      src_key.get_file(tmp, headers)
      tmp.seek(0)
      dst_key.set_contents_from_file(tmp, metadata)

  def ExpandWildcardsAndContainers(self, uri_strs, headers=None, debug=False):
    """Expands URI wildcarding, object-less bucket names, and directory names.

    Examples:
      Calling with uri_strs='gs://bucket' will enumerate all contained objects.
      Calling with uri_strs='file:///tmp' will enumerate all files under /tmp
         (or under any subdirectory).
      The previous example is equivalent to uri_strs='file:///tmp/*'
         and to uri_strs='file:///tmp/**'

    Args:
      uri_strs: URI strings needing expansion
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: flag indicating whether to include debug output

    Returns:
      dict mapping StorageUri(uri_str) -> list of StorageUri, for reach input.

      We build a dict of the expansion instead of using a generator to
      iterate incrementally because caller needs to know count before
      iterating and performing copy operations.
    """
    # The algorithm we use is:
    # 1. Build a first level expanded list from uri_strs consisting of all
    #    URIs that aren't file wildcards, plus expansions of the file wildcards.
    # 2. Build dict from above expanded list.
    #    We do so that we can properly handle the following example:
    #      gsutil cp file0 dir0 gs://bucket
    #    where dir0 contains file1 and dir1/file2.
    # If we didn't do the first expansion, this cp command would end up
    # with this expansion:
    #   {file://file0:[file://file0],file://dir0:[file://dir0/file1,
    #                                             file://dir0/dir1/file2]}
    # instead of the (correct) expansion:
    #   {file://file0:[file://file0],file://dir0/file1:[file://dir0/file1],
    #                                file://dir0/dir1:[file://dir0/dir1/file2]}
    # The latter expansion is needed so that in the "Copying..." loop of
    # CopyObjsCommand we know that dir0 was being copied, so we create an
    # object called gs://bucket/dir0/dir1/file2. (Otherwise it would look
    # like a single file was being copied, so we'd create an object called
    # gs://bucket/file2.)

    # Step 1.
    uris_to_expand = []
    for uri_str in uri_strs:
      uri = StorageUri(uri_str, debug=debug, validate=False)
      if uri.is_file_uri() and ContainsWildcard(uri_str):
        uris_to_expand.extend(list(wildcard_iterator(uri, ResultType.URIS,
                                                     headers=headers,
                                                     debug=debug)))
      else:
        uris_to_expand.append(uri)

    # Step 2.
    result = {}
    for uri in uris_to_expand:
      if uri.names_container():
        if uri.is_file_uri():
          # dir -> convert to implicit recursive wildcard.
          uri_to_iter = '%s/**' % uri.uri
        else:
          # bucket -> convert to implicit wildcard.
          uri_to_iter = uri.clone_replace_name('*')
      else:
        uri_to_iter = uri
      result[uri] = list(wildcard_iterator(uri_to_iter, ResultType.URIS,
                                           headers=headers, debug=debug))
    return result

  def ErrorCheckCopyRequest(self, src_uri_expansion, dst_uri_str, headers,
                            debug, command='cp'):
    """Checks copy request for problems, and builds needed dst_uri.

    Prints error message and exists if there's a problem.

    Args:
      src_uri_expansion: result from ExpandWildcardsAndContainers call.
      dst_uri_str: string representation of destination StorageUri.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: flag indicating whether to include debug output
      command: name of command on behalf of which this call is running.

    Returns:
      (dst_uri to use for copy, bool indicator of multi-source request).

    Raises:
      CommandException if any errors found.
    """
    if ContainsWildcard(dst_uri_str):
      matches = list(wildcard_iterator(dst_uri_str, ResultType.URIS,
                                       headers=headers, debug=debug))
      if len(matches) > 1:
        raise CommandException('Destination (%s) matches more than 1 URI' %
                               dst_uri_str)
      dst_uri = matches[0]
    else:
      dst_uri = StorageUri(dst_uri_str, debug=debug)

    for src_uri in src_uri_expansion:
      for exp_src_uri in src_uri_expansion[src_uri]:
        if (exp_src_uri.equals(dst_uri) or
            # Example case: gsutil cp gs://mybucket/a/bb mybucket
            (dst_uri.is_cloud_uri() and
             exp_src_uri.uri.find(dst_uri.uri) != -1)):
          raise CommandException('Overlapping source and dest URIs not '
                                 'allowed.')

    # If this is a multi-object copy request ensure dst_uri names a container.
    multi_src_request = (len(src_uri_expansion) > 1 or
                         len(src_uri_expansion.values()[0]) > 1)
    if multi_src_request:
      self.InsistUriNamesContainer(command, dst_uri)

    return (dst_uri, multi_src_request)

  def HandleMultiSrcCopyRequst(self, src_uri_expansion, dst_uri):
    """Rewrites dst_uri and creates dest dir as needed for multi-source copy.

    Args:
      src_uri_expansion: result from ExpandWildcardsAndContainers call.
      dst_uri: destination StorageUri.

    Returns:
      dst_uri to use for copy.
    """
    # If src_uri and dst_uri both name containers, handle
    # two cases to make copy command work like UNIX "cp -r" works:
    #   a) if dst_uri names a non-existent directory, copy objects to a new
    #      directory with the dst_uri name. In this case,
    #        gsutil gs://bucket/a dir
    #      should create dir/a.
    #   b) if dst_uri names an existing directory, copy objects under that
    #      directory. In this case,
    #        gsutil gs://bucket/a dir
    #      should create dir/bucket/a.
    src_uri_to_check = src_uri_expansion.keys()[0]
    if (src_uri_to_check.names_container() and dst_uri.names_container() and
        os.path.exists(dst_uri.object_name)):
      new_name = ('%s%s%s' % (dst_uri.object_name, os.sep,
                              src_uri_to_check.bucket_name)).rstrip('/')
      dst_uri = dst_uri.clone_replace_name(new_name)
    # Create dest directory if needed.
    if dst_uri.is_file_uri() and not os.path.exists(dst_uri.object_name):
      os.makedirs(dst_uri.object_name)
    return dst_uri

  def CopyObjsCommand(self, args, sub_opts=None, headers=None, debug=False,
                      command='cp'):
    """Implementation of cp command.

    Args:
      args: command-line arguments
      sub_opts: command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: flag indicating whether to include debug output
      command: name of command on behalf of which this call is running.

    Raises:
      CommandException: If any errors encountered.
    """
    # Expand wildcards and containers in source StorageUris.
    src_uri_expansion = self.ExpandWildcardsAndContainers(
        args[0:len(args)-1], headers, debug)

    # Check for various problems, and determine dst_uri based on request.
    (dst_uri, multi_src_request) = self.ErrorCheckCopyRequest(src_uri_expansion,
                                                              args[-1], headers,
                                                              debug, command)

    # Rewrite dst_uri and create dest dir as needed for multi-source copy.
    if multi_src_request:
      dst_uri = self.HandleMultiSrcCopyRequst(src_uri_expansion, dst_uri)

    # Now iterate over expanded src URIs, and perform copy operations.
    for src_uri in iter(src_uri_expansion):
      for exp_src_uri in src_uri_expansion[src_uri]:
        print 'Copying %s...' % exp_src_uri
        if dst_uri.names_container():
          # To match naming semantics of UNIX 'cp' command, copying files
          # to buckets/dirs should result in objects/files named by just the
          # final filename component; while copying directories should result
          # in objects/files mirroring the directory hierarchy. Example of the
          # first case:
          #   gsutil cp dir1/file1 gs://bucket
          # should create object gs://bucket/file1
          # Example of the second case:
          #   gsutil cp dir1/dir2 gs://bucket
          # should create object gs://bucket/dir2/file2 (assuming dir1/dir2
          # contains file2).
          if src_uri.names_container():
            dst_path_start = (src_uri.object_name.rstrip(os.sep)
                              .rpartition(os.sep)[-1])
            start_pos = exp_src_uri.object_name.find(dst_path_start)
            dst_key_name = exp_src_uri.object_name[start_pos:]
          else:
            # src is a file or object, so use final component of src name.
            dst_key_name = os.path.basename(exp_src_uri.object_name)
          if dst_uri.is_file_uri():
            # dst names a directory, so append src obj name to dst obj name.
            dst_key_name = '%s%s%s' % (dst_uri.object_name, os.sep,
                                       dst_key_name)
            self.CheckForDirFileConflict(exp_src_uri, dst_key_name)
        else:
          # dest is an object or file: use dst obj name
          dst_key_name = dst_uri.object_name
        new_dst_uri = dst_uri.clone_replace_name(dst_key_name)
        self.PerformCopy(exp_src_uri, new_dst_uri, sub_opts, headers)

  def HelpCommand(self, unused_args, unused_sub_opts=None, unused_headers=None,
                  unused_debug=None):
    """Implementation of help command.

    Args:
      unused_args: command-line arguments
      unused_sub_opts: command-specific options from getopt.
      unused_headers: dictionary containing optional HTTP headers to send.
      unused_debug: flag indicating whether to include debug output.
    """
    self.OutputUsageAndExit()

  def VerCommand(self, args, unused_sub_opts=None, unused_headers=None,
                 unused_debug=None):
    """Implementation of ver command.

    Args:
      args: command-line arguments. Only used by detailedDebug option.
      unused_sub_opts: command-specific options from getopt.
      unused_headers: dictionary containing optional HTTP headers to send.
      unused_debug: flag indicating whether to include debug output.
    """
    config_ver = ''
    for path in BotoConfigLocations:
      try:
        f = open(path, 'r')
        while True:
          line = f.readline()
          if not line:
            break
          if line.find('was created by gsutil version') != -1:
            config_ver = ', config file version %s' % line.split('"')[-2]
            break
        # Only look at first first config file found in BotoConfigLocations.
        break
      except IOError:
        pass

    if args:
      prefix = args[0]
    else:
      prefix = ''
    print '%sgsutil version %s%s' % (prefix, self.LoadVersionString(),
                                     config_ver)

  def PrintBucketInfo(self, bucket_uri, listing_style, headers=None,
                      debug=False):
    """Print listing info for given bucket.

    Args:
      bucket_uri: StorageUri being listed.
      listing_style: ListingStyle enum describing type of output desired.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: flag indicating whether to include debug output

    Returns:
      Tuple (total objects, total bytes) in the bucket.
    """
    bucket_objs = 0
    bucket_bytes = 0
    if listing_style == ListingStyle.SHORT:
      print bucket_uri
    else:
      try:
        for obj in wildcard_iterator(bucket_uri.clone_replace_name('*'),
                                     ResultType.KEYS, headers=headers,
                                     debug=debug):
          bucket_objs += 1
          bucket_bytes += obj.size
      except WildcardException, e:
        # Ignore non-matching wildcards, to allow empty bucket listings.
        if e.reason.find('No matches') == -1:
          raise e
      if listing_style == ListingStyle.LONG:
        print '%s : %s objects, %s' % (
            bucket_uri, bucket_objs, MakeHumanReadable(bucket_bytes))
      else:  # listing_style == ListingStyle.LONG_LONG:
        print '%s :\n\t%s objects, %s\n\tACL: %s' % (
            bucket_uri, bucket_objs, MakeHumanReadable(bucket_bytes),
            bucket_uri.get_acl(False, headers))
    return (bucket_objs, bucket_bytes)

  def PrintObjectInfo(self, iterated_uri, obj, listing_style, headers, debug):
    """Print listing info for given object.

    Args:
      iterated_uri: base StorageUri being listed (e.g., gs://abc/*).
      obj: object to be listed (or None if no associated object).
      listing_style: ListingStyle enum describing type of output desired.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: flag indicating whether to include debug output

    Returns:
      Object length (if listing_style is one of the long listing formats).

    Raises:
      CommandException if any errors encountered.
    """
    if listing_style == ListingStyle.SHORT:
      print UriStrFor(iterated_uri, obj)
      return 0
    elif listing_style == ListingStyle.LONG:
      # Exclude timestamp fractional secs (example: 2010-08-23T12:46:54.187Z).
      timestamp = obj.last_modified[:19]
      print '%10s  %s  %s' % (obj.size, timestamp, UriStrFor(iterated_uri, obj))
      return obj.size
    elif listing_style == ListingStyle.LONG_LONG:
      uri_str = UriStrFor(iterated_uri, obj)
      print '%s:' % uri_str
      obj.open_read()
      print '\tObject size:\t%s' % obj.size
      print '\tLast mod:\t%s' % obj.last_modified
      if obj.cache_control:
        print '\tCache control:\t%s' % obj.cache_control
      print '\tMIME type:\t%s' % obj.content_type
      if obj.content_encoding:
        print '\tContent-Encoding:\t%s' % obj.content_encoding
      if obj.metadata:
        for name in obj.metadata:
          print '\tMetadata:\t%s = %s' % (name, obj.metadata[name])
      print '\tMD5:\t%s' % obj.etag.strip('"\'')
      print '\tACL:\t%s' % StorageUri(uri_str, debug=debug).get_acl(False,
                                                                    headers)
      return obj.size
    else:
      raise CommandException('Unexpected ListingStyle(%s)' % listing_style)

  def ListCommand(self, args, sub_opts=None, headers=None, debug=False):
    """Implementation of ls command.

    Args:
      args: command-line arguments
      sub_opts: command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: flag indicating whether to include debug output
    """
    listing_style = ListingStyle.SHORT
    get_bucket_info = False
    if sub_opts:
      for o, unused_a in sub_opts:
        if o == '-b':
          get_bucket_info = True
        if o == '-l':
          listing_style = ListingStyle.LONG
        if o == '-L':
          listing_style = ListingStyle.LONG_LONG
    if not args:
      # default to listing all gs buckets
      args = ['gs://']

    total_objs = 0
    total_bytes = 0
    for uri_str in args:
      uri = StorageUri(uri_str, debug=debug, validate=False)

      if not uri.bucket_name:
        # Provider URI: add bucket wildcard to list buckets.
        for uri in wildcard_iterator('%s://*' % uri.scheme, ResultType.URIS,
                                     headers=headers, debug=debug):
          (bucket_objs, bucket_bytes) = self.PrintBucketInfo(uri, listing_style,
                                                             headers=headers,
                                                             debug=debug)
          total_bytes += bucket_bytes
          total_objs += bucket_objs

      elif not uri.object_name:
        if get_bucket_info:
          # ls -b request on provider+bucket URI: List info about bucket(s).
          for uri in wildcard_iterator(uri, ResultType.URIS, headers=headers,
                                       debug=debug):
            (bucket_objs, bucket_bytes) = self.PrintBucketInfo(uri,
                                                               listing_style,
                                                               headers=headers,
                                                               debug=debug)
            total_bytes += bucket_bytes
            total_objs += bucket_objs
        else:
          # ls request on provider+bucket URI: List objects in the bucket(s).
          for obj in wildcard_iterator(uri.clone_replace_name('*'),
                                       ResultType.KEYS, headers=headers,
                                       debug=debug):
            total_bytes += self.PrintObjectInfo(uri, obj, listing_style,
                                                headers=headers, debug=debug)
            total_objs += 1

      else:
        # Provider+bucket+object URI -> list the object(s).
        for obj in wildcard_iterator(uri, ResultType.KEYS, headers=headers,
                                     debug=debug):
          total_bytes += self.PrintObjectInfo(uri, obj, listing_style,
                                              headers=headers, debug=debug)
          total_objs += 1
    if listing_style != ListingStyle.SHORT:
      print ('TOTAL: %s objects, %s bytes (%s)' %
             (total_objs, total_bytes, MakeHumanReadable(total_bytes)))

  def MakeBucketsCommand(self, args, unused_sub_opts=None, headers=None,
                         debug=False):
    """Implementation of mb command.

    Args:
      args: command-line arguments
      unused_sub_opts: command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: flag indicating whether to include debug output

    Raises:
      CommandException if any errors encountered.
    """
    for bucket_uri_str in args:
      bucket_uri = StorageUri(bucket_uri_str, debug=debug)
      print 'Creating %s...' % bucket_uri
      bucket_uri.create_bucket(headers)

  def MoveObjsCommand(self, args, sub_opts=None, headers=None, debug=False):
    """Implementation of mv command.

       Note that there is no atomic rename operation - this command is simply
       a shorthand for 'cp' followed by 'rm'.

    Args:
      args: command-line arguments
      sub_opts: command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: flag indicating whether to include debug output
    """
    # Refuse to delete a bucket or directory src URI (force users to explicitly
    # do that as a separate operation).
    src_uri_to_check = StorageUri(args[0])
    if src_uri_to_check.names_container():
      raise CommandException('Will not remove source buckets or directories. '
                             'You must separately copy and remove for that '
                             'purpose.')

    if len(args) > 2:
      self.InsistUriNamesContainer('mv', StorageUri(args[-1]))

    # Expand wildcards before calling CopyObjsCommand and RemoveObjsCommand,
    # to prevent the following problem: starting with a bucket containing
    # only the object gs://bucket/obj, say the user does:
    #   gsutil mv gs://bucket/* gs://bucket/d.txt
    # If we didn't expand the wildcard first, the CopyObjsCommand would
    # first copy gs://bucket/obj exists to gs://bucket/d.txt, and the
    # RemoveObjsCommand would then remove that object.
    exp_arg_list = []
    for uri_str in args:
      uri = StorageUri(uri_str, debug=debug, validate=False)
      if ContainsWildcard(uri_str):
        exp_arg_list.extend(str(u) for u in list(
            wildcard_iterator(uri, ResultType.URIS, headers=headers,
                              debug=debug)))
      else:
        exp_arg_list.append(uri.uri)

    self.CopyObjsCommand(exp_arg_list, sub_opts, headers, debug, 'mv')
    self.RemoveObjsCommand(exp_arg_list[0:1], sub_opts, headers, debug)

  def RemoveBucketsCommand(self, args, unused_sub_opts=None, headers=None,
                           debug=False):
    """Implementation of rb command.

    Args:
      args: command-line arguments
      unused_sub_opts: command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: flag indicating whether to include debug output

    Raises:
      CommandException if any errors encountered.
    """
    # Expand bucket name wildcards, if any.
    for uri_str in args:
      for uri in wildcard_iterator(uri_str, ResultType.URIS, headers=headers,
                                   debug=debug):
        if uri.object_name:
          raise CommandException('"rb" command requires a URI with no object '
                                 'name')
        print 'Removing %s...' % uri
        uri.delete_bucket(headers)

  def RemoveObjsCommand(self, args, unused_sub_opts=None, headers=None,
                        debug=False):
    """Implementation of rm command.

    Args:
      args: command-line arguments
      unused_sub_opts: command-specific options from getopt.
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: flag indicating whether to include debug output

    Raises:
      CommandException or WildcardException if errors encountered.
    """
    # Expand object name wildcards, if any.
    for uri_str in args:
      for uri in wildcard_iterator(uri_str, ResultType.URIS, headers=headers,
                                   debug=debug):
        if uri.names_container():
          uri_str = uri_str.rstrip('/')
          raise CommandException('"rm" command will not remove buckets. To '
                                 'delete this/these bucket(s) do:\n\tgsutil rm '
                                 '%s/*\n\tgsutil rb %s' % (uri_str, uri_str))
        print 'Removing %s...' % uri
        uri.delete_key(False, headers)
