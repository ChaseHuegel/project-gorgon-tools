$pids = Get-Process WindowsPlayer -ErrorAction Stop | Select-Object -ExpandProperty Id

$tcp = Get-NetTCPConnection |
    Where-Object { $pids -contains $_.OwningProcess } |
    Select-Object -ExpandProperty LocalPort -Unique |
    Sort-Object |
    ForEach-Object { "tcp.port == $_" }

$udp = Get-NetUDPEndpoint |
    Where-Object { $pids -contains $_.OwningProcess } |
    Select-Object -ExpandProperty LocalPort -Unique |
    Sort-Object |
    ForEach-Object { "udp.port == $_" }

($tcp) -join " || "
($udp) -join " || "