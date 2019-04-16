param (
    [Parameter(Mandatory=$true)][string]$keyfile,
    [Parameter(Mandatory=$true)][string]$api,
    [Parameter(Mandatory=$true)][string]$outfile
 )

$stream = [System.IO.StreamWriter] $outfile
$stream.WriteLine("[Credentials]")
$stream.WriteLine("gs_service_key_file = $keyfile")
$stream.WriteLine("[GSUtil]")
$stream.WriteLine("test_notification_url = https://bigstore-test-notify.appspot.com/notify")
$stream.WriteLine("default_project_id = bigstore-gsutil-testing")
$stream.WriteLine("prefer_api = $api")
$stream.WriteLine("[OAuth2]")
$stream.WriteLine("client_id = 909320924072.apps.googleusercontent.com")
$stream.WriteLine("client_secret = p3RlpR10xMFh9ZXBS/ZNLYUu")
$stream.close()

