$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$port = 5173
$toolDir = Join-Path $root "tools"
$cloudflared = Join-Path $toolDir "cloudflared.exe"
$pidFile = Join-Path $root ".tunnel.pid"
$urlFile = Join-Path $root ".tunnel.url"
$outLog = Join-Path $root "tunnel.out.log"
$errLog = Join-Path $root "tunnel.err.log"

function Ensure-Backend {
  try {
    $r = Invoke-RestMethod -Uri "http://127.0.0.1:$port/healthz" -TimeoutSec 3
    if ($r.ok -eq $true) { return }
  } catch {}
  & (Join-Path $root "start.ps1")
  Start-Sleep -Milliseconds 800
}

function Ensure-Cloudflared {
  if (Test-Path $cloudflared) { return }
  New-Item -ItemType Directory -Path $toolDir -Force | Out-Null
  $url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
  Write-Host "Downloading cloudflared..."
  Invoke-WebRequest -Uri $url -OutFile $cloudflared
}

function Try-ReadUrlFromText([string]$text) {
  if (-not $text) { return $null }
  $m = [regex]::Match($text, "https://[-a-z0-9]+\.trycloudflare\.com")
  if ($m.Success) { return $m.Value }
  return $null
}

Ensure-Backend
Ensure-Cloudflared

if (Test-Path $pidFile) {
  $oldPid = Get-Content $pidFile | Select-Object -First 1
  if ($oldPid) {
    $oldProc = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
    if ($oldProc) {
      if (Test-Path $urlFile) {
        $u = (Get-Content $urlFile | Select-Object -First 1)
        if ($u) {
          Write-Host "Public URL already running:"
          Write-Host $u
          exit 0
        }
      }
      Write-Host "Tunnel process already running (PID: $oldPid), but URL file missing."
    }
  }
}

if (Test-Path $outLog) { Remove-Item $outLog -Force -ErrorAction SilentlyContinue }
if (Test-Path $errLog) { Remove-Item $errLog -Force -ErrorAction SilentlyContinue }

$args = @("tunnel", "--url", "http://127.0.0.1:$port", "--no-autoupdate")
$proc = Start-Process -FilePath $cloudflared -ArgumentList $args -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput $outLog -RedirectStandardError $errLog
Set-Content -Path $pidFile -Value $proc.Id -Encoding ascii

$url = $null
for ($i = 0; $i -lt 50; $i++) {
  Start-Sleep -Milliseconds 400
  $txt = ""
  if (Test-Path $outLog) { $txt += (Get-Content $outLog -Raw -ErrorAction SilentlyContinue) }
  if (Test-Path $errLog) { $txt += "`n" + (Get-Content $errLog -Raw -ErrorAction SilentlyContinue) }
  $url = Try-ReadUrlFromText $txt
  if ($url) { break }
}

if (-not $url) {
  Write-Host "Tunnel started, but URL not detected yet."
  Write-Host "Check logs:"
  Write-Host "  $outLog"
  Write-Host "  $errLog"
  exit 1
}

Set-Content -Path $urlFile -Value $url -Encoding ascii
Write-Host "Public URL:"
Write-Host "$url/index.html"
