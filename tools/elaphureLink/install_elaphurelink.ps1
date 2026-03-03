# ============================================================
# install_elaphurelink.ps1
# 将 elaphureLink RDDI DLL 安装到 Keil MDK，实现无线 DAP 调试
#
# 使用方法 (以管理员身份运行):
#   .\install_elaphurelink.ps1 [-KeilPath "C:\Keil_v5"]
# ============================================================
param(
    [string]$KeilPath = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

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
    # 尝试从注册表查找
    try {
        $regPath = Get-ItemProperty -Path "HKLM:\SOFTWARE\WOW6432Node\Keil\Products\MDK" -ErrorAction SilentlyContinue
        if ($regPath -and $regPath.Path) {
            $kp = Split-Path $regPath.Path -Parent
            if (Test-Path "$kp\UV4\UV4.exe") { return $kp }
        }
    } catch {}
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
if (-not (Test-Path "$UV4Dir\UV4.exe")) {
    Write-Host "[ERROR] 无效的 Keil 路径: $KeilPath (未找到 UV4\UV4.exe)" -ForegroundColor Red
    exit 1
}

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  elaphureLink Keil 安装器" -ForegroundColor Cyan
Write-Host "  Keil 路径: $KeilPath" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# ── 备份原始 RDDI DLL ──
$rddiDll = Join-Path $UV4Dir "elaphureRddi.dll"
$backupDir = Join-Path $UV4Dir "elaphureLink_backup"

# elaphureLink 的 RDDI DLL 替换 Keil 的 RDDI DLL
# 实际上 elaphureLink 安装的是: 将 elaphureRddi.dll 复制到 UV4 目录
$sourceRddi = Join-Path $ScriptDir "elaphureRddi.dll"
$sourceDll = Join-Path $ScriptDir "elaphureLink.dll"

if (-not (Test-Path $sourceRddi)) {
    Write-Host "[ERROR] 未找到 $sourceRddi" -ForegroundColor Red
    exit 1
}

# 创建备份目录
if (-not (Test-Path $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    Write-Host "[INFO] 创建备份目录: $backupDir" -ForegroundColor Yellow
}

# 复制 elaphureLink DLL 到 UV4
Write-Host "[INSTALL] 复制 elaphureRddi.dll → $UV4Dir" -ForegroundColor Green
Copy-Item $sourceRddi -Destination $UV4Dir -Force

Write-Host "[INSTALL] 复制 elaphureLink.dll → $UV4Dir" -ForegroundColor Green
Copy-Item $sourceDll -Destination $UV4Dir -Force

# 更新 elaphureLink 配置中的 Keil 路径
$configFile = Join-Path $ScriptDir "elaphureLink.Wpf.exe.config"
if (Test-Path $configFile) {
    $content = Get-Content $configFile -Raw
    $content = $content -replace '(<setting name="keilPathInstallation" serializeAs="String">\s*<value>)[^<]*(</value>)', "`$1$KeilPath`$2"
    Set-Content $configFile -Value $content -Encoding UTF8
    Write-Host "[CONFIG] 已更新 elaphureLink 配置: keilPath = $KeilPath" -ForegroundColor Green
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  安装完成!" -ForegroundColor Green
Write-Host "" -ForegroundColor Green
Write-Host "  使用步骤:" -ForegroundColor White
Write-Host "  1. 运行 elaphureLink.Wpf.exe" -ForegroundColor White
Write-Host "  2. 设置设备地址为 ehub.local (或 ESP32 IP)" -ForegroundColor White
Write-Host "  3. 点击 Start 启动代理" -ForegroundColor White
Write-Host "  4. 在 Keil 中选择 CMSIS-DAP 调试器" -ForegroundColor White
Write-Host "  5. 开始无线调试!" -ForegroundColor White
Write-Host "============================================" -ForegroundColor Green
