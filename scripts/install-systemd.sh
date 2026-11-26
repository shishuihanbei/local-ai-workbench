#!/usr/bin/env bash
# 安装为 systemd 服务。用法：
#   sudo bash scripts/install-systemd.sh [项目目录] [运行用户]
set -euo pipefail

APP_DIR="${1:-/opt/local-ai-workbench}"
APP_USER="${2:-${SUDO_USER:-workbench}}"
SERVICE="/etc/systemd/system/local-ai-workbench.service"

if [ "$(id -u)" -ne 0 ]; then
  echo "请用 sudo 运行：sudo bash scripts/install-systemd.sh $APP_DIR $APP_USER"
  exit 1
fi

if [ ! -f "$APP_DIR/run.py" ]; then
  echo "[失败] $APP_DIR 下没有 run.py，请先放好项目。"
  exit 1
fi

PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)
PY
    then PY="$cand"; break; fi
  fi
done
if [ -z "$PY" ]; then
  echo "[失败] 需要 Python 3.10 或更高。"
  exit 1
fi
PYVER="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
case "$PYVER" in
  3.10|3.11|3.12) ;;
  *) echo "[提示] Python $PYVER 可用，但图片/扫描件 OCR 组件只支持 3.10–3.12，需要 OCR 请换 3.12。" ;;
esac

if ! id "$APP_USER" >/dev/null 2>&1; then
  echo "==> 创建用户 $APP_USER"
  useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
fi

echo "==> 目录与权限"
mkdir -p "$APP_DIR/data" "$APP_DIR/models" "$APP_DIR/llama"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "==> 创建虚拟环境"
if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
  runuser -u "$APP_USER" -- "$PY" -m venv "$APP_DIR/.venv"
fi

echo "==> 安装依赖"
runuser -u "$APP_USER" -- "$APP_DIR/.venv/bin/pip" install --upgrade pip --disable-pip-version-check -q
runuser -u "$APP_USER" -- "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" --disable-pip-version-check

echo "==> 写入 systemd 服务"
sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__APP_USER__|$APP_USER|g" \
  "$APP_DIR/deploy/local-ai-workbench.service" > "$SERVICE"

systemctl daemon-reload
systemctl enable --now local-ai-workbench
sleep 2
systemctl --no-pager status local-ai-workbench || true

cat <<EOF

安装完成。

  用户端    http://127.0.0.1:9100/
  控制台    http://127.0.0.1:9100/console/
  日志      journalctl -u local-ai-workbench -f
  停止      sudo systemctl stop local-ai-workbench
  重启      sudo systemctl restart local-ai-workbench

EOF
