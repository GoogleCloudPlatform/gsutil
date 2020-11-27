# -*- coding: utf-8 -*-
# Copyright 2020 Google Inc. All Rights Reserved.
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
"""Manages device context mTLS certificates."""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

import atexit
import os
import subprocess

from boto import config

import gslib

# Maintain a single context configuration.
_singleton_config = None


class CertProvisionError(Exception):
  """Represents errors when provisioning a client certificate."""
  pass


class ContextConfigSingletonAlreadyExistsError(Exception):
  """Error for when create_context_config is called multiple times."""
  pass


def _IsPemSectionMarker(line):
  """Returns (begin:bool, end:bool, name:str)."""
  if line.startswith('-----BEGIN ') and line.endswith('-----'):
    return True, False, line[11:-5]
  elif line.startswith('-----END ') and line.endswith('-----'):
    return False, True, line[9:-5]
  else:
    return False, False, ''


def _SplitPemIntoSections(contents, logger):
  """Returns dict with {name: section} by parsing contents in PEM format.

  A simple parser for PEM file. Please see RFC 7468 for the format of PEM
  file. Not using regex to improve performance catching nested matches.
  Note: This parser requires the post-encapsulation label of a section to
  match its pre-encapsulation label. It ignores a section without a
  matching label.

  Args:
    contents (str): Contents of a PEM file.
    logger (logging.logger): gsutil logger.

  Returns:
    A dict of the PEM file sections.
  """
  result = {}
  pem_lines = []
  pem_section_name = None

  for line in contents.splitlines():
    line = line.strip()
    if not line:
      continue

    begin, end, name = _IsPemSectionMarker(line)
    if begin:
      if pem_section_name:
        logger.warning('Section %s missing end line and will be ignored.' %
                       pem_section_name)
      if name in result.keys():
        logger.warning('Section %s already exists, and the older section will '
                       'be ignored.' % name)
      pem_section_name = name
      pem_lines = []
    elif end:
      if not pem_section_name:
        logger.warning(
            'Section %s missing a beginning line and will be ignored.' % name)
      elif pem_section_name != name:
        logger.warning('Section %s missing a matching end line. Found: %s' %
                       (pem_section_name, name))
        pem_section_name = None

    if pem_section_name:
      pem_lines.append(line)
      if end:
        result[name] = '\n'.join(pem_lines) + '\n'
        pem_section_name = None

  if pem_section_name:
    logger.warning('Section %s missing an end line.' % pem_section_name)

  return result


class _ContextConfig(object):
  """Represents the configurations associated with context aware access.

  Only one instance of Config can be created for the program.
  """

  def __init__(self, logger):
    """Initializes config.

    Args:
      logger (logging.logger): gsutil logger.
    """
    self.logger = logger

    self.use_client_certificate = config.getbool('Credentials',
                                                 'use_client_certificate')
    self.client_cert_path = None
    self.client_cert_password = None

    if not self.use_client_certificate:
      # Don't spend time generating values gsutil won't need.
      return

    # Generates certificate and deletes it afterwards.
    atexit.register(self._UnprovisionClientCert)
    command_string = config.get('Credentials', 'cert_provider_command', None)
    if not command_string:
      raise CertProvisionError('No cert provider detected.')

    self.client_cert_path = os.path.join(gslib.GSUTIL_DIR, 'caa_cert.pem')
    try:
      # Certs provisioned using endpoint verification are stored as a
      # single file holding both the public certificate and the private key.
      self._ProvisionClientCert(command_string, self.client_cert_path)
    except CertProvisionError as e:
      self.logger.error('Failed to provision client certificate: %s' % e)

  def _ProvisionClientCert(self, command_string, cert_path):
    """Executes certificate provider to obtain client certificate and keys."""
    # Monkey-patch command line args to get password-protected certificate.
    # Adds password flag if it's not already there.
    password_arg = ' --with_passphrase'
    if ('--print_certificate' in command_string and
        password_arg not in command_string):
      command_string += password_arg

    try:
      command_process = subprocess.Popen(command_string.split(' '),
                                         stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE)
      command_stdout, command_stderr = command_process.communicate()
      if command_process.returncode != 0:
        raise CertProvisionError(command_stderr)

      # Python 3 outputs bytes from communicate() by default.
      command_stdout_string = command_stdout.decode()

      sections = _SplitPemIntoSections(command_stdout_string, self.logger)
      with open(cert_path, 'w+') as f:
        f.write(sections['CERTIFICATE'])
        f.write(sections['ENCRYPTED PRIVATE KEY'])
      self.client_cert_password = sections['PASSPHRASE'].splitlines()[1]
    except OSError as e:
      raise CertProvisionError(e)
    except KeyError as e:
      raise CertProvisionError(
          'Invalid output format from certificate provider, no %s' % e)

  def _UnprovisionClientCert(self):
    """Cleans up any files or resources provisioned during config init."""
    if self.client_cert_path is not None:
      try:
        os.remove(self.client_cert_path)
        self.logger.debug('Unprovisioned client cert: %s' %
                          self.client_cert_path)
      except OSError as e:
        self.logger.error('Failed to remove client certificate: %s' % e)


def create_context_config(logger):
  """Should be run once at gsutil startup. Creates global singleton.

  Args:
    logger (logging.logger): For logging during config functions.

  Returns:
    New ContextConfig singleton.

  Raises:
    Exception if singleton already exists.
  """
  global _singleton_config
  if not _singleton_config:
    _singleton_config = _ContextConfig(logger)
    return _singleton_config
  raise ContextConfigSingletonAlreadyExistsError


def get_context_config():
  """Retrieves ContextConfig global singleton.

  Returns:
    ContextConfig or None if global singleton doesn't exist.
  """
  global _singleton_config
  return _singleton_config
