import os.path
import sys
import unittest


CURDIR = os.path.abspath(os.path.dirname(__file__))
GSLIB_DIR = os.path.split(CURDIR)[0]
GSUTIL_DIR = os.path.split(GSLIB_DIR)[0]
BOTO_DIR = os.path.join(GSUTIL_DIR, 'boto')


def MungePath():
  try:
    import boto
  except ImportError:
    sys.path.append(BOTO_DIR)

  try:
    import gslib
  except ImportError:
    sys.path.append(GSUTIL_DIR)


if __name__ == '__main__':
  MungePath()
  suite = unittest.TestLoader().discover(CURDIR)
  ret = unittest.TextTestRunner(verbosity=2).run(suite)
  if ret.wasSuccessful():
    sys.exit(0)
  sys.exit(1)
