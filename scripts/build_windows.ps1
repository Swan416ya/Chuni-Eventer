param(
    [string]$Version = "0.6.3",
    [switch]$SkipPyInstaller,
    [Alias("SkipBridge")][switch]$SkipPenguinToolsCli,
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
if (-not $SkipPenguinToolsCli) { Assert-Command "dotnet" }

function Resolve-PenguinToolsRoot {
    $candidates = @()
    if ($env:CHUNI_PENGUINTOOLS_ROOT) {
        $candidates += $env:CHUNI_PENGUINTOOLS_ROOT
    }
    $candidates += (Join-Path $Root "PenguinTools")
    $candidates += (Join-Path (Split-Path -Parent $Root) "PenguinTools")
    foreach ($cand in $candidates) {
        if (-not $cand) { continue }
        $full = [System.IO.Path]::GetFullPath($cand)
        $cliProj = Join-Path $full "PenguinTools.CLI\PenguinTools.CLI.csproj"
        if (Test-Path $cliProj) {
            return $full
        }
    }
    return $null
}

function Ensure-PenguinToolsMua([string]$penguinToolsRoot, [string]$projectRoot) {
    if (-not $penguinToolsRoot) { return }
    $expected = Join-Path $penguinToolsRoot "External\muautils\cmake-build-vcpkg\Release\mua.exe"
    if (Test-Path $expected) { return }

    $fallbackExe = Join-Path $projectRoot "tools\PenguinTools\mua.exe"
    $fallbackLicense = Join-Path $projectRoot "tools\PenguinTools\mua.LICENSE.txt"
    if (-not (Test-Path $fallbackExe)) {
        return
    }

    Write-Host "  mua.exe missing in PenguinTools submodule output; applying fallback copy from tools\PenguinTools ..."
    New-Item -ItemType Directory -Path (Split-Path -Parent $expected) -Force | Out-Null
    Copy-Item $fallbackExe $expected -Force

    $muautilsLicense = Join-Path $penguinToolsRoot "External\muautils\LICENSE"
    if (Test-Path $fallbackLicense) {
        Copy-Item $fallbackLicense $muautilsLicense -Force
    }
}

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

$PenguinToolsRoot = Resolve-PenguinToolsRoot
$PenguinToolsCliOut = $null
if (-not $SkipPenguinToolsCli) {
    if (-not $PenguinToolsRoot) {
        throw "PenguinTools source not found. Run scripts\setup_penguin_tools.ps1, or set CHUNI_PENGUINTOOLS_ROOT to a Foahh/PenguinTools checkout."
    }
    Ensure-PenguinToolsMua -penguinToolsRoot $PenguinToolsRoot -projectRoot $Root
    $PenguinToolsCliProject = Join-Path $PenguinToolsRoot "PenguinTools.CLI\PenguinTools.CLI.csproj"
    $PenguinToolsCliOut = Join-Path $PenguinToolsRoot "PenguinTools.CLI\bin\Release\net10.0\publish\WinX64-SelfContained-SingleFile-ExternalAssets"
    Write-Host "[3/5] Publish PenguinTools.CLI ..."
    & dotnet publish $PenguinToolsCliProject -c Release -p:PublishProfile=WinX64-SelfContained-SingleFile-ExternalAssets
    if ($LASTEXITCODE -ne 0) {
        throw "dotnet publish PenguinTools.CLI failed (exit $LASTEXITCODE). Run scripts\setup_penguin_tools.ps1, or pass -SkipPenguinToolsCli."
    }
} else {
    $PenguinToolsCliOut = Join-Path $Root "tools\PenguinToolsCLI"
    Write-Host "[3/5] Skip PenguinTools.CLI publish"
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

$PenguinToolsCliExe = Join-Path $PenguinToolsCliOut "PenguinTools.CLI.exe"
function Copy-PenguinToolsCliPublish([string]$dest) {
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
    Copy-Item -Path (Join-Path $PenguinToolsCliOut "*") -Destination $dest -Recurse -Force
    Get-ChildItem $dest -Recurse -File | Where-Object { $_.Extension -eq ".pdb" } | ForEach-Object {
        Remove-Item $_.FullName -Force
    }
}

if (Test-Path $PenguinToolsCliExe) {
    $CliDist = Join-Path $OutDir ".tools\PenguinToolsCLI"
    Copy-PenguinToolsCliPublish $CliDist
    # Also place PenguinTools.CLI under dist/.tools for users who directly run dist\ChuniEventer.exe.
    $DistTools = Join-Path $Root "dist\.tools"
    $DistCli = Join-Path $DistTools "PenguinToolsCLI"
    Copy-PenguinToolsCliPublish $DistCli
} elseif ($SkipPenguinToolsCli) {
    Write-Host "  Skip PenguinTools.CLI bundle (no $PenguinToolsCliExe ; pgko / pjsk 转谱不可用)"
} else {
    throw "PenguinTools.CLI.exe not found: $PenguinToolsCliExe"
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
Write-Host "PenguinTools.CLI: $PenguinToolsCliExe"
if (-not $SkipCompressonator) {
    Write-Host "CompressonatorCLI: $(Join-Path $OutDir '.tools\CompressonatorCLI\compressonatorcli.exe')"
}
Write-Host "Folder: $OutDir"
Write-Host "Zip: $ZipPath"
