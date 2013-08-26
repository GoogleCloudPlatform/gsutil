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

"""Helper routines to facilitate use of oauth2_client in gsutil."""

import boto
import sys
import time
import webbrowser

from gslib.cred_types import CredTypes
import oauth2_client
from oauth2client.client import OAuth2WebServerFlow
from oauth2client.file import Storage



GSUTIL_CLIENT_ID = '909320924072.apps.googleusercontent.com'
# Google OAuth2 clients always have a secret, even if the client is an installed
# application/utility such as gsutil.  Of course, in such cases the "secret" is
# actually publicly known; security depends entirely on the secrecy of refresh
# tokens, which effectively become bearer tokens.
GSUTIL_CLIENT_NOTSOSECRET = 'p3RlpR10xMFh9ZXBS/ZNLYUu'

GOOGLE_OAUTH2_PROVIDER_LABEL = 'Google'
GOOGLE_OAUTH2_PROVIDER_AUTHORIZATION_URI = (
    'https://accounts.google.com/o/oauth2/auth')
GOOGLE_OAUTH2_PROVIDER_TOKEN_URI = (
    'https://accounts.google.com/o/oauth2/token')
GOOGLE_OAUTH2_DEFAULT_FILE_PASSWORD = 'notasecret'

OOB_REDIRECT_URI = 'urn:ietf:wg:oauth:2.0:oob'

def OAuth2ClientFromBotoConfig(config, 
    cred_type=CredTypes.OAUTH2_USER_ACCOUNT):
  token_cache = None
  token_cache_type = config.get('OAuth2', 'token_cache', 'file_system')
  if token_cache_type == 'file_system':
    if config.has_option('OAuth2', 'token_cache_path_pattern'):
      token_cache = oauth2_client.FileSystemTokenCache(
          path_pattern=config.get('OAuth2', 'token_cache_path_pattern'))
    else:
      token_cache = oauth2_client.FileSystemTokenCache()
  elif token_cache_type == 'in_memory':
    token_cache = oauth2_client.InMemoryTokenCache()
  else:
    raise Exception(
        "Invalid value for config option OAuth2/token_cache: %s" %
        token_cache_type)

  proxy_host = None
  proxy_port = None
  if (config.has_option('Boto', 'proxy')
      and config.has_option('Boto', 'proxy_port')):
    proxy_host = config.get('Boto', 'proxy')
    proxy_port = int(config.get('Boto', 'proxy_port'))
  
  provider_label = config.get(  
      'OAuth2', 'provider_label', GOOGLE_OAUTH2_PROVIDER_LABEL)  
  provider_authorization_uri = config.get(  
      'OAuth2', 'provider_authorization_uri',  
      GOOGLE_OAUTH2_PROVIDER_AUTHORIZATION_URI)
  provider_token_uri = config.get(
      'OAuth2', 'provider_token_uri', GOOGLE_OAUTH2_PROVIDER_TOKEN_URI)

  if cred_type == CredTypes.OAUTH2_SERVICE_ACCOUNT:
    service_client_id = config.get('Credentials', 'gs_service_client_id', '')
    private_key_filename = config.get('Credentials', 'gs_service_key_file', '')
    key_file_pass = config.get('Credentials', 'gs_service_key_file_password',
                               GOOGLE_OAUTH2_DEFAULT_FILE_PASSWORD)
    with open(private_key_filename, 'rb') as private_key_file:
      private_key = private_key_file.read()
    
    return oauth2_client.OAuth2ServiceAccountClient(service_client_id, 
        private_key, key_file_pass, access_token_cache=token_cache,
        auth_uri=provider_authorization_uri, token_uri=provider_token_uri,
        disable_ssl_certificate_validation=not(config.getbool(
            'Boto', 'https_validate_certificates', True)),
        proxy_host=proxy_host, proxy_port=proxy_port)

  elif cred_type == CredTypes.OAUTH2_USER_ACCOUNT:
    client_id = config.get('OAuth2', 'client_id', GSUTIL_CLIENT_ID)
    client_secret = config.get(
        'OAuth2', 'client_secret', GSUTIL_CLIENT_NOTSOSECRET)
    return oauth2_client.OAuth2UserAccountClient(
            provider_token_uri, client_id, client_secret,
            config.get('Credentials', 'gs_oauth2_refresh_token'),
            auth_uri=provider_authorization_uri,
            access_token_cache=token_cache,
            disable_ssl_certificate_validation=not(config.getbool(
                'Boto', 'https_validate_certificates', True)),
            proxy_host=proxy_host, proxy_port=proxy_port,
            ca_certs_file=config.get_value('Boto', 'ca_certificates_file'))
  else:
    raise Exception('You have attempted to create an OAuth2 client without '
        'setting up OAuth2 credentials. Please run "gsutil config" to set up '
        'your credentials correctly or see "gsutil help config" for more '
        'information.')


def OAuth2ApprovalFlow(oauth2_client, scopes, launch_browser=False):
  flow = OAuth2WebServerFlow(
      oauth2_client.client_id, oauth2_client.client_secret, scopes,
      auth_uri=oauth2_client.auth_uri, token_uri=oauth2_client.token_uri,
      redirect_uri=OOB_REDIRECT_URI)
  approval_url = flow.step1_get_authorize_url()

  if launch_browser:
    sys.stdout.write(
        'Attempting to launch a browser with the OAuth2 approval dialog at '
        'URL: %s\n\n'
        '[Note: due to a Python bug, you may see a spurious error message '
        '"object is not\ncallable [...] in [...] Popen.__del__" which can be '
        'ignored.]\n\n' % approval_url)
  else:
    sys.stdout.write(
        'Please navigate your browser to the following URL:\n%s\n' %
        approval_url)

  sys.stdout.write(
      'In your browser you should see a page that requests you to authorize '
      'gsutil to access\nGoogle Cloud Storage on your behalf. After you '
      'approve, an authorization code will be displayed.\n\n')
  if (launch_browser and
      not webbrowser.open(approval_url, new=1, autoraise=True)):
    sys.stdout.write(
        'Launching browser appears to have failed; please navigate a browser '
        'to the following URL:\n%s\n' % approval_url)
  # Short delay; webbrowser.open on linux insists on printing out a message
  # which we don't want to run into the prompt for the auth code.
  time.sleep(2)
  code = raw_input('Enter the authorization code: ')
  credentials = flow.step2_exchange(code,
                                    http=oauth2_client.CreateHttpRequest())
  return credentials.refresh_token
