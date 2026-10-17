@echo off
setlocal
rem The execution-policy override applies only to this PowerShell process.
rem No user or machine policy is changed; managed Group Policy still applies.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap-windows.ps1" %*
set "HIBREAK_SETUP_EXIT=%ERRORLEVEL%"
echo.
if not "%HIBREAK_SETUP_EXIT%"=="0" echo Setup finished with status %HIBREAK_SETUP_EXIT%. Read the instructions above.
if "%HIBREAK_NO_PAUSE%"=="1" exit /b %HIBREAK_SETUP_EXIT%
pause
exit /b %HIBREAK_SETUP_EXIT%
