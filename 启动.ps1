$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$appExe = Join-Path $PSScriptRoot 'dist\抖音视频下载器\抖音视频下载器.exe'
$appPython = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
if (Test-Path -LiteralPath $appExe) {
    Start-Process -FilePath $appExe -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
} elseif (Test-Path -LiteralPath $appPython) {
    Start-Process -FilePath $appPython -ArgumentList 'app.py' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
} else {
    throw '请先运行 安装依赖.ps1，或使用 dist 文件夹内的打包程序。'
}
