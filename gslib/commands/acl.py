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
"""Implementation of acl command for cloud storage providers."""

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
  gsutil acl set [-f] [-R] [-a] file-or-canned_acl_name url...
"""

_GET_SYNOPSIS = """
  gsutil acl get url
"""

_CH_SYNOPSIS = """
  gsutil acl ch [-R] -u|-g|-d <grant>... url...

  where each <grant> is one of the following forms:

    -u <id|email>:<perm>
    -g <id|email|domain|All|AllAuth>:<perm>
    -d <id|email|domain|All|AllAuth>
"""

_GET_DESCRIPTION = """
<B>GET</B>
  The "acl get" command gets the ACL text for a bucket or object, which you can
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

  Note that multi-threading/multi-processing is only done when the named URLs
  refer to objects. gsutil -m acl set gs://bucket1 gs://bucket2 will run the
  acl set operations sequentially.


<B>SET OPTIONS</B>
  The "set" sub-command has the following options

    -R, -r      Performs "acl set" request recursively, to all objects under
                the specified URL.

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
  to add or delete, and for grant additions, one of R, W, O (for the
  permission to be granted). A more formal description is provided in a later
  section; below we provide examples.

<B>CH EXAMPLES</B>
  Examples for "ch" sub-command:

  Grant the user john.doe@example.com WRITE access to the bucket
  example-bucket:

    gsutil acl ch -u john.doe@example.com:WRITE gs://example-bucket

  Grant the group admins@example.com OWNER access to all jpg files in
  the top level of example-bucket:

    gsutil acl ch -g admins@example.com:O gs://example-bucket/*.jpg

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
  following command adds OWNER for admin@example.org using
  multi-threading:

    gsutil -m acl ch -R -u admin@example.org:O gs://example-bucket

  Grant READ access to everyone from my-domain.org and to all authenticated
  users, and grant OWNER to admin@mydomain.org, for the buckets
  my-bucket and my-other-bucket, with multi-threading enabled:

    gsutil -m acl ch -R -g my-domain.org:R -g AllAuth:R \\
      -u admin@mydomain.org:O gs://my-bucket/ gs://my-other-bucket

<B>CH ROLES</B>
  You may specify the following roles with either their shorthand or
  their full name:

    R: READ
    W: WRITE
    O: OWNER

<B>CH ENTITIES</B>
  There are four different entity types: Users, Groups, All Authenticated Users,
  and All Users.

  Users are added with -u and a plain ID or email address, as in
  "-u john-doe@gmail.com:r"

  Groups are like users, but specified with the -g flag, as in
  "-g power-users@example.com:fc". Groups may also be specified as a full
  domain, as in "-g my-company.com:r".

  AllAuthenticatedUsers and AllUsers are specified directly, as
  in "-g AllUsers:R" or "-g AllAuthenticatedUsers:O". These are case
  insensitive, and may be shortened to "all" and "allauth", respectively.

  Removing roles is specified with the -d flag and an ID, email
  address, domain, or one of AllUsers or AllAuthenticatedUsers.

  Many entities' roles can be specified on the same command line, allowing
  bundled changes to be executed in a single run. This will reduce the number of
  requests made to the server.

<B>CH OPTIONS</B>
  The "ch" sub-command has the following options

    -R, -r      Performs acl ch request recursively, to all objects under the
                specified URL.

    -u          Add or modify a user entity's role.

    -g          Add or modify a group entity's role.

    -d          Remove all roles associated with the matching entity.

    -f          Normally gsutil stops at the first error. The -f option causes
                it to continue when it encounters errors. With this option the
                gsutil exit status will be 0 even if some ACLs couldn't be
                changed.
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


def _ApplyAclChangesWrapper(cls, url_or_expansion_result, thread_state=None):
  cls.ApplyAclChanges(url_or_expansion_result, thread_state=thread_state)


class AclCommand(Command):
  """Implementation of gsutil acl command."""

  # Command specification. See base class for documentation.
  command_spec = Command.CreateCommandSpec(
      'acl',
      command_name_aliases=['getacl', 'setacl', 'chacl'],
      min_args=2,
      max_args=NO_MAX,
      supported_sub_args='afRrg:u:d:',
      file_url_ok=False,
      provider_url_ok=False,
      urls_start_arg=1,
      gs_api_support=[ApiSelector.XML, ApiSelector.JSON],
      gs_default_api=ApiSelector.JSON,
  )
  # Help specification. See help_provider.py for documentation.
  help_spec = Command.HelpSpec(
      help_name='acl',
      help_name_aliases=['getacl', 'setacl', 'chmod', 'chacl'],
      help_type='command_help',
      help_one_line_summary='Get, set, or change bucket and/or object ACLs',
      help_text=_detailed_help_text,
      subcommand_help_text={
          'get': _get_help_text, 'set': _set_help_text, 'ch': _ch_help_text},
  )

  def _CalculateUrlsStartArg(self):
    if not self.args:
      self._RaiseWrongNumberOfArgumentsException()
    if (self.args[0].lower() == 'set') or (self.command_alias_used == 'setacl'):
      return 1
    else:
      return 0

  def _SetAcl(self):
    """Parses options and sets ACLs on the specified buckets/objects."""
    self.continue_on_error = False
    if self.sub_opts:
      for o, unused_a in self.sub_opts:
        if o == '-a':
          self.all_versions = True
        elif o == '-f':
          self.continue_on_error = True
        elif o == '-r' or o == '-R':
          self.recursion_requested = True
    try:
      self.SetAclCommandHelper(SetAclFuncWrapper, SetAclExceptionHandler)
    except AccessDeniedException, unused_e:
      self._WarnServiceAccounts()
      raise
    if not self.everything_set_okay:
      raise CommandException('ACLs for some objects could not be set.')

  def _ChAcl(self):
    """Parses options and changes ACLs on the specified buckets/objects."""
    self.parse_versions = True
    self.changes = []
    self.continue_on_error = False

    if self.sub_opts:
      for o, a in self.sub_opts:
        if o == '-f':
          self.continue_on_error = True
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

    if (not UrlsAreForSingleProvider(self.args) or
        StorageUrlFromString(self.args[0]).scheme != 'gs'):
      raise CommandException(
          'The "{0}" command can only be used with gs:// URLs'.format(
              self.command_name))

    self.everything_set_okay = True
    self.ApplyAclFunc(_ApplyAclChangesWrapper, _ApplyExceptionHandler,
                      self.args)
    if not self.everything_set_okay:
      raise CommandException('ACLs for some objects could not be set.')

  @Retry(ServiceException, tries=3, timeout_secs=1)
  def ApplyAclChanges(self, name_expansion_result, thread_state=None):
    """Applies the changes in self.changes to the provided URL.

    Args:
      name_expansion_result: NameExpansionResult describing the target object.
      thread_state: If present, gsutil Cloud API instance to apply the changes.
    """
    if thread_state:
      gsutil_api = thread_state
    else:
      gsutil_api = self.gsutil_api

    url_string = name_expansion_result.GetExpandedUrlStr()
    url = StorageUrlFromString(url_string)

    if url.IsBucket():
      bucket = gsutil_api.GetBucket(url.bucket_name, provider=url.scheme,
                                    fields=['acl', 'metageneration'])
      current_acl = bucket.acl
    elif url.IsObject():
      gcs_object = gsutil_api.GetObjectMetadata(
          url.bucket_name, url.object_name, provider=url.scheme,
          generation=url.generation,
          fields=['acl', 'generation', 'metageneration'])
      current_acl = gcs_object.acl
    if not current_acl:
      self._WarnServiceAccounts()
      self.logger.warning('Failed to set acl for %s. Please ensure you have '
                          'OWNER-role access to this resource.' % url_string)
      return

    modification_count = 0
    for change in self.changes:
      modification_count += change.Execute(url_string, current_acl,
                                           self.logger)
    if modification_count == 0:
      self.logger.info('No changes to {0}'.format(url_string))
      return

    try:
      if url.IsBucket():
        preconditions = Preconditions(meta_gen_match=bucket.metageneration)
        bucket_metadata = apitools_messages.Bucket(acl=current_acl)
        gsutil_api.PatchBucket(url.bucket_name, bucket_metadata,
                               preconditions=preconditions,
                               provider=url.scheme, fields=['id'])
      else:  # Object
        preconditions = Preconditions(meta_gen_match=gcs_object.metageneration)
        # If we're operating on the live version of the object, only apply
        # if the live version hasn't changed or been overwritten.  If we're
        # referring to a version explicitly, then we don't care what the live
        # version is and we will change the ACL on the requested version.
        if not url.generation:
          preconditions.gen_match = gcs_object.generation

        object_metadata = apitools_messages.Object(acl=current_acl)
        gsutil_api.PatchObjectMetadata(
            url.bucket_name, url.object_name, object_metadata,
            preconditions=preconditions, provider=url.scheme,
            generation=url.generation)
    except BadRequestException as e:
      # Don't retry on bad requests, e.g. invalid email address.
      raise CommandException('Received bad request from server: %s' % str(e))

    self.logger.info('Updated ACL on {0}'.format(url_string))

  def RunCommand(self):
    """Command entry point for the acl command."""
    action_subcommand = self.args.pop(0)
    self.sub_opts, self.args = getopt.getopt(
        self.args, self.command_spec.supported_sub_args)
    self.CheckArguments()
    self.def_acl = False
    if action_subcommand == 'get':
      self.GetAndPrintAcl(self.args[0])
    elif action_subcommand == 'set':
      self._SetAcl()
    elif action_subcommand in ('ch', 'change'):
      self._ChAcl()
    else:
      raise CommandException(('Invalid subcommand "%s" for the %s command.\n'
                              'See "gsutil help acl".') %
                             (action_subcommand, self.command_name))

    return 0
