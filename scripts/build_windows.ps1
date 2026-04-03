param(
    [string]$Version = "0.4.3",
    [switch]$SkipPyInstaller,
    [switch]$SkipBridge
)

# Run from repo root is NOT required; script cd's to parent of scripts/
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Assert-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $Name"
    }
}

Assert-Command "python"
if (-not $SkipBridge) { Assert-Command "dotnet" }

$VenvPy = Join-Path $Root ".venv-build\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Write-Host "Creating .venv-build ..."
    python -m venv (Join-Path $Root ".venv-build")
}

Write-Host "[1/4] Install build dependencies ..."
& $VenvPy -m pip install -r (Join-Path $Root "requirements-build.txt")

if (-not $SkipPyInstaller) {
    Write-Host "[2/4] Build main app with PyInstaller ..."
    & $VenvPy -m PyInstaller --noconfirm (Join-Path $Root "ChuniEventer.spec")
} else {
    Write-Host "[2/4] Skip PyInstaller"
}

$BridgeOut = Join-Path $Root "tools\PenguinBridge\bin\Release\net8.0"
if (-not $SkipBridge) {
    Write-Host "[3/4] Build PenguinBridge ..."
    & dotnet build (Join-Path $Root "tools\PenguinBridge\PenguinBridge.csproj") -c Release
    if ($LASTEXITCODE -ne 0) {
        throw "dotnet build PenguinBridge failed (exit $LASTEXITCODE). Run scripts\setup_penguin_tools.ps1 or pass -SkipBridge."
    }
} else {
    Write-Host "[3/4] Skip bridge build"
}

Write-Host "[4/4] Assemble distributable ..."
$AppExe = Join-Path $Root "dist\ChuniEventer.exe"
if (-not (Test-Path $AppExe)) {
    throw "Main executable not found: $AppExe"
}

$OutDir = Join-Path $Root ("dist\release\Chuni-Eventer-v{0}" -f $Version)
if (Test-Path $OutDir) { Remove-Item $OutDir -Recurse -Force }
New-Item -ItemType Directory -Path $OutDir | Out-Null

Copy-Item $AppExe (Join-Path $OutDir "ChuniEventer.exe") -Force

$BridgeExe = Join-Path $BridgeOut "PenguinBridge.exe"
if (-not (Test-Path $BridgeExe)) {
    throw "PenguinBridge.exe not found: $BridgeExe"
}
function Copy-PenguinBridgePublish([string]$dest) {
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
    # 复制 net8.0 输出目录内除 pdb 外的全部文件（含 PenguinTools.Core 及其依赖 dll）
    Get-ChildItem $BridgeOut -File | Where-Object { $_.Extension -ne ".pdb" } | ForEach-Object {
        Copy-Item $_.FullName $dest -Force
    }
}

$BridgeDist = Join-Path $OutDir ".tools\PenguinBridge"
Copy-PenguinBridgePublish $BridgeDist

# Also place bridge under dist/.tools for users who directly run dist\ChuniEventer.exe.
$DistBridge = Join-Path $Root "dist\.tools\PenguinBridge"
Copy-PenguinBridgePublish $DistBridge

$ReleaseNote = Join-Path $Root ("packaging\GITHUB_RELEASE_v{0}.md" -f $Version)
if (Test-Path $ReleaseNote) {
    Copy-Item $ReleaseNote (Join-Path $OutDir ("GITHUB_RELEASE_v{0}.md" -f $Version)) -Force
}

$ZipPath = Join-Path $Root ("dist\Chuni-Eventer-v{0}.zip" -f $Version)
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path (Join-Path $OutDir "*") -DestinationPath $ZipPath -CompressionLevel Optimal

Write-Host "Done."
Write-Host "EXE: $AppExe"
Write-Host "Bridge: $BridgeExe"
Write-Host "Folder: $OutDir"
Write-Host "Zip: $ZipPath"
