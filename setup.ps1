$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "==> Creating virtual environment" -ForegroundColor Cyan
python -m venv .venv

Write-Host "==> Installing Python deps" -ForegroundColor Cyan
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r requirements.txt

Write-Host "==> Installing Playwright Chromium" -ForegroundColor Cyan
.\.venv\Scripts\python.exe -m playwright install chromium

Write-Host "==> Running one test check" -ForegroundColor Cyan
.\.venv\Scripts\python.exe cita_watcher.py

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "If the test above printed 'unavailable' you're good."
Write-Host "Now register the scheduled task with: .\register_task.ps1"
