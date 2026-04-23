# Clone Foahh/PenguinTools into repo root as ./PenguinTools (used to publish PenguinTools.CLI for packaging).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Target = Join-Path $Root "PenguinTools"
$cli = Join-Path $Target "PenguinTools.CLI\PenguinTools.CLI.csproj"
if (Test-Path $cli) {
    Write-Host "PenguinTools already present: $cli"
    exit 0
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git not found. Install Git for Windows, or clone manually: https://github.com/Foahh/PenguinTools"
}
Write-Host "Cloning Foahh/PenguinTools -> $Target ..."
git clone --depth 1 "https://github.com/Foahh/PenguinTools.git" $Target
if ($LASTEXITCODE -ne 0) {
    if (Test-Path $Target) { Remove-Item $Target -Recurse -Force -ErrorAction SilentlyContinue }
    throw "git clone failed (exit $LASTEXITCODE). Check network / proxy, or clone manually into: $Target"
}
if (-not (Test-Path $cli)) {
    if (Test-Path $Target) { Remove-Item $Target -Recurse -Force -ErrorAction SilentlyContinue }
    throw "Clone finished but project file missing: $cli"
}

Write-Host "Initializing PenguinTools submodules ..."
git -C $Target submodule update --init --recursive
if ($LASTEXITCODE -ne 0) {
    throw "submodule update failed (exit $LASTEXITCODE). Check network / proxy and rerun."
}

Write-Host "Done. Next: dotnet publish PenguinTools\PenguinTools.CLI\PenguinTools.CLI.csproj -c Release -p:PublishProfile=WinX64-SelfContained-SingleFile-ExternalAssets"
