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

rem debug lines, remove me later
dir
echo ""
tree /F
echo ""


set GsutilRepoDir=%1
set "PyExePath=C:\python%PYMAJOR%%PYMINOR%\python.exe"

cmd config_generator.bat "C:\src\keystore\74008+gsutil_kokoro_service_key" %API% "C:\src\.boto_%API%"

PowerShell -NoProfile -ExecutionPolicy Bypass -Command "& '%run_integration_tests.ps1%' -GsutilRepoDir '%GsutilRepoDir%' -PyExe '%PyExePath%'";

