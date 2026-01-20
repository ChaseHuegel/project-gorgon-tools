# --- CONFIGURATION ---
$TSharkPath = "D:\Wireshark\tshark.exe"
$OutputFolder = "D:\Downloads\GameCaptures"
$InterfaceId = 4  # Run with -ListInterfaces to check this number
$DisplayFilter = "tcp.payload contains 53:65:61:72:63:68:20:43:6f:72:70:73:65:20:6f:66:20" # Only keep loot window packets

# --- SETUP ---
if (-not (Test-Path $TSharkPath)) {
    Write-Error "TShark not found. Please install Wireshark."
    exit
}
if (-not (Test-Path $OutputFolder)) {
    New-Item -ItemType Directory -Path $OutputFolder | Out-Null
}

# --- HELPER: LIST INTERFACES ---
param ( [switch]$ListInterfaces )
if ($ListInterfaces) {
    & $TSharkPath -D
    Write-Host "`nUpdate `$InterfaceId in the script to match your adapter." -ForegroundColor Yellow
    exit
}

# --- START CAPTURE ---
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$rawPcap = Join-Path $OutputFolder "raw_$timestamp.pcapng"
$jsonFile = Join-Path $OutputFolder "capture_$timestamp.json"

Write-Host "Starting TShark Capture..." -ForegroundColor Cyan
Write-Host "Saving raw data to: $rawPcap" -ForegroundColor DarkGray

# Start TShark without a duration limit (-w writes to file)
$captureArgs = @("-i", $InterfaceId, "-w", $rawPcap)
$tsharkProcess = Start-Process -FilePath $TSharkPath -ArgumentList $captureArgs -PassThru

# --- WAIT FOR USER INPUT ---
Write-Host "`n[ RECORDING IN PROGRESS ]" -ForegroundColor Green -BackgroundColor Black
Write-Host "Press ANY KEY to Stop capturing and convert to JSON..." -ForegroundColor Yellow

$null = Read-Host

# --- STOP CAPTURE ---
Write-Host "`nStopping TShark..." -ForegroundColor Cyan
Stop-Process -Id $tsharkProcess.Id -Force

# Small buffer to ensure file handle is released
Start-Sleep -Seconds 2

# --- CONVERT TO JSON ---
if (Test-Path $rawPcap) {
    Write-Host "Converting to JSON (This may take a moment)..." -ForegroundColor Cyan
    
    # We use tshark again to read (-r) the raw file and export (-T) to json
    $convertCmd = "& `"$TSharkPath`" -r `"$rawPcap`" -2 -Y `"$DisplayFilter`" -T json | Out-File `"$jsonFile`" -Encoding ASCII"
    Invoke-Expression $convertCmd

    Write-Host "Success! JSON saved to: $jsonFile" -ForegroundColor Green
    
    # Optional: Delete the raw PCAP to save space
    # Remove-Item $rawPcap
}
else {
    Write-Error "Raw capture file was not found. TShark may have failed to start."
}