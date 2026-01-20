param (
    [switch]$ListInterfaces,
    [string]$TSharkPath = "tshark.exe",
    [string]$OutputFolder = "output\captures\",
    [int]$InterfaceId = 4,  # Run with -ListInterfaces to find this
    [string]$DisplayFilter = "tcp.payload contains 53:65:61:72:63:68:20:43:6f:72:70:73:65:20:6f:66:20" # "Search Corpse of "
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
Write-Host "Press ANY KEY to Stop capturing and convert to JSON..." -ForegroundColor Yellow

$null = Read-Host

Write-Host "`nStopping TShark..." -ForegroundColor Cyan
Stop-Process -Id $tsharkProcess.Id -Force

# Small buffer to ensure file handle is released
Start-Sleep -Seconds 2

if (Test-Path $rawPcap) {
    Write-Host "Converting to JSON (This may take a moment)..." -ForegroundColor Cyan
    
    $convertCmd = "& `"$TSharkPath`" -r `"$rawPcap`" -2 -Y `"$DisplayFilter`" -T json | Out-File `"$jsonFile`" -Encoding ASCII"
    Invoke-Expression $convertCmd

    Write-Host "Success! JSON saved to: $jsonFile" -ForegroundColor Green
}
else {
    Write-Error "Raw capture file was not found. TShark may have failed to start."
}