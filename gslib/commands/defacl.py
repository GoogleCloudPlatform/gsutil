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
"""Implementation of default object acl command for Google Cloud Storage."""

import getopt

from gslib import aclhelpers
from gslib.cloud_api import AccessDeniedException
from gslib.cloud_api import BadRequestException
from gslib.cloud_api import Preconditions
from gslib.cloud_api import ServiceException
from gslib.command import Command
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.command import CommandSpecKey
from gslib.command import FILE_URLS_OK
from gslib.command import MAX_ARGS
from gslib.command import MIN_ARGS
from gslib.command import PROVIDER_URLS_OK
from gslib.command import SetAclExceptionHandler
from gslib.command import SetAclFuncWrapper
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
from gslib.translation_helper import AclTranslation
from gslib.util import NO_MAX
from gslib.util import Retry
from gslib.util import UrlsAreForSingleProvider

_SET_SYNOPSIS = """
  gsutil defacl set file-or-canned_acl_name url...
"""

_GET_SYNOPSIS = """
  gsutil defacl get url
"""

_CH_SYNOPSIS = """
  gsutil defacl ch -u|-g|-d <grant>... url...
"""

_SET_DESCRIPTION = """
<B>SET</B>
  The "defacl set" command sets default object ACLs for the specified buckets.
  If you specify a default object ACL for a certain bucket, Google Cloud
  Storage applies the default object ACL to all new objects uploaded to that
  bucket.

  Similar to the "acl set" command, the file-or-canned_acl_name names either a
  canned ACL or the path to a file that contains ACL text. (See "gsutil
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
  Gets the default ACL text for a bucket, which you can save and edit
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
  example-bucket with READ access:

    gsutil defacl ch -u john.doe@example.com:READ gs://example-bucket

  Add the group admins@example.com to the default object ACL on bucket
  example-bucket with OWNER access:

    gsutil defacl ch -g admins@example.com:O gs://example-bucket
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
      COMMAND_NAME: 'defacl',
      # List of command name aliases.
      COMMAND_NAME_ALIASES: ['setdefacl', 'getdefacl', 'chdefacl'],
      # Min number of args required by this command.
      MIN_ARGS: 2,
      # Max number of args required by this command, or NO_MAX.
      MAX_ARGS: NO_MAX,
      # Getopt-style string specifying acceptable sub args.
      SUPPORTED_SUB_ARGS: 'fg:u:d:',
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
      HELP_NAME: 'defacl',
      # List of help name aliases.
      HELP_NAME_ALIASES: ['default acl', 'setdefacl', 'getdefacl', 'chdefacl'],
      # Type of help:
      HELP_TYPE: HelpType.COMMAND_HELP,
      # One line summary of this help.
      HELP_ONE_LINE_SUMMARY: 'Get, set, or change default ACL on buckets',
      # The full help text.
      HELP_TEXT: _detailed_help_text,
      # Help text for sub-commands.
      SUBCOMMAND_HELP_TEXT: {'get': _get_help_text,
                             'set': _set_help_text,
                             'ch': _ch_help_text},
  }

  def _CalculateUrlsStartArg(self):
    if not self.args:
      self._RaiseWrongNumberOfArgumentsException()
    if self.args[0].lower() == 'set':
      return 2
    elif self.command_alias_used == 'getdefacl':
      return 0
    else:
      return 1

  def _SetDefAcl(self):
    if not StorageUrlFromString(self.args[-1]).IsBucket():
      raise CommandException('URL must name a bucket for the %s command' %
                             self.command_name)
    try:
      self.SetAclCommandHelper(SetAclFuncWrapper, SetAclExceptionHandler)
    except AccessDeniedException:
      self._WarnServiceAccounts()
      raise

  def _GetDefAcl(self):
    if not StorageUrlFromString(self.args[0]).IsBucket():
      raise CommandException('URL must name a bucket for the %s command' %
                             self.command_name)
    self.GetAndPrintAcl(self.args[0])

  def _ChDefAcl(self):
    """Parses options and changes default object ACLs on specified buckets."""
    self.parse_versions = True
    self.changes = []

    if self.sub_opts:
      for o, a in self.sub_opts:
        if o == '-g':
          self.changes.append(
              aclhelpers.AclChange(a, scope_type=aclhelpers.ChangeType.GROUP))
        if o == '-u':
          self.changes.append(
              aclhelpers.AclChange(a, scope_type=aclhelpers.ChangeType.USER))
        if o == '-d':
          self.changes.append(aclhelpers.AclDel(a))

    if not self.changes:
      raise CommandException(
          'Please specify at least one access change '
          'with the -g, -u, or -d flags')

    if (not UrlsAreForSingleProvider(self.args) or
        StorageUrlFromString(self.args[0]).scheme != 'gs'):
      raise CommandException(
          'The "{0}" command can only be used with gs:// URLs'.format(
              self.command_name))

    bucket_urls = set()
    for url_arg in self.args:
      for result in self.WildcardIterator(url_arg):
        url = StorageUrlFromString(result.url_string)
        if not url.IsBucket():
          raise CommandException(
              'The defacl ch command can only be applied to buckets.')
        bucket_urls.add(url.GetUrlString())

    for url_string in bucket_urls:
      self.ApplyAclChanges(url_string)

  @Retry(ServiceException, tries=3, timeout_secs=1)
  def ApplyAclChanges(self, url_string):
    """Applies the changes in self.changes to the provided URL."""
    url = StorageUrlFromString(url_string)
    bucket = self.gsutil_api.GetBucket(
        url.bucket_name, provider=url.scheme,
        fields=['defaultObjectAcl', 'metageneration'])
    current_acl = bucket.defaultObjectAcl
    current_xml_acl = AclTranslation.BotoAclFromMessage(current_acl)
    if not current_acl:
      self._WarnServiceAccounts()
      self.logger.warning('Failed to set acl for %s. Please ensure you have '
                          'OWNER-role access to this resource.' % url_string)
      return

    modification_count = 0
    for change in self.changes:
      modification_count += change.Execute(url, current_xml_acl, self.logger)
    if modification_count == 0:
      self.logger.info('No changes to {0}'.format(url))
      return

    try:
      preconditions = Preconditions(meta_gen_match=bucket.metageneration)
      acl_to_set = list(AclTranslation.BotoObjectAclToMessage(current_xml_acl))
      bucket_metadata = apitools_messages.Bucket(defaultObjectAcl=acl_to_set)
      self.gsutil_api.PatchBucket(url.bucket_name, bucket_metadata,
                                  preconditions=preconditions,
                                  provider=url.scheme, fields=['id'])
    except BadRequestException as e:
      # Don't retry on bad requests, e.g. invalid email address.
      raise CommandException('Received bad request from server: %s' % str(e))

    self.logger.info('Updated default ACL on {0}'.format(url))

  def RunCommand(self):
    """Command entry point for the defacl command."""
    action_subcommand = self.args.pop(0)
    self.sub_opts, self.args = getopt.getopt(
        self.args, self.command_spec[SUPPORTED_SUB_ARGS])
    self.CheckArguments()
    self.def_acl = True
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
