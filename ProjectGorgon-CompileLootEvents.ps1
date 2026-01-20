param (
    [string]$ItemInputPath="output\parsed-chat.txt",
    [string]$EventInputPath="output\parsed-packets.txt"
)

# 1. Load Data
if (-not (Test-Path $ItemInputPath))  { Write-Error "Items file not found"; return }
if (-not (Test-Path $EventInputPath)) { Write-Error "Events file not found"; return }

$itemResults  = Get-Content $ItemInputPath  -Raw | ConvertFrom-Json
$eventResults = Get-Content $EventInputPath -Raw | ConvertFrom-Json

$BufferSeconds   = 5
$SessionTimeout  = 3

# === TUNING VARIABLE ===
# If an item drops less than this many seconds before a State Change packet,
# we consider it part of that action (e.g. Skinning).
# Based on your data: Skins drop ~0.1s before packet, Pork drops ~1.0s before.
$RetroactiveThreshold = 0.9

# 2. Date Parser
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

# 3. Build Timeline
# SortPriority: Loot (1) comes before Source (2) if timestamps are identical.
# This ensures we buffer the item, then immediately process it with the packet.
$sources = $eventResults | Select-Object @{N='Time';E={ & $ParseDate $_.Time }},
                                         @{N='Data';E={$_.Monster}},
                                         @{N='HasSkin';E={$_.CanSkin}},
                                         @{N='HasButcher';E={$_.CanButcher}},
                                         @{N='EventType';E={'Source'}},
                                         @{N='SortPriority';E={2}}

$drops   = $itemResults   | Select-Object @{N='Time';E={ & $ParseDate $_.Time }},
                                         @{N='Data';E={$_.ItemName}},
                                         @{N='Amount';E={$_.Amount}},
                                         @{N='EventType';E={'Loot'}},
                                         @{N='SortPriority';E={1}}

$timeline = @($sources) + @($drops) | Sort-Object Time, SortPriority

# 4. State Machine
$correlatedLoot = @()
$pendingDrops = @()

$encounterID = 0
$currentMonsterName = $null
$lastPacketTime = [DateTime]::MinValue

# State Flags
$lastSkinFlag = $false
$lastButcherFlag = $false

foreach ($event in $timeline) {

    if ($event.EventType -eq 'Loot') {
        # Add to buffer. We don't assign Activity yet.
        $pendingDrops += $event
    }
    elseif ($event.EventType -eq 'Source') {
        
        $timeSinceLast = ($event.Time - $lastPacketTime).TotalSeconds
        $isSameEncounter = ($event.Data -eq $currentMonsterName -and $timeSinceLast -le $SessionTimeout)
        
        # Determine if a Transition happened just now
        $justSkinned = ($isSameEncounter -and $lastSkinFlag -and -not $event.HasSkin)
        $justButchered = ($isSameEncounter -and $lastButcherFlag -and -not $event.HasButcher)

        # === PROCESS BUFFER ===
        foreach ($drop in $pendingDrops) {

            # Calculate how close this drop was to the current packet
            $lag = ($event.Time - $drop.Time).TotalSeconds

            # Determine Activity
            $thisActivity = "Looting" # Default

            if ($justSkinned -and $lag -le $RetroactiveThreshold) {
                # If we just skinned, and the item dropped < 0.9s ago, it's a skin.
                $thisActivity = "Skinning"
            }
            elseif ($justButchered -and $lag -le $RetroactiveThreshold) {
                # If we just butchered, and the item dropped < 0.9s ago, it's meat.
                $thisActivity = "Butchering"
            }
            
            # Determine Linking
            if ($currentMonsterName) {
                $origin = $currentMonsterName
                $status = "Linked"
                $id = $encounterID
            } else {
                # Fallback for startup items
                $origin = "Ground/Unknown"
                $status = "Orphaned"
                $id = 0
            }

            # Handle "New Monster" boundary in buffer
            # If the buffer has old items but we just switched monsters, this logic might need tweaking,
            # but usually the buffer is empty by the time a NEW monster packet arrives due to time gaps.

            $correlatedLoot += [PSCustomObject]@{
                Time     = $drop.Time
                Source   = $origin
                ID       = $id
                Activity = $thisActivity
                Item     = $drop.Data
                Amount   = $drop.Amount
                Status   = $status
                LagTime  = $lag # Useful for debugging thresholds
            }
        }

        # Clear Buffer
        $pendingDrops = @()

        # === UPDATE STATE ===
        if (-not $isSameEncounter) {
            $encounterID++
            $currentMonsterName = $event.Data
        }

        # Update flags for the *next* loop iteration
        $lastSkinFlag = $event.HasSkin
        $lastButcherFlag = $event.HasButcher
        $lastPacketTime = $event.Time
    }
}

# Flush leftovers
foreach ($drop in $pendingDrops) {
    $correlatedLoot += [PSCustomObject]@{
        Time = $drop.Time; Source = $currentMonsterName; ID = $encounterID;
        Activity = "Looting"; Item = $drop.Data; Amount = $drop.Amount;
        Status = "Orphaned"; LagTime = 0
    }
}

# Output
$summary = $correlatedLoot | Where-Object { $_.Status -eq 'Linked' } |
    Group-Object ID, Activity |
    Sort-Object {$_.Group[0].Time} |
    Select-Object @{N='Monster';E={$_.Group[0].Source}},
                  @{N='Action';E={$_.Values[1]}},
                  @{N='Items';E={ ($_.Group | ForEach-Object { "$($_.Amount)x $($_.Item)" }) -join ', ' }} |
    Format-Table -AutoSize | Out-String

Write-Host $summary
return $correlatedLoot