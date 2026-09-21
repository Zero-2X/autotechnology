param([int]$WebPort = 8765, [int]$ApiPort = 8000)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$console = Join-Path $root 'apps\web-console'
node (Join-Path $console 'scripts\build.mjs') --out-dir (Join-Path $console 'dist')
Start-Process -WindowStyle Hidden -FilePath python -ArgumentList @('-m','uvicorn','apps.api.main:create_app','--factory','--host','127.0.0.1','--port',"$ApiPort") -WorkingDirectory $root
Start-Process -WindowStyle Hidden -FilePath python -ArgumentList @('-m','http.server',"$WebPort",'--bind','127.0.0.1','--directory',(Join-Path $console 'dist')) -WorkingDirectory $console
Write-Host "后台: http://127.0.0.1:$WebPort/"
Write-Host "API:  http://127.0.0.1:$ApiPort/health/live"
