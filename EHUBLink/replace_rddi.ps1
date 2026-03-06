$bin = "F:\Keil_v5\ARM\BIN"
$src = "C:\Users\MC\Desktop\wifidap\EHUBLink\bin\Release\EHUBLink.dll"

$keil = Get-Process -Name "UV4" -ErrorAction SilentlyContinue
if ($keil) {
    Write-Host "[ERROR] Keil UV4 still running. Please close Keil first." -ForegroundColor Red
    exit 1
}

Copy-Item $src "$bin\elaphureRddi.dll" -Force
$size = (Get-Item "$bin\elaphureRddi.dll").Length
Write-Host "[OK] Installed: $bin\elaphureRddi.dll ($([int]($size/1KB)) KB)" -ForegroundColor Green
Write-Host "[OK] Open Keil -> Debug Settings -> select 'EHUB WiFi Debugger'" -ForegroundColor Green
