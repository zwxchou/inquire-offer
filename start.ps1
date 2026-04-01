$ErrorActionPreference = 'Stop'
$port = 5173
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$serverPidFile = Join-Path $root '.server.pid'
$monitorPidFile = Join-Path $root '.monitor.pid'

function Get-LanIpv4List {
  try {
    $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
      Where-Object {
        $_.IPAddress -ne '127.0.0.1' -and
        $_.IPAddress -notlike '169.254.*' -and
        $_.PrefixOrigin -ne 'WellKnown'
      } |
      Select-Object -ExpandProperty IPAddress -Unique
    if ($ips) { return $ips }
  } catch {}

  # Fallback for environments where Get-NetIPAddress is unavailable.
  $raw = ipconfig | Select-String -Pattern 'IPv4'
  $parsed = @()
  foreach ($line in $raw) {
    if ($line.Line -match '(\d{1,3}\.){3}\d{1,3}') {
      $ip = $Matches[0]
      if ($ip -ne '127.0.0.1' -and $ip -notlike '169.254.*') {
        $parsed += $ip
      }
    }
  }
  return $parsed | Select-Object -Unique
}

function Test-Healthy {
  try {
    $r = Invoke-RestMethod -Uri "http://127.0.0.1:$port/healthz" -TimeoutSec 4
    return ($r.ok -eq $true)
  } catch {
    return $false
  }
}

function Start-Backend {
  $proc = Start-Process -FilePath "python" -ArgumentList "backend.py" -WorkingDirectory $root -PassThru
  Set-Content -Path $serverPidFile -Value $proc.Id -Encoding ascii
  return $proc.Id
}

function Ensure-Backend {
  $running = $false
  if (Test-Path $serverPidFile) {
    $oldPid = Get-Content $serverPidFile | Select-Object -First 1
    if ($oldPid) {
      $p = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
      if ($p) { $running = $true }
    }
  }

  if ($running -and (Test-Healthy)) {
    Write-Host "Backend already healthy at http://localhost:$port"
    return
  }

  if ($running) {
    try { Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue } catch {}
  }
  Write-Host "Starting backend at http://localhost:$port ..."
  $newPid = Start-Backend
  Start-Sleep -Milliseconds 800
  Write-Host "Backend started. PID: $newPid"
}

function Ensure-Monitor {
  $monitorRunning = $false
  if (Test-Path $monitorPidFile) {
    $mpid = Get-Content $monitorPidFile | Select-Object -First 1
    if ($mpid) {
      $mp = Get-Process -Id $mpid -ErrorAction SilentlyContinue
      if ($mp) { $monitorRunning = $true }
    }
  }
  if ($monitorRunning) {
    Write-Host "Monitor already running."
    return
  }
  $mProc = Start-Process -FilePath "powershell" -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$root\monitor.ps1`"" -WorkingDirectory $root -WindowStyle Hidden -PassThru
  Set-Content -Path $monitorPidFile -Value $mProc.Id -Encoding ascii
  Write-Host "Monitor started. PID: $($mProc.Id)"
}

Ensure-Backend
Ensure-Monitor

Write-Host ""
Write-Host "Local URL: http://localhost:$port/index.html"
$lanIps = Get-LanIpv4List
if ($lanIps -and $lanIps.Count -gt 0) {
  Write-Host "LAN URLs (same network):"
  foreach ($ip in $lanIps) {
    Write-Host "  http://${ip}:$port/index.html"
  }
} else {
  Write-Host "LAN URL not detected. Run ipconfig to check local IPv4 address."
}
Start-Process "http://localhost:$port/index.html"
