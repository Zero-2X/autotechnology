param([int]$WebPort = 8766, [int]$ApiPort = 8000)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$console = Join-Path $root 'apps\web-console'
node (Join-Path $console 'scripts\build.mjs') --out-dir (Join-Path $console 'dist')
function Test-LocalEndpoint([string]$Url) {
    try { Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 1 | Out-Null; return $true } catch { return $false }
}
if (-not (Test-LocalEndpoint "http://127.0.0.1:$ApiPort/health/live")) {
    Start-Process -WindowStyle Hidden -FilePath python -ArgumentList @('-m','uvicorn','apps.api.main:create_app','--factory','--host','127.0.0.1','--port',"$ApiPort") -WorkingDirectory $root
}
if (-not (Test-LocalEndpoint "http://127.0.0.1:$WebPort/")) {
    Start-Process -WindowStyle Hidden -FilePath python -ArgumentList @('-m','http.server',"$WebPort",'--bind','127.0.0.1','--directory',(Join-Path $console 'dist')) -WorkingDirectory $console
}
$ready = $false
for ($i = 0; $i -lt 20; $i++) {
    if (Test-LocalEndpoint "http://127.0.0.1:$ApiPort/health/live") { $ready = $true; break }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) { throw "API failed to start; check whether port $ApiPort is already in use." }
Write-Host "Web: http://127.0.0.1:$WebPort/"
Write-Host "API:  http://127.0.0.1:$ApiPort/health/live"
