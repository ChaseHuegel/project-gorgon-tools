Add-Type -AssemblyName System.Drawing

$x = 1700
$y = 0
$width = 170
$height = 50
$intervalSeconds = 5

$currentDir = Get-Location
$outputDir = "$currentDir\output"

if (!(Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}

$imgPath = Join-Path $outputDir "zone_capture.png"
$csvPath = Join-Path $outputDir "zones.csv"

if (Test-Path $csvPath) {
    Write-Host "Appending to existing file: $csvPath" -ForegroundColor Cyan
} else {
    Write-Host "Creating new file: $csvPath" -ForegroundColor Cyan
}

Write-Host "`n[ RECORDING IN PROGRESS ]" -ForegroundColor Green -BackgroundColor Black
Write-Host "Press ANY KEY to Stop capturing..." -ForegroundColor Yellow

$lastText = $null
while ($true) {
    $date = [DateTime]::UtcNow

    # Capture the screen
    $bitmap = New-Object System.Drawing.Bitmap $width, $height
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen($x, $y, 0, 0, $bitmap.Size)
        $bitmap.Save($imgPath, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }

    # Use OCR to read the image
    $ocrResult = Convert-PsoImageToText -Path $imgPath

    # Clean and normalize the value
    $currentText = if ($ocrResult.Text) { $ocrResult.Text.Trim() } else { $null }

    if (-not [string]::IsNullOrWhiteSpace($currentText)) {
        if ($currentText -ne $lastText) {
            # Zone changed
            $newRecord = [PSCustomObject]@{
                Time = $date.ToString("yyyy-MM-dd HH:mm:ss")
                Zone = $currentText
            }

            $newRecord | Export-Csv -Path $csvPath -Append -NoTypeInformation -Encoding UTF8

            $lastText = $currentText

            Write-Host "[$($newRecord.Time)] New Zone Detected: '$($newRecord.Zone)'" -ForegroundColor Green
        } else {
            # Zone hasn't changed
            Write-Host "[$($date.ToString("HH:mm:ss"))] Duplicate: '$currentText' - Skipped" -ForegroundColor Gray
        }
    } else {
        # No zone text found
        Write-Host "[$($date.ToString("HH:mm:ss"))] Read: <EMPTY> - Skipped" -ForegroundColor DarkGray
    }

    # Wait to stop else continue to the next capture
    for ($i = 0; $i -lt ($intervalSeconds * 10); $i++) {
        if ([Console]::KeyAvailable) {
            $key = [Console]::ReadKey($true)
            Write-Host "`nStopping capture..." -ForegroundColor Yellow
            return
        }

        Start-Sleep -Milliseconds 100
    }
}