param (
    [string]$ItemInputPath="output\parsed-chat.txt",
    [string]$EventInputPath="output\parsed-packets.txt",
    [string]$SessionInputPath="output\parsed-sessions.txt",
    [string]$ZoneInputPath="output\zones.csv"
)

if (-not (Test-Path $ItemInputPath))  { Write-Error "Items file not found"; return }
if (-not (Test-Path $EventInputPath)) { Write-Error "Events file not found"; return }
if (-not (Test-Path $SessionInputPath)) { Write-Error "Session file not found"; return }
if (-not (Test-Path $ZoneInputPath)) { Write-Error "Zones file not found"; return }

$itemResults = Get-Content $ItemInputPath -Raw | ConvertFrom-Json
$eventResults = Get-Content $EventInputPath -Raw | ConvertFrom-Json
$sessionResults = Get-Content $SessionInputPath -Raw | ConvertFrom-Json
$zoneResults = Import-Csv $ZoneInputPath

$BufferSeconds = 10
$SessionTimeout = 3
# If an item drops less than this many seconds before a State Change packet,
# we consider it part of that action (e.g. Skinning).
$RetroactiveThreshold = 0.9

$ParseDate = {
    param($dateInput)
    if ($dateInput -match '^\/Date\((\-?\d+)\)\/$') {
        $ms = [long]$matches[1]
        return ([DateTime]'1970-01-01 00:00:00').AddMilliseconds($ms).ToLocalTime()
    }
    else {
        return [DateTime]$dateInput
    }
}

$sources = $eventResults | Select-Object @{N='Time';E={ & $ParseDate $_.Time }},
                                        @{N='Data';E={$_.Monster}},
                                        @{N='HasSkin';E={$_.CanSkin}},
                                        @{N='HasButcher';E={$_.CanButcher}},
                                        @{N='HasExtract';E={$_.CanExtract}},
                                        @{N='EventType';E={'Source'}},
                                        @{N='SortPriority';E={2}}

$drops = $itemResults | Select-Object @{N='Time';E={ & $ParseDate $_.Time }},
                                        @{N='Data';E={$_.ItemName}},
                                        @{N='Amount';E={$_.Amount}},
                                        @{N='EventType';E={'Loot'}},
                                        @{N='SortPriority';E={1}}

$validSessions = $sessionResults | Select-Object @{N='Start';E={[DateTime]$_.Start}},
                                                @{N='End';E={[DateTime]$_.End}}

$zoneResults = $zoneResults | Select-Object @{N='Time';E={[DateTime]$_.Time}}, Zone | Sort-Object Time

# Filter out drops that do not fall within a session
$drops = $drops | Where-Object {
    $dropTime = $_.Time
    $isValid = $false

    foreach ($session in $validSessions) {
        if ($dropTime -ge $session.Start -and $dropTime -le $session.End.AddSeconds($BufferSeconds)) {
            $isValid = $true
            break
        }
    }

    return $isValid
}

$timeline = @($sources) + @($drops) | Sort-Object Time, SortPriority

$correlatedLoot = @()
$pendingDrops = @()

$encounterID = New-Guid
$currentMonsterName = $null
$lastPacketTime = [DateTime]::MinValue

$lastSkinFlag = $false
$lastButcherFlag = $false
$lastExtractFlag = $false

foreach ($event in $timeline) {

    if ($event.EventType -eq 'Loot') {
        $pendingDrops += $event
    } elseif ($event.EventType -eq 'Source') {
        $timeSinceLast = ($event.Time - $lastPacketTime).TotalSeconds
        $isSameEncounter = ($event.Data -eq $currentMonsterName -and $timeSinceLast -le $SessionTimeout)
        
        $justSkinned = ($isSameEncounter -and $lastSkinFlag -and -not $event.HasSkin)
        $justButchered = ($isSameEncounter -and $lastButcherFlag -and -not $event.HasButcher)
        $justExtracted = ($isSameEncounter -and $lastExtractFlag -and -not $event.HasExtract)

        foreach ($drop in $pendingDrops) {

            $lag = ($event.Time - $drop.Time).TotalSeconds

            $thisActivity = "Looting" # Default
            if ($justSkinned -and $lag -le $RetroactiveThreshold) {
                $thisActivity = "Skinning"
            } elseif ($justButchered -and $lag -le $RetroactiveThreshold) {
                $thisActivity = "Butchering"
            } elseif ($justExtracted -and $lag -le $RetroactiveThreshold) {
                $thisActivity = "Extracting"
            }
            
            if ($currentMonsterName -and $lag -le $BufferSeconds) {
                $origin = $currentMonsterName
                $status = "Linked"
                $id = $encounterID
            } else {
                $origin = "Ground/Unknown"
                $status = "Orphaned"
                $id = New-Guid
            }

            $correlatedLoot += [PSCustomObject]@{
                Time     = $drop.Time
                Source   = $origin
                ID       = $id
                Activity = $thisActivity
                Item     = $drop.Data
                Amount   = $drop.Amount
                Status   = $status
                LagTime  = $lag
            }
        }

        $pendingDrops = @()

        if (-not $isSameEncounter) {
            $encounterID = New-Guid
            $currentMonsterName = $event.Data
        }

        $lastSkinFlag = $event.HasSkin
        $lastButcherFlag = $event.HasButcher
        $lastExtractFlag = $event.HasExtract
        $lastPacketTime = $event.Time
    }
}

foreach ($drop in $pendingDrops) {
    $correlatedLoot += [PSCustomObject]@{
        Time        = $drop.Time;
        Source      = $currentMonsterName;
        ID          = $encounterID;
        Activity    = "Looting";
        Item        = $drop.Data;
        Amount      = $drop.Amount;
        Status      = "Linked";
        LagTime     = 0
    }
}

$correlatedLoot = $correlatedLoot | Sort-Object Time

$zoneIndex = 0
$currentZoneName = "Unknown"
foreach ($lootEvent in $correlatedLoot) {
    while ($zoneIndex -lt $zoneResults.Count -and $zoneResults[$zoneIndex].Time -le $lootEvent.Time) {
        $currentZoneName = $zoneResults[$zoneIndex].Zone
        $zoneIndex++
    }

    # Add the Zone to the object
    $lootEvent | Add-Member -NotePropertyName "Zone" -NotePropertyValue $currentZoneName
}

$summary = $correlatedLoot | Where-Object { $_.Status -eq 'Linked' } |
    Group-Object ID, Activity |
    Sort-Object {$_.Group[0].Zone}, {$_.Group[0].Time} |
    Select-Object @{N='Zone';E={$_.Group[0].Zone}},
                  @{N='Monster';E={$_.Group[0].Source}},
                  @{N='Action';E={$_.Values[1]}},
                  @{N='Items';E={ ($_.Group | ForEach-Object { "$($_.Amount)x $($_.Item)" }) -join ', ' }} |
    Format-Table -AutoSize | Out-String

return $correlatedLoot