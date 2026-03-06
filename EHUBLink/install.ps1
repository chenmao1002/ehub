# ============================================================
# install.ps1  —  EHUBLink Keil MDK 安装脚本
#
# 将 EHUBLink.dll 以 elaphureRddi.dll 名称安装到 Keil UV4 目录
# 无需 WPF 代理进程, 直接通过 OpenOCD TCP (port 6000) 连接 EHUB
#
# 使用方法 (以管理员身份运行):
#   .\install.ps1 [-KeilPath "C:\Keil_v5"] [-Host "ehub.local"] [-Port 6000]
# ============================================================
param(
    [string]$KeilPath = "",
    [string]$Host     = "ehub.local",
    [int]   $Port     = 6000
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# ── 1. 寻找 EHUBLink.dll ──────────────────────────────────────
$dllCandidates = @(
    (Join-Path $ScriptDir "bin\Release\EHUBLink.dll"),
    (Join-Path $ScriptDir "bin\Debug\EHUBLink.dll"),
    (Join-Path $ScriptDir "EHUBLink.dll")
)
$sourceDll = $null
foreach ($c in $dllCandidates) {
    if (Test-Path $c) { $sourceDll = $c; break }
}
if (-not $sourceDll) {
    Write-Host "[ERROR] 未找到 EHUBLink.dll，请先在 Visual Studio 中编译项目" -ForegroundColor Red
    exit 1
}
Write-Host "[INFO] 使用 DLL: $sourceDll" -ForegroundColor Cyan

# ── 2. 定位 Keil 安装目录 ─────────────────────────────────────
function Find-KeilPath {
    $paths = @(
        "C:\Keil_v5", "D:\Keil_v5", "C:\Keil", "D:\Keil",
        "${env:ProgramFiles}\Keil_v5",
        "${env:ProgramFiles(x86)}\Keil_v5"
    )
    foreach ($p in $paths) {
        if (Test-Path "$p\UV4\UV4.exe") { return $p }
    }
    try {
        $reg = Get-ItemProperty -Path "HKLM:\SOFTWARE\WOW6432Node\Keil\Products\MDK" -EA SilentlyContinue
        if ($reg -and $reg.Path) {
            $kp = Split-Path $reg.Path -Parent
            if (Test-Path "$kp\UV4\UV4.exe") { return $kp }
        }
    } catch {}
    return $null
}

if (-not $KeilPath) {
    $KeilPath = Find-KeilPath
    if (-not $KeilPath) {
        Write-Host "[ERROR] 未找到 Keil MDK，请使用 -KeilPath 指定路径" -ForegroundColor Red
        exit 1
    }
}

$UV4Dir = Join-Path $KeilPath "UV4"
if (-not (Test-Path "$UV4Dir\UV4.exe")) {
    Write-Host "[ERROR] 无效的 Keil 路径: $KeilPath" -ForegroundColor Red
    exit 1
}

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  EHUBLink Keil 安装器" -ForegroundColor Cyan
Write-Host "  Keil 路径 : $KeilPath" -ForegroundColor Cyan
Write-Host "  EHUB 地址 : ${Host}:${Port}" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

# ── 3. 备份原有 elaphureRddi.dll──────────────────────────────
$target    = Join-Path $UV4Dir "elaphureRddi.dll"
$backupDir = Join-Path $UV4Dir "EHUBLink_backup"

if (Test-Path $target) {
    if (-not (Test-Path $backupDir)) {
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    }
    $stamp  = Get-Date -Format "yyyyMMdd_HHmmss"
    $backup = Join-Path $backupDir "elaphureRddi_$stamp.dll"
    Copy-Item $target $backup -Force
    Write-Host "[BACKUP] $target → $backup" -ForegroundColor Yellow
}

# ── 4. 安装 DLL ───────────────────────────────────────────────
Copy-Item $sourceDll -Destination $target -Force
Write-Host "[INSTALL] EHUBLink.dll → $target" -ForegroundColor Green

# ── 5. 写入 ehublink.cfg ──────────────────────────────────────
$cfgPath = Join-Path $UV4Dir "ehublink.cfg"
$cfgContent = @"
# EHUBLink configuration
host=$Host
port=$Port
"@
Set-Content -Path $cfgPath -Value $cfgContent -Encoding UTF8
Write-Host "[CONFIG] ehublink.cfg → $cfgPath" -ForegroundColor Green

Write-Host ""
Write-Host "================================================" -ForegroundColor Green
Write-Host "  安装完成!" -ForegroundColor Green
Write-Host ""
Write-Host "  使用步骤:" -ForegroundColor White
Write-Host "  1. 确保 EHUB 已上电并接入 WiFi" -ForegroundColor White
Write-Host "  2. 在 Keil 中选择 CMSIS-DAP 调试器" -ForegroundColor White
Write-Host "  3. 无需运行任何代理程序，直接调试!" -ForegroundColor White
Write-Host "================================================" -ForegroundColor Green
