#!/usr/bin/env python
#
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

import boto
import pickle

from google.appengine.api import memcache
from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import util
from google.appengine.ext.webapp.util import login_required
from oauth2_plugin import Credentials
from oauth2client.appengine import StorageByKeyName
from oauth2client.client import OAuth2WebServerFlow


class MainHandler(webapp.RequestHandler):

  @login_required
  def get(self):
    user = users.get_current_user()
    credentials = StorageByKeyName(
        Credentials, user.user_id(), 'credentials').get()

    if not credentials or credentials.invalid:
      # Fill out the client ID and secret you created from the Developer
      # Console below. Also you need to edit the redirect URI into the Dev
      # Console, and that value needs to be updated when you move from
      # running this app locally to running on Google App Server (else you'll
      # get a 'redirect_uri_mismatch' error).
      flow = OAuth2WebServerFlow(
          client_id='<YOUR_CLIENT_ID>',
          client_secret='<YOUR_CLIENT_SECRET>',
          scope='https://www.googleapis.com/auth/devstorage.read_only',
          user_agent='cloudauth-sample',
          auth_uri='https://accounts.google.com/o/oauth2/auth',
          token_uri='https://accounts.google.com/o/oauth2/token')
      callback = self.request.relative_url('/auth_return')
      authorize_url = flow.step1_get_authorize_url(callback)
      memcache.set(user.user_id(), pickle.dumps(flow))
      self.redirect(authorize_url)
    else:
      try:
        # List the user's buckets. This always requires auth, so will fail
        # if authorization didn't succeed.
        uri = boto.storage_uri('gs://')
        self.response.headers['Content-Type'] = 'text/plain'
        self.response.out.write(uri.get_all_buckets())
      except boto.exception.GSResponseError, e:
        if e.error_code == 'AccessDenied':
          StorageByKeyName(
              Credentials, user.user_id(), 'credentials').put(None)
          self.redirect('/')
        else:
          self.response.out.write('Got error: %s' % str(e))



class AuthHandler(webapp.RequestHandler):

  @login_required
  def get(self):
    user = users.get_current_user()
    flow = pickle.loads(memcache.get(user.user_id()))
    # This code should be ammended with application specific error
    # handling. The following cases should be considered:
    # 1. What if the flow doesn't exist in memcache? Or is corrupt?
    # 2. What if the step2_exchange fails?
    if flow:
      credentials = flow.step2_exchange(self.request.params)
      StorageByKeyName(
          Credentials, user.user_id(), 'credentials').put(credentials)
      self.redirect('/')
    else:
      # Add application specific error handling here.
      pass


def main():
  application = webapp.WSGIApplication(
      [
      ('/', MainHandler),
      ('/auth_return', AuthHandler)
      ],
      debug=True)
  util.run_wsgi_app(application)


if __name__ == '__main__':
  main()
