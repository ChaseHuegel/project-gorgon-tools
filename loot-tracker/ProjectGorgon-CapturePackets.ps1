param (
    [switch]$ListInterfaces,
    [string]$TSharkPath = "tshark.exe",
    [string]$OutputFolder = "output\captures\",
    [int]$InterfaceId = 4  # Run with -ListInterfaces to find this
)

# Ensure output folder exists
if (-not (Test-Path $OutputFolder)) {
    New-Item -ItemType Directory -Path $OutputFolder | Out-Null
}

if ($ListInterfaces) {
    & $TSharkPath -D
    Write-Host "`nUpdate `$InterfaceId in the script to match your adapter." -ForegroundColor Yellow
    exit
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$rawPcap = Join-Path $OutputFolder "raw_$timestamp.pcapng"
$jsonFile = Join-Path $OutputFolder "capture_$timestamp.json"

Write-Host "Starting TShark Capture..." -ForegroundColor Cyan
Write-Host "Saving raw data to: $rawPcap" -ForegroundColor DarkGray

$captureArgs = @("-i", $InterfaceId, "-w", $rawPcap)
$tsharkProcess = Start-Process -FilePath $TSharkPath -ArgumentList $captureArgs -PassThru -NoNewWindow

Write-Host "`n[ RECORDING IN PROGRESS ]" -ForegroundColor Green -BackgroundColor Black
Write-Host "Press ANY KEY to Stop capturing..." -ForegroundColor Yellow

$null = Read-Host

Write-Host "`nStopping TShark..." -ForegroundColor Cyan
Stop-Process -Id $tsharkProcess.Id -Force