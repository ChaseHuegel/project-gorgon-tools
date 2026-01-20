param (
    [string]$OutputPath="output\parsed-chat.txt"
)

$logDirectory = Join-Path $env:USERPROFILE "AppData\LocalLow\Elder Game\Project Gorgon\ChatLogs"
$logFiles = Get-ChildItem -Path $logDirectory -File

$chatResults = foreach ($logPath in $logFiles)
{
    $logData = Get-Content $logPath.FullName

    foreach ($line in $logData) {
        # Regex Pattern:
        # 1. Capture Timestamp (yy-MM-dd HH:mm:ss)
        # 2. Look for [Status]
        # 3. Capture Item Name (Non-greedy match until optional count or end)
        # 4. Optional Capture Count (x followed by digits)
        # 5. End with "added to inventory."
        if ($line -match '^(?<timestamp>[\d-]+\s+[\d:]+)\s+\[Status\]\s+(?<item>.+?)(?:\s+x(?<count>\d+))?\s+added to inventory\.$') {

            $count = if ($Matches['count']) { [int]$Matches['count'] } else { 1 }

            $date = [DateTime]::ParseExact(
                $Matches['timestamp'].Trim(),
                "yy-MM-dd HH:mm:ss",
                [System.Globalization.CultureInfo]::InvariantCulture
            )

            [PSCustomObject]@{
                Time     = $date
                ItemName = $Matches['item'].Trim()
                Amount   = $count
            }
        }
    }
}

Set-Content -Path $OutputPath -Value $chatResults
