<#
.SYNOPSIS
  Set daily briefing Windows scheduled task
  Runs daily-briefing.py at 9:20 AM daily, pushes via ServerChan
#>

$TaskName     = "DailyBriefing"
$TaskDesc     = "Daily 9:20 auto generate and push info briefing"
$TaskTime     = "09:20"
$ScriptPath   = "E:\openworkspace1\scripts\daily-briefing.py"
$PythonExe    = "python"
$OutputDir    = "E:\openworkspace1\scripts\output\DailyBriefing"
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

$Command = "cmd /c set PYTHONIOENCODING=utf-8 && set MODELSCOPE_TOKEN=$(Get-Content $SecretFile -Raw) && set SERVERCHAN_KEY=$ServerChanKey && set OUTPUT_DIR=$OutputDir && $PythonExe $ScriptPath >> $LogFile 2>&1"

Write-Host "Creating scheduled task: $TaskName (daily at $TaskTime)" -ForegroundColor Cyan

schtasks /Create /TN $TaskName /TR $Command /SC DAILY /ST $TaskTime /F

if ($LASTEXITCODE -eq 0) {
    Write-Host "SUCCESS: Task created" -ForegroundColor Green
    Write-Host "  Name: $TaskName"
    Write-Host "  Time: Daily $TaskTime"
    Write-Host "  Script: $ScriptPath"
    Write-Host "  Log: $LogFile"
} else {
    Write-Host "FAILED: Task creation error (code: $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}