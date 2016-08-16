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
# pylint:mode=test
"""Unit tests for analytics data collection."""

from __future__ import absolute_import

from collections import namedtuple
import logging
import os
import pickle
import socket
import subprocess
import sys
import tempfile
import urllib

from apitools.base.py import exceptions as apitools_exceptions
from apitools.base.py import http_wrapper
from boto.storage_uri import BucketStorageUri

from gslib import metrics
from gslib import VERSION
from gslib.cs_api_map import ApiSelector
import gslib.exception
from gslib.gcs_json_api import GcsJsonApi
from gslib.metrics import MetricsCollector
from gslib.metrics_reporter import LOG_FILE_PATH
import gslib.tests.testcase as testcase
from gslib.tests.util import ObjectToURI as suri
from gslib.tests.util import SetBotoConfigForTest
from gslib.tests.util import unittest
from gslib.third_party.storage_apitools import storage_v1_messages as apitools_messages
from gslib.thread_message import RetryableErrorMessage
from gslib.util import LogAndHandleRetries
from gslib.util import ONE_KIB
from gslib.util import START_CALLBACK_PER_BYTES
import mock

# A piece of the URL logged for all of the tests.
GLOBAL_DIMENSIONS_URL = '&a=b&c=d&cd1=cmd1+action1&cd2=x%2Cy%2Cz&cd3=opta%2Coptb&cd6=CommandException&cm1=0'

# A TestMetric is equivalent to a _Metric, except the body is a frozenset of
# key=value strings rather than a URL-encoded string. This allows us to compare
# URLs that might be ordered differently.
TestMetric = namedtuple('TestMetric',
                        ['endpoint', 'method', 'body', 'user_agent'])

GLOBAL_PARAMETERS = ['a=b', 'c=d', 'cd1=cmd1 action1', 'cd2=x,y,z',
                     'cd3=opta,optb', 'cd6=CommandException', 'cm1=0',
                     'ev=0', 'el={0}'.format(VERSION)]
COMMAND_AND_ERROR_TEST_METRICS = set([
    TestMetric(
        'https://example.com', 'POST',
        frozenset(GLOBAL_PARAMETERS +
                  ['ec=' + metrics._GA_COMMANDS_CATEGORY,
                   'ea=cmd1 action1', 'cm2=3']),
        'user-agent-007'),
    TestMetric(
        'https://example.com', 'POST',
        frozenset(GLOBAL_PARAMETERS +
                  ['ec=' + metrics._GA_ERRORRETRY_CATEGORY,
                   ('ea=retryable_error_type_1'), ('cm2=2')]),
        'user-agent-007'),
    TestMetric(
        'https://example.com', 'POST',
        frozenset(GLOBAL_PARAMETERS +
                  [('ec=' + metrics._GA_ERRORRETRY_CATEGORY),
                   ('ea=retryable_error_type_2'), ('cm2=1')]),
        'user-agent-007'),
    TestMetric(
        'https://example.com', 'POST',
        frozenset(GLOBAL_PARAMETERS +
                  [('ec=' + metrics._GA_ERRORFATAL_CATEGORY),
                   ('ea=CommandException')]),
        'user-agent-007')
])


def MetricListToTestMetricSet(metric_list):
  """Convert a list of _Metrics to a set of TestMetrics."""
  def MetricToTestMetric(metric):
    body = frozenset(urllib.unquote_plus(metric.body).split('&'))
    return TestMetric(metric.endpoint, metric.method, body, metric.user_agent)
  return set([MetricToTestMetric(metric) for metric in metric_list])


def _TryExceptAndPass(func, *args, **kwargs):
  """Calls the given function with the arguments and ignores exceptions.

  In these tests, we often force a failure that doesn't matter in order to
  check that a metric was collected.

  Args:
    func: The function to call.
    *args: Any arguments to call the function with.
    **kwargs: Any named arguments to call the function with.
  """
  try:
    func(*args, **kwargs)
  except:  # pylint: disable=bare-except
    pass


def _LogAllTestMetrics():
  """Logs all the common metrics for a test."""
  metrics.LogCommandParams(
      command_name='cmd1', subcommands=['action1'],
      global_opts=[('-y', 'value'), ('-z', ''), ('-x', '')],
      sub_opts=[('optb', ''), ('opta', '')])
  metrics.LogRetryableError('retryable_error_type_1')
  metrics.LogRetryableError('retryable_error_type_1')
  metrics.LogRetryableError('retryable_error_type_2')
  metrics.LogFatalError(gslib.exception.CommandException('test'))


class RetryableErrorsQueue(object):
  """Emulates Cloud API status queue, processes only RetryableErrorMessages."""

  def put(self, status_item):  # pylint: disable=invalid-name
    if isinstance(status_item, RetryableErrorMessage):
      metrics.LogRetryableError(status_item.error_type)


@mock.patch('time.time', new=mock.MagicMock(return_value=0))
class TestMetricsUnitTests(testcase.GsUtilUnitTestCase):
  """Unit tests for analytics data collection."""

  def setUp(self):
    super(TestMetricsUnitTests, self).setUp()

    # Save the original state of the collector.
    self.original_collector_instance = MetricsCollector.GetCollector()

    # Set dummy attributes for the collector.
    MetricsCollector.StartTestCollector('https://example.com', 'user-agent-007',
                                        {'a': 'b', 'c': 'd'})
    self.collector = MetricsCollector.GetCollector()

  def tearDown(self):
    super(TestMetricsUnitTests, self).tearDown()

    # Reset to default collection settings.
    MetricsCollector.StopTestCollector(
        original_instance=self.original_collector_instance)

  def testDisabling(self):
    """Tests enabling/disabling of metrics collection."""
    self.assertEqual(self.collector, MetricsCollector.GetCollector())

    # Test when gsutil is part of the Cloud SDK and the user opted in there.
    with mock.patch.dict(os.environ,
                         values={'CLOUDSDK_WRAPPER': '1',
                                 'GA_CID': '555'}):
      MetricsCollector._CheckAndSetDisabledCache()
      self.assertFalse(MetricsCollector._disabled_cache)
      self.assertEqual(self.collector, MetricsCollector.GetCollector())

    # Test when gsutil is part of the Cloud SDK and the user did not opt in
    # there.
    with mock.patch.dict(os.environ,
                         values={'CLOUDSDK_WRAPPER': '1',
                                 'GA_CID': ''}):
      MetricsCollector._CheckAndSetDisabledCache()
      self.assertTrue(MetricsCollector._disabled_cache)
      self.assertEqual(None, MetricsCollector.GetCollector())

    # Test when gsutil is not part of the Cloud SDK and there is no UUID file.
    with mock.patch.dict(os.environ, values={'CLOUDSDK_WRAPPER': ''}):
      with mock.patch('os.path.exists', return_value=False):
        MetricsCollector._CheckAndSetDisabledCache()
        self.assertTrue(MetricsCollector._disabled_cache)
        self.assertEqual(None, MetricsCollector.GetCollector())

    # Test when gsutil is not part of the Cloud SDK and there is a UUID file.
    with mock.patch.dict(os.environ, values={'CLOUDSDK_WRAPPER': ''}):
      with mock.patch('os.path.exists', return_value=True):
        # Mock the contents of the file.
        with mock.patch('__builtin__.open') as mock_open:
          mock_open.return_value.__enter__ = lambda s: s

          # Set the file.read() method to return the disabled text.
          mock_open.return_value.read.return_value = metrics._DISABLED_TEXT
          MetricsCollector._CheckAndSetDisabledCache()
          self.assertTrue(MetricsCollector._disabled_cache)
          self.assertEqual(None, MetricsCollector.GetCollector())

          # Set the file.read() method to return a mock cid (analytics enabled).
          mock_open.return_value.read.return_value = 'mock_cid'
          MetricsCollector._CheckAndSetDisabledCache()
          self.assertFalse(MetricsCollector._disabled_cache)
          self.assertEqual(self.collector, MetricsCollector.GetCollector())

          # Check that open/read was called twice.
          self.assertEqual(2, len(mock_open.call_args_list))
          self.assertEqual(2, len(mock_open.return_value.read.call_args_list))

  def testConfigValueValidation(self):
    """Tests the validation of potentially PII config values."""
    string_and_bool_categories = ['check_hashes', 'content_language',
                                  'disable_analytics_prompt',
                                  'https_validate_certificates',
                                  'json_api_version',
                                  'parallel_composite_upload_component_size',
                                  'parallel_composite_upload_threshold',
                                  'prefer_api',
                                  'sliced_object_download_component_size',
                                  'sliced_object_download_threshold',
                                  'tab_completion_time_logs', 'token_cache',
                                  'use_magicfile']
    int_categories = ['debug', 'default_api_version', 'http_socket_timeout',
                      'max_retry_delay', 'num_retries',
                      'oauth2_refresh_retries', 'parallel_process_count',
                      'parallel_thread_count', 'resumable_threshold',
                      'rsync_buffer_lines',
                      'sliced_object_download_max_components',
                      'software_update_check_period', 'tab_completion_timeout',
                      'task_estimation_threshold']
    all_categories = sorted(string_and_bool_categories + int_categories)

    # Test general invalid values.
    with mock.patch('boto.config.get_value', return_value=None):
      self.assertEqual('', self.collector._ValidateAndGetConfigValues())

    with mock.patch('boto.config.get_value', return_value='invalid string'):
      self.assertEqual(','.join([
          category + ':INVALID' for category in all_categories
      ]), self.collector._ValidateAndGetConfigValues())

    # Test that non-ASCII characters are invalid.
    with mock.patch('boto.config.get_value', return_value='£'):
      self.assertEqual(','.join([
          category + ':INVALID' for category in all_categories
      ]), self.collector._ValidateAndGetConfigValues())

    # Mock valid return values for specific string validations.
    def MockValidStrings(section, category):
      if section == 'GSUtil':
        if category == 'check_hashes':
          return 'if_fast_else_skip'
        if category == 'content_language':
          return 'chi'
        if category == 'json_api_version':
          return 'v3'
        if category == 'prefer_api':
          return 'xml'
        if category in ('disable_analytics_prompt', 'use_magicfile',
                        'tab_completion_time_logs'):
          return 'True'
      if section == 'OAuth2' and category == 'token_cache':
        return 'file_system'
      if section == 'Boto' and category == 'https_validate_certificates':
        return 'True'
      return ''
    with mock.patch('boto.config.get_value', side_effect=MockValidStrings):
      self.assertEqual(
          'check_hashes:if_fast_else_skip,content_language:chi,'
          'disable_analytics_prompt:True,https_validate_certificates:True,'
          'json_api_version:v3,prefer_api:xml,tab_completion_time_logs:True,'
          'token_cache:file_system,use_magicfile:True',
          self.collector._ValidateAndGetConfigValues())

    # Test that "small" and "large" integers are appropriately validated.
    def MockValidSmallInts(_, category):
      if category in int_categories:
        return '1999'
      return ''
    with mock.patch('boto.config.get_value', side_effect=MockValidSmallInts):
      self.assertEqual(
          'debug:1999,default_api_version:1999,http_socket_timeout:1999,'
          'max_retry_delay:1999,num_retries:1999,oauth2_refresh_retries:1999,'
          'parallel_process_count:1999,parallel_thread_count:1999,'
          'resumable_threshold:1999,rsync_buffer_lines:1999,'
          'sliced_object_download_max_components:1999,'
          'software_update_check_period:1999,tab_completion_timeout:1999,'
          'task_estimation_threshold:1999',
          self.collector._ValidateAndGetConfigValues())

    def MockValidLargeInts(_, category):
      if category in int_categories:
        return '2001'
      return ''
    with mock.patch('boto.config.get_value', side_effect=MockValidLargeInts):
      self.assertEqual(
          'debug:INVALID,default_api_version:INVALID,'
          'http_socket_timeout:INVALID,max_retry_delay:INVALID,'
          'num_retries:INVALID,oauth2_refresh_retries:INVALID,'
          'parallel_process_count:INVALID,parallel_thread_count:INVALID,'
          'resumable_threshold:2001,rsync_buffer_lines:2001,'
          'sliced_object_download_max_components:INVALID,'
          'software_update_check_period:INVALID,'
          'tab_completion_timeout:INVALID,task_estimation_threshold:2001',
          self.collector._ValidateAndGetConfigValues())

      # Test that a non-integer return value is invalid.
      def MockNonIntegerValue(_, category):
        if category in int_categories:
          return '10.28'
        return ''
      with mock.patch('boto.config.get_value', side_effect=MockNonIntegerValue):
        self.assertEqual(
            ','.join([category + ':INVALID' for category in int_categories]),
            self.collector._ValidateAndGetConfigValues())

      # Test data size validation.
      def MockDataSizeValue(_, category):
        if category in ('parallel_composite_upload_component_size',
                        'parallel_composite_upload_threshold',
                        'sliced_object_download_component_size',
                        'sliced_object_download_threshold'):
          return '10MiB'
        return ''
      with mock.patch('boto.config.get_value', side_effect=MockDataSizeValue):
        self.assertEqual('parallel_composite_upload_component_size:10485760,'
                         'parallel_composite_upload_threshold:10485760,'
                         'sliced_object_download_component_size:10485760,'
                         'sliced_object_download_threshold:10485760',
                         self.collector._ValidateAndGetConfigValues())

  def testGAEventsCollection(self):
    """Tests the collection of each event category."""
    self.assertEqual([], self.collector._metrics)

    _LogAllTestMetrics()
    # Only the first command should be logged.
    metrics.LogCommandParams(command_name='cmd2')

    # Commands and errors should not be collected until we explicitly collect
    # them.
    self.assertEqual([], self.collector._metrics)
    self.collector._CollectCommandAndErrorMetrics()
    self.assertEqual(COMMAND_AND_ERROR_TEST_METRICS,
                     MetricListToTestMetricSet(self.collector._metrics))

    metrics.LogPerformanceSummary(True)
    perfsum1_metric = TestMetric(
        'https://example.com', 'POST',
        frozenset(GLOBAL_PARAMETERS +
                  ['ec=' + metrics._GA_PERFSUM_CATEGORY, ('ea=Upload')]),
        'user-agent-007')
    COMMAND_AND_ERROR_TEST_METRICS.add(perfsum1_metric)
    self.assertEqual(COMMAND_AND_ERROR_TEST_METRICS,
                     MetricListToTestMetricSet(self.collector._metrics))

    metrics.LogPerformanceSummary(False)
    perfsum2_metric = TestMetric(
        'https://example.com', 'POST',
        frozenset(GLOBAL_PARAMETERS +
                  ['ec=' + metrics._GA_PERFSUM_CATEGORY, ('ea=Download')]),
        'user-agent-007')
    COMMAND_AND_ERROR_TEST_METRICS.add(perfsum2_metric)
    self.assertEqual(COMMAND_AND_ERROR_TEST_METRICS,
                     MetricListToTestMetricSet(self.collector._metrics))

  def testCommandCollection(self):
    """Tests the collection of command parameters."""
    _TryExceptAndPass(self.command_runner.RunNamedCommand,
                      'acl', ['set', '-a'], collect_analytics=True)
    self.assertEqual(
        'acl set',
        self.collector.ga_params.get(metrics._GA_LABEL_MAP['Command Name']))
    self.assertEqual('a', self.collector.ga_params.get(metrics._GA_LABEL_MAP[
        'Command-Level Options']))

    # Reset the ga_params, which store the command info.
    self.collector.ga_params.clear()
    self.command_runner.RunNamedCommand('list', collect_analytics=True)
    self.assertEqual(
        'ls',
        self.collector.ga_params.get(metrics._GA_LABEL_MAP['Command Name']))
    self.assertEqual(
        'list',
        self.collector.ga_params.get(metrics._GA_LABEL_MAP['Command Alias']))

    self.collector.ga_params.clear()
    _TryExceptAndPass(
        self.command_runner.RunNamedCommand,
        'iam', ['get', 'dummy_bucket'], collect_analytics=True)
    self.assertEqual(
        'iam get',
        self.collector.ga_params.get(metrics._GA_LABEL_MAP['Command Name']))

  # We only care about the error logging, not the actual exceptions handling.
  @mock.patch.object(http_wrapper, 'HandleExceptionsAndRebuildHttpConnections')
  def testRetryableErrorCollection(self, mock_default_retry):
    """Tests the collection of a retryable error in the retry function."""
    # A DiscardMessagesQueue has the same retryable error-logging code as the
    # UIThread and the MainThreadUIQueue.
    mock_queue = RetryableErrorsQueue()
    value_error_retry_args = http_wrapper.ExceptionRetryArgs(None, None,
                                                             ValueError(), None,
                                                             None, None)
    socket_error_retry_args = http_wrapper.ExceptionRetryArgs(None, None,
                                                              socket.error(),
                                                              None, None, None)
    metadata_retry_func = LogAndHandleRetries(is_data_transfer=False,
                                              status_queue=mock_queue)
    media_retry_func = LogAndHandleRetries(is_data_transfer=True,
                                           status_queue=mock_queue)

    metadata_retry_func(value_error_retry_args)
    self.assertEqual(self.collector.retryable_errors['ValueError'], 1)
    metadata_retry_func(value_error_retry_args)
    self.assertEqual(self.collector.retryable_errors['ValueError'], 2)
    metadata_retry_func(socket_error_retry_args)
    self.assertEqual(self.collector.retryable_errors['SocketError'], 1)

    # The media retry function raises an exception after logging because
    # the GcsJsonApi handles retryable errors for media transfers itself.
    _TryExceptAndPass(media_retry_func, value_error_retry_args)
    _TryExceptAndPass(media_retry_func, socket_error_retry_args)
    self.assertEqual(self.collector.retryable_errors['ValueError'], 3)
    self.assertEqual(self.collector.retryable_errors['SocketError'], 2)

  def testExceptionCatchingDecorator(self):
    """Tests the exception catching decorator CaptureAndLogException."""
    original_log_level = self.root_logger.getEffectiveLevel()
    self.root_logger.setLevel(logging.DEBUG)

    # Test that a wrapped function with an exception doesn't stop the process.
    mock_exc_fn = mock.MagicMock(__name__='mock_exc_fn',
                                 side_effect=Exception())
    wrapped_fn = metrics.CaptureAndLogException(mock_exc_fn)
    wrapped_fn()
    self.assertEqual(1, mock_exc_fn.call_count)
    with open(self.log_handler_file) as f:
      log_output = f.read()
      self.assertIn('Exception captured in mock_exc_fn during metrics '
                    'collection', log_output)

    mock_err_fn = mock.MagicMock(__name__='mock_err_fn',
                                 side_effect=TypeError())
    wrapped_fn = metrics.CaptureAndLogException(mock_err_fn)
    wrapped_fn()
    self.assertEqual(1, mock_err_fn.call_count)
    with open(self.log_handler_file) as f:
      log_output = f.read()
      self.assertIn('Exception captured in mock_err_fn during metrics '
                    'collection', log_output)

    # Test that exceptions in the unprotected metrics functions are caught.
    with mock.patch.object(MetricsCollector, 'GetCollector',
                           return_value='not a collector'):
      # These calls should all fail, but the exceptions shouldn't propagate up.
      metrics.Shutdown()
      metrics.LogCommandParams()
      metrics.LogRetryableError()
      metrics.LogFatalError()
      metrics.LogPerformanceSummary()
      metrics.CheckAndMaybePromptForAnalyticsEnabling('invalid argument')
      with open(self.log_handler_file) as f:
        log_output = f.read()
        self.assertIn(
            'Exception captured in Shutdown during metrics collection',
            log_output)
        self.assertIn(
            'Exception captured in LogCommandParams during metrics collection',
            log_output)
        self.assertIn(
            'Exception captured in LogRetryableError during metrics collection',
            log_output)
        self.assertIn(
            'Exception captured in LogFatalError during metrics collection',
            log_output)
        self.assertIn(
            'Exception captured in LogPerformanceSummary during metrics '
            'collection', log_output)
        self.assertIn(
            'Exception captured in CheckAndMaybePromptForAnalyticsEnabling '
            'during metrics collection', log_output)
    self.root_logger.setLevel(original_log_level)


# Mock callback handlers to throw errors in integration tests, based on handlers
# from test_cp.py.
class _JSONForceHTTPErrorCopyCallbackHandler(object):
  """Test callback handler that raises an arbitrary HTTP error exception."""

  def __init__(self, startover_at_byte, http_error_num):
    self._startover_at_byte = startover_at_byte
    self._http_error_num = http_error_num
    self.started_over_once = False

  # pylint: disable=invalid-name
  def call(self, total_bytes_transferred, unused_total_size):
    """Forcibly exits if the transfer has passed the halting point."""
    if (total_bytes_transferred >= self._startover_at_byte and
        not self.started_over_once):
      self.started_over_once = True
      raise apitools_exceptions.HttpError({'status': self._http_error_num},
                                          None, None)


class _ResumableUploadRetryHandler(object):
  """Test callback handler for causing retries during a resumable transfer."""

  def __init__(self, retry_at_byte, exception_to_raise, exc_args,
               num_retries=1):
    self._retry_at_byte = retry_at_byte
    self._exception_to_raise = exception_to_raise
    self._exception_args = exc_args
    self._num_retries = num_retries

    self._retries_made = 0

  # pylint: disable=invalid-name
  def call(self, total_bytes_transferred, unused_total_size):
    """Cause a single retry at the retry point."""
    if (total_bytes_transferred >= self._retry_at_byte and
        self._retries_made < self._num_retries):
      self._retries_made += 1
      raise self._exception_to_raise(*self._exception_args)


class TestMetricsIntegrationTests(testcase.GsUtilIntegrationTestCase):
  """Integration tests for analytics data collection."""

  def setUp(self):
    super(TestMetricsIntegrationTests, self).setUp()

    # Save the original state of the collector.
    self.original_collector_instance = MetricsCollector.GetCollector()

    # Set dummy attributes for the collector.
    MetricsCollector.StartTestCollector('https://example.com', 'user-agent-007',
                                        {'a': 'b', 'c': 'd'})
    self.collector = MetricsCollector.GetCollector()

  def tearDown(self):
    super(TestMetricsIntegrationTests, self).tearDown()

    # Reset to default collection settings.
    MetricsCollector.StopTestCollector(
        original_instance=self.original_collector_instance)

  def _RunGsUtilWithAnalyticsOutput(self, cmd, expected_status=0):
    """Runs the gsutil command to check for metrics log output.

    The env value is set so that the metrics collector in the subprocess will
    use testing parameters and output the metrics collected to the debugging
    log, which lets us check for proper collection in the stderr.

    Args:
      cmd: The command to run, as a list.
      expected_status: The expected return code.

    Returns:
      The stderr (log output) of the run command.
    """
    return self.RunGsUtil(['-d'] + cmd, return_stderr=True,
                          expected_status=expected_status,
                          env_vars={'GSUTIL_TEST_ANALYTICS': '2'})

  def _StartObjectPatch(self, *args, **kwargs):
    """Runs mock.patch.object with the given args, and returns the mock object.

    This starts the patcher, returns the mock object, and registers the patcher
    to stop on test teardown.

    Args:
      *args: The args to pass to mock.patch.object()
      **kwargs: The kwargs to pass to mock.patch.object()

    Returns:
      Mock, The result of starting the patcher.
    """
    patcher = mock.patch.object(*args, **kwargs)
    self.addCleanup(patcher.stop)
    return patcher.start()

  @mock.patch('time.time', new=mock.MagicMock(return_value=0))
  def testMetricsReporting(self):
    """Tests the subprocess creation by Popen in metrics.py."""
    popen_mock = self._StartObjectPatch(subprocess, 'Popen')

    # Set up the temp file for pickle dumping metrics into.
    metrics_file = tempfile.NamedTemporaryFile()
    metrics_file.close()
    temp_file_mock = self._StartObjectPatch(tempfile, 'NamedTemporaryFile')
    temp_file_mock.return_value = open(metrics_file.name, 'wb')

    # If there are no metrics, Popen should not be called.
    self.collector.ReportMetrics()
    self.assertEqual(0, popen_mock.call_count)

    _LogAllTestMetrics()

    # Report the metrics and check Popen calls.
    metrics.Shutdown()
    call_list = popen_mock.call_args_list
    self.assertEqual(1, len(call_list))
    # Check to make sure that we have the proper PYTHONPATH in the subprocess.
    args = call_list[0]
    self.assertIn('PYTHONPATH', args[1]['env'])
    # Ensure that we can access the same modules as the main process from
    # PYTHONPATH.
    missing_paths = (
        set(sys.path) - set(args[1]['env']['PYTHONPATH'].split(os.pathsep)))
    self.assertEqual(set(), missing_paths)

    # Check that the metrics were correctly dumped into the temp file.
    with open(metrics_file.name, 'rb') as metrics_file:
      reported_metrics = pickle.load(metrics_file)
    self.assertEqual(COMMAND_AND_ERROR_TEST_METRICS,
                     MetricListToTestMetricSet(reported_metrics))

  @mock.patch('time.time', new=mock.MagicMock(return_value=0))
  def testMetricsPosting(self):
    """Tests the metrics posting process as performed in metrics_reporter.py."""
    # Clear the log file.
    open(LOG_FILE_PATH, 'w').close()
    metrics.LogCommandParams(
        global_opts=[('-y', 'value'), ('-z', ''), ('-x', '')])

    # Collect a metric and set log level for the metrics_reporter subprocess.
    def CollectMetricAndSetLogLevel(log_level):
      metrics.LogCommandParams(command_name='cmd1', subcommands=['action1'],
                               sub_opts=[('optb', ''), ('opta', '')])
      metrics.LogFatalError(gslib.exception.CommandException('test'))

      # Wait for report to make sure the log is written before we check it.
      self.collector.ReportMetrics(wait_for_report=True, log_level=log_level)
      self.assertEqual([], self.collector._metrics)

    # The log file should be empty unless the debug option is specified.
    CollectMetricAndSetLogLevel(logging.DEBUG)
    with open(LOG_FILE_PATH, 'rb') as metrics_log:
      log_text = metrics_log.read()
    expected_request = (
        '_Metric(endpoint=\'https://example.com\', method=\'POST\', '
        'body=\'ec={0}&ea=cmd1+action1&el={1}&ev=0&cm2=0{2}\', '
        'user_agent=\'user-agent-007\')').format(metrics._GA_COMMANDS_CATEGORY,
                                                 VERSION, GLOBAL_DIMENSIONS_URL)
    self.assertIn(expected_request, log_text)
    self.assertIn('RESPONSE: 200', log_text)

    CollectMetricAndSetLogLevel(logging.INFO)
    with open(LOG_FILE_PATH, 'rb') as metrics_log:
      log_text = metrics_log.read()
    self.assertEqual(log_text, '')

    CollectMetricAndSetLogLevel(logging.WARN)
    with open(LOG_FILE_PATH, 'rb') as metrics_log:
      log_text = metrics_log.read()
    self.assertEqual(log_text, '')

  def testMetricsReportingWithFail(self):
    """Tests that metrics reporting error does not throw an exception."""
    popen_mock = self._StartObjectPatch(subprocess, 'Popen')
    popen_mock.side_effect = OSError()

    self.collector._metrics.append('dummy metric')
    # Shouldn't raise an exception.
    self.collector.ReportMetrics()

    self.assertTrue(popen_mock.called)

  def testCommandCollection(self):
    """Tests the collection of commands."""
    stderr = self._RunGsUtilWithAnalyticsOutput(['-m', 'acl', 'set', '-a'],
                                                expected_status=1)
    self.assertIn('ec=Command&ea=acl+set', stderr)
    # Check that the options were collected.
    self.assertIn('cd3=a', stderr)
    self.assertIn('cd2=d%2Cm', stderr)

    stderr = self._RunGsUtilWithAnalyticsOutput(['ver'])
    self.assertIn('ec=Command&ea=version', stderr)
    # Check the recording of the command alias.
    self.assertIn('cd5=ver', stderr)

  def testRetryableErrorMetadataCollection(self):
    """Tests that retryable errors are collected on JSON metadata operations."""
    # Retryable errors will only be collected with the JSON API.
    if self.test_api != ApiSelector.JSON:
      return unittest.skip('Retryable errors are only collected in JSON')

    bucket_uri = self.CreateBucket()
    object_uri = self.CreateObject(bucket_uri=bucket_uri,
                                   object_name='foo',
                                   contents='bar')
    # Generate a JSON API instance because the RunGsUtil method uses the XML
    # API.
    gsutil_api = GcsJsonApi(BucketStorageUri, logging.getLogger(),
                            RetryableErrorsQueue(), self.default_provider)
    # Don't wait for too many retries or for long periods between retries to
    # avoid long tests.
    gsutil_api.api_client.num_retries = 2
    gsutil_api.api_client.max_retry_wait = 1

    # Throw an error when transferring metadata.
    key = object_uri.get_key()
    src_obj_metadata = apitools_messages.Object(name=key.name,
                                                bucket=key.bucket.name,
                                                contentType=key.content_type)
    dst_obj_metadata = apitools_messages.Object(
        bucket=src_obj_metadata.bucket,
        name=self.MakeTempName('object'),
        contentType=src_obj_metadata.contentType)
    with mock.patch.object(http_wrapper, '_MakeRequestNoRetry',
                           side_effect=socket.error()):
      _TryExceptAndPass(gsutil_api.CopyObject, src_obj_metadata,
                        dst_obj_metadata)
    self.assertEqual(self.collector.retryable_errors['SocketError'], 1)

    # Throw an error when removing a bucket.
    with mock.patch.object(http_wrapper, '_MakeRequestNoRetry',
                           side_effect=ValueError()):
      _TryExceptAndPass(gsutil_api.DeleteObject, bucket_uri.bucket_name,
                        object_uri.object_name)
    self.assertEqual(self.collector.retryable_errors['ValueError'], 1)

  def testRetryableErrorMediaCollection(self):
    """Tests that retryable errors are collected on JSON media operations."""
    # Retryable errors will only be collected with the JSON API.
    if self.test_api != ApiSelector.JSON:
      return unittest.skip('Retryable errors are only collected in JSON')

    boto_config_for_test = [('GSUtil', 'resumable_threshold', str(ONE_KIB))]
    bucket_uri = self.CreateBucket()
    # For the resumable upload exception, we need to ensure at least one
    # callback occurs.
    halt_size = START_CALLBACK_PER_BYTES * 2
    fpath = self.CreateTempFile(contents='a' * halt_size)

    # Test that the retry function for data transfers catches and logs an error.
    test_callback_file = self.CreateTempFile(contents=pickle.dumps(
        _ResumableUploadRetryHandler(5, apitools_exceptions.BadStatusCodeError,
                                     ('unused', 'unused', 'unused'))))
    with SetBotoConfigForTest(boto_config_for_test):
      stderr = self._RunGsUtilWithAnalyticsOutput(['cp', '--testcallbackfile',
                                                   test_callback_file, fpath,
                                                   suri(bucket_uri)])
      self.assertIn('ec=RetryableError&ea=BadStatusCodeError', stderr)
      self.assertIn('cm2=1', stderr)

    # Test that the ResumableUploadStartOverException in copy_helper is caught.
    test_callback_file = self.CreateTempFile(
        contents=pickle.dumps(_JSONForceHTTPErrorCopyCallbackHandler(5, 404)))
    with SetBotoConfigForTest(boto_config_for_test):
      stderr = self._RunGsUtilWithAnalyticsOutput(['cp', '--testcallbackfile',
                                                   test_callback_file, fpath,
                                                   suri(bucket_uri)])
      self.assertIn('ec=RetryableError&ea=ResumableUploadStartOverException',
                    stderr)
      self.assertIn('cm2=1', stderr)

    # Test retryable error collection in a multithread/multiprocess situation.
    test_callback_file = self.CreateTempFile(
        contents=pickle.dumps(_JSONForceHTTPErrorCopyCallbackHandler(5, 404)))
    with SetBotoConfigForTest(boto_config_for_test):
      stderr = self._RunGsUtilWithAnalyticsOutput(['-m', 'cp',
                                                   '--testcallbackfile',
                                                   test_callback_file, fpath,
                                                   suri(bucket_uri)])
      self.assertIn('ec=RetryableError&ea=ResumableUploadStartOverException',
                    stderr)
      self.assertIn('cm2=1', stderr)

  def testFatalErrorCollection(self):
    """Tests that fatal errors are collected."""
    stderr = self._RunGsUtilWithAnalyticsOutput(['invalid-command'],
                                                expected_status=1)
    self.assertIn('ec=FatalError&ea=CommandException', stderr)

    stderr = self._RunGsUtilWithAnalyticsOutput(['mb', '-invalid-option'],
                                                expected_status=1)
    self.assertIn('ec=FatalError&ea=CommandException', stderr)

    bucket_uri = self.CreateBucket()
    stderr = self._RunGsUtilWithAnalyticsOutput(
        ['cp', suri(bucket_uri), suri(bucket_uri)],
        expected_status=1)
    self.assertIn('ec=FatalError&ea=CommandException', stderr)
