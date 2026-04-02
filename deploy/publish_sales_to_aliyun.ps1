param(
    [string]$ServerIp = "47.112.197.85",
    [int]$SshPort = 22,
    [string]$ServerUser = "root",
    [string]$RemoteAppDir = "/opt/sales-app/app",
    [string]$RemoteTempDir = "/tmp",
    [string]$AppService = "sales-app",
    [string]$NginxService = "nginx",
    [string]$HealthUrl = "http://127.0.0.1:5173/healthz"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$archiveName = "sales-release.tar.gz"
$localArchive = Join-Path $env:TEMP $archiveName
$remote = "$ServerUser@$ServerIp"
$releaseId = Get-Date -Format "yyyyMMdd_HHmmss"
$remoteExtractDir = "$RemoteTempDir/sales-release-$releaseId"
$remoteBackupDir = "$RemoteTempDir/sales-backup-$releaseId"

function Invoke-Remote {
    param([string]$Command)
    ssh -o ConnectTimeout=15 -p $SshPort $remote $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Remote command failed: $Command"
    }
}

Write-Host "==> 1/7 Pack local project"
if (Test-Path $localArchive) { Remove-Item $localArchive -Force }
tar -czf $localArchive `
  --exclude ".git" `
  --exclude "__pycache__" `
  --exclude ".venv" `
  --exclude "*.pyc" `
  --exclude "sales.db" `
  --exclude "backups" `
  --exclude "customer_cards" `
  -C $projectRoot .

Write-Host "==> 2/7 Upload archive"
scp -P $SshPort $localArchive "${remote}:${RemoteTempDir}/$archiveName"
if ($LASTEXITCODE -ne 0) { throw "Upload failed." }

Write-Host "==> 3/7 Backup remote app"
$backupCmd = "set -e; mkdir -p '$RemoteAppDir'; rm -rf '$remoteBackupDir'; mkdir -p '$remoteBackupDir'; rsync -a '$RemoteAppDir/' '$remoteBackupDir/'"
Invoke-Remote $backupCmd

Write-Host "==> 4/7 Extract and sync files"
$syncCmd = "set -e; rm -rf '$remoteExtractDir'; mkdir -p '$remoteExtractDir'; tar -xzf '$RemoteTempDir/$archiveName' -C '$remoteExtractDir'; rsync -av --delete --exclude 'sales.db' --exclude 'backups/' --exclude 'customer_cards/' '$remoteExtractDir/' '$RemoteAppDir/'"
Invoke-Remote $syncCmd

Write-Host "==> 5/7 Set permissions and restart"
$restartCmd = "set -e; chown -R salesapp:salesapp '$RemoteAppDir'; systemctl daemon-reload; systemctl restart $AppService; systemctl restart $NginxService"
Invoke-Remote $restartCmd

Write-Host "==> 6/7 Health check"
$checkCmd = "set -e; for i in 1 2 3 4 5; do if curl -fsS '$HealthUrl' >/dev/null; then exit 0; fi; sleep 2; done; exit 1"
try {
    Invoke-Remote $checkCmd
    Write-Host "Health check passed" -ForegroundColor Green
}
catch {
    Write-Host "Health check failed, start rollback..." -ForegroundColor Yellow
    $rollbackCmd = "set -e; rsync -a --delete '$remoteBackupDir/' '$RemoteAppDir/'; systemctl restart $AppService; systemctl restart $NginxService"
    Invoke-Remote $rollbackCmd
    throw "Deploy failed and rollback completed."
}

Write-Host "==> 7/7 Cleanup temp files"
$cleanupCmd = "set +e; rm -rf '$remoteExtractDir'; rm -rf '$remoteBackupDir'; rm -f '$RemoteTempDir/$archiveName'"
Invoke-Remote $cleanupCmd
if (Test-Path $localArchive) { Remove-Item $localArchive -Force }

Write-Host ""
Write-Host "Deploy done: http://$ServerIp/index.html" -ForegroundColor Green
