@echo off
setlocal
cd /d "%~dp0"
set "SALES_PYTHON=%USERPROFILE%\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%SALES_PYTHON%" set "SALES_PYTHON=python"
"%SALES_PYTHON%" -B -m backend.desk --open
if errorlevel 1 pause
