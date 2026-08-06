# 将 ChuniPingu/PenguinTools 放到仓库根目录 ./PenguinTools，供打包时发布 PenguinTools.CLI。
# 发布还依赖 External/mua 与 PenguinTools.CRI，详见 scripts/build_windows.ps1。
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Target = Join-Path $Root "PenguinTools"
$cli = Join-Path $Target "PenguinTools.CLI\PenguinTools.CLI.csproj"

# 若本机已有 penguin-butler 下的 PenguinTools，优先建立目录联接。
$ButlerPt = Join-Path (Split-Path -Parent $Root) "penguin-butler\external\PenguinTools"
$ButlerCli = Join-Path $ButlerPt "PenguinTools.CLI\PenguinTools.CLI.csproj"
if ((-not (Test-Path $cli)) -and (Test-Path $ButlerCli)) {
    Write-Host "联接 penguin-butler PenguinTools -> $Target ..."
    New-Item -ItemType Junction -Path $Target -Target $ButlerPt | Out-Null
}

if (Test-Path $cli) {
    Write-Host "PenguinTools 已就绪：$cli"
    exit 0
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "未找到 git。请安装 Git for Windows，或手动克隆：https://github.com/ChuniPingu/PenguinTools"
}
Write-Host "正在克隆 ChuniPingu/PenguinTools -> $Target ..."
git clone --depth 1 "https://github.com/ChuniPingu/PenguinTools.git" $Target
if ($LASTEXITCODE -ne 0) {
    if (Test-Path $Target) { Remove-Item $Target -Recurse -Force -ErrorAction SilentlyContinue }
    throw "git clone 失败（exit $LASTEXITCODE）。请检查网络/代理，或手动克隆到：$Target"
}
if (-not (Test-Path $cli)) {
    if (Test-Path $Target) { Remove-Item $Target -Recurse -Force -ErrorAction SilentlyContinue }
    throw "克隆完成但缺少工程文件：$cli"
}

Write-Host "正在初始化 PenguinTools 子模块 ..."
git -C $Target submodule update --init --recursive
if ($LASTEXITCODE -ne 0) {
    throw "submodule update 失败（exit $LASTEXITCODE）。请检查网络/代理后重试。"
}

Write-Host "完成。下一步可用 scripts\build_windows.ps1（发布 NativeAOT CLI + CRI），或手动："
Write-Host "  cd External\mua; .\scripts\build.ps1"
Write-Host "  dotnet publish PenguinTools.CRI\PenguinTools.CRI.csproj -c Release -p:PublishProfile=WinX64-NativeAOT"
Write-Host "  dotnet publish PenguinTools.CLI\PenguinTools.CLI.csproj -c Release -p:PublishProfile=WinX64-NativeAOT"
