#!/usr/bin/env bash
# 本地一键启动（Linux / macOS）：检测 Python → venv → 依赖 → 后台启动
set -e
cd "$(dirname "$0")"

PORT="${PORT:-9100}"
HOST="${HOST:-0.0.0.0}"
mkdir -p data/logs data/audio data/uploads

echo
echo "本地 AI 工作台 · 一键启动"
echo "目录：$(pwd)"
echo

PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)
PY
    then PY="$cand"; break; fi
  fi
done
if [ -z "$PY" ]; then
  echo "[失败] 没找到 Python 3.10+，请先安装："
  echo "  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
  echo "  macOS: brew install python@3.12"
  exit 1
fi

if [ -x ".venv/bin/python" ]; then
  echo "==> 使用已有虚拟环境 .venv"
else
  echo "==> 使用 $PY 创建虚拟环境 .venv"
  "$PY" -m venv .venv
fi

VPY=".venv/bin/python"

echo "==> 检查依赖"
if ! "$VPY" -c "import fastapi, uvicorn, aiosqlite, httpx, psutil, edge_tts, mutagen, cryptography" >/dev/null 2>&1; then
  echo "==> 首次安装依赖（约 1-3 分钟）"
  INDEX="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
  "$VPY" -m pip install --upgrade pip --disable-pip-version-check -q || true
  if ! "$VPY" -m pip install -r requirements.txt --disable-pip-version-check -i "$INDEX"; then
    echo "==> 镜像失败，改用官方 PyPI"
    "$VPY" -m pip install -r requirements.txt --disable-pip-version-check
  fi
fi

# 从别的机器拷来时，config.json 里可能是原机器的路径；不存在就改到包内目录
"$VPY" - <<'PY' || true
import sys
sys.path.insert(0, ".")
from pathlib import Path
from backend.config import load_config, save_config
cfg = load_config()
changed = []
if not Path(cfg["models_dir"]).exists():
    cfg["models_dir"] = str(Path.cwd() / "models"); changed.append("models_dir")
if not Path(cfg["llama_dir"]).exists():
    cfg["llama_dir"] = str(Path.cwd() / "platforms" / "llama.cpp"); changed.append("llama_dir")
if changed:
    save_config(cfg)
    print("已把不存在的目录改到包内：" + ", ".join(changed))
PY

# 已有实例
if [ -f data/workbench.pid ]; then
  OLD=$(cat data/workbench.pid 2>/dev/null || true)
  if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null; then
    OLD_PORT=$(cat data/workbench.port 2>/dev/null || echo "$PORT")
    echo "已在运行 (PID $OLD)，端口 $OLD_PORT"
    echo "管理控制台：http://127.0.0.1:$OLD_PORT/console/"
    exit 0
  fi
fi

if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":$PORT "; then
  echo "[失败] 端口 $PORT 已被占用，可换端口：PORT=9200 ./start.sh"
  exit 1
fi

export PYTHONUTF8=1
export WORKBENCH_SERVE_FRONTEND=1
OUT="data/logs/start-$PORT.out"
ERR="data/logs/start-$PORT.err"

echo "==> 后台启动"
nohup "$VPY" run.py --host "$HOST" --port "$PORT" >"$OUT" 2>"$ERR" &
PID=$!
echo "$PID" > data/workbench.pid
echo "$PORT" > data/workbench.port

OK=0
for i in $(seq 1 30); do
  sleep 0.7
  if "$VPY" - "$PORT" <<'PY' >/dev/null 2>&1
import json, sys, urllib.request
port = sys.argv[1]
with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
    raise SystemExit(0 if json.load(r).get("status") == "ok" else 1)
PY
  then OK=1; break; fi
  if ! kill -0 "$PID" 2>/dev/null; then break; fi
done

if [ "$OK" != "1" ]; then
  echo "[失败] 后端没有起来，最近日志："
  tail -n 15 "$ERR" 2>/dev/null || true
  rm -f data/workbench.pid
  exit 1
fi

LAN=$( (hostname -I 2>/dev/null || true) | awk '{print $1}' )
echo
echo "启动成功 (PID $PID)"
echo "  用户端     http://127.0.0.1:$PORT/"
echo "  管理控制台 http://127.0.0.1:$PORT/console/"
[ -n "$LAN" ] && echo "  局域网     http://$LAN:$PORT/" || true
echo "  日志       data/logs/app.log"
echo "  停止       ./stop.sh"
echo
echo "首次使用：打开用户端初始化管理员并登录；之后可自行注册，管理员从控制台管理用户与模型。"
