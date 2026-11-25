#!/usr/bin/env bash
# 停止工作台（Linux / macOS）
cd "$(dirname "$0")"
PID_FILE="data/workbench.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "未找到 PID 文件，可能不是通过 ./start.sh 启动的。"
  exit 0
fi

PID=$(cat "$PID_FILE" 2>/dev/null || true)
if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
  kill "$PID" 2>/dev/null || true
  for i in $(seq 1 10); do
    kill -0 "$PID" 2>/dev/null || break
    sleep 0.3
  done
  kill -9 "$PID" 2>/dev/null || true
  echo "已停止 (PID $PID)"
else
  echo "进程不存在（PID $PID）"
fi

rm -f "$PID_FILE" data/workbench.port
