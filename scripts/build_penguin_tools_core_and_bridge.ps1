# Build vendored PenguinTools.Core (net8) + PenguinBridge, and copy runtime next to the bridge exe.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "==> dotnet build PenguinTools.Core (Release)"
dotnet build "PenguinTools\PenguinTools.Core\PenguinTools.Core.csproj" -c Release

Write-Host "==> dotnet build PenguinBridge (Release)"
dotnet build "tools\PenguinBridge\PenguinBridge.csproj" -c Release

$Out = Join-Path $Root "tools\PenguinBridge\bin\Release\net8.0"
Write-Host "Done. Bridge output: $Out"
Write-Host "Expected: PenguinBridge.exe, assets.json, PenguinTools.Core.dll, SonicAudioLib.dll, VGAudio.dll, System.Text.Json.dll"
