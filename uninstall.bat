@echo off
setlocal
cd /d "%~dp0"
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS%" set "PS=pwsh"
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1" %*
set "RC=%ERRORLEVEL%"
if exist "%~dp0uninstall.ps1" del /f /q "%~dp0uninstall.ps1" >nul 2>nul
if exist "%~dp0uninstall.sh" del /f /q "%~dp0uninstall.sh" >nul 2>nul
rem 程序目录都删掉了，说明是全删模式：整个目录一起清掉
if exist "%~dp0backend" goto end
if exist "%~dp0platforms" goto end
if exist "%~dp0.venv" goto end
(goto) 2>nul & rmdir /s /q "%~dp0"
:end
if not "%RC%"=="0" (
  echo.
  echo Uninstall failed. See messages above.
  pause
)
(goto) 2>nul & del "%~f0"
