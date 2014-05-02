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
"""Contains helper objects for changing and deleting ACLs."""

import re

from gslib.exception import CommandException
from gslib.storage_url import StorageUrlFromString


class ChangeType(object):
  USER = 'User'
  GROUP = 'Group'


class AclChange(object):
  """Represents a logical change to an access control list."""
  public_scopes = ['AllAuthenticatedUsers', 'AllUsers']
  id_scopes = ['UserById', 'GroupById']
  email_scopes = ['UserByEmail', 'GroupByEmail']
  domain_scopes = ['GroupByDomain']
  scope_types = public_scopes + id_scopes + email_scopes + domain_scopes

  public_entity_types = ('allUsers', 'allAuthenticatedUsers')
  project_entity_prefixes = ('project-editors-', 'project-owners-',
                             'project-viewers-')
  group_entity_prefix = 'group-'
  user_entity_prefix = 'user-'
  domain_entity_prefix = 'domain-'

  permission_shorthand_mapping = {
      'R': 'READER',
      'W': 'WRITER',
      'FC': 'OWNER',
      'O': 'OWNER',
      'READ': 'READER',
      'WRITE': 'WRITER',
      'FULL_CONTROL': 'OWNER'
      }

  def __init__(self, acl_change_descriptor, scope_type):
    """Creates an AclChange object.

    Args:
      acl_change_descriptor: An acl change as described in the "ch" section of
                             the "acl" command's help.
      scope_type: Either ChangeType.USER or ChangeType.GROUP, specifying the
                  extent of the scope.
    """
    self.identifier = ''

    self.raw_descriptor = acl_change_descriptor
    self._Parse(acl_change_descriptor, scope_type)
    self._Validate()

  def __str__(self):
    return 'AclChange<{0}|{1}|{2}>'.format(
        self.scope_type, self.perm, self.identifier)

  def _Parse(self, change_descriptor, scope_type):
    """Parses an ACL Change descriptor."""

    def _ClassifyScopeIdentifier(text):
      re_map = {
          'AllAuthenticatedUsers': r'^(AllAuthenticatedUsers|AllAuth)$',
          'AllUsers': '^(AllUsers|All)$',
          'Email': r'^.+@.+\..+$',
          'Id': r'^[0-9A-Fa-f]{64}$',
          'Domain': r'^[^@]+\.[^@]+$',
          }
      for type_string, regex in re_map.items():
        if re.match(regex, text, re.IGNORECASE):
          return type_string

    if change_descriptor.count(':') != 1:
      raise CommandException('{0} is an invalid change description.'
                             .format(change_descriptor))

    scope_string, perm_token = change_descriptor.split(':')

    perm_token = perm_token.upper()
    if perm_token in self.permission_shorthand_mapping:
      self.perm = self.permission_shorthand_mapping[perm_token]
    else:
      self.perm = perm_token

    scope_class = _ClassifyScopeIdentifier(scope_string)
    if scope_class == 'Domain':
      # This may produce an invalid UserByDomain scope,
      # which is good because then validate can complain.
      self.scope_type = '{0}ByDomain'.format(scope_type)
      self.identifier = scope_string
    elif scope_class in ('Email', 'Id'):
      self.scope_type = '{0}By{1}'.format(scope_type, scope_class)
      self.identifier = scope_string
    elif scope_class == 'AllAuthenticatedUsers':
      self.scope_type = 'AllAuthenticatedUsers'
    elif scope_class == 'AllUsers':
      self.scope_type = 'AllUsers'
    else:
      # This is just a fallback, so we set it to something
      # and the validate step has something to go on.
      self.scope_type = scope_string

  def _Validate(self):
    """Validates a parsed AclChange object."""

    def _ThrowError(msg):
      raise CommandException('{0} is not a valid ACL change\n{1}'
                             .format(self.raw_descriptor, msg))

    if self.scope_type not in self.scope_types:
      _ThrowError('{0} is not a valid scope type'.format(self.scope_type))

    if self.scope_type in self.public_scopes and self.identifier:
      _ThrowError('{0} requires no arguments'.format(self.scope_type))

    if self.scope_type in self.id_scopes and not self.identifier:
      _ThrowError('{0} requires an id'.format(self.scope_type))

    if self.scope_type in self.email_scopes and not self.identifier:
      _ThrowError('{0} requires an email address'.format(self.scope_type))

    if self.scope_type in self.domain_scopes and not self.identifier:
      _ThrowError('{0} requires domain'.format(self.scope_type))

    if self.perm not in self.permission_shorthand_mapping.values():
      perms = ', '.join(self.permission_shorthand_mapping.values())
      _ThrowError('Allowed permissions are {0}'.format(perms))

  def _YieldMatchingEntries(self, current_acl):
    """Generator that yields entries that match the change descriptor.

    Args:
      current_acl: A list of apitools_messages.BucketAccessControls or
                   ObjectAccessControls which will be searched for matching
                   entries.

    Yields:
      An apitools_messages.BucketAccessControl or ObjectAccessControl.
    """
    for entry in current_acl:
      if (self.scope_type in ('UserById', 'GroupById') and
          entry.entityId and self.identifier == entry.entityId):
        yield entry
      elif (self.scope_type in ('UserByEmail', 'GroupByEmail')
            and entry.email and self.identifier == entry.email):
        yield entry
      elif (self.scope_type == 'GroupByDomain' and
            entry.domain and self.identifier == entry.domain):
        yield entry
      elif (self.scope_type in ('AllUsers', 'AllAuthenticatedUsers') and
            entry.entity in self.public_entity_types):
        yield entry

  def _AddEntry(self, current_acl, entry_class):
    """Adds an entry to current_acl."""
    if self.scope_type == 'UserById':
      entry = entry_class(entityId=self.identifier, role=self.perm,
                          entity=self.user_entity_prefix + self.identifier)
    elif self.scope_type == 'GroupById':
      entry = entry_class(entityId=self.identifier, role=self.perm,
                          entity=self.group_entity_prefix + self.identifier)
    elif self.scope_type == 'UserByEmail':
      entry = entry_class(email=self.identifier, role=self.perm,
                          entity=self.user_entity_prefix + self.identifier)
    elif self.scope_type == 'GroupByEmail':
      entry = entry_class(email=self.identifier, role=self.perm,
                          entity=self.group_entity_prefix + self.identifier)
    elif self.scope_type == 'GroupByDomain':
      entry = entry_class(domain=self.identifier, role=self.perm,
                          entity=self.domain_entity_prefix + self.identifier)
    elif self.scope_type in ('AllUsers', 'AllAuthenticatedUsers'):
      entry = entry_class(entity=self.scope_type, role=self.perm)
    else:
      raise CommandException('Add entry to ACL got unexpected scope type %s.' %
                             self.scope_type)
    current_acl.append(entry)

  def _GetEntriesClass(self, current_acl):
    # Entries will share the same class, so just return the first one.
    for acl_entry in current_acl:
      return acl_entry.__class__

  def Execute(self, url_string, current_acl, logger):
    """Executes the described change on an ACL.

    Args:
      url_string: URL string representing the object to change.
      current_acl: An instance of boto.gs.acl.ACL to permute.
      logger: An instance of logging.Logger.

    Returns:
      The number of changes that were made.
    """
    logger.debug('Executing {0} on {1}'.format(self.raw_descriptor, url_string))

    if self.perm == 'WRITER' and StorageUrlFromString(url_string).IsObject():
      logger.warning(
          'Skipping {0} on {1}, as WRITER does not apply to objects'
          .format(self.raw_descriptor, url_string))
      return 0

    entry_class = self._GetEntriesClass(current_acl)
    matching_entries = list(self._YieldMatchingEntries(current_acl))
    change_count = 0
    if matching_entries:
      for entry in matching_entries:
        if entry.permission != self.perm:
          entry.permission = self.perm
          change_count += 1
    else:
      self._AddEntry(current_acl, entry_class)
      change_count = 1

    logger.debug('New Acl:\n{0}'.format(str(current_acl)))
    return change_count


class AclDel(object):
  """Represents a logical change from an access control list."""
  scope_regexes = {
      r'All(Users)?$': 'AllUsers',
      r'AllAuth(enticatedUsers)?$': 'AllAuthenticatedUsers',
  }

  def __init__(self, identifier):
    self.raw_descriptor = '-d {0}'.format(identifier)
    self.identifier = identifier
    for regex, scope in self.scope_regexes.items():
      if re.match(regex, self.identifier, re.IGNORECASE):
        self.identifier = scope
    self.scope_type = 'Any'
    self.perm = 'NONE'

  def _YieldMatchingEntries(self, current_acl):
    """Generator that yields entries that match the change descriptor.

    Args:
      current_acl: An instance of apitools_messages.BucketAccessControls or
                   ObjectAccessControls which will be searched for matching
                   entries.

    Yields:
      An apitools_messages.BucketAccessControl or ObjectAccessControl.
    """
    for entry in current_acl:
      if entry.entityId and self.identifier == entry.entityId:
        yield entry
      elif entry.email and self.identifier == entry.email:
        yield entry
      elif entry.domain and self.identifier == entry.domain:
        yield entry
      elif entry.entity.lower() == 'allusers' and self.identifier == 'AllUsers':
        yield entry
      elif (entry.entity.lower() == 'allauthenticatedusers' and
            self.identifier == 'AllAuthenticatedUsers'):
        yield entry

  def Execute(self, uri, current_acl, logger):
    logger.debug('Executing {0} on {1}'.format(self.raw_descriptor, uri))
    matching_entries = list(self._YieldMatchingEntries(current_acl))
    for entry in matching_entries:
      current_acl.remove(entry)
    logger.debug('New Acl:\n{0}'.format(str(current_acl)))
    return len(matching_entries)
