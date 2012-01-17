# Copyright 2011 Google Inc.
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

# This code implements an OAUTH2 plugin that reads the access token from
# App Engine StorageByKeyName.

from oauth2client.appengine import CredentialsProperty
from oauth2client.appengine import StorageByKeyName
from google.appengine.api import users
from google.appengine.ext import db
from boto.auth_handler import AuthHandler
from boto.auth_handler import NotReadyToAuthenticate 


class Credentials(db.Model):
  credentials = CredentialsProperty()


class OAuth2Auth(AuthHandler):

  capability = ['google-oauth2', 's3']

  def __init__(self, path, config, provider):
    if provider.name != 'google':
      raise NotReadyToAuthenticate()

  def add_auth(self, http_request):
    user = users.get_current_user()
    credentials = StorageByKeyName(
        Credentials, user.user_id(), 'credentials').get()
    if not credentials or credentials.invalid:
      raise NotReadyToAuthenticate()
    http_request.headers['Authorization'] = (
        'Bearer %s' % str(credentials.access_token))
