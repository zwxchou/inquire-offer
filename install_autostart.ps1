$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskName = 'SalesSystemAutoStart'
$taskCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$root\start.ps1`""
$startupDir = [Environment]::GetFolderPath('Startup')
$startupCmd = Join-Path $startupDir 'SalesSystemAutoStart.cmd'

# Try delete old task (ignore result)
cmd /c "schtasks /Delete /TN $taskName /F" *> $null

# Try schedule task first
cmd /c "schtasks /Create /SC ONLOGON /TN $taskName /TR \"$taskCmd\" /F" *> $null
if ($LASTEXITCODE -eq 0) {
  cmd /c "schtasks /Query /TN $taskName" *> $null
  if ($LASTEXITCODE -eq 0) {
    Write-Host "Auto-start task installed: $taskName"
    Write-Host "Command: $taskCmd"
    Write-Host "It will run at user logon."
    exit 0
  }
}

# Fallback: startup folder command file
New-Item -ItemType Directory -Path $startupDir -Force | Out-Null
"@echo off`r`n$taskCmd" | Set-Content -Path $startupCmd -Encoding ASCII
if (Test-Path $startupCmd) {
  Write-Host "Task scheduler unavailable. Installed startup command instead:"
  Write-Host $startupCmd
  Write-Host "It will run at user logon."
  exit 0
}

Write-Error "Failed to install any auto-start method."
exit 1
