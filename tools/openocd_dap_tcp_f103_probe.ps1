param(
    [string]$OpenOcdExe = "C:\Users\MC\Desktop\wifidap\openocd\src\openocd.exe",
    [string]$TclDir = "C:\Users\MC\Desktop\wifidap\openocd\tcl",
    [string]$Cfg = "tools/openocd_dap_tcp_f103_test.cfg",
    [int]$SpeedKHz = 100,
    [string]$LogPath = "tools/openocd_probe.log"
)

if (!(Test-Path $OpenOcdExe)) { throw "OpenOCD not found: $OpenOcdExe" }
if (!(Test-Path $TclDir)) { throw "TCL dir not found: $TclDir" }

$cmdStage1 = @(
    "-d2",
    "-s", $TclDir,
    "-f", $Cfg,
    "-c", "adapter speed $SpeedKHz",
    "-c", "init",
    "-c", "targets",
    "-c", "shutdown"
)

$cmdStage2 = @(
    "-d2",
    "-s", $TclDir,
    "-f", $Cfg,
    "-c", "adapter speed $SpeedKHz",
    "-c", "init",
    "-c", "mdw 0xE000ED00 1",
    "-c", "shutdown"
)

"=== STAGE1: link/target detect ===" | Out-File -FilePath $LogPath -Encoding utf8
& $OpenOcdExe @cmdStage1 *>&1 | Tee-Object -FilePath $LogPath -Append
$exit1 = $LASTEXITCODE

"`n=== STAGE2: minimal register read ===" | Tee-Object -FilePath $LogPath -Append
& $OpenOcdExe @cmdStage2 *>&1 | Tee-Object -FilePath $LogPath -Append
$exit2 = $LASTEXITCODE

Write-Host "EXIT_STAGE1=$exit1 EXIT_STAGE2=$exit2"

$txt = Get-Content $LogPath -Raw
$dpOk = $txt -match "SWD DPIDR 0x1ba01477"
$coreOk = $txt -match "Cortex-M3"
$cpuidOk = $txt -match "0xe000ed00:"
$mismatchErr = $txt -match "command mismatch"
$memErr = $txt -match "Failed to read memory|Failed to write memory"
$dpErr = $txt -match "Error connecting DP"

if ($dpOk -and $coreOk -and -not $mismatchErr -and -not $memErr -and -not $dpErr -and $exit1 -eq 0 -and $exit2 -eq 0) {
    Write-Host "PROBE_PASS"
    if ($cpuidOk) { Write-Host "CPUID_READ_OK" }
    exit 0
}

Write-Host "PROBE_FAIL"
exit 1
