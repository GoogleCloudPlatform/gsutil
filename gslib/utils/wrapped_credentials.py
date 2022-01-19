import copy
import datetime
import json

import google.auth.aws
import google.auth.credentials
import google.auth.identity_pool

import oauth2client
from google.auth.transport import requests
from gslib.utils import constants

# Expiry is stored in RFC3339 UTC format
EXPIRY_FORMAT = '%Y-%m-%dT%H:%M:%SZ'

DEFAULT_SCOPES = [
    constants.Scopes.CLOUD_PLATFORM,
    constants.Scopes.CLOUD_PLATFORM_READ_ONLY,
    constants.Scopes.FULL_CONTROL,
    constants.Scopes.READ_ONLY,
    constants.Scopes.READ_WRITE,
]


class WrappedCredentials(oauth2client.client.OAuth2Credentials):

  def __init__(self, base):
    if not isinstance(base, google.auth.credentials.Credentials):
      raise TypeError("Invalid Credentials")
    self._base = base
    super(WrappedCredentials, self).__init__(None, base._audience, None, None,
                                             None, None, None)

  def _do_refresh_request(self, http):
    self._base.refresh(requests.Request())
    if self.store is not None:
      self.store.locked_put(self)

  @property
  def access_token(self):
    return self._base.token

  @access_token.setter
  def access_token(self, value):
    self._base.token = value

  @property
  def token_expiry(self):
    return self._base.expiry

  @token_expiry.setter
  def token_expiry(self, value):
    self._base.expiry = value

  def _to_json(self, strip, to_serialize=None):
    """Utility function that creates JSON repr. of a Credentials object.

    Args:
        strip: array, An array of names of members to exclude from the
                JSON.
        to_serialize: dict, (Optional) The properties for this object
                      that will be serialized. This allows callers to
                      modify before serializing.

    Returns:
        string, a JSON representation of this instance, suitable to pass to
        from_json().
    """
    curr_type = self.__class__
    if to_serialize is None:
      to_serialize = copy.copy(self.__dict__)
    else:
      # Assumes it is a str->str dictionary, so we don't deep copy.
      to_serialize = copy.copy(to_serialize)
    for member in strip:
      if member in to_serialize:
        del to_serialize[member]
    # Add in information we will need later to reconstitute this instance.
    to_serialize['_class'] = curr_type.__name__
    to_serialize['_module'] = curr_type.__module__
    # Make base serializable.
    to_serialize['_base'] = copy.copy(self._base.info)
    # Serialize token and expiration.
    to_serialize['access_token'] = self._base.token
    to_serialize['token_expiry'] = _parse_expiry(self.token_expiry)
    for key, val in to_serialize.items():
      if isinstance(val, bytes):
        to_serialize[key] = val.decode('utf-8')
      if isinstance(val, set):
        to_serialize[key] = list(val)
    return json.dumps(to_serialize)

  @classmethod
  def for_external_account(cls, filename):
    creds = _get_external_account_credentials_from_file(filename)
    return cls(creds)

  @classmethod
  def from_json(cls, json_data):
    """Instantiate a Credentials object from a JSON description of it.

    The JSON should have been produced by calling .to_json() on the object.

    Args:
        data: dict, A deserialized JSON object.

    Returns:
        An instance of a Credentials subclass.
    """
    data = json.loads(json_data)
    # Rebuild the credentials.
    base = data.get("_base")
    # Init base cred.
    external_account_creds = _get_external_account_credentials_from_info(base)
    creds = cls(external_account_creds)
    # Inject token and expiry.
    creds.access_token = data.get("access_token")
    if (data.get('token_expiry') and
        not isinstance(data['token_expiry'], datetime.datetime)):
      try:
        data['token_expiry'] = datetime.datetime.strptime(
            data['token_expiry'], EXPIRY_FORMAT)
      except ValueError:
        data['token_expiry'] = None
    creds.token_expiry = data.get("token_expiry")
    return creds


def _get_external_account_credentials_from_info(info):
  try:
    # Check if configuration corresponds to an AWS credentials.
    creds = google.auth.aws.Credentials.from_info(info, scopes=DEFAULT_SCOPES)
  except Exception as e:
    try:
      # Check if configuration corresponds to an Identity Pool credentials.
      creds = google.auth.identity_pool.Credentials.from_info(
          info, scopes=DEFAULT_SCOPES)
    except Exception as e:
      # If the configuration is invalid or does not correspond to any
      # supported external_account credentials, raise an error.
      return None
  return creds


def _get_external_account_credentials_from_file(filename):
  try:
    # Check if configuration corresponds to an AWS credentials.
    creds = google.auth.aws.Credentials.from_file(filename,
                                                  scopes=DEFAULT_SCOPES)
  except Exception as e:
    try:
      # Check if configuration corresponds to an Identity Pool credentials.
      creds = google.auth.identity_pool.Credentials.from_file(
          filename, scopes=DEFAULT_SCOPES)
    except Exception as e:
      # If the configuration is invalid or does not correspond to any
      # supported external_account credentials, raise an error.
      return None
  return creds


def _parse_expiry(expiry):
  if expiry and isinstance(expiry, datetime.datetime):
    return expiry.strftime(EXPIRY_FORMAT)
  else:
    return None
