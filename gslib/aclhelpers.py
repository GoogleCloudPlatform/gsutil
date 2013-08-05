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
from xml.dom import minidom

from boto.gs import acl

from gslib.exception import CommandException


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

  permission_shorthand_mapping = {
      'R': 'READ',
      'W': 'WRITE',
      'FC': 'FULL_CONTROL',
      }

  def __init__(self, acl_change_descriptor, scope_type, logger):
    """Creates an AclChange object.

    Args:
      acl_change_descriptor: An acl change as described in the "ch" section of
                             the "acl" command's help.
      scope_type: Either ChangeType.USER or ChangeType.GROUP, specifying the
                  extent of the scope.
      logger: An instance of logging.Logger.
    """
    self.logger = logger
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
    elif scope_class in ['Email', 'Id']:
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
      current_acl: An instance of bogo.gs.acl.ACL which will be searched
                   for matching entries.

    Yields:
      An instance of boto.gs.acl.Entry.
    """
    for entry in current_acl.entries.entry_list:
      if entry.scope.type == self.scope_type:
        if self.scope_type in ['UserById', 'GroupById']:
          if self.identifier == entry.scope.id:
            yield entry
        elif self.scope_type in ['UserByEmail', 'GroupByEmail']:
          if self.identifier == entry.scope.email_address:
            yield entry
        elif self.scope_type == 'GroupByDomain':
          if self.identifier == entry.scope.domain:
            yield entry
        elif self.scope_type in ['AllUsers', 'AllAuthenticatedUsers']:
          yield entry
        else:
          raise CommandException('Found an unrecognized ACL '
                                 'entry type, aborting.')

  def _AddEntry(self, current_acl):
    """Adds an entry to an ACL."""
    if self.scope_type in ['UserById', 'UserById', 'GroupById']:
      entry = acl.Entry(type=self.scope_type, permission=self.perm,
                        id=self.identifier)
    elif self.scope_type in ['UserByEmail', 'GroupByEmail']:
      entry = acl.Entry(type=self.scope_type, permission=self.perm,
                        email_address=self.identifier)
    elif self.scope_type == 'GroupByDomain':
      entry = acl.Entry(type=self.scope_type, permission=self.perm,
                        domain=self.identifier)
    else:
      entry = acl.Entry(type=self.scope_type, permission=self.perm)

    current_acl.entries.entry_list.append(entry)

  def Execute(self, uri, current_acl):
    """Executes the described change on an ACL.

    Args:
      uri: The URI object to change.
      current_acl: An instance of boto.gs.acl.ACL to permute.

    Returns:
      The number of changes that were made.
    """
    self.logger.debug('Executing {0} on {1}'.format(self.raw_descriptor, uri))

    if self.perm == 'WRITE' and uri.names_object():
      self.logger.warning(
          'Skipping {0} on {1}, as WRITE does not apply to objects'
          .format(self.raw_descriptor, uri))
      return 0

    matching_entries = list(self._YieldMatchingEntries(current_acl))
    change_count = 0
    if matching_entries:
      for entry in matching_entries:
        if entry.permission != self.perm:
          entry.permission = self.perm
          change_count += 1
    else:
      self._AddEntry(current_acl)
      change_count = 1

    parsed_acl = minidom.parseString(current_acl.to_xml())
    self.logger.debug('New Acl:\n{0}'.format(parsed_acl.toprettyxml()))
    return change_count


class AclDel(AclChange):
  """Represents a logical change from an access control list."""
  scope_regexes = {
      r'All(Users)?$': 'AllUsers',
      r'AllAuth(enticatedUsers)?$': 'AllAuthenticatedUsers',
  }

  def __init__(self, identifier, logger):
    self.raw_descriptor = '-d {0}'.format(identifier)
    self.logger = logger
    self.identifier = identifier
    for regex, scope in self.scope_regexes.items():
      if re.match(regex, self.identifier, re.IGNORECASE):
        self.identifier = scope
    self.scope_type = 'Any'
    self.perm = 'NONE'

  def _YieldMatchingEntries(self, current_acl):
    for entry in current_acl.entries.entry_list:
      if self.identifier == entry.scope.id:
        yield entry
      elif self.identifier == entry.scope.email_address:
        yield entry
      elif self.identifier == entry.scope.domain:
        yield entry
      elif self.identifier == 'AllUsers' and entry.scope.type == 'AllUsers':
        yield entry
      elif (self.identifier == 'AllAuthenticatedUsers'
            and entry.scope.type == 'AllAuthenticatedUsers'):
        yield entry

  def Execute(self, uri, current_acl):
    self.logger.debug('Executing {0} on {1}'.format(self.raw_descriptor, uri))
    matching_entries = list(self._YieldMatchingEntries(current_acl))
    for entry in matching_entries:
      current_acl.entries.entry_list.remove(entry)
    parsed_acl = minidom.parseString(current_acl.to_xml())
    self.logger.debug('New Acl:\n{0}'.format(parsed_acl.toprettyxml()))
    return len(matching_entries)
