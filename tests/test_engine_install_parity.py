"""四个引擎走同一套“检测 → 下载 → 安装 → 启动 → 探测”流程，目录与缓存口径一致。"""
from __future__ import annotations

from pathlib import Path

from backend.services import platform_deploy as pd
from backend.services import platform_store

ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_all_engines_use_the_same_deploy_entry():
    src = _src("backend/services/platform_deploy.py")
    for key in platform_store.MANAGED_ENGINES:
        assert f'"{key}"' in src
    for fn in ("_deploy_llama", "_deploy_ollama", "_deploy_lmstudio", "_deploy_vllm"):
        assert f"await {fn}(" in src, fn
    # 同一套按钮：一键部署 / 启动 / 已运行
    assert '"一键部署"' in src and '"启动"' in src and '"已运行"' in src


def test_no_system_temp_left_behind():
    """安装过程不再用 tempfile.mkdtemp 写系统 %TEMP%。"""
    for rel in ("backend/services/installer.py", "backend/services/platform_deploy.py"):
        src = _src(rel)
        assert "tempfile.mkdtemp" not in src, rel
        assert "mkdtemp" not in src, rel
    assert "platform_store.workbench_tmp" in _src("backend/services/installer.py")
    assert "platform_store.workbench_tmp" in _src("backend/services/platform_deploy.py")


def test_lmstudio_installs_inside_workbench():
    src = _src("backend/services/platform_deploy.py")
    assert "llmster.lmstudio.ai" in src
    assert '"bootstrap"' in src
    assert "LMS_NO_MODIFY_PATH" in src
    # 家目录指回工作台，避免写 ~/.lmstudio 与 %LOCALAPPDATA%
    assert "home=home" in src
    assert "def lmstudio_home(" in src


def test_vllm_has_its_own_venv_and_no_fake_windows_install():
    src = _src("backend/services/platform_deploy.py")
    assert "def vllm_python(" in src
    assert "vllm\\\\.venv" in src or "vllm" in src
    assert "不支持 Windows" in src or "not support Windows" in src
    assert "WSL2" in src and "vllm/vllm-openai" in src


def test_ollama_and_llama_download_caches_are_in_platforms():
    src = _src("backend/services/platform_deploy.py")
    assert 'download_dir(cfg, "lmstudio")' in src
    assert 'platform_store.download_dir' in src
    inst = _src("backend/services/installer.py")
    assert 'platform_store.download_dir' in inst


def test_usage_payload_for_every_engine():
    cfg = {"models_dir": str(ROOT / "models"), "upstream_base": "http://127.0.0.1:8080"}
    for key in ("llama.cpp", "ollama", "lmstudio", "vllm"):
        item = {
            "key": key,
            "healthy": True,
            "models": ["qwen2.5:7b"],
            "base_url": "http://127.0.0.1:11434" if key == "ollama" else "http://127.0.0.1:1234",
        }
        usage = pd.engine_usage(key, item, cfg)
        assert usage["api_base"].endswith("/v1"), key
        assert usage["chat_url"] == usage["api_base"] + "/chat/completions"
        assert usage["sample_model"] == "qwen2.5:7b"
        assert "curl" in usage["curl"] and "chat/completions" in usage["curl"]
        assert usage["frontend_auto"] is True
        assert usage["frontend_ready"] is True
        assert usage["frontend_count"] == 1
        assert len(usage["steps"]) >= 2


def test_usage_marks_not_ready_when_no_models():
    usage = pd.engine_usage("ollama", {"healthy": True, "models": [], "base_url": "http://127.0.0.1:11434"}, {})
    assert usage["frontend_ready"] is False
    assert usage["frontend_count"] == 0
    assert "你的模型" in usage["curl"]
