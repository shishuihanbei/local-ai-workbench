#!/usr/bin/env bash
# AI 工作台桌面图标入口（Linux / macOS）：服务没在跑就先静默拉起来，再打开前台页面。
set -u
root="$(cd "$(dirname "$0")" && pwd)"
cd "$root"

port="${WORKBENCH_PORT:-}"
if [ -z "${port}" ] && [ -f "data/config.json" ]; then
  py=".venv/bin/python"
  [ -x "$py" ] || py="python3"
  port="$("$py" -c 'import json;print(json.load(open("data/config.json")).get("port",""))' 2>/dev/null || true)"
fi
port="${port:-9100}"
url="http://127.0.0.1:${port}/"

up() { curl -fsS "http://127.0.0.1:${port}/api/health" >/dev/null 2>&1; }

if ! up; then
  PORT="${port}" nohup ./start.sh >/dev/null 2>&1 &
  for _ in $(seq 1 45); do
    sleep 0.7
    up && break
  done
fi

if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "${url}" >/dev/null 2>&1 &
else
  open "${url}" >/dev/null 2>&1 || true
fi
