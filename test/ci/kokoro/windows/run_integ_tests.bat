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
set PyExe=%2

PowerShell -NoProfile -ExecutionPolicy Bypass -Command "& '%run_integration_tests.ps1%' '%GsutilRepoDir%' '%PyExe%'";

