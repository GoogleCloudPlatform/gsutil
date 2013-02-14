# Copyright 2012 Google Inc. All Rights Reserved.
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

"""Unit tests for PluralityCheckableIterator"""

from gslib.plurality_checkable_iterator import PluralityCheckableIterator
import gslib.tests.testcase as testcase

class PluralityCheckableIteratorTests(testcase.GsUtilUnitTestCase):

  def testPluralityCheckableIteratorWith0Elems(self):
    """Tests empty PluralityCheckableIterator."""
    input_list = range(0)
    it = iter(input_list)
    pcit = PluralityCheckableIterator(it)
    self.assertTrue(pcit.is_empty())
    self.assertFalse(pcit.has_plurality())
    output_list = list(pcit)
    self.assertEqual(input_list, output_list)

  def testPluralityCheckableIteratorWith1Elem(self):
    """Tests PluralityCheckableIterator with 1 element."""
    input_list = range(1)
    it = iter(input_list)
    pcit = PluralityCheckableIterator(it)
    self.assertFalse(pcit.is_empty())
    self.assertFalse(pcit.has_plurality())
    output_list = list(pcit)
    self.assertEqual(input_list, output_list)

  def testPluralityCheckableIteratorWith2Elems(self):
    """Tests PluralityCheckableIterator with 2 elements."""
    input_list = range(2)
    it = iter(input_list)
    pcit = PluralityCheckableIterator(it)
    self.assertFalse(pcit.is_empty())
    self.assertTrue(pcit.has_plurality())
    output_list = list(pcit)
    self.assertEqual(input_list, output_list)

  def testPluralityCheckableIteratorWith3Elems(self):
    """Tests PluralityCheckableIterator with 3 elements."""
    input_list = range(3)
    it = iter(input_list)
    pcit = PluralityCheckableIterator(it)
    self.assertFalse(pcit.is_empty())
    self.assertTrue(pcit.has_plurality())
    output_list = list(pcit)
    self.assertEqual(input_list, output_list)
