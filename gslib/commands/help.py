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

import sys

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

usage_string = """
SYNOPSIS
  gsutil [-d][-D] [-h header]... [-m] [command args...]

  -d option shows HTTP requests/headers.
  -D option includes additional debug info needed when posting support
     requests to gs-discussion@googlegroups.com.
  -DD includes HTTP upstream payload.

  -h option allows you to specify additional HTTP headers, for example:
     gsutil -h "Cache-Control:public,max-age=3600" -h "Content-Type:text/html" cp ...

  -m option causes supported operations (cp, mv, rm) to run in parallel.

  Commands:
    Concatenate object content to stdout:
      cat [-h] uri...
        -h  Prints short header for each object.
    Copy objects:
      cp [-a canned_acl] [-e] [-p] [-t] [-z ext1,ext2,...] src_uri dst_uri
        - or -
      cp [-a canned_acl] [-e] [-p] [-R] [-t] [-z extensions] uri... dst_uri
        -a Sets named canned_acl when uploaded objects created (list below).
        -e Exclude symlinks. When specified, symbolic links will not be copied.
        -p Causes ACL to be preserved when copying in the cloud. Causes extra API calls.
        -R Causes directories and buckets to be copied recursively.
        -t Sets MIME type based on file extension.
        -z 'txt,html' Compresses file uploads with the given extensions.
      Use '-' in place of src_uri or dst_uri to perform streaming transfer.
    Disable logging on buckets:
      disablelogging uri...
    Enable logging on buckets:
      enablelogging -b log_bucket [-o log_object_prefix] uri...
        -b Log bucket.
        -o Prefix for log object names. Default value is the bucket name.
    Get ACL XML for a bucket or object (save and edit for "setacl" command):
      getacl uri
    Get default ACL XML for a bucket (save and edit for "setdefacl" command):
      getdefacl uri
    Get logging XML for a bucket:
      getlogging uri
    List buckets or objects:
      ls [-b] [-l] [-L] [-p proj_id] uri...
         -l Prints long listing (owner, length); -L provides more detail.
         -b Prints info about the bucket when used with a bucket URI.
         -p proj_id Specifies the project ID to use for listing buckets.
    Make buckets:
      mb [-l LocationConstraint] [-p proj_id] uri...
         -l can be us or eu. Default is us
         -p proj_id Specifies the project ID under which to create the bucket.
    Move/rename objects:
      mv [-p] src_uri dst_uri
        - or -
      mv [-p] uri... dst_uri
      The -p option causes ACL to be preserved when copying in the
      cloud. Causes extra API calls.
    Remove buckets:
      rb uri...
    Remove objects:
      rm [-f] uri...
         -f Continues despite errors when removing by wildcard.
    Set ACL on buckets and/or objects:
      setacl file-or-canned_acl_name uri...
    Set default ACL on buckets:
      setdefacl file-or-canned_acl_name uri...
    Print version info:
      ver
    Obtain credentials and create configuration file:
      config [options] [-o <config file>]
         Run 'gsutil config -h' for detailed help on this command.

  Omitting URI scheme defaults to "file". For example, "dir/file.txt" is
  equivalent to "file://dir/file.txt"

  URIs support object name wildcards, for example:
    gsutil cp gs://mybucket/[a-f]*.doc localdir

  Source directory or bucket names are implicitly wildcarded, so
    gsutil cp localdir gs://mybucket
  will recursively copy localdir.

  canned_acl_name can be one of: "private", "project-private",
  "public-read", "public-read-write", "authenticated-read",
  "bucket-owner-read", "bucket-owner-full-control"
"""

class HelpCommand(Command):
  """Implementation of gsutil help command."""

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'help',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : ['?'],
    # Min number of args required by this command.
    MIN_ARGS : 0,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : 0,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : '',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : False,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 0,
    # True if must configure gsutil before running command.
    CONFIG_REQUIRED : False,
  }

  # Command entry point.
  def RunCommand(self):
    sys.stderr.write(usage_string)
    sys.exit(0)
