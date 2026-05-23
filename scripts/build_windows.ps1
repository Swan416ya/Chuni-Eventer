param(
    [string]$Version = "0.7.6",
    [switch]$SkipPyInstaller,
    [Alias("SkipBridge")][switch]$SkipPenguinToolsCli,
    # 懒人包默认不再打入 Compressonator（exe 内已有 quicktex）；需完整离线 DDS 回退时显式 -IncludeCompressonator
    [switch]$IncludeCompressonator,
    [switch]$SkipCompressonator
)

$BundleCompressonator = $IncludeCompressonator -and (-not $SkipCompressonator)

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

function Initialize-PenguinToolsMua([string]$penguinToolsRoot, [string]$projectRoot) {
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

Write-Host "[1/6] Install build dependencies ..."
& $VenvPy -m pip install -r (Join-Path $Root "requirements-build.txt")

if (-not $SkipPyInstaller) {
    Write-Host "[2/6] Build main app with PyInstaller ..."
    & $VenvPy -m PyInstaller --noconfirm (Join-Path $Root "ChuniEventer.spec")
} else {
    Write-Host "[2/6] Skip PyInstaller"
}

$PenguinToolsRoot = Resolve-PenguinToolsRoot
$PenguinToolsCliOut = $null
if (-not $SkipPenguinToolsCli) {
    if (-not $PenguinToolsRoot) {
        throw "PenguinTools source not found. Run scripts\setup_penguin_tools.ps1, or set CHUNI_PENGUINTOOLS_ROOT to a Foahh/PenguinTools checkout."
    }
    Initialize-PenguinToolsMua -penguinToolsRoot $PenguinToolsRoot -projectRoot $Root
    $PenguinToolsCliProject = Join-Path $PenguinToolsRoot "PenguinTools.CLI\PenguinTools.CLI.csproj"
    $PenguinToolsCliOut = Join-Path $PenguinToolsRoot "PenguinTools.CLI\bin\Release\net10.0\publish\WinX64-SelfContained-SingleFile-EmbeddedAssets"
    Write-Host "[3/6] Publish PenguinTools.CLI ..."
    & dotnet publish $PenguinToolsCliProject -c Release -p:PublishProfile=WinX64-SelfContained-SingleFile-EmbeddedAssets
    if ($LASTEXITCODE -ne 0) {
        throw "dotnet publish PenguinTools.CLI failed (exit $LASTEXITCODE). Run scripts\setup_penguin_tools.ps1, or pass -SkipPenguinToolsCli."
    }
} else {
    $PenguinToolsCliOut = Join-Path $Root "tools\PenguinToolsCLI"
    Write-Host "[3/6] Skip PenguinTools.CLI publish"
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

# FFmpeg essentials (BtbN win64 gpl). 懒人包打入 .tools/ffmpeg/bin/ffmpeg.exe；单 exe 版由应用首次启动自动下载。
$FfmpegUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
$FfmpegZip = Join-Path $Root ".cache\ffmpeg-master-latest-win64-gpl.zip"
$FfmpegStage = Join-Path $Root ".cache\ffmpeg-extract"

function Ensure-Ffmpeg {
    New-Item -ItemType Directory -Path (Join-Path $Root ".cache") -Force | Out-Null
    if (-not (Test-Path $FfmpegZip)) {
        Write-Host "  Downloading ffmpeg win64 gpl zip ..."
        Invoke-WebRequest -Uri $FfmpegUrl -OutFile $FfmpegZip -UseBasicParsing
    }
    $found = Get-ChildItem -Path $FfmpegStage -Recurse -Filter "ffmpeg.exe" -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $found) {
        if (Test-Path $FfmpegStage) { Remove-Item $FfmpegStage -Recurse -Force }
        Write-Host "  Extracting FFmpeg ..."
        Expand-Archive -LiteralPath $FfmpegZip -DestinationPath $FfmpegStage -Force
        $found = Get-ChildItem -Path $FfmpegStage -Recurse -Filter "ffmpeg.exe" -File -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if (-not $found) {
        throw "ffmpeg.exe not found after extract (under $FfmpegStage)"
    }
    return $found.FullName
}

function Copy-FfmpegBundle([string]$toolsParent) {
    $ffmpegExe = Ensure-Ffmpeg
    $destDir = Join-Path $toolsParent "ffmpeg\bin"
    if (Test-Path $destDir) { Remove-Item $destDir -Recurse -Force }
    New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    Copy-Item $ffmpegExe (Join-Path $destDir "ffmpeg.exe") -Force
    # 应用未使用 ffprobe；BtbN gpl 静态包内 ffprobe.exe 亦 ~193MB，故懒人包只带 ffmpeg.exe。
}

if ($BundleCompressonator) {
    Write-Host "[4/5] Ensure Compressonator CLI bundle ..."
    Ensure-CompressonatorCli
} else {
    Write-Host "[4/5] Skip Compressonator bundle (default; pass -IncludeCompressonator for offline fallback)"
}

Write-Host "[5/6] Assemble distributable ..."
$AppExe = Join-Path $Root "dist\ChuniEventer.exe"
if (-not (Test-Path $AppExe)) {
    throw "Main executable not found: $AppExe"
}

# 懒人包目录：解压后 ChuniEventer.exe 与 .tools 同级，双击 exe 即用（与历史发布结构一致）。
$BundleDir = Join-Path $Root ("dist\release\Chuni-Eventer-v{0}" -f $Version)
if (Test-Path $BundleDir) { Remove-Item $BundleDir -Recurse -Force }
New-Item -ItemType Directory -Path $BundleDir -Force | Out-Null

# 与 lite 分发的是同一份 PyInstaller 产物，仅懒人包额外带上 .tools。
Copy-Item $AppExe (Join-Path $BundleDir "ChuniEventer.exe") -Force

$OutTools = Join-Path $BundleDir ".tools"
$DistToolsRoot = Join-Path $Root "dist\.tools"
if (Test-Path $OutTools) { Remove-Item $OutTools -Recurse -Force }
if (Test-Path $DistToolsRoot) { Remove-Item $DistToolsRoot -Recurse -Force }
New-Item -ItemType Directory -Path $OutTools -Force | Out-Null
New-Item -ItemType Directory -Path $DistToolsRoot -Force | Out-Null

Write-Host "  Bundle FFmpeg into .tools ..."
Copy-FfmpegBundle $OutTools
Copy-FfmpegBundle $DistToolsRoot

if ($BundleCompressonator) {
    Copy-CompressonatorBundle $OutTools
    Copy-CompressonatorBundle $DistToolsRoot
}

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
    Copy-PenguinToolsCliPublish (Join-Path $OutTools "PenguinToolsCLI")
    Copy-PenguinToolsCliPublish (Join-Path $DistToolsRoot "PenguinToolsCLI")
} elseif ($SkipPenguinToolsCli) {
    Write-Host "  Skip PenguinTools.CLI bundle (no $PenguinToolsCliExe ; pgko / pjsk 转谱不可用)"
} else {
    throw "PenguinTools.CLI.exe not found: $PenguinToolsCliExe"
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

$C2sSanitizeUrl = "https://github.com/Swan416ya/Chuni-Eventer/releases/download/v0.7.1/c2s-sanitize.exe"

function Ensure-C2sSanitize([string]$projectRoot) {
    $destDir = Join-Path $projectRoot "tools\PenguinTools"
    $dest = Join-Path $destDir "c2s-sanitize.exe"
    if (Test-Path $dest) { return }
    New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    Write-Host "  Downloading c2s-sanitize.exe for lazy bundle ..."
    Invoke-WebRequest -Uri $C2sSanitizeUrl -OutFile $dest -UseBasicParsing
    if (-not (Test-Path $dest)) {
        throw "c2s-sanitize.exe download failed: $dest"
    }
}

Ensure-C2sSanitize -projectRoot $Root
Copy-PenguinToolsBundle $OutTools
Copy-PenguinToolsBundle $DistToolsRoot

if ($BundleCompressonator) {
    $ThirdParty = Join-Path $Root "packaging\THIRD_PARTY_COMPRESSONATOR.txt"
    if (Test-Path $ThirdParty) {
        Copy-Item $ThirdParty (Join-Path $BundleDir "THIRD_PARTY_COMPRESSONATOR.txt") -Force
    }
}

$ReleaseNote = Join-Path $Root ("packaging\GITHUB_RELEASE_v{0}.md" -f $Version)
if (Test-Path $ReleaseNote) {
    Copy-Item $ReleaseNote (Join-Path $BundleDir ("GITHUB_RELEASE_v{0}.md" -f $Version)) -Force
}

$readmeTools = if ($BundleCompressonator) {
    "FFmpeg、Compressonator CLI、PenguinToolsCLI、mua、c2s-sanitize"
} else {
    "FFmpeg、PenguinToolsCLI、mua、c2s-sanitize"
}
$ReadmeBundle = @"
Chuni Eventer v$Version（离线懒人包）

解压本 zip 后目录内应包含：
  ChuniEventer.exe
  .tools\          （$readmeTools 等，与 exe 同级）

直接双击 ChuniEventer.exe 即可使用，无需再下载上述依赖。
DDS 转换默认使用 exe 内自带的 quicktex。若 quicktex 不可用且需 Compressonator 回退，请在
「设置 - 外部工具」一键下载，或使用 -IncludeCompressonator 构建的完整懒人包。

GitHub Release 默认推荐 Lite 单 exe：体积更小，可按需在首次运行时下载 .tools。
"@
Set-Content -Path (Join-Path $BundleDir "README.txt") -Value $ReadmeBundle -Encoding UTF8

$ZipBundle = Join-Path $Root ("dist\Chuni-Eventer-v{0}.zip" -f $Version)
if (Test-Path $ZipBundle) { Remove-Item $ZipBundle -Force }
Compress-Archive -Path (Join-Path $BundleDir "*") -DestinationPath $ZipBundle -CompressionLevel Optimal

# Lite：只分发这一个 exe（与懒人包内 ChuniEventer.exe 为同一构建产物）。
$ReleaseDir = Join-Path $Root "dist\release"
New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null
$LiteExe = Join-Path $ReleaseDir "ChuniEventer.exe"
Copy-Item $AppExe $LiteExe -Force

Write-Host "Done."
Write-Host "Build EXE (lite + 懒人包共用): $AppExe"
Write-Host "PenguinTools.CLI: $PenguinToolsCliExe"
Write-Host "FFmpeg: $(Join-Path $BundleDir '.tools\ffmpeg\bin\ffmpeg.exe')"
if ($BundleCompressonator) {
    Write-Host "CompressonatorCLI: $(Join-Path $BundleDir '.tools\CompressonatorCLI\compressonatorcli.exe')"
} else {
    Write-Host 'CompressonatorCLI: skipped (pass -IncludeCompressonator to bundle)'
}
Write-Host "懒人包目录: $BundleDir"
Write-Host "懒人包 zip: $ZipBundle"
Write-Host "Lite 单 exe (上传 GitHub): $LiteExe"
