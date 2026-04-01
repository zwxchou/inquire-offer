$ErrorActionPreference = 'Continue'
$port = 5173
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$serverPidFile = Join-Path $root '.server.pid'
$logFile = Join-Path $root 'monitor.log'

function Write-Log($msg) {
  $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  Add-Content -Path $logFile -Value "[$ts] $msg"
}

function Test-Healthy {
  try {
    $r = Invoke-RestMethod -Uri "http://127.0.0.1:$port/healthz" -TimeoutSec 4
    return ($r.ok -eq $true)
  } catch {
    return $false
  }
}

function Restart-Backend {
  try {
    if (Test-Path $serverPidFile) {
      $oldPid = Get-Content $serverPidFile | Select-Object -First 1
      if ($oldPid) { Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue }
    } else {
      Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    }
  } catch {}

  $p = Start-Process -FilePath "python" -ArgumentList "backend.py" -WorkingDirectory $root -PassThru -WindowStyle Hidden
  Set-Content -Path $serverPidFile -Value $p.Id -Encoding ascii
  Write-Log "backend restarted, pid=$($p.Id)"
}

Write-Log "monitor started"
while ($true) {
  if (-not (Test-Healthy)) {
    Write-Log "health check failed, restarting backend"
    Restart-Backend
    Start-Sleep -Seconds 3
  }
  Start-Sleep -Seconds 20
}
