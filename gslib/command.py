# Copyright 2010 Google Inc.
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
class state (such as GetAclCommandHelper, which depends on self.gsutil_bin_dir,
self.bucket_storage_uri_class, etc.) In general, functions that depend on class
state and that are used by multiple commands belong in this file. Functions that
don't depend on class state belong in util.py, and non-shared helpers belong in
individual subclasses.
"""

import boto
import getopt
import gslib
import logging
import multiprocessing
import os
import platform
import re
import sys
import wildcard_iterator
import xml.dom.minidom
import xml.sax.xmlreader

from boto import handler
from boto.storage_uri import StorageUri
from exception import CommandException
from getopt import GetoptError
from gslib import util
from gslib.project_id import ProjectIdHandler
from gslib.thread_pool import ThreadPool
from gslib.thread_pool import Worker
from gslib.util import HAVE_OAUTH2
from gslib.util import NO_MAX
from gslib.wildcard_iterator import ResultType

def _ThreadedLogger():
  """Creates a logger that resembles 'print' output, but is thread safe.

  The logger will display all messages logged with level INFO or above. Log
  propagation is disabled.

  Returns:
    A logger object.
  """
  log = logging.getLogger('threaded-logging')
  log.propagate = False
  log.setLevel(logging.INFO)
  log_handler = logging.StreamHandler()
  log_handler.setFormatter(logging.Formatter('%(message)s'))
  log.addHandler(log_handler)
  return log

# command_spec key constants.
COMMAND_NAME = 'command_name'
COMMAND_NAME_ALIASES = 'command_name_aliases'
MIN_ARGS = 'min_args'
MAX_ARGS = 'max_args'
SUPPORTED_SUB_ARGS = 'supported_sub_args'
FILE_URIS_OK = 'file_uri_ok'
PROVIDER_URIS_OK = 'provider_uri_ok'
URIS_START_ARG = 'uris_start_arg'
CONFIG_REQUIRED = 'config_required'

class Command(object):
  # Global instance of a threaded logger object.
  THREADED_LOGGER = _ThreadedLogger()

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
    # True if must configure gsutil before running command.
    CONFIG_REQUIRED : True,
  }
  _default_command_spec = command_spec

  # Define a convenience property for command name, since it's used many places.
  def _get_command_name(self):
    return self.command_spec[COMMAND_NAME]
  command_name = property(_get_command_name)

  def __init__(self, command_runner, args, headers, debug, parallel_operations,
               gsutil_bin_dir, boto_lib_dir, config_file_list,
               bucket_storage_uri_class, test_method=None):
    """
    Args:
      command_runner: CommandRunner (for commands built atop other commands).
      args: command-line args (arg0 = actual arg, not command name ala bash).
      headers: dictionary containing optional HTTP headers to pass to boto.
      debug: debug level to pass in to boto connection (range 0..3).
      parallel_operations: Should command operations be executed in parallel?
      gsutil_bin_dir: bin dir from which gsutil is running.
      boto_lib_dir: lib dir where boto runs.
      config_file_list: config file list returned by _GetBotoConfigFileList().
      bucket_storage_uri_class: Class to instantiate for cloud StorageUris.
                                Settable for testing/mocking.
      test_method: Optional general purpose method for testing purposes. 
                   Application and semantics of this method will vary by
                   command and test type. 
    """
    
    # Save class values from constructor params.
    self.command_runner = command_runner
    self.args = args
    self.headers = headers
    self.debug = debug
    self.parallel_operations = parallel_operations
    self.gsutil_bin_dir = gsutil_bin_dir
    self.boto_lib_dir = boto_lib_dir
    self.config_file_list = config_file_list
    self.bucket_storage_uri_class = bucket_storage_uri_class
    self.test_method = test_method
    self.ignore_symlinks = False
    
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

    # Parse and validate args.
    try:
      (self.sub_opts, self.args) = getopt.getopt(
          args, self.command_spec[SUPPORTED_SUB_ARGS])
    except GetoptError, e:
      raise CommandException('%s for "%s" command.' % (e.msg,
                                                       self.command_name))
    if (len(self.args) < self.command_spec[MIN_ARGS] or
        len(self.args) > self.command_spec[MAX_ARGS]):
      raise CommandException('Wrong number of arguments for "%s" command.' %
                             self.command_name)
    if (not self.command_spec[FILE_URIS_OK] and
        self._HaveFileUris(self.args[self.command_spec[URIS_START_ARG]:])):
      raise CommandException('"%s" command does not support "file://" URIs. '
                             'Did you mean to use a gs:// URI?' %
                             self.command_name)
    if (not self.command_spec[PROVIDER_URIS_OK] and
        self._HaveProviderUris(self.args[self.command_spec[URIS_START_ARG]:])):
      raise CommandException('"%s" command does not support provider-only '
                             'URIs.' % self.command_name)
    if self.command_spec[CONFIG_REQUIRED]:
      self._ConfigureNoOpAuthIfNeeded()

    self.proj_id_handler = ProjectIdHandler()

  def RunCommand(self):
    """Abstract function in base class. Subclasses must implement this."""
    raise CommandException('Command %s is missing its RunCommand() '
                           'implementation' % self.command_name)

  ############################################################
  # Shared helper functions that depend on base class state. #
  ############################################################

  def StorageUri(self, uri_str):
    """
    Helper to instantiate boto.StorageUri with gsutil default flag values.
    Uses self.bucket_storage_uri_class to support mocking/testing.

    Args:
      uri_str: StorageUri naming bucket + optional object.

    Returns:
      boto.StorageUri for given uri_str.

    Raises:
      InvalidUriError: if uri_str not valid.
    """
    return boto.storage_uri(
        uri_str, 'file', debug=self.debug, validate=False,
        bucket_storage_uri_class=self.bucket_storage_uri_class)

  def CmdWildcardIterator(self, uri_or_str, result_type=ResultType.URIS):
    """
    Helper to instantiate gslib.WildcardIterator, passing
    self.bucket_storage_uri_class to support mocking/testing.
    Args are same as gslib.WildcardIterator interface, but filling in most
    of the values from Command instance state).
    """
    return wildcard_iterator.wildcard_iterator(
        uri_or_str, self.proj_id_handler, result_type=result_type,
        bucket_storage_uri_class=self.bucket_storage_uri_class,
        headers=self.headers, debug=self.debug)

  def InsistUriNamesContainer(self, uri, command_name,
                              msg='Destination URI must name a bucket or '
                                  'directory for the\nmultiple source form of '
                                  'the %s command.'):
    """Checks that URI names a directory or bucket.

    Args:
      uri: StorageUri to check
      command_name: name of command making call. May not be the same as
          self.command_name in the case of commands implemented atop other
          commands (like mv command).
      msg: message to print on error, containing one '%s' to be replaced by
          command_name.

    Raises:
      CommandException: if errors encountered.
    """
    if uri.names_singleton():
      raise CommandException(msg % command_name)

  def UrisAreForSingleProvider(self, uri_args):
    """Tests whether the uris are all for a single provider.

    Returns a StorageUri for one of the uris on success, None on failure.
    """
    provider = None
    uri = None
    for uri_str in uri_args:
      # validate=False because we allow wildcard uris.
      uri = boto.storage_uri(uri_str, debug=self.debug, validate=False,
          bucket_storage_uri_class=self.bucket_storage_uri_class)
      if not provider:
        provider = uri.scheme
      elif uri.scheme != provider:
        return None
    return uri

  def SetAclCommandHelper(self):
    """Common logic for setting ACLs. Sets the standard ACL or the default
    object ACL depending on self.command_name."""
    acl_arg = self.args[0]
    uri_args = self.args[1:]
    # Disallow multi-provider setacl requests, because there are differences in
    # the ACL models.
    storage_uri = self.UrisAreForSingleProvider(uri_args)
    if not storage_uri:
      raise CommandException('"%s" command spanning providers not allowed.' %
                             self.command_name)

    # Get ACL object from connection for one URI, for interpreting the ACL.
    # This won't fail because the main startup code insists on at least 1 arg
    # for this command.
    acl_class = storage_uri.acl_class()
    canned_acls = storage_uri.canned_acls()

    # Determine whether acl_arg names a file containing XML ACL text vs. the
    # string name of a canned ACL.
    if os.path.isfile(acl_arg):
      acl_file = open(acl_arg, 'r')
      acl_txt = acl_file.read()
      acl_file.close()
      acl_obj = acl_class()
      h = handler.XmlHandler(acl_obj, storage_uri.get_bucket())
      try:
        xml.sax.parseString(acl_txt, h)
      except xml.sax._exceptions.SAXParseException, e:
        raise CommandException('Requested ACL is invalid: %s at line %s, '
                               'column %s' % (e.getMessage(), e.getLineNumber(),
                                              e.getColumnNumber()))
      acl_arg = acl_obj
    else:
      # No file exists, so expect a canned ACL string.
      if acl_arg not in canned_acls:
        raise CommandException('Invalid canned ACL "%s".' % acl_arg)

    # Now iterate over URIs and set the ACL on each.
    for uri_str in uri_args:
      for uri in self.CmdWildcardIterator(uri_str):
        if self.command_name == 'setdefacl':
          print 'Setting default object ACL on %s...' % uri
          uri.set_def_acl(acl_arg, uri.object_name, False, self.headers)
        else:
          print 'Setting ACL on %s...' % uri
          uri.set_acl(acl_arg, uri.object_name, False, self.headers)

  def GetAclCommandHelper(self):
    """Common logic for getting ACLs. Gets the standard ACL or the default
    object ACL depending on self.command_name."""
    # Wildcarding is allowed but must resolve to just one object.
    uris = list(self.CmdWildcardIterator(self.args[0]))
    if len(uris) != 1:
      raise CommandException('Wildcards must resolve to exactly one object for '
                             '"%s" command.' % self.command_name)
    uri = uris[0]
    if not uri.bucket_name:
      raise CommandException('"%s" command must specify a bucket or '
                             'object.' % self.command_name)
    if self.command_name == 'getdefacl':
      acl = uri.get_def_acl(False, self.headers)
    else:
      acl = uri.get_acl(False, self.headers)
    # Pretty-print the XML to make it more easily human editable.
    parsed_xml = xml.dom.minidom.parseString(acl.to_xml().encode('utf-8'))
    print parsed_xml.toprettyxml(indent='    ')

  def GetXmlSubresource(self, subresource, uri_arg):
    """Print an xml subresource, e.g. logging, for a bucket/object.

    Args:
      subresource: the subresource name
      uri_arg: uri for the bucket/object.  Wildcards will be expanded.

    Raises:
      CommandException: if errors encountered.
    """
    # Wildcarding is allowed but must resolve to just one bucket.
    uris = list(self.CmdWildcardIterator(uri_arg))
    if len(uris) != 1:
      raise CommandException('Wildcards must resolve to exactly one item for '
                             'get %s' % subresource)
    uri = uris[0]
    xml_str = uri.get_subresource(subresource, False, self.headers)
    # Pretty-print the XML to make it more easily human editable.
    parsed_xml = xml.dom.minidom.parseString(xml_str.encode('utf-8'))
    print parsed_xml.toprettyxml(indent='    ')

  def LoadVersionString(self):
    """Loads version string for currently installed gsutil command.

    Returns:
      Version string.

    Raises:
      CommandException: if errors encountered.
    """
    ver_file_path = self.gsutil_bin_dir + os.sep + 'VERSION'
    if not os.path.isfile(ver_file_path):
      raise CommandException(
          '%s not found. Did you install the\ncomplete gsutil software after '
          'the gsutil "update" command was implemented?' % ver_file_path)
    ver_file = open(ver_file_path, 'r')
    installed_version_string = ver_file.read().rstrip('\n')
    ver_file.close()
    return installed_version_string

  ######################
  # Private functions. #
  ######################

  def _HaveFileUris(self, args_to_check):
    """Checks whether args_to_check contain any file URIs.

    Args:
      args_to_check: command-line argument subset to check

    Returns:
      True if args_to_check contains any file URIs.
    """
    for uri_str in args_to_check:
      if uri_str.lower().startswith('file://') or uri_str.find(':') == -1:
        return True
    return False

  def _HaveProviderUris(self, args_to_check):
    """Checks whether args_to_check contains any provider URIs (like 'gs://').

    Args:
      args_to_check: command-line argument subset to check

    Returns:
      True if args_to_check contains any provider URIs.
    """
    for uri_str in args_to_check:
      if re.match('^[a-z]+://$', uri_str):
        return True
    return False

  def _ConfigureNoOpAuthIfNeeded(self):
    """Sets up no-op auth handler if no boto credentials are configured."""
    config = boto.config
    if not util.HasConfiguredCredentials():
      if self.config_file_list:
        if (config.has_option('Credentials', 'gs_oauth2_refresh_token')
            and not HAVE_OAUTH2):
          raise CommandException(
              "Your gsutil is configured with OAuth2 authentication "
              "credentials.\nHowever, OAuth2 is only supported when running "
              "under Python 2.6 or later\n(unless additional dependencies are "
              "installed, see README for details); you are running Python %s." %
              sys.version)
        raise CommandException('You have no storage service credentials in any '
                               'of the following boto config\nfiles. Please '
                               'add your credentials as described in the '
                               'gsutil README file, or else\nre-run '
                               '"gsutil config" to re-create a config '
                               'file:\n%s' % self.config_file_list)
      else:
        # With no boto config file the user can still access publicly readable
        # buckets and objects.
        from gslib import no_op_auth_plugin

  def Apply(self, func, src_uri_expansion, thr_exc_handler):    
    """Dispatch input URI assignments across a pool of parallel OS
       processes and/or Python threads, based on options (-m or not) 
       and settings in the user's config file. If non-parallel mode 
       or only one OS process requested, execute requests sequentially 
       in the current OS process. 

    Args:
      func: function to call to process each URI.
      src_uri_expansion: dictionary of groups of URIs to process.
      thr_exc_handler: exception handler for ThreadPool class.
    """
    # Set OS process and python thread count as a function of options 
    # and config.
    if self.parallel_operations:
      process_count = boto.config.getint(
          'GSUtil', 'parallel_process_count',
          gslib.commands.config.DEFAULT_PARALLEL_PROCESS_COUNT)
      if process_count < 1:
        raise CommandException('Invalid parallel_process_count "%d".' % 
                               process_count)
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

    if self.debug:
      self.THREADED_LOGGER.info('process count: %d', process_count)
      self.THREADED_LOGGER.info('thread count: %d', thread_count)

    # Construct dictionary of assigned URIs containing one list per 
    # OS process/shard. Assignments are stored as tuples containing 
    # original source URI and expanded source URI.
    shard = 0
    assigned_uris = {}
    for src_uri in iter(src_uri_expansion):
      for exp_src_uri in src_uri_expansion[src_uri]:
        if shard not in assigned_uris:
          assigned_uris[shard] = []
        assigned_uris[shard].append((src_uri, exp_src_uri))
        shard = (shard + 1) % process_count

    if self.parallel_operations and (process_count > 1):
      procs = []
      byte_count = None
      # If the command calling this method keeps track of bytes transferred,
      # arrange to manage a global count across multiple OS processes.
      # TODO: The logic that manages the global byte_count is specific 
      # to the cp command and should be refactored to be generic.
      if hasattr(self, 'total_bytes_transferred'):
        byte_count = multiprocessing.Value('i', 0)
      for shard in assigned_uris:
        # Spawn a separate OS process for each shard.
        if self.debug:
          self.THREADED_LOGGER.info('spawning process for shard %d', shard)
        p = multiprocessing.Process(target=self.ApplyThreads,
              args=(func, assigned_uris[shard], shard, thread_count, 
              byte_count, thr_exc_handler))
        procs.append(p)
        p.start()
      # Wait for all spawned OS processes to finish.
      for p in procs:
        p.join()
      # If tracking bytes processed, update the master process' count from 
      # the global counter. 
      if hasattr(self, 'total_bytes_transferred'):
        self.total_bytes_transferred = byte_count.value
    else:
      # Only one OS process requested so perform request in current
      # OS process, in shard zero with thread_count threads.
      self.ApplyThreads(func, assigned_uris[0], 0, thread_count, None, 
                        thr_exc_handler)

  def ApplyThreads(self, func, assigned_uris, shard, num_threads, 
                       count=None, thr_exc_handler=None):
    """Perform subset of required requests across a caller specified 
       number of parallel Python threads, which may be one, in which
       case the requests are processed in the current thread. 
    
    Args:
      func: function to call for each request.
      assigned_uris: list of URIs to process.
      shard: assigned subset (shard number) for this function.
      num_threads: number of Python threads to spawn to process this shard.
      count: shared integer for tracking total bytes transferred.
             (only relevant, and non-None, if this function is
             run in a separate OS process)
      thr_exc_handler: exception handler for ThreadPool class.
    """ 
    # Each OS process needs to establish its own set of connections to
    # the server to avoid writes from different OS processes interleaving
    # onto the same socket (and messing up the underlying SSL session). 
    # We ensure each process gets its own set of connections here by 
    # closing all connections in the storage provider connection pool. 
    connection_pool = StorageUri.provider_pool
    if connection_pool:
      for i in connection_pool:
        connection_pool[i].connection.close()

    if num_threads > 1:
      thread_pool = ThreadPool(num_threads, thr_exc_handler)
    try:
      # Iterate over assigned URIs and perform copy operations for each.
      for (src_uri, exp_src_uri) in assigned_uris:
        if self.debug:
          self.THREADED_LOGGER.info('process %d shard %d is handling uri %s', 
                                    os.getpid(), shard, exp_src_uri)
        if (self.ignore_symlinks and exp_src_uri.is_file_uri()
            and os.path.islink(exp_src_uri.object_name)):
          self.THREADED_LOGGER.info('Skipping symbolic link %s...',
                                    exp_src_uri)
        elif num_threads > 1:
          thread_pool.AddTask(func, src_uri, exp_src_uri)
        else:
          func(src_uri, exp_src_uri)
      # If any Python threads created, wait here for them to finish.
      if num_threads > 1:
        thread_pool.WaitCompletion()
    finally:
      if num_threads > 1:
        thread_pool.Shutdown()
    # If this call was spawned in a separate OS process, update shared
    # memory count of bytes transferred.
    if count:
      count.value += self.total_bytes_transferred
