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
import ctypes
import gzip
import mimetypes
import os
import platform
import re
import sys
import tempfile
import threading
import time

from boto.gs.resumable_upload_handler import ResumableUploadHandler
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
from gslib.exception import ProjectIdException
from gslib import wildcard_iterator
from gslib.project_id import ProjectIdHandler
from gslib.util import MakeHumanReadable
from gslib.util import NO_MAX
from gslib.util import ONE_MB
from gslib.wildcard_iterator import ContainsWildcard

class CpCommand(Command):
  """Implementation of gsutil cp command."""

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
    SUPPORTED_SUB_ARGS : 'a:eprRtz:',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : True,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 0,
    # True if must configure gsutil before running command.
    CONFIG_REQUIRED : True,
  }
  
  def check_final_md5(self, key, file_name):
    """
    Checks that etag from server agrees with md5 computed after the
    download completes. This is important, since the download could
    have spanned a number of hours and multiple processes (e.g.,
    gsutil runs), and the user could change some of the file and not
    realize they have inconsistent data.
    """
    # Open file in binary mode to avoid surprises in Windows.
    fp = open(file_name, 'rb')
    try:
      file_md5 = key.compute_md5(fp)[0]
    finally:
      fp.close()
    obj_md5 = key.etag.strip('"\'')
    if self.debug:
      print 'Checking file md5 against etag. (%s/%s)' % (file_md5, obj_md5)
    if file_md5 != obj_md5:
      # Checksums don't match - remove file and raise exception.
      os.unlink(file_name)
      raise CommandException(
        'File changed during download: md5 signature doesn\'t match '
        'etag (incorrect downloaded file deleted)')

  def _CheckForDirFileConflict(self, src_uri, dst_path):
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
      CommandException: if errors encountered.
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

  def _GetTransferHandlers(self, uri, key, file_size, upload):
    """
    Selects upload/download and callback handlers.

    We use a callback handler that shows a simple textual progress indicator
    if file_size is above the configurable threshold.

    We use a resumable transfer handler if file_size is >= the configurable
    threshold and resumable transfers are supported by the given provider.
    boto supports resumable downloads for all providers, but resumable
    uploads are currently only supported by GS.
    """
    config = boto.config
    resumable_threshold = config.getint('GSUtil', 'resumable_threshold', ONE_MB)
    if file_size >= resumable_threshold:
      cb = self._FileCopyCallbackHandler(upload).call
      num_cb = int(file_size / ONE_MB)
      resumable_tracker_dir = config.get(
          'GSUtil', 'resumable_tracker_dir',
          os.path.expanduser('~' + os.sep + '.gsutil'))
      if not os.path.exists(resumable_tracker_dir):
        os.makedirs(resumable_tracker_dir)
      if upload:
        # Encode the src bucket and key into the tracker file name.
        res_tracker_file_name = (
            re.sub('[/\\\\]', '_', 'resumable_upload__%s__%s.url' %
                   (key.bucket.name, key.name)))
      else:
        # Encode the fully-qualified src file name into the tracker file name.
        res_tracker_file_name = (
            re.sub('[/\\\\]', '_', 'resumable_download__%s.etag' %
                   (os.path.realpath(uri.object_name))))
      tracker_file = '%s%s%s' % (resumable_tracker_dir, os.sep,
                                 res_tracker_file_name)
      if upload:
        if uri.scheme == 'gs':
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

  # We pass the headers explicitly to this call instead of using self.headers
  # so we can set different metadata (like MIME type) for each object.
  def _CopyObjToObjSameProvider(self,  src_key, src_uri, dst_uri, headers):
    # Do Object -> object copy within same provider (uses
    # x-<provider>-copy-source metadata HTTP header to request copying at the
    # server).
    src_bucket = src_uri.get_bucket(False, headers)
    dst_bucket = dst_uri.get_bucket(False, headers)
    preserve_acl = False
    if self.sub_opts:
      for o, a in self.sub_opts:
        if o == '-p':
          preserve_acl = True
    start_time = time.time()
    dst_bucket.copy_key(dst_uri.object_name, src_bucket.name,
                        src_uri.object_name, headers, preserve_acl=preserve_acl)
    end_time = time.time()
    return (end_time - start_time, src_key.size)

  def _CheckFreeSpace(self, path):
    """Return path/drive free space (in bytes)."""
    if platform.system() == 'Windows':
      free_bytes = ctypes.c_ulonglong(0)
      ctypes.windll.kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(path), None,
                                                 None,
                                                 ctypes.pointer(free_bytes))
      return free_bytes.value
    else:
      (_, f_frsize, _, _, f_bavail, _, _, _, _, _) = os.statvfs(path)
      return f_frsize * f_bavail

  def _PerformResumableUploadIfApplies(self, fp, dst_uri, canned_acl):
    """
    Performs resumable upload if supported by provider and file is above
    threshold, else performs non-resumable upload.

    Returns (elapsed_time, bytes_transferred).
    """
    start_time = time.time()
    file_size = os.path.getsize(fp.name)
    dst_key = dst_uri.new_key(False, self.headers)
    (cb, num_cb, res_upload_handler) = self._GetTransferHandlers(
        dst_uri, dst_key, file_size, True)
    if dst_uri.scheme == 'gs':
      # Resumable upload protocol is Google Cloud Storage-specific.
      dst_key.set_contents_from_file(fp, self.headers, policy=canned_acl,
                                     cb=cb, num_cb=num_cb,
                                     res_upload_handler=res_upload_handler)
    else:
      dst_key.set_contents_from_file(fp, self.headers, policy=canned_acl,
                                     cb=cb, num_cb=num_cb)
    if res_upload_handler:
      bytes_transferred = file_size - res_upload_handler.upload_start_point
    else:
      bytes_transferred = file_size
    end_time = time.time()
    return (end_time - start_time, bytes_transferred)

  def _PerformStreamUpload(self, fp, dst_uri, canned_acl=None):
    """
    Performs Stream upload to cloud.

    Args:
      fp: the file whose contents to upload
      dst_uri: destination StorageUri.
      canned_acl: optional canned ACL to set on the object

    Returns (elapsed_time, bytes_transferred).
    """
    start_time = time.time()
    dst_key = dst_uri.new_key(False, self.headers)

    cb = self._StreamCopyCallbackHandler().call
    dst_key.set_contents_from_stream(fp, self.headers, policy=canned_acl, cb=cb)
    try:
        bytes_transferred = fp.tell()
    except:
        bytes_transferred = 0;

    end_time = time.time()
    return (end_time - start_time, bytes_transferred)

  def _UploadFileToObject(self, src_key, src_uri, dst_uri):
    """Helper method for uploading a local file to an object.

    Args:
      src_key: source StorageUri. Must be a file URI.
      src_uri: source StorageUri.
      dst_uri: destination StorageUri.

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
          mimetype_tuple = mimetypes.guess_type(src_uri.object_name)
          mime_type = mimetype_tuple[0]
          content_encoding = mimetype_tuple[1]
          if mime_type:
            self.headers['Content-Type'] = mime_type
            print '\t[Setting Content-Type=%s]' % mime_type
          else:
            print '\t[Unknown content type -> using application/octet stream]'
          if content_encoding:
            self.headers['Content-Encoding'] = content_encoding
        elif o == '-z':
          gzip_exts = a.split(',')
    fname_parts = src_uri.object_name.split('.')
    if len(fname_parts) > 1 and fname_parts[-1] in gzip_exts:
      if self.debug:
        print 'Compressing %s (to tmp)...' % src_key
      gzip_tmp = tempfile.mkstemp()
      gzip_path = gzip_tmp[1]
      # Check for temp space. Assume the compressed object is at most 2x
      # the size of the object (normally should compress to smaller than
      # the object)
      if self._CheckFreeSpace(gzip_path) < 2*int(os.path.getsize(src_key.name)):
        raise CommandException('Inadequate temp space available to compress '
                               '%s' % src_key.name)
      gzip_fp = gzip.open(gzip_path, 'wb')
      try:
        gzip_fp.writelines(src_key.fp)
      finally:
        gzip_fp.close()
      self.headers['Content-Encoding'] = 'gzip'
      gzip_fp = open(gzip_path, 'rb')
      try:
        (elapsed_time, bytes_transferred) = (
            self._PerformResumableUploadIfApplies(gzip_fp, dst_uri,
                                                  canned_acl))
      finally:
        gzip_fp.close()
      os.unlink(gzip_path)
    elif (src_key.is_stream() and
          dst_uri.get_provider().supports_chunked_transfer()):
      (elapsed_time, bytes_transferred) = self._PerformStreamUpload(
          src_key.fp, dst_uri, canned_acl)
    else:
      if src_key.is_stream():
        # For Providers that doesn't support chunked Transfers
        tmp = tempfile.NamedTemporaryFile()
        file_uri = self.StorageUri('file://%s' % tmp.name)
        try:
          file_uri.new_key(False, self.headers).set_contents_from_file(
              src_key.fp, self.headers)
          src_key = file_uri.get_key()
        finally:
          file_uri.close()
      try:
        (elapsed_time, bytes_transferred) = (
            self._PerformResumableUploadIfApplies(src_key.fp, dst_uri,
                                                  canned_acl))
      finally:
        if src_key.is_stream():
          tmp.close()
        else:
          src_key.close()

    return (elapsed_time, bytes_transferred)

  def _DownloadObjectToFile(self, src_key, src_uri, dst_uri):
    (cb, num_cb, res_download_handler) = self._GetTransferHandlers(
        src_uri, src_key, src_key.size, False)
    file_name = dst_uri.object_name
    dir_name = os.path.dirname(file_name)
    if dir_name and not os.path.exists(dir_name):
      os.makedirs(dir_name)
    # For gzipped objects not named *.gz download to a temp file and unzip.
    if (hasattr(src_key, 'content_encoding') and
        src_key.content_encoding == 'gzip' and
        not file_name.endswith('.gz')):
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
      src_key.get_contents_to_file(fp, self.headers, cb=cb, num_cb=num_cb,
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

    # Verify downloaded file checksum matches source object's checksum.
    self.check_final_md5(src_key, download_file_name)

    if res_download_handler:
      bytes_transferred = (
          src_key.size - res_download_handler.download_start_point)
    else:
      bytes_transferred = src_key.size
    if need_to_unzip:
      if self.debug:
        sys.stderr.write('Uncompressing tmp to %s...\n' % file_name)
      # Downloaded gzipped file to a filename w/o .gz extension, so unzip.
      f_in = gzip.open(download_file_name, 'rb')
      f_out = open(file_name, 'wb')
      try:
        f_out.writelines(f_in)
      finally:
        f_out.close();
        f_in.close();
        os.unlink(download_file_name)
    return (end_time - start_time, bytes_transferred)

  def _PerformDownloadToStream(self, src_key, src_uri, str_fp):
    (cb, num_cb, res_download_handler) = self._GetTransferHandlers(
                                src_uri, src_key, src_key.size, False)
    start_time = time.time()
    src_key.get_contents_to_file(str_fp, self.headers, cb=cb, num_cb=num_cb)
    end_time = time.time()
    bytes_transferred = src_key.size
    end_time = time.time()
    return (end_time - start_time, bytes_transferred)

  def _CopyFileToFile(self, src_key, dst_uri):
    dst_key = dst_uri.new_key(False, self.headers)
    start_time = time.time()
    dst_key.set_contents_from_file(src_key.fp, self.headers)
    end_time = time.time()
    return (end_time - start_time, os.path.getsize(src_key.fp.name))

  def _CopyObjToObjDiffProvider(self, src_key, src_uri, dst_uri):
    # If destination is GS, We can avoid the local copying through a local file
    # as GS supports chunked transfer.
    if dst_uri.scheme == 'gs':
      canned_acls = None
      if self.sub_opts:
        for o, a in self.sub_opts:
          if o == '-a':
            canned_acls = dst_uri.canned_acls()
            if a not in canned_acls:
              raise CommandException('Invalid canned ACL "%s".' % a)
            canned_acl = a
          elif o == '-p':
            raise NotImplementedError(
              'Cross-provider ACL-preserving cp not supported')

          elif o == '-t':
            mimetype_tuple = mimetypes.guess_type(src_uri.object_name)
            mime_type = mimetype_tuple[0]
            content_encoding = mimetype_tuple[1]
            if mime_type:
              self.headers['Content-Type'] = mime_type
              print '\t[Setting Content-Type=%s]' % mime_type
            else:
              print '\t[Unknown content type -> using application/octet stream]'
            if content_encoding:
              self.headers['Content-Encoding'] = content_encoding

      # TODO: This _PerformStreamUpload call passes in a Key for fp
      # param, relying on Python "duck typing" (the fact that the lower-level
      # methods that expect an fp only happen to call fp methods that are
      # defined and semantically equivalent to those defined on src_key). This
      # should be replaced by a class that wraps an fp interface around the
      # Key, throwing 'not implemented' for methods (like seek) that aren't
      # implemented by non-file Keys.
      return self._PerformStreamUpload(src_key, dst_uri, canned_acls)

    # If destination is not GS, We implement object copy through a local
    # temp file. Note that a downside of this approach is that killing the
    # gsutil process partway through and then restarting will always repeat the
    # download and upload, because the temp file name is different for each
    # incarnation. (If however you just leave the process running and failures
    # happen along the way, they will continue to restart and make progress
    # as long as not too many failures happen in a row with no progress.)
    tmp = tempfile.NamedTemporaryFile()
    if self._CheckFreeSpace(tempfile.tempdir) < src_key.size:
      raise CommandException('Inadequate temp space available to perform the '
                             'requested copy')
    start_time = time.time()
    file_uri = self.StorageUri('file://%s' % tmp.name)
    try:
      self._DownloadObjectToFile(src_key, src_uri, file_uri)
      self._UploadFileToObject(file_uri.get_key(), file_uri, dst_uri)
    finally:
      tmp.close()
    end_time = time.time()
    return (end_time - start_time, src_key.size)

  def _PerformCopy(self, src_uri, dst_uri):
    """Helper method for CopyObjsCommand.

    Args:
      src_uri: source StorageUri.
      dst_uri: destination StorageUri.

    Returns:
      (elapsed_time, bytes_transferred) excluding overhead like initial HEAD.

    Raises:
      CommandException: if errors encountered.
    """
    # Make a copy of the input headers each time so we can set a different
    # MIME type for each object.
    if self.headers:
      headers = self.headers.copy()
    else:
      headers = {}

    src_key = src_uri.get_key(False, headers)
    if not src_key:
      raise CommandException('"%s" does not exist.' % src_uri)

    # Separately handle cases to avoid extra file and network copying of
    # potentially very large files/objects.

    if src_uri.is_cloud_uri() and dst_uri.is_cloud_uri():
      if src_uri.scheme == dst_uri.scheme:
        return self._CopyObjToObjSameProvider(src_key, src_uri, dst_uri,
                                              headers)
      else:
        return self._CopyObjToObjDiffProvider(src_key, src_uri, dst_uri)
    elif src_uri.is_file_uri() and dst_uri.is_cloud_uri():
      return self._UploadFileToObject(src_key, src_uri, dst_uri)
    elif src_uri.is_cloud_uri() and dst_uri.is_file_uri():
      return self._DownloadObjectToFile(src_key, src_uri, dst_uri)
    elif src_uri.is_file_uri() and dst_uri.is_file_uri():
      return self._CopyFileToFile(src_key, dst_uri)
    else:
      raise CommandException('Unexpected src/dest case')

  def _ExpandWildcardsAndContainers(self, uri_strs):
    """Expands URI wildcarding, object-less bucket names, and directory names.

    Examples:
      Calling with uri_strs='gs://bucket' will enumerate all contained objects.
      Calling with uri_strs='file:///tmp' will enumerate all files under /tmp
         (or under any subdirectory).
      The previous example is equivalent to uri_strs='file:///tmp/*'
         and to uri_strs='file:///tmp/**'

    Args:
      uri_strs: URI strings needing expansion

    Returns:
      dict mapping StorageUri -> list of StorageUri, for each input uri_str.

      We build a dict of the expansion instead of using a generator to
      iterate incrementally because caller needs to know count before
      iterating and performing copy operations (in order to determine if
      this is a multi-source copy request). That limits the scalability of
      wildcard iteration, since the entire list needs to fit in memory.
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

    should_recurse = False
    if self.sub_opts:
      for o, unused_a in self.sub_opts:
        if o == '-r' or o == '-R':
          should_recurse = True

    # Step 1.
    uris_to_expand = []
    for uri_str in uri_strs:
      uri = self.StorageUri(uri_str)
      if uri.is_file_uri() and ContainsWildcard(uri_str):
        uris_to_expand.extend(list(self.CmdWildcardIterator(uri)))
      elif uri.is_file_uri() and uri.is_stream():
        # Special case for Streams
        uri_dict = {}
        uri_dict[uri] = [uri]
        return uri_dict
      else:
        uris_to_expand.append(uri)

    # Step 2.
    result = {}
    for uri in uris_to_expand:
      if uri.names_container():
        if not should_recurse:
          if uri.is_file_uri():
            desc = 'directory'
          else:
            desc = 'bucket'
          print 'Omitting %s "%s".' % (desc, uri.uri)
          result[uri] = []
          continue
        if uri.is_file_uri():
          # dir -> convert to implicit recursive wildcard.
          uri_to_iter = '%s/**' % uri.uri
        else:
          # bucket -> convert to implicit wildcard.
          uri_to_iter = uri.clone_replace_name('*')
      else:
        uri_to_iter = uri
      result[uri] = list(self.CmdWildcardIterator(uri_to_iter))
    return result

  def _ErrorCheckCopyRequest(self, src_uri_expansion, dst_uri_str):
    """Checks copy request for problems, and builds needed base_dst_uri.

    base_dst_uri is the base uri to be used if it's a multi-object copy, e.g.,
    the URI for the destination bucket. The actual dst_uri can then be
    constructed from the src_uri and this base_dst_uri.

    Args:
      src_uri_expansion: result from ExpandWildcardsAndContainers call.
      dst_uri_str: string representation of destination StorageUri.

    Returns:
      (base_dst_uri to use for copy, bool indicator of multi-source request).

    Raises:
      CommandException: if errors found.
    """
    for src_uri in src_uri_expansion:
      if src_uri.is_cloud_uri() and not src_uri.bucket_name:
        raise CommandException('Provider-only src_uri (%s)')

    if ContainsWildcard(dst_uri_str):
      matches = list(self.CmdWildcardIterator(dst_uri_str))
      if len(matches) > 1:
        raise CommandException('Destination (%s) matches more than 1 URI' %
                               dst_uri_str)
      base_dst_uri = matches[0]
    else:
      base_dst_uri = self.StorageUri(dst_uri_str)

    # Make sure entire expansion didn't result in nothing to copy. This can
    # happen if user request copying a directory w/o -r option, for example.
    have_work = False
    for v in src_uri_expansion.values():
      if v:
        have_work = True
        break
    if not have_work:
      raise CommandException('Nothing to copy')

    # If multi-object copy request ensure base_dst_uri names a container.
    multi_src_request = (len(src_uri_expansion) > 1 or
                         len(src_uri_expansion.values()[0]) > 1)
    if multi_src_request:
      self.InsistUriNamesContainer(base_dst_uri, self.command_name)

    # Ensure no src/dest pairs would overwrite src. Note that this is
    # more restrictive than the UNIX 'cp' command (which would, for example,
    # allow "mv * dir" and just skip the implied mv dir dir). We disallow such
    # partial completion operations in cloud copies because they are risky.
    for src_uri in iter(src_uri_expansion):
      for exp_src_uri in src_uri_expansion[src_uri]:
        new_dst_uri = self._ConstructDstUri(src_uri, exp_src_uri, base_dst_uri)
        if self._SrcDstSame(exp_src_uri, new_dst_uri):
          raise CommandException('cp: "%s" and "%s" are the same object - '
                                 'abort.' % (exp_src_uri.uri, new_dst_uri.uri))

    return (base_dst_uri, multi_src_request)

  def _HandleMultiSrcCopyRequst(self, src_uri_expansion, dst_uri):
    """
    Rewrites dst_uri and creates dest dir as needed, if this is a
    multi-source copy.

    Args:
      src_uri_expansion: result from ExpandWildcardsAndContainers call.
      dst_uri: uri constructed by ErrorCheckCopyRequest() call.

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

  def _SrcDstSame(self, src_uri, dst_uri):
    """Checks if src_uri and dst_uri represent same object.

    We don't handle anything about hard or symbolic links.

    Args:
      src_uri: source StorageUri.
      dst_uri: dest StorageUri.

    Returns:
      Bool indication.
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
      return src_uri.uri == dst_uri.uri

  def _ConstructDstUri(self, src_uri, exp_src_uri, base_dst_uri):
    """Constructs a destination URI for CopyObjsCommand.

    Args:
      src_uri: src_uri to be copied.
      exp_src_uri: single URI from wildcard expansion of src_uri.
      base_dst_uri: uri constructed by ErrorCheckCopyRequest() call.

    Returns:
      dst_uri to use for copy.

    Raises:
      CommandException if destination object name not specified for
      source and source is a stream.
    """
    if base_dst_uri.names_container():
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
        if exp_src_uri.is_file_uri() and exp_src_uri.is_stream():
          raise CommandException('Destination Object name needed if '
                            'source is stream')
        # src is a file or object, so use final component of src name.
        dst_key_name = os.path.basename(exp_src_uri.object_name)
      if base_dst_uri.is_file_uri():
        # dst names a directory, so append src obj name to dst obj name.
        dst_key_name = '%s%s%s' % (base_dst_uri.object_name, os.sep,
                                   dst_key_name)
        self._CheckForDirFileConflict(exp_src_uri, dst_key_name)
    else:
      # dest is an object or file: use dst obj name
      dst_key_name = base_dst_uri.object_name
    return base_dst_uri.clone_replace_name(dst_key_name)

  # Command entry point.
  def RunCommand(self):
    self.total_elapsed_time = self.total_bytes_transferred = 0
    if self.args[-1] == '-' or self.args[-1] == 'file://-':
      # Destination is <STDOUT>. Manipulate sys.stdout so as to redirect all
      # debug messages to <STDERR>.
      stdout_fp = sys.stdout
      sys.stdout = sys.stderr
      for uri_str in self.args[0:len(self.args)-1]:
        for uri in self.CmdWildcardIterator(uri_str):
          if not uri.object_name:
            raise CommandException('Destination Stream requires that '
                                   'source URI %s should represent an object!')
          key = uri.get_key(False, self.headers)
          (elapsed_time, bytes_transferred) = self._PerformDownloadToStream(
              key, uri, stdout_fp)
          self.total_elapsed_time += elapsed_time
          self.total_bytes_transferred += bytes_transferred
      if self.debug == 3:
        if self.total_bytes_transferred != 0:
          sys.stderr.write(
              'Total bytes copied=%d, total elapsed time=%5.3f secs (%sps)\n' %
                  (self.total_bytes_transferred, self.total_elapsed_time,
                   MakeHumanReadable(float(self.total_bytes_transferred) /
                                     float(self.total_elapsed_time))))
      return

    # Expand wildcards and containers in source StorageUris.
    src_uri_expansion = self._ExpandWildcardsAndContainers(
        self.args[0:len(self.args)-1])

    # Check for various problems and determine base_dst_uri based for request.
    (base_dst_uri, multi_src_request) = self._ErrorCheckCopyRequest(
        src_uri_expansion, self.args[-1])
    # Rewrite base_dst_uri and create dest dir as needed for multi-source copy.
    if multi_src_request:
      base_dst_uri = self._HandleMultiSrcCopyRequst(src_uri_expansion,
                                                    base_dst_uri)

    # Should symbolic links be skipped?
    if self.sub_opts:
      for o, unused_a in self.sub_opts:
        if o == '-e':
          self.ignore_symlinks = True

    # To ensure statistics are accurate with threads we need to use a lock.
    stats_lock = threading.Lock()

    # Used to track if any files failed to copy over.
    self.everything_copied_okay = True

    def _CopyExceptionHandler(e):
      """Simple exception handler to allow post-completion status."""
      self.THREADED_LOGGER.error(str(e))
      self.everything_copied_okay = False

    def _CopyFunc(src_uri, exp_src_uri):
      """Worker function for performing the actual copy."""
      if exp_src_uri.is_file_uri() and exp_src_uri.is_stream():
        sys.stderr.write("Copying from <STDIN>...\n")
      else:
        self.THREADED_LOGGER.info('Copying %s...', exp_src_uri)
      dst_uri = self._ConstructDstUri(src_uri, exp_src_uri, base_dst_uri)
      (elapsed_time, bytes_transferred) = self._PerformCopy(exp_src_uri,
                                                            dst_uri)
      stats_lock.acquire()
      self.total_elapsed_time += elapsed_time
      self.total_bytes_transferred += bytes_transferred
      stats_lock.release()

    
    # Start the clock.
    start_time = time.time()

    # Perform copy requests in parallel (-m) mode, if requested, using    
    # configured number of parallel processes and threads. Otherwise,
    # perform request with sequential function calls in current process.
    self.Apply(_CopyFunc, src_uri_expansion, _CopyExceptionHandler)

    end_time = time.time()
    self.total_elapsed_time = end_time - start_time

    if self.debug == 3:
      # Note that this only counts the actual GET and PUT bytes for the copy
      # - not any transfers for doing wildcard expansion, the initial HEAD
      # request boto performs when doing a bucket.get_key() operation, etc.
      if self.total_bytes_transferred != 0:
        sys.stderr.write(
            'Total bytes copied=%d, total elapsed time=%5.3f secs (%sps)\n' % (
                self.total_bytes_transferred, self.total_elapsed_time,
                MakeHumanReadable(float(self.total_bytes_transferred) /
                                  float(self.total_elapsed_time))))
    if not self.everything_copied_okay:
      raise CommandException('Some files could not be transferred.')
