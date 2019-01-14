from gslib.tests import testcase
from gslib.utils import json_six
from six import PY3

class TestJsonConversion(testcase.GsUtilUnitTestCase):
  @classmethod
  def setUpClass(cls):
    if PY3:
      cls.text_json = str('[{"integer": 1,"decimal": 3.14,"text": '
                          '"testing, 1, 2"}]')
      cls.binary_json = bytes(b'[{"integer": 1,"decimal": 3.14,"text": '
                              b'"testing, 1, 2"}]')
    else:
      cls.text_json = unicode('[{"integer": 1,"decimal": 3.14,"text": '
                              '"testing, 1, 2"}]')
      cls.binary_json = str('[{"integer": 1,"decimal": 3.14,"text": '
                          '"testing, 1, 2"}]')
    cls.keys = {"integer", "decimal", "text"}
    cls.json = [
      {
        "integer": 1,
        "decimal": 3.14,
        "text": "testing, 1, 2"
      }
    ]
  def test_json_load_text(self):
    result = json_six.loads(self.text_json)
    self.assertEqual(self.json, result)
    for key in result[0]:
      self.assertIn(key, self.keys)

  def test_json_load_byte(self):
    result = json_six.loads(self.binary_json)
    self.assertEqual(self.json, result)
    for key in result[0]:
      self.assertIn(key, self.keys)
