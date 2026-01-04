param(
  [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'

# Stop anything currently listening on the port
try {
  $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
  foreach ($c in $conns) {
    if ($c.OwningProcess -and $c.OwningProcess -ne 0) {
      try {
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction Stop
      } catch {
        # ignore
      }
    }
  }
} catch {
  # No listener or Get-NetTCPConnection unavailable
}

# Start server from the web folder
Set-Location $PSScriptRoot
& "C:/Users/jdpoo/Documents/GitHub/BearsPawMainReport/.venv/Scripts/python.exe" -m http.server $Port
