@echo off
echo dsGPT local owner recovery
echo.
echo Stop the managed backend before continuing. If all credentials are lost,
echo disable automatic startup in Startup Settings, then restart Windows.
echo Do not reopen dsGPT before running this recovery shortcut.
echo This replaces the local owner credential and revokes all paired devices.
echo Conversations, projects and model files are preserved.
echo Other desktop server connections are preserved.
echo.
choice /C YN /N /M "Recover this Windows user's managed dsGPT account? [Y/N] "
if errorlevel 2 goto :eof
if not errorlevel 1 goto :eof
"%~dp0python\python.exe" -I -m dsgpt.managed recover-owner --confirm-revoke-devices
echo.
echo Review the result above. On success, open dsGPT normally and pair devices again.
pause
