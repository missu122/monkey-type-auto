@echo off
cd /d "%~dp0"
set "CODEX_PYW=%~dp0..\..\work\ck_mvp_venv\Scripts\pythonw.exe"
if exist "%CODEX_PYW%" (
  start "" "%CODEX_PYW%" "%~dp0src\text_typer.py"
  exit /b 0
)
start "" pyw -3 "%~dp0src\text_typer.py"
exit /b 0
