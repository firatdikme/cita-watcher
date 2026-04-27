@echo off
cd /d "%~dp0"
if exist cita.env.local (
  for /f "usebackq tokens=1,* delims==" %%A in ("cita.env.local") do (
    if not "%%A"=="" if not "%%A:~0,1%"=="#" set "%%A=%%B"
  )
)
call .venv\Scripts\activate.bat
python cita_watcher.py >> watcher.log 2>&1
