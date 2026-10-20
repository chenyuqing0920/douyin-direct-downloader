$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.\tools\cloudflared.exe')) { throw '请先运行 准备远程版.ps1。' }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --windowed --onedir --name '抖音手机远程版' --collect-all playwright --collect-all yt_dlp --add-data 'web;web' --add-binary 'tools\cloudflared.exe;tools' remote_app.py
if ($LASTEXITCODE -ne 0) { throw '打包失败。' }
Copy-Item -LiteralPath '.\手机远程版使用说明.md','.\开源说明.md' -Destination '.\dist\抖音手机远程版'
& .\.venv\Scripts\python.exe .\tools\copy_licenses.py '.\dist\抖音手机远程版'
Write-Host '完成：dist\抖音手机远程版\抖音手机远程版.exe'
