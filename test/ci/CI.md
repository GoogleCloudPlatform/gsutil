# Gsutil Continuous Integration Testing

**PREAMBLE**: This document describes the system we use for integration tests and how to use it.

## Kokoro CI

### Overview
-----

Kokoro aims to be our primary CI system. For internal Googlers, its documentation is at [go/kokoro](http://go/kokoro). Our design document for integrating with Kokoro is at [go/gsutil-test-matrix](http://go/gsutil-test-matrix).

Kokoro listens to our GitHub repository for changes, and when a PR is submitted or code is `git push`ed, Kokoro spins up VMs and runs integration tests on the new code.

The build configs found in this repository under the `gsutil/test/ci/kokoro` directory and the job configs found internally at [go/gsutil-kokoro-piper](http://go/gsutil-kokoro-piper) define how Kokoro will run our tests, with what scripts, and with which VMs.

### Test Matrix
-----

We currently support Gsutil on Windows, Mac, and Linux, using Python versoins 2.7, 3.5, 3.6, 3.7, and any future 3.x versions. Additionally, integration tests need to be run separately for each API, both XML and JSON.

Each of these 24 combinations of `(OS / Python version / API)` is run on a separate VM managed by Kokoro, all running in parallel. 

### VM Configuration
-----

Kokoro provides stock VMs with common software pre-installed. We use the GCP variety of these stock VMs since they can access the internet to download dependencies and source from GitHub.

The stock configurations are listed here ([Windows](http://go/gcp-windows-vm-configuration-v2k), [Mac](http://go/kokoro-macos-external-configuration), [Linux](http://gcp-ubuntu-vm-configuration-v2b)). Some dependencies (such as crcmod via pip) are downloaded in the test script to prepare the environment for test runs.

In our case, a VM spawns for each py*.cfg in each OS folder in our Kokoro CI directory. When each VM starts, it pulls our source code from GitHub to the VM as well as Keystore keys as defined the config files for each OS.

### Test Scripts
-----

Linux and Mac share the same bash script in `gsutil/test/ci/kokoro/run_integ_tests.sh`. Windows targets a `gsutil/test/ci/kokoro/windows/run_integ_tests.bat` which initializes environment variables and passes them to a powershell script which runs the tests in parallel. Kokoro insists on calling a `.bat` script specifically, hence the wrapper.

### Test Results
-----

Current and past test runs and links to their results are listed in [Fusion](http://go/ops-fusion). You can either search for `cloud_storage_gsutil` or using one of the following go links for continuous and presubmit builds:

- go/gsutil-kokoro-linux
- go/gsutil-kokoro-linux-pr
- go/gsutil-kokoro-mac
- go/gsutil-kokoro-mac-pr

Note that this is currently only available to internal Googlers. We do not currently have an interface for external contributers to view the Kokoro test results.
