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
from gslib import name_expansion
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
from gslib.help_provider import HELP_TYPE
from gslib.help_provider import HelpType
from gslib.help_provider import SUBCOMMAND_HELP_TEXT
from gslib.util import NO_MAX
from gslib.util import Retry

_SET_SYNOPSIS = """
  gsutil acl set [-f] [-R] [-a] file-or-canned_acl_name uri...
"""

_GET_SYNOPSIS = """
  gsutil acl get uri
"""

_CH_SYNOPSIS = """
  gsutil acl ch [-R] -u|-g|-d <grant>... uri...

  where each <grant> is one of the following forms:

    -u <id|email>:<perm>
    -g <id|email|domain|All|AllAuth>:<perm>
    -d <id|email|domain|All|AllAuth>
"""

_GET_DESCRIPTION = """
<B>GET</B>
  The "acl get" command gets the ACL XML for a bucket or object, which you can
  save and edit for the acl set command.
"""

_SET_DESCRIPTION = """
<B>SET</B>
  The "acl set" command allows you to set an Access Control List on one or
  more buckets and objects. The simplest way to use it is to specify one of
  the canned ACLs, e.g.,:

    gsutil acl set private gs://bucket

  or:

    gsutil acl set public-read gs://bucket/object

  See "gsutil help acls" for a list of all canned ACLs.

  NOTE: By default, publicly readable objects are served with a Cache-Control
  header allowing such objects to be cached for 3600 seconds. If you need to
  ensure that updates become visible immediately, you should set a
  Cache-Control header of "Cache-Control:private, max-age=0, no-transform" on
  such objects. For help doing this, see 'gsutil help setmeta'.

  If you want to define more fine-grained control over your data, you can
  retrieve an ACL using the "acl get" command, save the output to a file, edit
  the file, and then use the "acl set" command to set that ACL on the buckets
  and/or objects. For example:

    gsutil acl get gs://bucket/file.txt > acl.txt

  Make changes to acl.txt such as adding an additional grant, then:

    gsutil acl set acl.txt gs://cats/file.txt

  Note that you can set an ACL on multiple buckets or objects at once,
  for example:

    gsutil acl set acl.txt gs://bucket/*.jpg

  If you have a large number of ACLs to update you might want to use the
  gsutil -m option, to perform a parallel (multi-threaded/multi-processing)
  update:

    gsutil -m acl set acl.txt gs://bucket/*.jpg

  Note that multi-threading/multi-processing is only done when the named URIs
  refer to objects. gsutil -m acl set gs://bucket1 gs://bucket2 will run the
  acl set operations sequentially.


<B>SET OPTIONS</B>
  The "set" sub-command has the following options

    -R, -r      Performs "acl set" request recursively, to all objects under
                the specified URI.

    -a          Performs "acl set" request on all object versions.

    -f          Normally gsutil stops at the first error. The -f option causes
                it to continue when it encounters errors. With this option the
                gsutil exit status will be 0 even if some ACLs couldn't be
                set.
"""

_CH_DESCRIPTION = """
<B>CH</B>
  The "acl ch" (or "acl change") command updates access control lists, similar
  in spirit to the Linux chmod command. You can specify multiple access grant
  additions and deletions in a single command run; all changes will be made
  atomically to each object in turn. For example, if the command requests
  deleting one grant and adding a different grant, the ACLs being updated will
  never be left in an intermediate state where one grant has been deleted but
  the second grant not yet added. Each change specifies a user or group grant
  to add or delete, and for grant additions, one of R, W, FC (for the
  permission to be granted). A more formal description is provided in a later
  section; below we provide examples.

<B>CH EXAMPLES</B>
  Examples for "ch" sub-command:

  Grant the user john.doe@example.com WRITE access to the bucket
  example-bucket:

    gsutil acl ch -u john.doe@example.com:WRITE gs://example-bucket

  Grant the group admins@example.com FULL_CONTROL access to all jpg files in
  the top level of example-bucket:

    gsutil acl ch -g admins@example.com:FC gs://example-bucket/*.jpg

  Grant the user with the specified canonical ID READ access to all objects
  in example-bucket that begin with folder/:

    gsutil acl ch -R \\
      -u 84fac329bceSAMPLE777d5d22b8SAMPLE785ac2SAMPLE2dfcf7c4adf34da46:R \\
      gs://example-bucket/folder/

  Grant all users from my-domain.org READ access to the bucket
  gcs.my-domain.org:

    gsutil acl ch -g my-domain.org:R gs://gcs.my-domain.org

  Remove any current access by john.doe@example.com from the bucket
  example-bucket:

    gsutil acl ch -d john.doe@example.com gs://example-bucket

  If you have a large number of objects to update, enabling multi-threading
  with the gsutil -m flag can significantly improve performance. The
  following command adds FULL_CONTROL for admin@example.org using
  multi-threading:

    gsutil -m acl ch -R -u admin@example.org:FC gs://example-bucket

  Grant READ access to everyone from my-domain.org and to all authenticated
  users, and grant FULL_CONTROL to admin@mydomain.org, for the buckets
  my-bucket and my-other-bucket, with multi-threading enabled:

    gsutil -m acl ch -R -g my-domain.org:R -g AllAuth:R \\
      -u admin@mydomain.org:FC gs://my-bucket/ gs://my-other-bucket

<B>CH PERMISSIONS</B>
  You may specify the following permissions with either their shorthand or
  their full name:

    R: READ
    W: WRITE
    FC: FULL_CONTROL

<B>CH SCOPES</B>
  There are four different scopes: Users, Groups, All Authenticated Users,
  and All Users.

  Users are added with -u and a plain ID or email address, as in
  "-u john-doe@gmail.com:r"

  Groups are like users, but specified with the -g flag, as in
  "-g power-users@example.com:fc". Groups may also be specified as a full
  domain, as in "-g my-company.com:r".

  AllAuthenticatedUsers and AllUsers are specified directly, as
  in "-g AllUsers:R" or "-g AllAuthenticatedUsers:FC". These are case
  insensitive, and may be shortened to "all" and "allauth", respectively.

  Removing permissions is specified with the -d flag and an ID, email
  address, domain, or one of AllUsers or AllAuthenticatedUsers.

  Many scopes can be specified on the same command line, allowing bundled
  changes to be executed in a single run. This will reduce the number of
  requests made to the server.

<B>CH OPTIONS</B>
  The "ch" sub-command has the following options

    -R, -r      Performs acl ch request recursively, to all objects under the
                specified URI.

    -u          Add or modify a user permission as specified in the SCOPES
                and PERMISSIONS sections.

    -g          Add or modify a group permission as specified in the SCOPES
                and PERMISSIONS sections.

    -d          Remove all permissions associated with the matching argument,
                as specified in the SCOPES and PERMISSIONS sections
"""

_SYNOPSIS = (_SET_SYNOPSIS + _GET_SYNOPSIS.lstrip('\n') +
             _CH_SYNOPSIS.lstrip('\n') + '\n\n')

_DESCRIPTION = ("""
  The acl command has three sub-commands:
""" + '\n'.join([_GET_DESCRIPTION, _SET_DESCRIPTION, _CH_DESCRIPTION]))

_detailed_help_text = CreateHelpText(_SYNOPSIS, _DESCRIPTION)

_get_help_text = CreateHelpText(_GET_SYNOPSIS, _GET_DESCRIPTION)
_set_help_text = CreateHelpText(_SET_SYNOPSIS, _SET_DESCRIPTION)
_ch_help_text = CreateHelpText(_CH_SYNOPSIS, _CH_DESCRIPTION)

def _ApplyExceptionHandler(cls, exception):
  cls.logger.error('Encountered a problem: {0}'.format(exception))
  cls.everything_set_okay = False

def _ApplyAclChangesWrapper(cls, uri_or_expansion_result):
  cls.ApplyAclChanges(uri_or_expansion_result)


class AclCommand(Command):
  """Implementation of gsutil acl command."""

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'acl',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : ['getacl', 'setacl', 'chacl'],
    # Min number of args required by this command.
    MIN_ARGS : 2,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : NO_MAX,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : 'afRrvg:u:d:',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : False,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 1,
  }
  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'acl',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['getacl', 'setacl', 'chmod', 'chacl'],
    # Type of help:
    HELP_TYPE : HelpType.COMMAND_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Get, set, or change bucket and/or object ACLs',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
    # Help text for sub-commands.
    SUBCOMMAND_HELP_TEXT : {'get' : _get_help_text,
                            'set' : _set_help_text,
                            'ch' : _ch_help_text},
  }

  def _CalculateUrisStartArg(self):
    if not self.args:
      self._RaiseWrongNumberOfArgumentsException()
    if (self.args[0].lower() == 'set') or (self.command_alias_used == 'setacl'):
      return 1
    else:
      return 0

  def _SetAcl(self):
    self.continue_on_error = False
    if self.sub_opts:
      for o, unused_a in self.sub_opts:
        if o == '-a':
          self.all_versions = True
        elif o == '-f':
          self.continue_on_error = True
        elif o == '-r' or o == '-R':
          self.recursion_requested = True
        elif o == '-v':
          self.logger.warning('WARNING: The %s -v option is no longer'
                              ' needed, and will eventually be '
                              'removed.\n' % self.command_name)
    try:
      self.SetAclCommandHelper()
    except GSResponseError as e:
      if e.code == 'AccessDenied' and e.reason == 'Forbidden' \
          and e.status == 403:
        self._WarnServiceAccounts()
      raise

  def _GetAcl(self):
    try:
      self.GetAclCommandHelper()
    except GSResponseError as e:
      if e.code == 'AccessDenied' and e.reason == 'Forbidden' \
          and e.status == 403:
        self._WarnServiceAccounts()
      raise
    
  def _ChAcl(self):
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
        if o == '-r' or o == '-R':
          self.recursion_requested = True

    if not self.changes:
      raise CommandException(
          'Please specify at least one access change '
          'with the -g, -u, or -d flags')

    storage_uri = self.UrisAreForSingleProvider(self.args)
    if not (storage_uri and storage_uri.get_provider().name == 'google'):
      raise CommandException(
          'The "{0}" command can only be used with gs:// URIs'.format(
              self.command_name))

    bulk_uris = set()
    for uri_arg in self.args:
      for result in self.WildcardIterator(uri_arg):
        uri = result.uri
        if uri.names_bucket():
          if self.recursion_requested:
            bulk_uris.add(uri.clone_replace_name('*').uri)
          else:
            # If applying to a bucket directly, the threading machinery will
            # break, so we have to apply now, in the main thread.
            self.ApplyAclChanges(uri)
        else:
          bulk_uris.add(uri_arg)

    try:
      name_expansion_iterator = name_expansion.NameExpansionIterator(
          self.command_name, self.proj_id_handler, self.headers, self.debug,
          self.logger, self.bucket_storage_uri_class, bulk_uris,
          self.recursion_requested)
    except CommandException as e:
      # NameExpansionIterator will complain if there are no URIs, but we don't
      # want to throw an error if we handled bucket URIs.
      if e.reason == 'No URIs matched':
        return 0
      else:
        raise e

    self.everything_set_okay = True
    self.Apply(_ApplyAclChangesWrapper,
               name_expansion_iterator,
               _ApplyExceptionHandler)
    if not self.everything_set_okay:
      raise CommandException('ACLs for some objects could not be set.')

  @Retry(GSResponseError, tries=3, timeout_secs=1)
  def ApplyAclChanges(self, uri_or_expansion_result):
    """Applies the changes in self.changes to the provided URI."""
    if isinstance(uri_or_expansion_result, name_expansion.NameExpansionResult):
      uri = self.suri_builder.StorageUri(
          uri_or_expansion_result.expanded_uri_str)
    else:
      uri = uri_or_expansion_result

    try:
      current_acl = uri.get_acl()
    except GSResponseError as e:
      if (e.code == 'AccessDenied' and e.reason == 'Forbidden'
          and e.status == 403):
        self._WarnServiceAccounts()
      self.logger.warning('Failed to set acl for {0}: {1}'
                          .format(uri, e.reason))
      return

    modification_count = 0
    for change in self.changes:
      modification_count += change.Execute(uri, current_acl, self.logger)
    if modification_count == 0:
      self.logger.info('No changes to {0}'.format(uri))
      return

    # TODO: Remove the concept of forcing when boto provides access to
    # bucket generation and metageneration.
    headers = dict(self.headers)
    force = uri.names_bucket()
    if not force:
      key = uri.get_key()
      headers['x-goog-if-generation-match'] = key.generation
      headers['x-goog-if-metageneration-match'] = key.metageneration

    # If this fails because of a precondition, it will raise a
    # GSResponseError for @Retry to handle.
    try:
      uri.set_acl(current_acl, uri.object_name, False, headers)
    except GSResponseError as e:
      # Don't retry on bad requests, e.g. invalid email address.
      if getattr(e, 'status', None) == 400:
        raise CommandException('Received bad request from server: %s' % str(e))
      raise
    self.logger.info('Updated ACL on {0}'.format(uri))

  # Command entry point.
  def RunCommand(self):
    action_subcommand = self.args.pop(0)
    (self.sub_opts, self.args) = getopt.getopt(self.args,
          self.command_spec[SUPPORTED_SUB_ARGS])
    self.CheckArguments()
    if action_subcommand == 'get':
      func = self._GetAcl
    elif action_subcommand == 'set':
      func = self._SetAcl
    elif action_subcommand in ('ch', 'change'):
      func = self._ChAcl
    else:
      raise CommandException(('Invalid subcommand "%s" for the %s command.\n'
                             'See "gsutil help acl".') %
                             (action_subcommand, self.command_name))

    func()
    return 0
