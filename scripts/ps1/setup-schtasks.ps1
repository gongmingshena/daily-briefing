<#
.SYNOPSIS
  Set daily briefing Windows scheduled task
  Runs daily-briefing.py at 9:20 AM daily, pushes via ServerChan
#>

$TaskName     = "DailyBriefing"
$TaskDesc     = "Daily 7:45 hot backup — runs if GitHub Actions (2:00 AM) failed"
$TaskTime     = "07:45"
$HotBackupScript = "powershell.exe -ExecutionPolicy Bypass -File E:\openworkspace1\scripts\ps1\hot-backup.ps1"
$ScriptPath   = "E:\openworkspace1\scripts\daily-briefing.py"
$PythonExe    = "python"
$OutputDir    = "E:\openworkspace1\scripts\output\每日简报"
$LogFile      = "E:\openworkspace1\scripts\output\schtasks-log.txt"
$SecretFile   = "E:\openworkspace1\.opencode\secrets\modelscope-token.txt"
$ServerChanKey = "SCT352036ToJIzPCe6DmfvV0oIbAMIYiZw"

Write-Host "=== Daily Briefing Scheduled Task Setup ===" -ForegroundColor Cyan

if (-not (Test-Path $ScriptPath)) {
    Write-Host "ERROR: Script not found: $ScriptPath" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $SecretFile)) {
    Write-Host "ERROR: ModelScope token file not found" -ForegroundColor Red
    exit 1
}

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")
if (-not $isAdmin) {
    Write-Host "ERROR: Admin rights required" -ForegroundColor Red
    exit 1
}

$existing = schtasks /Query /TN $TaskName 2>$null
if ($existing) {
    Write-Host "Deleting existing task: $TaskName" -ForegroundColor Yellow
    schtasks /Delete /TN $TaskName /F
}

$Command = "cmd /c powershell.exe -ExecutionPolicy Bypass -File E:\openworkspace1\scripts\ps1\hot-backup.ps1"

Write-Host "Creating scheduled task: $TaskName (daily at $TaskTime, hot backup)" -ForegroundColor Cyan

schtasks /Create /TN $TaskName /TR $Command /SC DAILY /ST $TaskTime /F

if ($LASTEXITCODE -eq 0) {
    Write-Host "SUCCESS: Task created" -ForegroundColor Green
    Write-Host "  Name: $TaskName"
    Write-Host "  Time: Daily $TaskTime (backup for GitHub Actions at 2:00 AM)"
    Write-Host "  Hot backup script: $HotBackupScript"
    Write-Host "  Log: $LogFile"
} else {
    Write-Host "FAILED: Task creation error (code: $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}