#!/bin/bash

# This shell script is used for setting up our Kokoro Mac environment
# with necessary dependencies for running integration tests, and then
# running tests when PRs are submitted.

# For now, continuous.sh and presubmit.sh are both symlinks to this file.
# Kokoro looks for files with those names, but our continuous and presubmit jobs
# on Mac should be identical.

# -e : Fail on any error
# -x : Display commands being run
# -u : Disallow unset variables
# Doc: https://www.gnu.org/software/bash/manual/html_node/The-Set-Builtin.html#The-Set-Builtin
set -exu

# For debugging on the CI branch, let me SSH in
# go/kokoro-ssh-vm
#echo "$SSH_AUTHORIZED_KEY" >> ~/.ssh/authoirized_keys
#external_ip=$(curl -s -H "Metadata-Flavor: Google" http://metadata/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip)
#echo "INSTANCE_EXTERNAL_IP=${external_ip}"
#sleep 2400

GITHUB_REPO="https://github.com/GoogleCloudPlatform/gsutil"
GSUTIL_KEY="/src/keystore/gsutil_kokoro_service_key.json"
GSUTIL_SRC_PATH="/src/gsutil"
GSUTIL_ENTRYPOINT="$GSUTIL_SRC_PATH/gsutil.py"
PYTHON_PATH="/usr/local/bin/python"
CONFIG_JSON="/src/.boto_json"
CONFIG_XML="/src/.boto_xml"
# PYMAJOR and PYMINOR environment variables are set for each Kokoro job.
# go/kokoro-gsutil-configs
PYTHON_INTERPRETER="$PYTHON_PATH$PYMAJOR.$PYMINOR"

# Processes to use based on default Mac Kokoro specs here:
# go/kokoro-macos-external-configuration
PROCS="8"

# Install crcmod for the current interpreter if it isn't already.
# https://stackoverflow.com/a/4910393/5377671
"$PYTHON_INTERPRETER" -m pip install -U crcmod

# Create config files for gsutil
if [[ ! -f  $CONFIG_JSON ]]; then
  ../config_generator.sh "$GSUTIL_KEY" "json" > "$CONFIG_JSON"
fi

if [[ ! -f  $CONFIG_XML ]]; then
  ../config_generator.sh "$GSUTIL_KEY" "xml" > "$CONFIG_XML"
fi

cd "$GSUTIL_SRC_PATH"
git submodule update --init --recursive

# Run integration tests
"$PYTHON_INTERPRETER" "$GSUTIL_ENTRYPOINT" test -p "$PROCS"

