# -*- coding: utf-8 -*-
# Copyright 2014 Google Inc. All Rights Reserved.
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
"""Additional help text about retry handling."""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

from gslib.help_provider import HelpProvider

_DETAILED_HELP_TEXT = ("""
<B>RETRY STRATEGY</B>
  If a gsutil operation fails for the one of the following reasons, you must
  take action before retrying:

  - Invalid credentials.
  - Network unreachable because of a proxy configuration problem.
  - Access denied, because the bucket or object you are trying to use has an
    ACL that doesn't permit the action you're trying to perform.
  - Individual operations that fail within a command that is running operations
    in parallel using the -m top-level flag.
  
  gsutil retries the following errors without requiring you to take additional action:
  
  - Transient network failures.
  - HTTP 429 and 5xx error codes.
  - HTTP 408 error codes when performing a resumable upload.
  
  For retryable errors, gsutil retries requests using a truncated binary
  exponential backoff strategy:

  - Wait a random period between [0..1] seconds and retry;
  - If that fails, wait a random period between [0..2] seconds and retry;
  - If that fails, wait a random period between [0..4] seconds and retry;
  - And so on, up to a configurable maximum number of retries,
  with each retry period bounded by a configurable maximum period of time.

  By default, gsutil retries 23 times over 1+2+4+8+16+32+60 seconds
  for about 10 minutes. You can adjust the number of retries and maximum delay
  of any individual retry by editing the num_retries and max_retry_delay
  configuration variables in the "[Boto]" section of the .boto config file.
  Most of the time, you shouldn't need to change these values.

  For data transfers using the gsutil cp and rsync commands, gsutil provides
  additional retry functionality in the form of resumable transfers.
  Essentially, a transfer that was interrupted because of a transient error
  can be restarted without starting over from scratch. For more details
  about this, see the "RESUMABLE TRANSFERS" section of "gsutil help cp".
  
  For information about how other Cloud Storage tools handle retry strategy,
  see `Retry strategy <https://cloud.google.com/storage/docs/retry-strategy>`_.
""")


class CommandOptions(HelpProvider):
  """Additional help text about retry handling."""

  # Help specification. See help_provider.py for documentation.
  help_spec = HelpProvider.HelpSpec(
      help_name='retries',
      help_name_aliases=['retry', 'backoff', 'reliability'],
      help_type='additional_help',
      help_one_line_summary='Retry Handling Strategy',
      help_text=_DETAILED_HELP_TEXT,
      subcommand_help_text={},
  )
