param(
    [string]$ServerIp = "YOUR_SERVER_IP",
    [string]$ServerUser = "root",
    [string]$RemoteRoot = "/opt/chuni-chart-uploader",
    [string]$SshKeyPath = "$HOME\.ssh\id_ed25519"
)

$ErrorActionPreference = "Stop"

function Ask-Value([string]$Prompt, [string]$Default = "") {
    if ([string]::IsNullOrWhiteSpace($Default)) {
        return (Read-Host $Prompt).Trim()
    }
    $v = (Read-Host "$Prompt [$Default]").Trim()
    if ([string]::IsNullOrWhiteSpace($v)) { return $Default }
    return $v
}

Write-Host "=== Chuni Chart Uploader Windows Deploy ===" -ForegroundColor Cyan

$uploaderDomain = Ask-Value "Uploader domain (e.g. uploader.example.com)"
$uploadApiKey = Ask-Value "Upload API key (long random string)"
$storageRoot = Ask-Value "Storage root" "/data/chuni-charts"
$maxUploadMb = Ask-Value "Max upload MB" "100"
$maxStorageGb = Ask-Value "Max storage GB" "20"
$rateLimitCount = Ask-Value "Rate limit count" "30"
$rateLimitWindowSec = Ask-Value "Rate limit window sec" "60"
$enableTls = Ask-Value "Enable HTTPS certbot now? (y/N)" "y"

if ([string]::IsNullOrWhiteSpace($uploaderDomain) -or [string]::IsNullOrWhiteSpace($uploadApiKey)) {
    throw "Uploader domain and upload API key are required."
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$serviceRoot = Split-Path -Parent $scriptDir
$remote = "$ServerUser@$ServerIp"
$sshCommonArgs = @("-i", $SshKeyPath, "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=accept-new")

Write-Host "1) Create remote directory..." -ForegroundColor Yellow
ssh @sshCommonArgs $remote "mkdir -p $RemoteRoot"

Write-Host "2) Upload service files..." -ForegroundColor Yellow
scp @sshCommonArgs -r "$serviceRoot/*" "${remote}:$RemoteRoot/"

$remoteCmd = @(
    "cd $RemoteRoot"
    "sed -i 's/\r$//' scripts/install-on-ubuntu.sh"
    "chmod +x scripts/install-on-ubuntu.sh"
    "bash scripts/install-on-ubuntu.sh << 'EOF'"
    "$uploaderDomain"
    "$uploadApiKey"
    "$storageRoot"
    "$maxUploadMb"
    "$maxStorageGb"
    "$rateLimitCount"
    "$rateLimitWindowSec"
    "$enableTls"
    "EOF"
) -join "`n"

Write-Host "3) Run remote installer..." -ForegroundColor Yellow
ssh @sshCommonArgs $remote $remoteCmd

Write-Host ""
Write-Host "Deploy completed." -ForegroundColor Green
Write-Host "Health check URL: https://$uploaderDomain/health"
Write-Host "In desktop settings:"
Write-Host "  - Upload API Base: https://$uploaderDomain"
Write-Host "  - Upload API Key : $uploadApiKey"
