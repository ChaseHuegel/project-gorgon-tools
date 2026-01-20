param (
    [string]$InputPath="output\captures\",
    [string]$SessionOutputPath="output\parsed-sessions.txt"
)

function Parse-WiresharkTime {
    param ([string]$rawString)
    # Remove timezone suffix
    $cleanTime = $rawString -replace '\s+[A-Z].*$', ''

    return [DateTime]::Parse(
        $cleanTime,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::AssumeLocal
    )
}

$captureFiles = Get-ChildItem -Path $InputPath -File -Filter "*.json"
$sessionWindows = @()
$allEvents = @()

foreach ($captureFilePath in $captureFiles)
{
    $json = Get-Content $captureFilePath.FullName -Raw | ConvertFrom-Json

    if ($json.Count -gt 0) {
        $startTime = Parse-WiresharkTime $json[0]._source.layers.frame.'frame.time'
        $endTime   = Parse-WiresharkTime $json[-1]._source.layers.frame.'frame.time'

        $sessionWindows += [PSCustomObject]@{
            FileName = $captureFilePath.Name
            Start    = $startTime
            End      = $endTime
        }
    }

    foreach ($item in $json) {
        $layers = $item._source.layers
        $hexPayload = $layers.tcp.'tcp.payload'
        if (-not $hexPayload) { $hexPayload = $layers.data.'data.data' }
        if (-not $hexPayload) { continue }

        # Convert Hex to Byte array
        $bytes = ($hexPayload -split ':' | ForEach-Object { [char][Convert]::ToByte($_, 16) })
        if ($bytes.Count -eq 0) { continue }

        $rawString = -join $bytes
        $cleanAscii = -join ($bytes | Where-Object { ($_ -ge 32 -and $_ -le 126) -or $_ -eq 10 -or $_ -eq 13 })

        if ($cleanAscii -match 'Search Corpse of (?<name>[^\r\n]*)') {

            $monsterName = $Matches['name'].Trim()
            $canSkin     = $rawString -match "Skin Corpse"
            $canButcher  = $rawString -match "Butcher Corpse"
            $time        = Parse-WiresharkTime $layers.frame.'frame.time'

            $allEvents += [PSCustomObject]@{
                Time       = $time
                Monster    = $monsterName
                CanSkin    = $canSkin
                CanButcher = $canButcher
            }
        }
    }
}

$sessionWindows | ConvertTo-Json | Set-Content $SessionOutputPath
Write-Host "Saved $($sessionWindows.Count) sessions to $SessionOutputPath" -ForegroundColor Cyan

return $allEvents