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
"""Additional help about gsutil's interaction with Cloud Storage APIs."""

from gslib.help_provider import HelpProvider

_detailed_help_text = ("""
<B>OVERVIEW</B>
  Google Cloud Storage offers two APIs: an XML and a JSON API. Gsutil can
  interact with both APIs. By default, gsutil versions starting with 4.0
  interact with the JSON API. If it is not possible to perform a command using
  one of the APIs (for example, the notification command is not supported in
  the XML API), gsutil will silently fall back to using the other API. Also,
  gsutil will automatically fall back to using the XML API when interacting
  with cloud storage providers that only support that API.

<B>CONFIGURING WHICH API IS USED</B>
  To use a certain API for interacting with Google Cloud Storage, you can set
  the 'prefer_api' variable in the "GSUtil" section of .boto config file to
  'xml' or 'json' like so:
    prefer_api = json

  This will cause gsutil to use that API where possible (falling back to the
  other API in cases as noted above).
""")


class CommandOptions(HelpProvider):
  """Additional help about gsutil's interaction with Cloud Storage APIs."""

  # Help specification. See help_provider.py for documentation.
  help_spec = HelpProvider.HelpSpec(
      help_name='apis',
      help_name_aliases=['XML', 'JSON', 'api', 'force_api', 'prefer_api'],
      help_type='additional_help',
      help_one_line_summary='Cloud Storage APIs',
      help_text=_detailed_help_text,
      subcommand_help_text={},
  )

