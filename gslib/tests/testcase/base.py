from gslib.tests.util import unittest


class GsUtilTestCase(unittest.TestCase):

  def assertNumLines(self, text, numlines):
    self.assertEqual(text.count('\n'), numlines)

