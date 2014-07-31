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
"""Implementation of Url Signing workflow.

see: https://developers.google.com/storage/docs/accesscontrol#Signed-URLs)
"""

from __future__ import absolute_import

import base64
import calendar
from datetime import datetime
from datetime import timedelta
import getpass
import re
import time
import urllib

import httplib2

from gslib.command import Command
from gslib.cs_api_map import ApiSelector
from gslib.exception import CommandException
from gslib.storage_url import ContainsWildcard
from gslib.storage_url import StorageUrlFromString
from gslib.util import GetNewHttp
from gslib.util import NO_MAX

try:
  # Check for openssl.
  # pylint: disable=C6204
  from OpenSSL.crypto import load_pkcs12
  from OpenSSL.crypto import sign
  HAVE_OPENSSL = True
except ImportError:
  load_pkcs12 = None
  sign = None
  HAVE_OPENSSL = False

_DETAILED_HELP_TEXT = ("""
<B>SYNOPSIS</B>
  gsutil signurl pkcs12-file url...


<B>DESCRIPTION</B>
  The signurl command will generate signed urls that can be used to access
  the specified objects without authentication for a specific period of time.

  Please see the `Signed URLs documentation
  https://developers.google.com/storage/docs/accesscontrol#Signed-URLs` for
  background about signed URLs.

  Multiple gs:// urls may be provided and may contain wildcards.  A signed url
  will be produced for each provided url, authorized
  for the specified HTTP method and valid for the given duration.

  Note: Unlike the gsutil ls command, the signurl command does not support
  operations on sub-directories. For example, if you run the command:

    gsutil signurl <private-key-file> gs://some-bucket/some-object/

  The signurl command uses the private key for a  service account (the
  '<private-key-file>' argument) to generate the cryptographic
  signature for the generated URL.  The private key file must be in PKCS12
  format. The signurl command will prompt for the passphrase used to protect
  the private key file (default 'notasecret').  For more information
  regarding generating a private key for use with the signurl command please
  see the `Authentication documentation.
  https://developers.google.com/storage/docs/authentication#generating-a-private-key`

  gsutil will look up information about the object "some-object/" (with a
  trailing slash) inside bucket "some-bucket", as opposed to operating on
  objects nested under gs://some-bucket/some-object. Unless you actually
  have an object with that name, the operation will fail.

<B>OPTIONS</B>
  -m          Specifies the HTTP method to be authorized for use
              with the signed url, default is GET.

  -d          Specifies the duration that the signed url should be valid
              for, default duration is 1 hour.

              Times may be specified with no suffix (default hours), or
              with s = seconds, m = minutes, h = hours, d = days.

              This option may be specified multiple times, in which case
              the duration the link remains valid is the sum of all the
              duration options.

  -c          Specifies the content type for which the signed url is
              valid for.

  -p          Specify the keystore password instead of prompting.

<B>USAGE</B>

  Create a signed url for downloading an object valid for 10 minutes:

    gsutil signurl <private-key-file> -d 10m gs://<bucket>/<object>

  Create a signed url for uploading a plain text file via HTTP PUT:

    gsutil signurl <private-key-file> -m PUT -d 1h gs://<bucket>/<object>

  To construct a signed URL that allows anyone in possession of
  the URL to PUT to the specified bucket for one day, creating
  any object of Content-Type image/jpg, run:

    gsutil signurl <private-key-file> -m PUT -d 1d -c image/jpg gs://<bucket>/<obj>


""")


def _DurationToTimeDelta(duration):
  r"""Parses the given duration and returns an equivalent timedelta."""

  match = re.match(r'^(\d+)([dDhHmMsS])?$', duration)
  if not match:
    raise CommandException('Unable to parse duration string')

  duration, modifier = match.groups('h')
  duration = int(duration)
  modifier = modifier.lower()

  if modifier == 'd':
    ret = timedelta(days=duration)
  elif modifier == 'h':
    ret = timedelta(hours=duration)
  elif modifier == 'm':
    ret = timedelta(minutes=duration)
  elif modifier == 's':
    ret = timedelta(seconds=duration)

  return ret


def _GenSignedUrl(key, client_id, method, md5,
                  content_type, expiration, gcs_path):
  """Construct a string to sign with the provided key and returns \
  the complete url."""

  tosign = ('{0}\n{1}\n{2}\n{3}\n/{4}'
            .format(method, md5, content_type,
                    expiration, gcs_path))
  signature = base64.b64encode(sign(key, tosign, 'RSA-SHA256'))

  final_url = ('https://storage.googleapis.com/{0}?'
               'GoogleAccessId={1}&Expires={2}&Signature={3}'
               .format(gcs_path, client_id, expiration,
                       urllib.quote_plus(str(signature))))

  return final_url


def _ReadKeystore(ks_contents, passwd):
  ks = load_pkcs12(ks_contents, passwd)
  client_id = (ks.get_certificate()
               .get_subject()
               .CN.replace('.apps.googleusercontent.com',
                           '@developer.gserviceaccount.com'))

  return ks, client_id


class UrlSignCommand(Command):
  """Implementation of gsutil url_sign command."""

  # Command specification. See base class for documentation.
  command_spec = Command.CreateCommandSpec(
      'signurl',
      command_name_aliases=['signedurl', 'queryauth'],
      min_args=2,
      max_args=NO_MAX,
      supported_sub_args='m:d:c:p:',
      file_url_ok=False,
      provider_url_ok=False,
      urls_start_arg=1,
      gs_api_support=[ApiSelector.XML, ApiSelector.JSON],
      gs_default_api=ApiSelector.JSON,
  )
  # Help specification. See help_provider.py for documentation.
  help_spec = Command.HelpSpec(
      help_name='signurl',
      help_name_aliases=['signedurl', 'queryauth'],
      help_type='command_help',
      help_one_line_summary='Create a signed url',
      help_text=_DETAILED_HELP_TEXT,
      subcommand_help_text={},
  )

  def _ParseSubOpts(self):
    # Default argument values
    delta = None
    method = 'GET'
    content_type = ''
    passwd = None

    for o, v in self.sub_opts:
      if o == '-d':
        if delta is not None:
          delta += _DurationToTimeDelta(v)
        else:
          delta = _DurationToTimeDelta(v)
      elif o == '-m':
        method = v
      elif o == '-c':
        content_type = v
      elif o == '-p':
        passwd = v

    if delta is None:
      delta = timedelta(hours=1)

    expiration = calendar.timegm((datetime.utcnow() + delta).utctimetuple())
    if method not in ['GET', 'PUT', 'DELETE', 'HEAD']:
      raise CommandException('HTTP method must be one of [GET|HEAD|PUT|DELETE]')

    return method, expiration, content_type, passwd

  def _CheckClientCanRead(self, key, client_id, gcs_path):
    """Performs a head request against a signed url to check for read access."""

    signed_url = _GenSignedUrl(key, client_id,
                               'HEAD', '', '',
                               int(time.time()) + 10,
                               gcs_path)
    h = GetNewHttp()
    try:
      response, _ = h.request(signed_url, 'HEAD')

      return response.status == 200
    except httplib2.HttpLib2Error as e:
      raise CommandException('Unexpected error while querying'
                             'object readability ({0})'
                             .format(e.message))

  def _EnumerateStorageUrls(self, in_urls):
    ret = []

    for url_str in in_urls:
      url = StorageUrlFromString(url_str)

      if ContainsWildcard(url_str):
        ret.extend([StorageUrlFromString(blr.url_string)
                    for blr in self.WildcardIterator(url_str)])
      else:
        ret.append(url)

    return ret

  def RunCommand(self):
    """Command entry point for signurl command."""
    if not HAVE_OPENSSL:
      raise CommandException(
          'The signurl command requires the pyopenssl library (try pip '
          'install pyopenssl or easy_install pyopenssl)')

    method, expiration, content_type, passwd = self._ParseSubOpts()
    storage_urls = self._EnumerateStorageUrls(self.args[1:])

    if not passwd:
      passwd = getpass.getpass('Keystore password:')

    ks, client_id = _ReadKeystore(open(self.args[0], 'rb').read(), passwd)

    print 'URL\tHTTP Method\tExpiration\tSigned URL'
    for url in storage_urls:
      if url.scheme != 'gs':
        raise CommandException('Can only create signed urls from gs:// urls')
      if url.IsBucket():
        gcs_path = url.bucket_name
      else:
        gcs_path = '{0}/{1}'.format(url.bucket_name, url.object_name)

      final_url = _GenSignedUrl(ks.get_privatekey(), client_id,
                                method, '', content_type, expiration,
                                gcs_path)

      expiration_dt = datetime.fromtimestamp(expiration)

      print '{0}\t{1}\t{2}\t{3}'.format(url, method,
                                        (expiration_dt
                                         .strftime('%Y-%m-%d %H:%M:%S')),
                                        final_url)
      if  (method != 'PUT' and
           not self._CheckClientCanRead(ks.get_privatekey(),
                                        client_id,
                                        gcs_path)):
        self.logger.warn('{0} does not have permissions '
                         'on {1}, using this link will likely result '
                         'in a 403 error until at least READ permissions '
                         'are granted'.format(client_id, url))

    return 0
