param([ValidateRange(1024, 65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$consolePath = Join-Path $root 'apps\web-console'
$buildPath = Join-Path $root '.local\web-console-dist'
Push-Location $consolePath
try {
    node scripts/build.mjs --out-dir $buildPath
    if ($LASTEXITCODE -ne 0) { throw 'Web console build failed.' }
    Write-Host "Open http://127.0.0.1:$Port/ — browser-local prototype; Ctrl+C stops the server."
    python -m http.server $Port --bind 127.0.0.1 --directory $buildPath
} finally {
    Pop-Location
}
