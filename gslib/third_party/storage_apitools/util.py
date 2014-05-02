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
"""Assorted utilities shared between parts of apitools."""

import collections
import httplib
import os
import types
import urllib2

from gslib.third_party.storage_apitools import exceptions

__all__ = [
    'DetectGae',
    'DetectGce',
]


def DetectGae():
  """Determine whether or not we're running on GAE.

  This is based on:
    https://developers.google.com/appengine/docs/python/#The_Environment

  Returns:
    True iff we're running on GAE.
  """
  server_software = os.environ.get('SERVER_SOFTWARE', '')
  return (server_software.startswith('Development/') or
          server_software.startswith('Google App Engine/'))


def DetectGce():
  """Determine whether or not we're running on GCE.

  This is based on:
    https://developers.google.com/compute/docs/instances#dmi

  Returns:
    True iff we're running on a GCE instance.
  """
  try:
    o = urllib2.urlopen('http://metadata.google.internal')
  except urllib2.URLError:
    return False
  return o.getcode() == httplib.OK


def NormalizeScopes(scope_spec):
  """Normalize scope_spec to a set of strings."""
  if isinstance(scope_spec, types.StringTypes):
    return set(scope_spec.split(' '))
  elif isinstance(scope_spec, collections.Iterable):
    return set(scope_spec)
  raise exceptions.TypecheckError(
      'NormalizeScopes expected string or iterable, found %s' % (
          type(scope_spec),))


def Typecheck(arg, arg_type, msg=None):
  if not isinstance(arg, arg_type):
    if msg is None:
      if isinstance(arg_type, tuple):
        msg = 'Type of arg is "%s", not one of %r' % (type(arg), arg_type)
      else:
        msg = 'Type of arg is "%s", not "%s"' % (type(arg), arg_type)
      raise exceptions.TypecheckError(msg)
  return arg
