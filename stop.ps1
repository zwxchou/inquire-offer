$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$serverPidFile = Join-Path $root '.server.pid'
$monitorPidFile = Join-Path $root '.monitor.pid'

function Stop-ByPidFile($filePath, $name) {
  if (!(Test-Path $filePath)) { return }
  $pidValue = Get-Content $filePath | Select-Object -First 1
  if ($pidValue) {
    try { Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue } catch {}
  }
  Remove-Item $filePath -ErrorAction SilentlyContinue
  Write-Host "$name stopped."
}

Stop-ByPidFile $monitorPidFile 'Monitor'
Stop-ByPidFile $serverPidFile 'Backend'
