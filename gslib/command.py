# Copyright 2010 Google Inc. All Rights Reserved.
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

"""Base class for gsutil commands.

In addition to base class code, this file contains helpers that depend on base
class state (such as GetAclCommandHelper) In general, functions that depend on
class state and that are used by multiple commands belong in this file.
Functions that don't depend on class state belong in util.py, and non-shared
helpers belong in individual subclasses.
"""

import boto
import codecs
import getopt
import gslib
import logging
import multiprocessing
import os
import Queue
import re
import signal
import sys
import textwrap
import threading
import wildcard_iterator
import xml.dom.minidom

from boto import handler
from boto.exception import GSResponseError
from boto.storage_uri import StorageUri
from getopt import GetoptError
from gslib import util
from gslib.exception import CommandException
from gslib.help_provider import HelpProvider
from gslib.name_expansion import NameExpansionIterator
from gslib.name_expansion import NameExpansionIteratorQueue
from gslib.project_id import ProjectIdHandler
from gslib.storage_uri_builder import StorageUriBuilder
from gslib.thread_pool import ThreadPool
from gslib.util import IS_WINDOWS
from gslib.util import NO_MAX
from gslib.wildcard_iterator import ContainsWildcard
from oauth2client.client import HAS_CRYPTO


def _ThreadedLogger(command_name):
  """Creates a logger that resembles 'print' output, but is thread safe and
     abides by gsutil -d/-D/-DD/-q options.

  By default (if none of the above options is specified) the logger will display
  all messages logged with level INFO or above. Log propagation is disabled.

  Returns:
    A logger object.
  """
  log = logging.getLogger(command_name)
  log.propagate = False
  log.setLevel(logging.root.level)
  log_handler = logging.StreamHandler()
  log_handler.setFormatter(logging.Formatter('%(message)s'))
  # Commands that call other commands (like mv) would cause log handlers to be
  # added more than once, so avoid adding if one is already present.
  if not log.handlers:
    log.addHandler(log_handler)
  return log

def _UriArgChecker(command_instance, uri, shard):
  exp_src_uri = command_instance.suri_builder.StorageUri(
      uri.GetExpandedUriStr())
  command_instance.logger.debug('process %d shard %d is handling uri %s',
                                os.getpid(), shard, exp_src_uri)
  if (command_instance.exclude_symlinks and exp_src_uri.is_file_uri()
      and os.path.islink(exp_src_uri.object_name)):
    command_instance.logger.info('Skipping symbolic link %s...', exp_src_uri)
    return False
  return True

def DummyArgChecker(command_instance, arg, shard):
  return True

# command_spec key constants.
COMMAND_NAME = 'command_name'
COMMAND_NAME_ALIASES = 'command_name_aliases'
MIN_ARGS = 'min_args'
MAX_ARGS = 'max_args'
SUPPORTED_SUB_ARGS = 'supported_sub_args'
FILE_URIS_OK = 'file_uri_ok'
PROVIDER_URIS_OK = 'provider_uri_ok'
URIS_START_ARG = 'uris_start_arg'

_EOF_ARGUMENT = ("EOF")

# Map from deprecated aliases to the current command and subcommands that
# provide the same behavior.
OLD_ALIAS_MAP = {'chacl': ['acl', 'ch'],
                 'getacl': ['acl', 'get'],
                 'setacl': ['acl', 'set'],
                 'getcors': ['cors', 'get'],
                 'setcors': ['cors', 'set'],
                 'chdefacl': ['defacl', 'ch'],
                 'getdefacl': ['defacl', 'get'],
                 'setdefacl': ['defacl', 'set'],
                 'disablelogging': ['logging', 'set', 'off'],
                 'enablelogging': ['logging', 'set', 'on'],
                 'getlogging': ['logging', 'get'],
                 'getversioning': ['versioning', 'get'],
                 'setversioning': ['versioning', 'set'],
                 'getwebcfg': ['web', 'get'],
                 'setwebcfg': ['web', 'set']}

class Command(object):
  REQUIRED_SPEC_KEYS = [COMMAND_NAME]

  # Each subclass must define the following map, minimally including the
  # keys in REQUIRED_SPEC_KEYS; other values below will be used as defaults,
  # although for readbility subclasses should specify the complete map.
  command_spec = {
    # Name of command.
    COMMAND_NAME : None,
    # List of command name aliases.
    COMMAND_NAME_ALIASES : [],
    # Min number of args required by this command.
    MIN_ARGS : 0,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : NO_MAX,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : '',
    # True if file URIs are acceptable for this command.
    FILE_URIS_OK : False,
    # True if provider-only URIs are acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 0,
  }
  _default_command_spec = command_spec
  help_spec = HelpProvider.help_spec
  _commands_with_subcommands_and_subopts = ['acl', 'defacl', 'logging', 'web']

  """Define an empty test specification, which derived classes must populate.

  This is a list of tuples containing the following values:

    step_name - mnemonic name for test, displayed when test is run
    cmd_line - shell command line to run test
    expect_ret or None - expected return code from test (None means ignore)
    (result_file, expect_file) or None - tuple of result file and expected
                                         file to diff for additional test
                                         verification beyond the return code
                                         (None means no diff requested)
  Notes:

  - Setting expected_ret to None means there is no expectation and,
    hence, any returned value will pass.

  - Any occurrences of the string 'gsutil' in the cmd_line parameter
    are expanded to the full path to the gsutil command under test.

  - The cmd_line, result_file and expect_file parameters may
    contain the following special substrings:

    $Bn - converted to one of 10 unique-for-testing bucket names (n=0..9)
    $On - converted to one of 10 unique-for-testing object names (n=0..9)
    $Fn - converted to one of 10 unique-for-testing file names (n=0..9)
    $G  - converted to the directory where gsutil is installed. Useful for
          referencing test data.

  - The generated file names are full pathnames, whereas the generated
    bucket and object names are simple relative names.

  - Tests with a non-None result_file and expect_file automatically
    trigger an implicit diff of the two files.

  - These test specifications, in combination with the conversion strings
    allow tests to be constructed parametrically. For example, here's an
    annotated subset of a test_steps for the cp command:

    # Copy local file to object, verify 0 return code.
    ('simple cp', 'gsutil cp $F1 gs://$B1/$O1', 0, None, None),
    # Copy uploaded object back to local file and diff vs. orig file.
    ('verify cp', 'gsutil cp gs://$B1/$O1 $F2', 0, '$F2', '$F1'),

  - After pattern substitution, the specs are run sequentially, in the
    order in which they appear in the test_steps list.
  """
  test_steps = []

  # Define a convenience property for command name, since it's used many places.
  def _GetDefaultCommandName(self):
    return self.command_spec[COMMAND_NAME]
  command_name = property(_GetDefaultCommandName)
  
  def _CalculateUrisStartArg(self):
    """Calculate the index in args of the first URI arg. By default, just use
       the value from command_spec.
    """
    return self.command_spec[URIS_START_ARG]

  def _TranslateDeprecatedAliases(self, args):
    """For commands that have deprecated aliases, this will map the aliases to
       the corresponding new command and also warn the user about deprecation.
    """
    new_command_args = OLD_ALIAS_MAP.get(self.command_alias_used, None)
    if new_command_args:
      # Prepend any subcommands for the new command. The command name itself
      # is not part of the args, so leave it out.
      args = new_command_args[1:] + args
      self.logger.warn('\n'.join(textwrap.wrap((
          'You are using a deprecated alias, "%(used_alias)s", for the '
          '"%(command_name)s" command. Please use "%(command_name)s" with the '
          'appropriate sub-command in the future. See "gsutil help '
          '%(command_name)s" for details.') %
          {'used_alias': self.command_alias_used,
           'command_name': self.command_name })))
    return args

  def __init__(self, command_runner, args, headers, debug, parallel_operations,
               config_file_list, bucket_storage_uri_class, test_method=None,
               logging_filters=None, command_alias_used=None):
    """
    Args:
      command_runner: CommandRunner (for commands built atop other commands).
      args: Command-line args (arg0 = actual arg, not command name ala bash).
      headers: Dictionary containing optional HTTP headers to pass to boto.
      debug: Debug level to pass in to boto connection (range 0..3).
      parallel_operations: Should command operations be executed in parallel?
      config_file_list: Config file list returned by GetBotoConfigFileList().
      bucket_storage_uri_class: Class to instantiate for cloud StorageUris.
                                Settable for testing/mocking.
      test_method: Optional general purpose method for testing purposes.
                   Application and semantics of this method will vary by
                   command and test type.
      logging_filters: Optional list of logging.Filters to apply to this
                       command's logger.
      command_alias_used: The alias that was actually used when running this
                          command (as opposed to the "official" command name,
                          which will always correspond to the file name).

    Implementation note: subclasses shouldn't need to define an __init__
    method, and instead depend on the shared initialization that happens
    here. If you do define an __init__ method in a subclass you'll need to
    explicitly call super().__init__(). But you're encouraged not to do this,
    because it will make changing the __init__ interface more painful.
    """
    # Save class values from constructor params.
    self.command_runner = command_runner
    self.unparsed_args = args
    self.headers = headers
    self.debug = debug
    self.parallel_operations = parallel_operations
    self.config_file_list = config_file_list
    self.bucket_storage_uri_class = bucket_storage_uri_class
    self.test_method = test_method
    self.exclude_symlinks = False
    self.recursion_requested = False
    self.all_versions = False
    self.command_alias_used = command_alias_used

    # Global instance of a threaded logger object.
    self.logger = _ThreadedLogger(self.command_name)
    if logging_filters:
      for filter in logging_filters:
        self.logger.addFilter(filter)

    # Process sub-command instance specifications.
    # First, ensure subclass implementation sets all required keys.
    for k in self.REQUIRED_SPEC_KEYS:
      if k not in self.command_spec or self.command_spec[k] is None:
        raise CommandException('"%s" command implementation is missing %s '
                               'specification' % (self.command_name, k))
    # Now override default command_spec with subclass-specified values.
    tmp = self._default_command_spec
    tmp.update(self.command_spec)
    self.command_spec = tmp
    del tmp

    # Make sure command provides a test specification.
    if not self.test_steps:
      # TODO: Uncomment following lines when test feature is ready.
      #raise CommandException('"%s" command implementation is missing test '
                             #'specification' % self.command_name)
      pass

    # Parse and validate args.
    args = self._TranslateDeprecatedAliases(args)
    try:
      (self.sub_opts, self.args) = getopt.getopt(
          args, self.command_spec[SUPPORTED_SUB_ARGS])
    except GetoptError, e:
      raise CommandException('%s for "%s" command.' % (e.msg,
                                                       self.command_name))
    self.command_spec[URIS_START_ARG] = self._CalculateUrisStartArg()
    
    if (len(self.args) < self.command_spec[MIN_ARGS]
        or len(self.args) > self.command_spec[MAX_ARGS]):
      raise CommandException('Wrong number of arguments for "%s" command.' %
                             self.command_name)

    if not (self.command_name in
            self._commands_with_subcommands_and_subopts):
      self.CheckArguments()
    
    self.proj_id_handler = ProjectIdHandler()
    self.suri_builder = StorageUriBuilder(debug, bucket_storage_uri_class)

    # Cross-platform path to run gsutil binary.
    self.gsutil_cmd = ''
    # Cross-platform list containing gsutil path for use with subprocess.
    self.gsutil_exec_list = []
    # If running on Windows, invoke python interpreter explicitly.
    if gslib.util.IS_WINDOWS:
      self.gsutil_cmd += 'python '
      self.gsutil_exec_list += ['python']
    # Add full path to gsutil to make sure we test the correct version.
    self.gsutil_path = gslib.GSUTIL_PATH
    self.gsutil_cmd += self.gsutil_path
    self.gsutil_exec_list += [self.gsutil_path]

    # We're treating recursion_requested like it's used by all commands, but
    # only some of the commands accept the -R option.
    if self.sub_opts:
      for o, unused_a in self.sub_opts:
        if o == '-r' or o == '-R':
          self.recursion_requested = True
          break

  def CheckArguments(self):
    """Checks that the arguments provided on the command line fit the
       expectations of the command_spec. Any commands in
       self._commands_with_subcommands_and_subopts are responsible for calling
       this method after handling initial parsing of their arguments.
       This prevents commands with sub-commands as well as options from breaking
       the parsing of getopt.

       TODO: Provide a function to parse commands and sub-commands more
       intelligently once we stop allowing the deprecated command versions.
    """

    if (not self.command_spec[FILE_URIS_OK]
        and self.HaveFileUris(self.args[self.command_spec[URIS_START_ARG]:])):
      raise CommandException('"%s" command does not support "file://" URIs. '
                             'Did you mean to use a gs:// URI?' %
                             self.command_name)
    if (not self.command_spec[PROVIDER_URIS_OK]
        and self._HaveProviderUris(
            self.args[self.command_spec[URIS_START_ARG]:])):
      raise CommandException('"%s" command does not support provider-only '
                             'URIs.' % self.command_name)

  def WildcardIterator(self, uri_or_str, all_versions=False):
    """
    Helper to instantiate gslib.WildcardIterator. Args are same as
    gslib.WildcardIterator interface, but this method fills in most of the
    values from instance state.

    Args:
      uri_or_str: StorageUri or URI string naming wildcard objects to iterate.
    """
    return wildcard_iterator.wildcard_iterator(
        uri_or_str, self.proj_id_handler,
        bucket_storage_uri_class=self.bucket_storage_uri_class,
        all_versions=all_versions,
        headers=self.headers, debug=self.debug)

  def RunCommand(self):
    """Abstract function in base class. Subclasses must implement this. The
    return value of this function will be used as the exit status of the
    process, so subclass commands should return an integer exit code (0 for
    success, a value in [1,255] for failure).
    """
    raise CommandException('Command %s is missing its RunCommand() '
                           'implementation' % self.command_name)

  ############################################################
  # Shared helper functions that depend on base class state. #
  ############################################################

  def UrisAreForSingleProvider(self, uri_args):
    """Tests whether the uris are all for a single provider.

    Returns: a StorageUri for one of the uris on success, None on failure.
    """
    provider = None
    uri = None
    for uri_str in uri_args:
      # validate=False because we allow wildcard uris.
      uri = boto.storage_uri(
          uri_str, debug=self.debug, validate=False,
          bucket_storage_uri_class=self.bucket_storage_uri_class)
      if not provider:
        provider = uri.scheme
      elif uri.scheme != provider:
        return None
    return uri

  def SetAclCommandHelper(self):
    """
    Common logic for setting ACLs. Sets the standard ACL or the default
    object ACL depending on self.command_name.
    """

    acl_arg = self.args[0]
    uri_args = self.args[1:]
    # Disallow multi-provider setacl requests, because there are differences in
    # the ACL models.
    storage_uri = self.UrisAreForSingleProvider(uri_args)
    if not storage_uri:
      raise CommandException('"%s" command spanning providers not allowed.' %
                             self.command_name)

    # Determine whether acl_arg names a file containing XML ACL text vs. the
    # string name of a canned ACL.
    if os.path.isfile(acl_arg):
      with codecs.open(acl_arg, 'r', 'utf-8') as f:
        acl_arg = f.read()
      self.canned = False
    else:
      # No file exists, so expect a canned ACL string.
      canned_acls = storage_uri.canned_acls()
      if acl_arg not in canned_acls:
        raise CommandException('Invalid canned ACL "%s".' % acl_arg)
      self.canned = True

    # Used to track if any ACLs failed to be set.
    self.everything_set_okay = True

    def _SetAclExceptionHandler(e):
      """Simple exception handler to allow post-completion status."""
      self.logger.error(str(e))
      self.everything_set_okay = False

    def _SetAclFunc(name_expansion_result):
      exp_src_uri = self.suri_builder.StorageUri(
          name_expansion_result.GetExpandedUriStr())
      # We don't do bucket operations multi-threaded (see comment below).
      assert self.command_name != 'defacl'
      self.logger.info('Setting ACL on %s...' %
                       name_expansion_result.expanded_uri_str)
      try:
        if self.canned:
          exp_src_uri.set_acl(acl_arg, exp_src_uri.object_name, False,
                              self.headers)
        else:
          exp_src_uri.set_xml_acl(acl_arg, exp_src_uri.object_name, False,
                                  self.headers)
      except GSResponseError as e:
        if self.continue_on_error:
          exc_name, message, detail = util.ParseErrorDetail(e)
          self.everything_set_okay = False
          sys.stderr.write(util.FormatErrorMessage(
            exc_name, e.status, e.code, e.reason, message, detail))
        else:
          raise

    # If user specified -R option, convert any bucket args to bucket wildcards
    # (e.g., gs://bucket/*), to prevent the operation from being  applied to
    # the buckets themselves.
    if self.recursion_requested:
      for i in range(len(uri_args)):
        uri = self.suri_builder.StorageUri(uri_args[i])
        if uri.names_bucket():
          uri_args[i] = uri.clone_replace_name('*').uri
    else:
      # Handle bucket ACL setting operations single-threaded, because
      # our threading machinery currently assumes it's working with objects
      # (name_expansion_iterator), and normally we wouldn't expect users to need
      # to set ACLs on huge numbers of buckets at once anyway.
      for i in range(len(uri_args)):
        uri_str = uri_args[i]
        if self.suri_builder.StorageUri(uri_str).names_bucket():
          self._RunSingleThreadedSetAcl(acl_arg, uri_args)
          return

    name_expansion_iterator = NameExpansionIterator(
        self.command_name, self.proj_id_handler, self.headers, self.debug,
        self.logger, self.bucket_storage_uri_class, uri_args,
        self.recursion_requested, self.recursion_requested,
        all_versions=self.all_versions)
    # Perform requests in parallel (-m) mode, if requested, using
    # configured number of parallel processes and threads. Otherwise,
    # perform requests with sequential function calls in current process.
    self.Apply(_SetAclFunc, name_expansion_iterator, _SetAclExceptionHandler)

    if not self.everything_set_okay and not self.continue_on_error:
      raise CommandException('ACLs for some objects could not be set.')

  def _RunSingleThreadedSetAcl(self, acl_arg, uri_args):
    some_matched = False
    for uri_str in uri_args:
      for blr in self.WildcardIterator(uri_str):
        if blr.HasPrefix():
          continue
        some_matched = True
        uri = blr.GetUri()
        if self.command_name == 'defacl':
          self.logger.info('Setting default object ACL on %s...', uri)
          if self.canned:
            uri.set_def_acl(acl_arg, uri.object_name, False, self.headers)
          else:
            uri.set_def_xml_acl(acl_arg, False, self.headers)
        else:
          self.logger.info('Setting ACL on %s...', uri)
          if self.canned:
            uri.set_acl(acl_arg, uri.object_name, False, self.headers)
          else:
            uri.set_xml_acl(acl_arg, uri.object_name, False, self.headers)
    if not some_matched:
      raise CommandException('No URIs matched')

  def _WarnServiceAccounts(self):
    """Warns service account users who have received an AccessDenied error for
    one of the metadata-related commands to make sure that they are listed as
    Owners in the API console."""

    # Import this here so that the value will be set first in oauth2_plugin.
    from gslib.third_party.oauth2_plugin.oauth2_plugin import IS_SERVICE_ACCOUNT

    if IS_SERVICE_ACCOUNT:
      # This method is only called when canned ACLs are used, so the warning
      # definitely applies.
      self.logger.warning('\n'.join(textwrap.wrap(
          'It appears that your service account has been denied access while '
          'attempting to perform a metadata operation. If you believe that you '
          'should have access to this metadata (i.e., if it is associated with '
          'your account), please make sure that your service account''s email '
          'address is listed as an Owner in the Team tab of the API console. '
          'See "gsutil help creds" for further information.\n')))

  def GetAclCommandHelper(self):
    """Common logic for getting ACLs. Gets the standard ACL or the default
    object ACL depending on self.command_name."""

    # Resolve to just one object.
    # Handle wildcard-less URI specially in case this is a version-specific
    # URI, because WildcardIterator().IterUris() would lose the versioning info.
    if not ContainsWildcard(self.args[0]):
      uri = self.suri_builder.StorageUri(self.args[0])
    else:
      uris = list(self.WildcardIterator(self.args[0]).IterUris())
      if len(uris) == 0:
        raise CommandException('No URIs matched')
      if len(uris) != 1:
        raise CommandException('%s matched more than one URI, which is not '
            'allowed by the %s command' % (self.args[0], self.command_name))
      uri = uris[0]
    if not uri.names_bucket() and not uri.names_object():
      raise CommandException('"%s" command must specify a bucket or '
                             'object.' % self.command_name)
    if self.command_name == 'defacl':
      acl = uri.get_def_acl(False, self.headers)
    else:
      acl = uri.get_acl(False, self.headers)
    # Pretty-print the XML to make it more easily human editable.
    parsed_xml = xml.dom.minidom.parseString(acl.to_xml().encode('utf-8'))
    print parsed_xml.toprettyxml(indent='    ').encode('utf-8')

  def GetXmlSubresource(self, subresource, uri_arg):
    """Print an xml subresource, e.g. logging, for a bucket/object.

    Args:
      subresource: The subresource name.
      uri_arg: URI for the bucket/object. Wildcards will be expanded.

    Raises:
      CommandException: if errors encountered.
    """
    # Wildcarding is allowed but must resolve to just one bucket.
    uris = list(self.WildcardIterator(uri_arg).IterUris())
    if len(uris) != 1:
      raise CommandException('Wildcards must resolve to exactly one item for '
                             'get %s' % subresource)
    uri = uris[0]
    xml_str = uri.get_subresource(subresource, False, self.headers)
    # Pretty-print the XML to make it more easily human editable.
    parsed_xml = xml.dom.minidom.parseString(xml_str.encode('utf-8'))
    print parsed_xml.toprettyxml(indent='    ')
    
  def _AccountForWindowsResourceLimitations(self, concurrency, is_main_thread):
    """In order to avoid the max number of files limit imposed by Windows
       (which apparently cannot be changed), we need to be careful not to
       create too many threads/processes. 
    """
    if IS_WINDOWS and not is_main_thread:
      # It seems that the most common limit to the number of open files is
      # 512, so try to stay under 400 in order to account for the top-level
      # threads/processes. This number might need some tweaking, as it
      # was obtained experimentally in one Windows 7 envrionment.
      concurrency = max(min(concurrency, 400 / concurrency), 2)
    return concurrency

  def Apply(self, func, args_iterator, thr_exc_handler,
            shared_attrs=None, arg_checker=_UriArgChecker,
            parallel_operations_override=False, process_count=None,
            thread_count=None, queue_class=NameExpansionIteratorQueue,
            should_return_results=False, ignore_subprocess_failures=False,
            is_main_thread=True):
    """Dispatch input arguments across a pool of parallel OS
       processes and/or Python threads, based on options (-m or not)
       and settings in the user's config file. If non-parallel mode
       or only one OS process requested, execute requests sequentially
       in the current OS process.

       For a non-recursive call to Apply, the following will happen:
       - If process_count is 1, then any necessary threads will be created
         by the current process by _ApplyThreads.
       - If thread_count is 1, then we will create any necessary processes,
         and each such process will execute func in its main thread.
       - If process_count > 1, then new processes will be created to call the
         _ApplyThreads method.
       - If thread_count > 1, then the _ApplyThreads method will create a thread
         pool with which to execute the calls to func.

       If this function is called recursively (indicated by is_main_thread
       being False), then the following will happen:
       - If process_count or thread_count is 1, then the logic does not change.
       - If process_count > 1 or thread_count > 1, then we will simply behave as
         though process_count == 1. This prevents us from creating processes in
         threads created by other processes, which exposes a Python bug. The
         issue is recorded at http://bugs.python.org/issue1731717, but it is
         called out in the multiprocessing source code as not having been fixed.

    Args:
      func: Function to call to process each URI.
      args_iterator: Iterable collection of arguments to be put into the
                     work queue.
      thr_exc_handler: Exception handler for ThreadPool class.
      shared_attrs: List of attributes to manage across sub-processes.
      arg_checker: Used to determine whether we should process the current
                   argument or simply skip it. Also handles any logging that
                   is specific to a particular type of argument.
      parallel_operations_override: Used to override self.parallel_operations.
                                    This allows the caller to safely override
                                    the top-level flag for a single call.
      process_count: The number of processes to use. If not specified, then
                     the configured default will be used.
      thread_count: The number of threads per process. If not speficied, then
                    the configured default will be used.
      queue_class: A class that behaves like a multiprocessing.Queue(), except
                   that it returns and "EOF" value forever once the queue is
                   empty.
      should_return_results: If true, then return the results of all successful
                             calls to func in a list.
      ignore_subprocess_failures: An exception will be raised upon failure in
                                  a subprocess iff this flag is False.
      is_main_thread: True iff this function was called from the main thread.

    Raises:
      CommandException if invalid config encountered.
    """

    # Set OS process and python thread count as a function of options
    # and config.
    if self.parallel_operations or parallel_operations_override:
      if not process_count:
        process_count = boto.config.getint(
            'GSUtil', 'parallel_process_count',
            gslib.commands.config.DEFAULT_PARALLEL_PROCESS_COUNT)
      if process_count < 1:
        raise CommandException('Invalid parallel_process_count "%d".' %
                               process_count)
      if not thread_count:
        thread_count = boto.config.getint(
            'GSUtil', 'parallel_thread_count',
            gslib.commands.config.DEFAULT_PARALLEL_THREAD_COUNT)
      if thread_count < 1:
        raise CommandException('Invalid parallel_thread_count "%d".' %
                               thread_count)
    else:
      # If -m not specified, then assume 1 OS process and 1 Python thread.
      process_count = 1
      thread_count = 1

    self.logger.debug('process count: %d', process_count)
    self.logger.debug('thread count: %d', thread_count)

    if ((self.parallel_operations or parallel_operations_override)
        and process_count > 1 and (is_main_thread or thread_count == 1)):
      # We know that thread_count == 1 if we're not in the main thread, so
      # limit the process_count.
      process_count = self._AccountForWindowsResourceLimitations(process_count,
                                                                 is_main_thread)
      return_values = []
      self.procs = []
      # If any shared attributes passed by caller, create a dictionary of
      # shared memory variables for every element in the list of shared
      # attributes.
      shared_vars = None
      if shared_attrs:
        for name in shared_attrs:
          if not shared_vars:
            shared_vars = {}
          shared_vars[name] = multiprocessing.Value('i', 0)
      # Construct work queue for parceling out work to multiprocessing workers,
      # setting the max queue length of 32.5k so we will block if workers don't
      # empty the queue as fast as we can continue iterating over the bucket
      # listing. This number may need tuning; it should be large enough to
      # keep workers busy (overlapping bucket list next-page retrieval with
      # operations being fed from the queue) but small enough that we don't
      # overfill memory when running across a slow network link. There also
      # appear to be default limits on some system configurations e.g., some
      # versions of OS X) that prevent setting this value above 32768.
      work_queue = multiprocessing.Queue(32500)
      manager = multiprocessing.Manager()
      result_list = manager.list()
      for shard in range(process_count):
        # Spawn a separate OS process for each shard.
        self.logger.debug('spawning process for shard %d', shard)
        p = multiprocessing.Process(target=self._ApplyThreads,
                                    args=(func, work_queue, shard,
                                          thread_count, thr_exc_handler,
                                          shared_vars, arg_checker,
                                          result_list, should_return_results))
        self.procs.append(p)
        p.start()

      # Catch ^C under Linux/MacOs so we can kill the suprocesses.
      if not IS_WINDOWS and is_main_thread:
        try:
          signal.signal(signal.SIGINT, self._HandleMultiProcessingControlC)
        except ValueError, e:
          # This can happen if signal() is called from a thread other than the
          # main thread, which can currently only happen in a special case of
          # perfdiag.
          # TODO: Remove this when Apply() has been refactored to not create
          # multiple recursive levels of threads and processes.
          self.logger.warn(e)

      last_name_expansion_result = None
      try:
        # Feed all work into the queue being emptied by the workers.
        for arg in args_iterator:
          last_arg = arg
          work_queue.put(arg)
      except:
        sys.stderr.write('Failed URI iteration. Last result (prior to '
                         'exception) was: %s\n'
                         % repr(last_arg))
      finally:
        # We do all of the process cleanup in a finally cause in case the name
        # expansion iterator throws an exception. This will send EOF to all the
        # child processes and join them back into the parent process.

        # Send an EOF per worker.
        for shard in range(process_count):
          work_queue.put(_EOF_ARGUMENT)

        # Wait for all spawned OS processes to finish.
        failed_process_count = 0
        for p in self.procs:
          p.join()
          # Count number of procs that returned non-zero exit code.
          if p.exitcode != 0:
            failed_process_count += 1

        # result_list is a ListProxy - copy it into a normal list.
        for result in result_list:
          return_values.append(result)

        # Propagate shared variables back to caller's attributes.
        if shared_vars:
          for (name, var) in shared_vars.items():
            setattr(self, name, var.value)

      # Abort main process if one or more sub-processes failed. Note that this
      # is outside the finally clause, because we only want to raise a new
      # exception if an exception wasn't already raised in the try clause above.
      if failed_process_count:
        plural_str = ''
        if failed_process_count > 1:
          plural_str = 'es'
        message = ('unexpected failure in %d sub-process%s, '
                   'aborting...' % (failed_process_count, plural_str))
        if ignore_subprocess_failures:
          logging.warning(message)
        else:
          raise Exception(message)
      return return_values

    else:
      # In this case, we're not going to create any new processes, so we only
      # need to limit the thread_count.
      thread_count = self._AccountForWindowsResourceLimitations(thread_count,
                                                                is_main_thread)

      # We're not creating a new process, so funnel arguments to _ApplyThreads
      # using a thread-safe queue class that will send one EOF once the
      # iterator empties.
      work_queue = queue_class(args_iterator, _EOF_ARGUMENT)
      return self._ApplyThreads(func, work_queue, 0, thread_count,
                                thr_exc_handler, None, arg_checker,
                                should_return_results=should_return_results,
                                use_thr_exc_handler=ignore_subprocess_failures)

  def _HandleMultiProcessingControlC(self, signal_num, cur_stack_frame):
    """Called when user hits ^C during a multi-processing/multi-threaded
       request, so we can kill the subprocesses."""
    # Note: This only works under Linux/MacOS. See
    # https://github.com/GoogleCloudPlatform/gsutil/issues/99 for details
    # about why making it work correctly across OS's is harder and still open.
    for proc in self.procs:
      os.kill(proc.pid, signal.SIGKILL)
    sys.stderr.write('Caught ^C - exiting\n')
    # Simply calling sys.exit(1) doesn't work - see above bug for details.
    os.kill(os.getpid(), signal.SIGKILL)

  def HaveFileUris(self, args_to_check):
    """Checks whether args_to_check contain any file URIs.

    Args:
      args_to_check: Command-line argument subset to check.

    Returns:
      True if args_to_check contains any file URIs.
    """
    for uri_str in args_to_check:
      if uri_str.lower().startswith('file://') or uri_str.find(':') == -1:
        return True
    return False

  ######################
  # Private functions. #
  ######################

  def _HaveProviderUris(self, args_to_check):
    """Checks whether args_to_check contains any provider URIs (like 'gs://').

    Args:
      args_to_check: Command-line argument subset to check.

    Returns:
      True if args_to_check contains any provider URIs.
    """
    for uri_str in args_to_check:
      if re.match('^[a-z]+://$', uri_str):
        return True
    return False

  def _ApplyThreads(self, func, work_queue, shard, num_threads,
                    thr_exc_handler=None, shared_vars=None,
                    arg_checker=_UriArgChecker, result_list=None,
                    should_return_results=False, use_thr_exc_handler=False):
    """
    Perform subset of required requests across a caller specified
    number of parallel Python threads, which may be one, in which
    case the requests are processed in the current thread.

    Args:
      func: Function to call for each argument.
      work_queue: shared queue of arguments to process.
      shard: Assigned subset (shard number) for this function.
      num_threads: Number of Python threads to spawn to process this shard.
      thr_exc_handler: Exception handler for ThreadPool class.
      shared_vars: Dict of shared memory variables to be managed.
                   (only relevant, and non-None, if this function is
                   run in a separate OS process).
      arg_checker: Used to determine whether we should process the current
                   argument or simply skip it. Also handles any logging that
                   is specific to a particular type of argument.
      result_list: A thread- and process-safe shared list in which to store
                   the return values from all calls to func. If result_list
                   is None (the default), then no return values will be stored.
      should_return_results: If False (the default), then return no values from
                             result_list.
      use_thr_exc_handler: If true, then use thr_exc_handler to process any
                           exceptions from func. Otherwise, exceptions from
                           func are propagated normally.

    Returns:
      return_values: A list of the return values from all calls to func. Or,
                     if return_results is False (the default), an empty list.
    """
    # Each OS process needs to establish its own set of connections to
    # the server to avoid writes from different OS processes interleaving
    # onto the same socket (and garbling the underlying SSL session).
    # We ensure each process gets its own set of connections here by
    # closing all connections in the storage provider connection pool.
    connection_pool = StorageUri.provider_pool
    if connection_pool:
      for i in connection_pool:
        connection_pool[i].connection.close()

    return_values = []

    if num_threads > 1:
      thread_pool = ThreadPool(num_threads, thr_exc_handler)
    try:
      while True: # Loop until we hit EOF marker.
        args = work_queue.get()
        if args == _EOF_ARGUMENT:
          break
        if not arg_checker(self, args, shard):
          continue
        if num_threads > 1:
          thread_pool.AddTask(func, args)
        else:
          try:
            return_value = func(args)
            if should_return_results:
              return_values.append(return_value)
              if (result_list is not None) and should_return_results:
                result_list.append(return_value)
          except Exception as e:
            if use_thr_exc_handler:
              thr_exc_handler(e)
            else:
              raise

      # If any Python threads created, wait here for them to finish.
    finally:
      if num_threads > 1:
        # We provide return values both in the normal way and in the
        # result_list so that we can use the result_list (which is quite slow)
        # for IPC, where it's necessary, and just return the values normally
        # when we're calling this function from a single process.
        return_values = thread_pool.Shutdown(should_return_results)
        if (result_list is not None) and should_return_results:
          for value in return_values:
              result_list.append(value)
    # If any shared variables (which means we are running in a separate OS
    # process), increment value for each shared variable.
    if shared_vars:
      for (name, var) in shared_vars.items():
        var.value += getattr(self, name)
    return return_values

class EofWorkQueue(Queue.Queue):
  """Thread-safe queue used to behave like a multiprocessing.Queue for the
     single-process case of command.Apply(). The only difference in
     functionality is that this object knows to always send a "final object"
     after the queue is empty, which will indicate that there is no more work
     to be done.
  """
  def __init__(self, args_list, final_argument):
    """Args:
         args_list: A list of all arguments that should be in the queue.
         final_argument: The "EOF" argument used by Apply() to indicate that
                         the process reading this queue has no more work to do.
    """
    self.queue = Queue.Queue(len(args_list))
    self.final_argument = final_argument
    for arg in args_list:
      self.queue.put(arg)

  def get(self):
    if self.queue.empty():
      # Apply assumes that the queue will continue to return
      # self.final_argument forever, so that each process running
      # _ApplyThreads will know that it has no more work to do.
      return self.final_argument
    else:
      return self.queue.get()
