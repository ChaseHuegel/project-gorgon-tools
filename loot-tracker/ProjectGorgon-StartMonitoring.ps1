param (
    [string]$CapturePacketsScriptPath=".\ProjectGorgon-CapturePackets.ps1",
    [string]$CaptureZonesScriptPath=".\ProjectGorgon-CaptureZones.ps1",
    [string]$CaptureTargetsScriptPath=".\ProjectGorgon-CaptureTargets.ps1"
)

Write-Host "Starting background scripts..." -ForegroundColor Cyan

$proc1 = Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$CapturePacketsScriptPath`"" -PassThru -NoNewWindow
$proc2 = Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$CaptureZonesScriptPath`"" -PassThru -NoNewWindow
$proc3 = Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$CaptureTargetsScriptPath`"" -PassThru -NoNewWindow

Write-Host "Scripts are running (PIDs: $($proc1.Id), $($proc2.Id), $($proc3.Id))." -ForegroundColor Green
Write-Host "Press ANY KEY to stop both scripts and exit..." -ForegroundColor Yellow

$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

Write-Host "`nStopping scripts..." -ForegroundColor Cyan

if (-not $proc1.HasExited) {
    taskkill.exe /PID $proc1.Id /T /F | Out-Null
    Write-Host "Stopped packet capture (PID: $($proc1.Id))" -ForegroundColor Gray
}

if (-not $proc2.HasExited) {
    taskkill.exe /PID $proc2.Id /T /F | Out-Null
    Write-Host "Stopped zone capture (PID: $($proc2.Id))" -ForegroundColor Gray
}

if (-not $proc3.HasExited) {
    taskkill.exe /PID $proc3.Id /T /F | Out-Null
    Write-Host "Stopped target capture (PID: $($proc3.Id))" -ForegroundColor Gray
}

Write-Host "All tasks stopped." -ForegroundColor Green