param([ValidateRange(1024, 65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$consolePath = Join-Path (Split-Path $PSScriptRoot -Parent) 'apps\web-console'
Push-Location $consolePath
try {
    node scripts/build.mjs --out-dir dist
    if ($LASTEXITCODE -ne 0) { throw 'Web console build failed.' }
    Write-Host "Open http://127.0.0.1:$Port/ — browser-local prototype; Ctrl+C stops the server."
    python -m http.server $Port --bind 127.0.0.1 --directory dist
} finally {
    Pop-Location
}
