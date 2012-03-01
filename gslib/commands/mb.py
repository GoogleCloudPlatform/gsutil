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
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HelpType
from gslib.help_provider import HELP_TYPE
from gslib.util import NO_MAX

_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil mb [-l location] [-p proj_id] uri...


<B>DESCRIPTION</B>
  The mb command creates a new bucket. Google Cloud Storage has a single
  namespace, so you will not be allowed to create a bucket with a name already
  in use by another user. You can, however, carve out parts of the bucket name
  space corresponding to your company's domain name (see "gsutil help naming").

  If you specify a location for the bucket (using the -l option), the
  bucket will be created in the named geographic location. Once created in
  a location, a bucket cannot be moved to a different location; you would
  instead need to create a new bucket and move the data over and then delete
  the original bucket.

  If you don't specify a project ID using the -p option, the bucket
  will be created using the default project ID specified in your gsutil
  configuration file (see "gsutil help config"). For more details about
  projects see "gsutil help projects".


<B>OPTIONS</B>
  -l location Can be us or eu. Default is us.

  -p proj_id  Specifies the project ID under which to create the bucket.
""")


class MbCommand(Command):
  """Implementation of gsutil mb command."""

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'mb',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : ['makebucket', 'createbucket', 'md', 'mkdir'],
    # Min number of args required by this command.
    MIN_ARGS : 1,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : NO_MAX,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : 'l:p:',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : False,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 0,
    # True if must configure gsutil before running command.
    CONFIG_REQUIRED : True,
  }
  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'mb',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['makebucket', 'createbucket', 'md', 'mkdir'],
    # Type of help:
    HELP_TYPE : HelpType.COMMAND_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Make buckets',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }

  # Command entry point.
  def RunCommand(self):
    location = ''
    if self.sub_opts:
      for o, a in self.sub_opts:
        if o == '-l':
          location = a
        elif o == '-p':
          self.proj_id_handler.SetProjectId(a)

    if not self.headers:
      headers = {}
    else:
      headers = self.headers.copy()

    for bucket_uri_str in self.args:
      bucket_uri = self.suri_builder.StorageUri(bucket_uri_str)
      self.proj_id_handler.FillInProjectHeaderIfNeeded('mb', bucket_uri,
                                                       headers)
      print 'Creating %s...' % bucket_uri
      bucket_uri.create_bucket(headers=headers, location=location)

