@echo off
setlocal
set "TARGET=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Codex Usage Widget.cmd"
if exist "%TARGET%" del /q "%TARGET%"
echo Codex Usage Widget autostart entry removed.
pause
