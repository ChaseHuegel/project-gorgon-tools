param (
    [string]$OutputPath="output\loot.csv",
    [string]$ChatParseScript=".\ProjectGorgon-ParseChat.ps1",
    [string]$ChatOutputPath="output\parsed-chat.txt",
    [string]$PacketParseScript=".\ProjectGorgon-ParsePackets.ps1",
    [string]$PacketOutputPath="output\parsed-packets.txt",
    [string]$BuildTableScript=".\ProjectGorgon-CompileLootEvents.ps1"
)

#############################################################################################
####### Parse chat logs
#############################################################################################
$chatOutputDir = Split-Path $ChatOutputPath -Parent
if ($chatOutputDir -and -not (Test-Path $chatOutputDir)) {
    New-Item -ItemType Directory -Path $chatOutputDir | Out-Null
}

Write-Host "Parsing chat logs for items..." -ForegroundColor Cyan

& $ChatParseScript | ConvertTo-Json -Depth 2 | Set-Content -Path $ChatOutputPath

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
$packetOutputDir = Split-Path $PacketOutputPath -Parent
if ($packetOutputDir -and -not (Test-Path $packetOutputDir)) {
    New-Item -ItemType Directory -Path $packetOutputDir | Out-Null
}

Write-Host "Parsing packets for events..." -ForegroundColor Cyan

& $PacketParseScript | ConvertTo-Json -Depth 2 | Set-Content -Path $PacketOutputPath

if (Test-Path $PacketOutputPath) {
    $itemCount = (Get-Content $PacketOutputPath).Count
    Write-Host "Success! Saved $itemCount events to $PacketOutputPath" -ForegroundColor Green
} else {
    Write-Host "Error! Failed to save events to $PacketOutputPath" -ForegroundColor Red
    return
}

#############################################################################################
###### Compile loot and events into a table
#############################################################################################
$outputDir = Split-Path $OutputPath -Parent
if ($outputDir -and -not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}

Write-Host "Correlating loot and events to a loot table..." -ForegroundColor Cyan

$correlatedLoot = & $BuildTableScript

$exportData = $correlatedLoot | Select-Object Time, Source, ID, Activity, Item, Amount, Status
$exportData | Export-Csv $OutputPath -NoTypeInformation -Encoding UTF8

if (Test-Path $OutputPath) {
    $itemCount = (Import-Csv $OutputPath).Count
    Write-Host "Success! Saved $itemCount loot entries to $OutputPath" -ForegroundColor Green
} else {
    Write-Host "Error! Failed to loot table to $OutputPath" -ForegroundColor Red
    return
}

$exportData | Out-GridView -Title "Loot Table Results" -Wait