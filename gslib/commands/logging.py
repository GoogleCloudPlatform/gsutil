# Copyright 2011 Google Inc. All Rights Reserved.
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

import getopt
import sys
import textwrap

from gslib.command import Command
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.command import FILE_URIS_OK
from gslib.command import MAX_ARGS
from gslib.command import MIN_ARGS
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
from gslib.util import NO_MAX
from gslib.util import UnaryDictToXml
from xml.dom.minidom import parseString as XmlParseString

_SET_SYNOPSIS = """
  gsutil logging set on -b logging_bucket [-o log_object_prefix] uri...
  gsutil logging set off uri...
"""

_GET_SYNOPSIS = """
  gsutil logging get uri
"""

_SYNOPSIS =  _SET_SYNOPSIS + _GET_SYNOPSIS.lstrip('\n') + '\n'

_SET_DESCRIPTION = """
<B>SET</B>
  The set sub-command has two sub-commands:

<B>ON</B>
  The "gsutil set on" command will enable access logging of the
  buckets named by the specified uris, outputting log files in the specified
  logging_bucket. logging_bucket must already exist, and all URIs must name
  buckets (e.g., gs://bucket). The required bucket parameter specifies the
  bucket to which the logs are written, and the optional log_object_prefix
  parameter specifies the prefix for log object names. The default prefix
  is the bucket name. For example, the command:

    gsutil logging set on -b gs://my_logging_bucket -o AccessLog \\
        gs://my_bucket1 gs://my_bucket2

  will cause all read and write activity to objects in gs://mybucket1 and
  gs://mybucket2 to be logged to objects prefixed with the name "AccessLog",
  with those log objects written to the bucket gs://my_logging_bucket.

  Next, you need to grant cloud-storage-analytics@google.com write access to
  the log bucket, using this command:

    acl ch -g cloud-storage-analytics@google.com:W gs://my_logging_bucket

  Note that log data may contain sensitive information, so you should make
  sure to set an appropriate default bucket ACL to protect that data. (See
  "gsutil help defacl".)

<B>OFF</B>
  This command will disable access logging of the buckets named by the
  specified uris. All URIs must name buckets (e.g., gs://bucket).

  No logging data is removed from the log buckets when you disable logging,
  but Google Cloud Storage will stop delivering new logs once you have
  run this command.

"""

_GET_DESCRIPTION = """
<B>GET</B>
  If logging is enabled for the specified bucket uri, the server responds
  with a <Logging> XML element that looks something like this:

    <?xml version="1.0" ?>
    <Logging>
        <LogBucket>
            logs-bucket
        </LogBucket>
        <LogObjectPrefix>
            my-logs-enabled-bucket
        </LogObjectPrefix>
    </Logging>

  If logging is not enabled, an empty <Logging> element is returned.

  You can download log data from your log bucket using the gsutil cp command.

"""

_DESCRIPTION = """
  Google Cloud Storage offers access logs and storage data in the form of
  CSV files that you can download and view. Access logs provide information
  for all of the requests made on a specified bucket in the last 24 hours,
  while the storage logs provide information about the storage consumption of
  that bucket for the last 24 hour period. The logs and storage data files
  are automatically created as new objects in a bucket that you specify, in
  24 hour intervals.

  The logging command has two sub-commands:
""" + _SET_DESCRIPTION + _GET_DESCRIPTION + """

<B>ACCESS LOG AND STORAGE DATA FIELDS</B>
  For a complete list of access log fields and storage data fields, see:
  https://developers.google.com/storage/docs/accesslogs#reviewing
"""

_detailed_help_text = CreateHelpText(_SYNOPSIS, _DESCRIPTION)

_get_help_text = CreateHelpText(_GET_SYNOPSIS, _GET_DESCRIPTION)
_set_help_text = CreateHelpText(_SET_SYNOPSIS, _SET_DESCRIPTION)


class LoggingCommand(Command):
  """Implementation of gsutil logging command."""

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'logging',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : ['disablelogging', 'enablelogging', 'getlogging'],
    # Min number of args required by this command.
    MIN_ARGS : 2,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : NO_MAX,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : 'b:o:',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : False,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 0,
  }
  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'logging',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['loggingconfig', 'logs', 'log', 'getlogging',
                         'enablelogging', 'disablelogging'],
    # Type of help:
    HELP_TYPE : HelpType.COMMAND_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Configure or retrieve logging on buckets',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
    # Help text for sub-commands.
    SUBCOMMAND_HELP_TEXT : {'get' : _get_help_text,
                            'set' : _set_help_text},
  }

  def _Get(self):
    uri_args = self.args

    # Iterate over URIs, expanding wildcards, and getting the website
    # configuration on each.
    some_matched = False
    for uri_str in uri_args:
      for blr in self.WildcardIterator(uri_str):
        uri = blr.GetUri()
        if not uri.names_bucket():
          raise CommandException('URI %s must name a bucket for the %s command'
                                 % (uri, self.command_name))
        some_matched = True
        sys.stderr.write('Getting logging config on %s...\n' % uri)
        logging_config_xml = UnaryDictToXml(uri.get_logging_config())
        sys.stdout.write(XmlParseString(logging_config_xml).toprettyxml())
    if not some_matched:
      raise CommandException('No URIs matched')

  def _Enable(self):
    # Disallow multi-provider 'logging set on' calls, because the schemas
    # differ.
    storage_uri = self.UrisAreForSingleProvider(self.args)
    if not storage_uri:
      raise CommandException('"logging set on" command spanning providers not '
                             'allowed.')
    target_bucket_uri = None
    target_prefix = None
    for opt, opt_arg in self.sub_opts:
      if opt == '-b':
        target_bucket_uri = self.suri_builder.StorageUri(opt_arg)
      if opt == '-o':
        target_prefix = opt_arg

    if not target_bucket_uri:
      raise CommandException('"logging set on" requires \'-b <log_bucket>\' '
                             'option')
    if not target_bucket_uri.names_bucket():
      raise CommandException('-b option must specify a bucket uri')

    did_some_work = False
    for uri_str in self.args:
      for uri in self.WildcardIterator(uri_str).IterUris():
        if uri.names_object():
          raise CommandException('logging cannot be applied to objects')
        did_some_work = True
        self.logger.info('Enabling logging on %s...', uri)
        self.proj_id_handler.FillInProjectHeaderIfNeeded(
            'enablelogging', storage_uri, self.headers)
        uri.enable_logging(target_bucket_uri.bucket_name, target_prefix, False,
                           self.headers)
    if not did_some_work:
      raise CommandException('No URIs matched')

  def _Disable(self):
    did_some_work = False
    for uri_str in self.args:
      for uri in self.WildcardIterator(uri_str).IterUris():
        if uri.names_object():
          raise CommandException('logging cannot be applied to objects')
        did_some_work = True
        self.logger.info('Disabling logging on %s...', uri)
        self.proj_id_handler.FillInProjectHeaderIfNeeded('disablelogging',
                                                         uri, self.headers)
        uri.disable_logging(False, self.headers)
    if not did_some_work:
      raise CommandException('No URIs matched')

  # Command entry point.
  def RunCommand(self):
    # Parse the subcommand and alias for the new logging command.
    action_subcommand = self.args.pop(0)
    if action_subcommand == 'get':
      func = self._Get
    elif action_subcommand == 'set':
      state_subcommand = self.args.pop(0)
      if not self.args:
        self._RaiseWrongNumberOfArgumentsException()
      if state_subcommand == 'on':
        func = self._Enable
      elif state_subcommand == 'off':
        func = self._Disable
      else:
        raise CommandException((
            'Invalid subcommand "%s" for the "%s %s" command.\n'
            'See "gsutil help logging".') %
            (state_subcommand, self.command_name, action_subcommand))
    else:
      raise CommandException(('Invalid subcommand "%s" for the %s command.\n'
                             'See "gsutil help logging".') %
                             (action_subcommand, self.command_name))
    try:
      (self.sub_opts, self.args) = getopt.getopt(self.args,
          self.command_spec[SUPPORTED_SUB_ARGS])
      self.CheckArguments()
    except getopt.GetoptError, e:
      raise CommandException('%s for "%s" command.' % (e.msg,
                                                       self.command_name))
    func()
    return 0
