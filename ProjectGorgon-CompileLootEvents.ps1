# --- CONFIGURATION ---
$BufferSeconds   = 5
$SessionTimeout  = 3

# 1. Standardize Inputs
$sources = $packetResults | Select-Object @{N='Time';E={ [DateTime]::new($_.Time.Year, $_.Time.Month, $_.Time.Day, $_.Time.Hour, $_.Time.Minute, $_.Time.Second) }}, 
                                          @{N='Data';E={$_.Monster}},
                                          @{N='HasSkin';E={$_.CanSkin}},
                                          @{N='HasButcher';E={$_.CanButcher}},
                                          @{N='EventType';E={'Source'}},
                                          @{N='SortPriority';E={1}} 

$drops   = $chatResults   | Select-Object @{N='Time';E={$_.Time}}, 
                                          @{N='Data';E={$_.ItemName}}, 
                                          @{N='Amount';E={$_.Amount}}, 
                                          @{N='EventType';E={'Loot'}},
                                          @{N='SortPriority';E={2}}

# 2. Merge and Sort
$timeline = $sources + $drops | Sort-Object Time, SortPriority

# 3. State Machine Variables
$correlatedLoot = @()

# Encounter Context
$encounterID = 0
$currentMonsterName = $null
$lastPacketTime = [DateTime]::MinValue

# State Tracking
$currentActivity = "Looting" # Default state
$lastSkinFlag = $false
$lastButcherFlag = $false

foreach ($event in $timeline) {
    
    if ($event.EventType -eq 'Source') {
        
        # --- SESSION IDENTIFICATION ---
        $timeSinceLast = ($event.Time - $lastPacketTime).TotalSeconds
        $isSameEncounter = ($event.Data -eq $currentMonsterName -and $timeSinceLast -le $SessionTimeout)
        
        if (-not $isSameEncounter) {
            # NEW MONSTER: Reset everything
            $encounterID++
            $currentMonsterName = $event.Data
            $currentActivity = "Looting" # Reset to standard looting
            
            # Initialize flags from this FIRST packet
            $lastSkinFlag = $event.HasSkin
            $lastButcherFlag = $event.HasButcher
        } else {
            # SAME MONSTER: Check for State Changes (Transitions)
            
            # Detect Skinning: Option WAS present, NOW matches false
            if ($lastSkinFlag -and -not $event.HasSkin) {
                $currentActivity = "Skinning"
            }

            # Detect Butchering: Option WAS present, NOW matches false
            elseif ($lastButcherFlag -and -not $event.HasButcher) {
                $currentActivity = "Butchering"
            }
            
            # Update flags for the next loop
            $lastSkinFlag = $event.HasSkin
            $lastButcherFlag = $event.HasButcher
        }

        $lastPacketTime = $event.Time
    }
    elseif ($event.EventType -eq 'Loot') {
        
        $timeDiff = ($event.Time - $lastPacketTime).TotalSeconds

        if ($currentMonsterName -and ($timeDiff -ge 0) -and ($timeDiff -le $BufferSeconds)) {
            $origin = "$currentMonsterName"
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
    Group-Object Source | 
    Select-Object Name, Count, @{N='Items';E={$_.Group.Item -join ', '}} | 
    Format-Table -AutoSize

$correlatedLoot | Out-GridView -Title "Final Drop Table"
$correlatedLoot | Export-Csv "D:\Downloads\FinalLootTable.csv" -NoTypeInformation