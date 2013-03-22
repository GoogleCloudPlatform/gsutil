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
"""This module provides the chdefacl command to gsutil."""

from boto.exception import GSResponseError
from gslib import aclhelpers
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
from gslib.exception import CommandException
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HELP_TYPE
from gslib.help_provider import HelpType
from gslib.util import NO_MAX
from gslib.util import Retry


_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil chdefacl -u|-g|-d <grant>... uri...


<B>DESCRIPTION</B>
  The chdefacl command updates the default object access control list for a
  bucket. The syntax is shared with the chacl command, so see
  "gsutil help chacl" for the full help description.


<B>EXAMPLES</B>

  Add the user john.doe@example.com to the default object ACL on bucket
  example-bucket with WRITE access:

    gsutil chdefacl -u john.doe@example.com:WRITE gs://example-bucket

  Add the group admins@example.com to the default object ACL on bucket
  example-bucket with FULL_CONTROL access:

    gsutil chdefacl -g admins@example.com:FC gs://example-bucket

""")


class ChDefAclCommand(Command):
  """Implementation of gsutil chdefacl command."""

  # Command specification (processed by parent class).
  command_spec = {
      # Name of command.
      COMMAND_NAME: 'chdefacl',
      # List of command name aliases.
      COMMAND_NAME_ALIASES: [],
      # Min number of args required by this command.
      MIN_ARGS: 1,
      # Max number of args required by this command, or NO_MAX.
      MAX_ARGS: NO_MAX,
      # Getopt-style string specifying acceptable sub args.
      SUPPORTED_SUB_ARGS: 'fg:u:d:',
      # True if file URIs acceptable for this command.
      FILE_URIS_OK: False,
      # True if provider-only URIs acceptable for this command.
      PROVIDER_URIS_OK: False,
      # Index in args of first URI arg.
      URIS_START_ARG: 1,
      # True if must configure gsutil before running command.
      CONFIG_REQUIRED: True,
  }
  help_spec = {
      # Name of command or auxiliary help info for which this help applies.
      HELP_NAME: 'chdefacl',
      # List of help name aliases.
      HELP_NAME_ALIASES: [],
      # Type of help:
      HELP_TYPE: HelpType.COMMAND_HELP,
      # One line summary of this help.
      HELP_ONE_LINE_SUMMARY: 'Add / remove entries on bucket default ACL',
      # The full help text.
      HELP_TEXT: _detailed_help_text,
  }

  def RunCommand(self):
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

    return 0

  @Retry(GSResponseError, tries=3, delay=1, backoff=2)
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
