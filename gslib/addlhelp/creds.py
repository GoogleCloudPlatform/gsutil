# -*- coding: utf-8 -*-
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
"""Additional help about types of credentials and authentication."""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

from gslib.help_provider import HelpProvider

_DETAILED_HELP_TEXT = ("""
<B>OVERVIEW</B>
  gsutil currently supports several types of credentials/authentication, as
  well as the ability to `access public data anonymously
  <https://cloud.google.com/storage/docs/access-public-data>`_. Each of these
  type of credentials is discussed in more detail below, along with
  information about configuring and using credentials via the Cloud SDK.


<B>Configuring/Using Credentials via Cloud SDK Distribution of gsutil</B>
  When gsutil is installed/used via the Cloud SDK ("gcloud"), credentials are
  stored by Cloud SDK in a non-user-editable file located under
  ~/.config/gcloud (any manipulation of credentials should be done via the
  gcloud auth command). If you need to set up multiple credentials (e.g., one
  for an individual user account and a second for a service account), the
  gcloud auth command manages the credentials for you, and you switch between
  credentials using the gcloud auth command as well (for more details, see
  https://cloud.google.com/sdk/gcloud/reference/auth).

  Once credentials have been configured via gcloud auth, those credentials will
  be used regardless of whether the user has any boto configuration files (which
  are located at ~/.boto unless a different path is specified in the BOTO_CONFIG
  environment variable). However, gsutil will still look for credentials in the
  boto config file if a type of non-GCS credential is needed that's not stored
  in the gcloud credential store (e.g., an HMAC credential for an S3 account).


<B>SUPPORTED CREDENTIAL TYPES</B>
  gsutil supports several types of credentials (the specific subset depends on
  which distribution of gsutil you are using; see above discussion).

  OAuth2 User Account:
    This is the preferred type of credentials for authenticating requests on
    behalf of a specific user (which is probably the most common use of gsutil).
    This is the default type of credential that will be created when you run
    "gsutil config" (or "gcloud init" for Cloud SDK installs).
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
    service provider. To do so, after you run the "gsutil config" command (or
    "gcloud init" for Cloud SDK installs), you can edit the generated ~/.boto
    config file and look for comments for where other credentials can be added.

    For more details about HMAC authentication, see
    https://developers.google.com/storage/docs/reference/v1/getting-startedv1#keys

  OAuth2 Service Account:
    This is the preferred type of credential to use when authenticating on
    behalf of a service or application (as opposed to a user). For example, if
    you will run gsutil out of a nightly cron job to upload/download data,
    using a service account allows the cron job not to depend on credentials of
    an individual employee at your company. This is the type of credential that
    will be configured when you run "gsutil config -e". To configure service
    account credentials when installed via the Cloud SDK, run "gcloud auth
    activate-service-account".

    It is important to note that a service account is considered an Editor by
    default for the purposes of API access, rather than an Owner. In particular,
    the fact that Editors have OWNER access in the default object and
    bucket ACLs, but the canned ACL options remove OWNER access from
    Editors, can lead to unexpected results. The solution to this problem is to
    use "gsutil acl ch" instead of "gsutil acl set <canned-ACL>" to change
    permissions on a bucket.

    To set up a service account for use with "gsutil config -e" or "gcloud auth
    activate-service-account", see
    https://cloud.google.com/storage/docs/authentication#generating-a-private-key

    For more details about OAuth2 service accounts, see
    https://developers.google.com/accounts/docs/OAuth2ServiceAccount

    For further information about account roles, see
    https://developers.google.com/console/help/#DifferentRoles

  Google Compute Engine Internal Service Account:
    This is the type of service account used for accounts hosted by App Engine
    or Google Compute Engine. Such credentials are created automatically for
    you on Google Compute Engine when you run the gcloud compute instances
    creates command and the credentials can be controlled with the --scopes
    flag.

    For more details about Google Compute Engine service accounts, see
    https://developers.google.com/compute/docs/authentication;

    For more details about App Engine service accounts, see
    https://developers.google.com/appengine/docs/python/appidentity/overview

  Service Account Impersonation:
    Impersonating a service account is useful in scenarios where you need to
    grant short-term access to specific resources. For example, if you have a
    bucket of sensitive data that is typically read-only and want to
    temporarily grant write access through a trusted service account.

    You can specify which service account to use for impersonation by running
    "gsutil -i", "gsutil config" and editing the boto configuration file, or
    "gcloud config set auth/impersonate_service_account [service_account_email_address]".

    In order to impersonate, your original credentials need to be granted
    roles/iam.serviceAccountTokenCreator on the target service account.
    For more information see
    https://cloud.google.com/iam/docs/creating-short-lived-service-account-credentials

  External Account Credentials (Workload Identity Federation):
    Using workload identity federation, you can access Google Cloud resources
    from Amazon Web Services (AWS), Microsoft Azure or any identity provider
    that supports OpenID Connect (OIDC) or SAML 2.0.

    For more information see
    https://cloud.google.com/iam/docs/using-workload-identity-federation
""")


class CommandOptions(HelpProvider):
  """Additional help about types of credentials and authentication."""

  # Help specification. See help_provider.py for documentation.
  help_spec = HelpProvider.HelpSpec(
      help_name='creds',
      help_name_aliases=['credentials', 'authentication', 'auth', 'gcloud'],
      help_type='additional_help',
      help_one_line_summary='Credential Types Supporting Various Use Cases',
      help_text=_DETAILED_HELP_TEXT,
      subcommand_help_text={},
  )
