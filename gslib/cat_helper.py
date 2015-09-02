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
"""Helper for cat and cp streaming download."""

from __future__ import absolute_import

import sys

from gslib.cloud_api import EncryptionException
from gslib.encryption_helper import CryptoTupleFromKey
from gslib.encryption_helper import FindMatchingCryptoKey
from gslib.exception import CommandException
from gslib.exception import NO_URLS_MATCHED_TARGET
from gslib.util import ObjectIsGzipEncoded
from gslib.wildcard_iterator import StorageUrlFromString


class CatHelper(object):

  def __init__(self, command_obj):
    """Initializes the helper object.

    Args:
      command_obj: gsutil command instance of calling command.
    """
    self.command_obj = command_obj

  def CatUrlStrings(self, url_strings, show_header=False, start_byte=0,
                    end_byte=None):
    """Prints each of the url strings to stdout.

    Args:
      url_strings: String iterable.
      show_header: If true, print a header per file.
      start_byte: Starting byte of the file to print, used for constructing
                  range requests.
      end_byte: Ending byte of the file to print; used for constructing range
                requests. If this is negative, the start_byte is ignored and
                and end range is sent over HTTP (such as range: bytes -9)
    Returns:
      0 on success.

    Raises:
      CommandException if no URLs can be found.
    """
    printed_one = False
    # We manipulate the stdout so that all other data other than the Object
    # contents go to stderr.
    cat_outfd = sys.stdout
    sys.stdout = sys.stderr
    try:
      for url_str in url_strings:
        did_some_work = False
        # TODO: Get only the needed fields here.
        for blr in self.command_obj.WildcardIterator(url_str).IterObjects():

          decryption_tuple = None
          if (blr.root_object and
              blr.root_object.customerEncryption and
              blr.root_object.customerEncryption.keySha256):
            decryption_key = FindMatchingCryptoKey(
                blr.root_object.customerEncryption.keySha256)
            if not decryption_key:
              raise EncryptionException(
                  'Missing decryption key with SHA256 hash %s. No decryption '
                  'key matches object %s'
                  % (blr.root_object.customerEncryption.keySha256,
                     blr.url_string))
            decryption_tuple = CryptoTupleFromKey(decryption_key)

          did_some_work = True
          if show_header:
            if printed_one:
              print
            print '==> %s <==' % blr
            printed_one = True
          cat_object = blr.root_object
          storage_url = StorageUrlFromString(blr.url_string)
          if storage_url.IsCloudUrl():
            compressed_encoding = ObjectIsGzipEncoded(cat_object)
            self.command_obj.gsutil_api.GetObjectMedia(
                cat_object.bucket, cat_object.name, cat_outfd,
                compressed_encoding=compressed_encoding,
                start_byte=start_byte, end_byte=end_byte,
                object_size=cat_object.size, generation=storage_url.generation,
                decryption_tuple=decryption_tuple, provider=storage_url.scheme)
          else:
            cat_outfd.write(open(storage_url.object_name, 'rb').read())
        if not did_some_work:
          raise CommandException(NO_URLS_MATCHED_TARGET % url_str)
      sys.stdout = cat_outfd
    finally:
      sys.stdout = cat_outfd

    return 0
