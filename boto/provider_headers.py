# Copyright 2010 Google Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish, dis-
# tribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the fol-
# lowing conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABIL-
# ITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT
# SHALL THE AUTHOR BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.

# This class encapsulates the provider-specific header differences.

ACL_HEADER_KEY = 'acl_header'
AUTH_HEADER_KEY = 'auth_header'
AWS_HEADER_PREFIX = 'x-amz-'
COPY_SOURCE_HEADER_KEY = 'copy_source_header'
DATE_HEADER_KEY = 'date_header'
GOOG_HEADER_PREFIX = 'x-goog-'
HEADER_PREFIX_KEY = 'header_prefix'
METADATA_DIRECTIVE_HEADER_KEY = 'metadata_directive_header'
METADATA_PREFIX_KEY = 'metadata_prefix'
SECURITY_TOKEN_KEY = 'security-token'

class ProviderHeaders:

    ProviderHeaderInfoMap = {
        'aws' : {
            HEADER_PREFIX_KEY : AWS_HEADER_PREFIX,
            METADATA_PREFIX_KEY : AWS_HEADER_PREFIX + 'meta-',
            DATE_HEADER_KEY : AWS_HEADER_PREFIX + 'date',
            ACL_HEADER_KEY : AWS_HEADER_PREFIX + 'acl',
            AUTH_HEADER_KEY : 'AWS',
            COPY_SOURCE_HEADER_KEY : AWS_HEADER_PREFIX + 'copy-source',
            METADATA_DIRECTIVE_HEADER_KEY : AWS_HEADER_PREFIX +
                                            'metadata-directive',
            SECURITY_TOKEN_KEY : AWS_HEADER_PREFIX + 'security-token'
        },
        'google' : {
            HEADER_PREFIX_KEY : GOOG_HEADER_PREFIX,
            METADATA_PREFIX_KEY : GOOG_HEADER_PREFIX + 'meta-',
            DATE_HEADER_KEY : GOOG_HEADER_PREFIX + 'date',
            ACL_HEADER_KEY : GOOG_HEADER_PREFIX + 'acl',
            AUTH_HEADER_KEY : 'GOOG1',
            COPY_SOURCE_HEADER_KEY : GOOG_HEADER_PREFIX + 'copy-source',
            METADATA_DIRECTIVE_HEADER_KEY : GOOG_HEADER_PREFIX  +
                                            'metadata-directive',
            SECURITY_TOKEN_KEY : GOOG_HEADER_PREFIX + 'security-token'
        }
    }

    def __init__(self, provider):
        self.provider = provider
        header_info_map = self.ProviderHeaderInfoMap[self.provider]
        self.metadata_prefix = header_info_map[METADATA_PREFIX_KEY]
        self.header_prefix = header_info_map[HEADER_PREFIX_KEY]
        self.date_header = header_info_map[DATE_HEADER_KEY]
        self.acl_header = header_info_map[ACL_HEADER_KEY]
        self.auth_header = header_info_map[AUTH_HEADER_KEY]
        self.copy_source_header = header_info_map[COPY_SOURCE_HEADER_KEY]
        self.metadata_directive_header = (
            header_info_map[METADATA_DIRECTIVE_HEADER_KEY])
        self.security_token = header_info_map[SECURITY_TOKEN_KEY]

# Static utility method for getting default ProviderHeaders.
def get_default():
    return ProviderHeaders('aws')
