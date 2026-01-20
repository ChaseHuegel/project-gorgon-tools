param (
    [string]$ChatParseScript=".\ProjectGorgon-ParseChat.ps1",
    [string]$ChatOutputPath="output\parsed-chat.txt"
)

$chatOutputDir = Split-Path $ChatOutputPath -Parent
if ($chatOutputDir -and -not (Test-Path $chatOutputDir)) {
    New-Item -ItemType Directory -Path $chatOutputDir | Out-Null
}

Write-Host "Parsing chat logs..." -ForegroundColor Cyan

& $ChatParseScript | Set-Content -Path $ChatOutputPath

if (Test-Path $ChatOutputPath) {
    $itemCount = (Get-Content $ChatOutputPath).Count
    Write-Host "Success! Saved $itemCount items to $ChatOutputPath" -ForegroundColor Green
} else {
    Write-Host "Error! Failed to save items to $ChatOutputPath" -ForegroundColor Red
    return
}