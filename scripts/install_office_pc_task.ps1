# Registers the ACNABIN Tender Monitor scheduled tasks on a Windows PC in Bangladesh.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_office_pc_task.ps1          # office-PC sources only (recommended)
#   powershell -ExecutionPolicy Bypass -File scripts\install_office_pc_task.ps1 -Full    # the whole agent on this PC
#
# Default: some bank sites (Janata Bank, Islami Bank, ...) never answer GitHub's servers but load normally from
# Bangladesh. Those sources are marked "office_pc": true in config/sources.json; GitHub skips them and the hourly
# task here reads them. GitHub Actions keeps doing everything else.
#
# -Full: this PC also runs the complete hourly monitor (all sources, including the office-PC ones) and the daily
# newspaper e-paper run. Use it if you want the agent to run here instead of (or as well as) GitHub Actions.
#
# One-time setup on the PC (PowerShell, in the repository folder):
#   1. Install Python 3.11+ (tick "Add to PATH") and Git, clone or copy the repository.
#   2. pip install -r requirements.txt
#      python -m playwright install chromium
#   3. Copy the .env file from the old PC into the repository folder (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY;
#      for -Full also GEMINI_API_KEY and the other keys used by the e-paper and alert steps).
#   4. Run this script (as above). Power settings: never sleep.
#
# Logs: data\office_pc.log, data\full_run.log, data\epaper_run.log. Remove the tasks with:
#   Get-ScheduledTask -TaskName "ACNABIN*" | Unregister-ScheduledTask -Confirm:$false

param([switch]$Full)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python -ErrorAction Stop).Source
if (-not (Test-Path (Join-Path $repo ".env"))) { throw "No .env file in $repo (needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)." }
New-Item -ItemType Directory -Force (Join-Path $repo "data") | Out-Null

function Register-AgentTask([string]$name, [string]$arguments, [string]$logName, $trigger, [int]$limitMinutes) {
    $log = Join-Path $repo "data\$logName"
    # git pull first so the PC always uses the latest source list and code
    $command = "cd /d `"$repo`" && git pull -q & `"$python`" run_monitor.py $arguments >> `"$log`" 2>&1"
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $command"
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -DontStopOnIdleEnd `
        -ExecutionTimeLimit (New-TimeSpan -Minutes $limitMinutes) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
        -Description "ACNABIN Tender Monitor: run_monitor.py $arguments" -Force | Out-Null
    Write-Host "Installed task '$name' (log: $log)"
}

$hourly = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(20) -RepetitionInterval (New-TimeSpan -Hours 1)

if ($Full) {
    # Whole monitor every hour (all web sources; office_pc sources are included because this is not GitHub)
    Register-AgentTask "ACNABIN Tender Monitor (full, hourly)" "--no-epaper" "full_run.log" $hourly 50
    # Newspaper e-papers once a day at 10:30 Dhaka time (needs GEMINI_API_KEY in .env)
    $daily = New-ScheduledTaskTrigger -Daily -At "10:30"
    Register-AgentTask "ACNABIN Tender Monitor (e-paper, daily)" "--epaper" "epaper_run.log" $daily 120
    Start-ScheduledTask -TaskName "ACNABIN Tender Monitor (full, hourly)"
} else {
    Register-AgentTask "ACNABIN Tender Monitor (office PC)" "--office-pc" "office_pc.log" $hourly 30
    Start-ScheduledTask -TaskName "ACNABIN Tender Monitor (office PC)"
}
Write-Host "Done. The first run has started; watch the log file above."
