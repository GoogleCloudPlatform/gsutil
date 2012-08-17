# Copyright 2011 Google Inc.
# Copyright 2011, Nexenta Systems Inc.
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

import boto
import errno
import gzip
import hashlib
import mimetypes
import os
import platform
import re
import subprocess
import sys
import tempfile
import threading
import time

from boto.gs.resumable_upload_handler import ResumableUploadHandler
from boto import config
from boto.s3.resumable_download_handler import ResumableDownloadHandler
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
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HelpType
from gslib.help_provider import HELP_TYPE
from gslib.name_expansion import NameExpansionIterator
from gslib.util import MakeHumanReadable
from gslib.util import NO_MAX
from gslib.util import ONE_MB
from gslib.wildcard_iterator import ContainsWildcard

_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil cp [-a canned_acl] [-e] [-p] [-q] [-z ext1,ext2,...] src_uri dst_uri
    - or -
  gsutil cp [-a canned_acl] [-e] [-p] [-q] [-R] [-z extensions] uri... dst_uri


<B>DESCRIPTION</B>
  The gsutil cp command allows you to copy data between your local file
  system and the cloud, copy data within the cloud, and copy data between
  cloud storage providers. For example, to copy all text files from the
  local directory to a bucket you could do:

    gsutil cp *.txt gs://my_bucket

  Similarly, you can download text files from a bucket by doing:

    gsutil cp gs://my_bucket/*.txt .

  If you want to copy an entire directory tree you need to use the -R option:

    gsutil cp -R dir gs://my_bucket

  If you have a large number of files to upload you might want to use the
  gsutil -m option, to perform a parallel (multi-threaded/multi-processing)
  copy:

    gsutil -m cp -R dir gs://my_bucket


<B>HOW NAMES ARE CONSTRUCTED</B>
  The gsutil cp command strives to name objects in a way consistent with how
  Unix cp works, which causes names to be constructed in varying ways depending
  on whether you're performing a recursive directory copy or copying
  individually named objects; and whether you're copying to an existing or
  non-existent directory.

  When performing recursive directory copies, object names are constructed
  that mirror the source directory structure starting at the point of
  recursive processing. For example, the command:

    gsutil cp -R dir1/dir2 gs://my_bucket

  will create objects named like gs://my_bucket/dir2/a/b/c, assuming
  dir1/dir2 contains the file a/b/c.

  In contrast, copying individually named files will result in objects named
  by the final path component of the source files. For example, the command:

    gsutil cp dir1/dir2/** gs://my_bucket

  will create objects named like gs://my_bucket/c.

  The same rules apply for downloads: recursive copies of buckets and
  bucket subdirectories produce a mirrored filename structure, while copying
  individually (or wildcard) named objects produce flatly named files.

  Note that in the above example the '**' wildcard matches all names
  anywhere under dir. The wildcard '*' will match names just one level deep. For
  more details see 'gsutil help wildcards'.

  There's an additional wrinkle when working with subdirectories: the resulting
  names depend on whether the destination subdirectory exists. For example,
  if gs://my_bucket/subdir exists as a subdirectory, the command:

    gsutil cp -R dir1/dir2 gs://my_bucket/subdir

  will create objects named like gs://my_bucket/subdir/dir2/a/b/c. In contrast,
  if gs://my_bucket/subdir does not exist, this same gsutil cp command will
  create objects named like gs://my_bucket/subdir/a/b/c.


<B>COPYING TO/FROM SUBDIRECTORIES; DISTRIBUTING TRANSFERS ACROSS MACHINES</B>
  You can use gsutil to copy to and from subdirectories by using a command like:

    gsutil cp -R dir gs://my_bucket/data

  This will cause dir and all of its files and nested subdirectories to be
  copied under the specified destination, resulting in objects with names like
  gs://my_bucket/data/dir/a/b/c. Similarly you can download from bucket
  subdirectories by using a command like:

    gsutil cp -R gs://my_bucket/data dir

  This will cause everything nested under gs://my_bucket/data to be downloaded
  into dir, resulting in files with names like dir/data/a/b/c.

  Copying subdirectories is useful if you want to add data to an existing
  bucket directory structure over time. It's also useful if you want
  to parallelize uploads and downloads across multiple machines (often
  reducing overall transfer time compared with simply running gsutil -m
  cp on one machine). For example, if your bucket contains this structure:

    gs://my_bucket/data/result_set_01/
    gs://my_bucket/data/result_set_02/
    ...
    gs://my_bucket/data/result_set_99/

  you could perform concurrent downloads across 3 machines by running these
  commands on each machine, respectively:

    gsutil cp -R gs://my_bucket/data/result_set_[0-3]* dir
    gsutil cp -R gs://my_bucket/data/result_set_[4-6]* dir
    gsutil cp -R gs://my_bucket/data/result_set_[7-9]* dir

  Note that dir could be a local directory on each machine, or it could
  be a directory mounted off of a shared file server; whether the latter
  performs acceptably may depend on a number of things, so we recommend
  you experiment and find out what works best for you.


<B>COPYING IN THE CLOUD AND METADATA PRESERVATION</B>
  If both the source and destination URI are cloud URIs from the same
  provider, gsutil copies data "in the cloud" (i.e., without downloading
  to and uploading from the machine where you run gsutil). In addition to
  the performance and cost advantages of doing this, copying in the cloud
  preserves metadata (like Content-Type and Cache-Control).  In contrast,
  when you download data from the cloud it ends up in a file, which has
  no associated metadata. Thus, unless you have some way to hold on to
  or re-create that metadata, downloading to a file will not retain the
  metadata.

  Note that by default, the gsutil cp command does not copy the object
  ACL to the new object, and instead will use the default bucket ACL (see
  "gsutil help setdefacl").  You can override this behavior with the -p
  option (see OPTIONS below).


<B>RESUMABLE TRANSFERS</B>
  gsutil automatically uses the Google Cloud Storage resumable upload
  feature whenever you use the cp command to upload an object that is larger
  than 1 MB. You do not need to specify any special command line options
  to make this happen. If your upload is interrupted you can restart the
  upload by running the same cp command that you ran to start the upload.

  Similarly, gsutil automatically performs resumable downloads (using HTTP
  standard Range GET operations) whenever you use the cp command to download an
  object larger than 1 MB.

  Resumable uploads and downloads store some state information in a file
  in ~/.gsutil named by the destination object or file. If you attempt to
  resume a transfer from a machine with a different directory, the transfer
  will start over from scratch.

  See also "gsutil help prod" for details on using resumable transfers
  in production.


<B>STREAMING TRANSFERS</B>
  Use '-' in place of src_uri or dst_uri to perform a streaming
  transfer. For example:
    long_running_computation | gsutil cp - gs://my_bucket/obj

  Streaming transfers do not support resumable uploads/downloads.
  (The Google resumable transfer protocol has a way to support streaming
  transers, but gsutil doesn't currently implement support for this.)


<B>CHANGING TEMP DIRECTORIES</B>
  gsutil writes data to a temporary directory in several cases:
    - when compressing data to be uploaded (see the -z option)
    - when decompressing data being downloaded (when the data has
      Content-Encoding:gzip, e.g., as happens when uploaded using gsutil cp -z)
    - when copying between cloud service providers, where the destination
      provider does not support streaming uploads. In this case each object
      is downloaded from the source provider to a temp file, and then uploaded
      from that temp file to the destination provider.

  In these cases it's possible the temp file location on your system that
  gsutil selects by default may not have enough space. If you find that
  gsutil runs out of space during one of these operations (e.g., raising
  "CommandException: Inadequate temp space available to compress <your file>"
  during a gsutil cp -z operation), you can change where it writes these
  temp files by setting the TMPDIR environment variable. On Linux and MacOS
  you can do this using:

    export TMPDIR=/some/directory

  On Windows 7 you can change the TMPDIR environment variable from Start ->
  Computer -> System -> Advanced System Settings -> Environment Variables.
  You need to reboot after making this change for it to take effect. (Rebooting
  is not necessary after running the export command on Linux and MacOS.)


<B>OPTIONS</B>
  -a          Sets named canned_acl when uploaded objects created. See
              'gsutil help acls' for further details.

  -e          Exclude symlinks. When specified, symbolic links will not be
              copied.

  -p          Causes ACL to be preserved when copying in the cloud. Note that
              this option has performance and cost implications, because it
              is essentially performing three requests (getacl, cp, setacl).
              (The performance issue can be mitigated to some degree by
              using gsutil -m cp to cause parallel copying.)

	      You can avoid the additional performance and cost of using cp -p
	      if you want all objects in the destination bucket to end up with
	      the same ACL, but setting a default ACL on that bucket instead of
	      using cp -p. See "help gsutil setdefacl".

              Note that it's not valid to specify both the -a and -p options
              together.

  -q          Causes copies to be performed quietly, i.e., without reporting
              progress indicators of files being copied. Errors are still
              reported. This option can be useful for running gsutil from a
              cron job that logs its output to a file, for which the only
              information desired in the log is failures.

  -R, -r      Causes directories, buckets, and bucket subdirectories to be
              copied recursively. If you neglect to use this option for
              an upload, gsutil will copy any files it finds and skip any
              directories. Similarly, neglecting to specify -R for a download
              will cause gsutil to copy any objects at the current bucket
              directory level, and skip any subdirectories.

  -t          DEPRECATED. At one time this option was used to request setting
              Content-Type based on file extension and/or content, which is
              now the default behavior. The -t option is left in place for
              now to avoid breaking existing scripts. It will be removed at
              a future date.

  -z          'txt,html' Compresses file uploads with the given extensions.
              If you are uploading a large file with compressible content,
              such as a .js, .css, or .html file, you can gzip-compress the
              file during the upload process by specifying the -z <extensions>
              option. Compressing data before upload saves on usage charges
              because you are uploading a smaller amount of data.

              When you specify the -z option, the data from your files is
              compressed before it is uploaded, but your actual files are left
              uncompressed on the local disk. The uploaded objects retain the
              original content type and name as the original files but are given
              a Content-Encoding header with the value "gzip" to indicate that
              the object data stored are compressed on the Google Cloud Storage
              servers.

              For example, the following command:

                gsutil cp -z html -a public-read cattypes.html gs://mycats

              will do all of the following:
                - Upload as the object gs://mycats/cattypes.html (cp command)
                - Set the Content-Type to text/html (based on file extension)
                - Compress the data in the file cattypes.html (-z option)
                - Set the Content-Encoding to gzip (-z option)
                - Set the ACL to public-read (-a option)
                - If a user tries to view cattypes.html in a browser, the
                  browser will know to uncompress the data based on the
                  Content-Encoding header, and to render it as HTML based on
                  the Content-Type header.
""")

class KeyFile():
    """
    Wrapper class to expose Key class as file to boto.
    """
    def __init__(self, key):
        self.key = key

    def tell(self):
        raise IOError

    def seek(self, pos):
        raise IOError

    def read(self, size):
	return self.key.read(size)

    def write(self, buf):
        raise IOError

    def close(self):
        self.key.close()

class CpCommand(Command):
  """
  Implementation of gsutil cp command.

  Note that CpCommand is run for both gsutil cp and gsutil mv. The latter
  happens by MvCommand calling CpCommand and passing the hidden (undocumented)
  -M option. This allows the copy and remove needed for each mv to run
  together (rather than first running all the cp's and then all the rm's, as
  we originally had implemented), which in turn avoids the following problem
  with removing the wrong objects: starting with a bucket containing only
  the object gs://bucket/obj, say the user does:
    gsutil mv gs://bucket/* gs://bucket/d.txt
  If we ran all the cp's and then all the rm's and we didn't expand the wildcard
  first, the cp command would first copy gs://bucket/obj to gs://bucket/d.txt,
  and the rm command would then remove that object. In the implementation
  prior to gsutil release 3.12 we avoided this by building a list of objects
  to process and then running the copies and then the removes; but building
  the list up front limits scalability (compared with the current approach
  of processing the bucket listing iterator on the fly).
  """

  # Set default Content-Type type.
  DEFAULT_CONTENT_TYPE = 'application/octet-stream'
  USE_MAGICFILE = boto.config.getbool('GSUtil', 'use_magicfile', False)

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'cp',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : ['copy'],
    # Min number of args required by this command.
    MIN_ARGS : 2,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : NO_MAX,
    # Getopt-style string specifying acceptable sub args.
    # -t is deprecated but leave intact for now to avoid breakage.
    SUPPORTED_SUB_ARGS : 'a:eMpqrRtz:',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : True,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 0,
    # True if must configure gsutil before running command.
    CONFIG_REQUIRED : True,
  }
  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'cp',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['copy'],
    # Type of help:
    HELP_TYPE : HelpType.COMMAND_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Copy files and objects',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }

  def _CheckFinalMd5(self, key, file_name):
    """
    Checks that etag from server agrees with md5 computed after the
    download completes.
    """
    obj_md5 = key.etag.strip('"\'')
    file_md5 = None

    if hasattr(key, 'md5') and key.md5:
      file_md5 = key.md5
    else:
      print 'Computing MD5 from scratch for resumed download'

      # Open file in binary mode to avoid surprises in Windows.
      fp = open(file_name, 'rb')
      try:
        file_md5 = key.compute_md5(fp)[0]
      finally:
        fp.close()

    if self.debug:
      print 'Checking file md5 against etag. (%s/%s)' % (file_md5, obj_md5)
    if file_md5 != obj_md5:
      # Checksums don't match - remove file and raise exception.
      os.unlink(file_name)
      raise CommandException(
        'File changed during download: md5 signature doesn\'t match '
        'etag (incorrect downloaded file deleted)')

  def _CheckForDirFileConflict(self, exp_src_uri, dst_uri):
    """Checks whether copying exp_src_uri into dst_uri is not possible.

       This happens if a directory exists in local file system where a file
       needs to go or vice versa. In that case we print an error message and
       exits. Example: if the file "./x" exists and you try to do:
         gsutil cp gs://mybucket/x/y .
       the request can't succeed because it requires a directory where
       the file x exists.

       Note that we don't enforce any corresponding restrictions for buckets,
       because the flat namespace semantics for buckets doesn't prohibit such
       cases the way hierarchical file systems do. For example, if a bucket
       contains an object called gs://bucket/dir and then you run the command:
         gsutil cp file1 file2 gs://bucket/dir
       you'll end up with objects gs://bucket/dir, gs://bucket/dir/file1, and
       gs://bucket/dir/file2.

    Args:
      exp_src_uri: Expanded source StorageUri of copy.
      dst_uri: Destination URI.

    Raises:
      CommandException: if errors encountered.
    """
    if dst_uri.is_cloud_uri():
      # The problem can only happen for file destination URIs.
      return
    dst_path = dst_uri.object_name
    final_dir = os.path.dirname(dst_path)
    if os.path.isfile(final_dir):
      raise CommandException('Cannot retrieve %s because a file exists '
                             'where a directory needs to be created (%s).' %
                             (exp_src_uri, final_dir))
    if os.path.isdir(dst_path):
      raise CommandException('Cannot retrieve %s because a directory exists '
                             '(%s) where the file needs to be created.' %
                             (exp_src_uri, dst_path))

  def _InsistDstUriNamesContainer(self, exp_dst_uri,
                                  have_existing_dst_container, command_name):
    """
    Raises an exception if URI doesn't name a directory, bucket, or bucket
    subdir, with special exception for cp -R (see comments below).

    Args:
      exp_dst_uri: Wildcard-expanding dst_uri.
      have_existing_dst_container: bool indicator of whether exp_dst_uri
        names a container (directory, bucket, or existing bucket subdir).
      command_name: Name of command making call. May not be the same as
          self.command_name in the case of commands implemented atop other
          commands (like mv command).

    Raises:
      CommandException: if the URI being checked does not name a container.
    """
    if exp_dst_uri.is_file_uri():
      ok = exp_dst_uri.names_directory()
    else:
      if have_existing_dst_container:
        ok = True
      else:
        # It's ok to specify a non-existing bucket subdir, for example:
        #   gsutil cp -R dir gs://bucket/abc
        # where gs://bucket/abc isn't an existing subdir.
        ok = exp_dst_uri.names_object()
    if not ok:
      raise CommandException('Destination URI must name a directory, bucket, '
                             'or bucket\nsubdirectory for the multiple '
                             'source form of the %s command.' % command_name)

  class _FileCopyCallbackHandler(object):
    """Outputs progress info for large copy requests."""

    def __init__(self, upload):
      if upload:
        self.announce_text = 'Uploading'
      else:
        self.announce_text = 'Downloading'

    def call(self, total_bytes_transferred, total_size):
      sys.stderr.write('%s: %s/%s    \r' % (
          self.announce_text,
          MakeHumanReadable(total_bytes_transferred),
          MakeHumanReadable(total_size)))
      if total_bytes_transferred == total_size:
        sys.stderr.write('\n')

  class _StreamCopyCallbackHandler(object):
    """Outputs progress info for Stream copy to cloud.
       Total Size of the stream is not known, so we output
       only the bytes transferred.
    """

    def call(self, total_bytes_transferred, total_size):
      sys.stderr.write('Uploading: %s    \r' % (
          MakeHumanReadable(total_bytes_transferred)))
      if total_size and total_bytes_transferred == total_size:
        sys.stderr.write('\n')

  def _GetTransferHandlers(self, dst_uri, size, upload):
    """
    Selects upload/download and callback handlers.

    We use a callback handler that shows a simple textual progress indicator
    if size is above the configurable threshold.

    We use a resumable transfer handler if size is >= the configurable
    threshold and resumable transfers are supported by the given provider.
    boto supports resumable downloads for all providers, but resumable
    uploads are currently only supported by GS.

    Args:
      dst_uri: the destination URI.
      size: size of file (object) being uploaded (downloaded).
      upload: bool indication of whether transfer is an upload.
    """
    config = boto.config
    resumable_threshold = config.getint('GSUtil', 'resumable_threshold', ONE_MB)
    if not self.quiet and size >= resumable_threshold:
      cb = self._FileCopyCallbackHandler(upload).call
      num_cb = int(size / ONE_MB)
      resumable_tracker_dir = config.get(
          'GSUtil', 'resumable_tracker_dir',
          os.path.expanduser('~' + os.sep + '.gsutil'))
      if not os.path.exists(resumable_tracker_dir):
        os.makedirs(resumable_tracker_dir)
      if upload:
        # Encode the dest bucket and object name into the tracker file name.
        res_tracker_file_name = (
            re.sub('[/\\\\]', '_', 'resumable_upload__%s__%s.url' %
                   (dst_uri.bucket_name, dst_uri.object_name)))
      else:
        # Encode the fully-qualified dest file name into the tracker file name.
        res_tracker_file_name = (
            re.sub('[/\\\\]', '_', 'resumable_download__%s.etag' %
                   (os.path.realpath(dst_uri.object_name))))

      res_tracker_file_name = _hash_filename(res_tracker_file_name)
      tracker_file = '%s%s%s' % (resumable_tracker_dir, os.sep,
                                 res_tracker_file_name)
      if upload:
        if dst_uri.scheme == 'gs':
          transfer_handler = ResumableUploadHandler(tracker_file)
        else:
          transfer_handler = None
      else:
        transfer_handler = ResumableDownloadHandler(tracker_file)
    else:
      transfer_handler = None
      cb = None
      num_cb = None
    return (cb, num_cb, transfer_handler)

  def _LogCopyOperation(self, src_uri, dst_uri, headers):
    """
    Logs copy operation being performed, including Content-Type if appropriate.
    """
    if self.quiet:
      return
    if 'Content-Type' in headers and dst_uri.is_cloud_uri():
      content_type_msg = ' [Content-Type=%s]' % headers['Content-Type']
    else:
      content_type_msg = ''
    if src_uri.is_stream():
      self.THREADED_LOGGER.info('Copying from <STDIN>%s...', content_type_msg)
    else:
      self.THREADED_LOGGER.info('Copying %s%s...', src_uri, content_type_msg)

  # We pass the headers explicitly to this call instead of using self.headers
  # so we can set different metadata (like Content-Type type) for each object.
  def _CopyObjToObjSameProvider(self, src_key, src_uri, dst_uri, headers):
    self._SetContentTypeHeader(src_uri, headers)
    self._LogCopyOperation(src_uri, dst_uri, headers)
    # Do Object -> object copy within same provider (uses
    # x-<provider>-copy-source metadata HTTP header to request copying at the
    # server).
    src_bucket = src_uri.get_bucket(False, headers)
    dst_bucket = dst_uri.get_bucket(False, headers)
    preserve_acl = False
    canned_acl = None
    if self.sub_opts:
      for o, a in self.sub_opts:
        if o == '-a':
          canned_acls = dst_uri.canned_acls()
          if a not in canned_acls:
            raise CommandException('Invalid canned ACL "%s".' % a)
          canned_acl = a
          headers[dst_uri.get_provider().acl_header] = canned_acl
        if o == '-p':
          preserve_acl = True
    if preserve_acl and canned_acl:
      raise CommandException(
          'Specifying both the -p and -a options together is invalid.')
    start_time = time.time()
    # Pass headers in headers param not metadata param, so boto will copy
    # existing key's metadata and just set the additional headers specified
    # in the headers param (rather than using the headers to override existing
    # metadata). In particular this allows us to copy the existing key's
    # Content-Type and other metadata users need while still being able to
    # set headers the API needs (like x-goog-project-id). Note that this means
    # you can't do something like:
    #   gsutil cp -t Content-Type text/html gs://bucket/* gs://bucket2
    # to change the Content-Type while copying.
    dst_bucket.copy_key(dst_uri.object_name, src_bucket.name,
                        src_uri.object_name, preserve_acl=preserve_acl,
                        headers=headers)
    end_time = time.time()
    return (end_time - start_time, src_key.size)

  def _CheckFreeSpace(self, path):
    """Return path/drive free space (in bytes)."""
    if platform.system() == 'Windows':
      from ctypes import c_int, c_uint64, c_wchar_p, windll, POINTER, WINFUNCTYPE, WinError
      try:
        GetDiskFreeSpaceEx = WINFUNCTYPE(c_int, c_wchar_p, POINTER(c_uint64),
                                         POINTER(c_uint64), POINTER(c_uint64))
        GetDiskFreeSpaceEx = GetDiskFreeSpaceEx(
            ('GetDiskFreeSpaceExW', windll.kernel32), (
                (1, 'lpszPathName'),
                (2, 'lpFreeUserSpace'),
                (2, 'lpTotalSpace'),
                (2, 'lpFreeSpace'),))
      except AttributeError:
        GetDiskFreeSpaceEx = WINFUNCTYPE(c_int, c_char_p, POINTER(c_uint64),
                                         POINTER(c_uint64), POINTER(c_uint64))
        GetDiskFreeSpaceEx = GetDiskFreeSpaceEx(
            ('GetDiskFreeSpaceExA', windll.kernel32), (
                (1, 'lpszPathName'),
                (2, 'lpFreeUserSpace'),
                (2, 'lpTotalSpace'),
                (2, 'lpFreeSpace'),))

      def GetDiskFreeSpaceEx_errcheck(result, func, args):
        if not result:
            raise WinError()
        return args[1].value
      GetDiskFreeSpaceEx.errcheck = GetDiskFreeSpaceEx_errcheck

      return GetDiskFreeSpaceEx(os.getenv('SystemDrive'))
    else:
      (_, f_frsize, _, _, f_bavail, _, _, _, _, _) = os.statvfs(path)
      return f_frsize * f_bavail

  def _PerformResumableUploadIfApplies(self, fp, dst_uri, canned_acl, headers):
    """
    Performs resumable upload if supported by provider and file is above
    threshold, else performs non-resumable upload.

    Returns (elapsed_time, bytes_transferred).
    """
    start_time = time.time()
    file_size = os.path.getsize(fp.name)
    dst_key = dst_uri.new_key(False, headers)
    (cb, num_cb, res_upload_handler) = self._GetTransferHandlers(
        dst_uri, file_size, True)
    if dst_uri.scheme == 'gs':
      # Resumable upload protocol is Google Cloud Storage-specific.
      dst_key.set_contents_from_file(fp, headers, policy=canned_acl,
                                     cb=cb, num_cb=num_cb,
                                     res_upload_handler=res_upload_handler)
    else:
      dst_key.set_contents_from_file(fp, headers, policy=canned_acl,
                                     cb=cb, num_cb=num_cb)
    if res_upload_handler:
      bytes_transferred = file_size - res_upload_handler.upload_start_point
    else:
      bytes_transferred = file_size
    end_time = time.time()
    return (end_time - start_time, bytes_transferred)

  def _PerformStreamingUpload(self, fp, dst_uri, headers, canned_acl=None):
    """
    Performs a streaming upload to the cloud.

    Args:
      fp: The file whose contents to upload.
      dst_uri: Destination StorageUri.
      headers: A copy of the headers dictionary.
      canned_acl: Optional canned ACL to set on the object.

    Returns (elapsed_time, bytes_transferred).
    """
    start_time = time.time()
    dst_key = dst_uri.new_key(False, headers)

    cb = self._StreamCopyCallbackHandler().call
    dst_key.set_contents_from_stream(fp, headers, policy=canned_acl, cb=cb)
    try:
      bytes_transferred = fp.tell()
    except:
      bytes_transferred = 0

    end_time = time.time()
    return (end_time - start_time, bytes_transferred)

  def _SetContentTypeHeader(self, src_uri, headers):
    """
    Sets content type header to value specified in '-h Content-Type' option (if
    specified); else sets using Content-Type detection.
    """
    if 'Content-Type' in headers:
      # If empty string specified (i.e., -h "Content-Type:") set header to None,
      # which will inhibit boto from sending the CT header. Otherwise, boto will
      # pass through the user specified CT header.
      if not headers['Content-Type']:
        headers['Content-Type'] = None
      # else we'll keep the value passed in via -h option (not performing
      # content type detection).
    else:
      # Only do content type recognition is src_uri is a file. Object-to-object
      # copies with no -h Content-Type specified re-use the content type of the
      # source object.
      if src_uri.is_file_uri():
        object_name = src_uri.object_name
        content_type = None
        # Streams (denoted by '-') are expected to be 'application/octet-stream'
        # and 'file' would partially consume them.
        if object_name != '-':
          if self.USE_MAGICFILE:
            p = subprocess.Popen(['file', '--mime-type', object_name],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            output, error = p.communicate()
            if p.returncode != 0 or error:
              raise CommandException(
                  'Encountered error running "file --mime-type %s" '
                  '(returncode=%d).\n%s' % (object_name, p.returncode, error))
            # Parse output by removing line delimiter and splitting on last ":
            content_type = output.rstrip().rpartition(': ')[2]
          else:
            content_type = mimetypes.guess_type(object_name)[0]
        if not content_type:
          content_type = self.DEFAULT_CONTENT_TYPE
        headers['Content-Type'] = content_type

  def _UploadFileToObject(self, src_key, src_uri, dst_uri, headers,
                          should_log=True):
    """Helper method for uploading a local file to an object.

    Args:
      src_key: Source StorageUri. Must be a file URI.
      src_uri: Source StorageUri.
      dst_uri: Destination StorageUri.
      headers: The headers dictionary.
      should_log: bool indicator whether we should log this operation.
    Returns:
      (elapsed_time, bytes_transferred) excluding overhead like initial HEAD.

    Raises:
      CommandException: if errors encountered.
    """
    gzip_exts = []
    canned_acl = None
    if self.sub_opts:
      for o, a in self.sub_opts:
        if o == '-a':
          canned_acls = dst_uri.canned_acls()
          if a not in canned_acls:
            raise CommandException('Invalid canned ACL "%s".' % a)
          canned_acl = a
        elif o == '-t':
          print('Warning: -t is deprecated, and will be removed in the future. '
                'Content type\ndetection is '
                'now performed by default, unless inhibited by specifying '
                'a\nContent-Type header via the -h option.')
        elif o == '-z':
          gzip_exts = a.split(',')

    self._SetContentTypeHeader(src_uri, headers)
    if should_log:
      self._LogCopyOperation(src_uri, dst_uri, headers)

    if 'Content-Language' not in headers:
       content_language = config.get_value('GSUtil', 'content_language')
       if content_language:
         headers['Content-Language'] = content_language

    fname_parts = src_uri.object_name.split('.')
    if len(fname_parts) > 1 and fname_parts[-1] in gzip_exts:
      if self.debug:
        print 'Compressing %s (to tmp)...' % src_key
      (gzip_fh, gzip_path) = tempfile.mkstemp()
      gzip_fp = None
      try:
        # Check for temp space. Assume the compressed object is at most 2x
        # the size of the object (normally should compress to smaller than
        # the object)
        if (self._CheckFreeSpace(gzip_path)
            < 2*int(os.path.getsize(src_key.name))):
          raise CommandException('Inadequate temp space available to compress '
                                 '%s' % src_key.name)
        gzip_fp = gzip.open(gzip_path, 'wb')
        gzip_fp.writelines(src_key.fp)
      finally:
        if gzip_fp:
          gzip_fp.close()
        os.close(gzip_fh)
      headers['Content-Encoding'] = 'gzip'
      gzip_fp = open(gzip_path, 'rb')
      try:
        (elapsed_time, bytes_transferred) = (
            self._PerformResumableUploadIfApplies(gzip_fp, dst_uri,
                                                  canned_acl, headers))
      finally:
        gzip_fp.close()
      try:
        os.unlink(gzip_path)
      # Windows sometimes complains the temp file is locked when you try to
      # delete it.
      except Exception, e:
        pass
    elif (src_key.is_stream()
          and dst_uri.get_provider().supports_chunked_transfer()):
      (elapsed_time, bytes_transferred) = self._PerformStreamingUpload(
          src_key.fp, dst_uri, headers, canned_acl)
    else:
      if src_key.is_stream():
        # For Providers that doesn't support chunked Transfers
        tmp = tempfile.NamedTemporaryFile()
        file_uri = self.suri_builder.StorageUri('file://%s' % tmp.name)
        try:
          file_uri.new_key(False, headers).set_contents_from_file(
              src_key.fp, headers)
          src_key = file_uri.get_key()
        finally:
          file_uri.close()
      try:
        (elapsed_time, bytes_transferred) = (
            self._PerformResumableUploadIfApplies(src_key.fp, dst_uri,
                                                  canned_acl, headers))
      finally:
        if src_key.is_stream():
          tmp.close()
        else:
          src_key.close()

    return (elapsed_time, bytes_transferred)

  def _DownloadObjectToFile(self, src_key, src_uri, dst_uri, headers,
                            should_log=True):
    if should_log:
      self._LogCopyOperation(src_uri, dst_uri, headers)
    (cb, num_cb, res_download_handler) = self._GetTransferHandlers(
        dst_uri, src_key.size, False)
    file_name = dst_uri.object_name
    dir_name = os.path.dirname(file_name)
    if dir_name and not os.path.exists(dir_name):
      # Do dir creation in try block so can ignore case where dir already
      # exists. This is needed to avoid a race condition when running gsutil
      # -m cp.
      try:
        os.makedirs(dir_name)
      except OSError, e:
        if e.errno != errno.EEXIST:
          raise
    # For gzipped objects not named *.gz download to a temp file and unzip.
    if (hasattr(src_key, 'content_encoding')
        and src_key.content_encoding == 'gzip'
        and not file_name.endswith('.gz')):
      # We can't use tempfile.mkstemp() here because we need a predictable
      # filename for resumable downloads.
      download_file_name = '%s_.gztmp' % file_name
      need_to_unzip = True
    else:
      download_file_name = file_name
      need_to_unzip = False
    fp = None
    try:
      if res_download_handler:
        fp = open(download_file_name, 'ab')
      else:
        fp = open(download_file_name, 'wb')
      start_time = time.time()
      src_key.get_contents_to_file(fp, headers, cb=cb, num_cb=num_cb,
                                   res_download_handler=res_download_handler)
      # If a custom test method is defined, call it here. For the copy command,
      # test methods are expected to take one argument: an open file pointer,
      # and are used to perturb the open file during download to exercise
      # download error detection.
      if self.test_method:
        self.test_method(fp)
      end_time = time.time()
    finally:
      if fp:
        fp.close()

    # Discard the md5 if we are resuming a partial download.
    if res_download_handler and res_download_handler.download_start_point:
      src_key.md5 = None

    # Verify downloaded file checksum matched source object's checksum.
    self._CheckFinalMd5(src_key, download_file_name)

    if res_download_handler:
      bytes_transferred = (
          src_key.size - res_download_handler.download_start_point)
    else:
      bytes_transferred = src_key.size
    if need_to_unzip:
      # Log that we're uncompressing if the file is big enough that
      # decompressing would make it look like the transfer "stalled" at the end.
      if not self.quiet and bytes_transferred > 10 * 1024 * 1024:
        self.THREADED_LOGGER.info('Uncompressing downloaded tmp file to %s...',
                                  file_name)
      # Downloaded gzipped file to a filename w/o .gz extension, so unzip.
      f_in = gzip.open(download_file_name, 'rb')
      f_out = open(file_name, 'wb')
      try:
        while True:
          data = f_in.read(8192)
          if not data:
            break
          f_out.write(data)
      finally:
        f_out.close()
        f_in.close()
        os.unlink(download_file_name)
    return (end_time - start_time, bytes_transferred)

  def _PerformDownloadToStream(self, src_key, src_uri, str_fp, headers):
    (cb, num_cb, res_download_handler) = self._GetTransferHandlers(
                                src_uri, src_key.size, False)
    start_time = time.time()
    src_key.get_contents_to_file(str_fp, headers, cb=cb, num_cb=num_cb)
    end_time = time.time()
    bytes_transferred = src_key.size
    end_time = time.time()
    return (end_time - start_time, bytes_transferred)

  def _CopyFileToFile(self, src_key, src_uri, dst_uri, headers):
    self._LogCopyOperation(src_uri, dst_uri, headers)
    dst_key = dst_uri.new_key(False, headers)
    start_time = time.time()
    dst_key.set_contents_from_file(src_key.fp, headers)
    end_time = time.time()
    return (end_time - start_time, os.path.getsize(src_key.fp.name))

  def _CopyObjToObjDiffProvider(self, src_key, src_uri, dst_uri, headers):
    self._SetContentTypeHeader(src_uri, headers)
    self._LogCopyOperation(src_uri, dst_uri, headers)
    # If destination is GS we can avoid the local copying through a local file
    # as GS supports chunked transfer. This also allows us to preserve metadata
    # between original and destination object.
    if dst_uri.scheme == 'gs':
      canned_acl = None
      if self.sub_opts:
        for o, a in self.sub_opts:
          if o == '-a':
            canned_acls = dst_uri.canned_acls()
            if a not in canned_acls:
              raise CommandException('Invalid canned ACL "%s".' % a)
            canned_acl = a
          elif o == '-p':
            # We don't attempt to preserve ACLs across providers because
            # GCS and S3 support different ACLs.
            raise NotImplementedError('Cross-provider cp -p not supported')

      # TODO: This _PerformStreamingUpload call passes in a Key for fp
      # param, relying on Python "duck typing" (the fact that the lower-level
      # methods that expect an fp only happen to call fp methods that are
      # defined and semantically equivalent to those defined on src_key). This
      # should be replaced by a class that wraps an fp interface around the
      # Key, throwing 'not implemented' for methods (like seek) that aren't
      # implemented by non-file Keys.
      # NOTE: As of 7/28/2012 this bug now makes cross-provider copies into gs
      # fail, because of boto changes that make that code now attempt to perform
      # additional operations on the fp parameter, like seek() and tell().
      return self._PerformStreamingUpload(KeyFile(src_key), dst_uri, headers, canned_acl)

    # If destination is not GS we implement object copy through a local
    # temp file. There are at least 3 downsides of this approach:
    #   1. It doesn't preserve metadata from the src object when uploading to
    #      the dst object.
    #   2. It requires enough temp space on the local disk to hold the file
    #      while transferring.
    #   3. Killing the gsutil process partway through and then restarting will
    #      always repeat the download and upload, because the temp file name is
    #      different for each incarnation. (If however you just leave the
    #      process running and failures happen along the way, they will
    #      continue to restart and make progress as long as not too many
    #      failures happen in a row with no progress.)
    tmp = tempfile.NamedTemporaryFile()
    if self._CheckFreeSpace(tempfile.tempdir) < src_key.size:
      raise CommandException('Inadequate temp space available to perform the '
                             'requested copy')
    start_time = time.time()
    file_uri = self.suri_builder.StorageUri('file://%s' % tmp.name)
    try:
      self._DownloadObjectToFile(src_key, src_uri, file_uri, headers, False)
      self._UploadFileToObject(file_uri.get_key(), file_uri, dst_uri, headers,
                               False)
    finally:
      tmp.close()
    end_time = time.time()
    return (end_time - start_time, src_key.size)

  def _PerformCopy(self, src_uri, dst_uri):
    """Performs copy from src_uri to dst_uri, handling various special cases.

    Args:
      src_uri: Source StorageUri.
      dst_uri: Destination StorageUri.

    Returns:
      (elapsed_time, bytes_transferred) excluding overhead like initial HEAD.

    Raises:
      CommandException: if errors encountered.
    """
    # Make a copy of the input headers each time so we can set a different
    # content type for each object.
    if self.headers:
      headers = self.headers.copy()
    else:
      headers = {}

    src_key = src_uri.get_key(False, headers)
    if not src_key:
      raise CommandException('"%s" does not exist.' % src_uri)

    if src_uri.is_cloud_uri() and dst_uri.is_cloud_uri():
      if src_uri.scheme == dst_uri.scheme:
        return self._CopyObjToObjSameProvider(src_key, src_uri, dst_uri,
                                              headers)
      else:
        return self._CopyObjToObjDiffProvider(src_key, src_uri, dst_uri,
                                              headers)
    elif src_uri.is_file_uri() and dst_uri.is_cloud_uri():
      return self._UploadFileToObject(src_key, src_uri, dst_uri, headers)
    elif src_uri.is_cloud_uri() and dst_uri.is_file_uri():
      return self._DownloadObjectToFile(src_key, src_uri, dst_uri, headers)
    elif src_uri.is_file_uri() and dst_uri.is_file_uri():
      return self._CopyFileToFile(src_key, src_uri, dst_uri, headers)
    else:
      raise CommandException('Unexpected src/dest case')

  def _ExpandDstUri(self, dst_uri_str):
    """
    Expands wildcard if present in dst_uri_str.

    Args:
      dst_uri_str: String representation of requested dst_uri.

    Returns:
        (exp_dst_uri, have_existing_dst_container)
        where have_existing_dst_container is a bool indicating whether
        exp_dst_uri names an existing directory, bucket, or bucket subdirectory.

    Raises:
      CommandException: if dst_uri_str matched more than 1 URI.
    """
    dst_uri = self.suri_builder.StorageUri(dst_uri_str)

    # Handle wildcarded dst_uri case.
    if ContainsWildcard(dst_uri):
      blr_expansion = list(self.WildcardIterator(dst_uri))
      if len(blr_expansion) != 1:
        raise CommandException('Destination (%s) must match exactly 1 URI' %
                               dst_uri_str)
      blr = blr_expansion[0]
      uri = blr.GetUri()
      if uri.is_cloud_uri():
        return (uri, uri.names_bucket() or blr.HasPrefix()
                or blr.GetKey().endswith('/'))
      else:
        return (uri, uri.names_directory())

    # Handle non-wildcarded dst_uri:
    if dst_uri.is_file_uri():
      return (dst_uri, dst_uri.names_directory())
    if dst_uri.names_bucket():
      return (dst_uri, True)
    # For object URIs check 3 cases: (a) if the name ends with '/' treat as a
    # subdir; else, perform a wildcard expansion with dst_uri + "*" and then
    # find if (b) there's a Prefix matching dst_uri, or (c) name is of form
    # dir_$folder$ (and in both these cases also treat dir as a subdir).
    if dst_uri.is_cloud_uri() and dst_uri_str.endswith('/'):
      return (dst_uri, True)
    blr_expansion = list(self.WildcardIterator(
        '%s*' % dst_uri_str.rstrip(dst_uri.delim)))
    for blr in blr_expansion:
      if blr.GetRStrippedUriString().endswith('_$folder$'):
        return (dst_uri, True)
      if blr.GetRStrippedUriString() == dst_uri_str.rstrip(dst_uri.delim):
        return (dst_uri, blr.HasPrefix())
    return (dst_uri, False)

  def _ConstructDstUri(self, src_uri, exp_src_uri,
                       src_uri_names_container, src_uri_expands_to_multi,
                       have_multiple_srcs, exp_dst_uri,
                       have_existing_dest_subdir):
    """
    Constructs the destination URI for a given exp_src_uri/exp_dst_uri pair,
    using context-dependent naming rules that mimic Unix cp and mv behavior.

    Args:
      src_uri: src_uri to be copied.
      exp_src_uri: Single StorageUri from wildcard expansion of src_uri.
      src_uri_names_container: True if src_uri names a container (including the
          case of a wildcard-named bucket subdir (like gs://bucket/abc,
          where gs://bucket/abc/* matched some objects). Note that this is
          additional semantics tha src_uri.names_container() doesn't understand
          because the latter only understands StorageUris, not wildcards.
      src_uri_expands_to_multi: True if src_uri expanded to multiple URIs.
      have_multiple_srcs: True if this is a multi-source request. This can be
          true if src_uri wildcard-expanded to multiple URIs or if there were
          multiple source URIs in the request.
      exp_dst_uri: the expanded StorageUri requested for the cp destination.
          Final written path is constructed from this plus a context-dependent
          variant of src_uri.
      have_existing_dest_subdir: bool indicator whether dest is an existing
        subdirectory.

    Returns:
      StorageUri to use for copy.

    Raises:
      CommandException if destination object name not specified for
      source and source is a stream.
    """
    if self._ShouldTreatDstUriAsSingleton(
        have_multiple_srcs, have_existing_dest_subdir, exp_dst_uri):
      # We're copying one file or object to one file or object.
      return exp_dst_uri

    if exp_src_uri.is_stream():
      if exp_dst_uri.names_container():
        raise CommandException('Destination object name needed when '
                               'source is a stream')
      return exp_dst_uri

    if not self.recursion_requested and not have_multiple_srcs:
      # We're copying one file or object to a subdirectory. Append final comp
      # of exp_src_uri to exp_dest_uri.
      src_final_comp = exp_src_uri.object_name.rpartition(src_uri.delim)[-1]
      return self.suri_builder.StorageUri('%s%s%s' % (
          exp_dst_uri.uri.rstrip(exp_dst_uri.delim), exp_dst_uri.delim,
          src_final_comp))

    # Else we're copying multiple sources to a directory, bucket, or a bucket
    # "sub-directory".

    # Ensure exp_dst_uri ends in delim char if we're doing a multi-src copy or
    # a copy to a directory. (The check for copying to a directory needs
    # special-case handling so that the command:
    #   gsutil cp gs://bucket/obj dir
    # will turn into file://dir/ instead of file://dir -- the latter would cause
    # the file "dirobj" to be created.)
    # Note: need to check have_multiple_srcs or src_uri.names_container()
    # because src_uri could be a bucket containing a single object, named
    # as gs://bucket.
    if ((have_multiple_srcs or src_uri.names_container()
         or os.path.isdir(exp_dst_uri.object_name))
        and not exp_dst_uri.uri.endswith(exp_dst_uri.delim)):
      exp_dst_uri = exp_dst_uri.clone_replace_name(
         '%s%s' % (exp_dst_uri.object_name, exp_dst_uri.delim)
      )

    # Making naming behavior match how things work with local Unix cp and mv
    # operations depends on many factors, including whether the destination is a
    # container, the plurality of the source(s), and whether the mv command is
    # being used:
    # 1. For the "mv" command that specifies a non-existent destination subdir,
    #    renaming should occur at the level of the src subdir, vs appending that
    #    subdir beneath the dst subdir like is done for copying. For example:
    #      gsutil rm -R gs://bucket
    #      gsutil cp -R cloudreader gs://bucket
    #      gsutil cp -R cloudauth gs://bucket/subdir1
    #      gsutil mv gs://bucket/subdir1 gs://bucket/subdir2
    #    would (if using cp naming behavior) end up with paths like:
    #      gs://bucket/subdir2/subdir1/cloudauth/.svn/all-wcprops
    #    whereas mv naming behavior should result in:
    #      gs://bucket/subdir2/cloudauth/.svn/all-wcprops
    # 2. Copying from directories, buckets, or bucket subdirs should result in
    #    objects/files mirroring the source directory hierarchy. For example:
    #      gsutil cp dir1/dir2 gs://bucket
    #    should create the object gs://bucket/dir2/file2, assuming dir1/dir2
    #    contains file2).
    #    To be consistent with Unix cp behavior, there's one more wrinkle when
    #    working with subdirs: The resulting object names depend on whether the
    #    destination subdirectory exists. For example, if gs://bucket/subdir
    #    exists, the command:
    #      gsutil cp -R dir1/dir2 gs://bucket/subdir
    #    should create objects named like gs://bucket/subdir/dir2/a/b/c. In
    #    contrast, if gs://bucket/subdir does not exist, this same command
    #    should create objects named like gs://bucket/subdir/a/b/c.
    # 3. Copying individual files or objects to dirs, buckets or bucket subdirs
    #    should result in objects/files named by the final source file name
    #    component. Example:
    #      gsutil cp dir1/*.txt gs://bucket
    #    should create the objects gs://bucket/f1.txt and gs://bucket/f2.txt,
    #    assuming dir1 contains f1.txt and f2.txt.

    if (self.perform_mv and self.recursion_requested
        and src_uri_expands_to_multi and not have_existing_dest_subdir):
      # Case 1. Handle naming rules for bucket subdir mv. Here we want to
      # line up the src_uri against its expansion, to find the base to build
      # the new name. For example, running the command:
      #   gsutil mv gs://bucket/abcd gs://bucket/xyz
      # when processing exp_src_uri=gs://bucket/abcd/123
      # exp_src_uri_tail should become /123
      # Note: mv.py code disallows wildcard specification of source URI.
      exp_src_uri_tail = exp_src_uri.uri[len(src_uri.uri):]
      dst_key_name = '%s/%s' % (exp_dst_uri.object_name.rstrip('/'),
                                exp_src_uri_tail.strip('/'))
      return exp_dst_uri.clone_replace_name(dst_key_name)

    if src_uri_names_container and not exp_dst_uri.names_file():
      # Case 2. Build dst_key_name from subpath of exp_src_uri past
      # where src_uri ends. For example, for src_uri=gs://bucket/ and
      # exp_src_uri=gs://bucket/src_subdir/obj, dst_key_name should be
      # src_subdir/obj.
      src_uri_path_sans_final_dir = _GetPathBeforeFinalDir(src_uri)
      dst_key_name = exp_src_uri.uri[
         len(src_uri_path_sans_final_dir):].lstrip(src_uri.delim)
      # Handle case where dst_uri is a non-existent subdir.
      if not have_existing_dest_subdir:
        dst_key_name = dst_key_name.partition(exp_dst_uri.delim)[-1]
      # Handle special case where src_uri was a directory named with '.' or
      # './', so that running a command like:
      #   gsutil cp -r . gs://dest
      # will produce obj names of the form gs://dest/abc instead of
      # gs://dest/./abc.
      if dst_key_name.startswith('./'):
        dst_key_name = dst_key_name[2:]

    else:
      # Case 3.
      dst_key_name = exp_src_uri.object_name.rpartition(src_uri.delim)[-1]

    if (exp_dst_uri.is_file_uri()
        or self._ShouldTreatDstUriAsBucketSubDir(
            have_multiple_srcs, exp_dst_uri, have_existing_dest_subdir)):
      if exp_dst_uri.object_name.endswith(exp_dst_uri.delim):
        dst_key_name = '%s%s%s' % (
            exp_dst_uri.object_name.rstrip(exp_dst_uri.delim),
            exp_dst_uri.delim, dst_key_name)
      else:
        dst_key_name = '%s%s' % (exp_dst_uri.object_name, dst_key_name)

    return exp_dst_uri.clone_replace_name(dst_key_name)

  def _FixWindowsNaming(self, src_uri, dst_uri):
    """
    Rewrites the destination URI built by _ConstructDstUri() to translate
    Windows pathnames to cloud pathnames if needed.

    Args:
      src_uri: Source URI to be copied.
      dst_uri: The destination URI built by _ConstructDstUri().

    Returns:
      StorageUri to use for copy.
    """
    if (src_uri.is_file_uri() and src_uri.delim == '\\'
        and dst_uri.is_cloud_uri()):
      trans_uri_str = re.sub(r'\\', '/', dst_uri.uri)
      dst_uri = self.suri_builder.StorageUri(trans_uri_str)
    return dst_uri

  # Command entry point.
  def RunCommand(self):

    # Inner funcs.
    def _CopyExceptionHandler(e):
      """Simple exception handler to allow post-completion status."""
      self.THREADED_LOGGER.error(str(e))
      self.copy_failure_count += 1

    def _CopyFunc(name_expansion_result):
      """Worker function for performing the actual copy (and rm, for mv)."""
      if self.perform_mv:
        cmd_name = 'mv'
      else:
        cmd_name = self.command_name
      src_uri = self.suri_builder.StorageUri(
          name_expansion_result.GetSrcUriStr())
      exp_src_uri = self.suri_builder.StorageUri(
          name_expansion_result.GetExpandedUriStr())
      src_uri_names_container = name_expansion_result.NamesContainer()
      src_uri_expands_to_multi = name_expansion_result.NamesContainer()
      have_multiple_srcs = name_expansion_result.IsMultiSrcRequest()
      have_existing_dest_subdir = (
          name_expansion_result.HaveExistingDstContainer())

      if src_uri.names_provider():
        raise CommandException(
            'The %s command does not allow provider-only source URIs (%s)' %
            (cmd_name, src_uri))
      if have_multiple_srcs:
        self._InsistDstUriNamesContainer(exp_dst_uri,
                                         have_existing_dst_container,
                                         cmd_name)

      if self.perform_mv:
        # Disallow files as source arguments to protect users from deleting
        # data off the local disk. Note that we can't simply set FILE_URIS_OK
        # to False in command_spec because we *do* allow a file URI for the dest
        # URI. (We allow users to move data out of the cloud to the local disk,
        # but we disallow commands that would delete data off the local disk,
        # and instead require the user to delete data separately, using local
        # commands/tools.)
        if src_uri.is_file_uri():
          raise CommandException('The mv command disallows files as source '
                                 'arguments.\nDid you mean to use a gs:// URI? '
                                 'If you meant to use a file as a source, you\n'
                                 'might consider using the "cp" command '
                                 'instead.')
        if name_expansion_result.NamesContainer():
          # Use recursion_requested when performing name expansion for the
          # directory mv case so we can determine if any of the source URIs are
          # directories (and then use cp -R and rm -R to perform the move, to
          # match the behavior of Unix mv (which when moving a directory moves
          # all the contained files).
          self.recursion_requested = True
          # Disallow wildcard src URIs when moving directories, as supporting it
          # would make the name transformation too complex and would also be
          # dangerous (e.g., someone could accidentally move many objects to the
          # wrong name, or accidentally overwrite many objects).
          if ContainsWildcard(src_uri):
            raise CommandException('The mv command disallows naming source '
                                   'directories using wildcards')

      if (exp_dst_uri.is_file_uri()
          and not os.path.exists(exp_dst_uri.object_name)
          and have_multiple_srcs):
        os.makedirs(exp_dst_uri.object_name)

      dst_uri = self._ConstructDstUri(src_uri, exp_src_uri,
                                      src_uri_names_container,
                                      src_uri_expands_to_multi,
                                      have_multiple_srcs, exp_dst_uri,
                                      have_existing_dest_subdir)
      dst_uri = self._FixWindowsNaming(src_uri, dst_uri)

      self._CheckForDirFileConflict(exp_src_uri, dst_uri)
      if self._SrcDstSame(exp_src_uri, dst_uri):
        raise CommandException('%s: "%s" and "%s" are the same file - '
                               'abort.' % (cmd_name, exp_src_uri, dst_uri))

      (elapsed_time, bytes_transferred) = self._PerformCopy(exp_src_uri,
                                                            dst_uri)
      if self.perform_mv:
        if not self.quiet:
          self.THREADED_LOGGER.info('Removing %s...', exp_src_uri)
        exp_src_uri.delete_key(validate=False, headers=self.headers)
      stats_lock.acquire()
      self.total_elapsed_time += elapsed_time
      self.total_bytes_transferred += bytes_transferred
      stats_lock.release()

    # Start of RunCommand code.
    self._ParseArgs()

    self.total_elapsed_time = self.total_bytes_transferred = 0
    if self.args[-1] == '-' or self.args[-1] == 'file://-':
      self._HandleStreamingDownload()
      return

    (exp_dst_uri, have_existing_dst_container) = self._ExpandDstUri(
         self.args[-1])
    name_expansion_iterator = NameExpansionIterator(
        self.command_name, self.proj_id_handler, self.headers, self.debug,
        self.bucket_storage_uri_class, self.args[0:len(self.args)-1],
        self.recursion_requested or self.perform_mv,
        have_existing_dst_container)

    # Use a lock to ensure accurate statistics in the face of
    # multi-threading/multi-processing.
    stats_lock = threading.Lock()

    # Tracks if any copies failed.
    self.copy_failure_count = 0

    # Start the clock.
    start_time = time.time()

    # Tuple of attributes to share/manage across multiple processes in
    # parallel (-m) mode.
    shared_attrs = ('copy_failure_count', 'total_bytes_transferred')

    # Perform copy requests in parallel (-m) mode, if requested, using
    # configured number of parallel processes and threads. Otherwise,
    # perform requests with sequential function calls in current process.
    self.Apply(_CopyFunc, name_expansion_iterator, _CopyExceptionHandler,
               shared_attrs)
    if self.debug:
      print 'total_bytes_transferred:' + str(self.total_bytes_transferred)

    end_time = time.time()
    self.total_elapsed_time = end_time - start_time

    if self.debug == 3:
      # Note that this only counts the actual GET and PUT bytes for the copy
      # - not any transfers for doing wildcard expansion, the initial HEAD
      # request boto performs when doing a bucket.get_key() operation, etc.
      if self.total_bytes_transferred != 0:
        self.THREADED_LOGGER.info(
            'Total bytes copied=%d, total elapsed time=%5.3f secs (%sps)',
                self.total_bytes_transferred, self.total_elapsed_time,
                MakeHumanReadable(float(self.total_bytes_transferred) /
                                  float(self.total_elapsed_time)))
    if self.copy_failure_count:
      plural_str = ''
      if self.copy_failure_count > 1:
        plural_str = 's'
      raise CommandException('%d file%s/object%s could not be transferred.' % (
                             self.copy_failure_count, plural_str, plural_str))

  # Test specification. See definition of test_steps in base class for
  # details on how to populate these fields.
  test_steps = [
    # (test name, cmd line, ret code, (result_file, expect_file))
    ('upload', 'gsutil cp $F1 gs://$B1/$O1', 0, None),
    ('download', 'gsutil cp gs://$B1/$O1 $F9', 0, ('$F9', '$F1')),
    ('stream upload', 'cat $F1 | gsutil cp - gs://$B1/$O1', 0, None),
    ('check stream upload', 'gsutil cp gs://$B1/$O1 $F9', 0, ('$F9', '$F1')),
    # Clean up if we got interrupted.
    ('remove test files',
     'rm -f test.mp3 test_mp3.ct test.gif test_gif.ct test.foo',
      0, None),
    ('setup mp3 file', 'cp gslib/test_data/test.mp3 test.mp3', 0, None),
    ('setup mp3 CT', 'echo audio/mpeg >test_mp3.ct', 0, None),
    ('setup gif file', 'cp gslib/test_data/test.gif test.gif', 0, None),
    ('setup gif CT', 'echo image/gif >test_gif.ct', 0, None),
    # TODO: we don't need test.app and test.bin anymore if
    # USE_MAGICFILE=True. Implement a way to test both with and without using
    # magic file.
    #('setup app file', 'echo application/octet-stream >test.app', 0, None),
    ('setup foo file', 'echo foo/bar >test.foo', 0, None),
    ('upload mp3', 'gsutil cp test.mp3 gs://$B1/$O1', 0, None),
    ('verify mp3',
     'gsutil ls -L gs://$B1/$O1 | grep Content-Type | cut -f3 >$F1',
     0, ('$F1', 'test_mp3.ct')),
    ('upload gif', 'gsutil cp test.gif gs://$B1/$O1', 0, None),
    ('verify gif',
     'gsutil ls -L gs://$B1/$O1 | grep Content-Type | cut -f3 >$F1',
     0, ('$F1', 'test_gif.ct')),
    # TODO: The commented-out /noCT test below fails with USE_MAGICFILE=True.
    ('upload mp3/noCT',
     'gsutil -h "Content-Type:" cp test.mp3 gs://$B1/$O1', 0, None),
    ('verify mp3/noCT',
     'gsutil ls -L gs://$B1/$O1 | grep Content-Type | cut -f3 >$F1',
     0, ('$F1', 'test_mp3.ct')),
    ('upload gif/noCT',
     'gsutil -h "Content-Type:" cp test.gif gs://$B1/$O1', 0, None),
    ('verify gif/noCT',
     'gsutil ls -L gs://$B1/$O1 | grep Content-Type | cut -f3 >$F1',
     0, ('$F1', 'test_gif.ct')),
    #('upload foo/noCT', 'gsutil -h "Content-Type:" cp test.foo gs://$B1/$O1',
    # 0, None),
    #('verify foo/noCT',
    # 'gsutil ls -L gs://$B1/$O1 | grep Content-Type | cut -f3 >$F1',
    # 0, ('$F1', 'test_bin.ct')),
    ('upload mp3/-h gif',
     'gsutil -h "Content-Type:image/gif" cp test.mp3 gs://$B1/$O1', 0, None),
    ('verify mp3/-h gif',
     'gsutil ls -L gs://$B1/$O1 | grep Content-Type | cut -f3 >$F1',
     0, ('$F1', 'test_gif.ct')),
    ('upload gif/-h gif',
     'gsutil -h "Content-Type:image/gif" cp test.gif gs://$B1/$O1', 0, None),
    ('verify gif/-h gif',
     'gsutil ls -L gs://$B1/$O1 | grep Content-Type | cut -f3 >$F1',
     0, ('$F1', 'test_gif.ct')),
    ('upload foo/-h gif',
     'gsutil -h "Content-Type: image/gif" cp test.foo gs://$B1/$O1', 0, None),
    ('verify foo/-h gif',
     'gsutil ls -L gs://$B1/$O1 | grep Content-Type | cut -f3 >$F1',
     0, ('$F1', 'test_gif.ct')),
    ('remove test files',
     'rm -f test.mp3 test_mp3.ct test.gif test_gif.ct test.foo', 0, None),
  ]

  def _ParseArgs(self):
    self.perform_mv = False
    self.exclude_symlinks = False
    self.quiet = False
    # self.recursion_requested initialized in command.py (so can be checked
    # in parent class for all commands).
    if self.sub_opts:
      for o, unused_a in self.sub_opts:
        if o == '-e':
          self.exclude_symlinks = True
        elif o == '-M':
          # Note that we signal to the cp command to perform a move (copy
          # followed by remove) and use directory-move naming rules by passing
          # the undocumented (for internal use) -M option when running the cp
          # command from mv.py.
          self.perform_mv = True
        elif o == '-q':
          self.quiet = True
        elif o == '-r' or o == '-R':
          self.recursion_requested = True

  def _HandleStreamingDownload(self):
    # Destination is <STDOUT>. Manipulate sys.stdout so as to redirect all
    # debug messages to <STDERR>.
    stdout_fp = sys.stdout
    sys.stdout = sys.stderr
    did_some_work = False
    for uri_str in self.args[0:len(self.args)-1]:
      for uri in self.WildcardIterator(uri_str).IterUris():
        if not uri.names_object():
          raise CommandException('Destination Stream requires that '
                                 'source URI %s should represent an object!')
        did_some_work = True
        key = uri.get_key(False, self.headers)
        (elapsed_time, bytes_transferred) = self._PerformDownloadToStream(
            key, uri, stdout_fp, self.headers)
        self.total_elapsed_time += elapsed_time
        self.total_bytes_transferred += bytes_transferred
    if not did_some_work:
      raise CommandException('No URIs matched')
    if self.debug == 3:
      if self.total_bytes_transferred != 0:
        self.THREADED_LOGGER.info(
            'Total bytes copied=%d, total elapsed time=%5.3f secs (%sps)',
                self.total_bytes_transferred, self.total_elapsed_time,
                 MakeHumanReadable(float(self.total_bytes_transferred) /
                                   float(self.total_elapsed_time)))

  def _SrcDstSame(self, src_uri, dst_uri):
    """Checks if src_uri and dst_uri represent the same object or file.

    We don't handle anything about hard or symbolic links.

    Args:
      src_uri: Source StorageUri.
      dst_uri: Destination StorageUri.

    Returns:
      Bool indicator.
    """
    if src_uri.is_file_uri() and dst_uri.is_file_uri():
      # Translate a/b/./c to a/b/c, so src=dst comparison below works.
      new_src_path = re.sub('%s+\.%s+' % (os.sep, os.sep), os.sep,
                            src_uri.object_name)
      new_src_path = re.sub('^.%s+' % os.sep, '', new_src_path)
      new_dst_path = re.sub('%s+\.%s+' % (os.sep, os.sep), os.sep,
                            dst_uri.object_name)
      new_dst_path = re.sub('^.%s+' % os.sep, '', new_dst_path)
      return (src_uri.clone_replace_name(new_src_path).uri ==
              dst_uri.clone_replace_name(new_dst_path).uri)
    else:
      # TODO: There are cases where copying from src to dst with the same
      # object makes sense, namely, for setting metadata on an object. At some
      # point if we offer a command to do so, add a parameter to the current
      # function to allow this check to be overridden. Note that we want this
      # check to prevent a user from blowing away data using the mv command,
      # with a command like:
      #   gsutil mv gs://bucket/abc/* gs://bucket/abc
      return src_uri.uri == dst_uri.uri

  def _ShouldTreatDstUriAsBucketSubDir(self, have_multiple_srcs, dst_uri,
                                       have_existing_dest_subdir):
    """
    Checks whether dst_uri should be treated as a bucket "sub-directory". The
    decision about whether something constitutes a bucket "sub-directory"
    depends on whether there are multiple sources in this request and whether
    there is an existing bucket subdirectory. For example, when running the
    command:
      gsutil cp file gs://bucket/abc
    if there's no existing gs://bucket/abc bucket subdirectory we should copy
    file to the object gs://bucket/abc. In contrast, if
    there's an existing gs://bucket/abc bucket subdirectory we should copy
    file to gs://bucket/abc/file. And regardless of whether gs://bucket/abc
    exists, when running the command:
      gsutil cp file1 file2 gs://bucket/abc
    we should copy file1 to gs://bucket/abc/file1 (and similarly for file2).

    Note that we don't disallow naming a bucket "sub-directory" where there's
    already an object at that URI. For example it's legitimate (albeit
    confusing) to have an object called gs://bucket/dir and
    then run the command
    gsutil cp file1 file2 gs://bucket/dir
    Doing so will end up with objects gs://bucket/dir, gs://bucket/dir/file1,
    and gs://bucket/dir/file2.

    Args:
      have_multiple_srcs: Bool indicator of whether this is a multi-source
          operation.
      dst_uri: StorageUri to check.
      have_existing_dest_subdir: bool indicator whether dest is an existing
        subdirectory.

    Returns:
      bool indicator.
    """
    return ((have_multiple_srcs and dst_uri.is_cloud_uri())
            or (have_existing_dest_subdir))

  def _ShouldTreatDstUriAsSingleton(self, have_multiple_srcs,
                                    have_existing_dest_subdir, dst_uri):
    """
    Checks that dst_uri names a singleton (file or object) after
    dir/wildcard expansion. The decision is more nuanced than simply
    dst_uri.names_singleton()) because of the possibility that an object path
    might name a bucket sub-directory.

    Args:
      have_multiple_srcs: Bool indicator of whether this is a multi-source
          operation.
      have_existing_dest_subdir: bool indicator whether dest is an existing
        subdirectory.
      dst_uri: StorageUri to check.

    Returns:
      bool indicator.
    """
    if have_multiple_srcs:
      # Only a file meets the criteria in this case.
      return dst_uri.names_file()
    return not have_existing_dest_subdir and dst_uri.names_singleton()


def _GetPathBeforeFinalDir(uri):
  """
  Returns the part of the path before the final directory component for the
  given URI, handling cases for file system directories, bucket, and bucket
  subdirectories. Example: for gs://bucket/dir/ we'll return 'gs://bucket',
  and for file://dir we'll return file://

  Args:
    uri: StorageUri.

  Returns:
    String name of above-described path, sans final path separator.
  """
  sep = uri.delim
  assert not uri.names_file()
  if uri.names_directory():
    past_scheme = uri.uri[len('file://'):]
    if past_scheme.find(sep) == -1:
      return 'file://'
    else:
      return 'file://%s' % past_scheme.rstrip(sep).rpartition(sep)[0]
  if uri.names_bucket():
    return '%s://' % uri.scheme
  # Else it names a bucket subdir.
  return uri.uri.rstrip(sep).rpartition(sep)[0]

def _hash_filename(filename):
  """
  Apply a hash function (SHA1) to shorten the passed file name. The spec
  for the hashed file name is as follows:

      TRACKER_<hash>_<trailing>

  where hash is a SHA1 hash on the original file name and trailing is
  the last 16 chars from the original file name. Max file name lengths
  vary by operating system so the goal of this function is to ensure
  the hashed version takes fewer than 100 characters.

  Args:
    filename: file name to be hashed.

  Returns:
    shorter, hashed version of passed file name
  """
  m = hashlib.sha1(filename.encode('utf-8'))
  hashed_name = ("TRACKER_" + m.hexdigest() + '.' + filename[-16:])
  return hashed_name
