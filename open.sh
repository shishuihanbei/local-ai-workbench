#!/usr/bin/env bash
# AI 工作台桌面入口（Linux / macOS）：服务没起就静默拉起，再按配置打开前台或后台。
# 用法：open.sh [front|console]
set -u

MODE="${1:-console}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3 || true)"
fi
if [ -z "$PY" ]; then
  PY="$(command -v python || true)"
fi

BASE=""
if [ -n "$PY" ]; then
  BASE="$("$PY" - "$ROOT" <<'PY'
import json, os, sys
root = sys.argv[1]
cfg = {}
try:
    with open(os.path.join(root, "data", "config.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
except Exception:
    pass
port = int(cfg.get("port") or 9100)
mode = str(cfg.get("shortcut_mode") or "local")
ip = str(cfg.get("shortcut_lan_ip") or "").strip()
if mode == "lan" and not ip:
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = ""
if mode == "lan" and ip:
    print(f"http://{ip}:{port}")
    raise SystemExit
if mode == "custom":
    u = str(cfg.get("shortcut_custom_url") or "").strip().rstrip("/")
    if u.startswith(("http://", "https://")):
        print(u)
        raise SystemExit
print(f"http://127.0.0.1:{port}")
PY
)"
fi

PORT="$(printf '%s' "$BASE" | sed -n 's#.*:\([0-9][0-9]*\)$#\1#p')"
[ -n "$PORT" ] || PORT=9100
LOCAL="http://127.0.0.1:$PORT"
if [ -z "$BASE" ]; then BASE="$LOCAL"; fi
if [ "$MODE" = "front" ]; then URL="$BASE/"; else URL="$BASE/console/"; fi

up() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsS --max-time 3 "$LOCAL/api/health" >/dev/null 2>&1
  else
    return 1
  fi
}

if ! up; then
  START="$ROOT/start.sh"
  if [ -x "$START" ] || [ -f "$START" ]; then
    ( cd "$ROOT" && PORT="$PORT" nohup ./start.sh >/dev/null 2>&1 & )
    for _ in $(seq 1 45); do
      sleep 0.7
      if up; then break; fi
    done
  fi
fi

if command -v xdg-open >/dev/null 2>&1; then
  ( cd "$ROOT" && xdg-open "$URL" >/dev/null 2>&1 & )
elif command -v open >/dev/null 2>&1; then
  ( cd "$ROOT" && open "$URL" >/dev/null 2>&1 & )
fi
