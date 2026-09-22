param([int]$WebPort = 8766, [int]$ApiPort = 8000)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$console = Join-Path $root 'apps\web-console'
# Model access is optional.  When a key is present, select the documented
# OpenAI-compatible proxy without ever writing the key to disk or displaying it.
if ($env:OPENAI_API_KEY) {
    if (-not $env:MODEL_PROVIDER) { $env:MODEL_PROVIDER = 'zpproxy' }
    if (-not $env:MODEL_BASE_URL) { $env:MODEL_BASE_URL = 'https://webaiproxy.top/v1' }
    if (-not $env:MODEL_ID) { $env:MODEL_ID = 'gpt-5.6-sol' }
    if (-not $env:MODEL_TIMEOUT_SECONDS) { $env:MODEL_TIMEOUT_SECONDS = '20' }
}
node (Join-Path $console 'scripts\build.mjs') --out-dir (Join-Path $console 'dist')
function Test-LocalEndpoint([string]$Url) {
    try { Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 1 | Out-Null; return $true } catch { return $false }
}
if (-not (Test-LocalEndpoint "http://127.0.0.1:$ApiPort/health/live")) {
    Start-Process -WindowStyle Hidden -FilePath python -ArgumentList @('-m','uvicorn','apps.api.main:create_app','--factory','--host','127.0.0.1','--port',"$ApiPort") -WorkingDirectory $root
}
$ready = $false
for ($i = 0; $i -lt 20; $i++) {
    if (Test-LocalEndpoint "http://127.0.0.1:$ApiPort/health/live") { $ready = $true; break }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) { throw "API failed to start; check whether port $ApiPort is already in use." }
if (-not (Test-LocalEndpoint "http://127.0.0.1:$WebPort/")) {
    Start-Process -WindowStyle Hidden -FilePath python -ArgumentList @('-m','http.server',"$WebPort",'--bind','127.0.0.1','--directory',(Join-Path $console 'dist')) -WorkingDirectory $console
}
$webReady = $false
for ($i = 0; $i -lt 20; $i++) {
    if (Test-LocalEndpoint "http://127.0.0.1:$WebPort/") { $webReady = $true; break }
    Start-Sleep -Milliseconds 250
}
if (-not $webReady) { throw "Web console failed to start; check whether port $WebPort is already in use." }
Write-Host "Web: http://127.0.0.1:$WebPort/"
Write-Host "API:  http://127.0.0.1:$ApiPort/health/live"
