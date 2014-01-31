# Copyright 2013 Google Inc. All Rights Reserved.
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
"""Implementation of lifecycle configuration command for GCS buckets."""
import sys

from gslib.command import Command
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.command import CommandSpecKey
from gslib.command import FILE_URLS_OK
from gslib.command import MAX_ARGS
from gslib.command import MIN_ARGS
from gslib.command import NO_MAX
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
from gslib.translation_helper import LifecycleTranslation
from gslib.util import UrlsAreForSingleProvider


_GET_SYNOPSIS = """
  gsutil lifecycle get url
"""

_SET_SYNOPSIS = """
  gsutil lifecycle set config-xml-file url...
"""

_SYNOPSIS = _GET_SYNOPSIS + _SET_SYNOPSIS.lstrip('\n') + '\n'

_GET_DESCRIPTION = """
<B>GET</B>
  Gets the lifecycle configuration for a given bucket. You can get the
  lifecycle configuration for only one bucket at a time. The output can be
  redirected into a file, edited and then updated via the set sub-command.

"""

_SET_DESCRIPTION = """
<B>SET</B>
  Sets the lifecycle configuration on one or more buckets. The config-json-file
  specified on the command line should be a path to a local file containing
  the lifecycle congfiguration JSON document.

"""

_DESCRIPTION = """
  The lifecycle command can be used to get or set lifecycle management policies
  for the given bucket(s). This command is supported for buckets only, not
  objects. For more information on object lifecycle management, please see the
  `developer guide <https://developers.google.com/storage/docs/lifecycle>`_.

  The lifecycle command has two sub-commands:
""" + _GET_DESCRIPTION + _SET_DESCRIPTION + """
<B>EXAMPLES</B>
  The following lifecycle configuration JSON document specifies that all objects
  in this bucket that are more than 365 days old will be deleted automatically:

  {
    "rule":
    [
      {
        "action": {"type": "Delete"},
        "condition": {"age": 365}
      }
    ]
  }

  The following (empty) lifecycle configuration JSON document removes all
  lifecycle configuration for a bucket:

  {}

"""

_detailed_help_text = CreateHelpText(_SYNOPSIS, _DESCRIPTION)

_get_help_text = CreateHelpText(_GET_SYNOPSIS, _GET_DESCRIPTION)
_set_help_text = CreateHelpText(_SET_SYNOPSIS, _SET_DESCRIPTION)


class LifecycleCommand(Command):
  """Implementation of gsutil lifecycle command."""

  # Command specification (processed by parent class).
  command_spec = {
      # Name of command.
      COMMAND_NAME: 'lifecycle',
      # List of command name aliases.
      COMMAND_NAME_ALIASES: ['lifecycleconfig'],
      # Min number of args required by this command.
      MIN_ARGS: 2,
      # Max number of args required by this command, or NO_MAX.
      MAX_ARGS: NO_MAX,
      # Getopt-style string specifying acceptable sub args.
      SUPPORTED_SUB_ARGS: '',
      # True if file URLs acceptable for this command.
      FILE_URLS_OK: True,
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
      HELP_NAME: 'lifecycle',
      # List of help name aliases.
      HELP_NAME_ALIASES: ['getlifecycle', 'setlifecycle'],
      # Type of help)
      HELP_TYPE: HelpType.COMMAND_HELP,
      # One line summary of this help.
      HELP_ONE_LINE_SUMMARY: 'Get or set lifecycle configuration for a bucket',
      # The full help text.
      HELP_TEXT: _detailed_help_text,
      # Help text for sub-commands.
      SUBCOMMAND_HELP_TEXT: {'get': _get_help_text,
                             'set': _set_help_text},
  }

  def _SetLifecycleConfig(self):
    """Sets lifecycle configuration for a Google Cloud Storage bucket."""
    lifecycle_arg = self.args[0]
    url_args = self.args[1:]
    # Disallow multi-provider 'lifecycle set' requests.
    if not UrlsAreForSingleProvider(url_args):
      raise CommandException('"%s" command spanning providers not allowed.' %
                             self.command_name)

    # Open, read and parse file containing JSON document.
    lifecycle_file = open(lifecycle_arg, 'r')
    lifecycle_txt = lifecycle_file.read()
    lifecycle_file.close()
    lifecycle = LifecycleTranslation.JsonLifecycleToMessage(lifecycle_txt)

    # Iterate over URLs, expanding wildcards and setting the lifecycle on each.
    some_matched = False
    for url_str in url_args:
      bucket_iter = self.GetBucketUrlIterFromArg(url_str,
                                                 bucket_fields=['lifecycle'])
      for blr in bucket_iter:
        url = StorageUrlFromString(blr.url_string)
        some_matched = True
        self.logger.info('Setting lifecycle configuration on %s...',
                         blr.url_string)
        if url.scheme == 's3':
          self.gsutil_api.XmlPassThroughSetLifecycle(lifecycle_txt,
                                                     url.GetUrlString(),
                                                     provider=url.scheme)
        else:
          bucket_metadata = apitools_messages.Bucket(lifecycle=lifecycle)
          self.gsutil_api.PatchBucket(url.bucket_name, bucket_metadata,
                                      provider=url.scheme, fields=['id'])
    if not some_matched:
      raise CommandException('No URLs matched')
    return 0

  def _GetLifecycleConfig(self):
    """Gets lifecycle configuration for a Google Cloud Storage bucket."""
    bucket_url, bucket_metadata = self.GetSingleBucketUrlFromArg(
        self.args[0], bucket_fields=['lifecycle'])

    if bucket_url.scheme == 's3':
      sys.stdout.write(self.gsutil_api.XmlPassThroughGetLifecycle(
          bucket_url.GetUrlString(),
          provider=bucket_url.scheme))
    else:
      if bucket_metadata.lifecycle and bucket_metadata.lifecycle.rule:
        sys.stdout.write(LifecycleTranslation.JsonLifecycleFromMessage(
            bucket_metadata.lifecycle))
      else:
        sys.stdout.write('%s has no lifecycle configuration.\n' % bucket_url)

    return 0

  def RunCommand(self):
    """Command entry point for the lifecycle command."""
    subcommand = self.args.pop(0)
    if subcommand == 'get':
      return self._GetLifecycleConfig()
    elif subcommand == 'set':
      return self._SetLifecycleConfig()
    else:
      raise CommandException('Invalid subcommand "%s" for the %s command.' %
                             (subcommand, self.command_name))
