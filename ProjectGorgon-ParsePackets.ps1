param (
    [string]$InputPath="output\captures\"
)

$captureFiles = Get-ChildItem -Path $InputPath -File -Filter "*.json"

foreach ($captureFilePath in $captureFiles)
{

    $json = Get-Content $captureFilePath.FullName -Raw | ConvertFrom-Json

    foreach ($item in $json) {
        $layers = $item._source.layers
        $hexPayload = $layers.tcp.'tcp.payload'
        if (-not $hexPayload) { $hexPayload = $layers.data.'data.data' }
        if (-not $hexPayload) { continue }

        # Convert Hex to ASCII string
        # We keep the raw string for searching option flags
        $rawString = -join ($hexPayload -split ':' |
            Where-Object { $_ -match '^[0-9A-Fa-f]{2}$' } |
            ForEach-Object { [char][Convert]::ToByte($_, 16) }
        )
        
        # Filter printable ASCII for the Name Regex
        $cleanAscii = -join ($rawString.ToCharArray() | Where-Object { ($_ -ge 32 -and $_ -le 126) -or $_ -eq 10 -or $_ -eq 13 })

        if ($cleanAscii -match 'Search Corpse of (?<name>[^\r\n]*)') {

            $monsterName = $Matches['name'].Trim()

            $canSkin    = $rawString -match "Skin Corpse"
            $canButcher = $rawString -match "Butcher Corpse"

            $rawTime = $layers.frame.'frame.time'
            $cleanTime = $rawTime -replace '\s+[A-Z].*$', ''

            $time = [DateTime]::Parse(
                $cleanTime,
                [System.Globalization.CultureInfo]::InvariantCulture,
                [System.Globalization.DateTimeStyles]::AssumeLocal
            )

            [PSCustomObject]@{
                Time       = $time
                Monster    = $monsterName
                CanSkin    = $canSkin
                CanButcher = $canButcher
            }
        }
    }
}
