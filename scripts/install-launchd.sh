#!/bin/bash
# macOS 开机自启安装。用法：bash scripts/install-launchd.sh [项目目录]
set -euo pipefail

APP_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
PLIST="$HOME/Library/LaunchAgents/com.local-ai-workbench.plist"
LABEL="com.local-ai-workbench"

if [ ! -f "$APP_DIR/run.py" ]; then
  echo "[失败] $APP_DIR 下没有 run.py"
  exit 1
fi

PY=""
for cand in python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
  echo "[失败] 没找到 Python 3.10+，先 brew install python@3.12"
  exit 1
fi

mkdir -p "$APP_DIR/data/logs" "$APP_DIR/data/uploads" "$APP_DIR/models" "$APP_DIR/llama"
if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
  echo "==> 创建虚拟环境"
  "$PY" -m venv "$APP_DIR/.venv"
fi

echo "==> 安装依赖"
"$APP_DIR/.venv/bin/pip" install --upgrade pip --disable-pip-version-check -q
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" --disable-pip-version-check

mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__APP_DIR__|$APP_DIR|g" "$APP_DIR/deploy/com.local-ai-workbench.plist" > "$PLIST"
plutil -lint "$PLIST" >/dev/null

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

cat <<EOF

已安装并启动。

  用户端    http://127.0.0.1:9100/
  控制台    http://127.0.0.1:9100/console/
  日志      $APP_DIR/data/logs/launchd.err
  停止      launchctl unload "$PLIST"
  启动      launchctl load "$PLIST"

EOF
