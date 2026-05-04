# Decode CHUNITHM-style .awb (HCA) to WAV via bundled vgmstream-cli.
# Streaming .acb banks often have no embedded wave data — decode the sibling .awb with the same base name.
param(
    [Parameter(Mandatory = $true)]
    [string] $Source,
    [string] $OutputDir = ""
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$cli = Join-Path $here "vgmstream\vgmstream-cli.exe"
if (-not (Test-Path $cli)) {
    throw "Missing vgmstream-cli at $cli"
}

$repoRoot = Split-Path -Parent $here
if (-not $OutputDir) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputDir = Join-Path $repoRoot "_decoded_audio\decode_$stamp"
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$files = @()
if (Test-Path -LiteralPath $Source -PathType Container) {
    $files = Get-ChildItem -LiteralPath $Source -Recurse -File -Include "*.awb", "*.acb" | ForEach-Object { $_.FullName }
}
elseif (Test-Path -LiteralPath $Source -PathType Leaf) {
    $files = @((Resolve-Path -LiteralPath $Source).Path)
}
else {
    throw "Source not found: $Source"
}

$doneAwb = @{}
foreach ($f in $files) {
    if ($f -notmatch '\.(awb|acb)$') { continue }
    $dir = Split-Path -Parent $f
    $stem = [System.IO.Path]::GetFileNameWithoutExtension($f)
    $awbPath = if ($f -match '\.awb$') { $f } else { Join-Path $dir "$stem.awb" }

    if (-not (Test-Path -LiteralPath $awbPath)) {
        Write-Warning "Skipping $(Split-Path -Leaf $f): no matching AWB at $(Split-Path -Leaf $awbPath)"
        continue
    }
    if ($doneAwb.ContainsKey($awbPath.ToLowerInvariant())) { continue }
    $doneAwb[$awbPath.ToLowerInvariant()] = $true

    $prefix = ($stem -replace '[^\w\-]+', '_')
    Push-Location -LiteralPath $OutputDir
    try {
        Write-Host "Decoding $(Split-Path -Leaf $awbPath) -> $OutputDir"
        & $cli -S 0 -o "${prefix}_?s.wav" $awbPath
    }
    finally {
        Pop-Location
    }
}

Write-Host ""
Write-Host "Done. WAV files are in:"
Write-Host $OutputDir
