# 整机卸载：和 start.ps1 / stop.ps1 一个位置、一个用法。
#
#   uninstall.bat                 交互确认后，删掉整个工作台（含控制台、引擎、虚拟环境）
#   uninstall.bat -KeepModels     保留 models\ 与各引擎自己的模型（Ollama、LM Studio 的 models）
#   uninstall.bat -KeepData       连 data\（账号、知识库、日志、配置）一起保留
#   uninstall.bat -DryRun         只列出会删什么，不动手
#   uninstall.bat -Yes            跳过手输 UNINSTALL（给脚本调用）
#
# 做的事：停服务 → 关掉工作台拉起的引擎进程 → 撤开机自启与桌面图标 → 删目录
# 不碰：系统里另行安装的 Ollama / LM Studio、用户放在工作台外面的东西
param(
    [switch]$Yes,
    [switch]$KeepData,
    [switch]$KeepModels,
    [switch]$DryRun
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

$PlatformsDir = Join-Path $Root "platforms"
$ModelsDir = Join-Path $Root "models"
$DataDir = Join-Path $Root "data"

function Say($text, $color = "Gray") { Write-Host $text -ForegroundColor $color }

Say ""
Say "  本地 AI 工作台 · 整机卸载" "Cyan"
Say "  工作台目录：$Root"
Say ""
Say "  会删：程序本体、控制台前端、.venv、platforms（各引擎 + 安装包缓存）、临时解压、日志"
if ($KeepModels) { Say "  保留：models\ 与各引擎的 models（你下载的模型）" "Green" }
else { Say "  会删：models\ 与各引擎的 models（模型文件；想留着请加 -KeepModels）" "Yellow" }
if ($KeepData) { Say "  保留：data\（账号、知识库、日志、配置）" "Green" }
else { Say "  会删：data\（账号、知识库、对话、日志；想留着请加 -KeepData）" "Yellow" }
Say "  不碰：系统里单独装的 Ollama / LM Studio，以及工作台目录以外的东西"
Say ""

# 要先列清单就到此为止
if ($DryRun) {
    Say "  -DryRun：只列清单，不执行。" "Cyan"
    Say ""
    Say "  将删除以下内容（保留项已排除）："
    Get-ChildItem -LiteralPath $Root -Force | ForEach-Object {
        if ($KeepData -and $_.Name -eq "data") { return }
        if ($KeepModels -and $_.Name -eq "models") { return }
        Say "    $($_.FullName)"
    }
    if (Test-Path -LiteralPath $PlatformsDir) {
        Get-ChildItem -LiteralPath $PlatformsDir -Force -Directory | ForEach-Object {
            if ($KeepModels -and (Test-Path -LiteralPath (Join-Path $_.FullName "models"))) {
                Say "    $($_.FullName)（只删程序，保留 models）"
            }
        }
    }
    Say ""
    exit 0
}

# 二次确认：必须手输 UNINSTALL，防止误双击
if (-not $Yes) {
    $answer = Read-Host "  这一步不可恢复。确认请输入 UNINSTALL（直接回车取消）"
    if ($answer -cne "UNINSTALL") {
        Say ""
        Say "  已取消，什么都没删。" "Green"
        Say ""
        exit 0
    }
}

Say ""
Say "  [1/5] 停止服务" "Cyan"
$stopScript = Join-Path $Root "stop.ps1"
if (Test-Path -LiteralPath $stopScript) {
    try { & $stopScript 2>$null | Out-Null } catch { }
}
Start-Sleep -Seconds 2

Say "  [2/5] 关掉工作台拉起的引擎进程" "Cyan"
# 只杀可执行文件在工作台目录里的进程，系统里装的 Ollama / LM Studio 不碰
try {
    $procs = Get-CimInstance Win32_Process -ErrorAction Stop |
        Where-Object {
            $_.ExecutablePath -and (
                ($_.ExecutablePath -like "$PlatformsDir*") -or
                ($_.Name -eq "llama-server.exe" -and $_.ExecutablePath -like "$Root*")
            )
        }
    foreach ($p in $procs) {
        Say "      结束 $($p.Name) (PID $($p.ProcessId))"
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
} catch { }
# 工作台自己的 Python 进程（run.py）兜底
try {
    $pys = Get-CimInstance Win32_Process -ErrorAction Stop |
        Where-Object { $_.Name -like "python*" -and $_.CommandLine -and $_.CommandLine -like "*$Root*run.py*" }
    foreach ($p in $pys) {
        Say "      结束 $($p.Name) (PID $($p.ProcessId))"
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
} catch { }

Say "  [3/5] 撤掉开机自启" "Cyan"
$startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
foreach ($f in @("LocalAI-Workbench.cmd", "LocalAI-Workbench.lnk")) {
    $p = Join-Path $startup $f
    if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue; Say "      已删 $p" }
}
try {
    $run = Get-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -ErrorAction Stop
    $run.PSObject.Properties | Where-Object {
        $_.Name -notlike "PS*" -and $_.Value -and ($_.Value -like "*$Root*")
    } | ForEach-Object {
        Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name $_.Name -ErrorAction SilentlyContinue
        Say "      已删注册表自启项 $($_.Name)"
    }
} catch { }

Say "  [4/5] 删桌面与开始菜单图标" "Cyan"
$iconDirs = @(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) ""),
    (Join-Path $env:PUBLIC "Desktop"),
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs")
)
$sh = $null
try { $sh = New-Object -ComObject WScript.Shell } catch { }
foreach ($dir in $iconDirs) {
    if (-not (Test-Path -LiteralPath $dir)) { continue }
    Get-ChildItem -LiteralPath $dir -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in @(".lnk", ".url", ".webloc", ".desktop") } |
        ForEach-Object {
            $icon = $_
            $hit = $false
            if ($icon.Extension -eq ".lnk" -and $sh) {
                # 只删指回本工作台目录的快捷方式，别的图标不动
                try {
                    $target = $sh.CreateShortcut($icon.FullName).TargetPath
                    if ($target -and $target -like "$Root*") { $hit = $true }
                } catch { }
            } elseif ($icon.Extension -in @(".url", ".webloc", ".desktop")) {
                try {
                    $text = Get-Content -LiteralPath $icon.FullName -Raw -ErrorAction Stop
                    if ($text -and $text -like "*$Root*") { $hit = $true }
                } catch { }
            }
            if ($hit) {
                Remove-Item -LiteralPath $icon.FullName -Force -ErrorAction SilentlyContinue
                Say "      已删 $($icon.FullName)"
            }
        }
}

Say "  [5/5] 删目录" "Cyan"
$fail = @()
# 卸载脚本自己不能一边跑一边被删，留给最后延时清理
$selfNames = @("uninstall.ps1", "uninstall.bat", "uninstall.sh")
Get-ChildItem -LiteralPath $Root -Force | ForEach-Object {
    $name = $_.Name
    if ($name -in $selfNames) { return }
    if ($KeepData -and $name -eq "data") { Say "      保留 $($_.FullName)"; return }
    if ($KeepModels -and $name -eq "models") { Say "      保留 $($_.FullName)"; return }
    if ($name -eq "platforms" -and $KeepModels) {
        # platforms 下只保留各引擎的 models
        Get-ChildItem -LiteralPath $_.FullName -Force | ForEach-Object {
            $child = $_
            $modelsHere = Join-Path $child.FullName "models"
            if ($child.PSIsContainer -and (Test-Path -LiteralPath $modelsHere)) {
                Get-ChildItem -LiteralPath $child.FullName -Force |
                    Where-Object { $_.Name -ne "models" } |
                    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
                Say "      保留 $modelsHere"
            } else {
                Remove-Item -LiteralPath $child.FullName -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
        return
    }
    try {
        Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop
        Say "      已删 $($_.FullName)"
    } catch {
        $fail += $_.FullName
        Say "      删不掉（可能被占用）：$($_.FullName)" "Yellow"
    }
}

Say ""
Push-Location $env:TEMP
if ($KeepData -or $KeepModels) {
    Say "  程序已删除；按参数保留的内容仍在 $Root" "Green"
    Say "  想彻底清掉，把剩下的 models\ / data\ 手动删除即可。"
} else {
    Say "  程序已全部删除，只剩这一个卸载脚本所在的空目录。" "Green"
    Say "  目录和脚本会在退出后由 uninstall.bat 自动清掉（直接运行 ps1 时手动删掉即可）。"
}
Pop-Location
Say ""
Say "  浏览器里打开的页面会断开，属于正常。"
Say ""
if ($fail) { exit 1 } else { exit 0 }
