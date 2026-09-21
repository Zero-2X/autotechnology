param([Parameter(Mandatory=$true)][string]$AccountKey)
$ErrorActionPreference = 'Stop'
python (Join-Path $PSScriptRoot 'start-xhs-login.py') --account-key $AccountKey
