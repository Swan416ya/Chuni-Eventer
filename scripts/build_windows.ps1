# Run from repo root is NOT required; script cd's to parent of scripts/
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$VenvPy = Join-Path $Root ".venv-build\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Write-Host "Creating .venv-build ..."
    python -m venv (Join-Path $Root ".venv-build")
}
& $VenvPy -m pip install -r (Join-Path $Root "requirements-build.txt")
& $VenvPy -m PyInstaller --noconfirm (Join-Path $Root "ChuniEventer.spec")
Write-Host "Done: dist\ChuniEventer.exe"
