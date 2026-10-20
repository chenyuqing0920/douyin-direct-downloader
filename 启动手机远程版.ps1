$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$remoteExe = Join-Path $PSScriptRoot 'dist\抖音手机远程版\抖音手机远程版.exe'
$remotePython = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
if (Test-Path -LiteralPath $remoteExe) {
    Start-Process -FilePath $remoteExe -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
} elseif (Test-Path -LiteralPath $remotePython) {
    Start-Process -FilePath $remotePython -ArgumentList 'remote_app.py' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
} else {
    throw '请先运行 安装依赖.ps1 和 准备远程版.ps1。'
}
