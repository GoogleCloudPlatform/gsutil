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
"""This module provides the command to gsutil."""

from __future__ import absolute_import
from __future__ import print_function

import getopt
import textwrap

from gslib import metrics
from gslib.command import Command
from gslib.command_argument import CommandArgument
from gslib.cs_api_map import ApiSelector
from gslib.exception import CommandException
from gslib.exception import NO_URLS_MATCHED_TARGET
from gslib.help_provider import CreateHelpText
from gslib.third_party.storage_apitools import storage_v1_messages as apitools_messages
from gslib.utils.constants import NO_MAX
from gslib.utils.text_util import InsistOnOrOff

_SET_SYNOPSIS = """
  gsutil rpo set (on|off) gs://<bucket_name>...
"""

_GET_SYNOPSIS = """
  gsutil rpo get bucket_url...
"""

_SYNOPSIS = _SET_SYNOPSIS + _GET_SYNOPSIS.lstrip('\n')

_SET_DESCRIPTION = """
<B>SET</B>
  The ``rpo set`` command enables or disables uniform
  bucket-level access for Google Cloud Storage buckets.

<B>SET EXAMPLES</B>
  Configure your buckets to use rpo:

    gsutil rpo set ASYNC_PREMIUM gs://redbucket gs://bluebucket

  Configure your buckets to NOT use rapid replication:

    gsutil rpo set DEFAULT gs://redbucket gs://bluebucket
"""

_GET_DESCRIPTION = """
TODO
<B>GET</B>
  The ``ubla get`` command shows whether uniform bucket-level access is enabled
  for the specified Cloud Storage bucket(s).

<B>GET EXAMPLES</B>
  Check if your buckets are using uniform bucket-level access:

    gsutil ubla get gs://redbucket gs://bluebucket
"""

_DESCRIPTION = """
  TODO
  The ``ubla`` command is used to retrieve or configure the
  `uniform bucket-level access
  <https://cloud.google.com/storage/docs/bucket-policy-only>`_ setting of
  Cloud Storage bucket(s). This command has two sub-commands, ``get`` and
  ``set``.
""" + _GET_DESCRIPTION + _SET_DESCRIPTION

_DETAILED_HELP_TEXT = CreateHelpText(_SYNOPSIS, _DESCRIPTION)
_set_help_text = CreateHelpText(_SET_SYNOPSIS, _SET_DESCRIPTION)
_get_help_text = CreateHelpText(_GET_SYNOPSIS, _GET_DESCRIPTION)

# Aliases to make these more likely to fit on one line.
IamConfigurationValue = apitools_messages.Bucket.IamConfigurationValue
uniformBucketLevelAccessValue = IamConfigurationValue.BucketPolicyOnlyValue


class RpoCommand(Command):
  """Implements the gsutil rpo command."""

  command_spec = Command.CreateCommandSpec(
      'rpo',
      command_name_aliases=[],
      usage_synopsis=_SYNOPSIS,
      min_args=2,
      max_args=NO_MAX,
      supported_sub_args='',
      file_url_ok=False,
      provider_url_ok=False,
      urls_start_arg=2,
      gs_api_support=[ApiSelector.JSON],
      gs_default_api=ApiSelector.JSON,
      argparse_arguments={
          'get': [CommandArgument.MakeNCloudURLsArgument(1),],
          'set': [
              CommandArgument('mode', choices=['DEFAULT', 'ASYNC_PREMIUM']),
              CommandArgument.MakeZeroOrMoreCloudBucketURLsArgument()
          ],
      })
  # Help specification. See help_provider.py for documentation.
  help_spec = Command.HelpSpec(
      help_name='rpo',
      help_name_aliases=[],
      help_type='command_help',
      help_one_line_summary='Configure RPO',
      help_text=_DETAILED_HELP_TEXT,
      subcommand_help_text={
          'get': _get_help_text,
          'set': _set_help_text,
      },
  )

  def _ValidateBucketListingRefAndReturnBucketName(self, blr):
    if blr.storage_url.scheme != 'gs':
      raise CommandException(
          'The %s command can only be used with gs:// bucket URLs.' %
          self.command_name)

  def _GetRpo(self, url_args):
    """Gets the Uniform bucket-level access setting for a bucket."""
    some_matched = False
    for url_str in url_args:
      bucket_iter = self.GetBucketUrlIterFromArg(url_str,
                                                 bucket_fields=['rpo',
                                                                'versioning'])
      for blr in bucket_iter:
        print('{}: {}'.format(blr.url_string.rstrip('/'),
                              blr.root_object.rpo))
        some_matched = True

    if not some_matched:
      raise CommandException(NO_URLS_MATCHED_TARGET % list(url_args))

  def _SetUbla(self, blr, setting_arg):
    """Sets the Uniform bucket-level access setting for a bucket on or off."""
    self._ValidateBucketListingRefAndReturnBucketName(blr)
    bucket_url = blr.storage_url

    iam_config = IamConfigurationValue()
    # TODO(mynameisrafe): Replace bucketPolicyOnly with uniformBucketLevelAccess
    # when the property is live.
    iam_config.bucketPolicyOnly = uniformBucketLevelAccessValue()
    iam_config.bucketPolicyOnly.enabled = (setting_arg == 'on')

    bucket_metadata = apitools_messages.Bucket(iamConfiguration=iam_config)

    setting_verb = 'Enabling' if setting_arg == 'on' else 'Disabling'
    print('%s Uniform bucket-level access for %s...' %
          (setting_verb, str(bucket_url).rstrip('/')))

    self.gsutil_api.PatchBucket(bucket_url.bucket_name,
                                bucket_metadata,
                                fields=['iamConfiguration'],
                                provider=bucket_url.scheme)
    return 0

  def _Rpo(self):
    """Handles ubla command on a Cloud Storage bucket."""
    subcommand = self.args.pop(0)

    if subcommand not in ('get', 'set'):
      raise CommandException('rpo only supports get|set')

    subcommand_func = None
    subcommand_args = []
    setting_arg = None

    if subcommand == 'get':
      subcommand_func = self._GetRpo
    elif subcommand == 'set':
      subcommand_func = self._SetRpo
      setting_arg = self.args.pop(0)
      InsistOnOrOff(setting_arg,
                    'Only on and off values allowed for set option')
      subcommand_args.append(setting_arg)

    url_args = self.args
    if not url_args:
      self.RaiseWrongNumberOfArgumentsException()
    subcommand_func(url_args)
    return 0

  def RunCommand(self):
    """Command entry point for the ubla command."""
    if self.gsutil_api.GetApiSelector(provider='gs') != ApiSelector.JSON:
      raise CommandException('\n'.join(
          textwrap.wrap(
              'The "%s" command can only be used with the Cloud Storage JSON API.'
              % self.command_name)))

    action_subcommand = self.args[0]
    self.ParseSubOpts(check_args=True)

    if action_subcommand == 'get' or action_subcommand == 'set':
      metrics.LogCommandParams(sub_opts=self.sub_opts)
      metrics.LogCommandParams(subcommands=[action_subcommand])
      self._Rpo()
    else:
      raise CommandException('Invalid subcommand "%s", use get|set instead.' %
                             action_subcommand)
