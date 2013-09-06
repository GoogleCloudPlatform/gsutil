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

import sys
import xml

from boto import handler
from boto.gs.lifecycle import LifecycleConfig
from gslib.command import Command
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.command import FILE_URIS_OK
from gslib.command import MAX_ARGS
from gslib.command import MIN_ARGS
from gslib.command import NO_MAX
from gslib.command import PROVIDER_URIS_OK
from gslib.command import SUPPORTED_SUB_ARGS
from gslib.command import URIS_START_ARG
from gslib.exception import CommandException
from gslib.help_provider import CreateHelpText
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HelpType
from gslib.help_provider import HELP_TYPE
from gslib.help_provider import SUBCOMMAND_HELP_TEXT


_GET_SYNOPSIS = """
  gsutil lifecycle get uri
"""

_SET_SYNOPSIS = """
  gsutil lifecycle set config-xml-file uri...
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
  Sets the lifecycle configuration on one or more buckets. The config-xml-file
  specified on the command line should be a path to a local file containing
  the lifecycle congfiguration XML document.

"""

_DESCRIPTION = """
  The lifecycle command can be used to get or set lifecycle management policies
  for the given bucket(s). This command is supported for buckets only, not
  objects. For more information on object lifecycle management, please see the
  `developer guide <https://developers.google.com/storage/docs/lifecycle>`_.

  The lifecycle command has two sub-commands:
""" + _GET_DESCRIPTION + _SET_DESCRIPTION + """
<B>EXAMPLES</B>
  The following lifecycle configuration XML document specifies that all objects
  that are more than 365 days old will be deleted automatically:

    <?xml version="1.0" ?>
    <LifecycleConfiguration>
        <Rule>
            <Action>
                <Delete/>
            </Action>
            <Condition>
                <Age>365</Age>
            </Condition>
        </Rule>
    </LifecycleConfiguration>
"""

_detailed_help_text = CreateHelpText(_SYNOPSIS, _DESCRIPTION)

_get_help_text = CreateHelpText(_GET_SYNOPSIS, _GET_DESCRIPTION)
_set_help_text = CreateHelpText(_SET_SYNOPSIS, _SET_DESCRIPTION)


class LifecycleCommand(Command):
  """Implementation of gsutil lifecycle command."""

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'lifecycle',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : ['lifecycleconfig'],
    # Min number of args required by this command.
    MIN_ARGS : 2,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : NO_MAX,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : '',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : True,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 1,
  }
  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'lifecycle',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['getlifecycle', 'setlifecycle'],
    # Type of help)
    HELP_TYPE : HelpType.COMMAND_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Get or set lifecycle configuration for a bucket',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
    # Help text for sub-commands.
    SUBCOMMAND_HELP_TEXT : {'get' : _get_help_text,
                            'set' : _set_help_text},
  }

  # Get lifecycle configuration
  def _GetLifecycleConfig(self):
    # Wildcarding is allowed but must resolve to just one bucket.
    uris = list(self.WildcardIterator(self.args[0]).IterUris())
    if len(uris) == 0:
      raise CommandException('No URIs matched')
    if len(uris) != 1:
      raise CommandException('%s matched more than one URI, which is not\n'
          'allowed by the %s command' % (self.args[0], self.command_name))
    uri = uris[0]
    if not uri.names_bucket():
      raise CommandException('"%s" command must specify a bucket' %
                             self.command_name)
    lifecycle_config = uri.get_lifecycle_config(False, self.headers)
    # Pretty-print the XML to make it more easily human editable.
    parsed_xml = xml.dom.minidom.parseString(
        lifecycle_config.to_xml().encode('utf-8'))
    sys.stdout.write(parsed_xml.toprettyxml(indent='    '))
    return 0

  # Set lifecycle configuration
  def _SetLifecycleConfig(self):
    lifecycle_arg = self.args[0]
    uri_args = self.args[1:]
    # Disallow multi-provider setlifecycle requests.
    storage_uri = self.UrisAreForSingleProvider(uri_args)
    if not storage_uri:
      raise CommandException('"%s" command spanning providers not allowed.' %
                             self.command_name)

    # Open, read and parse file containing XML document.
    lifecycle_file = open(lifecycle_arg, 'r')
    lifecycle_txt = lifecycle_file.read()
    lifecycle_file.close()
    lifecycle_config = LifecycleConfig()

    # Parse XML document and convert into LifecycleConfig object.
    h = handler.XmlHandler(lifecycle_config, None)
    try:
      xml.sax.parseString(lifecycle_txt, h)
    except xml.sax._exceptions.SAXParseException, e:
      raise CommandException(
          'Requested lifecycle config is invalid: %s at line %s, column %s' %
          (e.getMessage(), e.getLineNumber(), e.getColumnNumber()))

    # Iterate over URIs, expanding wildcards, and setting the lifecycle config
    # on each.
    some_matched = False
    for uri_str in uri_args:
      for blr in self.WildcardIterator(uri_str):
        uri = blr.GetUri()
        if not uri.names_bucket():
          raise CommandException('URI %s must name a bucket for the %s command'
                                 % (str(uri), self.command_name))
        some_matched = True
        self.logger.info('Setting lifecycle configuration on %s...', uri)
        uri.configure_lifecycle(lifecycle_config, False, self.headers)
    if not some_matched:
      raise CommandException('No URIs matched')

    return 0

  # Command entry point.
  def RunCommand(self):
    subcommand = self.args.pop(0)
    if subcommand == 'get':
      return self._GetLifecycleConfig()
    elif subcommand == 'set':
      return self._SetLifecycleConfig()
    else:
      raise CommandException('Invalid subcommand "%s" for the %s command.' %
                             (subcommand, self.command_name))
