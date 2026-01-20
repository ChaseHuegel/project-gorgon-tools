param (
    [string]$ItemInputPath="output\parsed-chat.txt",
    [string]$EventInputPath="output\parsed-packets.txt"
)

if ((Test-Path $ItemInputPath) -eq $False) {
    Write-Error "Items file not found: $ItemInputPath";
    return
}

if ((Test-Path $EventInputPath) -eq $False) {
    Write-Error "Events file not found: $EventInputPath";
    return
}

$itemResults  = Get-Content $ItemInputPath -Raw | ConvertFrom-Json
$eventResults = Get-Content $EventInputPath -Raw | ConvertFrom-Json

$BufferSeconds   = 5
$SessionTimeout  = 3

$sources = $eventResults | Select-Object @{N='Time';E={ [DateTime]$_.Time }},
                                         @{N='Data';E={$_.Monster}},
                                         @{N='HasSkin';E={$_.CanSkin}},
                                         @{N='HasButcher';E={$_.CanButcher}},
                                         @{N='EventType';E={'Source'}},
                                         @{N='SortPriority';E={1}}

$drops   = $itemResults   | Select-Object @{N='Time';E={ [DateTime]$_.Time }},
                                         @{N='Data';E={$_.ItemName}},
                                         @{N='Amount';E={$_.Amount}},
                                         @{N='EventType';E={'Loot'}},
                                         @{N='SortPriority';E={2}}

# 2. Merge and Sort
$timeline = @($sources) + @($drops) | Sort-Object Time, SortPriority

# 3. State Machine Variables
$correlatedLoot = @()

# Encounter Context
$encounterID = 0
$currentMonsterName = $null
$lastPacketTime = [DateTime]::MinValue

# State Tracking
$currentActivity = "Looting"
$lastSkinFlag = $false
$lastButcherFlag = $false

foreach ($event in $timeline) {
    if ($event.EventType -eq 'Source') {
        
        $timeSinceLast = ($event.Time - $lastPacketTime).TotalSeconds
        $isSameEncounter = ($event.Data -eq $currentMonsterName -and $timeSinceLast -le $SessionTimeout)
        
        if (-not $isSameEncounter) {
            # NEW MONSTER
            $encounterID++
            $currentMonsterName = $event.Data
            $currentActivity = "Looting" # Reset to standard looting
            
            $lastSkinFlag = $event.HasSkin
            $lastButcherFlag = $event.HasButcher
        } else {
            # SAME MONSTER
            
            if ($lastSkinFlag -and -not $event.HasSkin) {
                $currentActivity = "Skinning"
            }

            elseif ($lastButcherFlag -and -not $event.HasButcher) {
                $currentActivity = "Butchering"
            }
            
            $lastSkinFlag = $event.HasSkin
            $lastButcherFlag = $event.HasButcher
        }

        $lastPacketTime = $event.Time
    } elseif ($event.EventType -eq 'Loot') {
        $timeDiff = ($event.Time - $lastPacketTime).TotalSeconds

        if ($currentMonsterName -and ($timeDiff -ge 0) -and ($timeDiff -le $BufferSeconds)) {
            $origin = $currentMonsterName
            $status = "Linked"
        }
        else {
            $origin = "Ground/Unknown"
            $status = "Orphaned"
        }

        $correlatedLoot += [PSCustomObject]@{
            Time     = $event.Time
            Source   = $origin
            ID       = $encounterID
            Activity = $currentActivity
            Item     = $event.Data
            Amount   = $event.Amount
            Status   = $status
        }
    }
}

$correlatedLoot | Where-Object { $_.Status -eq 'Linked' } |
    Group-Object ID, Activity |
    Sort-Object {$_.Group[0].Time} |
    Select-Object @{N='Monster';E={$_.Group[0].Source}},
                  @{N='Action';E={$_.Values[1]}},
                  @{N='Items';E={ ($_.Group | ForEach-Object { "$($_.Amount)x $($_.Item)" }) -join ', ' }} |
    Format-Table -AutoSize

return $correlatedLoot