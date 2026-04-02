# Clone Foahh/PenguinTools into repo root as ./PenguinTools (required to build PenguinBridge with Core).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Target = Join-Path $Root "PenguinTools"
$core = Join-Path $Target "PenguinTools.Core\PenguinTools.Core.csproj"
if (Test-Path $core) {
    Write-Host "PenguinTools already present: $core"
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
if (-not (Test-Path $core)) {
    if (Test-Path $Target) { Remove-Item $Target -Recurse -Force -ErrorAction SilentlyContinue }
    throw "Clone finished but project file missing: $core"
}
Write-Host "Done. Next: dotnet build tools\PenguinBridge\PenguinBridge.csproj -c Release"
