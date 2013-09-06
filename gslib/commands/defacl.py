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

from boto.exception import GSResponseError
from gslib import aclhelpers
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
from gslib.util import Retry

_SET_SYNOPSIS = """
  gsutil defacl set file-or-canned_acl_name uri...
"""

_GET_SYNOPSIS = """
  gsutil defacl get uri
"""

_CH_SYNOPSIS = """
  gsutil defacl ch -u|-g|-d <grant>... uri...
"""

_SET_DESCRIPTION = """
<B>SET</B>
  The "defacl set" command sets default object ACLs for the specified buckets.
  If you specify a default object ACL for a certain bucket, Google Cloud
  Storage applies the default object ACL to all new objects uploaded to that
  bucket.

  Similar to the "acl set" command, the file-or-canned_acl_name names either a
  canned ACL or the path to a file that contains ACL XML. (See "gsutil
  help acl" for examples of editing and setting ACLs via the
  acl command.)

  If you don't set a default object ACL on a bucket, the bucket's default
  object ACL will be project-private.

  Setting a default object ACL on a bucket provides a convenient way
  to ensure newly uploaded objects have a specific ACL, and avoids the
  need to back after the fact and set ACLs on a large number of objects
  for which you forgot to set the ACL at object upload time (which can
  happen if you don't set a default object ACL on a bucket, and get the
  default project-private ACL).
"""

_GET_DESCRIPTION = """
<B>GET</B>
  Gets the default ACL XML for a bucket, which you can save and edit
  for use with the "defacl set" command.
"""

_CH_DESCRIPTION = """
<B>CH</B>
  The "defacl ch" (or "defacl change") command updates the default object
  access control list for a bucket. The syntax is shared with the "acl ch"
  command, so see the "CH" section of "gsutil help acl" for the full help
  description.

<B>CH EXAMPLES</B>
  Add the user john.doe@example.com to the default object ACL on bucket
  example-bucket with WRITE access:

    gsutil defacl ch -u john.doe@example.com:WRITE gs://example-bucket

  Add the group admins@example.com to the default object ACL on bucket
  example-bucket with FULL_CONTROL access:

    gsutil defacl ch -g admins@example.com:FC gs://example-bucket
"""

_SYNOPSIS = (_SET_SYNOPSIS + _GET_SYNOPSIS.lstrip('\n') +
             _CH_SYNOPSIS.lstrip('\n') + '\n\n')

_DESCRIPTION = """
  The defacl command has three sub-commands:
""" + '\n'.join([_SET_DESCRIPTION + _GET_DESCRIPTION + _CH_DESCRIPTION])

_detailed_help_text = CreateHelpText(_SYNOPSIS, _DESCRIPTION)

_get_help_text = CreateHelpText(_GET_SYNOPSIS, _GET_DESCRIPTION)
_set_help_text = CreateHelpText(_SET_SYNOPSIS, _SET_DESCRIPTION)
_ch_help_text = CreateHelpText(_CH_SYNOPSIS, _CH_DESCRIPTION)


class DefAclCommand(Command):
  """Implementation of gsutil defacl command."""

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'defacl',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : ['setdefacl', 'getdefacl', 'chdefacl'],
    # Min number of args required by this command.
    MIN_ARGS : 1,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : NO_MAX,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : 'fg:u:d',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : False,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 1,
  }
  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'defacl',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['default acl', 'setdefacl', 'getdefacl', 'chdefacl'],
    # Type of help:
    HELP_TYPE : HelpType.COMMAND_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Get, set, or change default ACL on buckets',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
    # Help text for sub-commands.
    SUBCOMMAND_HELP_TEXT : {'get' : _get_help_text,
                            'set' : _set_help_text,
                            'ch' : _ch_help_text},
  }

  def _CalculateUrisStartArg(self):
    if (self.args[0].lower() == 'set'):
      return 2
    elif self.command_alias_used == 'getacl':
      return 0
    else:
      return 1

  def _SetDefAcl(self):
    if not self.suri_builder.StorageUri(self.args[-1]).names_bucket():
      raise CommandException('URI must name a bucket for the %s command' %
                             self.command_name)
    try:
      self.SetAclCommandHelper()
    except GSResponseError as e:
      if e.code == 'AccessDenied' and e.reason == 'Forbidden' \
          and e.status == 403:
        self._WarnServiceAccounts()
      raise

  def _GetDefAcl(self):
    if not self.suri_builder.StorageUri(self.args[-1]).names_bucket():
      raise CommandException('URI must name a bucket for the %s command' %
                             self.command_name)
    try:
      self.GetAclCommandHelper()
    except GSResponseError as e:
      if e.code == 'AccessDenied' and e.reason == 'Forbidden' \
          and e.status == 403:
        self._WarnServiceAccounts()
      raise

  def _ChDefAcl(self):
    self.parse_versions = True
    self.changes = []

    if self.sub_opts:
      for o, a in self.sub_opts:
        if o == '-g':
          self.changes.append(
              aclhelpers.AclChange(a, scope_type=aclhelpers.ChangeType.GROUP,
                                   logger=self.logger))
        if o == '-u':
          self.changes.append(
              aclhelpers.AclChange(a, scope_type=aclhelpers.ChangeType.USER,
                                   logger=self.logger))
        if o == '-d':
          self.changes.append(
              aclhelpers.AclDel(a, logger=self.logger))

    if not self.changes:
      raise CommandException(
          'Please specify at least one access change '
          'with the -g, -u, or -d flags')

    storage_uri = self.UrisAreForSingleProvider(self.args)
    if not (storage_uri and storage_uri.get_provider().name == 'google'):
      raise CommandException(
          'The "{0}" command can only be used with gs:// URIs'.format(
              self.command_name))

    bucket_uris = set()
    for uri_arg in self.args:
      for result in self.WildcardIterator(uri_arg):
        uri = result.uri
        if not uri.names_bucket():
          raise CommandException(
              'The chdefacl command can only be applied to buckets.')
        bucket_uris.add(uri)

    for uri in bucket_uris:
      self.ApplyAclChanges(uri)

  @Retry(GSResponseError, tries=3, timeout_secs=1)
  def ApplyAclChanges(self, uri):
    """Applies the changes in self.changes to the provided URI."""
    try:
      current_acl = uri.get_def_acl()
    except GSResponseError as e:
      if (e.code == 'AccessDenied' and e.reason == 'Forbidden'
          and e.status == 403):
        self._WarnServiceAccounts()
      self.logger.warning('Failed to set default acl for {0}: {1}'
                          .format(uri, e.reason))
      return

    modification_count = 0
    for change in self.changes:
      modification_count += change.Execute(uri, current_acl)
    if modification_count == 0:
      self.logger.info('No changes to {0}'.format(uri))
      return

    # TODO: Add if-metageneration-match when boto provides access to bucket
    # metageneration.

    # If this fails because of a precondition, it will raise a
    # GSResponseError for @Retry to handle.
    try:
      uri.set_def_acl(current_acl, validate=False)
    except GSResponseError as e:
      # Don't retry on bad requests, e.g. invalid email address.
      if getattr(e, 'status', None) == 400:
        raise CommandException('Received bad request from server: %s' % str(e))
      raise
    self.logger.info('Updated default ACL on {0}'.format(uri))

  # Command entry point.
  def RunCommand(self):
    action_subcommand = self.args.pop(0)
    (self.sub_opts, self.args) = getopt.getopt(self.args,
          self.command_spec[SUPPORTED_SUB_ARGS])
    self.CheckArguments()
    if action_subcommand == 'get':
      func = self._GetDefAcl
    elif action_subcommand == 'set':
      func = self._SetDefAcl
    elif action_subcommand in ('ch', 'change'):
      func = self._ChDefAcl
    else:
      raise CommandException(('Invalid subcommand "%s" for the %s command.\n'
                              'See "gsutil help defacl".') %
                             (action_subcommand, self.command_name))
    func()
    return 0
