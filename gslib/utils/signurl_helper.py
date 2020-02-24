# -*- coding: utf-8 -*-
# Copyright 2014 Google Inc. All Rights Reserved.
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
"""Utility functions for signurl command."""

import base64
from datetime import datetime
import hashlib

from gslib.utils.constants import UTF8
import six
from six.moves import urllib

_CANONICAL_REQUEST_FORMAT = ('{method}\n{resource}\n{query_string}\n{headers}'
                             '\n{signed_headers}\n{hashed_payload}')
_SIGNING_ALGO = 'GOOG4-RSA-SHA256'
_STRING_TO_SIGN_FORMAT = ('{signing_algo}\n{request_time}\n{credential_scope}'
                          '\n{hashed_request}')
_SIGNED_URL_FORMAT = ('https://{host}/{path}?x-goog-signature={sig}&'
                      '{query_string}')
_UNSIGNED_PAYLOAD = 'UNSIGNED-PAYLOAD'


def CreatePayload(client_id,
                  method,
                  duration,
                  path,
                  logger,
                  region,
                  signed_headers,
                  string_to_sign_debug=False):
  """TODO: Add function description."""
  signing_time = datetime.utcnow()

  canonical_day = signing_time.strftime('%Y%m%d')
  canonical_time = signing_time.strftime('%Y%m%dT%H%M%SZ')
  canonical_scope = '{date}/{region}/storage/goog4_request'.format(
      date=canonical_day, region=region)

  signed_query_params = {
      'x-goog-algorithm': _SIGNING_ALGO,
      'x-goog-credential': client_id + '/' + canonical_scope,
      'x-goog-date': canonical_time,
      'x-goog-signedheaders': ';'.join(sorted(signed_headers.keys())),
      'x-goog-expires': '%d' % duration.total_seconds()
  }

  canonical_resource = '/{}'.format(path)
  canonical_query_string = '&'.join([
      '{}={}'.format(param, urllib.parse.quote_plus(signed_query_params[param]))
      for param in sorted(signed_query_params.keys())
  ])
  canonical_headers = '\n'.join([
      '{}:{}'.format(header.lower(), signed_headers[header])
      for header in sorted(signed_headers.keys())
  ]) + '\n'
  canonical_signed_headers = ';'.join(sorted(signed_headers.keys()))

  canonical_request = _CANONICAL_REQUEST_FORMAT.format(
      method=method,
      resource=canonical_resource,
      query_string=canonical_query_string,
      headers=canonical_headers,
      signed_headers=canonical_signed_headers,
      hashed_payload=_UNSIGNED_PAYLOAD)

  if six.PY3:
    canonical_request = canonical_request.encode(UTF8)

  canonical_request_hasher = hashlib.sha256()
  canonical_request_hasher.update(canonical_request)
  hashed_canonical_request = base64.b16encode(
      canonical_request_hasher.digest()).lower().decode(UTF8)

  string_to_sign = _STRING_TO_SIGN_FORMAT.format(
      signing_algo=_SIGNING_ALGO,
      request_time=canonical_time,
      credential_scope=canonical_scope,
      hashed_request=hashed_canonical_request)

  if string_to_sign_debug and logger:
    logger.debug(
        'Canonical request (ignore opening/closing brackets): [[[%s]]]' %
        canonical_request)
    logger.debug('String to sign (ignore opening/closing brackets): [[[%s]]]' %
                 string_to_sign)

  return string_to_sign, canonical_query_string


def GetFinalUrl(raw_signature, host, path, canonical_query_string):
  signature = base64.b16encode(raw_signature).lower().decode()
  return _SIGNED_URL_FORMAT.format(host=host,
                                   path=path,
                                   sig=signature,
                                   query_string=canonical_query_string)
