<#
.SYNOPSIS
  Daily Briefing 本地热备脚本
  由 schtasks 在 9:25 触发（GitHub Actions 的 5 分钟后）
  如果 briefings/YYYY-MM-DD.md 已存在 → GitHub 已成功，跳过
  如果不存在 → GitHub 失败，本地执行并推送
#>

$ErrorActionPreference = "Continue"

$RepoRoot   = "E:\openworkspace1"
$Today      = (Get-Date).ToString("yyyy-MM-dd")
$BriefingFile = "$RepoRoot\briefings\$Today.md"
$LogFile    = "$RepoRoot\scripts\output\schtasks-log.txt"
$ScriptPath = "$RepoRoot\scripts\daily-briefing.py"
$SecretFile = "$RepoRoot\.opencode\secrets\modelscope-token.txt"

# 日志函数
function Write-Log($msg) {
    $time = (Get-Date).ToString("HH:mm:ss")
    "$time [HotBackup] $msg" | Out-File -FilePath $LogFile -Encoding utf8 -Append
}

Write-Log "========== 热备触发 =========="

# 1. git pull 获取最新（含 GitHub 刚提交的简报）
Write-Log "git pull 获取最新..."
cd $RepoRoot
$pullResult = git pull 2>&1 | Out-String
Write-Log "pull 结果: $pullResult"

# 2. 检查简报是否已存在
if (Test-Path $BriefingFile) {
    Write-Log "✅ 简报已存在: $BriefingFile"
    Write-Log "   GitHub Actions 已成功，本地热备无需执行"
    Write-Log "========== 热备跳过 =========="
    exit 0
}

# 3. 热备执行——GitHub 失败了
Write-Log "⚠️  简报不存在，GitHub 可能失败，本地热备开始执行..."
Write-Log "========================"

$ServerChanKey = "SCT352036ToJIzPCe6DmfvV0oIbAMIYiZw"

# 读取 token
$TokenContent = Get-Content $SecretFile -Raw
if (-not $TokenContent) {
    Write-Log "❌ 无法读取 ModelScope token"
    exit 1
}

# 执行简报脚本
$env:PYTHONIOENCODING = "utf-8"
$env:MODELSCOPE_TOKEN = $TokenContent.Trim()
$env:SERVERCHAN_KEY = $ServerChanKey

$result = & python $ScriptPath 2>&1 | Out-String
Write-Log "脚本输出:"
Write-Log $result

# 检查简报文件是否生成
if (Test-Path $BriefingFile) {
    Write-Log "✅ 热备成功，简报已生成"
    # 提交到仓库
    cd $RepoRoot
    git add briefings/ 2>&1 | Out-File -FilePath $LogFile -Encoding utf8 -Append
    git -c user.name="Daily Briefing Bot" -c user.email="bot@daily-briefing.local" commit -m "daily briefing $Today (hot backup)" 2>&1 | Out-File -FilePath $LogFile -Encoding utf8 -Append
    git push 2>&1 | Out-File -FilePath $LogFile -Encoding utf8 -Append
    Write-Log "✅ 热备已提交到仓库"
} else {
    Write-Log "❌ 热备失败，简报未生成"
}

Write-Log "========== 热备结束 =========="
