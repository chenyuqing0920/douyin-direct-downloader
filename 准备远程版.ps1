$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
New-Item -ItemType Directory -Path '.\tools' -Force | Out-Null
if (-not (Test-Path -LiteralPath '.\tools\cloudflared.exe')) {
    Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile '.\tools\cloudflared.exe'
}
Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/cloudflare/cloudflared/master/LICENSE' -OutFile '.\tools\cloudflared-LICENSE.txt'
$tunnelSignature = Get-AuthenticodeSignature -LiteralPath '.\tools\cloudflared.exe'
if ($tunnelSignature.Status -ne 'Valid' -or $tunnelSignature.SignerCertificate.Subject -notmatch 'Cloudflare') {
    throw '远程连接组件的 Cloudflare 数字签名验证失败，请重新从官网下载。'
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查网络。' }
Write-Host '准备完成，请运行 启动手机远程版.ps1。'
