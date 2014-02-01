# Copyright 2011 Google Inc. All Rights Reserved.
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
"""Implementation of Unix-like cp command for cloud storage providers."""

# Get the system logging module, not our local logging module.
from __future__ import absolute_import

import base64
import binascii
from collections import namedtuple
import copy
import csv
import datetime
import errno
import gzip
import hashlib
import json
import logging
import mimetypes
import os
import random
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import traceback

from boto import config
from boto.exception import ResumableUploadException
import crcmod
import gslib
from gslib.bucket_listing_ref import BucketListingRef
from gslib.bucket_listing_ref import BucketListingRefType
from gslib.cat_helper import CatHelper
from gslib.cloud_api import AccessDeniedException
from gslib.cloud_api import ArgumentException
from gslib.cloud_api import CloudApi
from gslib.cloud_api import NotFoundException
from gslib.cloud_api import PreconditionException
from gslib.cloud_api import ResumableDownloadException
from gslib.command import Command
from gslib.commands.compose import MAX_COMPONENT_COUNT
from gslib.commands.compose import MAX_COMPOSE_ARITY
from gslib.commands.config import DEFAULT_PARALLEL_COMPOSITE_UPLOAD_COMPONENT_SIZE
from gslib.commands.config import DEFAULT_PARALLEL_COMPOSITE_UPLOAD_THRESHOLD
from gslib.cp_helper import GetDownloadSerializationDict
from gslib.cp_helper import GetHashAlgs
from gslib.cp_helper import GetMD5FromETag
from gslib.cs_api_map import ApiSelector
from gslib.exception import CommandException
from gslib.file_part import FilePart
from gslib.name_expansion import NameExpansionIterator
from gslib.name_expansion import NameExpansionResult
from gslib.storage_url import ContainsWildcard
from gslib.storage_url import StorageUrlFromString
from gslib.translation_helper import AddS3MarkerAclToObjectMetadata
from gslib.translation_helper import CopyObjectMetadata
from gslib.translation_helper import DEFAULT_CONTENT_TYPE
from gslib.translation_helper import ObjectMetadataFromHeaders
from gslib.translation_helper import PreconditionsFromHeaders
from gslib.translation_helper import S3MarkerAclFromObjectMetadata
from gslib.util import CalculateMd5FromContents
from gslib.util import CreateLock
from gslib.util import CreateTrackerDirIfNeeded
from gslib.util import DEFAULT_FILE_BUFFER_SIZE
from gslib.util import GetCloudApiInstance
from gslib.util import GetFileSize
from gslib.util import GetStreamFromFileUrl
from gslib.util import HumanReadableToBytes
from gslib.util import IS_WINDOWS
from gslib.util import MakeHumanReadable
from gslib.util import NO_MAX
from gslib.util import TWO_MB
from gslib.util import UTF8

# pylint: disable=g-import-not-at-top
if IS_WINDOWS:
  import msvcrt
  from ctypes import c_int
  from ctypes import c_uint64
  from ctypes import c_char_p
  from ctypes import c_wchar_p
  from ctypes import windll
  from ctypes import POINTER
  from ctypes import WINFUNCTYPE
  from ctypes import WinError

PARALLEL_UPLOAD_TEMP_NAMESPACE = (
    u'/gsutil/tmp/parallel_composite_uploads/for_details_see/gsutil_help_cp/')

PARALLEL_UPLOAD_STATIC_SALT = u"""
PARALLEL_UPLOAD_SALT_TO_PREVENT_COLLISIONS.
The theory is that no user will have prepended this to the front of
one of their object names and then done an MD5 hash of the name, and
then prepended PARALLEL_UPLOAD_TEMP_NAMESPACE to the front of their object
name. Note that there will be no problems with object name length since we
hash the original name.
"""

# In order to prevent people from uploading thousands of tiny files in parallel
# (which, apart from being useless, is likely to cause them to be throttled
# for the compose calls), don't allow files smaller than this to use parallel
# composite uploads.
MIN_PARALLEL_COMPOSITE_FILE_SIZE = 20971520  # 20 MB

# When uploading a file, get the following fields in the response for
# filling in command output and manifests.
UPLOAD_RETURN_FIELDS = ['generation', 'md5Hash', 'size']

# For files >= this size, output a message indicating that we're running an
# operation on the file (like hashing or gzipping) so it does not appear to the
# user that the command is hanging.
MIN_SIZE_COMPUTE_LOGGING = 100*1024*1024  # 100 MB

SYNOPSIS_TEXT = """
<B>SYNOPSIS</B>
  gsutil cp [OPTION]... src_url dst_url
  gsutil cp [OPTION]... src_url... dst_url
  gsutil cp [OPTION]... -I dst_url
"""

DESCRIPTION_TEXT = """
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

  You can pass a list of URLs to copy on STDIN instead of as command line
  arguments by using the -I option. This allows you to use gsutil in a
  pipeline to copy files and objects as generated by a program, such as:

    some_program | gsutil -m cp -I gs://my_bucket

  The contents of STDIN can name files, cloud URLs, and wildcards of files
  and cloud URLs.
"""

NAME_CONSTRUCTION_TEXT = """
<B>HOW NAMES ARE CONSTRUCTED</B>
  The gsutil cp command strives to name objects in a way consistent with how
  Linux cp works, which causes names to be constructed in varying ways depending
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
"""

SUBDIRECTORIES_TEXT = """
<B>COPYING TO/FROM SUBDIRECTORIES; DISTRIBUTING TRANSFERS ACROSS MACHINES</B>
  You can use gsutil to copy to and from subdirectories by using a command
  like:

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

    gsutil -m cp -R gs://my_bucket/data/result_set_[0-3]* dir
    gsutil -m cp -R gs://my_bucket/data/result_set_[4-6]* dir
    gsutil -m cp -R gs://my_bucket/data/result_set_[7-9]* dir

  Note that dir could be a local directory on each machine, or it could
  be a directory mounted off of a shared file server; whether the latter
  performs acceptably may depend on a number of things, so we recommend
  you experiment and find out what works best for you.
"""

COPY_IN_CLOUD_TEXT = """
<B>COPYING IN THE CLOUD AND METADATA PRESERVATION</B>
  If both the source and destination URL are cloud URLs from the same
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
  "gsutil help defacl").  You can override this behavior with the -p
  option (see OPTIONS below).
"""

RESUMABLE_TRANSFERS_TEXT = """
<B>RESUMABLE TRANSFERS</B>
  gsutil automatically uses the Google Cloud Storage resumable upload
  feature whenever you use the cp command to upload an object that is larger
  than 2 MB. You do not need to specify any special command line options
  to make this happen. If your upload is interrupted you can restart the
  upload by running the same cp command that you ran to start the upload.

  Similarly, gsutil automatically performs resumable downloads (using HTTP
  standard Range GET operations) whenever you use the cp command to download an
  object larger than 2 MB.

  Resumable uploads and downloads store some state information in a file
  in ~/.gsutil named by the destination object or file. If you attempt to
  resume a transfer from a machine with a different directory, the transfer
  will start over from scratch.

  See also "gsutil help prod" for details on using resumable transfers
  in production.
"""

STREAMING_TRANSFERS_TEXT = """
<B>STREAMING TRANSFERS</B>
  Use '-' in place of src_url or dst_url to perform a streaming
  transfer. For example:

    long_running_computation | gsutil cp - gs://my_bucket/obj

  Streaming transfers do not support resumable uploads/downloads.
  (The Google resumable transfer protocol has a way to support streaming
  transfers, but gsutil doesn't currently implement support for this.)
"""

PARALLEL_COMPOSITE_UPLOADS_TEXT = """
<B>PARALLEL COMPOSITE UPLOADS</B>
  gsutil automatically uses
  `object composition <https://developers.google.com/storage/docs/composite-objects>`_
  to perform uploads in parallel for large, local files being uploaded to
  Google Cloud Storage. This means that, by default, a large file will be split
  into component pieces that will be uploaded in parallel. Those components will
  then be composed in the cloud, and the temporary components in the cloud will
  be deleted after successful composition. No additional local disk space is
  required for this operation.

  Any file whose size exceeds the "parallel_composite_upload_threshold" config
  variable will trigger this feature by default. The ideal size of a
  component can also be set with the "parallel_composite_upload_component_size"
  config variable. See the .boto config file for details about how these values
  are used.

  If the transfer fails prior to composition, running the command again will
  take advantage of resumable uploads for those components that failed, and
  the component objects will be deleted after the first successful attempt.
  Any temporary objects that were uploaded successfully before gsutil failed
  will still exist until the upload is completed successfully. The temporary
  objects will be named in the following fashion:
  <random ID>%s<hash>
  where <random ID> is some numerical value, and <hash> is an MD5 hash (not
  related to the hash of the contents of the file or object).

  One important caveat is that files uploaded in this fashion are still subject
  to the maximum number of components limit. For example, if you upload a large
  file that gets split into %d components, and try to compose it with another
  object with %d components, the operation will fail because it exceeds the %d
  component limit. If you wish to compose an object later and the component
  limit is a concern, it is recommended that you disable parallel composite
  uploads for that transfer.

  Also note that an object uploaded using this feature will have a CRC32C hash,
  but it will not have an MD5 hash. For details see 'gsutil help crc32c'.

  Note that this feature can be completely disabled by setting the
  "parallel_composite_upload_threshold" variable in the .boto config file to 0.
""" % (PARALLEL_UPLOAD_TEMP_NAMESPACE, 10, MAX_COMPONENT_COUNT - 9,
       MAX_COMPONENT_COUNT)

CHANGING_TEMP_DIRECTORIES_TEXT = """
<B>CHANGING TEMP DIRECTORIES</B>
  gsutil writes data to a temporary directory in several cases:

  - when compressing data to be uploaded (see the -z option)
  - when decompressing data being downloaded (when the data has
    Content-Encoding:gzip, e.g., as happens when uploaded using gsutil cp -z)
  - when running integration tests (using the gsutil test command)

  In these cases it's possible the temp file location on your system that
  gsutil selects by default may not have enough space. If you find that
  gsutil runs out of space during one of these operations (e.g., raising
  "CommandException: Inadequate temp space available to compress <your file>"
  during a gsutil cp -z operation), you can change where it writes these
  temp files by setting the TMPDIR environment variable. On Linux and MacOS
  you can do this either by running gsutil this way:

    TMPDIR=/some/directory gsutil cp ...

  or by adding this line to your ~/.bashrc file and then restarting the shell
  before running gsutil:

    export TMPDIR=/some/directory

  On Windows 7 you can change the TMPDIR environment variable from Start ->
  Computer -> System -> Advanced System Settings -> Environment Variables.
  You need to reboot after making this change for it to take effect. (Rebooting
  is not necessary after running the export command on Linux and MacOS.)
"""

OPTIONS_TEXT = """
<B>OPTIONS</B>
  -a canned_acl  Sets named canned_acl when uploaded objects created. See
                 'gsutil help acls' for further details.

  -c            If an error occurrs, continue to attempt to copy the remaining
                files. Note that this option is always true when running
                "gsutil -m cp".

  -D            Copy in "daisy chain" mode, i.e., copying between two buckets by
                hooking a download to an upload, via the machine where gsutil is
                run. By default, data are copied between two buckets
                "in the cloud", i.e., without needing to copy via the machine
                where gsutil runs.

                By default, a "copy in the cloud" when the source is a composite
                object will retain the composite nature of the object. However,
                Daisy chain mode can be used to change a composite object into
                a non-composite object. For example:

                    gsutil cp -D -p gs://bucket/obj gs://bucket/obj_tmp
                    gsutil mv -p gs://bucket/obj_tmp gs://bucket/obj

                Note: Daisy chain mode is automatically used when copying
                between providers (e.g., to copy data from Google Cloud Storage
                to another provider).

  -e            Exclude symlinks. When specified, symbolic links will not be
                copied.

  -L <file>     Outputs a manifest log file with detailed information about each
                item that was copied. This manifest contains the following
                information for each item:

                - Source path.
                - Destination path.
                - Source size.
                - Bytes transferred.
                - MD5 hash.
                - UTC date and time transfer was started in ISO 8601 format.
                - UTC date and time transfer was completed in ISO 8601 format.
                - Upload id, if a resumable upload was performed.
                - Final result of the attempted transfer, success or failure.
                - Failure details, if any.

                If the log file already exists, gsutil will use the file as an
                input to the copy process, and will also append log items to the
                existing file. Files/objects that are marked in the existing log
                file as having been successfully copied (or skipped) will be
                ignored. Files/objects without entries will be copied and ones
                previously marked as unsuccessful will be retried. This can be
                used in conjunction with the -c option to build a script that
                copies a large number of objects reliably, using a bash script
                like the following:

                    status=1
                    while [ $status -ne 0 ] ; do
                        gsutil cp -c -L cp.log -R ./dir gs://bucket
                        status=$?
                    done

                The -c option will cause copying to continue after failures
                occur, and the -L option will allow gsutil to pick up where it
                left off without duplicating work. The loop will continue
                running as long as gsutil exits with a non-zero status (such a
                status indicates there was at least one failure during the
                gsutil run).

  -n            No-clobber. When specified, existing files or objects at the
                destination will not be overwritten. Any items that are skipped
                by this option will be reported as being skipped. This option
                will perform an additional GET request to check if an item
                exists before attempting to upload the data. This will save
                retransmitting data, but the additional HTTP requests may make
                small object transfers slower and more expensive.

  -p            Causes ACLs to be preserved when copying in the cloud. Note that
                this option has performance and cost implications when using 
                the XML API, as it requires separate HTTP calls for interacting
                with ACLs. The performance issue can be mitigated to some
                degree by using gsutil -m cp to cause parallel copying.)

                You can avoid the additional performance and cost of using cp -p
                if you want all objects in the destination bucket to end up with
                the same ACL by setting a default ACL on that bucket instead of
                using cp -p. See "help gsutil defacl".

                Note that it's not valid to specify both the -a and -p options
                together.

  -q            Deprecated. Please use gsutil -q cp ... instead.

  -R, -r        Causes directories, buckets, and bucket subdirectories to be
                copied recursively. If you neglect to use this option for
                an upload, gsutil will copy any files it finds and skip any
                directories. Similarly, neglecting to specify -R for a download
                will cause gsutil to copy any objects at the current bucket
                directory level, and skip any subdirectories.

  -v            Requests that the version-specific URL for each uploaded object
                be printed. Given this URL you can make future upload requests
                that are safe in the face of concurrent updates, because Google
                Cloud Storage will refuse to perform the update if the current
                object version doesn't match the version-specific URL. See
                'gsutil help versions' for more details.

  -z <ext,...>  Applies gzip content-encoding to file uploads with the given
                extensions. This is useful when uploading files with
                compressible content (such as .js, .css, or .html files) because
                it saves network bandwidth and space in Google Cloud Storage,
                which in turn reduces storage costs.

                When you specify the -z option, the data from your files is
                compressed before it is uploaded, but your actual files are left
                uncompressed on the local disk. The uploaded objects retain the
                Content-Type and name of the original files but are given a
                Content-Encoding header with the value "gzip" to indicate that
                the object data stored are compressed on the Google Cloud
                Storage servers.

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
"""

_detailed_help_text = '\n\n'.join([SYNOPSIS_TEXT,
                                   DESCRIPTION_TEXT,
                                   NAME_CONSTRUCTION_TEXT,
                                   SUBDIRECTORIES_TEXT,
                                   COPY_IN_CLOUD_TEXT,
                                   RESUMABLE_TRANSFERS_TEXT,
                                   STREAMING_TRANSFERS_TEXT,
                                   PARALLEL_COMPOSITE_UPLOADS_TEXT,
                                   CHANGING_TEMP_DIRECTORIES_TEXT,
                                   OPTIONS_TEXT])


# This tuple is used only to encapsulate the arguments needed for
# _PerformResumableUploadIfApplies, so that the arguments fit the model of
# command.Apply().
PerformResumableUploadIfAppliesArgs = namedtuple(
    'PerformResumableUploadIfAppliesArgs',
    'filename file_start file_length src_url dst_url canned_acl headers '
    'tracker_file tracker_file_lock')

ObjectFromTracker = namedtuple('ObjectFromTracker',
                               'object_name generation')

CP_SUB_ARGS = 'a:cDeIL:MNnpqrRtvz:'

# The maximum length of a file name can vary wildly between different
# operating systems, so we always ensure that tracker files are less
# than 100 characters in order to avoid any such issues.
MAX_TRACKER_FILE_NAME_LENGTH = 100


class TrackerFileType(object):
  UPLOAD = 1
  DOWNLOAD = 2
  PARALLEL_UPLOAD = 3


def _CopyFuncWrapper(cls, args, thread_state=None):
  cls.CopyFunc(args, thread_state=thread_state)


# TODO: gsutil-beta: Port this function and other parallel upload functions,
# then re-enable linting for it.
# pylint: disable=g-short-docstring-punctuation,g-doc-return-or-yield
# pylint: disable=g-no-space-after-docstring-summary,g-doc-args
# pylint: disable=protected-access
def _PerformResumableUploadIfAppliesWrapper(cls, args):
  """A wrapper for cp._PerformResumableUploadIfApplies, which takes in a
     PerformResumableUploadIfAppliesArgs, extracts the arguments to form the
     arguments for the wrapped function, and then calls the wrapped function.
     This was designed specifically for use with command.Apply().
  """
  fp = FilePart(args.filename, args.file_start, args.file_length)
  with fp:
    already_split = True
    ret = cls._PerformResumableUploadIfApplies(
        fp, args.src_url, args.dst_url, args.canned_acl, args.headers,
        fp.length, already_split)

  # Update the tracker file after each call in order to be as robust as possible
  # against interrupts, failures, etc.
  component = ret[2]
  _AppendComponentTrackerToParallelUploadTrackerFile(args.tracker_file,
                                                     component,
                                                     args.tracker_file_lock)
  return ret


def _CopyExceptionHandler(cls, e):
  """Simple exception handler to allow post-completion status."""
  cls.logger.error(str(e))
  cls.copy_failure_count += 1
  cls.logger.debug('\n\nEncountered exception while copying:\n%s\n' %
                   traceback.format_exc())


def _RmExceptionHandler(cls, e):
  """Simple exception handler to allow post-completion status."""
  cls.logger.error(str(e))


class CpCommand(Command):
  """Implementation of gsutil cp command.

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

  # TODO: Refactor this file to be less cumbersome. In particular, some of the
  # different paths (e.g., uploading a file to an object vs. downloading an
  # object to a file) could be split into separate files.

  USE_MAGICFILE = config.getbool('GSUtil', 'use_magicfile', False)
  # Chunk size to use while unzipping gzip files.
  GUNZIP_CHUNK_SIZE = 8192

  # Command specification. See base class for documentation.
  command_spec = Command.CreateCommandSpec(
      'cp',
      command_name_aliases = ['copy'],
      min_args = 1,
      max_args = NO_MAX,
      # -t is deprecated but leave intact for now to avoid breakage.
      supported_sub_args = CP_SUB_ARGS,
      file_url_ok = True,
      provider_url_ok = False,
      urls_start_arg = 0,
      gs_api_support = [ApiSelector.XML, ApiSelector.JSON],
      gs_default_api = ApiSelector.JSON,
  )
  # Help specification. See help_provider.py for documentation.
  help_spec = Command.HelpSpec(
      help_name = 'cp',
      help_name_aliases = ['copy'],
      help_type = 'command_help',
      help_one_line_summary = 'Copy files and objects',
      help_text = _detailed_help_text,
      subcommand_help_text = {},
  )

  def _CheckForDirFileConflict(self, exp_src_url, dst_url):
    """Checks whether copying exp_src_url into dst_url is not possible.

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
      exp_src_url: Expanded source StorageUrl.
      dst_url: Destination StorageUrl.

    Raises:
      CommandException: if errors encountered.
    """
    if dst_url.IsCloudUrl():
      # The problem can only happen for file destination URLs.
      return
    dst_path = dst_url.object_name
    final_dir = os.path.dirname(dst_path)
    if os.path.isfile(final_dir):
      raise CommandException('Cannot retrieve %s because a file exists '
                             'where a directory needs to be created (%s).' %
                             (exp_src_url.GetUrlString(), final_dir))
    if os.path.isdir(dst_path):
      raise CommandException('Cannot retrieve %s because a directory exists '
                             '(%s) where the file needs to be created.' %
                             (exp_src_url.GetUrlString(), dst_path))

  def _GetBucketWithVersioningConfig(self, exp_dst_url):
    """Gets versioning config for a bucket and ensures that it exists.

    Args:
      exp_dst_url: Wildcard-expanded destination StorageUrl.

    Raises:
      AccessDeniedException: if there was a permissions problem accessing the
                             bucket or its versioning config.
      CommandException: if URL refers to a cloud bucket that does not exist.

    Returns:
      apitools Bucket with versioning configuration.
    """
    bucket = None
    if exp_dst_url.IsCloudUrl() and exp_dst_url.IsBucket():
      try:
        bucket = self.gsutil_api.GetBucket(
            exp_dst_url.bucket_name, provider=exp_dst_url.scheme,
            fields=['versioning'])
      except AccessDeniedException, e:
        raise
      except NotFoundException, e:
        raise CommandException('Destination bucket %s does not exist.' %
                               exp_dst_url.GetUrlString())
      except Exception, e:
        raise CommandException('Error retrieving destination bucket %s: %s' %
                               (exp_dst_url.GetUrlString(), e.message))
      return bucket

  def _InsistDstUrlNamesContainer(self, exp_dst_url,
                                  have_existing_dst_container, command_name):
    """Ensures the destination URL names a container.

    Acceptable containers include directory, bucket, bucket
    subdir, and non-existing bucket subdir.

    Args:
      exp_dst_url: Wildcard-expanded destination StorageUrl.
      have_existing_dst_container: bool indicator of whether exp_dst_url
        names a container (directory, bucket, or existing bucket subdir).
      command_name: Name of command making call. May not be the same as
          self.command_name in the case of commands implemented atop other
          commands (like mv command).

    Raises:
      CommandException: if the URL being checked does not name a container.
    """
    if ((exp_dst_url.IsFileUrl() and not exp_dst_url.IsDirectory()) or
        (exp_dst_url.IsCloudUrl() and exp_dst_url.IsBucket()
         and not have_existing_dst_container)):
      raise CommandException('Destination URL must name a directory, bucket, '
                             'or bucket\nsubdirectory for the multiple '
                             'source form of the %s command.' % command_name)

  class _FileCopyCallbackHandler(object):
    """Outputs progress info for large copy requests."""

    def __init__(self, upload, logger):
      if upload:
        self.announce_text = 'Uploading'
      else:
        self.announce_text = 'Downloading'
      self.logger = logger

    # pylint: disable=invalid-name
    def call(self, total_bytes_transferred, total_size):
      # Use sys.stderr.write instead of self.logger.info so progress messages
      # output on a single continuously overwriting line.
      if self.logger.isEnabledFor(logging.INFO):
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

    def __init__(self, logger):
      self.logger = logger

    # pylint: disable=invalid-name
    def call(self, total_bytes_transferred, total_size):
      # Use sys.stderr.write instead of self.logger.info so progress messages
      # output on a single continuously overwriting line.
      if self.logger.isEnabledFor(logging.INFO):
        sys.stderr.write('Uploading: %s    \r' %
                         MakeHumanReadable(total_bytes_transferred))
        if total_size and total_bytes_transferred == total_size:
          sys.stderr.write('\n')

  # TODO: gsutil-beta: Port this function and other parallel upload functions,
  # then re-enable linting for it.
  def _GetTrackerFilePath(self, dst_url, tracker_file_type, src_url=None):
    resumable_tracker_dir = CreateTrackerDirIfNeeded()
    if tracker_file_type == TrackerFileType.UPLOAD:
      # Encode the dest bucket and object name into the tracker file name.
      res_tracker_file_name = (
          re.sub('[/\\\\]', '_', 'resumable_upload__%s__%s.url' %
                 (dst_url.bucket_name, dst_url.object_name)))
      tracker_file_type_str = 'upload'
    elif tracker_file_type == TrackerFileType.DOWNLOAD:
      # Encode the fully-qualified dest file name into the tracker file name.
      res_tracker_file_name = (
          re.sub('[/\\\\]', '_', 'resumable_download__%s.etag' %
                 (os.path.realpath(dst_url.object_name))))
      tracker_file_type_str = 'download'
    elif tracker_file_type == TrackerFileType.PARALLEL_UPLOAD:
      # Encode the dest bucket and object names as well as the source file name
      # into the tracker file name.
      res_tracker_file_name = (
          re.sub('[/\\\\]', '_', 'parallel_upload__%s__%s__%s.url' %
                 (dst_url.bucket_name, dst_url.object_name, src_url)))
      tracker_file_type_str = 'parallel_upload'

    res_tracker_file_name = _HashFilename(res_tracker_file_name)
    tracker_file_name = '%s_%s' % (tracker_file_type_str, res_tracker_file_name)
    tracker_file_path = '%s%s%s' % (resumable_tracker_dir, os.sep,
                                    tracker_file_name)
    assert len(tracker_file_name) < MAX_TRACKER_FILE_NAME_LENGTH
    return tracker_file_path

  def _LogCopyOperation(self, src_url, dst_url, dst_obj_metadata):
    """Logs copy operation, including Content-Type if appropriate.

    Args:
      src_url: Source StorageUrl.
      dst_url: Destination StorageUrl.
      dst_obj_metadata: Object-specific metadata that should be overidden during
                        the copy.
    """
    if (dst_url.IsCloudUrl() and dst_obj_metadata and
        dst_obj_metadata.contentType):
      content_type_msg = ' [Content-Type=%s]' % dst_obj_metadata.contentType
    else:
      content_type_msg = ''
    if src_url.IsFileUrl() and src_url.IsStream():
      self.logger.info('Copying from <STDIN>%s...', content_type_msg)
    else:
      self.logger.info('Copying %s%s...', src_url.GetUrlString(),
                       content_type_msg)

  def _CopyObjToObjInTheCloud(self, src_url, src_obj_size, dst_url,
                              dst_obj_metadata, preconditions, gsutil_api):
    """Performs copy-in-the cloud from specified src to dest object.

    Args:
      src_url: Source CloudUrl.
      src_obj_size: Size of source object.
      dst_url: Destination CloudUrl.
      dst_obj_metadata: Object-specific metadata that should be overidden during
                        the copy.
      preconditions: Preconditions to use for the copy.
      gsutil_api: gsutil Cloud API instance to use for the copy.

    Returns:
      (elapsed_time, bytes_transferred, dst_url with generation,
      md5 hash of destination) excluding overhead like initial GET.

    Raises:
      CommandException: if errors encountered.
    """
    self._LogCopyOperation(src_url, dst_url, dst_obj_metadata)

    start_time = time.time()

    dst_obj = gsutil_api.CopyObject(
        src_url.bucket_name, src_url.object_name,
        src_generation=src_url.generation, dst_obj_metadata=dst_obj_metadata,
        preconditions=preconditions, provider=dst_url.scheme,
        fields=UPLOAD_RETURN_FIELDS)

    end_time = time.time()

    result_url = dst_url.Clone()
    result_url.generation = dst_obj.generation

    return (end_time - start_time, src_obj_size, result_url, dst_obj.md5Hash)

  def _CheckFreeSpace(self, path):
    """Return path/drive free space (in bytes)."""
    if IS_WINDOWS:
      # pylint: disable=g-import-not-at-top
      try:
        # pylint: disable=invalid-name
        get_disk_free_space_ex = WINFUNCTYPE(c_int, c_wchar_p,
                                             POINTER(c_uint64),
                                             POINTER(c_uint64),
                                             POINTER(c_uint64))
        get_disk_free_space_ex = get_disk_free_space_ex(
            ('GetDiskFreeSpaceExW', windll.kernel32), (
                (1, 'lpszPathName'),
                (2, 'lpFreeUserSpace'),
                (2, 'lpTotalSpace'),
                (2, 'lpFreeSpace'),))
      except AttributeError:
        get_disk_free_space_ex = WINFUNCTYPE(c_int, c_char_p,
                                             POINTER(c_uint64),
                                             POINTER(c_uint64),
                                             POINTER(c_uint64))
        get_disk_free_space_ex = get_disk_free_space_ex(
            ('GetDiskFreeSpaceExA', windll.kernel32), (
                (1, 'lpszPathName'),
                (2, 'lpFreeUserSpace'),
                (2, 'lpTotalSpace'),
                (2, 'lpFreeSpace'),))

      def GetDiskFreeSpaceExErrCheck(result, unused_func, args):
        if not result:
          raise WinError()
        return args[1].value
      get_disk_free_space_ex.errcheck = GetDiskFreeSpaceExErrCheck

      return get_disk_free_space_ex(os.getenv('SystemDrive'))
    else:
      (_, f_frsize, _, _, f_bavail, _, _, _, _, _) = os.statvfs(path)
      return f_frsize * f_bavail

  def _SetContentTypeFromFile(self, src_url, dst_obj_metadata):
    """Detects and sets Content-Type if src_url names a local file.

    Args:
      src_url: Source StorageUrl.
      dst_obj_metadata: Object-specific metadata that should be overidden during
                       the copy.
    """
    # contentType == '' if user requested default type.
    if (dst_obj_metadata.contentType is None and src_url.IsFileUrl()
        and not src_url.IsStream()):
      # Only do content type recognition if src_url is a file. Object-to-object
      # copies with no -h Content-Type specified re-use the content type of the
      # source object.
      object_name = src_url.object_name
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
        content_type = DEFAULT_CONTENT_TYPE
      dst_obj_metadata.contentType = content_type

  def _UploadFileToObjectNonResumable(self, src_url, src_obj_filestream,
                                      src_obj_size, dst_url, dst_obj_metadata,
                                      preconditions, gsutil_api):
    """Uploads the file using a non-resumable strategy.

    Args:
      src_url: Source StorageUrl to upload.
      src_obj_filestream: File pointer to uploadable bytes.
      src_obj_size: Size of the source object.
      dst_url: Destination StorageUrl for the upload.
      dst_obj_metadata: Metadata for the target object.
      preconditions: Preconditions for the upload, if any.
      gsutil_api: gsutil Cloud API instance to use for the upload.

    Returns:
      Elapsed upload time, uploaded Object with generation, md5, and size fields
      populated.
    """
    if not src_url.IsStream():
      with open(src_url.object_name, 'rb') as f_in:
        if src_obj_size >= MIN_SIZE_COMPUTE_LOGGING:
          self.logger.info('Computing CRC for %s...', src_url.GetUrlString())
        crc32c_b64 = base64.encodestring(binascii.unhexlify(
            _CalculateCrc32cFromContents(f_in))).rstrip('\n')
        dst_obj_metadata.crc32c = crc32c_b64
    start_time = time.time()
    if src_url.IsStream():
      # TODO: gsutil-beta: Provide progress callbacks for streaming uploads.
      uploaded_object = gsutil_api.UploadObjectStreaming(
          src_obj_filestream, object_metadata=dst_obj_metadata,
          preconditions=preconditions, provider=dst_url.scheme,
          fields=UPLOAD_RETURN_FIELDS)
    else:
      uploaded_object = gsutil_api.UploadObject(
          src_obj_filestream, object_metadata=dst_obj_metadata,
          preconditions=preconditions, provider=dst_url.scheme,
          size=src_obj_size, fields=UPLOAD_RETURN_FIELDS)
    end_time = time.time()
    elapsed_time = end_time - start_time
    return elapsed_time, uploaded_object

  def _UploadFileToObjectResumable(self, src_url, src_obj_filestream,
                                   src_obj_size, dst_url, dst_obj_metadata,
                                   preconditions, gsutil_api):
    """Uploads the file using a resumable strategy.

    Args:
      src_url: Source FileUrl to upload.  Must not be a stream.
      src_obj_filestream: File pointer to uploadable bytes.
      src_obj_size: Size of the source object.
      dst_url: Destination StorageUrl for the upload.
      dst_obj_metadata: Metadata for the target object.
      preconditions: Preconditions for the upload, if any.
      gsutil_api: gsutil Cloud API instance to use for the upload.

    Returns:
      Elapsed upload time, uploaded Object with generation, md5, and size fields
      populated.
    """
    tracker_file_name = self._GetTrackerFileName(
        dst_url, TrackerFileType.UPLOAD,
        gsutil_api.GetApiSelector(provider=dst_url.scheme))

    def _UploadTrackerCallback(serialization_data):
      """Creates a new tracker file for starting an upload from scratch.

      This function is called by the gsutil Cloud API implementation and the
      the serialization data is implementation-specific.

      Args:
        serialization_data: Serialization data used in resuming the upload.
      """
      try:
        tracker_file = open(tracker_file_name, 'w')
        tracker_file.write(str(serialization_data))
      except IOError as e:
        raise CommandException(
            'Couldn\'t write tracker file (%s): %s.\nThis can happen'
            'if you\'re using an incorrectly configured download tool\n'
            '(e.g., gsutil configured to save tracker files to an '
            'unwritable directory)' %
            (self.tracker_file_name, e.strerror))
      finally:
        if tracker_file:
          tracker_file.close()

    # TODO: gsutil-beta: JSON resumable uploads require that you supply
    # the hash on the initial POST.  Research if there is any way to do it
    # on the fly (for both JSON and XML).
    # Currently, the XML upload code will compute an MD5 on the fly.
    if src_obj_size >= MIN_SIZE_COMPUTE_LOGGING:
      self.logger.info('Computing CRC for %s...', src_url.GetUrlString())
    with open(src_url.object_name, 'rb') as f_in:
      crc32c_b64 = base64.encodestring(binascii.unhexlify(
          _CalculateCrc32cFromContents(f_in))).rstrip('\n')
      dst_obj_metadata.crc32c = crc32c_b64

    # This contains the upload URL, which will uniquely identify the
    # destination object.
    tracker_data = self._GetUploadTrackerData(tracker_file_name)
    if tracker_data:
      self.logger.debug('Resuming upload for %s', src_url.GetUrlString())

    retryable = False

    start_time = time.time()
    try:
      uploaded_object = gsutil_api.UploadObjectResumable(
          src_obj_filestream, object_metadata=dst_obj_metadata,
          preconditions=preconditions, provider=dst_url.scheme,
          size=src_obj_size, serialization_data=tracker_data,
          fields=UPLOAD_RETURN_FIELDS,
          tracker_callback=_UploadTrackerCallback,
          progress_callback=self._FileCopyCallbackHandler(
              True, self.logger).call)
    except ResumableUploadException:
      retryable = True
      raise
    finally:
      if not retryable:
        self._DeleteTrackerFile(tracker_file_name)

    end_time = time.time()
    elapsed_time = end_time - start_time

    result_url = dst_url.Clone()
    result_url.generation = uploaded_object.generation

    return (elapsed_time, uploaded_object)

  def _CompressFileForUpload(self, src_url, src_obj_filestream, src_obj_size):
    """Compresses a to-be-uploaded local file to save bandwidth.

    Args:
      src_url: Source FileUrl.
      src_obj_filestream: Read stream of the source file - will be consumed
                          and closed.
      src_obj_size: Size of the source file.

    Returns:
      StorageUrl path to compressed file, compressed file size.
    """
    # TODO: gsutil-beta: When we add on-the-fly hash computation for uploads,
    # calculate the hash by compressing and hashing one file block at a time.
    if src_obj_size >= MIN_SIZE_COMPUTE_LOGGING:
      self.logger.info('Compressing %s (to tmp)...', src_url)
    (gzip_fh, gzip_path) = tempfile.mkstemp()
    gzip_fp = None
    try:
      # Check for temp space. Assume the compressed object is at most 2x
      # the size of the object (normally should compress to smaller than
      # the object)
      if self._CheckFreeSpace(gzip_path) < 2*int(src_obj_size):
        raise CommandException('Inadequate temp space available to compress '
                               '%s. See the CHANGING TEMP DIRECTORIES section '
                               'of "gsutil help cp" for more info.' % src_url)
      gzip_fp = gzip.open(gzip_path, 'wb')
      gzip_fp.writelines(src_obj_filestream)
    finally:
      if gzip_fp:
        gzip_fp.close()
      os.close(gzip_fh)
      src_obj_filestream.close()
    gzip_size = os.path.getsize(gzip_path)
    return StorageUrlFromString(gzip_path), gzip_size

  def _UploadFileToObject(self, src_url, src_obj_filestream, src_obj_size,
                          dst_url, dst_obj_metadata, preconditions, gsutil_api,
                          allow_splitting=True):
    """Uploads a local file to an object.

    Args:
      src_url: Source FileUrl.
      src_obj_filestream: Read stream of the source file to be read and closed.
      src_obj_size: Size of the source file.
      dst_url: Destination CloudUrl.
      dst_obj_metadata: Metadata to be applied to the destination object.
      preconditions: Preconditions to use for the copy.
      gsutil_api: gsutil Cloud API to use for the copy.
      allow_splitting: If true, allow this upload to be split into parallel
                       uploads and composed.
    Returns:
      (elapsed_time, bytes_transferred, dst_url with generation,
      md5 hash of destination) excluding overhead like initial GET.

    Raises:
      CommandException: if errors encountered.
    """
    gzip_exts = []
    if self.sub_opts:
      for o, a in self.sub_opts:
        if o == '-z':
          gzip_exts = a.split(',')

    self._SetContentTypeFromFile(src_url, dst_obj_metadata)
    self._LogCopyOperation(src_url, dst_url, dst_obj_metadata)

    if not dst_obj_metadata or not dst_obj_metadata.contentLanguage:
      content_language = config.get_value('GSUtil', 'content_language')
      if content_language:
        dst_obj_metadata.contentLanguage = content_language

    fname_parts = src_url.object_name.split('.')
    upload_url = src_url
    upload_stream = src_obj_filestream
    upload_size = src_obj_size
    zipped_file = False
    if len(fname_parts) > 1 and fname_parts[-1] in gzip_exts:
      upload_url, upload_size = self._CompressFileForUpload(
          src_url, src_obj_filestream, src_obj_size)
      upload_stream = open(upload_url.object_name, 'rb')
      dst_obj_metadata.contentEncoding = 'gzip'
      zipped_file = True

    elapsed_time = None
    uploaded_object = None
    try:
      if upload_size < self.resumable_threshold or src_url.IsStream():
        elapsed_time, uploaded_object = self._UploadFileToObjectNonResumable(
            upload_url, upload_stream, upload_size, dst_url, dst_obj_metadata,
            preconditions, gsutil_api)
      else:
        elapsed_time, uploaded_object = self._UploadFileToObjectResumable(
            upload_url, upload_stream, upload_size, dst_url, dst_obj_metadata,
            preconditions, gsutil_api)

    finally:
      if zipped_file:
        try:
          os.unlink(upload_url.object_name)
        # Windows sometimes complains the temp file is locked when you try to
        # delete it.
        except Exception:  # pylint: disable=broad-except
          self.logger.warning('Could not delete %s. This can occur in Windows '
                              'because the temporary file is still locked.' %
                              upload_url.object_name)
      # In the gzip case, this is the gzip stream.  _CompressFileForUpload will
      # have already closed the original source stream.
      upload_stream.close()

    result_url = dst_url.Clone()
    result_url.generation = uploaded_object.generation

    return (elapsed_time, uploaded_object.size, result_url,
            uploaded_object.md5Hash)

  def _GetTrackerFileName(self, dst_url, tracker_file_type, api_selector,
                          src_url=None):
    """Gets the tracker file name described by the arguments.

    Args:
      dst_url: Destination URL for tracker file.
      tracker_file_type: TrackerFileType for this operation.
      api_selector: API to use for this operation.
      src_url: Source URL for the source file name for parallel uploads.
    """
    resumable_tracker_dir = CreateTrackerDirIfNeeded()
    if tracker_file_type == TrackerFileType.UPLOAD:
      # Encode the dest bucket and object name into the tracker file name.
      res_tracker_file_name = (
          re.sub('[/\\\\]', '_', 'resumable_upload__%s__%s__%s.url' %
                 (dst_url.bucket_name, dst_url.object_name, api_selector)))
    elif tracker_file_type == TrackerFileType.DOWNLOAD:
      # Encode the fully-qualified dest file name into the tracker file name.
      res_tracker_file_name = (
          re.sub('[/\\\\]', '_', 'resumable_download__%s__%s.etag' %
                 (os.path.realpath(dst_url.object_name), api_selector)))
    elif tracker_file_type == TrackerFileType.PARALLEL_UPLOAD:
      # Encode the dest bucket and object names as well as the source file name
      # into the tracker file name.
      res_tracker_file_name = (
          re.sub('[/\\\\]', '_', 'parallel_upload__%s__%s__%s__%s.url' %
                 (dst_url.bucket_name, dst_url.object_name,
                  src_url, api_selector)))

    res_tracker_file_name = _HashFilename(res_tracker_file_name)
    tracker_file_name = '%s%s%s' % (resumable_tracker_dir, os.sep,
                                    res_tracker_file_name)
    return tracker_file_name

  def _SelectDownloadStrategy(self, src_obj_metadata, dst_url):
    """Get download strategy based on the source and dest objects.

    Args:
      src_obj_metadata: Object describing the source object.
      dst_url: Destination StorageUrl.

    Returns:
      gsutil Cloud API DownloadStrategy.
    """
    dst_is_special = False
    if dst_url.IsFileUrl():
      # Check explicitly first because os.stat doesn't work on 'nul' in Windows.
      if dst_url.object_name == os.devnull:
        dst_is_special = True
      try:
        mode = os.stat(dst_url.object_name).st_mode
        if stat.S_ISCHR(mode):
          dst_is_special = True
      except OSError:
        pass

    if src_obj_metadata.size >= self.resumable_threshold and not dst_is_special:
      return CloudApi.DownloadStrategy.RESUMABLE
    else:
      return CloudApi.DownloadStrategy.ONE_SHOT

  def _GetUploadTrackerData(self, tracker_file_name):
    """Checks for an upload tracker file and creates one if it does not exist.

      Args:
        tracker_file_name: Tracker file name for this upload.

      Returns:
        Serialization data if the tracker file already exists (resume existing
        upload), None otherwise.
    """
    tracker_file = None

    # If we already have a matching tracker file, get the serialization data
    # so that we can resume the upload.
    try:
      tracker_file = open(tracker_file_name, 'r')
      tracker_data = tracker_file.read()
      return tracker_data
    except IOError as e:
      # Ignore non-existent file (happens first time a upload
      # is attempted on an object), but warn user for other errors.
      if e.errno != errno.ENOENT:
        print('Couldn\'t read upload tracker file (%s): %s. Restarting '
              'upload from scratch.' %
              (self.tracker_file_name, e.strerror))
    finally:
      if tracker_file:
        tracker_file.close()

  def _ReadOrCreateDownloadTrackerFile(self, src_obj_metadata, src_url,
                                       api_selector):
    """Checks for a download tracker file and creates one if it does not exist.

      Args:
        src_obj_metadata: Metadata for the source object.  Must include
                          etag.
        dst_url: Source StorageUrl.
        api_selector: API mode to use (for tracker file naming).

      Returns:
        True if the tracker file already exists (resume existing download),
        False if we created a new tracker file (new download).
    """
    assert src_obj_metadata.etag
    tracker_file_name = self._GetTrackerFileName(
        src_url, TrackerFileType.DOWNLOAD, api_selector)
    tracker_file = None

    # Check to see if we already have a matching tracker file.
    try:
      tracker_file = open(tracker_file_name, 'r')
      etag_value = tracker_file.readline().rstrip('\n')
      if etag_value is src_obj_metadata.etag:
        return True
    except IOError as e:
      # Ignore non-existent file (happens first time a download
      # is attempted on an object), but warn user for other errors.
      if e.errno != errno.ENOENT:
        print('Couldn\'t read URL tracker file (%s): %s. Restarting '
              'download from scratch.' %
              (self.tracker_file_name, e.strerror))
    finally:
      if tracker_file:
        tracker_file.close()

    # Otherwise, create a new tracker file and start from scratch
    try:
      with os.fdopen(os.open(tracker_file_name,
                             os.O_WRONLY | os.O_CREAT, 0600), 'w') as tf:
        tf.write('%s\n' % src_obj_metadata.etag)
      return False
    except IOError as e:
      raise CommandException(
          'Couldn\'t write tracker file (%s): %s.\nThis can happen'
          'if you\'re using an incorrectly configured download tool\n'
          '(e.g., gsutil configured to save tracker files to an '
          'unwritable directory)' %
          (self.tracker_file_name, e.strerror))
    finally:
      if tracker_file:
        tracker_file.close()

  def _DeleteTrackerFile(self, tracker_file_name):
    if tracker_file_name and os.path.exists(tracker_file_name):
      os.unlink(tracker_file_name)

  def _DownloadObjectToFile(self, src_url, src_obj_metadata, dst_url,
                            gsutil_api):
    """Downloads an object to a local file.

    Args:
      src_url: Source CloudUrl.
      src_obj_metadata: Metadata from the source object.
      dst_url: Destination FileUrl.
      gsutil_api: gsutil Cloud API instance to use for the download.
    Returns:
      (elapsed_time, bytes_transferred, dst_url, md5), excluding overhead like
      initial GET.

    Raises:
      CommandException: if errors encountered.
    """
    self._LogCopyOperation(src_url, dst_url, None)
    file_name = dst_url.object_name
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
    api_selector = gsutil_api.GetApiSelector(provider=src_url.scheme)
    if (src_obj_metadata.contentEncoding and
        src_obj_metadata.contentEncoding == 'gzip' and
        api_selector == ApiSelector.XML):
      # We can't use tempfile.mkstemp() here because we need a predictable
      # filename for resumable downloads.
      download_file_name = '%s_.gztmp' % file_name
      self.logger.info('Downloading to temp gzip filename %s' %
                       download_file_name)
      need_to_unzip = True
    else:
      # httplib2 (used by JSON API) will decompress on-the-fly for us.
      download_file_name = file_name
      need_to_unzip = False

    # Set up hash digesters.
    hash_algs = GetHashAlgs(src_etag=src_obj_metadata.etag,
                            src_md5=src_obj_metadata.md5Hash,
                            src_crc32c=src_obj_metadata.crc32c)
    digesters = dict((alg, hash_algs[alg]()) for alg in hash_algs or {})

    fp = None
    download_strategy = self._SelectDownloadStrategy(src_obj_metadata, dst_url)
    download_start_point = 0
    # This is used for resuming downloads, but also for passing the mediaLink
    # and size into the download for new downloads so that we can avoid
    # making an extra HTTP call.
    serialization_data = None
    serialization_dict = GetDownloadSerializationDict(src_obj_metadata)
    try:
      if download_strategy is CloudApi.DownloadStrategy.ONE_SHOT:
        fp = open(download_file_name, 'wb')
      elif download_strategy is CloudApi.DownloadStrategy.RESUMABLE:
        # If this is a resumable download, we need to open the file for append,
        # manage a tracker file, and prepare a callback function.
        fp = open(download_file_name, 'ab')

        api_selector = gsutil_api.GetApiSelector(provider=src_url.scheme)
        resuming = self._ReadOrCreateDownloadTrackerFile(
            src_obj_metadata, dst_url, api_selector)
        if resuming:
          # Find out how far along we are so we can request the appropriate
          # remaining range of the object.
          existing_file_size = GetFileSize(fp, position_to_eof=True)
          if existing_file_size > src_obj_metadata.size:
            self._DeleteTrackerFile(self._GetTrackerFileName(
                dst_url, TrackerFileType.DOWNLOAD, api_selector))
            raise CommandException(
                '%s is larger (%d) than %s (%d).\nDeleting tracker file, so '
                'if you re-try this download it will start from scratch' %
                (fp.name, existing_file_size, src_url.object_name,
                 src_obj_metadata.size))
          if existing_file_size is src_obj_metadata.size:
            self.logger.debug('Download already complete for file %s, just.'
                              'deleting tracker file' % fp.name)
            self._DeleteTrackerFile(self._GetTrackerFileName(
                dst_url, TrackerFileType.DOWNLOAD, api_selector))
          else:
            download_start_point = existing_file_size
            serialization_dict['progress'] = download_start_point
            # Catch up our digester with the hash data.
            if existing_file_size > TWO_MB:
              for alg_name in digesters:
                self.logger.info('Catching up %s for %s' % (alg_name,
                                                            download_file_name))
            with open(download_file_name, 'rb') as hash_fp:
              while True:
                data = hash_fp.read(DEFAULT_FILE_BUFFER_SIZE)
                if not data:
                  break
                for alg_name in digesters:
                  digesters[alg_name].update(data)
        else:
          # Starting a new download, blow away whatever is already there.
          fp.truncate(0)

      else:
        raise CommandException('Invalid download strategy %s chosen for'
                               'file %s' % (download_strategy, fp.name))

      if not dst_url.IsStream():
        serialization_data = json.dumps(serialization_dict)

      start_time = time.time()
      # TODO: With gzip encoding (which may occur on-the-fly and not be part of
      # the object's metadata), when we request a range to resume, it's possible
      # that the server will just resend the entire object, which means our
      # caught-up hash will be incorrect.  We recalculate the hash on
      # the local file in the case of a failed gzip hash anyway, but it would
      # be better if we actively detected this case.
      gsutil_api.GetObjectMedia(
          src_url.bucket_name, src_url.object_name, fp,
          start_byte=download_start_point, generation=src_url.generation,
          provider=src_url.scheme,
          serialization_data=serialization_data, digesters=digesters,
          progress_callback=self._FileCopyCallbackHandler(
              False, self.logger).call)

      end_time = time.time()

      # If a custom test method is defined, call it here. For the copy command,
      # test methods are expected to take one argument: an open file pointer,
      # and are used to perturb the open file during download to exercise
      # download error detection.
      if self.test_method:
        self.test_method(fp)
    except ResumableDownloadException as e:
      self.logger.warning('Caught non-retryable ResumableDownloadException '
                          '(%s).' % e.message)
    finally:
      if fp:
        fp.close()

    digesters_succeeded = True
    for alg in digesters:
      # If we get a digester with a None algorithm, the underlying
      # implementation failed to calculate a digest, so we will need to
      # calculate one from scratch.
      if not digesters[alg]:
        digesters_succeeded = False
        break

    if digesters_succeeded:
      local_hashes = self._CreateDigestsFromDigesters(digesters)
    else:
      local_hashes = self._CreateDigestsFromLocalFile(
          hash_algs, download_file_name, src_obj_metadata)

    # If we decompressed a content-encoding gzip file on the fly, this may not
    # be accurate, but it is the best we can do without going deep into the
    # underlying HTTP libraries.
    bytes_transferred = src_obj_metadata.size - download_start_point

    digest_verified = True
    try:
      self._CheckHashes(src_obj_metadata, download_file_name, local_hashes)
    except CommandException, e:
      # If the digest doesn't match, we'll try checking it again after
      # unzipping.
      if ('doesn\'t match cloud-supplied digest' in str(e) and
          (api_selector == ApiSelector.JSON or need_to_unzip)):
        digest_verified = False
      else:
        os.unlink(download_file_name)
        raise

    if need_to_unzip:
      # Log that we're uncompressing if the file is big enough that
      # decompressing would make it look like the transfer "stalled" at the end.
      if bytes_transferred > 10 * 1024 * 1024:
        self.logger.info('Uncompressing downloaded tmp file to %s...',
                         file_name)

      # Downloaded gzipped file to a filename w/o .gz extension, so unzip.
      with gzip.open(download_file_name, 'rb') as f_in:
        with open(file_name, 'wb') as f_out:
          data = f_in.read(self.GUNZIP_CHUNK_SIZE)
          while data:
            f_out.write(data)
            data = f_in.read(self.GUNZIP_CHUNK_SIZE)

      os.unlink(download_file_name)

    if not digest_verified:
      try:
        # Recalculate hashes on the unzipped local file.
        local_hashes = self._CreateDigestsFromLocalFile(hash_algs, file_name,
                                                        src_obj_metadata)
        self._CheckHashes(src_obj_metadata, file_name, local_hashes)
      except CommandException, e:
        os.unlink(file_name)
        raise

    local_md5 = None
    if 'md5' in local_hashes:
      local_md5 = local_hashes['md5']
    return (end_time - start_time, bytes_transferred, dst_url, local_md5)

  def _CreateDigestsFromDigesters(self, digesters):
    digests = {}
    for alg in digesters:
      digests[alg] = base64.encodestring(
          digesters[alg].digest()).rstrip('\n')
    return digests

  def _CreateDigestsFromLocalFile(self, algs, file_name, src_obj_metadata):
    digests = {}
    if 'md5' in algs:
      if src_obj_metadata.size and src_obj_metadata.size > TWO_MB:
        self.logger.info('Computing MD5 for %s...', file_name)
      with open(file_name, 'rb') as fp:
        digests['md5'] = base64.encodestring(binascii.unhexlify(
            CalculateMd5FromContents(fp))).rstrip('\n')
    if 'crc32c' in algs:
      if src_obj_metadata.size and src_obj_metadata.size > TWO_MB:
        self.logger.info('Computing CRC32C for %s...', file_name)
      with open(file_name, 'rb') as fp:
        digests['crc32c'] = base64.encodestring(binascii.unhexlify(
            _CalculateCrc32cFromContents(fp))).rstrip('\n')
    return digests

  def _CheckHashes(self, src_obj_metadata, file_name, digests):
    """Validates integrity by comparing cloud digest to local digest.

    Args:
      src_obj_metadata: Cloud object being downloaded.
      file_name: Name of downloaded file on local disk.
      digest: Computed Digests for the object.

    Raises:
      CommandException: if cloud digests don't match local digests.
    """
    etag_md5 = GetMD5FromETag(getattr(src_obj_metadata, 'etag', None))
    if not src_obj_metadata.md5Hash and etag_md5:
      # md5Hash is in base64 format.
      src_obj_metadata.md5Hash = base64.encodestring(binascii.unhexlify(
          etag_md5))

    local_hashes = digests
    cloud_hashes = {}
    if src_obj_metadata.md5Hash:
      cloud_hashes['md5'] = src_obj_metadata.md5Hash.rstrip('\n')
    if src_obj_metadata.crc32c:
      cloud_hashes['crc32c'] = src_obj_metadata.crc32c.rstrip('\n')

    for alg in local_hashes:
      if alg not in cloud_hashes:
        continue

      local_b64_digest = local_hashes[alg]
      cloud_b64_digest = cloud_hashes[alg]
      self.logger.debug('Comparing local vs cloud %s-checksum. (%s/%s)' % (
          alg, local_b64_digest, cloud_b64_digest))
      if local_b64_digest != cloud_b64_digest:
        raise CommandException(
            '%s signature computed for local file (%s) doesn\'t match '
            'cloud-supplied digest (%s). Local file (%s) deleted.' % (
                alg, local_b64_digest, cloud_b64_digest, file_name))

  def _CopyFileToFile(self, src_url, dst_url):
    """Copies a local file to a local file.

    Args:
      src_url: Source FileUrl.
      dst_url: Destination FileUrl.
    Returns:
      (elapsed_time, bytes_transferred, dst_url, md5=None).

    Raises:
      CommandException: if errors encountered.
    """
    self._LogCopyOperation(src_url, dst_url, None)
    src_fp = GetStreamFromFileUrl(src_url)
    dir_name = os.path.dirname(dst_url.object_name)
    if dir_name and not os.path.exists(dir_name):
      os.makedirs(dir_name)
    dst_fp = open(dst_url.object_name, 'wb')
    start_time = time.time()
    shutil.copyfileobj(src_fp, dst_fp)
    end_time = time.time()
    return (end_time - start_time, os.path.getsize(dst_url.object_name),
            dst_url, None)

  def _CopyObjToObjDaisyChainMode(self, src_url, src_obj_metadata, dst_url,
                                  dst_obj_metadata, preconditions, gsutil_api):
    """Copies from src_url to dst_url in "daisy chain" mode.
       See -D OPTION documentation about what daisy chain mode is.

    Args:
      src_url: Source CloudUrl
      src_obj_metadata: Metadata from source object
      dst_url: Destination CloudUrl
      dst_obj_metadata: Object-specific metadata that should be overidden during
                        the copy.
      preconditions: Preconditions to use for the copy.
      gsutil_api: gsutil Cloud API to use for the copy.

    Returns:
      (elapsed_time, bytes_transferred, dst_url with generation,
      md5 hash of destination) excluding overhead like initial GET.

    Raises:
      CommandException: if errors encountered.
    """
    # Preserve relevant metadata from the source object if it's not already
    # provided from the headers.
    CopyObjectMetadata(src_obj_metadata, dst_obj_metadata, override=False)
    self._LogCopyOperation(src_url, dst_url, dst_obj_metadata)

    # We don't attempt to preserve ACLs across providers because
    # GCS and S3 support different ACLs and disjoint principals.
    if self.preserve_acl and src_url.scheme != dst_url.scheme:
      raise NotImplementedError(
          'Cross-provider cp -p not supported')
    if not self.preserve_acl:
      dst_obj_metadata.acl = []

    # TODO: gsutil-beta: Fow now, download the file locally in its entirety,
    # then upload it.  Need to extend this to feature-parity with gsutil3
    # via a KeyFile-like implementation that works for both XML and JSON.
    resumable_tracker_dir = CreateTrackerDirIfNeeded()

    (download_fh, download_path) = tempfile.mkstemp(dir=resumable_tracker_dir)
    download_fp = None
    tempfile.mkstemp(dir=resumable_tracker_dir)
    try:
      # Check for temp space. Assume the compressed object is at most 2x
      # the size of the object (normally should compress to smaller than
      # the object)
      if (self._CheckFreeSpace(download_path)
          < 2*int(src_obj_metadata.size)):
        raise CommandException('Inadequate temp space available to temporarily '
                               'copy %s for daisy-chaining.' % src_url)
      download_fp = open(download_path, 'wb')

      serialization_dict = GetDownloadSerializationDict(src_obj_metadata)
      serialization_data = json.dumps(serialization_dict)

      start_time = time.time()
      gsutil_api.GetObjectMedia(src_url.bucket_name,
                                src_url.object_name,
                                download_fp,
                                provider=src_url.scheme,
                                serialization_data=serialization_data)
      download_fp.close()

      upload_fp = open(download_path, 'rb')
      uploaded_object = gsutil_api.UploadObject(
          upload_fp, object_metadata=dst_obj_metadata,
          preconditions=preconditions, provider=dst_url.scheme,
          fields=UPLOAD_RETURN_FIELDS, size=src_obj_metadata.size)

      end_time = time.time()
    finally:
      if download_fp:
        download_fp.close()
      if upload_fp:
        upload_fp.close()
      os.close(download_fh)
      if os.path.exists(download_path):
        os.unlink(download_path)

    result_url = dst_url.Clone()
    result_url.generation = uploaded_object.generation
    return (end_time - start_time, src_obj_metadata.size, result_url,
            uploaded_object.md5Hash)

  def _PerformCopy(self, src_url, dst_url, gsutil_api):
    """Performs copy from src_url to dst_url, handling various special cases.

    Args:
      src_url: Source StorageUrl.
      dst_url: Destination StorageUrl.
      gsutil_api: gsutil Cloud API instance to use for the copy.

    Returns:
      (elapsed_time, bytes_transferred, version-specific dst_url) excluding
      overhead like initial GET.

    Raises:
      ItemExistsError: if no clobber flag is specified and the destination
                       object already exists.
      CommandException: if other errors encountered.
    """
    if self.headers:
      dst_obj_headers = self.headers.copy()
    else:
      dst_obj_headers = {}

    # Create a metadata instance for each destination object so metadata
    # such as content-type can be applied per-object.
    # Initialize metadata from any headers passed in via -h.
    dst_obj_metadata = ObjectMetadataFromHeaders(dst_obj_headers)

    preconditions = PreconditionsFromHeaders(dst_obj_headers)

    src_obj_metadata = None
    src_obj_filestream = None
    if src_url.IsCloudUrl():
      src_obj_fields = None
      if dst_url.IsCloudUrl():
        # For cloud or daisy chain copy, we need every copyable field.
        # If we're not modifying or overriding any of the fields, we can get
        # away without retrieving the object metadata because the copy
        # operation can succeed with just the destination bucket and object
        # name.  But if we are sending any metadata, the JSON API will expect a
        # complete object resource.  Since we want metadata like the object size
        # for our own tracking, we just get all of the metadata here.
        src_obj_fields = ['cacheControl', 'componentCount',
                          'contentDisposition', 'contentEncoding',
                          'contentLanguage', 'contentType', 'crc32c',
                          'etag', 'generation', 'md5Hash', 'mediaLink',
                          'metadata', 'metageneration', 'size']
        # We only need the ACL if we're going to preserve it.
        if self.preserve_acl:
          src_obj_fields.append('acl')
        if src_url.scheme == dst_url.scheme and not self.daisy_chain:
          copy_in_the_cloud = True
        else:
          copy_in_the_cloud = False
      else:
        # Just get the fields needed to validate the download.
        src_obj_fields = ['crc32c', 'contentEncoding', 'contentType', 'etag',
                          'mediaLink', 'md5Hash', 'size']
      try:
        src_obj_metadata = gsutil_api.GetObjectMetadata(
            src_url.bucket_name, src_url.object_name,
            generation=src_url.generation, provider=src_url.scheme,
            fields=src_obj_fields)
      except NotFoundException:
        raise CommandException(
            'NotFoundException: Could not retrieve source object %s.' %
            src_url.GetUrlString())
      src_obj_size = src_obj_metadata.size
      dst_obj_metadata.contentType = src_obj_metadata.contentType
      if self.preserve_acl:
        dst_obj_metadata.acl = src_obj_metadata.acl
        # Special case for S3-to-S3 copy URLs using preserve_acl.
        # dst_url will be verified in _CopyObjToObjDaisyChainMode if it
        # is not s3 (and thus differs from src_url).
        if src_url.scheme == 's3':
          acl_text = S3MarkerAclFromObjectMetadata(src_obj_metadata)
          if acl_text:
            AddS3MarkerAclToObjectMetadata(dst_obj_metadata, acl_text)
    else:
      try:
        src_obj_filestream = GetStreamFromFileUrl(src_url)
      except:
        raise CommandException('"%s" does not exist.' % src_url)
      if src_url.IsStream():
        src_obj_size = None
      else:
        src_obj_size = os.path.getsize(src_url.object_name)

    if self.use_manifest:
      # Set the source size in the manifest.
      self.manifest.Set(src_url.GetUrlString(), 'size', src_obj_size)

    # On Windows, stdin is opened as text mode instead of binary which causes
    # problems when piping a binary file, so this switches it to binary mode.
    if IS_WINDOWS and src_url.IsFileUrl() and src_url.IsStream():
      msvcrt.setmode(GetStreamFromFileUrl(src_url).fileno(), os.O_BINARY)

    if self.no_clobber:
      # There are two checks to prevent clobbering:
      # 1) The first check is to see if the URL
      #    already exists at the destination and prevent the upload/download
      #    from happening. This is done by the exists() call.
      # 2) The second check is only relevant if we are writing to gs. We can
      #    enforce that the server only writes the object if it doesn't exist
      #    by specifying the header below. This check only happens at the
      #    server after the complete file has been uploaded. We specify this
      #    header to prevent a race condition where a destination file may
      #    be created after the first check and before the file is fully
      #    uploaded.
      # In order to save on unnecessary uploads/downloads we perform both
      # checks. However, this may come at the cost of additional HTTP calls.
      if preconditions.gen_match:
        raise ArgumentException('Specifying x-goog-if-generation-match is '
                                'not supported with cp -n')
      else:
        preconditions.gen_match = 0
      if dst_url.IsFileUrl() and os.path.exists(dst_url.object_name):
        # The local file may be a partial. Check the file sizes.
        if src_obj_size == os.path.getsize(dst_url.object_name):
          raise ItemExistsError()
      elif dst_url.IsCloudUrl():
        try:
          dst_object = gsutil_api.GetObjectMetadata(
              dst_url.bucket_name, dst_url.object_name, provider=dst_url.scheme)
        except NotFoundException:
          dst_object = None
        if dst_object:
          raise ItemExistsError()

    # Cloud storage API gets object and bucket name from metadata.
    dst_obj_metadata.name = dst_url.object_name
    dst_obj_metadata.bucket = dst_url.bucket_name

    if src_url.IsCloudUrl():
      if dst_url.IsFileUrl():
        return self._DownloadObjectToFile(src_url, src_obj_metadata, dst_url,
                                          gsutil_api)
      elif copy_in_the_cloud:
        return self._CopyObjToObjInTheCloud(src_url, src_obj_size, dst_url,
                                            dst_obj_metadata, preconditions,
                                            gsutil_api)
      else:
        return self._CopyObjToObjDaisyChainMode(src_url, src_obj_metadata,
                                                dst_url, dst_obj_metadata,
                                                preconditions, gsutil_api)
    else:  # src_url.IsFileUrl()
      if dst_url.IsCloudUrl():
        return self._UploadFileToObject(src_url, src_obj_filestream,
                                        src_obj_size, dst_url, dst_obj_metadata,
                                        preconditions, gsutil_api)
      else:  # dst_url.IsFileUrl()
        return self._CopyFileToFile(src_url, dst_url)

  # TODO: gsutil-beta: Port this function and other parallel upload functions,
  # then re-enable linting for it.
  # pylint: disable=undefined-variable
  def _PartitionFile(self, fp, file_size, src_uri, headers, canned_acl, bucket,
                     random_prefix, tracker_file, tracker_file_lock):
    """Partitions a file into FilePart objects to be uploaded and later composed
       into an object matching the original file. This entails splitting the
       file into parts, naming and forming a destination URI for each part,
       and also providing the PerformResumableUploadIfAppliesArgs object
       corresponding to each part.

       Args:
         fp: The file object to be partitioned.
         file_size: The size of fp, in bytes.
         src_uri: The source StorageUri fromed from the original command.
         headers: The headers which ultimately passed to boto.
         canned_acl: The user-provided canned_acl, if applicable.
         bucket: The name of the destination bucket, of the form gs://bucket
         random_prefix: The randomly-generated prefix used to prevent collisions
                        among the temporary component names.
         tracker_file: The path to the parallel composite upload tracker file.
         tracker_file_lock: The lock protecting access to the tracker file.

       Returns:
         dst_args: The destination URIs for the temporary component objects.
    """
    parallel_composite_upload_component_size = HumanReadableToBytes(
        boto.config.get('GSUtil', 'parallel_composite_upload_component_size',
                        DEFAULT_PARALLEL_COMPOSITE_UPLOAD_COMPONENT_SIZE))
    (num_components, component_size) = _GetPartitionInfo(
        file_size, MAX_COMPOSE_ARITY, parallel_composite_upload_component_size)

    # Make sure that the temporary objects don't already exist.
    tmp_object_headers = copy.deepcopy(headers)
    tmp_object_headers['x-goog-if-generation-match'] = '0'

    uri_strs = []  # Used to create a NameExpansionIterator.
    dst_args = {}  # Arguments to create commands and pass to subprocesses.
    file_names = []  # Used for the 2-step process of forming dst_args.
    for i in range(num_components):
      # "Salt" the object name with something a user is very unlikely to have
      # used in an object name, then hash the extended name to make sure
      # we don't run into problems with name length. Using a deterministic
      # naming scheme for the temporary components allows users to take
      # advantage of resumable uploads for each component.
      encoded_name = (PARALLEL_UPLOAD_STATIC_SALT + fp.name).encode('utf-8')
      content_md5 = md5()
      content_md5.update(encoded_name)
      digest = content_md5.hexdigest()
      temp_file_name = (random_prefix + PARALLEL_UPLOAD_TEMP_NAMESPACE +
                        digest + '_' + str(i))
      tmp_dst_uri = MakeGsUri(bucket, temp_file_name, self.suri_builder)

      if i < (num_components - 1):
        # Every component except possibly the last is the same size.
        file_part_length = component_size
      else:
        # The last component just gets all of the remaining bytes.
        file_part_length = (file_size - ((num_components -1) * component_size))
      offset = i * component_size
      func_args = PerformResumableUploadIfAppliesArgs(
          fp.name, offset, file_part_length, src_uri, tmp_dst_uri, canned_acl,
          headers, tracker_file, tracker_file_lock)
      file_names.append(temp_file_name)
      dst_args[temp_file_name] = func_args
      uri_strs.append(self._MakeGsUriStr(bucket, temp_file_name))

    return dst_args

  # TODO: gsutil-beta: Port this function and other parallel upload functions,
  # then re-enable linting for it.
  # pylint: disable=g-long-lambda,broad-except
  def _DoParallelCompositeUpload(self, fp, src_uri, dst_uri, headers,
                                 canned_acl, file_size):
    """Uploads a local file to an object in the cloud for the Parallel Composite
       Uploads feature. The file is partitioned into parts, and then the parts
       are uploaded in parallel, composed to form the original destination
       object, and deleted.

       Args:
         fp: The file object to be uploaded.
         src_uri: The StorageURI of the local file.
         dst_uri: The StorageURI of the destination file.
         headers: The headers to pass to boto, if any.
         canned_acl: The canned acl to apply to the object, if any.
         file_size: The size of the source file in bytes.
    """
    start_time = time.time()
    gs_prefix = 'gs://'
    bucket = gs_prefix + dst_uri.bucket_name
    if 'content-type' in headers and not headers['content-type']:
      del headers['content-type']

    # Determine which components, if any, have already been successfully
    # uploaded.
    tracker_file = self._GetTrackerFilePath(dst_uri,
                                            TrackerFileType.PARALLEL_UPLOAD,
                                            src_uri)
    tracker_file_lock = CreateLock()
    (random_prefix, existing_components) = (
        _ParseParallelUploadTrackerFile(tracker_file, tracker_file_lock))

    # Create the initial tracker file for the upload.
    _CreateParallelUploadTrackerFile(tracker_file, random_prefix,
                                     existing_components, tracker_file_lock)

    # Get the set of all components that should be uploaded.
    dst_args = self._PartitionFile(fp, file_size, src_uri, headers, canned_acl,
                                   bucket, random_prefix, tracker_file,
                                   tracker_file_lock)

    (components_to_upload, existing_components, existing_objects_to_delete) = (
        FilterExistingComponents(dst_args, existing_components, bucket,
                                 self.suri_builder))

    # In parallel, copy all of the file parts that haven't already been
    # uploaded to temporary objects.
    cp_results = self.Apply(_PerformResumableUploadIfAppliesWrapper,
                            components_to_upload,
                            _CopyExceptionHandler,
                            ('copy_failure_count', 'total_bytes_transferred'),
                            arg_checker=gslib.command.DummyArgChecker,
                            parallel_operations_override=True,
                            should_return_results=True)
    uploaded_components = []
    total_bytes_uploaded = 0
    for cp_result in cp_results:
      total_bytes_uploaded += cp_result[1]
      uploaded_components.append(cp_result[2])
    components = uploaded_components + existing_components

    if len(components) == len(dst_args):
      # Only try to compose if all of the components were uploaded successfully.

      # Sort the components so that they will be composed in the correct order.
      components = sorted(
          components, key=lambda component:
          int(component.object_name[component.object_name.rfind('_')+1:]))
      result_uri = dst_uri.compose(components, headers=headers)

      try:
        # Make sure only to delete things that we know were successfully
        # uploaded (as opposed to all of the objects that we attempted to
        # create) so that we don't delete any preexisting objects, except for
        # those that were uploaded by a previous, failed run and have since
        # changed (but still have an old generation lying around).
        objects_to_delete = components + existing_objects_to_delete
        self.Apply(_DeleteKeyFn, objects_to_delete, _RmExceptionHandler,
                   arg_checker=gslib.command.DummyArgChecker,
                   parallel_operations_override=True)
      except Exception, e:
        if (e.message and ('unexpected failure in' in e.message)
            and ('sub-processes, aborting' in e.message)):
          # If some of the delete calls fail, don't cause the whole command to
          # fail. The copy was successful iff the compose call succeeded, so
          # just raise whatever exception (if any) happened before this instead,
          # and reduce this to a warning.
          logging.warning(
              'Failed to delete some of the following temporary objects:\n' +
              '\n'.join(dst_args.keys()))
        else:
          raise e
      finally:
        with tracker_file_lock:
          if os.path.exists(tracker_file):
            os.unlink(tracker_file)
    else:
      # Some of the components failed to upload. In this case, we want to exit
      # without deleting the objects.
      raise CommandException(
          'Some temporary components were not uploaded successfully. '
          'Please retry this upload.')

    return (time.time() - start_time, total_bytes_uploaded, result_uri)

  def _ShouldDoParallelCompositeUpload(self, allow_splitting, src_key, dst_uri,
                                       file_size):
    """Returns True iff a parallel upload should be performed on the source key.

       Args:
         allow_splitting: If false, then this function returns false.
         src_key: Corresponding to a local file.
         dst_uri: Corresponding to an object in the cloud.
         file_size: The size of the source file, in bytes.
    """
    parallel_composite_upload_threshold = HumanReadableToBytes(boto.config.get(
        'GSUtil', 'parallel_composite_upload_threshold',
        DEFAULT_PARALLEL_COMPOSITE_UPLOAD_THRESHOLD))
    return (allow_splitting  # Don't split the pieces multiple times.
            and not src_key.is_stream()  # We can't partition streams.
            and dst_uri.scheme == 'gs'  # Compose is only for gs.
            and parallel_composite_upload_threshold > 0
            and file_size >= parallel_composite_upload_threshold
            and file_size >= MIN_PARALLEL_COMPOSITE_FILE_SIZE)

  # TODO: Move this and other naming functions to a convenience class as part
  # of a cp refactor.
  def _ExpandDstUrl(self, dst_url_str):
    """Expands wildcard if present in dst_url_str.

    Args:
      dst_url_str: String representation of requested dst_url.

    Returns:
        (exp_dst_url, have_existing_dst_container)
        where exp_dst_url is a StorageUrl
        and have_existing_dst_container is a bool indicating whether
        exp_dst_url names an existing directory, bucket, or bucket subdirectory.
        In the case where we match a subdirectory AND an object, the
        subdirectory is returned.

    Raises:
      CommandException: if dst_url_str matched more than 1 URL.
    """
    # Handle wildcarded dst_url case.
    if ContainsWildcard(dst_url_str):
      blr_expansion = list(self.WildcardIterator(dst_url_str))
      if len(blr_expansion) != 1:
        raise CommandException('Destination (%s) must match exactly 1 URL' %
                               dst_url_str)
      blr = blr_expansion[0]
      # BLR is either an OBJECT, PREFIX, or BUCKET; the latter two represent
      # directories.
      return (StorageUrlFromString(blr.url_string),
              blr.ref_type != BucketListingRefType.OBJECT)

    storage_url = StorageUrlFromString(dst_url_str)

    # Handle non-wildcarded dst_url:
    if storage_url.IsFileUrl():
      return (storage_url, storage_url.IsDirectory())

    # At this point we have a cloud URL.
    if storage_url.IsBucket():
      return (storage_url, True)

    # For object/prefix URLs check 3 cases: (a) if the name ends with '/' treat
    # as a subdir; otherwise, use the wildcard iterator with dst_url to
    # find if (b) there's a Prefix matching dst_url, or (c) name is of form
    # dir_$folder$ (and in both these cases also treat dir as a subdir).
    # Cloud subdirs are always considered to be an existing container.
    if dst_url_str.endswith('/'):
      return (storage_url, True)

    # Check for the special case where we have a folder marker object
    folder_expansion = self.WildcardIterator(
        dst_url_str + '_$folder$').IterAll()
    for blr in folder_expansion:
      return (storage_url, True)

    blr_expansion = self.WildcardIterator(dst_url_str).IterAll()
    for blr in blr_expansion:
      if blr.ref_type == BucketListingRefType.PREFIX:
        return (storage_url, True)

    return (storage_url, False)

  def _ConstructDstUrl(self, src_url, exp_src_url,
                       src_url_names_container, src_url_expands_to_multi,
                       have_multiple_srcs, exp_dst_url,
                       have_existing_dest_subdir):
    """Constructs the destination URL for a given exp_src_url/exp_dst_url pair.

    Uses context-dependent naming rules that mimic Linux cp and mv behavior.

    Args:
      src_url: Source StorageUrl to be copied.
      exp_src_url: Single StorageUrl from wildcard expansion of src_url.
      src_url_names_container: True if src_url names a container (including the
          case of a wildcard-named bucket subdir (like gs://bucket/abc,
          where gs://bucket/abc/* matched some objects).
      src_url_expands_to_multi: True if src_url expanded to multiple URLs.
      have_multiple_srcs: True if this is a multi-source request. This can be
          true if src_url wildcard-expanded to multiple URLs or if there were
          multiple source URLs in the request.
      exp_dst_url: the expanded StorageUrl requested for the cp destination.
          Final written path is constructed from this plus a context-dependent
          variant of src_url.
      have_existing_dest_subdir: bool indicator whether dest is an existing
        subdirectory.

    Returns:
      StorageUrl to use for copy.

    Raises:
      CommandException if destination object name not specified for
      source and source is a stream.
    """
    if self._ShouldTreatDstUrlAsSingleton(
        have_multiple_srcs, have_existing_dest_subdir, exp_dst_url):
      # We're copying one file or object to one file or object.
      return exp_dst_url

    if exp_src_url.IsFileUrl() and exp_src_url.IsStream():
      if have_existing_dest_subdir:
        raise CommandException('Destination object name needed when '
                               'source is a stream')
      return exp_dst_url

    if not self.recursion_requested and not have_multiple_srcs:
      # We're copying one file or object to a subdirectory. Append final comp
      # of exp_src_url to exp_dst_url.
      src_final_comp = exp_src_url.object_name.rpartition(src_url.delim)[-1]
      return StorageUrlFromString('%s%s%s' % (
          exp_dst_url.GetUrlString().rstrip(exp_dst_url.delim),
          exp_dst_url.delim, src_final_comp))

    # Else we're copying multiple sources to a directory, bucket, or a bucket
    # "sub-directory".

    # Ensure exp_dst_url ends in delim char if we're doing a multi-src copy or
    # a copy to a directory. (The check for copying to a directory needs
    # special-case handling so that the command:
    #   gsutil cp gs://bucket/obj dir
    # will turn into file://dir/ instead of file://dir -- the latter would cause
    # the file "dirobj" to be created.)
    # Note: need to check have_multiple_srcs or src_url.names_container()
    # because src_url could be a bucket containing a single object, named
    # as gs://bucket.
    if ((have_multiple_srcs or src_url_names_container or
         (exp_dst_url.IsFileUrl() and exp_dst_url.IsDirectory()))
        and not exp_dst_url.GetUrlString().endswith(exp_dst_url.delim)):
      exp_dst_url = StorageUrlFromString('%s%s' % (exp_dst_url.GetUrlString(),
                                                   exp_dst_url.delim))

    # Making naming behavior match how things work with local Linux cp and mv
    # operations depends on many factors, including whether the destination is a
    # container, the plurality of the source(s), and whether the mv command is
    # being used:
    # 1. For the "mv" command that specifies a non-existent destination subdir,
    #    renaming should occur at the level of the src subdir, vs appending that
    #    subdir beneath the dst subdir like is done for copying. For example:
    #      gsutil rm -R gs://bucket
    #      gsutil cp -R dir1 gs://bucket
    #      gsutil cp -R dir2 gs://bucket/subdir1
    #      gsutil mv gs://bucket/subdir1 gs://bucket/subdir2
    #    would (if using cp naming behavior) end up with paths like:
    #      gs://bucket/subdir2/subdir1/dir2/.svn/all-wcprops
    #    whereas mv naming behavior should result in:
    #      gs://bucket/subdir2/dir2/.svn/all-wcprops
    # 2. Copying from directories, buckets, or bucket subdirs should result in
    #    objects/files mirroring the source directory hierarchy. For example:
    #      gsutil cp dir1/dir2 gs://bucket
    #    should create the object gs://bucket/dir2/file2, assuming dir1/dir2
    #    contains file2).
    #    To be consistent with Linux cp behavior, there's one more wrinkle when
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

    recursive_move_to_new_subdir = False
    if (self.perform_mv and self.recursion_requested
        and src_url_expands_to_multi and not have_existing_dest_subdir):
      # Case 1. Handle naming rules for bucket subdir mv. Here we want to
      # line up the src_url against its expansion, to find the base to build
      # the new name. For example, running the command:
      #   gsutil mv gs://bucket/abcd gs://bucket/xyz
      # when processing exp_src_url=gs://bucket/abcd/123
      # exp_src_url_tail should become /123
      # Note: mv.py code disallows wildcard specification of source URL.
      recursive_move_to_new_subdir = True
      exp_src_url_tail = (
          exp_src_url.GetUrlString()[len(src_url.GetUrlString()):])
      dst_key_name = '%s/%s' % (exp_dst_url.object_name.rstrip('/'),
                                exp_src_url_tail.strip('/'))

    elif src_url_names_container and (exp_dst_url.IsCloudUrl() or
                                      exp_dst_url.IsDirectory()):
      # Case 2.  Container copy to a destination other than a file.
      # Build dst_key_name from subpath of exp_src_url past
      # where src_url ends. For example, for src_url=gs://bucket/ and
      # exp_src_url=gs://bucket/src_subdir/obj, dst_key_name should be
      # src_subdir/obj.
      src_url_path_sans_final_dir = GetPathBeforeFinalDir(src_url)
      dst_key_name = exp_src_url.GetVersionlessUrlString()[
          len(src_url_path_sans_final_dir):].lstrip(src_url.delim)
      # Handle case where dst_url is a non-existent subdir.
      if not have_existing_dest_subdir:
        dst_key_name = dst_key_name.partition(src_url.delim)[-1]
      # Handle special case where src_url was a directory named with '.' or
      # './', so that running a command like:
      #   gsutil cp -r . gs://dest
      # will produce obj names of the form gs://dest/abc instead of
      # gs://dest/./abc.
      if dst_key_name.startswith('.%s' % os.sep):
        dst_key_name = dst_key_name[2:]

    else:
      # Case 3.
      dst_key_name = exp_src_url.object_name.rpartition(src_url.delim)[-1]

    if (not recursive_move_to_new_subdir and (
        exp_dst_url.IsFileUrl() or self._ShouldTreatDstUrlAsBucketSubDir(
            have_multiple_srcs, exp_dst_url, have_existing_dest_subdir))):
      if exp_dst_url.object_name and exp_dst_url.object_name.endswith(
          exp_dst_url.delim):
        dst_key_name = '%s%s%s' % (
            exp_dst_url.object_name.rstrip(exp_dst_url.delim),
            exp_dst_url.delim, dst_key_name)
      else:
        delim = exp_dst_url.delim if exp_dst_url.object_name else ''
        dst_key_name = '%s%s%s' % (exp_dst_url.object_name or '',
                                   delim, dst_key_name)

    new_exp_dst_url = exp_dst_url.Clone()
    new_exp_dst_url.object_name = dst_key_name
    return new_exp_dst_url

  def _FixWindowsNaming(self, src_url, dst_url):
    """Translates Windows pathnames to cloud pathnames.

    Rewrites the destination URL built by _ConstructDstUrl().

    Args:
      src_url: Source StorageUrl to be copied.
      dst_url: The destination StorageUrl built by _ConstructDstUrl().

    Returns:
      StorageUrl to use for copy.
    """
    if (src_url.IsFileUrl() and src_url.delim == '\\'
        and dst_url.IsCloudUrl()):
      trans_url_str = re.sub(r'\\', '/', dst_url.GetUrlString())
      dst_url = StorageUrlFromString(trans_url_str)
    return dst_url

  def _CopyExceptionHandler(self, e):
    """Simple exception handler to allow post-completion status."""
    self.logger.error(str(e))
    self.copy_failure_count += 1
    self.logger.debug(('\n\nEncountered exception while copying:\n%s\n' %
                       traceback.format_exc()))

  def _RmExceptionHandler(self, e):
    """Simple exception handler to allow post-completion status."""
    self.logger.error(str(e))

  def CopyFunc(self, name_expansion_result, thread_state=None):
    """Worker function for performing the actual copy (and rm, for mv)."""
    gsutil_api = GetCloudApiInstance(self, thread_state=thread_state)
    exp_dst_url = self.exp_dst_url
    have_existing_dst_container = self.have_existing_dst_container

    if self.perform_mv:
      cmd_name = 'mv'
    else:
      cmd_name = self.command_name
    src_url_str = name_expansion_result.GetSrcUrlStr()
    src_url = StorageUrlFromString(src_url_str)
    exp_src_url_str = name_expansion_result.GetExpandedUrlStr()
    exp_src_url = StorageUrlFromString(exp_src_url_str)
    src_url_names_container = name_expansion_result.NamesContainer()
    src_url_expands_to_multi = name_expansion_result.NamesContainer()
    have_multiple_srcs = name_expansion_result.IsMultiSrcRequest()
    have_existing_dest_subdir = (
        name_expansion_result.HaveExistingDstContainer())

    if src_url.IsCloudUrl() and src_url.IsProvider():
      raise CommandException(
          'The %s command does not allow provider-only source URLs (%s)' %
          (cmd_name, src_url))
    if have_multiple_srcs:
      self._InsistDstUrlNamesContainer(exp_dst_url,
                                       have_existing_dst_container,
                                       cmd_name)

    if self.use_manifest and self.manifest.WasSuccessful(
        exp_src_url.GetUrlString()):
      return

    if self.perform_mv:
      if name_expansion_result.NamesContainer():
        # Use recursion_requested when performing name expansion for the
        # directory mv case so we can determine if any of the source URLs are
        # directories (and then use cp -R and rm -R to perform the move, to
        # match the behavior of Linux mv (which when moving a directory moves
        # all the contained files).
        self.recursion_requested = True
        # Disallow wildcard src URLs when moving directories, as supporting it
        # would make the name transformation too complex and would also be
        # dangerous (e.g., someone could accidentally move many objects to the
        # wrong name, or accidentally overwrite many objects).
        if ContainsWildcard(src_url_str):
          raise CommandException('The mv command disallows naming source '
                                 'directories using wildcards')

    if (exp_dst_url.IsFileUrl()
        and not os.path.exists(exp_dst_url.object_name)
        and have_multiple_srcs):
      os.makedirs(exp_dst_url.object_name)

    dst_url = self._ConstructDstUrl(src_url, exp_src_url,
                                    src_url_names_container,
                                    src_url_expands_to_multi,
                                    have_multiple_srcs, exp_dst_url,
                                    have_existing_dest_subdir)
    dst_url = self._FixWindowsNaming(src_url, dst_url)

    self._CheckForDirFileConflict(exp_src_url, dst_url)
    if self._SrcDstSame(exp_src_url, dst_url):
      raise CommandException('%s: "%s" and "%s" are the same file - '
                             'abort.' % (cmd_name,
                                         exp_src_url.GetUrlString(),
                                         dst_url.GetUrlString()))

    if dst_url.IsCloudUrl() and dst_url.HasGeneration():
      raise CommandException('%s: a version-specific URL\n(%s)\ncannot be '
                             'the destination for gsutil cp - abort.'
                             % (cmd_name, dst_url.GetUrlString()))

    elapsed_time = bytes_transferred = 0
    try:
      if self.use_manifest:
        self.manifest.Initialize(exp_src_url.GetUrlString(),
                                 dst_url.GetUrlString())
      (elapsed_time, bytes_transferred, result_url, md5) = (
          self._PerformCopy(exp_src_url, dst_url, gsutil_api))
      if self.use_manifest:
        if md5:
          self.manifest.Set(exp_src_url.GetUrlString(), 'md5', md5)
        self.manifest.SetResult(exp_src_url.GetUrlString(), bytes_transferred,
                                'OK')
    except ItemExistsError:
      message = 'Skipping existing item: %s' % dst_url.GetUrlString()
      self.logger.info(message)
      if self.use_manifest:
        self.manifest.SetResult(exp_src_url.GetUrlString(), 0, 'skip', message)
    except Exception, e:
      if self._IsNoClobberServerException(e):
        message = 'Rejected (noclobber): %s' % dst_url.GetUrlString()
        self.logger.info(message)
        if self.use_manifest:
          self.manifest.SetResult(exp_src_url.GetUrlString(), 0, 'skip',
                                  message)
      elif self.continue_on_error:
        message = 'Error copying %s: %s' % (src_url.GetUrlString(), str(e))
        self.copy_failure_count += 1
        self.logger.error(message)
        if self.use_manifest:
          self.manifest.SetResult(exp_src_url.GetUrlString(), 0, 'error',
                                  message)
      else:
        if self.use_manifest:
          self.manifest.SetResult(exp_src_url.GetUrlString(), 0, 'error',
                                  str(e))
        raise

    if self.print_ver:
      # Some cases don't return a version-specific URL (e.g., if destination
      # is a file).
      self.logger.info('Created: %s' % result_url.GetUrlString())

    if self.canned_acl:
      # Package up destination URL in a NameExpansionResult so SetAclFunc
      # can operate on it.  All that is used is the blr to get the URL string.
      dst_blr = BucketListingRef(dst_url.GetUrlString(),
                                 BucketListingRefType.OBJECT)
      dst_name_ex_result = NameExpansionResult('', False, False, False, dst_blr,
                                               have_existing_dst_container=None)
      self.SetAclFunc(dst_name_ex_result, thread_state=thread_state)

    # TODO: If we ever use -n (noclobber) with -M (move) (not possible today
    # since we call copy internally from move and don't specify the -n flag)
    # we'll need to only remove the source when we have not skipped the
    # destination.
    if self.perform_mv:
      self.logger.info('Removing %s...', exp_src_url)
      if exp_src_url.IsCloudUrl():
        gsutil_api.DeleteObject(exp_src_url.bucket_name,
                                exp_src_url.object_name,
                                generation=exp_src_url.generation,
                                provider=exp_src_url.scheme)
      else:
        os.unlink(exp_src_url.object_name)

    with self.stats_lock:
      self.total_elapsed_time += elapsed_time
      self.total_bytes_transferred += bytes_transferred

  # Command entry point.
  def RunCommand(self):
    self._ParseArgs()

    self.total_elapsed_time = self.total_bytes_transferred = 0
    if self.args[-1] == '-' or self.args[-1] == 'file://-':
      return self._HandleStreamingDownload()

    if self.read_args_from_stdin:
      if len(self.args) != 1:
        raise CommandException('Source URLs cannot be specified with -I option')
      url_strs = self._StdinIterator()
    else:
      if len(self.args) < 2:
        raise CommandException('Wrong number of arguments for "cp" command.')
      url_strs = self.args[:-1]

    (exp_dst_url, have_existing_dst_container) = self._ExpandDstUrl(
        self.args[-1])

    # If the destination bucket has versioning enabled iterate with
    # all_versions=True. That way we'll copy all versions if the source bucket
    # is versioned; and by leaving all_versions=False if the destination bucket
    # has versioning disabled we will avoid copying old versions all to the same
    # un-versioned destination object.
    all_versions = False
    try:
      bucket = self._GetBucketWithVersioningConfig(exp_dst_url)
      if bucket and bucket.versioning and bucket.versioning.enabled:
        all_versions = True
    except AccessDeniedException:
      # This happens (in the XML API only) if the user doesn't have OWNER access
      # on the bucket (needed to check if versioning is enabled). In this case
      # fall back to copying all versions (which can be inefficient for the
      # reason noted in the comment above). We don't try to warn the user
      # because that would result in false positive warnings (since we can't
      # check if versioning is enabled on the destination bucket).
      #
      # For JSON, we will silently not return versioning if we don't have
      # access.
      all_versions = True

    name_expansion_iterator = NameExpansionIterator(
        self.command_name, self.debug,
        self.logger, self.gsutil_api, url_strs,
        self.recursion_requested or self.perform_mv,
        have_existing_dst_container=have_existing_dst_container,
        project_id=self.project_id, all_versions=all_versions)
    self.have_existing_dst_container = have_existing_dst_container
    self.exp_dst_url = exp_dst_url
    self.resumable_threshold = config.getint('GSUtil', 'resumable_threshold',
                                             TWO_MB)

    # Use a lock to ensure accurate statistics in the face of
    # multi-threading/multi-processing.
    self.stats_lock = CreateLock()

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
    self.Apply(_CopyFuncWrapper, name_expansion_iterator,
               _CopyExceptionHandler, shared_attrs, fail_on_error=True)
    self.logger.debug(
        'total_bytes_transferred: %d', self.total_bytes_transferred)

    end_time = time.time()
    self.total_elapsed_time = end_time - start_time

    # Sometimes, particularly when running unit tests, the total elapsed time
    # is really small. On Windows, the timer resolution is too small and
    # causes total_elapsed_time to be zero.
    try:
      float(self.total_bytes_transferred) / float(self.total_elapsed_time)
    except ZeroDivisionError:
      self.total_elapsed_time = 0.01

    self.total_bytes_per_second = (float(self.total_bytes_transferred) /
                                   float(self.total_elapsed_time))

    if self.debug == 3:
      # Note that this only counts the actual GET and PUT bytes for the copy
      # - not any transfers for doing wildcard expansion, the initial
      # HEAD/GET request performed to get the object metadata, etc.
      if self.total_bytes_transferred != 0:
        self.logger.info(
            'Total bytes copied=%d, total elapsed time=%5.3f secs (%sps)',
            self.total_bytes_transferred, self.total_elapsed_time,
            MakeHumanReadable(self.total_bytes_per_second))
    if self.copy_failure_count:
      plural_str = ''
      if self.copy_failure_count > 1:
        plural_str = 's'
      raise CommandException('%d file%s/object%s could not be transferred.' % (
          self.copy_failure_count, plural_str, plural_str))

    return 0

  def _ParseArgs(self):
    self.perform_mv = False
    self.exclude_symlinks = False
    self.no_clobber = False
    self.continue_on_error = False
    self.daisy_chain = False
    self.read_args_from_stdin = False
    self.print_ver = False
    self.use_manifest = False
    self.preserve_acl = False
    self.canned_acl = None

    # self.recursion_requested initialized in command.py (so can be checked
    # in parent class for all commands).
    if self.sub_opts:
      for o, a in self.sub_opts:
        if o == '-a':
          self.canned_acl = a
          # For Command helper func.
          self.canned = True
          self.def_acl = False
          self.acl_arg = a
        if o == '-c':
          self.continue_on_error = True
        elif o == '-D':
          self.daisy_chain = True
        elif o == '-e':
          self.exclude_symlinks = True
        elif o == '-I':
          self.read_args_from_stdin = True
        elif o == '-L':
          self.use_manifest = True
          self.manifest = _Manifest(a)
        elif o == '-M':
          # Note that we signal to the cp command to perform a move (copy
          # followed by remove) and use directory-move naming rules by passing
          # the undocumented (for internal use) -M option when running the cp
          # command from mv.py.
          self.perform_mv = True
        elif o == '-n':
          self.no_clobber = True
        if o == '-p':
          self.preserve_acl = True
        elif o == '-q':
          self.logger.warning(
              'Warning: gsutil cp -q is deprecated, and will be removed in the '
              'future.\nPlease use gsutil -q cp ... instead.')
          self.logger.setLevel(level=logging.WARNING)
        elif o == '-r' or o == '-R':
          self.recursion_requested = True
        elif o == '-v':
          self.print_ver = True
    if self.preserve_acl and self.canned_acl:
      raise CommandException(
          'Specifying both the -p and -a options together is invalid.')

  def _HandleStreamingDownload(self):
    # Destination is <STDOUT>.
    return CatHelper(self).CatUrlStrings(self.args[:-1])

  def _StdinIterator(self):
    """A generator function that returns lines from stdin."""
    for line in sys.stdin:
      # Strip CRLF.
      yield line.rstrip()

  def _SrcDstSame(self, src_url, dst_url):
    """Checks if src_url and dst_url represent the same object or file.

    We don't handle anything about hard or symbolic links.

    Args:
      src_url: Source StorageUrl.
      dst_url: Destination StorageUrl.

    Returns:
      Bool indicator.
    """
    if src_url.IsFileUrl() and dst_url.IsFileUrl():
      # Translate a/b/./c to a/b/c, so src=dst comparison below works.
      new_src_path = os.path.normpath(src_url.object_name)
      new_dst_path = os.path.normpath(dst_url.object_name)
      return new_src_path == new_dst_path
    else:
      return (src_url.GetUrlString() == dst_url.GetUrlString() and
              src_url.generation == dst_url.generation)

  def _ShouldTreatDstUrlAsBucketSubDir(self, have_multiple_srcs, dst_url,
                                       have_existing_dest_subdir):
    """Checks whether dst_url should be treated as a bucket "sub-directory".

    The decision about whether something constitutes a bucket "sub-directory"
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
    already an object at that URL. For example it's legitimate (albeit
    confusing) to have an object called gs://bucket/dir and
    then run the command
    gsutil cp file1 file2 gs://bucket/dir
    Doing so will end up with objects gs://bucket/dir, gs://bucket/dir/file1,
    and gs://bucket/dir/file2.

    Args:
      have_multiple_srcs: Bool indicator of whether this is a multi-source
          operation.
      dst_url: StorageUrl to check.
      have_existing_dest_subdir: bool indicator whether dest is an existing
        subdirectory.

    Returns:
      bool indicator.
    """
    return ((have_multiple_srcs and dst_url.IsCloudUrl())
            or (have_existing_dest_subdir))

  def _ShouldTreatDstUrlAsSingleton(self, have_multiple_srcs,
                                    have_existing_dest_subdir, dst_url):
    """Checks that dst_url names a single file/object after wildcard expansion.

    It is possible that an object path might name a bucket sub-directory.

    Args:
      have_multiple_srcs: Bool indicator of whether this is a multi-source
          operation.
      have_existing_dest_subdir: bool indicator whether dest is an existing
        subdirectory.
      dst_url: StorageUrl to check.

    Returns:
      bool indicator.
    """
    if dst_url.IsFileUrl():
      return not dst_url.IsDirectory()
    else:  # dst_url.IsCloudUrl()
      return (not have_multiple_srcs and
              not have_existing_dest_subdir and
              dst_url.IsObject())

  def _IsNoClobberServerException(self, e):
    """Checks to see if the server attempted to clobber a file.

    In this case we specified via a precondition that we didn't want the file
    clobbered.

    Args:
      e: The Exception that was generated by a failed copy operation

    Returns:
      bool indicator - True indicates that the server did attempt to clobber
          an existing file.
    """
    return self.no_clobber and (
        (isinstance(e, PreconditionException)) or
        (isinstance(e, ResumableUploadException) and '412' in e.message))


class _Manifest(object):
  """Stores the manifest items for the CpCommand class."""

  def __init__(self, path):
    # self.items contains a dictionary of rows
    self.items = {}
    self.manifest_filter = {}
    self.lock = CreateLock()

    self.manifest_path = os.path.expanduser(path)
    self._ParseManifest()
    self._CreateManifestFile()

  def _ParseManifest(self):
    """Load and parse a manifest file.

    This information will be used to skip any files that have a skip or OK
    status.
    """
    try:
      if os.path.exists(self.manifest_path):
        with open(self.manifest_path, 'rb') as f:
          first_row = True
          reader = csv.reader(f)
          for row in reader:
            if first_row:
              try:
                source_index = row.index('Source')
                result_index = row.index('Result')
              except ValueError:
                # No header and thus not a valid manifest file.
                raise CommandException(
                    'Missing headers in manifest file: %s' % self.manifest_path)
            first_row = False
            source = row[source_index]
            result = row[result_index]
            if result in ['OK', 'skip']:
              # We're always guaranteed to take the last result of a specific
              # source url.
              self.manifest_filter[source] = result
    except IOError:
      raise CommandException('Could not parse %s' % self.manifest_path)

  def WasSuccessful(self, src):
    """Returns whether the specified src url was marked as successful."""
    return src in self.manifest_filter

  def _CreateManifestFile(self):
    """Opens the manifest file and assigns it to the file pointer."""
    try:
      if ((not os.path.exists(self.manifest_path))
          or (os.stat(self.manifest_path).st_size == 0)):
        # Add headers to the new file.
        with open(self.manifest_path, 'wb', 1) as f:
          writer = csv.writer(f)
          writer.writerow(['Source',
                           'Destination',
                           'Start',
                           'End',
                           'Md5',
                           'UploadId',
                           'Source Size',
                           'Bytes Transferred',
                           'Result',
                           'Description'])
    except IOError:
      raise CommandException('Could not create manifest file.')

  def Set(self, url, key, value):
    if value is None:
      # In case we don't have any information to set we bail out here.
      # This is so that we don't clobber existing information.
      # To zero information pass '' instead of None.
      return
    if url in self.items:
      self.items[url][key] = value
    else:
      self.items[url] = {key: value}

  def Initialize(self, source_url, destination_url):
    # Always use the source_url as the key for the item. This is unique.
    self.Set(source_url, 'source_uri', source_url)
    self.Set(source_url, 'destination_uri', destination_url)
    self.Set(source_url, 'start_time', datetime.datetime.utcnow())

  def SetResult(self, source_url, bytes_transferred, result,
                description=''):
    self.Set(source_url, 'bytes', bytes_transferred)
    self.Set(source_url, 'result', result)
    self.Set(source_url, 'description', description)
    self.Set(source_url, 'end_time', datetime.datetime.utcnow())
    self._WriteRowToManifestFile(source_url)
    self._RemoveItemFromManifest(source_url)

  def _WriteRowToManifestFile(self, url):
    """Writes a manifest entry to the manifest file for the url argument."""
    row_item = self.items[url]
    data = [
        str(row_item['source_uri']),
        str(row_item['destination_uri']),
        '%sZ' % row_item['start_time'].isoformat(),
        '%sZ' % row_item['end_time'].isoformat(),
        row_item['md5'] if 'md5' in row_item else '',
        row_item['upload_id'] if 'upload_id' in row_item else '',
        str(row_item['size']) if 'size' in row_item else '',
        str(row_item['bytes']) if 'bytes' in row_item else '',
        row_item['result'],
        row_item['description']]

    # Aquire a lock to prevent multiple threads writing to the same file at
    # the same time. This would cause a garbled mess in the manifest file.
    with self.lock:
      with open(self.manifest_path, 'a', 1) as f:  # 1 == line buffered
        writer = csv.writer(f)
        writer.writerow(data)

  def _RemoveItemFromManifest(self, url):
    # Remove the item from the dictionary since we're done with it and
    # we don't want the dictionary to grow too large in memory for no good
    # reason.
    del self.items[url]


class ItemExistsError(Exception):
  """Exception class for objects that are skipped because they already exist."""
  pass


def GetPathBeforeFinalDir(url):
  """Returns the path section before the final directory component of the URL.

  This handles cases for file system directories, bucket, and bucket
  subdirectories. Example: for gs://bucket/dir/ we'll return 'gs://bucket',
  and for file://dir we'll return file://

  Args:
    url: StorageUrl representing a filesystem directory, cloud bucket or
         bucket subdir.

  Returns:
    String name of above-described path, sans final path separator.
  """
  sep = url.delim
  if url.IsFileUrl():
    past_scheme = url.GetUrlString()[len('file://'):]
    if past_scheme.find(sep) == -1:
      return 'file://'
    else:
      return 'file://%s' % past_scheme.rstrip(sep).rpartition(sep)[0]
  if url.IsBucket():
    return '%s://' % url.scheme
  # Else it names a bucket subdir.
  return url.GetUrlString().rstrip(sep).rpartition(sep)[0]


def _HashFilename(filename):
  """Apply a hash function (SHA1) to shorten the passed file name.

  The spec for the hashed file name is as follows:

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
  if isinstance(filename, unicode):
    filename = filename.encode(UTF8)
  else:
    filename = unicode(filename, UTF8).encode(UTF8)
  m = hashlib.sha1(filename)
  return 'TRACKER_' + m.hexdigest() + '.' + filename[-16:]


def _DivideAndCeil(dividend, divisor):
  """Returns ceil(dividend / divisor).

  Takes care to avoid the pitfalls of floating point arithmetic that could
  otherwise yield the wrong result for large numbers.

  Args:
    dividend: Dividend for the operation.
    divisor: Divisor for the operation.

  Returns:
    Quotient.
  """
  quotient = dividend // divisor
  if (dividend % divisor) != 0:
    quotient += 1
  return quotient


# TODO: gsutil-beta: Port this function and other parallel upload functions.
def _GetPartitionInfo(file_size, max_components, default_component_size):
  """Gets info about a file partition for parallel composite uploads.

  Args:
    file_size: The number of bytes in the file to be partitioned.
    max_components: The maximum number of components that can be composed.
    default_component_size: The size of a component, assuming that
                            max_components is infinite.
  Returns:
    The number of components in the partitioned file, and the size of each
    component (except the last, which will have a different size iff
    file_size != 0 (mod num_components)).
  """
  # num_components = ceil(file_size / default_component_size)
  num_components = _DivideAndCeil(file_size, default_component_size)

  # num_components must be in the range [2, max_components]
  num_components = max(min(num_components, max_components), 2)

  # component_size = ceil(file_size / num_components)
  component_size = _DivideAndCeil(file_size, num_components)
  return (num_components, component_size)


# TODO: gsutil-beta: Port this function and other parallel upload functions,
def _DeleteKeyFn(unused_cls, key):
  """Wrapper function to be used with command.Apply()."""
  return key.delete_key()


# TODO: gsutil-beta: Port this function and other parallel upload functions,
def _ParseParallelUploadTrackerFile(tracker_file, tracker_file_lock):
  """Parse the tracker file (if any) from the last parallel composite upload
     attempt. The tracker file is of the format described in
     _CreateParallelUploadTrackerFile. If the file doesn't exist or cannot be
     read, then the upload will start from the beginning.

     Args:
       tracker_file: The name of the file to parse.
       tracker_file_lock: Lock protecting access to the tracker file.

     Returns:
       random_prefix: A randomly-generated prefix to the name of the
                      temporary components.
       existing_objects: A list of ObjectFromTracker objects representing
                         the set of files that have already been uploaded.
  """
  existing_objects = []
  try:
    with tracker_file_lock:
      f = open(tracker_file, 'r')
      lines = f.readlines()
      lines = [line.strip() for line in lines]
      f.close()
  except IOError as e:
    # We can't read the tracker file, so generate a new random prefix.
    lines = [str(random.randint(1, (10 ** 10) - 1))]

    # Ignore non-existent file (happens first time an upload
    # is attempted on a file), but warn user for other errors.
    if e.errno != errno.ENOENT:
      # Will restart because we failed to read in the file.
      print('Couldn\'t read parallel upload tracker file (%s): %s. '
            'Restarting upload from scratch.' % (tracker_file, e.strerror))

  # The first line contains the randomly-generated prefix.
  random_prefix = lines[0]

  # The remaining lines were written in pairs to describe a single component
  # in the form:
  #   object_name (without random prefix)
  #   generation
  # Newlines are used as the delimiter because only newlines and carriage
  # returns are invalid characters in object names, and users can specify
  # a custom prefix in the config file.
  i = 1
  while i < len(lines):
    (name, generation) = (lines[i], lines[i+1])
    if not generation:
      # Cover the '' case.
      generation = None
    existing_objects.append(ObjectFromTracker(name, generation))
    i += 2
  return (random_prefix, existing_objects)


# TODO: gsutil-beta: Port this function and other parallel upload functions,
def _AppendComponentTrackerToParallelUploadTrackerFile(tracker_file, component,
                                                       tracker_file_lock):
  """Appends info about the uploaded component to an existing tracker file.

  Follows the format described in _CreateParallelUploadTrackerFile.

  Args:
    tracker_file: Tracker file to append to.
    component: Component that was uploaded.
    tracker_file_lock: Thread and process-safe Lock for the tracker file.
  """
  lines = _GetParallelUploadTrackerFileLinesForComponents([component])
  lines = [line + '\n' for line in lines]
  with tracker_file_lock:
    with open(tracker_file, 'a') as f:
      f.writelines(lines)


# TODO: gsutil-beta: Port this function and other parallel upload functions,
def _CreateParallelUploadTrackerFile(tracker_file, random_prefix, components,
                                     tracker_file_lock):
  """Writes information about components that were successfully uploaded.

  This way the upload can be resumed at a later date. The tracker file has
  the format:
    random_prefix
    temp_object_1_name
    temp_object_1_generation
    .
    .
    .
    temp_object_N_name
    temp_object_N_generation
    where N is the number of components that have been successfully uploaded.

   Args:
     tracker_file: The name of the parallel upload tracker file.
     random_prefix: The randomly-generated prefix that was used for
                    for uploading any existing components.
     components: A list of ObjectFromTracker objects that were uploaded.
  """
  lines = [random_prefix]
  lines += _GetParallelUploadTrackerFileLinesForComponents(components)
  lines = [line + '\n' for line in lines]
  with tracker_file_lock:
    open(tracker_file, 'w').close()  # Clear the file.
    with open(tracker_file, 'w') as f:
      f.writelines(lines)


# TODO: gsutil-beta: Port this function and other parallel upload functions,
def _GetParallelUploadTrackerFileLinesForComponents(components):
  """Return a list of the lines for use in a parallel upload tracker file.

  The lines represent the given components, using the format as described in
  _CreateParallelUploadTrackerFile.

  Args:
    components: A list of ObjectFromTracker objects that were uploaded.
  """
  lines = []
  for component in components:
    generation = None
    generation = component.generation
    if not generation:
      generation = ''
    lines += [component.object_name, generation]
  return lines


def FilterExistingComponents(dst_args, existing_components,
                             bucket_name, suri_builder):
  """Determines course of action for component objects.

  Given the list of all target objects based on partitioning the file and
  the list of objects that have already been uploaded successfully,
  this function determines which objects should be uploaded, which
  existing components are still valid, and which existing components should
  be deleted.

  Args:
    dst_args: The map of file_name -> PerformResumableUploadIfAppliesArgs
              calculated by partitioning the file.
    existing_components: A list of ObjectFromTracker objects that have been
                         uploaded in the past.
    bucket_name: The name of the bucket in which the components exist.

  Returns:
    components_to_upload: List of components that need to be uploaded.
    uploaded_components: List of components that have already been
                         uploaded and are still valid.
    existing_objects_to_delete: List of components that have already
                                been uploaded, but are no longer valid
                                and are in a versioned bucket, and
                                therefore should be deleted.
  """
  components_to_upload = []
  existing_component_names = [component.object_name
                              for component in existing_components]
  for component_name in dst_args:
    if component_name not in existing_component_names:
      components_to_upload.append(dst_args[component_name])

  objects_already_chosen = []

  # Don't reuse any temporary components whose MD5 doesn't match the current
  # MD5 of the corresponding part of the file. If the bucket is versioned,
  # also make sure that we delete the existing temporary version.
  existing_objects_to_delete = []
  uploaded_components = []
  for tracker_object in existing_components:
    if (tracker_object.object_name not in dst_args.keys()
        or tracker_object.object_name in objects_already_chosen):
      # This could happen if the component size has changed. This also serves
      # to handle object names that get duplicated in the tracker file due
      # to people doing things they shouldn't (e.g., overwriting an existing
      # temporary component in a versioned bucket).

      url = MakeGsUri(bucket_name, tracker_object.object_name, suri_builder)
      url.generation = tracker_object.generation
      existing_objects_to_delete.append(url)
      continue

    dst_arg = dst_args[tracker_object.object_name]
    file_part = FilePart(dst_arg.filename, dst_arg.file_start,
                         dst_arg.file_length)
    # TODO: calculate MD5's in parallel when possible.
    content_md5 = CalculateMd5FromContents(file_part)

    try:
      # Get the MD5 of the currently-existing component.
      blr = BucketListingRef(dst_arg.dst_url, BucketListingRefType.OBJECT)
      etag = blr.GetKey().etag
    except Exception:  # pylint: disable=broad-except
      # We don't actually care what went wrong - we couldn't retrieve the
      # object to check the MD5, so just upload it again.
      etag = None
    if etag != (('"%s"') % content_md5):
      components_to_upload.append(dst_arg)
      objects_already_chosen.append(tracker_object.object_name)
      if tracker_object.generation:
        # If the old object doesn't have a generation (i.e., it isn't in a
        # versioned bucket), then we will just overwrite it anyway.
        invalid_component_with_generation = copy.deepcopy(dst_arg.dst_url)
        invalid_component_with_generation.generation = tracker_object.generation
        existing_objects_to_delete.append(invalid_component_with_generation)
    else:
      url = copy.deepcopy(dst_arg.dst_url)
      url.generation = tracker_object.generation
      uploaded_components.append(url)
      objects_already_chosen.append(tracker_object.object_name)

  if uploaded_components:
    logging.info('Found %d existing temporary components to reuse.',
                 len(uploaded_components))

  return (components_to_upload, uploaded_components,
          existing_objects_to_delete)


def MakeGsUri(bucket, filename, suri_builder):
  """Returns a StorageUri for an object in GCS."""
  return suri_builder.StorageUri(bucket + '/' + filename)


def _CalculateCrc32cFromContents(fp):
  """Calculates the Crc32c hash of the contents of a file.

  This function resets the file pointer to position 0.

  Args:
    fp: An already-open file object.

  Returns:
    CRC32C digest of the file in hex string format.
  """
  current_crc = crcmod.predefined.Crc('crc-32c')
  fp.seek(0)
  while True:
    data = fp.read(8192)
    if not data:
      break
    current_crc.update(data)
  fp.seek(0)
  return current_crc.hexdigest()
