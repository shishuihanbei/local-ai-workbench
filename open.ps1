# AI Workbench desktop launcher.
# Kept ASCII-only on purpose: Windows PowerShell 5.1 reads UTF-8 without BOM as GBK,
# and non-ASCII comments used to break the param block (icon did nothing on double-click).
param(
  [int]$Port = 0,
  [ValidateSet('front', 'console')][string]$Mode = 'console',
  [switch]$DryRun
)

$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$cfgPath = Join-Path $root 'data\config.json'
$cfg = $null
if (Test-Path -LiteralPath $cfgPath) {
  try {
    $cfg = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
  } catch { $cfg = $null }
}
if ($Port -le 0) {
  $Port = 9100
  if ($cfg -and $cfg.port) { try { $Port = [int]$cfg.port } catch { $Port = 9100 } }
}

$local = 'http://127.0.0.1:' + $Port

function Test-WorkbenchUp {
  param([string]$Base)
  try {
    $r = Invoke-WebRequest ($Base + '/api/health') -TimeoutSec 3 -UseBasicParsing
    return ($r.StatusCode -eq 200)
  } catch { return $false }
}

function Get-ShortcutBase {
  $mode = 'local'
  if ($cfg -and $cfg.shortcut_mode) { $mode = [string]$cfg.shortcut_mode }
  if ($mode -eq 'lan') {
    $ip = ''
    if ($cfg -and $cfg.shortcut_lan_ip) { $ip = [string]$cfg.shortcut_lan_ip }
    if (-not $ip) {
      try {
        $ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
          Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
          Select-Object -First 1 -ExpandProperty IPAddress
      } catch { $ip = '' }
    }
    if ($ip) { return ('http://' + $ip + ':' + $Port) }
  }
  if ($mode -eq 'custom') {
    $u = ''
    if ($cfg -and $cfg.shortcut_custom_url) { $u = ([string]$cfg.shortcut_custom_url).Trim() }
    if ($u -match '^https?://') {
      while ($u.EndsWith('/')) { $u = $u.Substring(0, $u.Length - 1) }
      return $u
    }
  }
  return $local
}

$base = Get-ShortcutBase
if ($Mode -eq 'front') { $url = $base + '/' } else { $url = $base + '/console/' }
if ($DryRun) { Write-Output $url; exit 0 }

if (-not (Test-WorkbenchUp $local)) {
  $start = Join-Path $root 'start.ps1'
  if (Test-Path -LiteralPath $start) {
    Start-Process -FilePath 'powershell.exe' `
      -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
                      '-File', $start, '-NoBrowser', '-Port', "$Port") `
      -WindowStyle Hidden
    for ($i = 0; $i -lt 45; $i++) {
      Start-Sleep -Milliseconds 700
      if (Test-WorkbenchUp $local) { break }
    }
  }
}

$opened = $false
try { Start-Process $url; $opened = $true } catch { $opened = $false }
if (-not $opened) {
  try { & (Join-Path $env:SystemRoot 'explorer.exe') $url; $opened = $true } catch { $opened = $false }
}
if (-not $opened) {
  $logDir = Join-Path $root 'data\logs'
  New-Item -ItemType Directory -Force -Path $logDir | Out-Null
  $line = '{0} open failed: {1} up={2}' -f (Get-Date -Format 's'), $url, (Test-WorkbenchUp $local)
  Add-Content -LiteralPath (Join-Path $logDir 'desktop-open.log') -Value $line
}
