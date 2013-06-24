# Copyright 2013 Google Inc. All Rights Reserved.
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

from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HelpProvider
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HelpType
from gslib.help_provider import HELP_TYPE

_detailed_help_text = ("""
<B>OVERVIEW</B>
  Google Cloud Storage provides a cyclic redundancy check (CRC) header that
  allows clients to verify the integrity of composite object contents. All other
  download operations currently use MD5 for integrity checks, but support for
  CRC may be added in the future. The CRC variant used by Google Cloud Storage
  is called CRC32C (Castagnoli), which is not available in the standard Python
  distribution. The implementation of CRC32C used by gsutil is provided by a
  third-party Python module called
  `crcmod <https://pypi.python.org/pypi/crcmod>`_.

  The crcmod module contains a pure-Python implementation of CRC32C, but using
  it results in degraded performance, as the CPU becomes the bottleneck for
  transfers. A Python C extension is also provided by crcmod, which requires
  compiling into a binary module for use. gsutil ships with a precompiled
  crcmod C extension for Mac OS X; for other platforms, see installation
  instructions below.

  Since gsutil is platform agnostic, the
  compiled version of crcmod is not distributed with the gsutil release.


<B>CONFIGURATION</B>
  To determine if the compiled version of crcmod is available in your Python
  environment, you can inspect the output of the gsutil version command for the
  "compiled crcmod" entry::

    $ gsutil version -l
    ...
    compiled crcmod: True
    ...

  If your crcmod library is compiled to a native binary, this value will be
  True. If using the pure-Python version, the value will be False.

  To control gsutil's behavior in response to crcmod's status, you can set the
  "check_hashes" configuration variable. For details on this variable, see the
  surrounding comments in your gsutil configuration file. If check_hashes is not
  present in your configuration file, rerun gsutil config to regenerate the
  file.


<B>INSTALLATION</B>
  CentOS, RHEL, and Fedora
  ------------------------

  To compile and install crcmod:

    sudo yum install gcc python-devel python-setuptools
    sudo easy_install -U pip
    sudo pip uninstall crcmod
    sudo pip install -U crcmod

  Debian and Ubuntu
  -----------------

  To compile and install crcmod:

    sudo apt-get install gcc python-dev python-setuptools
    sudo easy_install -U pip
    sudo pip uninstall crcmod
    sudo pip install -U crcmod

  Mac OS X
  --------

  gsutil distributes a pre-compiled version of crcmod for OS X, so you shouldn't
  need to compile and install it yourself. If for some reason the pre-compiled
  version is not being detected, please let the Google Cloud Storage team know
  (see "gsutil help support").

  To compile manually on OS X, you will first need to install
  `XCode <https://developer.apple.com/xcode/>`_ and then run:

    sudo easy_install -U pip
    sudo pip install -U crcmod

  Windows
  -------

  An installer is available for the compiled version of crcmod from the Python
  Package Index (PyPi) at the following URL:

  https://pypi.python.org/pypi/crcmod/1.7

  MSI installers are available for the 32-bit versions of Python 2.6 and 2.7.

""")


class CommandOptions(HelpProvider):
  """Additional help about CRC32C and installing crcmod."""

  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'crc32c',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['crc32', 'crc', 'crcmod'],
    # Type of help:
    HELP_TYPE : HelpType.ADDITIONAL_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'CRC32C and Installing crcmod',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }
