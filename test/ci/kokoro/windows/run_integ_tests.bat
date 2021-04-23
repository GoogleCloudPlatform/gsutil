rem Copyright 2019 Google LLC
rem
rem Licensed under the Apache License, Version 2.0 (the "License");
rem you may not use this file except in compliance with the License.
rem You may obtain a copy of the License at
rem
rem     http://www.apache.org/licenses/LICENSE-2.0
rem
rem Unless required by applicable law or agreed to in writing, software
rem distributed under the License is distributed on an "AS IS" BASIS,
rem WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
rem See the License for the specific language governing permissions and
rem limitations under the License.

rem Kokoro looks for a .bat build file, but all our logic is actually in
rem a PowerShell script. This simply launches our script with the appropriate
rem parameters.

set GsutilRepoDir="T:\src\github\src\gsutil"
set "PyExePath=C:\python%PYMAJOR%%PYMINOR%\python.exe"
set "PipPath=C:\python%PYMAJOR%%PYMINOR%\Scripts\pip.exe"

PowerShell -NoProfile -ExecutionPolicy Bypass -Command "& '%GsutilRepoDir%\test\ci\kokoro\windows\config_generator.ps1' 'T:\src\keystore\74008_gsutil_kokoro_service_key' '%API%' '%BOTO_CONFIG%'"
type %BOTO_CONFIG%

cd %GsutilRepoDir%
git submodule update --init --recursive
%PipPath% install crcmod

rem Print config info prior to running tests
%PyExePath% %GsutilRepoDir%\gsutil.py version -l

PowerShell -NoProfile -ExecutionPolicy Bypass -Command "& '%GsutilRepoDir%\test\ci\kokoro\windows\run_integ_tests.ps1' -GsutilRepoDir '%GsutilRepoDir%' -PyExe '%PyExePath%'" || exit /B 1

rem Run custom endpont tests.
rem Not enough settings to merit generating a boto config.
set PscConfig=-o "Credentials:gs_host=storage-psc.p.googleapis.com"^
 -o "Credentials:gs_host_header=storage.googleapis.com"^
 -o "Credentials:gs_json_host=storage-psc.p.googleapis.com"^
 -o "Credentials:gs_json_host_header=www.googleapis.com"
PowerShell -NoProfile -ExecutionPolicy Bypass -Command "& '%GsutilRepoDir%\test\ci\kokoro\windows\run_integ_tests.ps1' -GsutilRepoDir '%GsutilRepoDir%' -PyExe '%PyExePath%' -Tests 'psc' -TopLevelFlags '%PscConfig%'" || exit /B 1

rem mTLS tests only run on GCS JSON.
if not "json" == "%API%" exit /B 0

set "MtlsTestAccountRefreshToken=T:\src\keystore\74008_mtls_test_account_refresh_token"
set "MtlsTestAccountClientId=T:\src\keystore\74008_mtls_test_account_client_id"
set "MtlsTestAccountClientSecret=T:\src\keystore\74008_mtls_test_account_client_secret"
set "MtlsTestCertPath=T:\src\keystore\74008_mtls_test_cert"

PowerShell -NoProfile -ExecutionPolicy Bypass -Command "& '%GsutilRepoDir%\test\ci\kokoro\windows\config_generator.ps1' '' '%API%' '%BOTO_CONFIG%' '%MtlsTestAccountRefreshToken%' '%MtlsTestAccountClientId%' '%MtlsTestAccountClientSecret%' '%MtlsTestCertPath%'"
PowerShell -NoProfile -ExecutionPolicy Bypass -Command "& '%GsutilRepoDir%\test\ci\kokoro\windows\run_integ_tests.ps1' -GsutilRepoDir '%GsutilRepoDir%' -PyExe '%PyExePath%' -Tests 'mtls'"
