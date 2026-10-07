@echo off
rem Smart Meeting launcher for Windows: `.\smart-meeting` in PowerShell or the command prompt, or a
rem double-click on this file. Same as `./smart-meeting` on Linux and macOS: installs uv if needed;
rem the app then checks the system, builds the interface and installs Ollama and the AI model itself.
rem Ctrl+C, or the Quit button, stops everything.
setlocal
set "ROOT=%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"

where uv >nul 2>nul || (
  echo Smart Meeting : installation de uv...
  powershell -NoProfile -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" || goto failed
)

rem CUDA libraries only with an NVIDIA GPU
set "EXTRAS="
nvidia-smi -L >nul 2>nul && set "EXTRAS=--extra cuda"

uv run --quiet --directory "%ROOT%backend" %EXTRAS% smart-meeting %*
if errorlevel 1 goto failed
exit /b 0

:failed
rem Started by a double-click: keep the window open to read the error
echo.
pause
exit /b 1
