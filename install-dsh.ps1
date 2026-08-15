#Requires -Version 5.1
<#
.SYNOPSIS
  DeepSeek Harness (dsh) Windows 一键安装脚本

.DESCRIPTION
  检查/安装 Node.js -> 安装 pnpm -> npm 全局安装 @deepseek-ai/dsh
  -> 配置 DEEPSEEK_API_KEY -> PATH 校验 -> headless 冒烟测试 -> 启动 Web UI

  运行方式（右键"使用 PowerShell 运行"，或）:
    powershell -ExecutionPolicy Bypass -File .\install-dsh.ps1

.PARAMETER SkipNode     跳过 Node.js 检查/安装（已装好 >=22.19 或 >=24 时用）
.PARAMETER SkipPnpm     跳过 pnpm 安装（dsh 本体不需要 pnpm，仅未来装插件需要）
.PARAMETER ApiKey       直接传入 DEEPSEEK_API_KEY，避免交互输入
.PARAMETER HeadlessTask 安装后执行一次 headless 任务（终端打印答案后退出）
.PARAMETER NoLaunch     只安装，不启动任何东西
.PARAMETER SkipSmoke    跳过 headless 冒烟测试（省时间/省 token）

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install-dsh.ps1
  powershell -ExecutionPolicy Bypass -File .\install-dsh.ps1 -ApiKey "sk-xxxx" -HeadlessTask "你好"
#>
[CmdletBinding()]
param(
  [switch]$SkipNode,
  [switch]$SkipPnpm,
  [string]$ApiKey = '',
  [string]$HeadlessTask = '',
  [switch]$NoLaunch,
  [switch]$SkipSmoke
)

$ErrorActionPreference = 'Continue'

function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Get-ToolVersion([string]$exe) {
  try {
    $o = (& $exe -v 2>$null | Out-String).Trim()
    return $o
  } catch {
    return ''
  }
}

function Write-Step([string]$msg) {
  Write-Host ''
  Write-Host "==> $msg" -ForegroundColor Cyan
}

# ---------- 1/6 Node.js ----------
Write-Step '1/6 检查 Node.js（需要 >=22.19 或 >=24）'
Refresh-Path
$nodeOk = $false
$nv = Get-ToolVersion 'node'
if ($nv -match '^v(\d+)\.(\d+)') {
  $major = [int]$Matches[1]
  $minor = [int]$Matches[2]
  if (($major -eq 22 -and $minor -ge 19) -or $major -ge 24) { $nodeOk = $true }
}
if ($nodeOk) {
  Write-Host "  [OK] Node.js $nv" -ForegroundColor Green
} elseif ($SkipNode) {
  Write-Warning "  跳过 Node 安装，但当前版本 '$nv' 可能不满足要求（需要 >=22.19 或 >=24）"
} else {
  Write-Host '  未检测到可用 Node.js，尝试 winget 安装 LTS...'
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if (-not $winget) {
    Write-Error '  未找到 winget。请手动安装 Node.js LTS (https://nodejs.org/)，装完重跑本脚本。'
    exit 1
  }
  winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
  if ($LASTEXITCODE -ne 0) {
    Write-Error "  winget 安装 Node.js 失败（exit $LASTEXITCODE），请手动安装后重跑。"
    exit 1
  }
  Refresh-Path
  $nv = Get-ToolVersion 'node'
  Write-Host "  [OK] Node.js $nv 安装完成" -ForegroundColor Green
}

# ---------- 2/6 pnpm（可选） ----------
Write-Step '2/6 安装 pnpm（dsh 本体不需要；仅未来安装 TUI 插件时需要）'
if ($SkipPnpm) {
  Write-Host '  已跳过（-SkipPnpm）'
} else {
  try {
    npm install -g pnpm@11.7.0 2>$null
    if ($LASTEXITCODE -eq 0) {
      Refresh-Path
      $pv = Get-ToolVersion 'pnpm'
      Write-Host "  [OK] pnpm $pv" -ForegroundColor Green
    } else {
      Write-Warning '  pnpm 安装失败（可忽略，dsh 本体不依赖 pnpm）'
    }
  } catch {
    Write-Warning '  pnpm 安装异常（可忽略）'
  }
}

# ---------- 3/6 dsh CLI ----------
Write-Step '3/6 安装 dsh CLI（@deepseek-ai/dsh）'
npm install -g "@deepseek-ai/dsh"
if ($LASTEXITCODE -ne 0) {
  Write-Error '  dsh 安装失败，请检查网络/代理后重试。'
  exit 1
}
Refresh-Path
$dv = Get-ToolVersion 'dsh'
Write-Host "  [OK] dsh $dv" -ForegroundColor Green

# ---------- 4/6 PATH 校验 ----------
Write-Step '4/6 校验 PATH'
$cmd = Get-Command dsh -ErrorAction SilentlyContinue
if (-not $cmd) {
  $npmPrefix = (& npm prefix -g 2>$null | Out-String).Trim()
  if ($npmPrefix -and (Test-Path $npmPrefix)) {
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($userPath -notlike "*$npmPrefix*") {
      [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $npmPrefix), 'User')
      Write-Host "  已将 $npmPrefix 写入用户 PATH（新终端永久生效）" -ForegroundColor Yellow
    }
    $env:Path = $env:Path + ';' + $npmPrefix
    $cmd = Get-Command dsh -ErrorAction SilentlyContinue
  }
}
if ($cmd) {
  Write-Host "  [OK] dsh 位于: $($cmd.Source)" -ForegroundColor Green
} else {
  Write-Warning '  当前会话仍找不到 dsh，请重开终端再试（PATH 已写入用户环境变量）'
}

# ---------- 5/6 API Key ----------
Write-Step '5/6 配置 DEEPSEEK_API_KEY'
if ($ApiKey -ne '') {
  [Environment]::SetEnvironmentVariable('DEEPSEEK_API_KEY', $ApiKey.Trim(), 'User')
  $env:DEEPSEEK_API_KEY = $ApiKey.Trim()
  Write-Host '  [OK] 已用 -ApiKey 写入用户环境变量' -ForegroundColor Green
} elseif (-not $env:DEEPSEEK_API_KEY) {
  $key = Read-Host '  请输入 DEEPSEEK_API_KEY (sk-...，直接回车则跳过)'
  if ([string]::IsNullOrWhiteSpace($key)) {
    Write-Warning '  未设置 Key；之后可写入用户环境变量或 ~/.dsh/.env 再使用'
  } else {
    [Environment]::SetEnvironmentVariable('DEEPSEEK_API_KEY', $key.Trim(), 'User')
    $env:DEEPSEEK_API_KEY = $key.Trim()
    Write-Host '  [OK] 已写入用户环境变量' -ForegroundColor Green
  }
} else {
  Write-Host "  [OK] 环境变量已存在（长度 $($env:DEEPSEEK_API_KEY.Length)）" -ForegroundColor Green
}

# ---------- 6/6 冒烟测试 + 启动 ----------
Write-Step '6/6 冒烟测试 + 启动'
if (-not $SkipSmoke -and $env:DEEPSEEK_API_KEY) {
  Write-Host '  运行 headless 冒烟测试（首次会初始化 profile，约 10~60 秒）...'
  & dsh --profile headless "只回复：OK"
  if ($LASTEXITCODE -eq 0) {
    Write-Host '  [OK] 冒烟测试通过' -ForegroundColor Green
  } else {
    Write-Warning "  冒烟测试退出码 $LASTEXITCODE（可能是网络或 Key 问题，不影响已完成的安装）"
  }
}

if ($NoLaunch) {
  Write-Host ''
  Write-Host '安装完成（-NoLaunch）。手动启动: dsh web' -ForegroundColor Green
  return
}

if ($HeadlessTask -ne '') {
  Write-Host ''
  Write-Host "执行 headless 任务..."
  & dsh --profile headless $HeadlessTask
  exit $LASTEXITCODE
}

Write-Host ''
Write-Host '启动 Web UI (http://127.0.0.1:3080)，按 Ctrl+C 停止...' -ForegroundColor Green
& dsh web

Write-Host ''
Write-Host @"
============================================================
📌 关于 TUI（终端界面）：
   官方 TUI 插件 turtle-ui 目前尚未发布（GitHub/npm 上均不存在，
   文档中仅作为示例提及）。发布后启用：
     dsh plugin --profile tui add github:deepseek-harness/turtle-ui
     dsh --profile tui
   当前可用的终端用法：
     dsh web                          # Web UI
     dsh --profile headless "任务"     # 终端跑一次任务，打印答案退出
============================================================
"@
