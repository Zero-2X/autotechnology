$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$buildPath = Join-Path $root '.local\web-console-dist'
$connections = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
foreach ($connection in $connections) { Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Process -WindowStyle Hidden -FilePath py -ArgumentList @('-m','http.server','8765','--bind','127.0.0.1','--directory',$buildPath) -WorkingDirectory $root
Start-Sleep -Seconds 1
Invoke-WebRequest http://127.0.0.1:8765/ -TimeoutSec 5 | Select-Object -ExpandProperty StatusCode
