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
"""Tests for gsutil utility functions."""

from __future__ import absolute_import

from gslib import util
import gslib.tests.testcase as testcase
from gslib.util import CompareVersions


class TestUtil(testcase.GsUtilUnitTestCase):
  """Tests for utility functions."""

  def test_MakeHumanReadable(self):
    """Tests converting byte counts to human-readable strings."""
    self.assertEqual(util.MakeHumanReadable(0), '0 B')
    self.assertEqual(util.MakeHumanReadable(1023), '1023 B')
    self.assertEqual(util.MakeHumanReadable(1024), '1 KB')
    self.assertEqual(util.MakeHumanReadable(1024 ** 2), '1 MB')
    self.assertEqual(util.MakeHumanReadable(1024 ** 3), '1 GB')
    self.assertEqual(util.MakeHumanReadable(1024 ** 3 * 5.3), '5.3 GB')
    self.assertEqual(util.MakeHumanReadable(1024 ** 4 * 2.7), '2.7 TB')
    self.assertEqual(util.MakeHumanReadable(1024 ** 5), '1 PB')
    self.assertEqual(util.MakeHumanReadable(1024 ** 6), '1 EB')

  def test_MakeBitsHumanReadable(self):
    """Tests converting bit counts to human-readable strings."""
    self.assertEqual(util.MakeBitsHumanReadable(0), '0 bit')
    self.assertEqual(util.MakeBitsHumanReadable(1023), '1023 bit')
    self.assertEqual(util.MakeBitsHumanReadable(1024), '1 Kbit')
    self.assertEqual(util.MakeBitsHumanReadable(1024 ** 2), '1 Mbit')
    self.assertEqual(util.MakeBitsHumanReadable(1024 ** 3), '1 Gbit')
    self.assertEqual(util.MakeBitsHumanReadable(1024 ** 3 * 5.3), '5.3 Gbit')
    self.assertEqual(util.MakeBitsHumanReadable(1024 ** 4 * 2.7), '2.7 Tbit')
    self.assertEqual(util.MakeBitsHumanReadable(1024 ** 5), '1 Pbit')
    self.assertEqual(util.MakeBitsHumanReadable(1024 ** 6), '1 Ebit')

  def test_HumanReadableToBytes(self):
    """Tests converting human-readable strings to byte counts."""
    self.assertEqual(util.HumanReadableToBytes('1'), 1)
    self.assertEqual(util.HumanReadableToBytes('15'), 15)
    self.assertEqual(util.HumanReadableToBytes('15.3'), 15)
    self.assertEqual(util.HumanReadableToBytes('15.7'), 16)
    self.assertEqual(util.HumanReadableToBytes('1023'), 1023)
    self.assertEqual(util.HumanReadableToBytes('1k'), 1024)
    self.assertEqual(util.HumanReadableToBytes('2048'), 2048)
    self.assertEqual(util.HumanReadableToBytes('1 K'), 1024)
    self.assertEqual(util.HumanReadableToBytes('1 mb'), 1024 ** 2)
    self.assertEqual(util.HumanReadableToBytes('1 GB'), 1024 ** 3)
    self.assertEqual(util.HumanReadableToBytes('1T'), 1024 ** 4)
    self.assertEqual(util.HumanReadableToBytes('1\t   pb'), 1024 ** 5)
    self.assertEqual(util.HumanReadableToBytes('1e'), 1024 ** 6)

  def test_CompareVersions(self):
    """Tests CompareVersions for various use cases."""
    # CompareVersions(first, second) returns (g, m), where
    #   g is True if first known to be greater than second, else False.
    #   m is True if first known to be greater by at least 1 major version,
    (g, m) = CompareVersions('3.37', '3.2')
    self.assertTrue(g)
    self.assertFalse(m)
    (g, m) = CompareVersions('7', '2')
    self.assertTrue(g)
    self.assertTrue(m)
    (g, m) = CompareVersions('3.32', '3.32pre')
    self.assertTrue(g)
    self.assertFalse(m)
    (g, m) = CompareVersions('3.32pre', '3.31')
    self.assertTrue(g)
    self.assertFalse(m)
    (g, m) = CompareVersions('3.4pre', '3.3pree')
    self.assertTrue(g)
    self.assertFalse(m)

    (g, m) = CompareVersions('3.2', '3.37')
    self.assertFalse(g)
    self.assertFalse(m)
    (g, m) = CompareVersions('2', '7')
    self.assertFalse(g)
    self.assertFalse(m)
    (g, m) = CompareVersions('3.32pre', '3.32')
    self.assertFalse(g)
    self.assertFalse(m)
    (g, m) = CompareVersions('3.31', '3.32pre')
    self.assertFalse(g)
    self.assertFalse(m)
    (g, m) = CompareVersions('3.3pre', '3.3pre')
    self.assertFalse(g)
    self.assertFalse(m)

    (g, m) = CompareVersions('foobar', 'baz')
    self.assertFalse(g)
    self.assertFalse(m)
    (g, m) = CompareVersions('3.32', 'baz')
    self.assertFalse(g)
    self.assertFalse(m)

    (g, m) = CompareVersions('3.4', '3.3')
    self.assertTrue(g)
    self.assertFalse(m)
    (g, m) = CompareVersions('3.3', '3.4')
    self.assertFalse(g)
    self.assertFalse(m)
    (g, m) = CompareVersions('4.1', '3.33')
    self.assertTrue(g)
    self.assertTrue(m)
    (g, m) = CompareVersions('3.10', '3.1')
    self.assertTrue(g)
    self.assertFalse(m)
