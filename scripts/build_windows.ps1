param(
    [string]$Version = "0.4.0",
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
$BridgeDist = Join-Path $OutDir ".tools\PenguinBridge"
New-Item -ItemType Directory -Path $BridgeDist -Force | Out-Null
Copy-Item (Join-Path $BridgeOut "PenguinBridge.exe") $BridgeDist -Force
Copy-Item (Join-Path $BridgeOut "PenguinBridge.dll") $BridgeDist -Force
Copy-Item (Join-Path $BridgeOut "PenguinBridge.deps.json") $BridgeDist -Force
Copy-Item (Join-Path $BridgeOut "PenguinBridge.runtimeconfig.json") $BridgeDist -Force

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
