$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
& (Join-Path $root "stop.ps1")
Start-Sleep -Seconds 1
& (Join-Path $root "start.ps1") @args
