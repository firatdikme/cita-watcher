$ErrorActionPreference = "Stop"

$taskName = "CitaWatcher"
$folder   = $PSScriptRoot
$batPath  = Join-Path $folder "run.bat"

$action    = New-ScheduledTaskAction  -Execute $batPath -WorkingDirectory $folder
$trigger   = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
             -RepetitionInterval (New-TimeSpan -Minutes 10)
$settings  = New-ScheduledTaskSettingsSet -StartWhenAvailable `
             -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
             -ExecutionTimeLimit (New-TimeSpan -Minutes 8) `
             -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "Polls Extranjeria Barcelona (carta de invitacion) every 10 min and pushes ntfy.sh with the status."

Write-Host "Scheduled task '$taskName' registered. Runs every 10 min." -ForegroundColor Green
Write-Host "Check status: Get-ScheduledTask -TaskName $taskName"
Write-Host "Tail log:     Get-Content -Wait .\watcher.log"
