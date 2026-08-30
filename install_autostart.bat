@echo off
setlocal
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if not exist "%STARTUP%" mkdir "%STARTUP%"
>"%STARTUP%\Codex Usage Widget.cmd" echo @echo off
>>"%STARTUP%\Codex Usage Widget.cmd" echo wscript.exe "%~dp0run_widget.vbs"
echo Codex Usage Widget will start with Windows.
pause
