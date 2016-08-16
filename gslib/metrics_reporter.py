# Copyright 2016 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Script for reporting metrics."""

import logging
import os
import pickle
import sys

try:
  from gslib.util import GetNewHttp  # pylint:disable=g-import-not-at-top
except Exception:  # pylint: disable=broad-except
  # Do nothing if we can't import the lib.
  sys.exit(0)

LOG_FILE_PATH = os.path.expanduser(os.path.join('~', '.gsutil/metrics.log'))


def ReportMetrics(metrics_file_path, log_level):
  """Sends the specified anonymous usage event to the given analytics endpoint.

  Args:
      metrics_file_path: str, File with pickled metrics (list of tuples).
      log_level: int, The logging level of gsutil's root logger.
  """
  logger = logging.getLogger()
  handler = logging.FileHandler(LOG_FILE_PATH, mode='w')
  logger.addHandler(handler)
  logger.setLevel(log_level)

  with open(metrics_file_path, 'rb') as metrics_file:
    metrics = pickle.load(metrics_file)
  os.remove(metrics_file_path)

  http = GetNewHttp()

  for metric in metrics:
    try:
      headers = {'User-Agent': metric.user_agent}
      response = http.request(metric.endpoint,
                              method=metric.method,
                              body=metric.body,
                              headers=headers)
      logger.debug(metric)
      logger.debug('RESPONSE: %s', response[0]['status'])
    except Exception as e:  # pylint: disable=broad-except
      logger.debug(e)
