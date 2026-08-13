@echo off
setlocal enabledelayedexpansion

set "REPO=%~dp0"
set "LOG=%REPO%out\monitor_log.txt"
cd /d "%REPO%"

echo. >> "%LOG%"
echo ==== %date% %time% ==== >> "%LOG%"
python monitor.py >> "%LOG%" 2>&1
echo ==== exit code %ERRORLEVEL% ==== >> "%LOG%"

rem Keep only the last 60 run headers worth of log. A "run" is everything
rem between one "====" header line and the next; trim from the top once
rem there are more than 60 header lines in the file.
set "HEADERCOUNT=0"
for /f %%c in ('findstr /b /c:"====" "%LOG%" ^| find /c /v ""') do set "HEADERCOUNT=%%c"
if !HEADERCOUNT! GTR 60 (
    set "TMP=%REPO%out\monitor_log.tmp"
    powershell -NoProfile -Command ^
        "$lines = Get-Content -LiteralPath '%LOG%';" ^
        "$headerIdx = @(); for ($i=0; $i -lt $lines.Count; $i++) { if ($lines[$i] -like '====*') { $headerIdx += $i } };" ^
        "$keepFrom = $headerIdx[$headerIdx.Count - 60];" ^
        "$lines[$keepFrom..($lines.Count-1)] | Set-Content -LiteralPath '%TMP%' -Encoding utf8"
    move /y "%TMP%" "%LOG%" >nul
)

endlocal
