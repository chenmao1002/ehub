# ============================================================
# uninstall_elaphurelink.ps1
# 从 Keil MDK 卸载 elaphureLink RDDI DLL
#
# 使用方法 (以管理员身份运行):
#   .\uninstall_elaphurelink.ps1 [-KeilPath "C:\Keil_v5"]
# ============================================================
param(
    [string]$KeilPath = ""
)

$ErrorActionPreference = "Stop"

# ── 自动检测 Keil 安装路径 ──
function Find-KeilPath {
    $searchPaths = @(
        "C:\Keil_v5",
        "D:\Keil_v5",
        "C:\Keil",
        "D:\Keil",
        "${env:ProgramFiles}\Keil_v5",
        "${env:ProgramFiles(x86)}\Keil_v5"
    )
    foreach ($p in $searchPaths) {
        if (Test-Path "$p\UV4\UV4.exe") { return $p }
    }
    return $null
}

if (-not $KeilPath) {
    $KeilPath = Find-KeilPath
    if (-not $KeilPath) {
        Write-Host "[ERROR] 未找到 Keil MDK 安装路径，请使用 -KeilPath 参数指定" -ForegroundColor Red
        exit 1
    }
}

$UV4Dir = Join-Path $KeilPath "UV4"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  elaphureLink Keil 卸载器" -ForegroundColor Cyan
Write-Host "  Keil 路径: $KeilPath" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# ── 删除 elaphureLink DLL ──
$filesToRemove = @("elaphureRddi.dll", "elaphureLink.dll")
foreach ($f in $filesToRemove) {
    $fp = Join-Path $UV4Dir $f
    if (Test-Path $fp) {
        Remove-Item $fp -Force
        Write-Host "[REMOVE] 已删除 $fp" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "[OK] elaphureLink 已从 Keil 卸载" -ForegroundColor Green
