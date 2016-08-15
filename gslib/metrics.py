# -*- coding: utf-8 -*-
# Copyright 2016 Google Inc. All Rights Reserved.
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
"""Static data and helper functions for collecting user data."""

import atexit
from collections import defaultdict
from collections import namedtuple
from functools import wraps
import logging
import os
import pickle
import platform
import re
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib
import uuid

import boto

from gslib import VERSION
from gslib.util import CreateDirIfNeeded
from gslib.util import HumanReadableToBytes

_GA_ENDPOINT = 'https://ssl.google-analytics.com/collect'

_GA_TID = 'UA-36037335-16'
_GA_TID_TESTING = 'UA-36037335-17'
_GA_COMMANDS_CATEGORY = 'Command'
_GA_ERRORRETRY_CATEGORY = 'RetryableError'
_GA_ERRORFATAL_CATEGORY = 'FatalError'
_GA_PERFSUM_CATEGORY = 'PerformanceSummary'
_GOOGLE_CORP_HOST_RE = re.compile('.*google.com$')

_UUID_FILE_PATH = os.path.expanduser(os.path.join('~',
                                                  '.gsutil/analytics-uuid'))
# If this string is written to analytics-uuid, that means that the user said
# 'no' to analytics, and it should thus be disabled.
_DISABLED_TEXT = 'DISABLED'

# Analytics collection uses the environment variable 'GSUTIL_TEST_ANALYTICS'.
# - A value of '1' completely disables analytics collection. This is used during
#   non-analytics tests to avoid reporting analytics events during normal
#   testing.
# - A value of '2' sets testing parameters and prevents the metrics_reporter.py
#   subprocess from writing to the metrics log file. This is used during
#   analytics tests in integration test subprocesses to disable reporting to GA
#   and avoid overwriting the metrics log file. In this scenario, the main
#   process’s root logger is enabled for debug output, so we still want
#   collection to occur so we can read metrics log messages from stderr.
# - Any other value sets default behavior.

# A Metric contains all of the information required to post a GA event. It is
# not a custom metric, which is a GA term for a specific number to track on the
# Analytics dashboard. This is not nested within MetricsCollector to allow
# pickle to dump a list of Metrics.
_Metric = namedtuple('_Metric', [
    # The URL of the request endpoint.
    'endpoint',
    # The HTTP method of request.
    'method',
    # The URL-encoded body to send with the request.
    'body',
    # The user-agent string to send as a header.
    'user_agent'
])

# Map from descriptive labels to the key labels that GA recognizes.
_GA_LABEL_MAP = {'Command Name': 'cd1',
                 'Global Options': 'cd2',
                 'Command-Level Options': 'cd3',
                 'Config': 'cd4',
                 'Command Alias': 'cd5',
                 'Fatal Error': 'cd6',
                 'Execution Time': 'cm1',
                 'Retryable Errors': 'cm2',
                 'Is Google Corp User': 'cm3'}


class MetricsCollector(object):
  """A singleton class to handle metrics reporting to Google Analytics (GA).

  This class is not thread or process-safe, and logging directly to the
  MetricsCollector instance can only be done by a single thread.
  """

  def __init__(self, ga_tid=_GA_TID, endpoint=_GA_ENDPOINT):
    """Initialize a new MetricsCollector.

    This should only be invoked through the GetCollector or StartTestCollector
    functions.

    Args:
      ga_tid: The Google Analytics tracking ID to use for metrics collection.
              Defaults to _GA_TID.
      endpoint: The URL to send requests to. Defaults to _GA_ENDPOINT.
    """
    self.start_time = _GetTimeInMillis()
    cid = MetricsCollector._GetCID()
    self.endpoint = endpoint
    self.logger = logging.getLogger()

    # Used by Google Analytics to track user OS.
    self.user_agent = '{system}/{release}'.format(system=platform.system(),
                                                  release=platform.release())

    # A string of non-PII config values.
    config_values = self._ValidateAndGetConfigValues()

    # gsutil developers should set this config value to true in order to hit the
    # testing GA property rather than the production property.
    use_test_property = boto.config.getbool('GSUtil', 'use_test_GA_property')
    if use_test_property:
      ga_tid = _GA_TID_TESTING

    # Approximate if this is a Google corporate user.
    is_corp_user = 0
    if _GOOGLE_CORP_HOST_RE.match(socket.gethostname()):
      is_corp_user = 1
    # Parameters to send with every GA event.
    self.ga_params = {'v': '1', 'tid': ga_tid, 'cid': cid, 't': 'event',
                      _GA_LABEL_MAP['Config']: config_values,
                      _GA_LABEL_MAP['Is Google Corp User']: is_corp_user}

    # A list of collected, unsent _Metrics. This list is currently bounded by
    # the number of retryable error types, and should not grow too large so that
    # we stay well within memory constraints.
    self._metrics = []

    # Store a count of the number of each type of retryable error.
    self.retryable_errors = defaultdict(int)

  _instance = None
  # Whether analytics collection is disabled or not.
  _disabled_cache = None

  def _ValidateAndGetConfigValues(self):
    """Parses the user's config file to aggregate non-PII config values.

    Returns:
      A comma-delimited string of config values explicitly set by the user in
      key:value pairs, sorted alphabetically by key.
    """
    config_values = []

    # If a user has an invalid config value set, we will mark it as such with
    # this value. If a user did not enter a value, we will not report it.
    invalid_value_string = 'INVALID'

    def GetAndValidateConfigValue(section, category, validation_fn):
      try:
        config_value = boto.config.get_value(section, category)
        if config_value and validation_fn(config_value):
          config_values.append((category, config_value))
        # If the user entered a non-valid config value, store it as invalid.
        elif config_value:
          config_values.append((category, invalid_value_string))
      # This function gets called during initialization of the MetricsCollector.
      # If any of the logic fails, we do not want to hinder the gsutil command
      # being run, and thus ignore any exceptions.
      except:  # pylint: disable=bare-except
        config_values.append((category, invalid_value_string))

    # Validate boolean values.
    for section, bool_category in (('Boto', 'https_validate_certificates'),
                                   ('GSUtil', 'disable_analytics_prompt'),
                                   ('GSUtil', 'use_magicfile'),
                                   ('GSUtil', 'tab_completion_time_logs')):
      GetAndValidateConfigValue(
          section=section, category=bool_category,
          validation_fn=lambda val: str(val).lower() in ('true', 'false'))

    # Define a threshold for some config values which should be reasonably low.
    small_int_threshold = 2000
    # Validate small integers.
    for section, small_int_category in (
        ('Boto', 'debug'),
        ('Boto', 'http_socket_timeout'),
        ('Boto', 'num_retries'),
        ('Boto', 'max_retry_delay'),
        ('GSUtil', 'default_api_version'),
        ('GSUtil', 'sliced_object_download_max_components'),
        ('GSUtil', 'parallel_process_count'),
        ('GSUtil', 'parallel_thread_count'),
        ('GSUtil', 'software_update_check_period'),
        ('GSUtil', 'tab_completion_timeout'),
        ('OAuth2', 'oauth2_refresh_retries')):
      GetAndValidateConfigValue(
          section=section, category=small_int_category,
          validation_fn=
          lambda val: str(val).isdigit() and int(val) < small_int_threshold)

    # Validate large integers.
    for section, large_int_category in (
        ('GSUtil', 'resumable_threshold'), ('GSUtil', 'rsync_buffer_lines'),
        ('GSUtil', 'task_estimation_threshold')):
      GetAndValidateConfigValue(
          section=section, category=large_int_category,
          validation_fn=lambda val: str(val).isdigit())

    # Validate data sizes.
    for section, data_size_category in (
        ('GSUtil', 'parallel_composite_upload_component_size'),
        ('GSUtil', 'parallel_composite_upload_threshold'),
        ('GSUtil', 'sliced_object_download_component_size'),
        ('GSUtil', 'sliced_object_download_threshold')):
      config_value = boto.config.get_value(section, data_size_category)
      if config_value:
        try:
          size_in_bytes = HumanReadableToBytes(config_value)
          config_values.append((data_size_category, size_in_bytes))
        except ValueError:
          config_values.append((data_size_category, invalid_value_string))

    # Validate specific options.
    # pylint: disable=g-long-lambda
    GetAndValidateConfigValue(
        section='GSUtil', category='check_hashes',
        validation_fn=lambda val: val in ('if_fast_else_fail',
                                          'if_fast_else_skip',
                                          'always', 'never'))
    # pylint: enable=g-long-lambda
    GetAndValidateConfigValue(
        section='GSUtil', category='content_language',
        validation_fn=lambda val: val.isalpha() and len(val) <= 3)
    GetAndValidateConfigValue(
        section='GSUtil', category='json_api_version',
        validation_fn=lambda val: val[0].lower() == 'v' and val[1:].isdigit())
    GetAndValidateConfigValue(
        section='GSUtil', category='prefer_api',
        validation_fn=lambda val: val in ('json', 'xml'))
    GetAndValidateConfigValue(
        section='OAuth2', category='token_cache',
        validation_fn=lambda val: val in ('file_system', 'in_memory'))

    return ','.join(sorted(['{0}:{1}'.format(config[0], config[1])
                            for config in config_values]))

  @staticmethod
  def GetCollector(ga_tid=_GA_TID):
    """Returns the singleton MetricsCollector instance or None if disabled."""
    if MetricsCollector.IsDisabled():
      return None

    if not MetricsCollector._instance:
      MetricsCollector._instance = MetricsCollector(ga_tid)
    return MetricsCollector._instance

  @staticmethod
  def IsDisabled():
    """Returns whether metrics collection should be disabled."""
    if MetricsCollector._disabled_cache is None:
      MetricsCollector._CheckAndSetDisabledCache()
    return MetricsCollector._disabled_cache

  @classmethod
  def _CheckAndSetDisabledCache(cls):
    """Sets _disabled_cache based on user opt-in or out."""
    # Disable collection for a test case where no metrics should be collected.
    if os.environ.get('GSUTIL_TEST_ANALYTICS') == '1':
      cls._disabled_cache = True
    # Enable test collector for a subprocess integration test case where we
    # check the log output, which requires a test collector.
    elif os.environ.get('GSUTIL_TEST_ANALYTICS') == '2':
      cls._disabled_cache = False
      cls.StartTestCollector()

    # Non-testing cases involve checking the cloud SDK wrapper and the analytics
    # uuid file.
    elif os.environ.get('CLOUDSDK_WRAPPER') == '1':
      cls._disabled_cache = not os.environ.get('GA_CID')
    elif os.path.exists(_UUID_FILE_PATH):
      with open(_UUID_FILE_PATH) as f:
        cls._disabled_cache = (f.read() == _DISABLED_TEXT)
    else:
      cls._disabled_cache = True

  @classmethod
  def StartTestCollector(cls, endpoint='https://example.com',
                         user_agent='user-agent-007', ga_params=None):
    """Reset the singleton MetricsCollector with testing parameters.

    Should only be used for tests, where we want to change the default
    parameters.

    Args:
      endpoint: str, URL to post to
      user_agent: str, User-Agent string for header.
      ga_params: A list of two-dimensional string tuples to send as parameters.
    """
    # Re-enable analytics for the duration of the testing.
    if cls.IsDisabled():
      os.environ['GSUTIL_TEST_ANALYTICS'] = '0'
    cls._disabled_cache = False
    cls._instance = cls(_GA_TID_TESTING, endpoint)
    if ga_params is None:
      ga_params = {'a': 'b', 'c': 'd'}
    cls._instance.ga_params = ga_params
    cls._instance.user_agent = user_agent
    cls._instance.start_time = 0

  @classmethod
  def StopTestCollector(cls, original_instance=None):
    """Reset the MetricsCollector with default parameters after testing.

    Args:
      original_instance: The original instance of the MetricsCollector so we can
        set the collector back to its original state.
    """
    os.environ['GSUTIL_TEST_ANALYTICS'] = '1'
    cls._disabled_cache = None
    cls._instance = original_instance

  @staticmethod
  def _GetCID():
    """Gets the client id from the UUID file or the SDK opt-in, or returns None.

    Returns:
      str, The hex string of the client id.
    """
    if os.path.exists(_UUID_FILE_PATH):
      with open(_UUID_FILE_PATH) as f:
        cid = f.read()
      if cid:
        return cid

    # Returns CID from SDK. This value will be None if there is no opt-in from
    # the SDK.
    return os.environ.get('GA_CID')

  def ExtendGAParams(self, new_params):
    """Extends self.ga_params to include new parameters.

    This is only used to record parameters that are sent with every event type,
    such as global and command-level options.

    Args:
      new_params: A dictionary of key-value parameters to send.
    """
    self.ga_params.update(new_params)

  def GetGAParam(self, param_name):
    """Convenience function for getting a ga_param of the collector.

    Args:
      param_name: The descriptive name of the param (e.g. 'Command Name'). Must
        be a key in _GA_LABEL_MAP.

    Returns:
      The GA parameter specified, or None.
    """
    return self.ga_params.get(_GA_LABEL_MAP[param_name])

  def CollectGAMetric(self, category, action,
                      label=VERSION, value=0, **custom_params):
    """Adds a GA metric with the given parameters to the metrics queue.

    Args:
      category: str, the GA Event category.
      action: str, the GA Event action.
      label: str, the GA Event label.
      value: int, the GA Event value.
      **custom_params: A dictionary of key, value pairs containing custom
        metrics and dimensions to send with the GA Event.
    """
    params = [('ec', category), ('ea', action), ('el', label), ('ev', value)]
    params.extend([(k, v) for k, v in custom_params.iteritems()
                   if v is not None])
    params.extend([(k, v) for k, v in self.ga_params.iteritems()
                   if v is not None])

    # Log how long after the start of the program this event happened.
    params.append((_GA_LABEL_MAP['Execution Time'],
                   _GetTimeInMillis() - self.start_time))

    data = urllib.urlencode(params)
    self._metrics.append(_Metric(endpoint=self.endpoint,
                                 method='POST',
                                 body=data,
                                 user_agent=self.user_agent))

  def _CollectCommandAndErrorMetrics(self):
    """Aggregates command and error info and adds them to the metrics list."""
    # Collect the command metric, including the number of retryable errors.
    command_name = self.GetGAParam('Command Name')
    if command_name:
      self.CollectGAMetric(category=_GA_COMMANDS_CATEGORY,
                           action=command_name,
                           **{_GA_LABEL_MAP['Retryable Errors']:
                              sum(self.retryable_errors.values())})

    # Collect the retryable errors.
    for error_type, num_errors in self.retryable_errors.iteritems():
      self.CollectGAMetric(category=_GA_ERRORRETRY_CATEGORY, action=error_type,
                           **{_GA_LABEL_MAP['Retryable Errors']: num_errors})

    # Collect the fatal error, if any.
    fatal_error_type = self.GetGAParam('Fatal Error')
    if fatal_error_type:
      self.CollectGAMetric(category=_GA_ERRORFATAL_CATEGORY,
                           action=fatal_error_type)

  def ReportMetrics(self, wait_for_report=False, log_level=None):
    """Reports the collected metrics using a separate async process.

    Args:
      wait_for_report: bool, True if the main process should wait for the
        subprocess to exit for testing purposes.
      log_level: int, The subprocess logger's level of debugging for testing
        purposes.
    """
    self._CollectCommandAndErrorMetrics()
    if not self._metrics:
      return

    if not log_level:
      log_level = self.logger.getEffectiveLevel()
    # If this a testing subprocess, we don't want to write to the log file.
    if os.environ.get('GSUTIL_TEST_ANALYTICS') == '2':
      log_level = logging.WARN

    temp_metrics_file = tempfile.NamedTemporaryFile(delete=False)
    with temp_metrics_file:
      pickle.dump(self._metrics, temp_metrics_file)
    logging.debug(self._metrics)
    self._metrics = []
    self.retryable_errors.clear()

    reporting_code = ('from gslib.metrics_reporter import ReportMetrics; '
                      'ReportMetrics("{0}", {1})').format(
                          temp_metrics_file.name,
                          log_level).encode('string-escape')
    execution_args = [sys.executable, '-c', reporting_code]
    exec_env = os.environ.copy()
    exec_env['PYTHONPATH'] = os.pathsep.join(sys.path)

    try:
      p = subprocess.Popen(execution_args, env=exec_env)
      self.logger.debug('Metrics reporting process started...')

      if wait_for_report:
        # NOTE: p.wait() can cause a deadlock. p.communicate() is recommended.
        # See python docs for more information.
        p.communicate()
        self.logger.debug('Metrics reporting process finished.')
    except OSError:
      # This can happen specifically if the Python executable moves between the
      # start of this process and now.
      self.logger.debug('Metrics reporting process failed to start.')


def CaptureAndLogException(func):
  """Function decorator to capture and log any exceptions.

  This is extra insurance that analytics collection will not hinder the command
  being run upon an error.

  Args:
    func: The function to wrap.

  Returns:
    The wrapped function.
  """
  @wraps(func)
  def Wrapper(*args, **kwds):
    try:
      return func(*args, **kwds)
    except:  # pylint:disable=bare-except
      logging.debug('Exception captured in %s during metrics collection',
                    func.__name__)
  return Wrapper


@CaptureAndLogException
@atexit.register
def Shutdown():
  """Reports the metrics that were collected upon termination."""
  collector = MetricsCollector.GetCollector()
  if collector:
    collector.ReportMetrics()


@CaptureAndLogException
def LogCommandParams(command_name=None, subcommands=None, global_opts=None,
                     sub_opts=None, command_alias=None):
  """Logs info about the gsutil command being run.

  This only updates the collector's ga_params. The actual command metric will
  be collected once ReportMetrics() is called at shutdown.

  Args:
    command_name: str, The official command name (e.g. version instead of ver).
    subcommands: A list of subcommands as strings already validated by
      RunCommand. We do not log subcommands for the help or test commands.
    global_opts: A list of string tuples already parsed by __main__.
    sub_opts: A list of command-level options as string tuples already parsed
      by RunCommand.
    command_alias: str, The supported alias that the user inputed.
  """
  collector = MetricsCollector.GetCollector()
  if not collector:
    return

  # Never re-log any parameter that's already there, as we should only be
  # collecting the global (user-run) command.
  if command_name and not collector.GetGAParam('Command Name'):
    collector.ExtendGAParams({_GA_LABEL_MAP['Command Name']: command_name})
  if global_opts and not collector.GetGAParam('Global Options'):
    global_opts_string = ','.join(sorted([opt[0].strip('-') for opt in
                                          global_opts]))
    collector.ExtendGAParams(
        {_GA_LABEL_MAP['Global Options']: global_opts_string})

  # Only log subcommands, suboptions, and command alias if a command has been
  # logged.
  command_name = collector.GetGAParam('Command Name')
  if not command_name:
    return
  if subcommands:
    full_command_name = '{0} {1}'.format(command_name, ' '.join(subcommands))
    collector.ExtendGAParams({_GA_LABEL_MAP['Command Name']: full_command_name})
  if sub_opts and not collector.GetGAParam('Command-Level Options'):
    sub_opts_string = ','.join(sorted([opt[0].strip('-') for opt in sub_opts]))
    collector.ExtendGAParams(
        {_GA_LABEL_MAP['Command-Level Options']: sub_opts_string})
  if command_alias and not collector.GetGAParam('Command Alias'):
    collector.ExtendGAParams({_GA_LABEL_MAP['Command Alias']: command_alias})


@CaptureAndLogException
def LogRetryableError(error_type):
  """Logs that a retryable error was caught for a gsutil command.

  Args:
    error_type: str, The error type, e.g. ServiceException, SocketError, etc.
  """
  collector = MetricsCollector.GetCollector()
  if collector:
    # Update the retryable_errors defaultdict.
    collector.retryable_errors[error_type] += 1


@CaptureAndLogException
def LogFatalError(exception):
  """Logs that a fatal error was caught for a gsutil command.

  Args:
    exception: The exception that the command failed on.
  """
  collector = MetricsCollector.GetCollector()
  if collector:
    collector.ExtendGAParams(
        {_GA_LABEL_MAP['Fatal Error']: exception.__class__.__name__})


# TODO: Add all custom dimensions and metrics for performance summaries.
@CaptureAndLogException
def LogPerformanceSummary(is_upload):
  """Logs a performance summary.

  gsutil periodically monitors its own threads; at the end of the execution of
  each cp/rsync command, it will present a performance summary of the command
  run.

  Args:
    is_upload: bool, True if the transfer was an upload, false if download.
  """
  action = 'Download'
  if is_upload:
    action = 'Upload'
  collector = MetricsCollector.GetCollector()
  if collector:
    collector.CollectGAMetric(category=_GA_PERFSUM_CATEGORY, action=action)


@CaptureAndLogException
def CheckAndMaybePromptForAnalyticsEnabling():
  """Asks a user to opt-in to data collection if a UUID file does not exist.

  If the user agrees, generates a UUID file. Will not prompt if part of SDK.
  """
  disable_prompt = boto.config.get_value('GSUtil', 'disable_analytics_prompt')
  if not os.path.exists(
      _UUID_FILE_PATH) and not disable_prompt and not os.environ.get(
          'CLOUDSDK_WRAPPER'):
    enable_analytics = raw_input('\n' + textwrap.fill(
        'gsutil developers rely on user feedback to make improvements to the '
        'tool. Would you like to send anonymous usage statistics to help '
        'improve gsutil? [y/N]') + ' ')

    text_to_write = _DISABLED_TEXT
    if enable_analytics.lower()[0] == 'y':
      text_to_write = uuid.uuid4().hex
    CreateDirIfNeeded(os.path.dirname(_UUID_FILE_PATH))
    with open(_UUID_FILE_PATH, 'w') as f:
      f.write(text_to_write)


def _GetTimeInMillis():
  return int(time.time() * 1000)
