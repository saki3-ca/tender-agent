# Registers the hourly "ACNABIN Tender Monitor (office PC)" task on a Windows PC in Bangladesh.
#
# Some bank sites (Janata Bank, Islami Bank, ...) never answer GitHub's servers but load normally from
# Bangladesh. Those sources are marked "office_pc": true in config/sources.json; GitHub skips them and this
# task reads them every hour and saves the results to the same Supabase database the dashboard uses.
#
# One-time setup on the office PC (PowerShell, in the repository folder):
#   1. Python 3.11+ installed, then:  pip install -r requirements.txt
#   2. A .env file in the repository folder with SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (copy it from this PC)
#   3. powershell -ExecutionPolicy Bypass -File scripts\install_office_pc_task.ps1
#
# The PC must stay switched on (sleep disabled). Log: data\office_pc.log. Remove the task with:
#   Unregister-ScheduledTask -TaskName "ACNABIN Tender Monitor (office PC)" -Confirm:$false

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python -ErrorAction Stop).Source
if (-not (Test-Path (Join-Path $repo ".env"))) { throw "No .env file in $repo (needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)." }
New-Item -ItemType Directory -Force (Join-Path $repo "data") | Out-Null

$log = Join-Path $repo "data\office_pc.log"
# git pull first so the PC always uses the latest source list, then the office-PC sources only.
$command = "cd /d `"$repo`" && git pull -q && `"$python`" run_monitor.py --office-pc >> `"$log`" 2>&1"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $command"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(20) -RepetitionInterval (New-TimeSpan -Hours 1)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName "ACNABIN Tender Monitor (office PC)" -Action $action -Trigger $trigger `
    -Settings $settings -Description "Reads the bank/NGO sites that block GitHub (office_pc sources) every hour." -Force | Out-Null

Write-Host "Installed. First run now..."
Start-ScheduledTask -TaskName "ACNABIN Tender Monitor (office PC)"
Write-Host "Done. Progress is written to $log"
