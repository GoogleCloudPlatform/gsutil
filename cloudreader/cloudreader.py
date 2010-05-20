#!/usr/bin/env python
#
# Copyright 2010 Google Inc.
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

"""Example Google App Engine application."""

import os

# Point to our boto.cfg before importing boto, because boto statically
# initializes credentials when its loaded.
os.environ['BOTO_CONFIG'] = 'boto.cfg'
import boto

from boto.exception import S3ResponseError
from boto.pyami.config import Config
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

class MainPage(webapp.RequestHandler):
    def get(self):
        self.response.out.write('<html><body><pre>')
        try:
            uri = boto.storage_uri('gs://pub/shakespeare/rose.txt')
            poem = uri.get_contents_as_string()
            self.response.out.write('<pre>' + poem + '</pre>')
            self.response.out.write('</body></html>')
        except AttributeError, e:
            self.response.out.write('<b>Failure: %s</b>' % e)
        except S3ResponseError, e:
            self.response.out.write(
                '<b>Failure: status=%d, code=%s, reason=%s.</b>' %
                (e.status, e.code, e.reason))

def main():
    application = webapp.WSGIApplication([('/', MainPage)], debug=True)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()
