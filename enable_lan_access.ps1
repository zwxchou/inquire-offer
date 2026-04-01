$ErrorActionPreference = 'Stop'
$port = 5173
$ruleName = "SalesSystem-5173-LAN"

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

try {
  $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
  if (-not $existing) {
    New-NetFirewallRule `
      -DisplayName $ruleName `
      -Direction Inbound `
      -Action Allow `
      -Enabled True `
      -Profile Private `
      -Protocol TCP `
      -LocalPort $port | Out-Null
    Write-Host "Firewall rule created: $ruleName (TCP $port, Private profile)."
  } else {
    Write-Host "Firewall rule already exists: $ruleName"
  }
} catch {
  Write-Host "Failed to configure firewall automatically."
  Write-Host "Please run this script as Administrator."
  throw
}

Write-Host ""
Write-Host "Share these URLs with users on the same LAN:"
$ips = Get-LanIpv4List
if ($ips -and $ips.Count -gt 0) {
  foreach ($ip in $ips) {
    Write-Host "  http://${ip}:$port/index.html"
  }
} else {
  Write-Host "  Unable to detect LAN IP. Run ipconfig and use your IPv4 address."
}
