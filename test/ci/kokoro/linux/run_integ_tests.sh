#!/bin/bash

# This shell script is used for setting up our Kokoro Ubuntu environment
# with necessary dependencies for running integration tests, and then
# running tests when PRs are submitted.

# For now, continuous.sh and presubmit.sh are both symlinks to this file.
# Kokoro looks for files with those names, but our continuous and presubmit jobs
# should be identical on Linux.

# -e : Fail on any error
# -x : Display commands being run
# -u : Disallow unset variables
# Doc: https://www.gnu.org/software/bash/manual/html_node/The-Set-Builtin.html#The-Set-Builtin
set -exu

GITHUB_REPO="https://github.com/GoogleCloudPlatform/gsutil"
GSUTIL_KEY="/src/keystore/gsutil_kokoro_service_key.json"
GSUTIL_SRC_PATH="/src/gsutil"
GSUTIL_ENTRYPOINT="$GSUTIL_SRC_PATH/gsutil.py"
PYTHON_PATH="/usr/local/bin/python"
CONFIG_JSON="/src/.boto_json"
CONFIG_XML="/src/.boto_xml"

# Processes to use based on default Ubuntu Kokoro specs here:
# go/gcp-ubuntu-vm-configuration-v32i
PROCS="4"

# PYMAJOR and PYMINOR environment variables are set for each Kokoro job in:
# go/kokoro-gsutil-configs
PYVERSION="$PYMAJOR.$PYMINOR"

function latest_python_release {
  # Return string with latest Python version triplet for a given version tuple.
  # Example: PYVERSION="2.7"; latest_python_release -> "2.7.15"
  pyenv install --list \
    | grep -vE "(^Available versions:|-src|dev|rc|alpha|beta|(a|b)[0-9]+)" \
    | grep -E "^\s*$PYVERSION" \
    | sed 's/^\s\+//' \
    | tail -1
}

function install_latest_python {
  pyenv update
  pyenv install -s "$PYVERSIONTRIPLET"
}

function init_configs {
  # Create config files for gsutil if they don't exist already
  # https://cloud.google.com/storage/docs/gsutil/commands/config
  if [[ ! -f  $CONFIG_JSON ]]; then
    ../config_generator.sh "$GSUTIL_KEY" "json" > "$CONFIG_JSON"
  fi

  if [[ ! -f  $CONFIG_XML ]]; then
    ../config_generator.sh "$GSUTIL_KEY" "xml" > "$CONFIG_XML"
  fi
}

function init_python {
  # Ensure latest release of desired Python version is installed, and that
  # dependencies, e.g. crcmod, are installed.
  PYVERSIONTRIPLET=$(latest_python_release)
  install_latest_python
  pyenv global "$PYVERSIONTRIPLET"
  python -m pip install -U crcmod
}

init_python
init_configs

cd "$GSUTIL_SRC_PATH"
git submodule update --init --recursive

# Run integration tests
python "$GSUTIL_ENTRYPOINT" test -p "$PROCS"

