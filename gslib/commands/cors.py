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
"""Implementation of cors configuration command for GCS buckets."""

import sys

from gslib.command import Command
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.command import CommandSpecKey
from gslib.command import FILE_URLS_OK
from gslib.command import MAX_ARGS
from gslib.command import MIN_ARGS
from gslib.command import PROVIDER_URLS_OK
from gslib.command import SUPPORTED_SUB_ARGS
from gslib.command import URLS_START_ARG
from gslib.cs_api_map import ApiSelector
from gslib.exception import CommandException
from gslib.help_provider import CreateHelpText
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HELP_TYPE
from gslib.help_provider import HelpType
from gslib.help_provider import SUBCOMMAND_HELP_TEXT
from gslib.storage_url import StorageUrlFromString
from gslib.third_party.storage_apitools import storage_v1beta2_messages as apitools_messages
from gslib.translation_helper import CorsTranslation
from gslib.util import NO_MAX
from gslib.util import UrlsAreForSingleProvider


_GET_SYNOPSIS = """
gsutil cors get url
"""

_SET_SYNOPSIS = """
gsutil cors set cors-json-file url...
"""

_GET_DESCRIPTION = """
<B>GET</B>
  Gets the CORS configuration for a single bucket. The output from
  "cors get" can be redirected into a file, edited and then updated using
  "cors set".
"""

_SET_DESCRIPTION = """
<B>SET</B>
  Sets the CORS configuration for one or more buckets. The
  cors-json-file specified on the command line should be a path to a local
  file containing a JSON document as described above.
"""

_SYNOPSIS = _SET_SYNOPSIS + _GET_SYNOPSIS.lstrip('\n') + '\n\n'

_DESCRIPTION = ("""
  Gets or sets the Cross-Origin Resource Sharing (CORS) configuration on one or
  more buckets. This command is supported for buckets only, not objects. An
  example CORS JSON document looks like the folllowing:

  [
    {
      "origin": ["http://origin1.example.com"],
      "responseHeader": ["Content-Type"],
      "method": ["GET"],
      "maxAgeSeconds": 3600
    }
  ]

  The above JSON document explicitly allows cross-origin GET requests from
  http://origin1.example.com and may include the Content-Type response header.
  The preflight request may be cached for 1 hour.

  The following (empty) CORS JSON document removes all CORS configuration for
  a bucket:

  []

  The cors command has two sub-commands:
""" + '\n'.join([_GET_DESCRIPTION, _SET_DESCRIPTION]) + """
For more info about CORS, see http://www.w3.org/TR/cors/.
""")

_detailed_help_text = CreateHelpText(_SYNOPSIS, _DESCRIPTION)

_get_help_text = CreateHelpText(_GET_SYNOPSIS, _GET_DESCRIPTION)
_set_help_text = CreateHelpText(_SET_SYNOPSIS, _SET_DESCRIPTION)


class CorsCommand(Command):
  """Implementation of gsutil cors command."""

  # Command specification (processed by parent class).
  command_spec = {
      # Name of command.
      COMMAND_NAME: 'cors',
      # List of command name aliases.
      COMMAND_NAME_ALIASES: ['getcors', 'setcors'],
      # Min number of args required by this command.
      MIN_ARGS: 2,
      # Max number of args required by this command, or NO_MAX.
      MAX_ARGS: NO_MAX,
      # Getopt-style string specifying acceptable sub args.
      SUPPORTED_SUB_ARGS: '',
      # True if file URLs acceptable for this command.
      FILE_URLS_OK: False,
      # True if provider-only URLs acceptable for this command.
      PROVIDER_URLS_OK: False,
      # Index in args of first URL arg.
      URLS_START_ARG: 1,
      # List of supported APIs
      CommandSpecKey.GS_API_SUPPORT: [ApiSelector.XML, ApiSelector.JSON],
      # Default API to use for this command
      CommandSpecKey.GS_DEFAULT_API: ApiSelector.JSON,
  }
  help_spec = {
      # Name of command or auxiliary help info for which this help applies.
      HELP_NAME: 'cors',
      # List of help name aliases.
      HELP_NAME_ALIASES: ['getcors', 'setcors', 'cross-origin'],
      # Type of help)
      HELP_TYPE: HelpType.COMMAND_HELP,
      # One line summary of this help.
      HELP_ONE_LINE_SUMMARY: 'Set a CORS JSON document for one or more buckets',
      # The full help text.
      HELP_TEXT: _detailed_help_text,
      # Help text for sub-commands.
      SUBCOMMAND_HELP_TEXT: {'get': _get_help_text,
                             'set': _set_help_text},
  }

  def _CalculateUrlsStartArg(self):
    if not self.args:
      self._RaiseWrongNumberOfArgumentsException()
    if self.args[0].lower() == 'set':
      return 2
    else:
      return 1

  def _SetCors(self):
    """Sets CORS configuration on a Google Cloud Storage bucket."""
    cors_arg = self.args[0]
    url_args = self.args[1:]
    # Disallow multi-provider 'cors set' requests.
    if not UrlsAreForSingleProvider(url_args):
      raise CommandException('"%s" command spanning providers not allowed.' %
                             self.command_name)

    # Open, read and parse file containing JSON document.
    cors_file = open(cors_arg, 'r')
    cors_txt = cors_file.read()
    cors_file.close()

    self.api = self.gsutil_api.GetApiSelector(
        StorageUrlFromString(url_args[0]).scheme)

    cors = CorsTranslation.JsonCorsToMessageEntries(cors_txt)

    # Iterate over URLs, expanding wildcards and setting the CORS on each.
    some_matched = False
    for url_str in url_args:
      bucket_iter = self.GetBucketUrlIterFromArg(url_str, bucket_fields=['id'])
      for blr in bucket_iter:
        url = StorageUrlFromString(blr.url_string)
        some_matched = True
        self.logger.info('Setting CORS on %s...', blr.url_string)
        if url.scheme == 's3':
          self.gsutil_api.XmlPassThroughSetCors(cors_txt, url.GetUrlString(),
                                                provider=url.scheme)
        else:
          bucket_metadata = apitools_messages.Bucket(cors=cors)
          self.gsutil_api.PatchBucket(url.bucket_name, bucket_metadata,
                                      provider=url.scheme, fields=['id'])
    if not some_matched:
      raise CommandException('No URLs matched')
    return 0

  def _GetCors(self):
    """Gets CORS configuration for a Google Cloud Storage bucket."""
    bucket_url, bucket_metadata = self.GetSingleBucketUrlFromArg(
        self.args[0], bucket_fields=['cors'])

    if bucket_url.scheme == 's3':
      sys.stdout.write(self.gsutil_api.XmlPassThroughGetCors(
          bucket_url.GetUrlString(),
          provider=bucket_url.scheme))
    else:
      if bucket_metadata.cors:
        sys.stdout.write(
            CorsTranslation.MessageEntriesToJson(bucket_metadata.cors))
      else:
        sys.stdout.write('%s has no CORS configuration.\n' % bucket_url)
    return 0

  def RunCommand(self):
    """Command entry point for the cors command."""
    action_subcommand = self.args.pop(0)
    if action_subcommand == 'get':
      func = self._GetCors
    elif action_subcommand == 'set':
      func = self._SetCors
    else:
      raise CommandException(('Invalid subcommand "%s" for the %s command.\n'
                              'See "gsutil help cors".') %
                             (action_subcommand, self.command_name))
    return func()
