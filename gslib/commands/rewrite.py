# -*- coding: utf-8 -*-
# Copyright 2015 Google Inc. All Rights Reserved.
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
"""Implementation of rewrite command (in-place cloud object transformation)."""

from __future__ import absolute_import

from apitools.base.py import encoding

from gslib.cloud_api import EncryptionException
from gslib.command import Command
from gslib.command_argument import CommandArgument
from gslib.cs_api_map import ApiSelector
from gslib.encryption_helper import CryptoTupleFromKey
from gslib.encryption_helper import FindMatchingCryptoKey
from gslib.encryption_helper import GetEncryptionTupleAndSha256Hash
from gslib.exception import CommandException
from gslib.name_expansion import NameExpansionIterator
from gslib.progress_callback import ConstructAnnounceText
from gslib.progress_callback import FileProgressCallbackHandler
from gslib.storage_url import StorageUrlFromString
from gslib.third_party.storage_apitools import storage_v1_messages as apitools_messages
from gslib.translation_helper import PreconditionsFromHeaders
from gslib.util import ConvertRecursiveToFlatWildcard
from gslib.util import GetCloudApiInstance
from gslib.util import NO_MAX
from gslib.util import StdinIterator

_SYNOPSIS = """
  gsutil rewrite -k [-f] [-r] url...
  gsutil rewrite -k [-f] [-r] -I
"""

_DETAILED_HELP_TEXT = ("""
<B>SYNOPSIS</B>
""" + _SYNOPSIS + """


<B>DESCRIPTION</B>
  The gsutil rewrite command performs in-place transformations on cloud objects.
  The transformation(s) are atomic and applied based on the input
  transformation flags. Currently, only the "-k" flag is supported to add,
  rotate, or remove encryption keys on objects.

  For example, the command:

    gsutil rewrite -k gs://bucket/**

  will update all objects in gs://bucket with the current encryption key
  from your boto config file.

  You can also use the -r option to specify recursive object transform; this is
  synonymous with the ** wildcard. Thus, either of the following two commands
  will perform encryption key transforms on gs://bucket/subdir and all objects
  and subdirectories under it:

    gsutil rewrite -k gs://bucket/subdir**
    gsutil rewrite -k -r gs://bucket/subdir

  The rewrite command acts only on live object versions, so specifying a
  URL with a generation will fail. If you want to rewrite an archived
  generation, first copy it to the live version, then rewrite it, for example:

    gsutil cp gs://bucket/object#123 gs://bucket/object
    gsutil rewrite -k gs://bucket/object

  The rewrite command will skip objects that are already in the desired state.
  For example, if you run:

    gsutil rewrite -k gs://bucket/**

  and gs://bucket contains objects that already match the encryption
  configuration, gsutil will skip rewriting those objects and only rewrite
  objects that do not match the encryption configuration.

  You can pass a list of URLs (one per line) to rewrite on stdin instead of as
  command line arguments by using the -I option. This allows you to use gsutil
  in a pipeline to rewrite objects identified by a program, such as:

    some_program | gsutil -m rewrite -k -I

  The contents of stdin can name cloud URLs and wildcards of cloud URLs.

  The rewrite command requires OWNER permissions on each object to preserve
  object ACLs. You can bypass this by using the -O flag, which will cause
  gsutil not to read the object's ACL and instead apply the default object ACL
  to the rewritten object:

    gsutil rewrite -k -O gs://bucket/**


<B>OPTIONS</B>
  -f          Continues silently (without printing error messages) despite
              errors when rewriting multiple objects. If some of the objects
              could not be rewritten, gsutil's exit status will be non-zero
              even if this flag is set. This option is implicitly set when
              running "gsutil -m rewrite ...".

  -I          Causes gsutil to read the list of objects to rewrite from stdin.
              This allows you to run a program that generates the list of
              objects to rewrite.

  -k          Rewrite the objects to the current encryption key specific in
              your boto configuration file. If encryption_key is specified,
              encrypt all objects with this key. If encryption_key is
              unspecified, decrypt all objects. See `gsutil help encryption`
              for details on encryption configuration.

  -O          Rewrite objects with the bucket's default object ACL instead of
              the existing object ACL. This is needed if you do not have
              OWNER permission on the object.

  -R, -r      The -R and -r options are synonymous. Causes bucket or bucket
              subdirectory contents to be rewritten recursively.
""")


def _RewriteExceptionHandler(cls, e):
  """Simple exception handler to allow post-completion status."""
  if not cls.continue_on_error:
    cls.logger.error(str(e))
  cls.op_failure_count += 1


def _RewriteFuncWrapper(cls, name_expansion_result, thread_state=None):
  cls.RewriteFunc(name_expansion_result, thread_state=thread_state)


def GenerationCheckGenerator(url_strs):
  """Generator function that ensures generation-less (live) arguments."""
  for url_str in url_strs:
    if StorageUrlFromString(url_str).generation is not None:
      raise CommandException(
          '"rewrite" called on URL with generation (%s).' % url_str)
    yield url_str


class _TransformTypes(object):
  """Enum class for valid transforms."""
  CRYPTO_KEY = 'crypto_key'


class RewriteCommand(Command):
  """Implementation of gsutil rewrite command."""

  # Command specification. See base class for documentation.
  command_spec = Command.CreateCommandSpec(
      'rewrite',
      command_name_aliases=[],
      usage_synopsis=_SYNOPSIS,
      min_args=0,
      max_args=NO_MAX,
      supported_sub_args='fkIrRO',
      file_url_ok=False,
      provider_url_ok=False,
      urls_start_arg=0,
      gs_api_support=[ApiSelector.JSON],
      gs_default_api=ApiSelector.JSON,
      argparse_arguments=[
          CommandArgument.MakeZeroOrMoreCloudURLsArgument()
      ]
  )
  # Help specification. See help_provider.py for documentation.
  help_spec = Command.HelpSpec(
      help_name='rewrite',
      help_name_aliases=['rekey', 'rotate'],
      help_type='command_help',
      help_one_line_summary='Rewrite objects',
      help_text=_DETAILED_HELP_TEXT,
      subcommand_help_text={},
  )

  def CheckProvider(self, url):
    if url.scheme != 'gs':
      raise CommandException(
          '"rewrite" called on URL with unsupported provider (%s).' % str(url))

  def RunCommand(self):
    """Command entry point for the rewrite command."""
    self.continue_on_error = self.parallel_operations
    self.read_args_from_stdin = False
    self.no_preserve_acl = False
    self.supported_transformation_flags = ['-k']
    self.transform_types = []

    self.op_failure_count = 0
    self.current_encryption_tuple, self.current_encryption_sha256 = (
        GetEncryptionTupleAndSha256Hash())

    if self.sub_opts:
      for o, unused_a in self.sub_opts:
        if o == '-f':
          self.continue_on_error = True
        elif o == '-k':
          self.transform_types.append(_TransformTypes.CRYPTO_KEY)
        elif o == '-I':
          self.read_args_from_stdin = True
        elif o == '-O':
          self.no_preserve_acl = True
        elif o == '-r' or o == '-R':
          self.recursion_requested = True
          self.all_versions = True

    if self.read_args_from_stdin:
      if self.args:
        raise CommandException('No arguments allowed with the -I flag.')
      url_strs = StdinIterator()
    else:
      if not self.args:
        raise CommandException('The rewrite command (without -I) expects at '
                               'least one URL.')
      url_strs = self.args

    url_strs = GenerationCheckGenerator(url_strs)

    if not self.transform_types:
      raise CommandException(
          'rewrite command requires at least one transformation flag. '
          'Currently supported transformation flags: %s' %
          self.supported_transformation_flags)

    self.preconditions = PreconditionsFromHeaders(self.headers or {})

    # Convert recursive flag to flat wildcard to avoid performing multiple
    # listings.
    if self.recursion_requested:
      url_strs = ConvertRecursiveToFlatWildcard(url_strs)

    # Expand the source argument(s).
    name_expansion_iterator = NameExpansionIterator(
        self.command_name, self.debug, self.logger, self.gsutil_api,
        url_strs, self.recursion_requested, project_id=self.project_id,
        continue_on_error=self.continue_on_error or self.parallel_operations)

    # Perform rewrite requests in parallel (-m) mode, if requested.
    self.Apply(_RewriteFuncWrapper, name_expansion_iterator,
               _RewriteExceptionHandler,
               fail_on_error=(not self.continue_on_error),
               shared_attrs=['op_failure_count'])

    if self.op_failure_count:
      plural_str = 's' if self.op_failure_count else ''
      raise CommandException('%d file%s/object%s could not be rewritten.' % (
          self.op_failure_count, plural_str, plural_str))

    return 0

  def RewriteFunc(self, name_expansion_result, thread_state=None):
    gsutil_api = GetCloudApiInstance(self, thread_state=thread_state)

    self.CheckProvider(name_expansion_result.expanded_storage_url)

    # If other transform types are added here, they must ensure that the
    # encryption key configuration matches the boto configuration, because
    # gsutil maintains an invariant that all objects it writes use the
    # encryption_key value (including decrypting if no key is present).
    if _TransformTypes.CRYPTO_KEY in self.transform_types:
      self.CryptoRewrite(name_expansion_result.expanded_storage_url, gsutil_api)

  def CryptoRewrite(self, transform_url, gsutil_api):
    """Make the cloud object at transform_url match encryption configuration.

    Args:
      transform_url: CloudUrl to rewrite.
      gsutil_api: gsutil CloudApi instance for making API calls.
    """
    # Get all fields so that we can ensure that the target metadata is
    # specified correctly.
    src_metadata = gsutil_api.GetObjectMetadata(
        transform_url.bucket_name, transform_url.object_name,
        generation=transform_url.generation, provider=transform_url.scheme)

    if self.no_preserve_acl:
      # Leave ACL unchanged.
      src_metadata.acl = []
    elif not src_metadata.acl:
      raise CommandException(
          'No OWNER permission found for object %s. OWNER permission is '
          'required for rewriting objects, (otherwise their ACLs would be '
          'reset).' % transform_url)

    src_encryption_sha256 = None
    if (src_metadata.customerEncryption and
        src_metadata.customerEncryption.keySha256):
      src_encryption_sha256 = src_metadata.customerEncryption.keySha256

    if src_encryption_sha256 == self.current_encryption_sha256:
      if self.current_encryption_sha256 is not None:
        self.logger.info('Skipping %s, already has current encryption key' %
                         transform_url)
      else:
        self.logger.info('Skipping %s, already decrypted' % transform_url)
    else:
      # Make a deep copy of the source metadata
      dst_metadata = encoding.PyValueToMessage(
          apitools_messages.Object, encoding.MessageToPyValue(src_metadata))

      # Remove some unnecessary/invalid fields.
      dst_metadata.customerEncryption = None
      dst_metadata.generation = None
      # Service has problems if we supply an ID, but it is responsible for
      # generating one, so it is not necessary to include it here.
      dst_metadata.id = None
      decryption_tuple = None

      if src_encryption_sha256 is None:
        announce_text = 'Encrypting'
      else:
        decryption_key = FindMatchingCryptoKey(src_encryption_sha256)
        if not decryption_key:
          raise EncryptionException(
              'Missing decryption key with SHA256 hash %s. No decryption key '
              'matches object %s' % (src_encryption_sha256, transform_url))
        decryption_tuple = CryptoTupleFromKey(decryption_key)

        if self.current_encryption_sha256 is None:
          announce_text = 'Decrypting'
        else:
          announce_text = 'Rotating'

      progress_callback = FileProgressCallbackHandler(
          ConstructAnnounceText(announce_text, transform_url.url_string),
          self.logger).call

      gsutil_api.CopyObject(
          src_metadata, dst_metadata, src_generation=transform_url.generation,
          preconditions=self.preconditions, progress_callback=progress_callback,
          decryption_tuple=decryption_tuple,
          encryption_tuple=self.current_encryption_tuple,
          provider=transform_url.scheme, fields=[])

