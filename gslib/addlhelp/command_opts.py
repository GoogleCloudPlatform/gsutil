# Copyright 2012 Google Inc. All Rights Reserved.
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
"""Additional help about gsutil command-level options."""

from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HELP_TYPE
from gslib.help_provider import HelpProvider
from gslib.help_provider import HelpType

_detailed_help_text = ("""
<B>SYNOPSIS</B>
  Top-level gsutil Options


<B>DESCRIPTION</B>
  gsutil supports separate options for the top-level gsutil command and
  the individual sub-commands (like cp, rm, etc.) The top-level options
  control behavior of gsutil that apply across commands. For example, in
  the command:

    gsutil -m cp -p file gs://bucket/obj

  the -m option applies to gsutil, while the -p option applies to the cp
  sub-command.


<B>OPTIONS</B>
  -d          Shows HTTP requests/headers.

  -D          Shows HTTP requests/headers plus additional debug info needed when
              posting support requests.

  -DD         Shows HTTP requests/headers plus additional debug info plus HTTP
              upstream payload.

  -h          Allows you to specify certain HTTP headers, for example:

                gsutil -h "Cache-Control:public,max-age=3600" \\
                       -h "Content-Type:text/html" cp ...

              Note that you need to quote the headers/values that
              contain spaces (such as "Content-Disposition: attachment;
              filename=filename.ext"), to avoid having the shell split them
              into separate arguments.
              
              The following headers are supported:
              Cache-Control
              Content-Disposition
              Content-Encoding
              Content-Language
              Content-MD5
              Content-Type
              Custom metadata headers with a matching Cloud Storage Provider
              prefix, such as:
                x-goog-meta-
              
              Note that for the Cache Control header, the Google Cloud Storage
              JSON API respects only the no-cache and max-age parameters.

              See also "gsutil help setmeta" for the ability to set metadata
              fields on objects after they have been uploaded.

  -m          Causes supported operations (acl ch, acl set, cp, mv, rm,
              and setmeta) to run in parallel. This can significantly improve
              performance if you are uploading, downloading, moving, removing,
              or changing ACLs on a large number of files over a fast network
              connection.

              gsutil performs the specified operation using a combination of
              multi-threading and multi-processing, using a number of threads
              and processors determined by the parallel_thread_count and
              parallel_process_count values set in the boto configuration
              file. You might want to experiment with these values, as the
              best values can vary based on a number of factors, including
              network speed, number of CPUs, and available memory.

              Using the -m option may make your performance worse if you
              are using a slower network, such as the typical network speeds
              offered by non-business home network plans.

              If a download or upload operation using parallel transfer fails
              before the entire transfer is complete (e.g. failing after 300 of
              1000 files have been transferred), you will need to restart the
              entire transfer.
              
              Also, although most commands will normally fail upon encountering
              an error when the -m flag is disabled, all commands will
              continue to try all operations when -m is enabled with multiple
              threads or processes, and the number of failed operations (if any)
              will be reported at the end of the command's execution.

              WARNING: If you use the gsutil -m option when copying data
              between versioned buckets, object version ordering will not be
              preserved. For more information see the
              "COPYING VERSIONED BUCKETS" section under
              'gsutil help versions'.

  -o          Set/override values in the boto configuration value, in the format
              <section>:<name>=<value>, e.g. gsutil -o "Boto:proxy=host" ...

  -q          Causes gsutil to perform operations quietly, i.e., without
              reporting progress indicators of files being copied or removed,
              etc. Errors are still reported. This option can be useful for
              running gsutil from a cron job that logs its output to a file, for
              which the only information desired in the log is failures.

  -s          Tells gsutil to use a simulated storage provider (for testing).
""")


class CommandOptions(HelpProvider):
  """Additional help about gsutil command-level options."""

  help_spec = {
      # Name of command or auxiliary help info for which this help applies.
      HELP_NAME: 'options',
      # List of help name aliases.
      HELP_NAME_ALIASES: ['arg', 'args', 'cli', 'opt', 'opts'],
      # Type of help:
      HELP_TYPE: HelpType.ADDITIONAL_HELP,
      # One line summary of this help.
      HELP_ONE_LINE_SUMMARY: 'Top-Level Command-Line Options',
      # The full help text.
      HELP_TEXT: _detailed_help_text,
  }
