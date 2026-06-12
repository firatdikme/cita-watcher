@echo off
cd /d "%~dp0"
if exist cita.env.local (
  rem eol=# skips comment lines natively
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("cita.env.local") do set "%%A=%%B"
)
call ".venv\Scripts\activate.bat"
python cita_watcher.py >> watcher.log 2>&1
