<#
.SYNOPSIS
  Daily Briefing 本地执行 (7:45)
  GitHub Actions (2:00) 只存档不推送，本地负责实际推送
  本脚本始终执行，不受 archive 是否已存在影响
#>

$ErrorActionPreference = "Continue"

$RepoRoot   = "E:\openworkspace1"
$Today      = (Get-Date).ToString("yyyy-MM-dd")
$BriefingFile = "$RepoRoot\briefings\$Today.md"
$LogFile    = "$RepoRoot\scripts\output\schtasks-log.txt"
$ScriptPath = "$RepoRoot\scripts\daily-briefing.py"
$SecretFile = "$RepoRoot\.opencode\secrets\modelscope-token.txt"

function Write-Log($msg) {
    $time = (Get-Date).ToString("HH:mm:ss")
    "$time [LocalRunner] $msg" | Out-File -FilePath $LogFile -Encoding utf8 -Append
}

Write-Log "=== LocalRunner triggered ==="

# Step 1: git pull (获取 GitHub 凌晨存档的最新状态)
Write-Log "git pull..."
Push-Location $RepoRoot
$pullResult = git pull 2>&1 | Out-String
Write-Log "pull: $($pullResult.Trim())"

# Step 2: 读取 token
$ServerChanKey = "SCT352036ToJIzPCe6DmfvV0oIbAMIYiZw"
$TokenContent = Get-Content $SecretFile -Raw
if (-not $TokenContent) {
    Write-Log "ERROR: cannot read ModelScope token"
    Pop-Location
    exit 1
}

$env:PYTHONIOENCODING = "utf-8"
$env:MODELSCOPE_TOKEN = $TokenContent.Trim()
$env:SERVERCHAN_KEY = $ServerChanKey
# 不设 SKIP_PUSH → 本地负责推送

Write-Log "Running daily-briefing.py (with push)..."
$result = & python $ScriptPath 2>&1 | Out-String
Write-Log "Output: $($result.Trim())"

# Step 3: 提交存档到仓库
if (Test-Path $BriefingFile) {
    Write-Log "Briefing generated, committing to repo..."
    & git add briefings/ 2>&1 | Out-File -FilePath $LogFile -Encoding utf8 -Append
    $commitMsg = "daily briefing $Today"
    & git -c user.name=Bot -c user.email=bot@local commit -m $commitMsg 2>&1 | Out-File -FilePath $LogFile -Encoding utf8 -Append
    & git push 2>&1 | Out-File -FilePath $LogFile -Encoding utf8 -Append
    Write-Log "Committed to repo"
} else {
    Write-Log "ERROR: no briefing generated"
}

Pop-Location
Write-Log "=== LocalRunner finished ==="