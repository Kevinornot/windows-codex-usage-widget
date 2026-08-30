@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python launcher "py" was not found. Install Python 3.11 or newer first.
    pause
    exit /b 1
)

if not exist ".venv-build\Scripts\python.exe" (
    py -3 -m venv .venv-build
    if errorlevel 1 goto :failed
)

call ".venv-build\Scripts\activate.bat"
python -m pip install --upgrade pip pyinstaller
if errorlevel 1 goto :failed

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name CodexUsageWidget ^
  --icon "assets\codex_usage_widget.ico" ^
  --add-data "assets\codex_usage_widget.ico;assets" ^
  --add-data "assets\codex_usage_widget.png;assets" ^
  --paths "src" ^
  "run_widget.pyw"
if errorlevel 1 goto :failed

echo.
echo Build complete: %~dp0dist\CodexUsageWidget.exe
pause
exit /b 0

:failed
echo.
echo Build failed. Review the messages above.
pause
exit /b 1
