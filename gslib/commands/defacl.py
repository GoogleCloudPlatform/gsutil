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

from __future__ import absolute_import

import getopt

from gslib import aclhelpers
from gslib.cloud_api import AccessDeniedException
from gslib.cloud_api import BadRequestException
from gslib.cloud_api import Preconditions
from gslib.cloud_api import ServiceException
from gslib.command import Command
from gslib.command import SetAclExceptionHandler
from gslib.command import SetAclFuncWrapper
from gslib.cs_api_map import ApiSelector
from gslib.exception import CommandException
from gslib.help_provider import CreateHelpText
from gslib.storage_url import StorageUrlFromString
from gslib.third_party.storage_apitools import storage_v1_messages as apitools_messages
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

_DETAILED_HELP_TEXT = CreateHelpText(_SYNOPSIS, _DESCRIPTION)

_get_help_text = CreateHelpText(_GET_SYNOPSIS, _GET_DESCRIPTION)
_set_help_text = CreateHelpText(_SET_SYNOPSIS, _SET_DESCRIPTION)
_ch_help_text = CreateHelpText(_CH_SYNOPSIS, _CH_DESCRIPTION)


class DefAclCommand(Command):
  """Implementation of gsutil defacl command."""

  # Command specification. See base class for documentation.
  command_spec = Command.CreateCommandSpec(
      'defacl',
      command_name_aliases=['setdefacl', 'getdefacl', 'chdefacl'],
      min_args=2,
      max_args=NO_MAX,
      supported_sub_args='fg:u:d:',
      file_url_ok=False,
      provider_url_ok=False,
      urls_start_arg=1,
      gs_api_support=[ApiSelector.XML, ApiSelector.JSON],
      gs_default_api=ApiSelector.JSON,
  )
  # Help specification. See help_provider.py for documentation.
  help_spec = Command.HelpSpec(
      help_name='defacl',
      help_name_aliases=[
          'default acl', 'setdefacl', 'getdefacl', 'chdefacl'],
      help_type='command_help',
      help_one_line_summary='Get, set, or change default ACL on buckets',
      help_text=_DETAILED_HELP_TEXT,
      subcommand_help_text={
          'get': _get_help_text, 'set': _set_help_text, 'ch': _ch_help_text},
  )

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
    if not current_acl:
      self._WarnServiceAccounts()
      self.logger.warning('Failed to set acl for %s. Please ensure you have '
                          'OWNER-role access to this resource.' % url_string)
      return

    modification_count = 0
    for change in self.changes:
      modification_count += change.Execute(
          url_string, current_acl, 'defacl', self.logger)
    if modification_count == 0:
      self.logger.info('No changes to {0}'.format(url_string))
      return

    try:
      preconditions = Preconditions(meta_gen_match=bucket.metageneration)
      bucket_metadata = apitools_messages.Bucket(defaultObjectAcl=current_acl)
      self.gsutil_api.PatchBucket(url.bucket_name, bucket_metadata,
                                  preconditions=preconditions,
                                  provider=url.scheme, fields=['id'])
    except BadRequestException as e:
      # Don't retry on bad requests, e.g. invalid email address.
      raise CommandException('Received bad request from server: %s' % str(e))

    self.logger.info('Updated default ACL on {0}'.format(url_string))

  def RunCommand(self):
    """Command entry point for the defacl command."""
    action_subcommand = self.args.pop(0)
    self.sub_opts, self.args = getopt.getopt(
        self.args, self.command_spec.supported_sub_args)
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
