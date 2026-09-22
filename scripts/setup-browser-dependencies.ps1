param()
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
python -m pip install -r (Join-Path $root 'requirements-browser.txt')
python -m playwright install chromium
Write-Host 'Browser dependencies are ready.'
