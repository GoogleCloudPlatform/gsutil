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
import copy
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
import traceback
import wildcard_iterator
import xml.dom.minidom

from boto import handler
from boto.exception import GSResponseError
from boto.storage_uri import StorageUri
from collections import namedtuple
from getopt import GetoptError
from gslib import util
from gslib.exception import CommandException
from gslib.help_provider import HelpProvider
from gslib.name_expansion import NameExpansionIterator
from gslib.name_expansion import NameExpansionIteratorQueue
from gslib.parallelism_framework_util import AtomicIncrementDict
from gslib.parallelism_framework_util import BasicIncrementDict
from gslib.parallelism_framework_util import ThreadAndProcessSafeDict
from gslib.project_id import ProjectIdHandler
from gslib.storage_uri_builder import StorageUriBuilder
from gslib.util import GetConfigFilePath
from gslib.util import IS_WINDOWS
from gslib.util import MultiprocessingIsAvailable
from gslib.util import NO_MAX
from gslib.wildcard_iterator import ContainsWildcard
from oauth2client.client import HAS_CRYPTO

if IS_WINDOWS:
  import ctypes


def _DefaultExceptionHandler(cls, e):
  cls.logger.exception(e)

def CreateGsutilLogger(command_name):
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

def _UriArgChecker(command_instance, uri):
  exp_src_uri = command_instance.suri_builder.StorageUri(
      uri.GetExpandedUriStr())
  command_instance.logger.debug('process %d is handling uri %s',
                                os.getpid(), exp_src_uri)
  if (command_instance.exclude_symlinks and exp_src_uri.is_file_uri()
      and os.path.islink(exp_src_uri.object_name)):
    command_instance.logger.info('Skipping symbolic link %s...', exp_src_uri)
    return False
  return True


def DummyArgChecker(command_instance, arg):
  return True

def _SetAclFuncWrapper(cls, name_expansion_result):
  return cls._SetAclFunc(name_expansion_result)

def _SetAclExceptionHandler(cls, e):
  """Exception handler that maintains state about post-completion status."""
  cls.logger.error(str(e))
  cls.everything_set_okay = False

# We will keep this list of all thread- or process-safe queues ever created by
# the main thread so that we can forcefully kill them upon shutdown. Otherwise,
# we encounter a Python bug in which empty queues block forever on join (which
# is called as part of the Python exit function cleanup) under the impression
# that they are non-empty.
# However, this also lets us shut down somewhat more cleanly when interrupted.
queues = []

def _NewMultiprocessingQueue():
  queue = multiprocessing.Queue(MAX_QUEUE_SIZE)
  queues.append(queue)
  return queue

def _NewThreadsafeQueue():
  queue = Queue.Queue(MAX_QUEUE_SIZE)
  queues.append(queue)
  return queue


# command_spec key constants.
COMMAND_NAME = 'command_name'
COMMAND_NAME_ALIASES = 'command_name_aliases'
MIN_ARGS = 'min_args'
MAX_ARGS = 'max_args'
SUPPORTED_SUB_ARGS = 'supported_sub_args'
FILE_URIS_OK = 'file_uri_ok'
PROVIDER_URIS_OK = 'provider_uri_ok'
URIS_START_ARG = 'uris_start_arg'

# The maximum size of a process- or thread-safe queue. Imposing this limit
# prevents us from needing to hold an arbitrary amount of data in memory.
# However, setting this number too high (e.g., >= 32768 on OS X) can cause
# problems on some operating systems.
MAX_QUEUE_SIZE = 32500

# That maximum depth of the tree of recursive calls to command.Apply. This is
# an arbitrary limit put in place to prevent developers from accidentally
# causing problems with infinite recursion, and it can be increased if needed.
MAX_RECURSIVE_DEPTH = 5

ZERO_TASKS_TO_DO_ARGUMENT = ("There were no", "tasks to do")

# Map from deprecated aliases to the current command and subcommands that
# provide the same behavior.
# TODO: Remove this map and deprecate old commands on 9/9/14.
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


# Declare all of the module level variables - see
# InitializeMultiprocessingVariables for an explanation of why this is
# necessary.
global manager, consumer_pools, task_queues, caller_id_lock, caller_id_counter
global total_tasks, call_completed_map, global_return_values_map
global need_pool_or_done_cond, caller_id_finished_count, new_pool_needed
global current_max_recursive_level, shared_vars_map, shared_vars_list_map
global class_map


def InitializeMultiprocessingVariables():
  """
  Used to initialize module-level variables that will be inherited by
  subprocesses. On Windows, a multiprocessing.Manager object should only
  be created within an "if __name__ == '__main__':" block. This function
  must be called, otherwise every command that calls Command.Apply will fail.
  """
  # This list of global variables must exactly match the above list of
  # declarations.
  global manager, consumer_pools, task_queues, caller_id_lock, caller_id_counter
  global total_tasks, call_completed_map, global_return_values_map
  global need_pool_or_done_cond, caller_id_finished_count, new_pool_needed
  global current_max_recursive_level, shared_vars_map, shared_vars_list_map
  global class_map

  manager = multiprocessing.Manager()

  consumer_pools = []

  # List of all existing task queues - used by all pools to find the queue
  # that's appropriate for the given recursive_apply_level.
  task_queues = []

  # Used to assign a globally unique caller ID to each Apply call.
  caller_id_lock = manager.Lock()
  caller_id_counter = multiprocessing.Value('i', 0)

  # Map from caller_id to total number of tasks to be completed for that ID.
  total_tasks = ThreadAndProcessSafeDict(manager)

  # Map from caller_id to a boolean which is True iff all its tasks are
  # finished.
  call_completed_map = ThreadAndProcessSafeDict(manager)

  # Used to keep track of the set of return values for each caller ID.
  global_return_values_map = AtomicIncrementDict(manager)

  # Condition used to notify any waiting threads that a task has finished or
  # that a call to Apply needs a new set of consumer processes.
  need_pool_or_done_cond = manager.Condition()

  # Map from caller_id to the current number of completed tasks for that ID.
  caller_id_finished_count = AtomicIncrementDict(manager)

  # Used as a way for the main thread to distinguish between being woken up
  # by another call finishing and being woken up by a call that needs a new set
  # of consumer processes.
  new_pool_needed = multiprocessing.Value('i', 0)

  current_max_recursive_level = multiprocessing.Value('i', 0)

  # Map from (caller_id, name) to the value of that shared variable.
  shared_vars_map = AtomicIncrementDict(manager)
  shared_vars_list_map = ThreadAndProcessSafeDict(manager)

  # Map from caller_id to calling class.
  class_map = manager.dict()


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
  
  # This keeps track of the recursive depth of the current call to Apply.
  recursive_apply_level = 0

  # If the multiprocessing module isn't available, we'll use this to keep track
  # of the caller_id.
  sequential_caller_id = -1

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
          '"%(command_name)s" command. This will stop working on 9/9/2014. '
          'Please use "%(command_name)s" with the appropriate sub-command in '
          'the future. See "gsutil help %(command_name)s" for details.') %
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
    self.logger = CreateGsutilLogger(self.command_name)
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
      self._RaiseWrongNumberOfArgumentsException()

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

    self.multiprocessing_is_available = MultiprocessingIsAvailable()[0]

  def _RaiseWrongNumberOfArgumentsException(self):
    """Raise an exception indicating that the wrong number of arguments was
       provided for this command.
    """
    if len(self.args) > self.command_spec[MAX_ARGS]:
      message = ('The %s command accepts at most %d arguments.' %
                 (self.command_name, self.command_spec[MAX_ARGS]))
    elif len(self.args) < self.command_spec[MIN_ARGS]:
      message = ('The %s command requires at least %d arguments.' %
                 (self.command_name, self.command_spec[MIN_ARGS]))
    raise CommandException(message)

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
  
  def _SetAclFunc(self, name_expansion_result):
    exp_src_uri = self.suri_builder.StorageUri(
        name_expansion_result.GetExpandedUriStr())
    # We don't do bucket operations multi-threaded (see comment below).
    assert self.command_name != 'defacl'
    self.logger.info('Setting ACL on %s...' %
                     name_expansion_result.expanded_uri_str)
    try:
      if self.canned:
        exp_src_uri.set_acl(self.acl_arg, exp_src_uri.object_name, False,
                            self.headers)
      else:
        exp_src_uri.set_xml_acl(self.acl_arg, exp_src_uri.object_name, False,
                                self.headers)
    except GSResponseError as e:
      if self.continue_on_error:
        exc_name, message, detail = util.ParseErrorDetail(e)
        self.everything_set_okay = False
        sys.stderr.write(util.FormatErrorMessage(
          exc_name, e.status, e.code, e.reason, message, detail))
      else:
        raise

  def SetAclCommandHelper(self):
    """
    Common logic for setting ACLs. Sets the standard ACL or the default
    object ACL depending on self.command_name.
    """

    self.acl_arg = self.args[0]
    uri_args = self.args[1:]
    # Disallow multi-provider acl set requests, because there are differences in
    # the ACL models.
    storage_uri = self.UrisAreForSingleProvider(uri_args)
    if not storage_uri:
      raise CommandException('"%s" command spanning providers not allowed.' %
                             self.command_name)

    # Determine whether acl_arg names a file containing XML ACL text vs. the
    # string name of a canned ACL.
    if os.path.isfile(self.acl_arg):
      with codecs.open(self.acl_arg, 'r', 'utf-8') as f:
        self.acl_arg = f.read()
      self.canned = False
    else:
      # No file exists, so expect a canned ACL string.
      canned_acls = storage_uri.canned_acls()
      if self.acl_arg not in canned_acls:
        raise CommandException('Invalid canned ACL "%s".' % self.acl_arg)
      self.canned = True

    # Used to track if any ACLs failed to be set.
    self.everything_set_okay = True

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
          self._RunSingleThreadedSetAcl(self.acl_arg, uri_args)
          return

    name_expansion_iterator = NameExpansionIterator(
        self.command_name, self.proj_id_handler, self.headers, self.debug,
        self.logger, self.bucket_storage_uri_class, uri_args,
        self.recursion_requested, self.recursion_requested,
        all_versions=self.all_versions)
    # Perform requests in parallel (-m) mode, if requested, using
    # configured number of parallel processes and threads. Otherwise,
    # perform requests with sequential function calls in current process.
    self.Apply(_SetAclFuncWrapper, name_expansion_iterator,
               _SetAclExceptionHandler)

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

  def _HandleMultiProcessingControlC(self, signal_num, cur_stack_frame):
    """Called when user hits ^C during a multi-processing/multi-threaded
       request, so we can kill the subprocesses."""
    # Note: This only works under Linux/MacOS. See
    # https://github.com/GoogleCloudPlatform/gsutil/issues/99 for details
    # about why making it work correctly across OS's is harder and still open.
    ShutDownGsutil()
    sys.stderr.write('Caught ^C - exiting\n')
    # Simply calling sys.exit(1) doesn't work - see above bug for details.
    KillProcess(os.getpid())

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
  
  def _ResetConnectionPool(self):
    # Each OS process needs to establish its own set of connections to
    # the server to avoid writes from different OS processes interleaving
    # onto the same socket (and garbling the underlying SSL session).
    # We ensure each process gets its own set of connections here by
    # closing all connections in the storage provider connection pool.
    connection_pool = StorageUri.provider_pool
    if connection_pool:
      for i in connection_pool:
        connection_pool[i].connection.close()

  def _GetProcessAndThreadCount(self, process_count, thread_count,
                                parallel_operations_override):
    """
    Determines the values of process_count and thread_count that we should
    actually use. If we're not performing operations in parallel, then ignore
    existing values and use process_count = thread_count = 1.

    Args:
      process_count: A positive integer or None. In the latter case, we read
                     the value from the .boto config file.
      thread_count: A positive integer or None. In the latter case, we read
                    the value from the .boto config file.
      parallel_operations_override: Used to override self.parallel_operations.
                                    This allows the caller to safely override
                                    the top-level flag for a single call.

    Returns:
      (process_count, thread_count): The number of processes and threads to use,
                                     respectively.
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

    if IS_WINDOWS and process_count > 1:
      raise CommandException('\n'.join(textwrap.wrap((
          'It is not possible to set process_count > 1 on Windows. Please '
          'update your config file (located at %s) and set '
          '"process_count = 1".') %
          GetConfigFilePath())))
    self.logger.debug('process count: %d', process_count)
    self.logger.debug('thread count: %d', thread_count)
    
    return (process_count, thread_count)

  def _SetUpPerCallerState(self):
    """Set up the state for a caller id, corresponding to one Apply call."""
    # Get a new caller ID.
    with caller_id_lock:
      caller_id_counter.value = caller_id_counter.value + 1
      caller_id = caller_id_counter.value
    
    # Create a copy of self with an incremented recursive level. This allows
    # the class to report its level correctly if the function called from it
    # also needs to call Apply.
    cls = copy.copy(self)
    cls.recursive_apply_level += 1

    # Thread-safe loggers can't be pickled, so we will remove it here and
    # recreate it later in the WorkerThread. This is not a problem since any
    # logger with the same name will be treated as a singleton.
    cls.logger = None
    class_map[caller_id] = cls
    
    total_tasks[caller_id] = -1  # -1 => the producer hasn't finished yet.
    call_completed_map[caller_id] = False
    caller_id_finished_count.put(caller_id, 0)
    global_return_values_map.put(caller_id, [])
    return caller_id

  def _CreateNewConsumerPool(self, num_processes, num_threads):
    """Create a new pool of processes that call _ApplyThreads."""
    processes = []
    task_queue = _NewMultiprocessingQueue()
    task_queues.append(task_queue)

    current_max_recursive_level.value = current_max_recursive_level.value + 1
    if current_max_recursive_level.value > MAX_RECURSIVE_DEPTH:
      raise CommandException('Recursion depth of Apply calls is too great.')
    for shard in range(num_processes):
      recursive_apply_level = len(consumer_pools)
      p = multiprocessing.Process(
          target=self._ApplyThreads,
          args=(num_threads, recursive_apply_level, shard))
      p.daemon = True
      processes.append(p)
      p.start()
    consumer_pool = _ConsumerPool(processes, task_queue)
    consumer_pools.append(consumer_pool)

  def Apply(self, func, args_iterator, exception_handler,
            shared_attrs=None, arg_checker=_UriArgChecker,
            parallel_operations_override=False, process_count=None,
            thread_count=None, should_return_results=False,
            fail_on_error=False):
    """
    Determines whether the necessary parts of the multiprocessing module are
    available, and delegates to _ParallelApply or _SequentialApply as
    appropriate.

    Args:
      func: Function to call to process each argument.
      args_iterator: Iterable collection of arguments to be put into the
                     work queue.
      exception_handler: Exception handler for WorkerThread class.
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
                    the configured default will be used..
      should_return_results: If true, then return the results of all successful
                             calls to func in a list.
      fail_on_error: If true, then raise any exceptions encountered when
                     executing func. This is only applicable in the case of
                     process_count == thread_count == 1.
    """
    if shared_attrs:
      original_shared_vars_values = {}  # We'll add these back in at the end.
      for name in shared_attrs:
        original_shared_vars_values[name] = getattr(self, name)
        # By setting this to 0, we simplify the logic for computing deltas.
        # We'll add it back after all of the tasks have been performed.
        setattr(self, name, 0)

    (process_count, thread_count) = self._GetProcessAndThreadCount(
        process_count, thread_count, parallel_operations_override)
    is_main_thread = (self.recursive_apply_level == 0
                      and self.sequential_caller_id == -1)

    # We don't honor the fail_on_error flag in the case of multiple threads
    # or processes.
    fail_on_error = fail_on_error and (process_count * thread_count == 1)
    
    # Only check this from the first call in the main thread. Apart from the
    # fact that it's  wasteful to try this multiple times in general, it also
    # will never work when called from a subprocess since we use daemon
    # processes, and daemons can't create other processes.
    if is_main_thread:
      if ((not self.multiprocessing_is_available)
          and thread_count * process_count > 1):
        # Run the check again and log the appropriate warnings. This was run
        # before, when the Command object was created, in order to calculate
        # self.multiprocessing_is_available, but we don't want to print the
        # warning until we're sure the user actually tried to use multiple
        # threads or processes.
        MultiprocessingIsAvailable(logger=self.logger)

    if self.multiprocessing_is_available:
      caller_id = self._SetUpPerCallerState()
    else:
      self.sequential_caller_id += 1
      caller_id = self.sequential_caller_id
      
      if is_main_thread:
        global global_return_values_map, shared_vars_map
        global caller_id_finished_count, shared_vars_list_map
        global_return_values_map = BasicIncrementDict()
        global_return_values_map.put(caller_id, [])
        shared_vars_map = BasicIncrementDict()
        caller_id_finished_count = BasicIncrementDict()
        shared_vars_list_map = {}


    # If any shared attributes passed by caller, create a dictionary of
    # shared memory variables for every element in the list of shared
    # attributes.
    if shared_attrs:
      shared_vars_list_map[caller_id] = shared_attrs
      for name in shared_attrs:
        shared_vars_map.put((caller_id, name), 0)

    # Make all of the requested function calls.
    if self.multiprocessing_is_available and thread_count * process_count > 1:
      self._ParallelApply(func, args_iterator, exception_handler, caller_id,
                          arg_checker, parallel_operations_override,
                          process_count, thread_count, should_return_results,
                          fail_on_error)
    else:
      self._SequentialApply(func, args_iterator, exception_handler, caller_id,
                            arg_checker, should_return_results, fail_on_error)

    if shared_attrs:
      for name in shared_attrs:
        # This allows us to retain the original value of the shared variable,
        # and simply apply the delta after what was done during the call to
        # apply.                      
        final_value = (original_shared_vars_values[name] +
                       shared_vars_map.get((caller_id, name)))
        setattr(self, name, final_value)

    if should_return_results:
      return global_return_values_map.get(caller_id)

  def _SequentialApply(self, func, args_iterator, exception_handler, caller_id,
                       arg_checker, should_return_results, fail_on_error):
    """
    Perform all function calls sequentially in the current thread. No other
    threads or processes will be spawned. This degraded functionality is only
    for use when the multiprocessing module is not available for some reason.
    """

    # Create a WorkerThread to handle all of the logic needed to actually call
    # the function. Note that this thread will never be started, and all work
    # is done in the current thread.
    worker_thread = WorkerThread(None, False)
    args_iterator = iter(args_iterator)
    while True:
      
      # Try to get the next argument, handling any exceptions that arise.
      try:
        args = args_iterator.next()
      except StopIteration, e:
        break
      except Exception, e:
        if fail_on_error:
          raise
        else:
          try:
            exception_handler(self, e)
          except Exception, e1:
            self.logger.debug(
                'Caught exception while handling exception for %s:\n%s',
                func, traceback.format_exc())
          continue
      if arg_checker(self, args):
        # Now that we actually have the next argument, perform the task.
        task = Task(func, args, caller_id, exception_handler,
                    should_return_results, arg_checker, fail_on_error)
        worker_thread.PerformTask(task, self)

  def _ParallelApply(self, func, args_iterator, exception_handler, caller_id,
                     arg_checker, parallel_operations_override, process_count,
                     thread_count, should_return_results, fail_on_error):
    """
    Dispatch input arguments across a pool of parallel OS
    processes and/or Python threads, based on options (-m or not)
    and settings in the user's config file. If non-parallel mode
    or only one OS process requested, execute requests sequentially
    in the current OS process.
    
    In the multi-process case, we will create one pool of worker processes for
    each level of the tree of recursive calls to Apply. E.g., if A calls
    Apply(B), and B ultimately calls Apply(C) followed by Apply(D), then we
    will only create two sets of worker processes - B will execute in the first,
    and C and D will execute in the second. If C is then changed to call
    Apply(E) and D is changed to call Apply(F), then we will automatically
    create a third set of processes (lazily, when needed) that will be used to
    execute calls to E and F. This might look something like:

    Pool1 Executes:                B
                                  / \
    Pool2 Executes:              C   D
                                /     \
    Pool3 Executes:            E       F

    Apply's parallelism is generally broken up into 4 cases:
    - If process_count == thread_count == 1, then all tasks will be executed
      in this thread.
    - If process_count > 1 and thread_count == 1, then the main thread will
      create a new pool of processes (if they don't already exist) and each of
      those processes will execute the tasks in a single thread.
    - If process_count == 1 and thread_count > 1, then this process will create
      a new pool of threads to execute the tasks.
    - If process_count > 1 and thread_count > 1, then the main thread will
      create a new pool of processes (if they don't already exist) and each of
      those processes will, upon creation, create a pool of threads to
      execute the tasks.

    Args:
      caller_id: The caller ID unique to this call to command.Apply.
      See command.Apply for description of other arguments.
    """    
    is_main_thread = self.recursive_apply_level == 0

    # Catch ^C under Linux/MacOs so we can do cleanup before exiting.
    if not IS_WINDOWS and is_main_thread:
      signal.signal(signal.SIGINT, self._HandleMultiProcessingControlC)

    if not len(task_queues):
      # The process we create will need to access the next recursive level
      # of task queues if it makes a call to Apply, so we always keep around
      # one more queue than we know we need. OTOH, if we don't create a new
      # process, the existing process still needs a task queue to use.
      task_queues.append(_NewMultiprocessingQueue())

    if process_count > 1:  # Handle process pool creation.
      # Check whether this call will need a new set of workers.
      with need_pool_or_done_cond:
        if self.recursive_apply_level >= current_max_recursive_level.value:
          # Only the main thread is allowed to create new processes - otherwise,
          # we will run into some Python bugs.
          if is_main_thread:
            self._CreateNewConsumerPool(process_count, thread_count)
          else:
            # Notify the main thread that we need a new consumer pool.
            new_pool_needed.value = 1
            need_pool_or_done_cond.notify_all()
            # The main thread will notify us when it finishes.
            need_pool_or_done_cond.wait()

    # If we're running in this process, create a separate task queue. Otherwise,
    # if Apply has already been called with process_count > 1, then there will
    # be consumer pools trying to use our processes.
    if process_count > 1:
      task_queue = task_queues[self.recursive_apply_level]
    else:
      task_queue = _NewMultiprocessingQueue()

    # Kick off a producer thread to throw tasks in the global task queue. We
    # do this asynchronously so that the main thread can be free to create new
    # consumer pools when needed (otherwise, any thread with a task that needs
    # a new consumer pool must block until we're completely done producing; in
    # the worst case, every worker blocks on such a call and the producer fills
    # up the task queue before it finishes, so we block forever).
    producer_thread = ProducerThread(copy.copy(self), args_iterator, caller_id,
                                     func, task_queue, should_return_results,
                                     exception_handler, arg_checker,
                                     fail_on_error)

    if process_count > 1:
      # Wait here until either:
      #   1. We're the main thread and someone needs a new consumer pool - in
      #      which case we create one and continue waiting.
      #   2. Someone notifies us that all of the work we requested is done, in
      #      which case we retrieve the results (if applicable) and stop
      #      waiting.
      while True:
        with need_pool_or_done_cond:
          # Either our call is done, or someone needs a new level of consumer
          # pools, or we the wakeup call was meant for someone else. It's
          # impossible for both conditions to be true, since the main thread is
          # blocked on any other ongoing calls to Apply, and a thread would not
          # ask for a new consumer pool unless it had more work to do.
          if call_completed_map[caller_id]:
            break
          elif is_main_thread and new_pool_needed.value:
            new_pool_needed.value = 0
            self._CreateNewConsumerPool(process_count, thread_count)
            need_pool_or_done_cond.notify_all()
            
          # Note that we must check the above conditions before the wait() call;
          # otherwise, the notification can happen before we start waiting, in
          # which case we'll block forever.
          need_pool_or_done_cond.wait()
    else:  # Using a single process.
      shard = 0
      self._ApplyThreads(thread_count, self.recursive_apply_level, shard,
                         is_blocking_call=True, task_queue=task_queue)

    # We encountered an exception from the producer thread before any arguments
    # were enqueued, but it wouldn't have been propagated, so we'll now
    # explicitly raise it here.
    if producer_thread.unknown_exception:
      raise producer_thread.unknown_exception

    # We encountered an exception from the producer thread while iterating over
    # the arguments, so raise it here if we're meant to fail on error.
    if producer_thread.iterator_exception and fail_on_error:
      raise producer_thread.iterator_exception

  def _ApplyThreads(self, thread_count, recursive_apply_level, shard,
                    is_blocking_call=False, task_queue=None):
    """
    Assigns the work from the global task queue shared among all processes
    to an individual process, for later consumption either by the WorkerThreads
    or in this thread if thread_count == 1.
    
    Args:
      thread_count: The number of threads used to perform the work. If 1, then
                    perform all work in this thread.
      recursive_apply_level: The depth in the tree of recursive calls to Apply
                             of this thread.
      shard: Assigned subset (shard number) for this function.
      is_blocking_call: True iff the call to Apply is blocked on this call
                        (which is true iff process_count == 1), implying that
                        _ApplyThreads must behave as a blocking call.
    """
    self._ResetConnectionPool()
    
    task_queue = task_queue or task_queues[recursive_apply_level]

    if thread_count > 1:
      worker_pool = WorkerPool(thread_count)
    else:
      worker_pool = SameThreadWorkerPool(self)

    num_enqueued = 0
    while True:
      task = task_queue.get()
      if task.args != ZERO_TASKS_TO_DO_ARGUMENT:
        # If we have no tasks to do and we're performing a blocking call, we
        # need a special signal to tell us to stop - otherwise, we block on
        # the call to task_queue.get() forever.
        worker_pool.AddTask(task)
        num_enqueued += 1

      if is_blocking_call:
        num_to_do = total_tasks[task.caller_id]
        # The producer thread won't enqueue the last task until after it has
        # updated total_tasks[caller_id], so we know that num_to_do < 0 implies
        # we will do this check again.
        if num_to_do >= 0 and num_enqueued == num_to_do:
          if thread_count == 1:
            return
          else:
            while True:
              with need_pool_or_done_cond:
                if call_completed_map[task.caller_id]:
                  # We need to check this first, in case the condition was
                  # notified before we grabbed the lock.
                  return
                need_pool_or_done_cond.wait()


# Below here lie classes and functions related to controlling the flow of tasks
# between various threads and processes.


class _ConsumerPool(object):
  def __init__(self, processes, task_queue):
    self.processes = processes
    self.task_queue = task_queue

  def ShutDown(self):
    for process in self.processes:
      KillProcess(process.pid)


def KillProcess(pid):
  # os.kill doesn't work in 2.X or 3.Y on Windows for any X < 7 or Y < 2.
  if IS_WINDOWS and ((2, 6) <= sys.version_info[:3] < (2, 7) or
                     (3, 0) <= sys.version_info[:3] < (3, 2)):
    try:
      kernel32 = ctypes.windll.kernel32
      handle = kernel32.OpenProcess(1, 0, pid)
      kernel32.TerminateProcess(handle, 0)
    except:
      pass
  else:
    try:
      os.kill(pid, signal.SIGKILL)
    except OSError:
      pass


class Task(namedtuple('Task',
    'func args caller_id exception_handler should_return_results arg_checker ' +
    'fail_on_error')):
  """
  Args:
    func: The function to be executed.
    args: The arguments to func.
    caller_id: The globally-unique caller ID corresponding to the Apply call.
    exception_handler: The exception handler to use if the call to func fails.
    should_return_results: True iff the results of this function should be
                           returned from the Apply call.
    arg_checker: Used to determine whether we should process the current
                 argument or simply skip it. Also handles any logging that
                 is specific to a particular type of argument.
    fail_on_error: If true, then raise any exceptions encountered when
                   executing func. This is only applicable in the case of
                   process_count == thread_count == 1.
  """
  pass


class ProducerThread(threading.Thread):
  """Thread used to enqueue work for other processes and threads."""
  def __init__(self, cls, args_iterator, caller_id, func, task_queue,
               should_return_results, exception_handler, arg_checker,
               fail_on_error):
    """
    Args:
      cls: Instance of Command for which this ProducerThread was created.
      args_iterator: Iterable collection of arguments to be put into the
                     work queue.
      caller_id: Globally-unique caller ID corresponding to this call to Apply.
      func: The function to be called on each element of args_iterator.
      task_queue: The queue into which tasks will be put, to later be consumed
                  by Command._ApplyThreads.
      should_return_results: True iff the results for this call to command.Apply
                             were requested.
      exception_handler: The exception handler to use when errors are
                         encountered during calls to func.
      arg_checker: Used to determine whether we should process the current
                   argument or simply skip it. Also handles any logging that
                   is specific to a particular type of argument.
      fail_on_error: If true, then raise any exceptions encountered when
                     executing func. This is only applicable in the case of
                     process_count == thread_count == 1.
    """
    super(ProducerThread, self).__init__()
    self.func = func
    self.cls = cls
    self.args_iterator = args_iterator
    self.caller_id = caller_id
    self.task_queue = task_queue
    self.arg_checker = arg_checker
    self.exception_handler = exception_handler
    self.should_return_results = should_return_results
    self.fail_on_error = fail_on_error
    self.shared_variables_updater = _SharedVariablesUpdater()
    self.daemon = True
    self.unknown_exception = None
    self.iterator_exception = None
    self.start()

  def run(self):
    num_tasks = 0
    cur_task = None
    last_task = None
    try:
      args_iterator = iter(self.args_iterator)
      while True:
        try:
          args = args_iterator.next()
        except StopIteration, e:
          break
        except Exception, e:
          if self.fail_on_error:
            self.iterator_exception = e
            raise
          else:
            try:
              self.exception_handler(self.cls, e)
            except Exception, e1:
              self.cls.logger.debug(
                  'Caught exception while handling exception for %s:\n%s',
                  self.func, traceback.format_exc())
            self.shared_variables_updater.Update(self.caller_id, self.cls)
            continue

        if self.arg_checker(self.cls, args):
          num_tasks += 1
          last_task = cur_task
          cur_task = Task(self.func, args, self.caller_id,
                          self.exception_handler, self.should_return_results,
                          self.arg_checker, self.fail_on_error)
          if last_task:
            self.task_queue.put(last_task, self.caller_id)
    except Exception, e:
      # This will also catch any exception raised due to an error in the
      # iterator when fail_on_error is set, so check that we failed for some
      # other reason before claiming that we had an unknown exception.
      if not self.iterator_exception:
        self.unknown_exception = e
    finally:
      # We need to make sure to update total_tasks[caller_id] before we enqueue
      # the last task. Otherwise, a worker can retrieve the last task and
      # complete it, then check total_tasks and determine that we're not done
      # producing all before we update total_tasks. This approach forces workers
      # to wait on the last task until after we've updated total_tasks.
      total_tasks[self.caller_id] = num_tasks
      if not cur_task:
        # This happens if there were zero arguments to be put in the queue.
        cur_task = Task(None, ZERO_TASKS_TO_DO_ARGUMENT, self.caller_id,
                        None, None, None, None)
      self.task_queue.put(cur_task, self.caller_id)

      # It's possible that the workers finished before we updated total_tasks,
      # so we need to check here as well.
      _NotifyIfDone(self.caller_id,
                    caller_id_finished_count.get(self.caller_id))
      

class SameThreadWorkerPool(object):
  """Behaves like a WorkerPool, but used for the single-threaded case."""
  def __init__(self, cls):
    self.cls = cls
    self.worker_thread = WorkerThread(None)
  
  def AddTask(self, task):
    self.worker_thread.PerformTask(task, self.cls)


class WorkerPool(object):
  """Pool of worker threads to which tasks can be added."""
  def __init__(self, thread_count):
    self.task_queue = _NewThreadsafeQueue()
    self.threads = []
    for _ in range(thread_count):
      worker_thread = WorkerThread(self.task_queue)
      self.threads.append(worker_thread)
      worker_thread.start()

  def AddTask(self, task):
    self.task_queue.put(task)


class WorkerThread(threading.Thread):
  """
  This thread is where all of the work will be performed in actually making the
  function calls for Apply. It takes care of all error handling, return value
  propagation, and shared_vars.

  Note that this thread is NOT started upon instantiation because the function-
  calling logic is also used in the single-threaded case.
  """
  def __init__(self, task_queue, multiprocessing_is_available=True):
    """
    Args:
      task_queue: The thread-safe queue from which this thread should obtain
                  its work.
      multiprocessing_is_available: False iff the multiprocessing module is not
                                    available, in which case we're using
                                    _SequentialApply.
    """
    super(WorkerThread, self).__init__()
    self.task_queue = task_queue
    self.multiprocessing_is_available = multiprocessing_is_available
    self.daemon = True
    self.cached_classes = {}
    self.shared_vars_updater = _SharedVariablesUpdater()

  def PerformTask(self, task, cls):
    """
    Makes the function call for a task.

    Args:
      task: The Task to perform.
      cls: The instance of a class which gives context to the functions called
           by the Task's function. E.g., see _SetAclFuncWrapper.
    """
    caller_id = task.caller_id
    try:
      results = task.func(cls, task.args)
      if task.should_return_results:
        global_return_values_map.update(caller_id, [results], default_value=[])
    except Exception, e:
      if task.fail_on_error:
        raise  # Only happens for single thread and process case.
      else:
        try:
          task.exception_handler(cls, e)
        except Exception, e1:
          # Don't allow callers to throw exceptions here and kill the worker
          # threads.
          cls.logger.debug(
              'Caught exception while handling exception for %s:\n%s',
              task, traceback.format_exc())
    finally:
      self.shared_vars_updater.Update(caller_id, cls)

    # Even if we encounter an exception, we still need to claim that that
    # the function finished executing. Otherwise, we won't know when to
    # stop waiting and return results.
    num_done = caller_id_finished_count.update(caller_id, 1)
    if self.multiprocessing_is_available:
      _NotifyIfDone(caller_id, num_done)

  def run(self):
    while True:
      task = self.task_queue.get()
      caller_id = task.caller_id

      # Get the instance of the command with the appropriate context.
      cls = self.cached_classes.get(caller_id, None)
      if not cls:
        cls = copy.copy(class_map[caller_id])
        cls.logger = CreateGsutilLogger(cls.command_name)
        self.cached_classes[caller_id] = cls

      self.PerformTask(task, cls)


class _SharedVariablesUpdater(object):
  """Used to update shared variable for a class in the global map. Note that
     each thread will have its own instance of the calling class for context,
     and it will also have its own instance of a _SharedVariablesUpdater.
     This is used in the following way:

     1. Before any tasks are performed, each thread will get a copy of the
        calling class, and the globally-consistent value of this shared variable
        will be initialized to whatever it was before the call to Apply began.

     2. After each time a thread performs a task, it will look at the current
        values of the shared variables in its instance of the calling class.

        2.A. For each such variable, it computes the delta of this variable
             between the last known value for this class (which is stored in
             a dict local to this class) and the current value of the variable
             in the class.

        2.B. Using this delta, we update the last known value locally as well
             as the globally-consistent value shared across all classes (the
             globally consistent value is simply increased by the computed
             delta).
    """
  def __init__(self):
    self.last_shared_var_values = {}

  def Update(self, caller_id, cls):
    """Update any shared variables with their deltas."""
    shared_vars = shared_vars_list_map.get(caller_id, None)
    if shared_vars:
      for name in shared_vars:
        key = (caller_id, name)
        last_value = self.last_shared_var_values.get(key, 0)
        # Compute the change made since the last time we updated here. This is
        # calculated by simply subtracting the last known value from the current
        # value in the class instance.
        delta = getattr(cls, name) - last_value
        self.last_shared_var_values[key] = delta + last_value

        # Update the globally-consistent value by simply increasing it by the
        # computed delta.
        shared_vars_map.update(key, delta)


def _NotifyIfDone(caller_id, num_done):
  """
  Notify any threads that are waiting for results that something has finished.
  Each waiting thread will then need to check the call_completed_map to see if
  its work is done.
  
  Note that num_done could be calculated here, but it is passed in as an
  optimization so that we have one less call to a globally-locked data
  structure.
  
  Args:
    caller_id: The caller_id of the function whose progress we're checking.
    num_done: The number of tasks currently completed for that caller_id.
  """
  num_to_do = total_tasks[caller_id]
  if num_to_do == num_done and num_to_do >= 0:
    # Notify the Apply call that's sleeping that it's ready to return.
    with need_pool_or_done_cond:
      call_completed_map[caller_id] = True
      need_pool_or_done_cond.notify_all()

def ShutDownGsutil():
  """Shut down all processes in consumer pools in preparation for exiting."""
  for q in queues:
    try:
      q.cancel_join_thread()
    except:
      pass
  for consumer_pool in consumer_pools:
    consumer_pool.ShutDown()

