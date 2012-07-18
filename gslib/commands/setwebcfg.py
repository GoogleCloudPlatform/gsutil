# Copyright 2012 Google Inc.
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

from gslib.command import Command
from gslib.command import COMMAND_NAME
from gslib.command import COMMAND_NAME_ALIASES
from gslib.command import CONFIG_REQUIRED
from gslib.command import FILE_URIS_OK
from gslib.command import MAX_ARGS
from gslib.command import MIN_ARGS
from gslib.command import PROVIDER_URIS_OK
from gslib.command import SUPPORTED_SUB_ARGS
from gslib.command import URIS_START_ARG
from gslib.exception import CommandException
from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HelpType
from gslib.help_provider import HELP_TYPE
from gslib.util import NO_MAX


_detailed_help_text = ("""
<B>SYNOPSIS</B>
  gsutil setwebcfg [-m main_page_suffix] [-e error_page] bucket_uri...


<B>DESCRIPTION</B>
  The Website Configuration feature enables you to configure a Google Cloud
  Storage bucket to simulate the behavior of a static website. You can define
  main pages or directory indices (for example, index.html) for buckets and
  "directories". Also, you can define a custom error page in case a requested
  resource does not exist.

  The gstuil setwebcfg command allows you to configure use of web semantics
  on one or more buckets. The main page suffix and error page parameters are
  specified as arguments to the -m and -e flags respectively. If either or
  both parameters are excluded, the corresponding behavior will be disabled
  on the target bucket.
""")

def BuildGSWebConfig(main_page_suffix=None, not_found_page=None):
  config_body_l = ['<WebsiteConfiguration>']
  if main_page_suffix:
    config_body_l.append('<MainPageSuffix>%s</MainPageSuffix>' %
                         main_page_suffix)
  if not_found_page:
    config_body_l.append('<NotFoundPage>%s</NotFoundPage>' %
                         not_found_page)
  config_body_l.append('</WebsiteConfiguration>')
  return "".join(config_body_l)

def BuildS3WebConfig(main_page_suffix=None, error_page=None):
  config_body_l = ['<WebsiteConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/">']
  if not main_page_suffix:
      raise CommandException('S3 requires main page / index document')
  config_body_l.append('<IndexDocument><Suffix>%s</Suffix></IndexDocument>' %
                       main_page_suffix)
  if error_page:
    config_body_l.append('<ErrorDocument><Key>%s</Key></ErrorDocument>' %
                         error_page)
  config_body_l.append('</WebsiteConfiguration>')
  return "".join(config_body_l)

class SetWebcfgCommand(Command):
  """Implementation of gsutil setwebcfg command."""

  # Command specification (processed by parent class).
  command_spec = {
    # Name of command.
    COMMAND_NAME : 'setwebcfg',
    # List of command name aliases.
    COMMAND_NAME_ALIASES : [],
    # Min number of args required by this command.
    MIN_ARGS : 1,
    # Max number of args required by this command, or NO_MAX.
    MAX_ARGS : NO_MAX,
    # Getopt-style string specifying acceptable sub args.
    SUPPORTED_SUB_ARGS : 'm:e:',
    # True if file URIs acceptable for this command.
    FILE_URIS_OK : False,
    # True if provider-only URIs acceptable for this command.
    PROVIDER_URIS_OK : False,
    # Index in args of first URI arg.
    URIS_START_ARG : 1,
    # True if must configure gsutil before running command.
    CONFIG_REQUIRED : True,
  }
  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'setwebcfg',
    # List of help name aliases.
    HELP_NAME_ALIASES : [],
    # Type of help)
    HELP_TYPE : HelpType.COMMAND_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Set a main page and/or error page for one or more buckets',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }


  # Command entry point.
  def RunCommand(self):
    main_page_suffix = None
    error_page = None
    if self.sub_opts:
      for o, a in self.sub_opts:
        if o == '-m':
          main_page_suffix = a
        elif o == '-e':
          error_page = a

    uri_args = self.args

    # Iterate over URIs, expanding wildcards, and setting the website
    # configuration on each.
    some_matched = False
    for uri_str in uri_args:
      for blr in self.WildcardIterator(uri_str):
        uri = blr.GetUri()
        if not uri.names_bucket():
          raise CommandException('URI %s must name a bucket for the %s command'
                                 % (str(uri), self.command_name))
        some_matched = True
        print 'Setting website config on %s...' % uri
        uri.set_website_config(main_page_suffix, error_page)
    if not some_matched:
      raise CommandException('No URIs matched')

  webcfg_full = (
'''<?xmlversion="1.0"?>
<WebsiteConfiguration>
<MainPageSuffix>
main
</MainPageSuffix>
<NotFoundPage>
404
</NotFoundPage>
</WebsiteConfiguration>
''')

  webcfg_main = (
'''<?xmlversion="1.0"?>
<WebsiteConfiguration>
<MainPageSuffix>
main
</MainPageSuffix>
</WebsiteConfiguration>
''')

  webcfg_error = (
'''<?xmlversion="1.0"?>
<WebsiteConfiguration>
<NotFoundPage>
404
</NotFoundPage>
</WebsiteConfiguration>
''')

  webcfg_empty = (
'''<?xmlversion="1.0"?>
<WebsiteConfiguration/>
''')

  test_steps = [
    ('1. setup webcfg_full', 'echo \'%s\' > $F0' % webcfg_full, 0, None),
    ('2. apply full config', 'gsutil setwebcfg -m main -e 404 gs://$B0', 0, None),
    ('3. check full config', 'gsutil getwebcfg gs://$B0 '
        '| grep -v \'^Getting website config on\' '
        '| sed \'s/\s//g\' > $F1', 0, ('$F0', '$F1')),
    ('4. setup webcfg_main', 'echo \'%s\' > $F0' % webcfg_main, 0, None),
    ('5. apply config_main', 'gsutil setwebcfg -m main gs://$B0', 0, None),
    ('6. check config_main', 'gsutil getwebcfg gs://$B0 '
        '| grep -v \'^Getting website config on\' '
        '| sed \'s/\s//g\' > $F1', 0, ('$F0', '$F1')),
    ('7. setup webcfg_error', 'echo \'%s\' > $F0' % webcfg_error, 0, None),
    ('8. apply config_error', 'gsutil setwebcfg -e 404 gs://$B0', 0, None),
    ('9. check config_error', 'gsutil getwebcfg gs://$B0 '
        '| grep -v \'^Getting website config on\' '
        '| sed \'s/\s//g\' > $F1', 0, ('$F0', '$F1')),
    ('10. setup webcfg_empty', 'echo \'%s\' > $F0' % webcfg_empty, 0, None),
    ('11. remove config', 'gsutil setwebcfg gs://$B0', 0, None),
    ('12. check empty config', 'gsutil getwebcfg gs://$B0 '
        '| grep -v \'^Getting website config on\' '
        '| sed \'s/\s//g\' > $F1', 0, ('$F0', '$F1')),
  ]
