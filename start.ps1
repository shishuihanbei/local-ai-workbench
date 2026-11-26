param(
    [int]$Port = 9100,
    [string]$HostAddr = "0.0.0.0",
    [string]$PythonExe = "",
    [switch]$Foreground,
    [switch]$NoBrowser
)

# 本地一键启动：检测 Python → 建虚拟环境 → 装依赖 → 后台启动 → 打开页面
# 兼容 Windows PowerShell 5.1 / PowerShell 7
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail($msg) {
    Write-Host ""
    Write-Host "[失败] $msg" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "本地 AI 工作台 · 一键启动" -ForegroundColor Green
Write-Host "目录：$root"
Write-Host ""

# ---------------------------------------------------------------- 1. 准备数据目录
foreach ($d in @("data", "data\logs", "data\audio", "data\uploads")) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d | Out-Null }
}

# ---------------------------------------------------------------- 2. 找 Python
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
$venvPyW = Join-Path $root ".venv\Scripts\pythonw.exe"
$sysPy = $null

function Get-PythonVersion($exe) {
    try {
        $out = & $exe -c "import sys; print(sys.version_info[0], sys.version_info[1], sys.version.split()[0])" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
        $parts = "$out".Trim().Split(" ")
        if ($parts.Count -lt 3) { return $null }
        return [pscustomobject]@{
            Major = [int]$parts[0]
            Minor = [int]$parts[1]
            Text  = [string]$parts[2]
        }
    } catch { return $null }
}

function Test-PythonVersion($v) {
    return ($v -and $v.Major -eq 3 -and $v.Minor -ge 10 -and $v.Minor -le 12)
}

function Find-Python([switch]$CompatibleOnly) {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($PythonExe) { $candidates.Add($PythonExe) }
    $localPy = Join-Path $env:LOCALAPPDATA "Programs\Python"
    foreach ($v in @("312", "311", "310", "313")) {
        $candidates.Add((Join-Path $localPy "Python$v\python.exe"))
        $candidates.Add("C:\Python$v\python.exe")
        $candidates.Add("D:\Python$v\python.exe")
        $candidates.Add("C:\Program Files\Python$v\python.exe")
    }
    $candidates.Add("D:\AI\python312\python.exe")
    $candidates.Add("D:\AI\python311\python.exe")
    $candidates.Add("D:\AI\python310\python.exe")

    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($ver in @("3.12", "3.11", "3.10", "3.13")) {
            try {
                $p = & py "-$ver" -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $p) { $candidates.Add("$p".Trim()) }
            } catch {}
        }
    }
    foreach ($name in @("python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $candidates.Add($cmd.Source) }
    }

    $seen = @{}
    foreach ($c in $candidates) {
        if (-not $c) { continue }
        $key = "$c".ToLower()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = 1
        if (-not (Test-Path $c)) { continue }
        $v = Get-PythonVersion $c
        if (-not $v) { continue }
        if ($CompatibleOnly -and -not (Test-PythonVersion $v)) { continue }
        if (-not $CompatibleOnly -and -not ($v.Major -eq 3 -and $v.Minor -ge 10)) { continue }
        return $c
    }
    return $null
}

$useExisting = $false
$venvVersion = $null
if (Test-Path $venvPy) { $venvVersion = Get-PythonVersion $venvPy }

if ($venvVersion -and (Test-PythonVersion $venvVersion)) {
    Write-Step "使用已有虚拟环境 .venv（Python $($venvVersion.Text)）"
    $useExisting = $true
} elseif ($venvVersion) {
    Write-Step "现有 .venv 是 Python $($venvVersion.Text)"
    Write-Step "资料库 OCR 需要 Python 3.10–3.12，正在寻找合适版本"
    $compatible = Find-Python -CompatibleOnly
    if ($compatible) {
        $sysPy = $compatible
        $backup = Join-Path $root (".venv-old-" + $venvVersion.Minor)
        Write-Step "改用 Python：$sysPy"
        Write-Step "旧虚拟环境改名保留：$backup"
        if (Test-Path $backup) { Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue }
        try {
            Rename-Item -LiteralPath (Join-Path $root ".venv") -NewName (Split-Path $backup -Leaf) -ErrorAction Stop
        } catch { Fail "旧虚拟环境改名失败，请先关闭正在运行的工作台，再重新运行 start.bat。" }
    } else {
        Write-Step "没找到 Python 3.10–3.12；先用 Python $($venvVersion.Text) 启动，OCR 暂不可用"
        $useExisting = $true
    }
} else {
    Write-Step "检测 Python（优先使用 3.10–3.12）"
    $sysPy = Find-Python -CompatibleOnly
    if (-not $sysPy) {
        $sysPy = Find-Python
        if ($sysPy) {
            $sv = Get-PythonVersion $sysPy
            Write-Host "    未找到 Python 3.10–3.12，将使用 Python $($sv.Text)；OCR 暂不可用" -ForegroundColor Yellow
        }
    }
    if (-not $sysPy) {
        Fail "没找到 Python 3.10+。请先安装 Python 3.12（勾选 Add python.exe to PATH），再重新运行 start.bat。`n下载：https://www.python.org/downloads/release/python-3127/"
    }
}

if (-not $useExisting) {
    Write-Step "使用 Python：$sysPy"
    Write-Step "创建虚拟环境 .venv（只需一次）"
    & $sysPy -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "创建虚拟环境失败：$sysPy -m venv .venv" }
    if (-not (Test-Path $venvPy)) { Fail "虚拟环境缺少 python.exe" }
}

$py = if (Test-Path $venvPy) { $venvPy } else { $sysPy }
$pyw = if (Test-Path $venvPyW) { $venvPyW } else { $py }

# ---------------------------------------------------------------- 3. 检查依赖
Write-Step "检查依赖"
$coreReq = Join-Path $root "requirements.txt"
$ocrReq = Join-Path $root "requirements-ocr.txt"
$importTest = "import fastapi, uvicorn, aiosqlite, httpx, psutil, edge_tts, mutagen, cryptography, pypdf, docx, openpyxl, xlrd, pptx, pymupdf, PIL"
& $py -c $importTest 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Step "首次安装基础依赖（国内默认走清华镜像，约 1-3 分钟）"
    $index = if ($env:PIP_INDEX_URL) { $env:PIP_INDEX_URL } else { "https://pypi.tuna.tsinghua.edu.cn/simple" }
    & $py -m pip install --upgrade pip --disable-pip-version-check -q
    & $py -m pip install -r $coreReq --disable-pip-version-check -i $index
    if ($LASTEXITCODE -ne 0) {
        Write-Step "镜像失败，改用官方 PyPI 重试"
        & $py -m pip install -r $coreReq --disable-pip-version-check
        if ($LASTEXITCODE -ne 0) {
            Fail "基础依赖安装失败。可手动执行：`n  .venv\Scripts\python.exe -m pip install -r requirements.txt"
        }
    }
    & $py -c $importTest
    if ($LASTEXITCODE -ne 0) { Fail "基础依赖装完但导入失败，请把上面的报错发我" }
} else {
    Write-Host "    基础依赖齐全"
}

# OCR 是可选组件：缺少它时聊天、资料库、格式解析照常，只有图片/扫描件不识别文字。
& $py -c "import rapidocr_onnxruntime" 2>$null
if ($LASTEXITCODE -ne 0) {
    $ocrPy = Get-PythonVersion $py
    if (Test-PythonVersion $ocrPy) {
        Write-Step "安装可选 OCR 组件（图片/扫描件识别，约 1-3 分钟）"
        $ocrIndex = if ($env:PIP_INDEX_URL) { $env:PIP_INDEX_URL } else { "https://pypi.tuna.tsinghua.edu.cn/simple" }
        & $py -m pip install -r $ocrReq --disable-pip-version-check -i $ocrIndex
        if ($LASTEXITCODE -ne 0) {
            Write-Step "镜像失败，改用官方 PyPI 安装 OCR"
            & $py -m pip install -r $ocrReq --disable-pip-version-check
        }
        & $py -c "import rapidocr_onnxruntime" 2>$null
        if ($LASTEXITCODE -eq 0) { Write-Host "    OCR 组件已就绪" } else {
            Write-Host "    [提示] OCR 组件没装成功；其余功能正常，图片/扫描件暂不识别文字。" -ForegroundColor Yellow
        }
    } else {
        Write-Host "    [提示] 当前 Python $($ocrPy.Text) 不支持 OCR 组件（需要 3.10–3.12）；其余功能正常。" -ForegroundColor Yellow
    }
} else {
    Write-Host "    OCR 组件齐全"
}

# ---------------------------------------------------------------- 3.5 路径可移植修正
# 从别的机器拷来时，config.json 里可能还写着原机器的绝对路径。
# 只在原路径不存在时，改为包内相对目录，避免一键安装写到不存在的盘。
$pathFix = @'
import sys
sys.path.insert(0, ".")
from pathlib import Path
from backend.config import load_config, save_config
cfg = load_config()
changed = []
if not Path(cfg["models_dir"]).exists():
    cfg["models_dir"] = str(Path.cwd() / "models")
    changed.append("models_dir")
if not Path(cfg["llama_dir"]).exists():
    cfg["llama_dir"] = str(Path.cwd() / "platforms" / "llama.cpp")
    changed.append("llama_dir")
if changed:
    save_config(cfg)
    print("[path] updated: " + ", ".join(changed))
'@
$pathFix | & $py -

# ---------------------------------------------------------------- 4. 已有实例？
$pidFile = Join-Path $root "data\workbench.pid"
if (Test-Path $pidFile) {
    $oldRaw = (Get-Content $pidFile -Raw).Trim()
    $oldId = 0
    try { $oldId = [int](($oldRaw | ConvertFrom-Json).pid) } catch { try { $oldId = [int]$oldRaw } catch {} }
    if ($oldId -gt 0 -and (Get-Process -Id $oldId -ErrorAction SilentlyContinue)) {
        $p = Get-Content (Join-Path $root "data\workbench.port") -ErrorAction SilentlyContinue
        if (-not $p) { $p = $Port }
        if ([int]$p -eq $Port) {
            Write-Host ""
            Write-Host "已在运行 (PID $oldId)，端口 $p" -ForegroundColor Yellow
            Write-Host "用户端：http://127.0.0.1:$p/"
            Write-Host "管理控制台：http://127.0.0.1:$p/console/"
            if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$p/" }
            exit 0
        }
    }
}

# ---------------------------------------------------------------- 5. 端口占用
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    $owner = (Get-Process -Id $busy.OwningProcess -ErrorAction SilentlyContinue).ProcessName
    Fail "端口 $Port 已被占用（$owner）。换端口：start.bat -Port 9200"
}

# ---------------------------------------------------------------- 6. 启动
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = ""
$env:PYTHONHOME = ""
$env:WORKBENCH_SERVE_FRONTEND = "1"   # 单进程：API + 用户前端 + 管理控制台
$outLog = Join-Path $root "data\logs\start-$Port.out"
$errLog = Join-Path $root "data\logs\start-$Port.err"

if ($Foreground) {
    Write-Host ""
    Write-Host "前台运行（Ctrl+C 停止）：http://127.0.0.1:$Port/" -ForegroundColor Yellow
    if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port/" }
    & $py (Join-Path $root "run.py") --host $HostAddr --port $Port
    exit $LASTEXITCODE
}

Write-Step "后台启动（不占窗口）"
$proc = Start-Process -FilePath $pyw `
    -ArgumentList @((Join-Path $root "run.py"), "--host", $HostAddr, "--port", "$Port") `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $outLog -RedirectStandardError $errLog
@{ pid = $proc.Id; port = $Port; started = (Get-Date).ToString("s") } | ConvertTo-Json -Compress | Set-Content $pidFile
Set-Content (Join-Path $root "data\workbench.port") $Port

$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 700
    try {
        $h = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
        if ($h.status -eq "ok") { $ok = $true; break }
    } catch {}
    if (-not (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) { break }
}

if (-not $ok) {
    Write-Host ""
    Write-Host "[失败] 后端没有起来，最近日志：" -ForegroundColor Red
    if (Test-Path $errLog) { Get-Content $errLog -Tail 12 }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    exit 1
}

# LAN IP
$lan = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and $_.PrefixOrigin -ne "WellKnown" } |
    Select-Object -First 1 -ExpandProperty IPAddress
if (-not $lan) {
    $lan = (ipconfig | Select-String "IPv4" | Select-Object -First 1) -replace ".*: ", ""
}

Write-Host ""
Write-Host "启动成功 (PID $($proc.Id))" -ForegroundColor Green
Write-Host "  用户端     http://127.0.0.1:$Port/"
Write-Host "  管理控制台 http://127.0.0.1:$Port/console/"
if ($lan) { Write-Host "  局域网     http://$lan`:$Port/" }
Write-Host "  日志       data\logs\app.log"
Write-Host "  停止       stop.bat    （或 stop.ps1）"
Write-Host ""
Write-Host "首次使用：打开用户端初始化管理员并登录；之后可自行注册，管理员从控制台管理用户与模型。" -ForegroundColor Yellow

if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port/" }
