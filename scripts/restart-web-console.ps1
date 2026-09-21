$ErrorActionPreference = 'Stop'
$connections = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
foreach ($connection in $connections) { Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Process -WindowStyle Hidden -FilePath py -ArgumentList @('-m','http.server','8765','--bind','127.0.0.1','--directory','D:\akagent\apps\web-console\dist') -WorkingDirectory 'D:\akagent\apps\web-console'
Start-Sleep -Seconds 1
Invoke-WebRequest http://127.0.0.1:8765/ -TimeoutSec 5 | Select-Object -ExpandProperty StatusCode
