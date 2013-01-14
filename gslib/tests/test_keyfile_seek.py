import gslib.commands.cp as cp
import gslib.tests.case as case


class KeyfileTest(case.GsUtilIntegrationTestCase):

  def testReadFull(self):
    bucket = self.CreateBucket()
    contents = '0123456789'
    k = self.CreateObject(bucket, contents=contents)
    keyfile = cp.KeyFile(k)
    self.assertEqual(keyfile.read(len(contents)), contents)
    keyfile.close()

  def testReadPartial(self):
    bucket = self.CreateBucket()
    contents = '0123456789'
    k = self.CreateObject(bucket, contents=contents)
    keyfile = cp.KeyFile(k)
    self.assertEqual(keyfile.read(5), contents[:5])
    self.assertEqual(keyfile.read(5), contents[5:])

  def testTell(self):
    bucket = self.CreateBucket()
    contents = '0123456789'
    k = self.CreateObject(bucket, contents=contents)
    keyfile = cp.KeyFile(k)
    self.assertEqual(keyfile.tell(), 0)
    keyfile.read(4)
    self.assertEqual(keyfile.tell(), 4)
    keyfile.read(6)
    self.assertEqual(keyfile.tell(), 10)
    keyfile.close()
    with self.assertRaisesRegexp(ValueError, 'operation on closed file'):
      keyfile.tell()

  def testSeek(self):
    bucket = self.CreateBucket()
    contents = '0123456789'
    k = self.CreateObject(bucket, contents=contents)
    keyfile = cp.KeyFile(k)
    self.assertEqual(keyfile.read(4), contents[:4])
    keyfile.seek(0)
    self.assertEqual(keyfile.read(4), contents[:4])
    keyfile.seek(5)
    self.assertEqual(keyfile.read(5), contents[5:])
