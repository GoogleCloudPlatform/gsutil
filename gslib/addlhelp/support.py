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
"""Additional help about technical and billing support."""

from gslib.help_provider import HelpProvider

_detailed_help_text = ("""
<B>TECHNICAL SUPPORT</B>
  If you have any questions or encounter any problems with Google Cloud Storage,
  please first read the `FAQ <https://developers.google.com/storage/docs/faq>`_.

  If you still have questions please use one of the following methods as
  appropriate, providing the details noted below:

  A) For API, tool usage, or other software development-related questions,
  please search for and post questions on Stack Overflow, using the official
  `google-cloud-storage tag
  <http://stackoverflow.com/questions/tagged/google-cloud-storage>`_. Our
  support team actively monitors questions to this tag and we'll do our best to
  respond.

  B) For questions regarding your account, billing, Terms Of Service, Google
  Cloud Console, or other administration-related questions please email
  gs-team@google.com.

  To help us diagnose any issues you encounter, please provide these details
  in addition to the description of your problem:

  - The resource you are attempting to access (bucket name, object name)
  - The operation you attempted (GET, PUT, etc.)
  - The time and date (including timezone) at which you encountered the problem
  - The tool or library you use to interact with Google Cloud Storage
  - If you can use gsutil to reproduce your issue, specify the -D option to
    display your request's HTTP details. Provide these details with your post
    to the forum as they can help us further troubleshoot your issue.

  Warning: The gsutil -d, -D, and -DD options will also print the authentication
  header with authentication credentials for your Google Cloud Storage account.
  Make sure to remove any "Authorization:" headers before you post HTTP details
  to the forum. Note also that if you upload files large enough to use resumable
  uploads, the resumable upload IDs are security-sensitive while an upload
  is not yet complete, so should not be posted on public forums.

  If you make any local modifications to gsutil, please make sure to use
  a released copy of gsutil (instead of your locally modified copy) when
  providing the gsutil -D output noted above. We cannot support versions
  of gsutil that include local modifications. (However, we're open to user
  contributions; see "gsutil help dev".)


<B>BILLING AND ACCOUNT QUESTIONS</B>
  For questions about billing or account issues, please visit
  https://developers.google.com/storage/docs/pricing-and-terms.
  If you want to cancel billing, follow the instructions at
  `Google Developers Console<https://developers.google.com/console/help/billing>`
  Caution: When you disable billing, you also disable the Google Cloud Storage
  service. Make sure you want to disable the Google Cloud Storage service
  before you disable billing.
""")


class CommandOptions(HelpProvider):
  """Additional help about technical and billing support."""

  # Help specification. See help_provider.py for documentation.
  help_spec = HelpProvider.HelpSpec(
      help_name = 'support',
      help_name_aliases = ['techsupport', 'tech support', 'technical support',
                           'billing', 'faq', 'questions'],
      help_type = 'additional_help',
      help_one_line_summary = 'Google Cloud Storage Support',
      help_text = _detailed_help_text,
      subcommand_help_text = {},
  )
