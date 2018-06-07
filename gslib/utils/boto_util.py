# -*- coding: utf-8 -*-
# Copyright 2018 Google Inc. All Rights Reserved.
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
"""Shared utility structures and methods that require importing boto.

This module also imports httplib2 (as it is Boto's http transport and closely
tied to some of Boto's core functionality) and oauth2client.
"""

from __future__ import absolute_import
from __future__ import print_function

import pkgutil
import os
import tempfile
import textwrap
import sys

import boto
from boto import config
import boto.auth
from boto.exception import NoAuthHandlerFound
from boto.gs.connection import GSConnection
from boto.provider import Provider
from boto.pyami.config import BotoConfigLocations

import gslib
from gslib.exception import CommandException
from gslib.utils.constants import DEFAULT_GCS_JSON_API_VERSION
from gslib.utils.constants import DEFAULT_GSUTIL_STATE_DIR
from gslib.utils.constants import SSL_TIMEOUT_SEC
from gslib.utils.system_util import CreateDirIfNeeded
from gslib.utils.unit_util import HumanReadableToBytes
from gslib.utils.unit_util import ONE_MIB

import httplib2
from oauth2client.client import HAS_CRYPTO

# Globals in this module are set according to values in the boto config.
BOTO_IS_SECURE = config.get('Boto', 'is_secure', True)
CERTIFICATE_VALIDATION_ENABLED = config.get(
    'Boto', 'https_validate_certificates', True)

configured_certs_file = None  # Single certs file for use across all processes.
temp_certs_file = None  # Temporary certs file for cleanup upon exit.


def ConfigureCertsFile():
  """Configures and returns the CA Certificates file.

  If one is already configured, use it. Otherwise, use the cert roots
  distributed with gsutil.

  Returns:
    string filename of the certs file to use.
  """
  certs_file = boto.config.get('Boto', 'ca_certificates_file', None)
  # The 'system' keyword indicates to use the system installed certs. Some
  # Linux distributions patch the stack such that the Python SSL
  # infrastructure picks up the system installed certs by default, thus no
  #  action necessary on our part
  if certs_file == 'system':
    return None
  if not certs_file:
    global configured_certs_file, temp_certs_file
    if not configured_certs_file:
      configured_certs_file = os.path.abspath(
          os.path.join(gslib.GSLIB_DIR, 'data', 'cacerts.txt'))
      if not os.path.exists(configured_certs_file):
        # If the file is not present on disk, this means the gslib module
        # doesn't actually exist on disk anywhere. This can happen if it's
        # being imported from a zip file. Unfortunately, we have to copy the
        # certs file to a local temp file on disk because the underlying SSL
        # socket requires it to be a filesystem path.
        certs_data = pkgutil.get_data('gslib', 'data/cacerts.txt')
        if not certs_data:
          raise CommandException('Certificates file not found. Please '
                                 'reinstall gsutil from scratch')
        fd, fname = tempfile.mkstemp(suffix='.txt', prefix='gsutil-cacerts')
        f = os.fdopen(fd, 'w')
        f.write(certs_data)
        f.close()
        temp_certs_file = fname
        configured_certs_file = temp_certs_file
    certs_file = configured_certs_file
  return certs_file


def ConfigureNoOpAuthIfNeeded():
  """Sets up no-op auth handler if no boto credentials are configured."""
  if not HasConfiguredCredentials():
    if (config.has_option('Credentials', 'gs_service_client_id')
        and not HAS_CRYPTO):
      if os.environ.get('CLOUDSDK_WRAPPER') == '1':
        raise CommandException('\n'.join(textwrap.wrap(
            'Your gsutil is configured with an OAuth2 service account, but '
            'you do not have PyOpenSSL or PyCrypto 2.6 or later installed. '
            'Service account authentication requires one of these libraries; '
            'please reactivate your service account via the gcloud auth '
            'command and ensure any gcloud packages necessary for '
            'service accounts are present.')))
      else:
        raise CommandException('\n'.join(textwrap.wrap(
            'Your gsutil is configured with an OAuth2 service account, but '
            'you do not have PyOpenSSL or PyCrypto 2.6 or later installed. '
            'Service account authentication requires one of these libraries; '
            'please install either of them to proceed, or configure a '
            'different type of credentials with "gsutil config".')))
    else:
      # With no boto config file the user can still access publicly readable
      # buckets and objects.
      from gslib import no_op_auth_plugin  # pylint: disable=unused-variable


def GetBotoConfigFileList():
  """Returns list of boto config files that exist."""
  config_paths = BotoConfigLocations
  if 'AWS_CREDENTIAL_FILE' in os.environ:
    config_paths.append(os.environ['AWS_CREDENTIAL_FILE'])
  return [cfg_path for cfg_path in config_paths if os.path.exists(cfg_path)]


def GetCertsFile():
  return configured_certs_file


def GetCleanupFiles():
  """Returns a list of temp files to delete (if possible) when program exits."""
  return [temp_certs_file] if temp_certs_file else []


def GetConfigFilePaths():
  """Returns a list of the path(s) to the boto config file(s) to be loaded."""
  config_paths = []
  # The only case in which we load multiple boto configurations is
  # when the BOTO_CONFIG environment variable is not set and the
  # BOTO_PATH environment variable is set with multiple path values.
  # Otherwise, we stop when we find the first readable config file.
  # This predicate was taken from the boto.pyami.config module.
  should_look_for_multiple_configs = (
      'BOTO_CONFIG' not in os.environ and
      'BOTO_PATH' in os.environ)
  for path in BotoConfigLocations:
    try:
      with open(path, 'r'):
        config_paths.append(path)
        if not should_look_for_multiple_configs:
          break
    except IOError:
      pass
  return config_paths


def GetGsutilStateDir():
  """Returns the location of the directory for gsutil state files.

  Certain operations, such as cross-process credential sharing and
  resumable transfer tracking, need a known location for state files which
  are created by gsutil as-needed.

  This location should only be used for storing data that is required to be in
  a static location.

  Returns:
    Path to directory for gsutil static state files.
  """
  config_file_dir = config.get('GSUtil', 'state_dir', DEFAULT_GSUTIL_STATE_DIR)
  CreateDirIfNeeded(config_file_dir)
  return config_file_dir


def GetCredentialStoreFilename():
  # As of gsutil 4.29, this changed from 'credstore' to 'credstore2' because
  # of a change to the underlying credential storage format.
  return os.path.join(GetGsutilStateDir(), 'credstore2')


def GetGceCredentialCacheFilename():
  return os.path.join(GetGsutilStateDir(), 'gcecredcache')


def GetGcsJsonApiVersion():
  return config.get('GSUtil', 'json_api_version', DEFAULT_GCS_JSON_API_VERSION)


# Resumable downloads and uploads make one HTTP call per chunk (and must be
# in multiples of 256KiB). Overridable for testing.
def GetJsonResumableChunkSize():
  chunk_size = config.getint('GSUtil', 'json_resumable_chunk_size',
                             1024*1024*100L)
  if chunk_size == 0:
    chunk_size = 1024*256L
  elif chunk_size % 1024*256L != 0:
    chunk_size += (1024*256L - (chunk_size % (1024*256L)))
  return chunk_size


def GetLastCheckedForGsutilUpdateTimestampFile():
  return os.path.join(GetGsutilStateDir(), '.last_software_update_check')


def GetMaxConcurrentCompressedUploads():
  """Gets the max concurrent transport compressed uploads allowed in parallel.

  Returns:
    The max number of concurrent transport compressed uploads allowed in
    parallel without exceeding the max_upload_compression_buffer_size.
  """
  upload_chunk_size = GetJsonResumableChunkSize()
  # From apitools compression.py.
  compression_chunk_size = 16 * ONE_MIB
  total_upload_size = (
      upload_chunk_size + compression_chunk_size + 17 +
      5 * (((compression_chunk_size - 1) / 16383) + 1))
  max_concurrent_uploads = (
      GetMaxUploadCompressionBufferSize() / total_upload_size)
  if max_concurrent_uploads <= 0:
    max_concurrent_uploads = 1
  return max_concurrent_uploads


def GetMaxRetryDelay():
  return config.getint('Boto', 'max_retry_delay', 32)


def GetMaxUploadCompressionBufferSize():
  """Get the max amount of memory compressed transport uploads may buffer."""
  return HumanReadableToBytes(
      config.get('GSUtil', 'max_upload_compression_buffer_size', '2GiB'))


def GetNewHttp(http_class=httplib2.Http, **kwargs):
  """Creates and returns a new httplib2.Http instance.

  Args:
    http_class: Optional custom Http class to use.
    **kwargs: Arguments to pass to http_class constructor.

  Returns:
    An initialized httplib2.Http instance.
  """
  proxy_host = config.get('Boto', 'proxy', None)
  proxy_info = httplib2.ProxyInfo(
      proxy_type=3,
      proxy_host=proxy_host,
      proxy_port=config.getint('Boto', 'proxy_port', 0),
      proxy_user=config.get('Boto', 'proxy_user', None),
      proxy_pass=config.get('Boto', 'proxy_pass', None),
      proxy_rdns=config.get('Boto',
                            'proxy_rdns',
                            True if proxy_host else False))

  if not (proxy_info.proxy_host and proxy_info.proxy_port):
    # Fall back to using the environment variable.
    for proxy_env_var in ['http_proxy', 'https_proxy', 'HTTPS_PROXY']:
      if proxy_env_var in os.environ and os.environ[proxy_env_var]:
        proxy_info = ProxyInfoFromEnvironmentVar(proxy_env_var)
        # Assume proxy_rnds is True if a proxy environment variable exists.
        proxy_info.proxy_rdns = config.get('Boto', 'proxy_rdns', True)
        break

  # Some installers don't package a certs file with httplib2, so use the
  # one included with gsutil.
  kwargs['ca_certs'] = GetCertsFile()
  # Use a non-infinite SSL timeout to avoid hangs during network flakiness.
  kwargs['timeout'] = SSL_TIMEOUT_SEC
  http = http_class(proxy_info=proxy_info, **kwargs)
  http.disable_ssl_certificate_validation = (not config.getbool(
      'Boto', 'https_validate_certificates'))
  return http


# Retry for 10 minutes with exponential backoff, which corresponds to
# the maximum Downtime Period specified in the GCS SLA
# (https://cloud.google.com/storage/sla)
def GetNumRetries():
  return config.getint('Boto', 'num_retries', 23)


def GetTabCompletionLogFilename():
  return os.path.join(GetGsutilStateDir(), 'tab-completion-logs')


def GetTabCompletionCacheFilename():
  tab_completion_dir = os.path.join(GetGsutilStateDir(), 'tab-completion')
  # Limit read permissions on the directory to owner for privacy.
  CreateDirIfNeeded(tab_completion_dir, mode=0700)
  return os.path.join(tab_completion_dir, 'cache')


def HasConfiguredCredentials():
  """Determines if boto credential/config file exists."""
  has_goog_creds = (config.has_option('Credentials', 'gs_access_key_id') and
                    config.has_option('Credentials', 'gs_secret_access_key'))
  has_amzn_creds = (config.has_option('Credentials', 'aws_access_key_id') and
                    config.has_option('Credentials', 'aws_secret_access_key'))
  has_oauth_creds = (
      config.has_option('Credentials', 'gs_oauth2_refresh_token'))
  has_service_account_creds = (
      HAS_CRYPTO and
      config.has_option('Credentials', 'gs_service_client_id') and
      config.has_option('Credentials', 'gs_service_key_file'))

  if (has_goog_creds or has_amzn_creds or has_oauth_creds or
      has_service_account_creds):
    return True

  valid_auth_handler = None
  try:
    valid_auth_handler = boto.auth.get_auth_handler(
        GSConnection.DefaultHost, config, Provider('google'),
        requested_capability=['s3'])
    # Exclude the no-op auth handler as indicating credentials are configured.
    # Note we can't use isinstance() here because the no-op module may not be
    # imported so we can't get a reference to the class type.
    if getattr(getattr(valid_auth_handler, '__class__', None),
               '__name__', None) == 'NoOpAuth':
      valid_auth_handler = None
  except NoAuthHandlerFound:
    pass

  return valid_auth_handler


def JsonResumableChunkSizeDefined():
  chunk_size_defined = config.get('GSUtil', 'json_resumable_chunk_size',
                                  None)
  return chunk_size_defined is not None


def ProxyInfoFromEnvironmentVar(proxy_env_var):
  """Reads proxy info from the environment and converts to httplib2.ProxyInfo.

  Args:
    proxy_env_var: Environment variable string to read, such as http_proxy or
       https_proxy.

  Returns:
    httplib2.ProxyInfo constructed from the environment string.
  """
  proxy_url = os.environ.get(proxy_env_var)
  if not proxy_url or not proxy_env_var.lower().startswith('http'):
    return httplib2.ProxyInfo(httplib2.socks.PROXY_TYPE_HTTP, None, 0)
  proxy_protocol = proxy_env_var.lower().split('_')[0]
  if not proxy_url.lower().startswith('http'):
    # proxy_info_from_url requires a protocol, which is always http or https.
    proxy_url = proxy_protocol + '://' + proxy_url
  return httplib2.proxy_info_from_url(proxy_url, method=proxy_protocol)


def ResumableThreshold():
  return config.getint('GSUtil', 'resumable_threshold', 8 * ONE_MIB)


def UsingCrcmodExtension(crcmod):
  return (boto.config.get('GSUtil', 'test_assume_fast_crcmod', None) or
          (getattr(crcmod, 'crcmod', None) and
           getattr(crcmod.crcmod, '_usingExtension', None)))
