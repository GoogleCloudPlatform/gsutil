import os
import re
import sys
import traceback

import gslib
from gslib.__main__ import debug_level, test_exception_traces
from gslib.utils import boto_util
from gslib.utils import constants
from gslib.utils import text_util
from gslib import metrics

# pylint: disable=unused-argument
def CleanupSignalHandler(signal_num, cur_stack_frame):
  """Cleans up if process is killed with SIGINT, SIGQUIT or SIGTERM.

  Note that this method is called after main() has been called, so it has
  access to all the modules imported at the start of main().

  Args:
    signal_num: Unused, but required in the method signature.
    cur_stack_frame: Unused, but required in the method signature.
  """
  Cleanup()
  if (gslib.utils.parallelism_framework_util.
      CheckMultiprocessingAvailableAndInit().is_available):
    gslib.command.TeardownMultiprocessingProcesses()


def Cleanup():
  for fname in boto_util.GetCleanupFiles():
    try:
      os.unlink(fname)
    except:  # pylint: disable=bare-except
      pass

def OutputAndExit(message, exception=None):
  """Outputs message to stderr and exits gsutil with code 1.

  This function should only be called in single-process, single-threaded mode.

  Args:
    message: Message to print to stderr.
    exception: The exception that caused gsutil to fail.
  """
  if debug_level >= constants.DEBUGLEVEL_DUMP_REQUESTS or test_exception_traces:
    stack_trace = traceback.format_exc()
    err = ('DEBUG: Exception stack trace:\n    %s\n%s\n' %
           (re.sub('\\n', '\n    ', stack_trace), message))
  else:
    err = '%s\n' % message
  try:
    text_util.print_to_fd(err, end='', file=sys.stderr)
  except UnicodeDecodeError:
    # Can happen when outputting invalid Unicode filenames.
    sys.stderr.write(err)
  if exception:
    metrics.LogFatalError(exception)
  sys.exit(1)

def OutputUsageAndExit(command_runner):
  command_runner.RunNamedCommand('help')
  sys.exit(1)
