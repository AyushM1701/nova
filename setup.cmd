@echo off
rem Double-click to install or update Nova on Windows. A setup window opens; this console closes.
start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0setup.ps1" %*
