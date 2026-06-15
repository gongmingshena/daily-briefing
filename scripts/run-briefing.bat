@echo off
REM ============================================================
REM Daily Briefing wrapper for Windows Scheduled Task
REM Called by schtasks at 9:20 daily
REM Token loaded from .opencode/secrets/ (not committed to git)
REM ============================================================
setlocal enabledelayedexpansion
set PYTHONIOENCODING=utf-8
REM Read ModelScope token from secrets file
set /p MODELSCOPE_TOKEN=<"E:\openworkspace1\.opencode\secrets\modelscope-token.txt"
set SERVERCHAN_KEY=SCT352036ToJIzPCe6DmfvV0oIbAMIYiZw
set OUTPUT_DIR=E:\openworkspace1\scripts\output\Ã¿ÈÕ¼ò±¨
python "E:\openworkspace1\scripts\daily-briefing.py" >> "E:\openworkspace1\scripts\output\schtasks-log.txt" 2>&1
endlocal
