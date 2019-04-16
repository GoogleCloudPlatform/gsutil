# Copyright 2019 Google LLC
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the Licens# Kokoro looks for a .bat build file, but all our logic is actually in
# a PowerShell script. This simply launches our script with the appropriate
# parameters.

param (
    [Parameter(Mandatory=$true)][string]$KeyFile,
    [Parameter(Mandatory=$true)][string]$Api,
    [Parameter(Mandatory=$true)][string]$OutFile
 )

$stream = [System.IO.StreamWriter] $OutFile
$stream.WriteLine("[Credentials]")
$stream.WriteLine("gs_service_key_file = $KeyFile")
$stream.WriteLine("[GSUtil]")
$stream.WriteLine("test_notification_url = https://bigstore-test-notify.appspot.com/notify")
$stream.WriteLine("default_project_id = bigstore-gsutil-testing")
$stream.WriteLine("prefer_api = $Api")
$stream.WriteLine("[OAuth2]")
$stream.WriteLine("client_id = 909320924072.apps.googleusercontent.com")
$stream.WriteLine("client_secret = p3RlpR10xMFh9ZXBS/ZNLYUu")
$stream.close()

