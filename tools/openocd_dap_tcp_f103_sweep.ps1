param(
    [string]$OpenOcdExe = "C:\Users\MC\Desktop\wifidap\openocd\src\openocd.exe",
    [string]$TclDir = "C:\Users\MC\Desktop\wifidap\openocd\tcl",
    [string]$Cfg = "tools/openocd_dap_tcp_f103_test.cfg",
    [string]$Hex = "C:/Users/MC/Desktop/wifidap/stm32f103_test/MDK-ARM/stm32f103_test/stm32f103_test.hex",
    [int[]]$Speeds = @(1000, 400, 200),
    [string]$LogDir = "tools/logs"
)

if (!(Test-Path $OpenOcdExe)) { throw "OpenOCD not found: $OpenOcdExe" }
if (!(Test-Path $TclDir)) { throw "TCL dir not found: $TclDir" }
if (!(Test-Path $Hex)) { throw "HEX not found: $Hex" }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$summary = @()

foreach ($spd in $Speeds) {
    $log = Join-Path $LogDir ("openocd_dap_tcp_f103_{0}k.log" -f $spd)
    Write-Host "=== TRY ${spd}kHz ==="

    $cmd = @(
        "-d2",
        "-s", $TclDir,
        "-f", $Cfg,
        "-c", "gdb_port disabled",
        "-c", "telnet_port disabled",
        "-c", "tcl_port disabled",
        "-c", "adapter speed $spd",
        "-c", "init",
        "-c", "reset halt",
        "-c", "program $Hex verify reset",
        "-c", "shutdown"
    )

    & $OpenOcdExe @cmd *>&1 | Tee-Object -FilePath $log
    $exitCode = $LASTEXITCODE

    $txt = Get-Content $log -Raw
    $dpOk = $txt -match "SWD DPIDR 0x1ba01477"
    $verifyOk = $txt -match "Verified OK|verified OK|Verify successful"
    $memErr = $txt -match "Failed to read memory"
    $clockErr = $txt -match "CMD_DAP_SWJ_CLOCK failed"
    $progErr = $txt -match "Programming Failed|Error:"

    $status = if ($exitCode -eq 0 -and $verifyOk -and -not $memErr -and -not $progErr) { "PASS" } else { "FAIL" }

    $summary += [pscustomobject]@{
        SpeedKHz = $spd
        ExitCode = $exitCode
        DpOk = $dpOk
        VerifyOk = $verifyOk
        MemReadErr = $memErr
        ClockErr = $clockErr
        Status = $status
        Log = $log
    }

    if ($status -eq "PASS") {
        Write-Host "PASS at ${spd}kHz"
        break
    }
}

$summary | Format-Table -AutoSize

# non-zero when all failed
if (($summary | Where-Object { $_.Status -eq 'PASS' }).Count -eq 0) {
    exit 1
}
exit 0
