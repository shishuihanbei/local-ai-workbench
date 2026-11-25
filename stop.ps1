# 停止工作台（Windows）
$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$pidFile = Join-Path $root "data\workbench.pid"
$portFile = Join-Path $root "data\workbench.port"

function Kill-Tree($procId) {
    if (-not $procId) { return }
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$procId" -ErrorAction SilentlyContinue
    foreach ($ch in $children) { Kill-Tree $ch.ProcessId }
    if (Get-Process -Id $procId -ErrorAction SilentlyContinue) {
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Write-Host "已停止 (PID $procId)" -ForegroundColor Green
    }
}

$target = 0
if (Test-Path $pidFile) {
    $raw = (Get-Content $pidFile -Raw).Trim()
    try { $target = [int](($raw | ConvertFrom-Json).pid) } catch { try { $target = [int]$raw } catch {} }
}

$port = 0
if (Test-Path $portFile) { try { $port = [int](Get-Content $portFile) } catch {} }

if ($target -gt 0) {
    Kill-Tree $target
} else {
    Write-Host "未找到 PID 文件（可能不是通过 start.bat 启动的）"
}

# 端口上的实际监听进程也要停掉：venv 的 pythonw 可能再拉起一个基础解释器子进程
if ($port -gt 0) {
    for ($i = 0; $i -lt 3; $i++) {
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if (-not $conn) { break }
        foreach ($c in $conn) { Kill-Tree $c.OwningProcess }
        Start-Sleep -Milliseconds 600
    }
    $still = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($still) {
        Write-Host "端口 $port 仍被 PID $($still.OwningProcess) 占用，请手动结束该进程。" -ForegroundColor Yellow
    } else {
        Write-Host "端口 $port 已释放"
    }
}

Remove-Item $pidFile -Force
Remove-Item $portFile -Force
