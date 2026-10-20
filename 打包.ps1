$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& .\.venv\Scripts\python.exe -m pip install 'pyinstaller==6.22.3'
if ($LASTEXITCODE -ne 0) { throw '打包工具安装失败。' }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name '抖音视频下载器' --collect-all playwright --collect-all yt_dlp --add-data 'README.md;.' --add-data '开源说明.md;.' app.py
if ($LASTEXITCODE -ne 0) { throw '打包失败。' }
Write-Host '完成：dist\抖音视频下载器\抖音视频下载器.exe'
