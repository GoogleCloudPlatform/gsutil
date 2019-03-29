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

rem Create a config file for gsutil to use in Kokoro tests.
rem https://cloud.google.com/storage/docs/gsutil/commands/config


set GSUTIL_KEY=%1
set API=%2
set OUTPUT_FILE=%3

(
echo [Credentials]
echo gs_service_key_file = %GSUTIL_KEY%
echo [GSUtil]
echo test_notification_url = https://bigstore-test-notify.appspot.com/notify
echo default_project_id = bigstore-gsutil-testing
echo prefer_api = %API%
echo [OAuth2]
echo client_id = 909320924072.apps.googleusercontent.com
echo client_secret = p3RlpR10xMFh9ZXBS/ZNLYUu
)>%OUTPUT_FILE%
