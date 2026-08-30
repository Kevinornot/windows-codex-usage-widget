@echo off
setlocal
cd /d "%~dp0"

where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 "%~dp0run_widget.pyw" %*
    exit /b
)

where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "%~dp0run_widget.pyw" %*
    exit /b
)

where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%~dp0run_widget.pyw" %*
    exit /b
)

where python >nul 2>nul
if not errorlevel 1 (
    python "%~dp0run_widget.pyw" %*
    exit /b
)

echo Python 3.11 or newer was not found.
echo Install Python from python.org and enable "Add Python to PATH".
exit /b 1
