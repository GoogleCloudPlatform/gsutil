# Copyright 2013 Google Inc. All Rights Reserved.
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

"""Unit tests for help command."""

import gslib.tests.testcase as testcase


class HelpTest(testcase.GsUtilUnitTestCase):
  """Help command test suite."""

  def test_help_noargs(self):
    stdout = self.RunCommand('help', return_stdout=True)
    self.assertIn('Available commands', stdout)

  def test_help_subcommand_arg(self):
    stdout = self.RunCommand('help', ['web', 'set'], return_stdout=True)
    self.assertIn('gsutil web set', stdout)
    self.assertNotIn('gsutil web get', stdout)

  def test_help_invalid_subcommand_arg(self):
    stdout = self.RunCommand('help', ['web', 'asdf'], return_stdout=True)
    self.assertIn('help about one of the subcommands', stdout)

  def test_help_with_subcommand_for_command_without_subcommands(self):
    stdout = self.RunCommand('help', ['ls', 'asdf'], return_stdout=True)
    self.assertIn('has no subcommands', stdout)

  def test_help_command_arg(self):
    stdout = self.RunCommand('help', ['ls'], return_stdout=True)
    self.assertIn('ls - List providers, buckets', stdout)

  def test_command_help_arg(self):
    stdout = self.RunCommand('ls', ['--help'], return_stdout=True)
    self.assertIn('ls - List providers, buckets', stdout)

  def test_subcommand_help_arg(self):
    stdout = self.RunCommand('web', ['set', '--help'], return_stdout=True)
    self.assertIn('gsutil web set', stdout)
    self.assertNotIn('gsutil web get', stdout)

  def test_command_args_with_help(self):
    stdout = self.RunCommand('cp', ['foo', 'bar', '--help'], return_stdout=True)
    self.assertIn('cp - Copy files and objects', stdout)
