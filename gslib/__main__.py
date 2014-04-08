#!/usr/bin/env python
# coding=utf8
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
"""Main module for Google Cloud Storage command line tool."""

import ConfigParser
import errno
import getopt
import logging
import os
import pkgutil
import re
import signal
import socket
import sys
import tempfile
import textwrap
import traceback

# Load the gsutil version number and append it to boto.UserAgent so the value is
# set before anything instantiates boto. This has to run after THIRD_PARTY_DIR
# is modified (done in gsutil.py) but before any calls are made that would cause
# boto.s3.Connection to be loaded - otherwise the Connection class would end up
# with a static reference to the pre-modified version of the UserAgent field,
# so boto requests would not include gsutil/version# in the UserAgent string.
import boto
import gslib
# TODO: gsutil-beta: Cloud SDK scans for this string and performs
# substitution; ensure this works with both apitools and boto.
boto.UserAgent += ' gsutil/%s (%s)' % (gslib.VERSION, sys.platform)

# pylint: disable=g-bad-import-order
# pylint: disable=g-import-not-at-top
import httplib2
import oauth2client
from gslib import wildcard_iterator
from gslib.cloud_api import AccessDeniedException
from gslib.cloud_api import ArgumentException
from gslib.cloud_api import BadRequestException
from gslib.cloud_api import ProjectIdException
from gslib.cloud_api import ServiceException
from gslib.command_runner import CommandRunner
import gslib.exception
from gslib.exception import CommandException
import gslib.third_party.storage_apitools.exceptions as apitools_exceptions
from gslib.util import CreateLock

GSUTIL_CLIENT_ID = '909320924072.apps.googleusercontent.com'
# Google OAuth2 clients always have a secret, even if the client is an installed
# application/utility such as gsutil.  Of course, in such cases the "secret" is
# actually publicly known; security depends entirely on the secrecy of refresh  
# tokens, which effectively become bearer tokens.  
GSUTIL_CLIENT_NOTSOSECRET = 'p3RlpR10xMFh9ZXBS/ZNLYUu'

# We don't use the oauth2 authentication plugin directly; importing it here
# ensures that it's loaded and available by default when an operation requiring
# authentication is performed.
try:
  # pylint: disable=unused-import,g-import-not-at-top
  import oauth2_plugin
except ImportError:
  pass

DEBUG_WARNING = """
***************************** WARNING *****************************
*** You are running gsutil with debug output enabled.
*** Be aware that debug output includes authentication credentials.
*** Make sure to remove the value of the Authorization header for
*** each HTTP request printed to the console prior to posting to
*** a public medium such as a forum post or Stack Overflow.
***************************** WARNING *****************************
""".lstrip()

HTTP_WARNING = """
***************************** WARNING *****************************
*** You are running gsutil with the "https_validate_certificates" config
*** variable set to False. This option should always be set to True in
*** production environments to protect against man-in-the-middle attacks,
*** and leaking of user data.
***************************** WARNING *****************************
""".lstrip()

debug = 0
test_exception_traces = False

# Temp files to delete, if possible, when program exits.
cleanup_files = []


def _Cleanup():
  for fname in cleanup_files:
    try:
      os.remove(fname)
    except OSError:
      pass


def _OutputAndExit(message):
  """Outputs message and exists with code 1."""
  from gslib.util import UTF8  # pylint: disable=g-import-not-at-top
  if debug >= 2 or test_exception_traces:
    stack_trace = traceback.format_exc()
    err = ('DEBUG: Exception stack trace:\n    %s\n' %
           re.sub('\\n', '\n    ', stack_trace))
  else:
    err = '%s\n' % message
  sys.stderr.write(err.encode(UTF8))
  sys.exit(1)


def _OutputUsageAndExit(command_runner):
  command_runner.RunNamedCommand('help')
  sys.exit(1)


def _ConfigureLogging(level=logging.INFO):
  """Similar to logging.basicConfig() except it always adds a handler."""
  handler = logging.StreamHandler()
  root_logger = logging.getLogger()
  root_logger.addHandler(handler)
  root_logger.setLevel(level)


def main():
  # These modules must be imported after importing gslib.__main__.
  # pylint: disable=redefined-outer-name,g-import-not-at-top
  import gslib.command
  import gslib.util
  from gslib.util import BOTO_IS_SECURE
  from gslib.util import CERTIFICATE_VALIDATION_ENABLED
  from gslib.util import GetBotoConfigFileList
  from oauth2_plugin import oauth2_client
  from gslib.util import MultiprocessingIsAvailable
  if MultiprocessingIsAvailable()[0]:
    # These setup methods must be called, and, on Windows, they can only be
    # called from within an "if __name__ == '__main__':" block.
    gslib.util.InitializeMultiprocessingVariables()
    gslib.command.InitializeMultiprocessingVariables()

  # This needs to be done after gslib.util.InitializeMultiprocessingVariables(),
  # since otherwise we can't call gslib.util.CreateLock.
  try:
    # pylint: disable=unused-import,g-import-not-at-top
    import oauth2_plugin
    oauth2_plugin.SetFallbackClientIdAndSecret(
        GSUTIL_CLIENT_ID, GSUTIL_CLIENT_NOTSOSECRET)
    oauth2_plugin.SetLock(CreateLock())
  except ImportError:
    pass

  global debug
  global test_exception_traces

  if not (2, 6) <= sys.version_info[:3] < (3,):
    raise gslib.exception.CommandException(
        'gsutil requires python 2.6 or 2.7.')

  if not BOTO_IS_SECURE:
    raise CommandException('\n'.join(textwrap.wrap(
        'Your boto configuration has is_secure = False. Gsutil cannot be '
        'run this way, for security reasons.')))

  # In gsutil 4.0 and beyond, we don't use the boto library for the JSON
  # API. However, we still store gsutil configuration data in the .boto
  # config file for compatibility with previous versions and user convenience.
  # Many users have a .boto configuration file from previous versions, and it
  # is useful to have all of the configuration for gsutil stored in one place.
  config_file_list = GetBotoConfigFileList()
  command_runner = CommandRunner(config_file_list)
  headers = {}
  parallel_operations = False
  quiet = False
  version = False
  debug = 0
  test_exception_traces = False

  # If user enters no commands just print the usage info.
  if len(sys.argv) == 1:
    sys.argv.append('help')

  # Change the default of the 'https_validate_certificates' boto option to
  # True (it is currently False in boto).
  if not boto.config.has_option('Boto', 'https_validate_certificates'):
    if not boto.config.has_section('Boto'):
      boto.config.add_section('Boto')
    boto.config.setbool('Boto', 'https_validate_certificates', True)

  # If ca_certificates_file is configured use it; otherwise configure boto to
  # use the cert roots distributed with gsutil.
  if not boto.config.get_value('Boto', 'ca_certificates_file', None):
    disk_certs_file = os.path.abspath(
        os.path.join(gslib.GSLIB_DIR, 'data', 'cacerts.txt'))
    if not os.path.exists(disk_certs_file):
      # If the file is not present on disk, this means the gslib module doesn't
      # actually exist on disk anywhere. This can happen if it's being imported
      # from a zip file. Unfortunately, we have to copy the certs file to a
      # local temp file on disk because the underlying SSL socket requires it
      # to be a filesystem path.
      certs_data = pkgutil.get_data('gslib', 'data/cacerts.txt')
      if not certs_data:
        raise gslib.exception.CommandException(
            'Certificates file not found. Please reinstall gsutil from scratch')
      fd, fname = tempfile.mkstemp(suffix='.txt', prefix='gsutil-cacerts')
      f = os.fdopen(fd, 'w')
      f.write(certs_data)
      f.close()
      disk_certs_file = fname
      cleanup_files.append(disk_certs_file)
    boto.config.set('Boto', 'ca_certificates_file', disk_certs_file)

  try:
    try:
      opts, args = getopt.getopt(sys.argv[1:], 'dDvo:h:mq',
                                 ['debug', 'detailedDebug', 'version', 'option',
                                  'help', 'header', 'multithreaded', 'quiet',
                                  'testexceptiontraces'])
    except getopt.GetoptError as e:
      _HandleCommandException(gslib.exception.CommandException(e.msg))
    for o, a in opts:
      if o in ('-d', '--debug'):
        # Passing debug=2 causes boto to include httplib header output.
        debug = 3
      elif o in ('-D', '--detailedDebug'):
        # We use debug level 3 to ask gsutil code to output more detailed
        # debug output. This is a bit of a hack since it overloads the same
        # flag that was originally implemented for boto use. And we use -DD
        # to ask for really detailed debugging (i.e., including HTTP payload).
        if debug == 3:
          debug = 4
        else:
          debug = 3
      elif o in ('-?', '--help'):
        _OutputUsageAndExit(command_runner)
      elif o in ('-h', '--header'):
        (hdr_name, _, hdr_val) = a.partition(':')
        if not hdr_name:
          _OutputUsageAndExit(command_runner)
        headers[hdr_name.lower()] = hdr_val
      elif o in ('-m', '--multithreaded'):
        parallel_operations = True
      elif o in ('-q', '--quiet'):
        quiet = True
      elif o in ('-v', '--version'):
        version = True
      elif o == '--testexceptiontraces':  # Hidden flag for integration tests.
        test_exception_traces = True
      elif o in ('-o', '--option'):
        (opt_section_name, _, opt_value) = a.partition('=')
        if not opt_section_name:
          _OutputUsageAndExit(command_runner)
        (opt_section, _, opt_name) = opt_section_name.partition(':')
        if not opt_section or not opt_name:
          _OutputUsageAndExit(command_runner)
        if not boto.config.has_section(opt_section):
          boto.config.add_section(opt_section)
        boto.config.set(opt_section, opt_name, opt_value)
    httplib2.debuglevel = debug
    if debug > 1:
      sys.stderr.write(DEBUG_WARNING)
    if debug >= 2:
      _ConfigureLogging(level=logging.DEBUG)
      command_runner.RunNamedCommand('ver', ['-l'])
      config_items = []
      try:
        config_items.extend(boto.config.items('Boto'))
        config_items.extend(boto.config.items('GSUtil'))
      except ConfigParser.NoSectionError:
        pass
      sys.stderr.write('config_file_list: %s\n' % config_file_list)
      sys.stderr.write('config: %s\n' % str(config_items))
    elif quiet:
      _ConfigureLogging(level=logging.WARNING)
    else:
      _ConfigureLogging(level=logging.INFO)
      # apiclient and oauth2client use info logging in places that would better
      # correspond to gsutil's debug logging (e.g., when refreshing access
      # tokens).
      oauth2client.client.logger.setLevel(logging.WARNING)

    if not CERTIFICATE_VALIDATION_ENABLED:
      sys.stderr.write(HTTP_WARNING)

    if version:
      command_name = 'version'
    elif not args:
      command_name = 'help'
    else:
      command_name = args[0]

    # Unset http_proxy environment variable if it's set, because it confuses
    # boto. (Proxies should instead be configured via the boto config file.)
    if 'http_proxy' in os.environ:
      if debug > 1:
        sys.stderr.write(
            'Unsetting http_proxy environment variable within gsutil run.\n')
      del os.environ['http_proxy']

    return _RunNamedCommandAndHandleExceptions(
        command_runner, command_name, args=args[1:], headers=headers,
        debug_level=debug, parallel_operations=parallel_operations)
  finally:
    _Cleanup()


def _HandleUnknownFailure(e):
  # Called if we fall through all known/handled exceptions. Allows us to
  # print a stacktrace if -D option used.
  if debug >= 2:
    stack_trace = traceback.format_exc()
    sys.stderr.write('DEBUG: Exception stack trace:\n    %s\n' %
                     re.sub('\\n', '\n    ', stack_trace))
  else:
    _OutputAndExit('Failure: %s.' % e)


def _HandleCommandException(e):
  if e.informational:
    _OutputAndExit(e.reason)
  else:
    _OutputAndExit('CommandException: %s' % e.reason)


# pylint: disable=unused-argument
def _HandleControlC(signal_num, cur_stack_frame):
  """Called when user hits ^C.

  This function prints a brief message instead of the normal Python stack trace
  (unless -D option is used).

  Args:
    signal_num: Signal that was caught.
    cur_stack_frame: Unused.
  """
  if debug >= 2:
    stack_trace = ''.join(traceback.format_list(traceback.extract_stack()))
    _OutputAndExit(
        'DEBUG: Caught signal %d - Exception stack trace:\n'
        '    %s' % (signal_num, re.sub('\\n', '\n    ', stack_trace)))
  else:
    _OutputAndExit('Caught signal %d - exiting' % signal_num)


def _HandleSigQuit(signal_num, cur_stack_frame):
  """Called when user hits ^\\, so we can force breakpoint a running gsutil."""
  import pdb  # pylint: disable=g-import-not-at-top
  pdb.set_trace()


def _ConstructAccountProblemHelp(reason):
  """Constructs a help string for an access control error.

  Args:
    reason: e.reason string from caught exception.

  Returns:
    Contructed help text.
  """
  default_project_id = boto.config.get_value('GSUtil', 'default_project_id')
  # pylint: disable=line-too-long, g-inconsistent-quotes
  if 'Account disabled' in reason or 'AccountProblem' in reason:
    acct_help = "Your request resulted in an Account disabled error. "
  else:
    # Assume problem was 'AccountProblem'.
    acct_help = (
        "Your request resulted in an AccountProblem (403) error. Usually this "
        "happens if you attempt to create a bucket without first having "
        "enabled billing for the project you are using. ")
  acct_help += (
      "Please ensure billing is enabled for your project by following the "
      "instructions at "
      "`Google Developers Console<https://developers.google.com/console/help/billing>`. ")
  if default_project_id:
    acct_help += (
        "In the project overview, ensure that the Project Number listed for "
        "your project matches the project ID (%s) from your boto config file. "
        % default_project_id)
  acct_help += (
      "If the above doesn't resolve your AccountProblem, please send mail to "
      "gs-team@google.com requesting assistance, noting the exact command you "
      "ran, the fact that you received a 403 AccountProblem error, and your "
      "project ID. Please do not post your project ID on StackOverflow. "
      "Note: It's possible to use Google Cloud Storage without enabling "
      "billing if you're only listing or reading objects for which you're "
      "authorized, or if you're uploading objects to a bucket billed to a "
      "project that has billing enabled. But if you're attempting to create "
      "buckets or upload objects to a bucket owned by your own project, you "
      "must first enable billing for that project.")
  return acct_help


def _CheckAndHandleCredentialException(e, args):
  # Provide detail to users who have no boto config file (who might previously
  # have been using gsutil only for accessing publicly readable buckets and
  # objects).
  # pylint: disable=g-import-not-at-top
  from gslib.util import HasConfiguredCredentials
  if (not HasConfiguredCredentials() and
      not boto.config.get_value('Tests', 'bypass_anonymous_access_warning',
                                False)):
    # The check above allows tests to assert that we get a particular,
    # expected failure, rather than always encountering this error message
    # when there are no configured credentials. This allows tests to
    # simulate a second user without permissions, without actually requiring
    # two separate configured users.
    _OutputAndExit('\n'.join(textwrap.wrap(
        'You are attempting to access protected data with no configured '
        'credentials. Please visit '
        'https://cloud.google.com/console#/project and sign up for an '
        'account, and then run the "gsutil config" command to configure '
        'gsutil to use these credentials.')))
  elif ((e.reason == 'AccountProblem' or e.reason == 'Account disabled.')
        and ','.join(args).find('gs://') != -1):
    _OutputAndExit('\n'.join(textwrap.wrap(
        _ConstructAccountProblemHelp(e.reason))))


def _RunNamedCommandAndHandleExceptions(command_runner, command_name, args=None,
                                        headers=None, debug_level=0,
                                        parallel_operations=False):
  """Runs the command with the given command runner and arguments."""
  # pylint: disable=g-import-not-at-top
  from gslib.util import GetConfigFilePath
  from gslib.util import IS_WINDOWS
  from gslib.util import IsRunningInteractively
  try:
    # Catch ^C so we can print a brief message instead of the normal Python
    # stack trace.
    signal.signal(signal.SIGINT, _HandleControlC)
    # Catch ^\ so we can force a breakpoint in a running gsutil.
    if not IS_WINDOWS:
      signal.signal(signal.SIGQUIT, _HandleSigQuit)
    return command_runner.RunNamedCommand(command_name, args, headers,
                                          debug_level, parallel_operations)
  except AttributeError as e:
    if str(e).find('secret_access_key') != -1:
      _OutputAndExit('Missing credentials for the given URI(s). Does your '
                     'boto config file contain all needed credentials?')
    else:
      _OutputAndExit(str(e))
  except gslib.exception.CommandException as e:
    _HandleCommandException(e)
  except getopt.GetoptError as e:
    _HandleCommandException(gslib.exception.CommandException(e.msg))
  except boto.exception.InvalidUriError as e:
    _OutputAndExit('InvalidUriError: %s.' % e.message)
  except gslib.exception.InvalidUrlError as e:
    _OutputAndExit('InvalidUrlError: %s.' % e.message)
  except boto.auth_handler.NotReadyToAuthenticate:
    _OutputAndExit('NotReadyToAuthenticate')
  except OSError as e:
    _OutputAndExit('OSError: %s.' % e.strerror)
  except IOError as e:
    if e.errno == errno.EPIPE and not IsRunningInteractively():
      # If we get a pipe error, this just means that the pipe to stdout or
      # stderr is broken. This can happen if the user pipes gsutil to a command
      # that doesn't use the entire output stream. Instead of raising an error,
      # just swallow it up and exit cleanly.
      sys.exit(0)
    else:
      raise
  except wildcard_iterator.WildcardException as e:
    _OutputAndExit(e.reason)
  except ProjectIdException as e:
    _OutputAndExit(
        'You are attempting to perform an operation that requires a '
        'project id, with none configured. Please re-run '
        'gsutil config and make sure to follow the instructions for '
        'finding and entering your default project id.')
  except BadRequestException as e:
    if e.reason == 'MissingSecurityHeader':
      _CheckAndHandleCredentialException(e, args)
    _OutputAndExit(e)
  except AccessDeniedException as e:
    _CheckAndHandleCredentialException(e, args)
    _OutputAndExit(e)
  except ArgumentException as e:
    _OutputAndExit(e)
  except ServiceException as e:
    _OutputAndExit(e)
  except apitools_exceptions.HttpError as e:
    # These should usually be retried by the underlying implementation or
    # wrapped by CloudApi ServiceExceptions, but if we do get them,
    # print something useful.
    _OutputAndExit('HttpError: %s, %s' % (getattr(e.response, 'status', ''),
                                          e.content or ''))
  except socket.error as e:
    if e.args[0] == errno.EPIPE:
      # Retrying with a smaller file (per suggestion below) works because
      # the library code send loop (in boto/s3/key.py) can get through the
      # entire file and then request the HTTP response before the socket
      # gets closed and the response lost.
      _OutputAndExit(
          'Got a "Broken pipe" error. This can happen to clients using Python '
          '2.x, when the server sends an error response and then closes the '
          'socket (see http://bugs.python.org/issue5542). If you are trying to '
          'upload a large object you might retry with a small (say 200k) '
          'object, and see if you get a more specific error code.'
      )
    else:
      _HandleUnknownFailure(e)
  except Exception as e:
    # Check for two types of errors related to service accounts. These errors
    # appear to be the same except for their messages, but they are caused by
    # different problems and both have unhelpful error messages. Moreover,
    # the error type belongs to PyOpenSSL, which is not necessarily installed.
    if 'mac verify failure' in str(e):
      _OutputAndExit(
          'Encountered an error while refreshing access token. '
          'If you are using a service account,\nplease verify that the '
          'gs_service_key_file_password field in your config file,'
          '\n%s, is correct.' % GetConfigFilePath())
    elif 'asn1 encoding routines' in str(e):
      _OutputAndExit(
          'Encountered an error while refreshing access token. '
          'If you are using a service account,\nplease verify that the '
          'gs_service_key_file field in your config file,\n%s, is correct.'
          % GetConfigFilePath())
    _HandleUnknownFailure(e)


if __name__ == '__main__':
  sys.exit(main())
