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

from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HelpProvider
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HelpType
from gslib.help_provider import HELP_TYPE

_detailed_help_text = ("""
<B>OVERVIEW</B>
  gsutil currently supports four types of credentials/authentication, as well as
  the ability to access public data anonymously (see "gsutil help anon" for more
  on anonymous access).
  
  OAuth2 User Account:
    This is the preferred type of credentials for authenticating requests on 
    behalf of a specific user (which is probably the most common use of gsutil).
    This is the default type of credential that will be created when you run
    "gsutil config".
    For more details about OAuth2 authentication, see:
      https://developers.google.com/accounts/docs/OAuth2#scenarios
  
  HMAC:
    This type of credential can be used by programs that are implemented using 
    HMAC authentication, which is an authentication mechanism supported by 
    certain other cloud storage service providers. This type of credential can 
    also be used for interactive use when moving data to/from service providers
    that support HMAC credentials. This is the type of credential that will be 
    created when you run "gsutil config -a".

    Note that it's possible to set up HMAC credentials for both Google Cloud 
    Storage and another service provider; or to set up OAuth2 user account 
    credentials for Google Cloud Storage and HMAC credentials for another 
    service provider. To do so, after you run the gsutil config command, you 
    can edit the generated ~/.boto config file and look for comments for where 
    other credentials can be added.

    For more details about HMAC authentication, see:
      https://developers.google.com/storage/docs/reference/v1/getting-startedv1#keys
      
  OAuth2 Service Account: 
    This is the preferred type of credential to use when authenticating on 
    behalf of a service or application (as opposed to a user). For example, if 
    you will run gsutil out of a nightly cron job to upload/download data, 
    using a service account allows the cron job not to depend on credentials of 
    an individual employee at your company. This is the type of credential that
    will be created when you run "gsutil config -e".
    
    It is important to note that a service account is considered an Editor by 
    default for the purposes of API access, rather than an Owner. In particular,
    the fact that Editors have full_control access in the default object and 
    bucket ACLs, but the canned ACL options remove full_control access from 
    Editors, can lead to unexpected results. The solution to this problem 
    is to visit https://code.google.com/apis/console/, find the email address 
    for your service account under "API Access", and then add that email address
    as an Owner under the "Team" tab. For further information about account
    roles, see: https://developers.google.com/console/help/#DifferentRoles

    For more details about OAuth2 service accounts, see:
      https://developers.google.com/accounts/docs/OAuth2ServiceAccount
      
  GCE Internal Service Account:
    This is the type of service account used for accounts hosted by App Engine 
    or GCE. Such credentials are created automatically for you on GCE when you 
    run the gcutil addinstance command with the --service_account flag.
    
    For more details about GCE service accounts, see:
      https://developers.google.com/compute/docs/authentication;
      
    For more details about App Engine service accounts, see:
      https://developers.google.com/appengine/docs/python/appidentity/overview
      
  
""")



class CommandOptions(HelpProvider):
  """Additional help about types of credentials and authentication."""

  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'creds',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['credentials', 'authentication', 'auth'],
    # Type of help:
    HELP_TYPE : HelpType.ADDITIONAL_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Credential Types Supporting Various Use Cases',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }
