@echo off
echo dsGPT startup settings
echo.
echo Enable starts the local backend when YOU sign in to Windows.
echo dsGPT retries a crashed backend up to three times, one minute apart.
echo The desktop window is not opened. It does not request elevation or a password.
echo Enable takes effect at your next sign-in, or after Stop Backend then opening dsGPT.
echo Disable removes future startup/retries; it does not stop the running backend.
echo An unrelated or modified scheduled task is preserved.
echo.
choice /C EDSQ /N /M "[E]nable, [D]isable, [S]tatus, [Q]uit: "
if errorlevel 4 exit /b 0
if errorlevel 3 goto status
if errorlevel 2 goto disable
if errorlevel 1 goto enable
exit /b 1
:enable
"%~dp0python\python.exe" -I -m dsgpt.managed startup-enable --confirm-startup-change
goto done
:disable
"%~dp0python\python.exe" -I -m dsgpt.managed startup-disable --confirm-startup-change
goto done
:status
"%~dp0python\python.exe" -I -m dsgpt.managed startup-status
:done
pause
