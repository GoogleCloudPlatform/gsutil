import sys
ver = sys.version_info
if ver.major != 3 or ver.minor < 9 or ver.minor > 13:
  sys.exit("Error")

