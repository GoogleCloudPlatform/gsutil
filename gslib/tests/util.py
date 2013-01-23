import unittest
if not hasattr(unittest.TestCase, "assertIsNone"):
  # external dependency unittest2 required for Python <= 2.6
  import unittest2 as unittest

# Flags for running different types of tests.
RUN_INTEGRATION_TESTS = True
RUN_UNIT_TESTS = True

# Whether the tests are running verbose or not.
VERBOSE_OUTPUT = False
