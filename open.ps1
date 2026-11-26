# AI 工作台桌面图标入口：服务没在跑就先静默拉起来，再打开前台页面。
param(
  [int]$Port = 0
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($Port -le 0) {
  $cfgPath = Join-Path $root "data\config.json"
  if (Test-Path -LiteralPath $cfgPath) {
    try { $Port = [int](Get-Content -LiteralPath $cfgPath -Raw | ConvertFrom-Json).port } catch { $Port = 0 }
  }
}
if ($Port -le 0) { $Port = 9100 }

$base = "http://127.0.0.1:$Port"
function Test-WorkbenchUp {
  try {
    $r = Invoke-WebRequest "$base/api/health" -TimeoutSec 3 -UseBasicParsing
    return ($r.StatusCode -eq 200)
  } catch { return $false }
}

if (-not (Test-WorkbenchUp)) {
  $start = Join-Path $root "start.ps1"
  if (Test-Path -LiteralPath $start) {
    Start-Process -FilePath "powershell.exe" `
      -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                      "-File", $start, "-NoBrowser", "-Port", "$Port") `
      -WindowStyle Hidden
    for ($i = 0; $i -lt 45; $i++) {
      Start-Sleep -Milliseconds 700
      if (Test-WorkbenchUp) { break }
    }
  }
}

Start-Process "$base/"
