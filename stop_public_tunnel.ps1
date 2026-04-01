$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $root ".tunnel.pid"
$urlFile = Join-Path $root ".tunnel.url"

if (Test-Path $pidFile) {
  $pid = Get-Content $pidFile | Select-Object -First 1
  if ($pid) {
    try {
      Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
      Write-Host "Public tunnel stopped. PID: $pid"
    } catch {
      Write-Host "Tunnel process not running."
    }
  }
  Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
} else {
  Write-Host "No tunnel PID file found."
}

Remove-Item $urlFile -Force -ErrorAction SilentlyContinue
