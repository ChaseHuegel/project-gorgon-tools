param (
    [string]$ChatParseScript=".\ProjectGorgon-ParseChat.ps1",
    [string]$ChatOutputPath="output\parsed-chat.txt",
    [string]$PacketParseScript=".\ProjectGorgon-ParsePackets.ps1",
    [string]$PacketOutputPath="output\parsed-packets.txt"
)

#############################################################################################
####### Parse chat logs
#############################################################################################
$chatOutputDir = Split-Path $ChatOutputPath -Parent
if ($chatOutputDir -and -not (Test-Path $chatOutputDir)) {
    New-Item -ItemType Directory -Path $chatOutputDir | Out-Null
}

Write-Host "Parsing chat logs for items..." -ForegroundColor Cyan

& $ChatParseScript | Set-Content -Path $ChatOutputPath

if (Test-Path $ChatOutputPath) {
    $itemCount = (Get-Content $ChatOutputPath).Count
    Write-Host "Success! Saved $itemCount items to $ChatOutputPath" -ForegroundColor Green
} else {
    Write-Host "Error! Failed to save items to $ChatOutputPath" -ForegroundColor Red
    return
}

#############################################################################################
###### Parse packets
#############################################################################################
$chatOutputDir = Split-Path $PacketOutputPath -Parent
if ($chatOutputDir -and -not (Test-Path $chatOutputDir)) {
    New-Item -ItemType Directory -Path $chatOutputDir | Out-Null
}

Write-Host "Parsing packets for events..." -ForegroundColor Cyan

& $PacketParseScript | Set-Content -Path $PacketOutputPath

if (Test-Path $PacketOutputPath) {
    $itemCount = (Get-Content $PacketOutputPath).Count
    Write-Host "Success! Saved $itemCount events to $PacketOutputPath" -ForegroundColor Green
} else {
    Write-Host "Error! Failed to save events to $PacketOutputPath" -ForegroundColor Red
    return
}