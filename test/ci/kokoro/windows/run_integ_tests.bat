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
rem
rem https://stackoverflow.com/questions/19335004/how-to-run-a-powershell-script-from-a-batch-file
rem http://blog.danskingdom.com/allow-others-to-run-your-powershell-scripts-from-a-batch-file-they-will-love-you-for-it/

set GsutilRepoDir="T:\src\github\src\gsutil"
set "PyExePath=C:\python%PYMAJOR%%PYMINOR%\python.exe"

PowerShell -NoProfile -ExecutionPolicy Bypass -Command "& -keyfile 'C:\src\keystore\74008_gsutil_kokoro_service_key' -api %API% -outfile %BOTO_CONFIG%'"
type %BOTO_CONFIG%

cd %GsutilRepoDir%
git submodule update --init --recursive

rem Print config info prior to running tests
%PyExePath% %GsutilRepoDir%\gsutil.py version -l

PowerShell -NoProfile -ExecutionPolicy Bypass -Command "& '%GsutilRepoDir%\test\ci\kokoro\windows\run_integ_tests.ps1' -GsutilRepoDir '%GsutilRepoDir%' -PyExe '%PyExePath%'"

