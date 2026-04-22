param(
    [string]$Version = "0.6.3",
    [switch]$SkipPyInstaller,
    [switch]$SkipBridge,
    [switch]$SkipCompressonator
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

Write-Host "[1/5] Install build dependencies ..."
& $VenvPy -m pip install -r (Join-Path $Root "requirements-build.txt")

if (-not $SkipPyInstaller) {
    Write-Host "[2/5] Build main app with PyInstaller ..."
    & $VenvPy -m PyInstaller --noconfirm (Join-Path $Root "ChuniEventer.spec")
} else {
    Write-Host "[2/5] Skip PyInstaller"
}

$BridgeOut = Join-Path $Root "tools\PenguinBridge\bin\Release\net8.0\win-x64\publish"
if (-not $SkipBridge) {
    Write-Host "[3/5] Publish PenguinBridge (self-contained) ..."
    & dotnet publish (Join-Path $Root "tools\PenguinBridge\PenguinBridge.csproj") -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:PublishTrimmed=false
    if ($LASTEXITCODE -ne 0) {
        throw "dotnet publish PenguinBridge failed (exit $LASTEXITCODE). Run scripts\setup_penguin_tools.ps1 (and ensure PenguinTools.Core can build), or pass -SkipBridge."
    }
} else {
    Write-Host "[3/5] Skip bridge build"
}

# AMD GPUOpen Compressonator CLI (pinned zip). App resolves .tools/CompressonatorCLI/compressonatorcli.exe when frozen.
$CompressUrl = "https://github.com/GPUOpen-Tools/compressonator/releases/download/V4.5.52/compressonatorcli-4.5.52-win64.zip"
$CompressZip = Join-Path $Root ".cache\compr-cli-4.5.52-win64.zip"
$CompressStage = Join-Path $Root ".cache\compr-cli-4.5.52-win64"
$CompressSrc = Join-Path $CompressStage "compressonatorcli-4.5.52-win64"

function Ensure-CompressonatorCli {
    New-Item -ItemType Directory -Path (Join-Path $Root ".cache") -Force | Out-Null
    if (-not (Test-Path $CompressZip)) {
        Write-Host "  Downloading compressonatorcli-4.5.52-win64.zip ..."
        Invoke-WebRequest -Uri $CompressUrl -OutFile $CompressZip -UseBasicParsing
    }
    $exe = Join-Path $CompressSrc "compressonatorcli.exe"
    if (-not (Test-Path $exe)) {
        if (Test-Path $CompressStage) { Remove-Item $CompressStage -Recurse -Force }
        Write-Host "  Extracting Compressonator CLI ..."
        Expand-Archive -LiteralPath $CompressZip -DestinationPath $CompressStage -Force
    }
    if (-not (Test-Path (Join-Path $CompressSrc "compressonatorcli.exe"))) {
        throw "compressonatorcli.exe not found after extract (expected under $CompressSrc)"
    }
}

function Copy-CompressonatorBundle([string]$toolsParent) {
    $dest = Join-Path $toolsParent "CompressonatorCLI"
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
    Copy-Item -Path (Join-Path $CompressSrc "*") -Destination $dest -Recurse -Force
}

if (-not $SkipCompressonator) {
    Write-Host "[4/5] Ensure Compressonator CLI bundle ..."
    Ensure-CompressonatorCli
} else {
    Write-Host "[4/5] Skip Compressonator bundle"
}

Write-Host "[5/5] Assemble distributable ..."
$AppExe = Join-Path $Root "dist\ChuniEventer.exe"
if (-not (Test-Path $AppExe)) {
    throw "Main executable not found: $AppExe"
}

$OutDir = Join-Path $Root ("dist\release\Chuni-Eventer-v{0}" -f $Version)
if (Test-Path $OutDir) { Remove-Item $OutDir -Recurse -Force }
New-Item -ItemType Directory -Path $OutDir | Out-Null

Copy-Item $AppExe (Join-Path $OutDir "ChuniEventer.exe") -Force

$BridgeExe = Join-Path $BridgeOut "PenguinBridge.exe"
function Copy-PenguinBridgePublish([string]$dest) {
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
    # 复制 self-contained 发布目录内除 pdb 外的全部文件（含 core 依赖）
    Get-ChildItem $BridgeOut -File | Where-Object { $_.Extension -ne ".pdb" } | ForEach-Object {
        Copy-Item $_.FullName $dest -Force
    }
}

if (Test-Path $BridgeExe) {
    $BridgeDist = Join-Path $OutDir ".tools\PenguinBridge"
    Copy-PenguinBridgePublish $BridgeDist
    # Also place bridge under dist/.tools for users who directly run dist\ChuniEventer.exe.
    $DistTools = Join-Path $Root "dist\.tools"
    $DistBridge = Join-Path $DistTools "PenguinBridge"
    Copy-PenguinBridgePublish $DistBridge
} elseif ($SkipBridge) {
    Write-Host "  Skip PenguinBridge bundle (no $BridgeExe ; pgko C# 转码不可用)"
} else {
    throw "PenguinBridge.exe not found: $BridgeExe"
}

if (-not $SkipCompressonator) {
    $OutTools = Join-Path $OutDir ".tools"
    $DistToolsRoot = Join-Path $Root "dist\.tools"
    Copy-CompressonatorBundle $OutTools
    Copy-CompressonatorBundle $DistToolsRoot
}

# Bundle PenguinTools resources (stage templates / optional mua.exe) if present.
function Copy-PenguinToolsBundle([string]$toolsParent) {
    $src = Join-Path $Root "tools\PenguinTools"
    if (-not (Test-Path $src)) { return }
    $dest = Join-Path $toolsParent "PenguinTools"
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
    Copy-Item -Path (Join-Path $src "*") -Destination $dest -Recurse -Force
}

$OutTools2 = Join-Path $OutDir ".tools"
$DistToolsRoot2 = Join-Path $Root "dist\.tools"
Copy-PenguinToolsBundle $OutTools2
Copy-PenguinToolsBundle $DistToolsRoot2

$ThirdParty = Join-Path $Root "packaging\THIRD_PARTY_COMPRESSONATOR.txt"
if (Test-Path $ThirdParty) {
    Copy-Item $ThirdParty (Join-Path $OutDir "THIRD_PARTY_COMPRESSONATOR.txt") -Force
}

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
if (-not $SkipCompressonator) {
    Write-Host "CompressonatorCLI: $(Join-Path $OutDir '.tools\CompressonatorCLI\compressonatorcli.exe')"
}
Write-Host "Folder: $OutDir"
Write-Host "Zip: $ZipPath"
