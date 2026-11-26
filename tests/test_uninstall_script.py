"""整机卸载：和 start.bat / stop.bat 同级的一键脚本，能把系统连同控制台一起删掉。"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_three_platforms_have_uninstall_entry():
    for name in ("uninstall.ps1", "uninstall.bat", "uninstall.sh"):
        assert (ROOT / name).is_file(), name


def test_bat_calls_ps1_then_cleans_itself():
    bat = _read("uninstall.bat")
    assert "uninstall.ps1" in bat
    assert "-ExecutionPolicy Bypass" in bat
    # 跑完把自己也删掉，不留半截脚本
    assert 'del "%~f0"' in bat or "del \"%~f0\"" in bat


def test_ps1_supports_keep_and_dry_run():
    ps1 = _read("uninstall.ps1")
    for flag in ("$KeepData", "$KeepModels", "$DryRun", "$Yes"):
        assert flag in ps1, flag
    # 手输确认，防误双击
    assert "UNINSTALL" in ps1
    assert "Read-Host" in ps1


def test_ps1_removes_service_autostart_and_icons():
    ps1 = _read("uninstall.ps1")
    assert "stop.ps1" in ps1                     # 先停服务
    assert "LocalAI-Workbench.cmd" in ps1        # 撤开机自启
    assert "Startup" in ps1
    assert 'Run"' in ps1 or "CurrentVersion\\Run" in ps1
    # 引擎进程只杀工作台目录里的，不碰系统安装的 Ollama / LM Studio
    assert "ExecutablePath" in ps1
    assert "Stop-Process" in ps1


def test_ps1_never_deletes_outside_workbench():
    ps1 = _read("uninstall.ps1")
    # 所有删除都基于脚本所在目录，且不出现 %LOCALAPPDATA% / ~/.ollama 这类系统路径
    assert "$Root = Split-Path -Parent $MyInvocation.MyCommand.Path" in ps1
    for bad in ("LOCALAPPDATA", ".ollama", ".lmstudio", ".cache"):
        assert bad not in ps1, bad


def test_sh_has_same_flags():
    sh = _read("uninstall.sh")
    assert "--keep-data" in sh and "--keep-models" in sh and "--dry-run" in sh
    assert "UNINSTALL" in sh
    assert "local-ai-workbench.service" in sh
    assert "com.local-ai-workbench.plist" in sh
    assert "local-ai-workbench autostart" in sh
