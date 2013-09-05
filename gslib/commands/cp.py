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

# Get the system logging module, not our local logging module.
from __future__ import absolute_import

import binascii
import boto
import copy
import crcmod
import csv
import datetime
import errno
import gslib
import gzip
import hashlib
import logging
import mimetypes
import mmap
import multiprocessing
import os
import platform
import random
import re
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import traceback

from gslib.util import AddAcceptEncoding

try:
  # This module doesn't necessarily exist on Windows.
  import resource
  HAS_RESOURCE_MODULE = True
except ImportError, e:
  HAS_RESOURCE_MODULE = False

try:
  from hashlib import md5
except ImportError:
  from md5 import md5

from boto import config
from boto.exception import GSResponseError
from boto.exception import ResumableUploadException
from boto.gs.resumable_upload_handler import ResumableUploadHandler
from boto.s3.keyfile import KeyFile
from boto.s3.resumable_download_handler import ResumableDownloadHandler
from boto.storage_uri import BucketStorageUri
from boto.storage_uri import StorageUri
from collections import namedtuple
from gslib.bucket_listing_ref import BucketListingRef
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.command import Command
from gslib.command import EofWorkQueue
from gslib.command import FILE_URIS_OK
from gslib.command import MAX_ARGS
from gslib.command import MIN_ARGS
from gslib.command import PROVIDER_URIS_OK
from gslib.command import SUPPORTED_SUB_ARGS
from gslib.command import URIS_START_ARG
from gslib.commands.compose import MAX_COMPONENT_COUNT
from gslib.commands.compose import MAX_COMPOSE_ARITY
from gslib.commands.config import DEFAULT_PARALLEL_COMPOSITE_UPLOAD_COMPONENT_SIZE
from gslib.commands.config import DEFAULT_PARALLEL_COMPOSITE_UPLOAD_THRESHOLD
from gslib.exception import CommandException
from gslib.file_part import FilePart
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HelpType
from gslib.help_provider import HELP_TYPE
from gslib.name_expansion import NameExpansionIterator
from gslib.util import CreateTrackerDirIfNeeded
from gslib.util import ParseErrorDetail
from gslib.util import HumanReadableToBytes
from gslib.util import IS_WINDOWS
from gslib.util import MakeHumanReadable
from gslib.util import NO_MAX
from gslib.util import TWO_MB
from gslib.util import UsingCrcmodExtension
from gslib.wildcard_iterator import ContainsWildcard
from gslib.name_expansion import NameExpansionResult


SLOW_CRC_WARNING = """
WARNING: Downloading this composite object requires integrity checking with
CRC32c, but your crcmod installation isn't using the module's C extension, so
the the hash computation will likely throttle download performance. For help
installing the extension, please see:
  $ gsutil help crcmod
To disable slow integrity checking, see the "check_hashes" option in your boto
config file.
"""

SLOW_CRC_EXCEPTION = CommandException(
"""
Downloading this composite object requires integrity checking with CRC32c, but
your crcmod installation isn't using the module's C extension, so the the hash
computation will likely throttle download performance. For help installing the
extension, please see:
  $ gsutil help crcmod
To download regardless of crcmod performance or to skip slow integrity checks,
see the "check_hashes" option in your boto config file.""")

NO_HASH_CHECK_WARNING = """
WARNING: This download will not be validated since your crcmod installation
doesn't use the module's C extension, so the hash computation would likely
throttle download performance. For help in installing the extension, please see:
  $ gsutil help crcmod
To force integrity checking, see the "check_hashes" option in your boto config
file.
"""

NO_SERVER_HASH_EXCEPTION = CommandException(
"""
This object has no server-supplied hash for performing integrity
checks. To skip integrity checking for such objects, see the "check_hashes"
option in your boto config file.""")

NO_SERVER_HASH_WARNING = """
WARNING: This object has no server-supplied hash for performing integrity
checks. To force integrity checking, see the "check_hashes" option in your boto
config file.
"""

PARALLEL_UPLOAD_TEMP_NAMESPACE = (
    u'/gsutil/tmp/parallel_composite_uploads/do_NOT/use_this_prefix')

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
MIN_PARALLEL_COMPOSITE_FILE_SIZE = 20971520 # 20 MB

SYNOPSIS_TEXT = """
<B>SYNOPSIS</B>
  gsutil cp [OPTION]... src_uri dst_uri
  gsutil cp [OPTION]... src_uri... dst_uri
  gsutil cp [OPTION]... -I dst_uri
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

  You can pass a list of URIs to copy on STDIN instead of as command line
  arguments by using the -I option. This allows you to use gsutil in a
  pipeline to copy files and objects as generated by a program, such as:

    some_program | gsutil -m cp -I gs://my_bucket

  The contents of STDIN can name files, cloud URIs, and wildcards of files
  and cloud URIs.
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
  Use '-' in place of src_uri or dst_uri to perform a streaming
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
  will still exist until the upload is completed successfully.

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
""" % (10, MAX_COMPONENT_COUNT - 9, MAX_COMPONENT_COUNT)

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
                files.

  -D            Copy in "daisy chain" mode, i.e., copying between two buckets by
                hooking a download to an upload, via the machine where gsutil is
                run. By default, data are copied between two buckets "in the
                cloud", i.e., without needing to copy via the machine where
                gsutil runs. However, copy-in-the-cloud is not supported when
                copying between different locations (like US and EU) or between
                different storage classes (like STANDARD and
                DURABLE_REDUCED_AVAILABILITY). For these cases, you can use the
                -D option to copy data between buckets.
                Note: Daisy chain mode is automatically used when copying
                between providers (e.g., to copy data from Google Cloud Storage
                to another provider). However, gsutil requires you to specify
                cp -D explicitly when copying between different locations or
                between different storage classes, to make sure it's clear that
                you're using a slower, more expensive option than the normal
                copy-in-the-cloud case.

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
                will perform an additional HEAD request to check if an item
                exists before attempting to upload the data. This will save
                retransmitting data, but the additional HTTP requests may make
                small object transfers slower and more expensive.

  -p            Causes ACLs to be preserved when copying in the cloud. Note that
                this option has performance and cost implications, because it
                is essentially performing three requests ('acl get', cp,
                'acl set'). (The performance issue can be mitigated to some
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

  -v            Requests that the version-specific URI for each uploaded object
                be printed. Given this URI you can make future upload requests
                that are safe in the face of concurrent updates, because Google
                Cloud Storage will refuse to perform the update if the current
                object version doesn't match the version-specific URI. See
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
    'filename file_start file_length src_uri dst_uri canned_acl headers')

ObjectFromTracker = namedtuple('ObjectFromTracker',
                               'object_name generation')

class TrackerFileType(object):
  UPLOAD = 1
  DOWNLOAD = 2
  PARALLEL_UPLOAD = 3

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

  # TODO: Refactor this file to be less cumbersome. In particular, some of the
  # different paths (e.g., uploading a file to an object vs. downloading an
  # object to a file) could be split into separate files.

  # Set default Content-Type type.
  DEFAULT_CONTENT_TYPE = 'application/octet-stream'
  USE_MAGICFILE = boto.config.getbool('GSUtil', 'use_magicfile', False)
  # Chunk size to use while unzipping gzip files.
  GUNZIP_CHUNK_SIZE = 8192

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'cp',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : ['copy'],
    # Min number of args required by this command.
    MIN_ARGS : 1,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : NO_MAX,
    # Getopt-style string specifying acceptable sub args.
    # -t is deprecated but leave intact for now to avoid breakage.
    SUPPORTED_SUB_ARGS : 'a:cDeIL:MNnpqrRtvz:',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : True,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 0,
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

  def _GetMD5FromETag(self, key):
    if not key.etag:
      return None
    possible_md5 = key.etag.strip('"\'').lower()
    if re.match(r'^[0-9a-f]{32}$', possible_md5):
      return binascii.a2b_hex(possible_md5)

  def _CheckHashes(self, key, file_name, hash_algs_to_compute,
                   computed_hashes=None):
    """Validates integrity by comparing cloud digest to local digest.

    Args:
      key: Instance of boto Key object.
      file_name: Name of downloaded file on local disk.
      hash_algs_to_compute: Dictionary mapping hash algorithm names to digester
                            objects.
      computed_hashes: If specified, use this dictionary mapping hash algorithm
                       names to the calculated digest. If not specified, the
                       key argument will be checked for local_digests property.
                       If neither exist, the local file will be opened and
                       digests calculated on-demand.

    Raises:
      CommandException: if cloud digests don't match local digests.
    """
    cloud_hashes = {}
    if hasattr(key, 'cloud_hashes'):
      cloud_hashes = key.cloud_hashes
    # Check for older-style MD5-based etag.
    etag_md5 = self._GetMD5FromETag(key)
    if etag_md5:
      cloud_hashes.setdefault('md5', etag_md5)

    local_hashes = {}
    # If we've already computed a valid local hash, use that, else calculate an
    # md5 or crc32c depending on what we have available to compare against.
    if computed_hashes:
      local_hashes = computed_hashes
    elif hasattr(key, 'local_hashes') and key.local_hashes:
      local_hashes = key.local_hashes
    elif 'md5' in cloud_hashes and 'md5' in hash_algs_to_compute:
      self.logger.info(
          'Computing MD5 from scratch for resumed download')

      # Open file in binary mode to avoid surprises in Windows.
      with open(file_name, 'rb') as fp:
        local_hashes['md5'] = binascii.a2b_hex(key.compute_md5(fp)[0])
    elif 'crc32c' in cloud_hashes and 'crc32c' in hash_algs_to_compute:
      self.logger.info(
          'Computing CRC32C from scratch for resumed download')

      # Open file in binary mode to avoid surprises in Windows.
      with open(file_name, 'rb') as fp:
        crc32c_alg = lambda: crcmod.predefined.Crc('crc-32c')
        crc32c_hex = key.compute_hash(
            fp, algorithm=crc32c_alg)[0]
        local_hashes['crc32c'] = binascii.a2b_hex(crc32c_hex)

    for alg in local_hashes:
      if alg not in cloud_hashes:
        continue
      local_hexdigest = binascii.b2a_hex(local_hashes[alg])
      cloud_hexdigest = binascii.b2a_hex(cloud_hashes[alg])
      self.logger.debug('Comparing local vs cloud %s-checksum. (%s/%s)' % (
          alg, local_hexdigest, cloud_hexdigest))
      if local_hexdigest != cloud_hexdigest:
        raise CommandException(
            '%s signature computed for local file (%s) doesn\'t match '
            'cloud-supplied digest (%s). Local file (%s) deleted.' % (
            alg, local_hexdigest, cloud_hexdigest, file_name))

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

    def __init__(self, upload, logger):
      if upload:
        self.announce_text = 'Uploading'
      else:
        self.announce_text = 'Downloading'
      self.logger = logger

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

    def call(self, total_bytes_transferred, total_size):
      # Use sys.stderr.write instead of self.logger.info so progress messages
      # output on a single continuously overwriting line.
      if self.logger.isEnabledFor(logging.INFO):
        sys.stderr.write('Uploading: %s    \r' %
                         MakeHumanReadable(total_bytes_transferred))
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
    resumable_threshold = config.getint('GSUtil', 'resumable_threshold', TWO_MB)
    transfer_handler = None
    cb = None
    num_cb = None

    # Checks whether the destination file is a "special" file, like /dev/null on
    # Linux platforms or null on Windows platforms, so we can disable resumable
    # download support since the file size of the destination won't ever be
    # correct.
    dst_is_special = False
    if dst_uri.is_file_uri():
      # Check explicitly first because os.stat doesn't work on 'nul' in Windows.
      if dst_uri.object_name == os.devnull:
        dst_is_special = True
      try:
        mode = os.stat(dst_uri.object_name).st_mode
        if stat.S_ISCHR(mode):
          dst_is_special = True
      except OSError:
        pass

    if size >= resumable_threshold and not dst_is_special:
      cb = self._FileCopyCallbackHandler(upload, self.logger).call
      num_cb = int(size / TWO_MB)

      if upload:
        tracker_file_type = TrackerFileType.UPLOAD
      else:
        tracker_file_type = TrackerFileType.DOWNLOAD
      tracker_file = self._GetTrackerFile(dst_uri, tracker_file_type)

      if upload:
        if dst_uri.scheme == 'gs':
          transfer_handler = ResumableUploadHandler(tracker_file)
      else:
        transfer_handler = ResumableDownloadHandler(tracker_file)

    return (cb, num_cb, transfer_handler)

  def _GetTrackerFile(self, dst_uri, tracker_file_type, src_uri=None):
    resumable_tracker_dir = CreateTrackerDirIfNeeded()
    if tracker_file_type == TrackerFileType.UPLOAD:
      # Encode the dest bucket and object name into the tracker file name.
      res_tracker_file_name = (
          re.sub('[/\\\\]', '_', 'resumable_upload__%s__%s.url' %
                 (dst_uri.bucket_name, dst_uri.object_name)))
    elif tracker_file_type == TrackerFileType.DOWNLOAD:
      # Encode the fully-qualified dest file name into the tracker file name.
      res_tracker_file_name = (
          re.sub('[/\\\\]', '_', 'resumable_download__%s.etag' %
                 (os.path.realpath(dst_uri.object_name))))
    elif tracker_file_type == TrackerFileType.PARALLEL_UPLOAD:
      # Encode the dest bucket and object names as well as the source file name
      # into the tracker file name.
      res_tracker_file_name = (
          re.sub('[/\\\\]', '_', 'parallel_upload__%s__%s__%s.url' %
                 (dst_uri.bucket_name, dst_uri.object_name, src_uri)))

    res_tracker_file_name = _HashFilename(res_tracker_file_name)
    tracker_file = '%s%s%s' % (resumable_tracker_dir, os.sep,
                               res_tracker_file_name)
    return tracker_file

  def _LogCopyOperation(self, src_uri, dst_uri, headers):
    """
    Logs copy operation being performed, including Content-Type if appropriate.
    """
    if 'content-type' in headers and dst_uri.is_cloud_uri():
      content_type_msg = ' [Content-Type=%s]' % headers['content-type']
    else:
      content_type_msg = ''
    if src_uri.is_stream():
      self.logger.info('Copying from <STDIN>%s...', content_type_msg)
    else:
      self.logger.info('Copying %s%s...', src_uri, content_type_msg)

  def _ProcessCopyObjectToObjectOptions(self, dst_uri, headers):
    """
    Common option processing between _CopyObjToObjInTheCloud and
    _CopyObjToObjDaisyChainMode.
    """
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
    return (preserve_acl, canned_acl, headers)

  # We pass the headers explicitly to this call instead of using self.headers
  # so we can set different metadata (like Content-Type type) for each object.
  def _CopyObjToObjInTheCloud(self, src_key, src_uri, dst_uri, headers):
    """Performs copy-in-the cloud from specified src to dest object.

    Args:
      src_key: Source Key.
      src_uri: Source StorageUri.
      dst_uri: Destination StorageUri.
      headers: A copy of the top-level headers dictionary.

    Returns:
      (elapsed_time, bytes_transferred, dst_uri) excluding overhead like initial
      HEAD. Note: At present copy-in-the-cloud doesn't return the generation of
      the created object, so the returned URI is actually not version-specific
      (unlike other cp cases).

    Raises:
      CommandException: if errors encountered.
    """
    self._SetContentTypeHeader(src_uri, headers)
    self._LogCopyOperation(src_uri, dst_uri, headers)
    # Do Object -> object copy within same provider (uses
    # x-<provider>-copy-source metadata HTTP header to request copying at the
    # server).
    src_bucket = src_uri.get_bucket(False, headers)
    (preserve_acl, canned_acl, headers) = (
        self._ProcessCopyObjectToObjectOptions(dst_uri, headers))
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

    try:
      dst_key = dst_uri.copy_key(
          src_bucket.name, src_uri.object_name, preserve_acl=preserve_acl,
          headers=headers, src_version_id=src_uri.version_id,
          src_generation=src_uri.generation)
    except GSResponseError as e:
      exc_name, message, detail = ParseErrorDetail(e)
      if (exc_name == 'GSResponseError'
          and ('Copy-in-the-cloud disallowed' in detail)):
          raise CommandException('%s.\nNote: you can copy between locations '
                                 'or between storage classes by using the '
                                 'gsutil cp -D option.' % detail)
      else:
        raise
    end_time = time.time()
    return (end_time - start_time, src_key.size,
            dst_uri.clone_replace_key(dst_key))

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

  def _PerformResumableUploadIfApplies(self, fp, src_uri, dst_uri, canned_acl,
                                       headers, file_size, already_split=False):
    """
    Performs resumable upload if supported by provider and file is above
    threshold, else performs non-resumable upload.

    Returns (elapsed_time, bytes_transferred, version-specific dst_uri).
    """
    start_time = time.time()
    (cb, num_cb, res_upload_handler) = self._GetTransferHandlers(
        dst_uri, file_size, True)
    if dst_uri.scheme == 'gs':
      # Resumable upload protocol is Google Cloud Storage-specific.
      dst_uri.set_contents_from_file(fp, headers, policy=canned_acl,
                                     cb=cb, num_cb=num_cb,
                                     res_upload_handler=res_upload_handler)
    else:
      dst_uri.set_contents_from_file(fp, headers, policy=canned_acl,
                                     cb=cb, num_cb=num_cb)
    if res_upload_handler:
      # ResumableUploadHandler does not update upload_start_point from its
      # initial value of -1 if transferring the whole file, so clamp at 0
      bytes_transferred = file_size - max(
          res_upload_handler.upload_start_point, 0)
      if self.use_manifest and not already_split:
        # Save the upload indentifier in the manifest file, unless we're
        # uploading a temporary component for parallel composite uploads.
        self.manifest.Set(
            src_uri, 'upload_id', res_upload_handler.get_upload_id())
    else:
      bytes_transferred = file_size
    end_time = time.time()
    return (end_time - start_time, bytes_transferred, dst_uri)

  def _PerformStreamingUpload(self, fp, dst_uri, headers, canned_acl=None):
    """
    Performs a streaming upload to the cloud.

    Args:
      fp: The file whose contents to upload.
      dst_uri: Destination StorageUri.
      headers: A copy of the top-level headers dictionary.
      canned_acl: Optional canned ACL to set on the object.

    Returns (elapsed_time, bytes_transferred, version-specific dst_uri).
    """
    start_time = time.time()

    cb = self._StreamCopyCallbackHandler(self.logger).call
    dst_uri.set_contents_from_stream(
        fp, headers, policy=canned_acl, cb=cb)
    try:
      bytes_transferred = fp.tell()
    except:
      bytes_transferred = 0

    end_time = time.time()
    return (end_time - start_time, bytes_transferred, dst_uri)

  def _SetContentTypeHeader(self, src_uri, headers):
    """
    Sets content type header to value specified in '-h Content-Type' option (if
    specified); else sets using Content-Type detection.
    """
    if 'content-type' in headers:
      # If empty string specified (i.e., -h "Content-Type:") set header to None,
      # which will inhibit boto from sending the CT header. Otherwise, boto will
      # pass through the user specified CT header.
      if not headers['content-type']:
        headers['content-type'] = None
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
        headers['content-type'] = content_type

  def _GetFileSize(self, fp):
    """Determines file size different ways for case where fp is actually a
       wrapper around a Key vs an actual file.

       Args:
         The file whose size we wish to determine.

       Returns:
         The size of the file, in bytes.
    """
    if isinstance(fp, KeyFile):
      return fp.getkey().size
    else:
      return os.path.getsize(fp.name)

  def _UploadFileToObject(self, src_key, src_uri, dst_uri, headers,
                          should_log=True, allow_splitting=True):
    """Uploads a local file to an object.

    Args:
      src_key: Source StorageUri. Must be a file URI.
      src_uri: Source StorageUri.
      dst_uri: Destination StorageUri.
      headers: The headers dictionary.
      should_log: bool indicator whether we should log this operation.
    Returns:
      (elapsed_time, bytes_transferred, version-specific dst_uri), excluding
      overhead like initial HEAD.

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
          self.logger.warning(
              'Warning: -t is deprecated, and will be removed in the future. '
              'Content type\ndetection is '
              'now performed by default, unless inhibited by specifying '
              'a\nContent-Type header via the -h option.')
        elif o == '-z':
          gzip_exts = a.split(',')

    self._SetContentTypeHeader(src_uri, headers)
    if should_log:
      self._LogCopyOperation(src_uri, dst_uri, headers)

    if 'content-language' not in headers:
       content_language = config.get_value('GSUtil', 'content_language')
       if content_language:
         headers['content-language'] = content_language

    fname_parts = src_uri.object_name.split('.')
    if len(fname_parts) > 1 and fname_parts[-1] in gzip_exts:
      self.logger.debug('Compressing %s (to tmp)...', src_key)
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
      headers['content-encoding'] = 'gzip'
      gzip_fp = open(gzip_path, 'rb')
      try:
        file_size = self._GetFileSize(gzip_fp)
        (elapsed_time, bytes_transferred, result_uri) = (
            self._PerformResumableUploadIfApplies(gzip_fp, src_uri, dst_uri,
                                                  canned_acl, headers,
                                                  file_size))
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
      (elapsed_time, bytes_transferred, result_uri) = (
          self._PerformStreamingUpload(src_key.fp, dst_uri, headers,
                                       canned_acl))
    else:
      if src_key.is_stream():
        # For Providers that don't support chunked Transfers
        tmp = tempfile.NamedTemporaryFile()
        file_uri = self.suri_builder.StorageUri('file://%s' % tmp.name)
        try:
          file_uri.new_key(False, headers).set_contents_from_file(
              src_key.fp, headers)
          src_key = file_uri.get_key()
        finally:
          file_uri.close()
      try:
        fp = src_key.fp
        file_size = self._GetFileSize(fp)
        if self._ShouldDoParallelCompositeUpload(allow_splitting, src_key,
                                                 dst_uri, file_size):
          (elapsed_time, bytes_transferred, result_uri) = (
              self._DoParallelCompositeUpload(fp, src_uri, dst_uri, headers,
                                              canned_acl, file_size))
        else:
          (elapsed_time, bytes_transferred, result_uri) = (
              self._PerformResumableUploadIfApplies(
                  src_key.fp, src_uri, dst_uri, canned_acl, headers,
                  self._GetFileSize(src_key.fp)))
      finally:
        if src_key.is_stream():
          tmp.close()
        else:
          src_key.close()
    return (elapsed_time, bytes_transferred, result_uri)

  def _GetHashAlgs(self, key):
    hash_algs = {}
    check_hashes_config = config.get(
        'GSUtil', 'check_hashes', 'if_fast_else_fail')
    if check_hashes_config == 'never':
      return hash_algs
    if self._GetMD5FromETag(key):
      hash_algs['md5'] = md5
    if hasattr(key, 'cloud_hashes') and key.cloud_hashes:
      if 'md5' in key.cloud_hashes:
        hash_algs['md5'] = md5
      # If the cloud provider supplies a CRC, we'll compute a checksum to
      # validate if we're using a native crcmod installation or MD5 isn't
      # offered as an alternative.
      if 'crc32c' in key.cloud_hashes:
        if UsingCrcmodExtension(crcmod):
          hash_algs['crc32c'] = lambda: crcmod.predefined.Crc('crc-32c')
        elif not hash_algs:
          if check_hashes_config == 'if_fast_else_fail':
            raise SLOW_CRC_EXCEPTION
          elif check_hashes_config == 'if_fast_else_skip':
            sys.stderr.write(NO_HASH_CHECK_WARNING)
          elif check_hashes_config == 'always':
            sys.stderr.write(SLOW_CRC_WARNING)
            hash_algs['crc32c'] = lambda: crcmod.predefined.Crc('crc-32c')
          else:
            raise CommandException(
                'Your boto config \'check_hashes\' option is misconfigured.')
    elif not hash_algs:
      if check_hashes_config == 'if_fast_else_skip':
        sys.stderr.write(NO_SERVER_HASH_WARNING)
      else:
        raise NO_SERVER_HASH_EXCEPTION
    return hash_algs

  def _DownloadObjectToFile(self, src_key, src_uri, dst_uri, headers,
                            should_log=True):
    """Downloads an object to a local file.

    Args:
      src_key: Source Key.
      src_uri: Source StorageUri.
      dst_uri: Destination StorageUri.
      headers: The headers dictionary.
      should_log: bool indicator whether we should log this operation.
    Returns:
      (elapsed_time, bytes_transferred, dst_uri), excluding overhead like
      initial HEAD.

    Raises:
      CommandException: if errors encountered.
    """
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
    # For gzipped objects, download to a temp file and unzip.
    if (hasattr(src_key, 'content_encoding')
        and src_key.content_encoding == 'gzip'):
      # We can't use tempfile.mkstemp() here because we need a predictable
      # filename for resumable downloads.
      download_file_name = '%s_.gztmp' % file_name
      need_to_unzip = True
    else:
      download_file_name = file_name
      need_to_unzip = False

    hash_algs = self._GetHashAlgs(src_key)

    # Add accept encoding for download operation.
    AddAcceptEncoding(headers)

    fp = None
    try:
      if res_download_handler:
        fp = open(download_file_name, 'ab')
      else:
        fp = open(download_file_name, 'wb')
      start_time = time.time()
      # Use our hash_algs if get_contents_to_file() will accept them, else the
      # default (md5-only) will suffice.
      try:
        src_key.get_contents_to_file(fp, headers, cb=cb, num_cb=num_cb,
                                     res_download_handler=res_download_handler,
                                     hash_algs=hash_algs)
      except TypeError:
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

    if (not need_to_unzip and
        hasattr(src_key, 'content_encoding')
        and src_key.content_encoding == 'gzip'):
      # TODO: HEAD requests are currently not returning proper Content-Encoding
      # headers when an object is gzip-encoded on-the-fly. Remove this once
      # it's fixed.
      renamed_file_name = '%s_.gztmp' % file_name
      os.rename(download_file_name, renamed_file_name)
      download_file_name = renamed_file_name
      need_to_unzip = True

    # Discard all hashes if we are resuming a partial download.
    if res_download_handler and res_download_handler.download_start_point:
      src_key.local_hashes = {}

    # Verify downloaded file checksum matched source object's checksum.
    digest_verified = True
    computed_hashes = None
    try:
      self._CheckHashes(src_key, download_file_name, hash_algs)
    except CommandException, e:
      # If the digest doesn't match, we'll try checking it again after
      # unzipping.
      if (not need_to_unzip or
          'doesn\'t match cloud-supplied digest' not in str(e)):
        os.unlink(download_file_name)
        raise
      digest_verified = False
      computed_hashes = dict(
          (alg, digester())
          for alg, digester in self._GetHashAlgs(src_key).iteritems())

    if res_download_handler:
      bytes_transferred = (
          src_key.size - res_download_handler.download_start_point)
    else:
      bytes_transferred = src_key.size

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
            if computed_hashes:
              # Compute digests again on the uncompressed data.
              for alg in computed_hashes.itervalues():
                alg.update(data)
            data = f_in.read(self.GUNZIP_CHUNK_SIZE)

      os.unlink(download_file_name)

      if not digest_verified:
        computed_hashes = dict((alg, digester.digest())
                               for alg, digester in computed_hashes.iteritems())
        try:
          self._CheckHashes(
              src_key, file_name, hash_algs, computed_hashes=computed_hashes)
        except CommandException, e:
          os.unlink(file_name)
          raise

    return (end_time - start_time, bytes_transferred, dst_uri)

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
    """Copies a local file to a local file.

    Args:
      src_key: Source StorageUri. Must be a file URI.
      src_uri: Source StorageUri.
      dst_uri: Destination StorageUri.
      headers: The headers dictionary.
    Returns:
      (elapsed_time, bytes_transferred, dst_uri), excluding
      overhead like initial HEAD.

    Raises:
      CommandException: if errors encountered.
    """
    self._LogCopyOperation(src_uri, dst_uri, headers)
    dst_key = dst_uri.new_key(False, headers)
    start_time = time.time()
    dst_key.set_contents_from_file(src_key.fp, headers)
    end_time = time.time()
    return (end_time - start_time, os.path.getsize(src_key.fp.name), dst_uri)

  def _CopyObjToObjDaisyChainMode(self, src_key, src_uri, dst_uri, headers):
    """Copies from src_uri to dst_uri in "daisy chain" mode.
       See -D OPTION documentation about what daisy chain mode is.

    Args:
      src_key: Source Key.
      src_uri: Source StorageUri.
      dst_uri: Destination StorageUri.
      headers: A copy of the top-level headers dictionary.

    Returns:
      (elapsed_time, bytes_transferred, version-specific dst_uri) excluding
      overhead like initial HEAD.

    Raises:
      CommandException: if errors encountered.
    """
    # Start with copy of input headers, so we'll include any headers that need
    # to be set from higher up in call stack (like x-goog-if-generation-match).
    headers = headers.copy()
    # Now merge headers from src_key so we'll preserve metadata.
    # Unfortunately boto separates headers into ones it puts in the metadata
    # dict and ones it pulls out into specific key fields, so we need to walk
    # through the latter list to find the headers that we copy over to the dest
    # object.
    for header_name, field_name in (
        ('cache-control', 'cache_control'),
        ('content-type', 'content_type'),
        ('content-language', 'content_language'),
        ('content-encoding', 'content_encoding'),
        ('content-disposition', 'content_disposition')):
      value = getattr(src_key, field_name, None)
      if value:
        headers[header_name] = value
    # Boto represents x-goog-meta-* headers in metadata dict with the
    # x-goog-meta- or x-amx-meta- prefix stripped. Turn these back into headers
    # for the destination object.
    for name, value in src_key.metadata.items():
      header_name = '%smeta-%s' % (dst_uri.get_provider().header_prefix, name)
      headers[header_name] = value
    # Set content type if specified in '-h Content-Type' option.
    self._SetContentTypeHeader(src_uri, headers)
    self._LogCopyOperation(src_uri, dst_uri, headers)
    (preserve_acl, canned_acl, headers) = (
        self._ProcessCopyObjectToObjectOptions(dst_uri, headers))
    if preserve_acl:
      if src_uri.get_provider() != dst_uri.get_provider():
        # We don't attempt to preserve ACLs across providers because
        # GCS and S3 support different ACLs and disjoint principals.
        raise NotImplementedError('Cross-provider cp -p not supported')
      # We need to read and write the ACL manually because the
      # Key.set_contents_from_file() API doesn't provide a preserve_acl
      # parameter (unlike the Bucket.copy_key() API used
      # by_CopyObjToObjInTheCloud).
      acl = src_uri.get_acl(headers=headers)
    fp = KeyFile(src_key)
    result = self._PerformResumableUploadIfApplies(fp, src_uri,
                                                   dst_uri, canned_acl, headers,
                                                   self._GetFileSize(fp))
    if preserve_acl:
      # If user specified noclobber flag, we need to remove the
      # x-goog-if-generation-match:0 header that was set when uploading the
      # object, because that precondition would fail when updating the ACL on
      # the now-existing object.
      if self.no_clobber:
        del headers['x-goog-if-generation-match']
      # Remove the owner field from the ACL in case we're copying from an object
      # that is owned by a different user. If we left that other user in the
      # ACL, attempting to set the ACL would result in a 400 (Bad Request).
      if hasattr(acl, 'owner'):
        del acl.owner
      dst_uri.set_acl(acl, dst_uri.object_name, headers=headers)
    return result

  def _PerformCopy(self, src_uri, dst_uri, allow_splitting=True):
    """Performs copy from src_uri to dst_uri, handling various special cases.

    Args:
      src_uri: Source StorageUri.
      dst_uri: Destination StorageUri.
      allow_splitting: Whether to allow the file to be split into component
                       pieces for an parallel composite upload.

    Returns:
      (elapsed_time, bytes_transferred, version-specific dst_uri) excluding
      overhead like initial HEAD.

    Raises:
      CommandException: if errors encountered.
    """
    # Make a copy of the input headers each time so we can set a different
    # content type for each object.
    headers = self.headers.copy() if self.headers else {}
    download_headers = headers.copy()
    # Add accept encoding for download operation.
    AddAcceptEncoding(download_headers)

    src_key = src_uri.get_key(False, download_headers)
    if not src_key:
      raise CommandException('"%s" does not exist.' % src_uri)

    if self.use_manifest:
      # Set the source size in the manifest.
      self.manifest.Set(src_uri, 'size', getattr(src_key, 'size', None))

    # On Windows, stdin is opened as text mode instead of binary which causes
    # problems when piping a binary file, so this switches it to binary mode.
    if IS_WINDOWS and src_uri.is_file_uri() and src_key.is_stream():
      import msvcrt
      msvcrt.setmode(src_key.fp.fileno(), os.O_BINARY)

    if self.no_clobber:
        # There are two checks to prevent clobbering:
        # 1) The first check is to see if the item
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
        if dst_uri.exists(download_headers):
          if dst_uri.is_file_uri():
            # The local file may be a partial. Check the file sizes.
            if src_key.size == dst_uri.get_key(headers=download_headers).size:
              raise ItemExistsError()
          else:
            raise ItemExistsError()
        if dst_uri.is_cloud_uri() and dst_uri.scheme == 'gs':
          headers['x-goog-if-generation-match'] = '0'

    if src_uri.is_cloud_uri() and dst_uri.is_cloud_uri():
      if src_uri.scheme == dst_uri.scheme and not self.daisy_chain:
        return self._CopyObjToObjInTheCloud(src_key, src_uri, dst_uri, headers)
      else:
        return self._CopyObjToObjDaisyChainMode(src_key, src_uri, dst_uri,
                                                headers)
    elif src_uri.is_file_uri() and dst_uri.is_cloud_uri():
      return self._UploadFileToObject(src_key, src_uri, dst_uri,
                                      download_headers)
    elif src_uri.is_cloud_uri() and dst_uri.is_file_uri():
      return self._DownloadObjectToFile(src_key, src_uri, dst_uri,
                                        download_headers)
    elif src_uri.is_file_uri() and dst_uri.is_file_uri():
      return self._CopyFileToFile(src_key, src_uri, dst_uri, download_headers)
    else:
      raise CommandException('Unexpected src/dest case')

  def _PartitionFile(self, fp, file_size, src_uri, headers, canned_acl, bucket,
                     random_prefix):
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

       Returns:
         dst_args: The destination URIs for the temporary component objects.
    """
    parallel_composite_upload_component_size = HumanReadableToBytes(
        boto.config.get('GSUtil', 'parallel_composite_upload_component_size',
                        DEFAULT_PARALLEL_COMPOSITE_UPLOAD_COMPONENT_SIZE))
    (num_components, component_size) = _GetPartitionInfo(file_size,
        MAX_COMPOSE_ARITY, parallel_composite_upload_component_size)

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
          headers)
      file_names.append(temp_file_name)
      dst_args[temp_file_name] = func_args
      uri_strs.append(self._MakeGsUriStr(bucket, temp_file_name))

    return dst_args

  def _MakeFileUri(self, filename):
    """Returns a StorageUri for a local file."""
    return self.suri_builder.StorageUri(filename)

  def _MakeGsUriStr(self, bucket, filename):
    """Returns a string of the form gs://bucket/filename, used to indicate an
       object in Google Cloud Storage.
    """
    return 'gs://' + bucket + '/' + filename

  def _PerformResumableUploadIfAppliesWrapper(self, args):
    """A wrapper for cp._PerformResumableUploadIfApplies, which takes in a
       PerformResumableUploadIfAppliesArgs, extracts the arguments to form the
       arguments for the wrapped function, and then calls the wrapped function.
       This was designed specifically for use with command.Apply().
    """
    fp = FilePart(args.filename, args.file_start, args.file_length)
    with fp:
      already_split = True
      ret = self._PerformResumableUploadIfApplies(
          fp, args.src_uri, args.dst_uri, args.canned_acl, args.headers,
          fp.length, already_split)
    return ret

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
    tracker_file = self._GetTrackerFile(dst_uri,
                                        TrackerFileType.PARALLEL_UPLOAD,
                                        src_uri)
    (random_prefix, existing_components) = (
        _ParseParallelUploadTrackerFile(tracker_file))

    # Get the set of all components that should be uploaded.
    dst_args = self._PartitionFile(fp, file_size, src_uri, headers, canned_acl,
                                   bucket, random_prefix)

    (components_to_upload, existing_components, existing_objects_to_delete) = (
        FilterExistingComponents(dst_args, existing_components, bucket,
                                      self.suri_builder))

    # In parallel, copy all of the file parts that haven't already been
    # uploaded to temporary objects.
    cp_results = self.Apply(self._PerformResumableUploadIfAppliesWrapper,
                            components_to_upload,
                            self._CopyExceptionHandler,
                            ('copy_failure_count', 'total_bytes_transferred'),
                            arg_checker=gslib.command.DummyArgChecker,
                            parallel_operations_override=True,
                            queue_class=EofWorkQueue,
                            should_return_results=True,
                            ignore_subprocess_failures=True,
                            is_main_thread=(not self.parallel_operations))

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
        self.Apply(_DeleteKeyFn, objects_to_delete, self._RmExceptionHandler,
                   arg_checker=gslib.command.DummyArgChecker,
                   parallel_operations_override=True, queue_class=EofWorkQueue,
                   is_main_thread=(not self.parallel_operations))
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
        if os.path.exists(tracker_file):
          os.unlink(tracker_file)
    else:
      # Some of the components failed to upload. In this case, we want to write
      # the tracker file and then exit without deleting the objects.
      _WriteParallelUploadTrackerFile(tracker_file, random_prefix, components)
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
    # TODO: Currently, parallel composite uploads are disabled when the
    # -m flag is present such that we don't spawn off an uncontrollable amount
    # of subprocesses. We should either refactor cp such that there is not a
    # nested call to command.Apply() in the parallel upload code, or find a
    # way to dynamically control the global number of processes by looking at
    # the inputs ahead of time.
    parallel_composite_upload_threshold = HumanReadableToBytes(boto.config.get(
        'GSUtil', 'parallel_composite_upload_threshold',
        DEFAULT_PARALLEL_COMPOSITE_UPLOAD_THRESHOLD))
    return (allow_splitting  # Don't split the pieces multiple times.
            and not src_key.is_stream()  # We can't partition streams.
            and dst_uri.scheme == 'gs'  # Compose is only for gs.
            and parallel_composite_upload_threshold > 0
            and file_size >= parallel_composite_upload_threshold
            and file_size >= MIN_PARALLEL_COMPOSITE_FILE_SIZE)

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
                or blr.GetKey().name.endswith('/'))
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
    using context-dependent naming rules that mimic Linux cp and mv behavior.

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
      # of exp_src_uri to exp_dst_uri.
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
      if exp_src_uri.is_cloud_uri():
        dst_key_name = exp_src_uri.versionless_uri[
           len(src_uri_path_sans_final_dir):].lstrip(src_uri.delim)
      else:
        dst_key_name = exp_src_uri.uri[
           len(src_uri_path_sans_final_dir):].lstrip(src_uri.delim)
      # Handle case where dst_uri is a non-existent subdir.
      if not have_existing_dest_subdir:
        dst_key_name = dst_key_name.partition(src_uri.delim)[-1]
      # Handle special case where src_uri was a directory named with '.' or
      # './', so that running a command like:
      #   gsutil cp -r . gs://dest
      # will produce obj names of the form gs://dest/abc instead of
      # gs://dest/./abc.
      if dst_key_name.startswith('.%s' % os.sep):
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
        delim = exp_dst_uri.delim if exp_dst_uri.object_name else ''
        dst_key_name = '%s%s%s' % (exp_dst_uri.object_name, delim, dst_key_name)

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

  def _CopyExceptionHandler(self, e):
    """Simple exception handler to allow post-completion status."""
    self.logger.error(str(e))
    self.copy_failure_count += 1
    self.logger.debug(('\n\nEncountered exception while copying:\n%s\n' %
                       traceback.format_exc()))

  def _RmExceptionHandler(self, e):
    """Simple exception handler to allow post-completion status."""
    self.logger.error(str(e))

  # Command entry point.
  def RunCommand(self):

    # Inner funcs.
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

      if self.use_manifest and self.manifest.WasSuccessful(str(exp_src_uri)):
        return

      if self.perform_mv:
        if name_expansion_result.NamesContainer():
          # Use recursion_requested when performing name expansion for the
          # directory mv case so we can determine if any of the source URIs are
          # directories (and then use cp -R and rm -R to perform the move, to
          # match the behavior of Linux mv (which when moving a directory moves
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

      if dst_uri.is_cloud_uri() and dst_uri.is_version_specific:
        raise CommandException('%s: a version-specific URI\n(%s)\ncannot be '
                               'the destination for gsutil cp - abort.'
                               % (cmd_name, dst_uri))

      elapsed_time = bytes_transferred = 0
      try:
        if self.use_manifest:
          self.manifest.Initialize(exp_src_uri, dst_uri)
        (elapsed_time, bytes_transferred, result_uri) = (
            self._PerformCopy(exp_src_uri, dst_uri))
        if self.use_manifest:
          if hasattr(dst_uri, 'md5'):
            self.manifest.Set(exp_src_uri, 'md5', dst_uri.md5)
          self.manifest.SetResult(exp_src_uri, bytes_transferred, 'OK')
      except ItemExistsError:
        message = 'Skipping existing item: %s' % dst_uri.uri
        self.logger.info(message)
        if self.use_manifest:
          self.manifest.SetResult(exp_src_uri, 0, 'skip', message)
      except Exception, e:
        if self._IsNoClobberServerException(e):
          message = 'Rejected (noclobber): %s' % dst_uri.uri
          self.logger.info(message)
          if self.use_manifest:
            self.manifest.SetResult(exp_src_uri, 0, 'skip', message)
        elif self.continue_on_error:
          message = 'Error copying %s: %s' % (src_uri.uri, str(e))
          self.copy_failure_count += 1
          self.logger.error(message)
          if self.use_manifest:
            self.manifest.SetResult(exp_src_uri, 0, 'error', message)
        else:
          if self.use_manifest:
            self.manifest.SetResult(exp_src_uri, 0, 'error', str(e))
          raise

      if self.print_ver:
        # Some cases don't return a version-specific URI (e.g., if destination
        # is a file).
        if hasattr(result_uri, 'version_specific_uri'):
          self.logger.info('Created: %s' % result_uri.version_specific_uri)
        else:
          self.logger.info('Created: %s' % result_uri.uri)

      # TODO: If we ever use -n (noclobber) with -M (move) (not possible today
      # since we call copy internally from move and don't specify the -n flag)
      # we'll need to only remove the source when we have not skipped the
      # destination.
      if self.perform_mv:
        self.logger.info('Removing %s...', exp_src_uri)
        exp_src_uri.delete_key(validate=False, headers=self.headers)
      stats_lock.acquire()
      self.total_elapsed_time += elapsed_time
      self.total_bytes_transferred += bytes_transferred
      stats_lock.release()

    # Start of RunCommand code.
    self._ParseArgs()

    # If possible (this will fail on Windows), set the maximum number of open
    # files to avoid hitting the limit imposed by the OS. This number was
    # obtained experimentally and may need tweaking.
    new_soft_max_file_limit = 10000
    # Try to set this with both resource names - RLIMIT_NOFILE for most Unix
    # platforms, and RLIMIT_OFILE for BSD. Ignore AttributeError because the
    # "resource" module is not guaranteed to know about these names.
    if HAS_RESOURCE_MODULE:
      try:
        self._SetSoftMaxFileLimitForResource(resource.RLIMIT_NOFILE,
                                             new_soft_max_file_limit)
      except AttributeError, e:
        pass
      try:
        self._SetSoftMaxFileLimitForResource(resource.RLIMIT_OFILE,
                                             new_soft_max_file_limit)
      except AttributeError, e:
        pass

    self.total_elapsed_time = self.total_bytes_transferred = 0
    if self.args[-1] == '-' or self.args[-1] == 'file://-':
      self._HandleStreamingDownload()
      return 0

    if self.read_args_from_stdin:
      if len(self.args) != 1:
        raise CommandException('Source URIs cannot be specified with -I option')
      uri_strs = self._StdinIterator()
    else:
      if len(self.args) < 2:
        raise CommandException('Wrong number of arguments for "cp" command.')
      uri_strs = self.args[:-1]

    (exp_dst_uri, have_existing_dst_container) = self._ExpandDstUri(
         self.args[-1])
    # If the destination bucket has versioning enabled iterate with
    # all_versions=True. That way we'll copy all versions if the source bucket
    # is versioned; and by leaving all_versions=False if the destination bucket
    # has versioning disabled we will avoid copying old versions all to the same
    # un-versioned destination object.
    try:
      all_versions = (exp_dst_uri.names_bucket()
                      and exp_dst_uri.get_versioning_config(self.headers))
    except GSResponseError as e:
      # This happens if the user doesn't have OWNER access on the bucket (needed
      # to check if versioning is enabled). In this case fall back to copying
      # all versions (which can be inefficient for the reason noted in the
      # comment above). We don't try to warn the user because that would result
      # in false positive warnings (since we can't check if versioning is
      # enabled on the destination bucket).
      if e.status == 403:
        all_versions = True
      else:
        raise
    name_expansion_iterator = NameExpansionIterator(
        self.command_name, self.proj_id_handler, self.headers, self.debug,
        self.logger, self.bucket_storage_uri_class, uri_strs,
        self.recursion_requested or self.perform_mv,
        have_existing_dst_container=have_existing_dst_container,
        all_versions=all_versions)
    self.have_existing_dst_container = have_existing_dst_container

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
    self.Apply(_CopyFunc, name_expansion_iterator, self._CopyExceptionHandler,
               shared_attrs)
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
      # - not any transfers for doing wildcard expansion, the initial HEAD
      # request boto performs when doing a bucket.get_key() operation, etc.
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

  def _SetSoftMaxFileLimitForResource(self, resource_name, new_soft_limit):
    """Sets a new soft limit for the maximum number of open files.    
       The soft limit is used for this process (and its children), but the
       hard limit is set by the system and cannot be exceeded.
    """
    try:
      (soft_limit, hard_limit) = resource.getrlimit(resource_name)
      soft_limit = max(new_soft_limit, soft_limit)
      resource.setrlimit(resource.RLIMIT_NOFILE, (soft_limit, hard_limit))
    except (resource.error, ValueError), e:
      pass

  def _ParseArgs(self):
    self.perform_mv = False
    self.exclude_symlinks = False
    self.no_clobber = False
    self.continue_on_error = False
    self.daisy_chain = False
    self.read_args_from_stdin = False
    self.print_ver = False
    self.use_manifest = False

    # self.recursion_requested initialized in command.py (so can be checked
    # in parent class for all commands).
    if self.sub_opts:
      for o, a in self.sub_opts:
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
          self.manifest = self._Manifest(a)
        elif o == '-M':
          # Note that we signal to the cp command to perform a move (copy
          # followed by remove) and use directory-move naming rules by passing
          # the undocumented (for internal use) -M option when running the cp
          # command from mv.py.
          self.perform_mv = True
        elif o == '-n':
          self.no_clobber = True
        elif o == '-q':
          self.logger.warning(
              'Warning: gsutil cp -q is deprecated, and will be removed in the '
              'future.\nPlease use gsutil -q cp ... instead.')
          self.logger.setLevel(level=logging.WARNING)
        elif o == '-r' or o == '-R':
          self.recursion_requested = True
        elif o == '-v':
          self.print_ver = True

  def _HandleStreamingDownload(self):
    # Destination is <STDOUT>. Manipulate sys.stdout so as to redirect all
    # debug messages to <STDERR>.
    stdout_fp = sys.stdout
    sys.stdout = sys.stderr
    did_some_work = False
    for uri_str in self.args[0:len(self.args)-1]:
      for uri in self.WildcardIterator(uri_str).IterUris():
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
        self.logger.info(
            'Total bytes copied=%d, total elapsed time=%5.3f secs (%sps)',
            self.total_bytes_transferred, self.total_elapsed_time,
            MakeHumanReadable(float(self.total_bytes_transferred) /
                              float(self.total_elapsed_time)))

  def _StdinIterator(self):
    """A generator function that returns lines from stdin."""
    for line in sys.stdin:
      # Strip CRLF.
      yield line.rstrip()

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
      new_src_path = os.path.normpath(src_uri.object_name)
      new_dst_path = os.path.normpath(dst_uri.object_name)
      return (src_uri.clone_replace_name(new_src_path).uri ==
              dst_uri.clone_replace_name(new_dst_path).uri)
    else:
      return (src_uri.uri == dst_uri.uri and
              src_uri.generation == dst_uri.generation and
              src_uri.version_id == dst_uri.version_id)

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

  def _IsNoClobberServerException(self, e):
    """
    Checks to see if the server attempted to clobber a file after we specified
    in the header that we didn't want the file clobbered.

    Args:
      e: The Exception that was generated by a failed copy operation

    Returns:
      bool indicator - True indicates that the server did attempt to clobber
          an existing file.
    """
    return self.no_clobber and (
        (isinstance(e, GSResponseError) and e.status==412) or
        (isinstance(e, ResumableUploadException) and 'code 412' in e.message))



  class _Manifest(object):
    """Stores the manifest items for the CpCommand class."""

    def __init__(self, path):
      # self.items contains a dictionary of rows
      self.manifest_fp = None
      self.items = {}
      self.manifest_filter = {}
      self.lock = threading.Lock()

      manifest_path = os.path.expanduser(path)
      self._ParseManifest(manifest_path)
      self._CreateManifestFile(manifest_path)

    def __del__(self):
      if self.manifest_fp:
        self.manifest_fp.close()

    def _ParseManifest(self, path):
      """
      Load and parse a manifest file. This information will be used to skip
      any files that have a skip or OK status.
      """
      try:
        if os.path.exists(path):
          with open(path, 'rb') as f:
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
                      'Missing headers in manifest file: %s' % path)
              first_row = False
              source = row[source_index]
              result = row[result_index]
              if result in ['OK', 'skip']:
                # We're always guaranteed to take the last result of a specific
                # source uri.
                self.manifest_filter[source] = result
      except IOError as ex:
        raise CommandException('Could not parse %s' % path)

    def WasSuccessful(self, src):
      """ Returns whether the specified src uri was marked as successful."""
      return src in self.manifest_filter

    def _CreateManifestFile(self, path):
      """Opens the manifest file and assigns it to the file pointer."""
      try:
        if not os.path.exists(path) or os.stat(path).st_size == 0:
          # Add headers to the new file.
          with open(path, 'wb', 1) as f:
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
        # This file pointer will be closed in the destructor.
        self.manifest_fp = open(path, 'a', 1)  # 1 == line buffered
      except IOError:
        raise CommandException('Could not create manifest file.')

    def Set(self, uri, key, value):
      if value is None:
        # In case we don't have any information to set we bail out here.
        # This is so that we don't clobber existing information.
        # To zero information pass '' instead of None.
        return
      if uri in self.items:
        self.items[uri][key] = value
      else:
        self.items[uri] = {key:value}

    def Initialize(self, source_uri, destination_uri):
      # Always use the source_uri as the key for the item. This is unique.
      self.Set(source_uri, 'source_uri', source_uri)
      self.Set(source_uri, 'destination_uri', destination_uri)
      self.Set(source_uri, 'start_time', datetime.datetime.utcnow())

    def SetResult(self, source_uri, bytes_transferred, result,
                  description=''):
      self.Set(source_uri, 'bytes', bytes_transferred)
      self.Set(source_uri, 'result', result)
      self.Set(source_uri, 'description', description)
      self.Set(source_uri, 'end_time', datetime.datetime.utcnow())
      self._WriteRowToManifestFile(source_uri)
      self._RemoveItemFromManifest(source_uri)

    def _WriteRowToManifestFile(self, uri):
      row_item = self.items[uri]
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
      self.lock.acquire()
      try:
        writer = csv.writer(self.manifest_fp)
        writer.writerow(data)
      finally:
        self.lock.release()

    def _RemoveItemFromManifest(self, uri):
      # Remove the item from the dictionary since we're done with it and
      # we don't want the dictionary to grow too large in memory for no good
      # reason.
      del self.items[uri]


class ItemExistsError(Exception):
  """Exception class for objects that are skipped because they already exist."""
  pass


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
  # If the source uri argument had a wildcard and wasn't expanded by the
  # shell, then uri.names_file() will always be true, so we check for
  # this case explicitly.
  assert ((not uri.names_file()) or ContainsWildcard(uri.object_name))
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

def _HashFilename(filename):
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
  if isinstance(filename, unicode):
    filename = filename.encode('utf-8')
  else:
    filename = unicode(filename, 'utf8').encode('utf-8')
  m = hashlib.sha1(filename)
  return "TRACKER_" + m.hexdigest() + '.' + filename[-16:]

def _DivideAndCeil(dividend, divisor):
  """Returns ceil(dividend / divisor), taking care to avoid the pitfalls of
     floating point arithmetic that could otherwise yield the wrong result
     for large numbers.
  """
  quotient = dividend // divisor
  if (dividend % divisor) != 0:
    quotient += 1
  return quotient

def _GetPartitionInfo(file_size, max_components, default_component_size):
  """
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

def _DeleteKeyFn(key):
  """Wrapper function to be used with command.Apply()."""
  return key.delete_key()

def _ParseParallelUploadTrackerFile(tracker_file):
  """Parse the tracker file (if any) from the last parallel composite upload
     attempt. The tracker file is of the format described in
     _WriteParallelUploadTrackerFile. If the file doesn't exist or cannot be
     read, then the upload will start from the beginning.

     Args:
       tracker_file: The name of the file to parse.

     Returns:
       random_prefix: A randomly-generated prefix to the name of the
                      temporary components.
       existing_objects: A list of ObjectFromTracker objects representing
                         the set of files that have already been uploaded.
  """
  existing_objects = []
  try:
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
    if generation == '':
      generation = None
    existing_objects.append(ObjectFromTracker(name, generation))
    i += 2
  return (random_prefix, existing_objects)

def _WriteParallelUploadTrackerFile(tracker_file, random_prefix, components):
  """Writes information about components that were successfully uploaded so
     that the upload can be resumed at a later date. The tracker file has
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
  for component in components:
    generation = None
    generation = component.generation
    if not generation:
      generation = ''
    lines += [component.object_name, generation]
  lines = [line + '\n' for line in lines]
  open(tracker_file, 'w').close()  # Clear the file.
  with open(tracker_file, 'w') as f:
    f.writelines(lines)

def FilterExistingComponents(dst_args, existing_components,
                             bucket_name, suri_builder):
  """Given the list of all target objects based on partitioning the file and
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
    if not (component_name in existing_component_names):
      components_to_upload.append(dst_args[component_name])

  # Don't reuse any temporary components whose MD5 doesn't match the current
  # MD5 of the corresponding part of the file. If the bucket is versioned,
  # also make sure that we delete the existing temporary version.
  existing_objects_to_delete = []
  uploaded_components = []
  for tracker_object in existing_components:
    if not tracker_object.object_name in dst_args.keys():
      # This could happen if the component size has changed.
      uri = MakeGsUri(bucket_name, tracker_object.object_name, suri_builder)
      uri.generation = tracker_object.generation
      existing_objects_to_delete.append(uri)
      continue
    dst_arg = dst_args[tracker_object.object_name]
    file_part = FilePart(dst_arg.filename, dst_arg.file_start,
                         dst_arg.file_length)
    # TODO: calculate MD5's in parallel when possible.
    content_md5 = _CalculateMd5FromContents(file_part)

    try:
      # Get the MD5 of the currently-existing component.
      blr = BucketListingRef(dst_arg.dst_uri)
      etag = blr.GetKey().etag
    except Exception as e:
      # We don't actually care what went wrong - we couldn't retrieve the
      # object to check the MD5, so just upload it again.
      etag = None
    if etag != (('"%s"') % content_md5):
      components_to_upload.append(dst_arg)
      if tracker_object.generation:
        # If the old object doesn't have a generation (i.e., it isn't in a
        # versioned bucket), then we will just overwrite it anyway.
        invalid_component_with_generation = copy.deepcopy(dst_arg.dst_uri)
        invalid_component_with_generation.generation = tracker_object.generation
        existing_objects_to_delete.append(invalid_component_with_generation)
    else:
      uri = copy.deepcopy(dst_arg.dst_uri)
      uri.generation = tracker_object.generation
      uploaded_components.append(uri)
  if uploaded_components:
    logging.info(("Found %d existing temporary components to reuse.")
                  % len(uploaded_components))
  return (components_to_upload, uploaded_components,
          existing_objects_to_delete)

def MakeGsUri(bucket, filename, suri_builder):
  """Returns a StorageUri for an object in GCS."""
  return suri_builder.StorageUri(bucket + '/' + filename)

def _CalculateMd5FromContents(file):
  """Calculates the MD5 hash of the contents of a file.

     Args:
       file: An already-open file object.
  """
  current_md5 = md5()
  file.seek(0)
  while True:
    data = file.read(8192)
    if not data:
      break
    current_md5.update(data)
  file.seek(0)
  return current_md5.hexdigest()
