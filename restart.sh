#!/usr/bin/env bash
# 重启工作台（Linux / macOS）
cd "$(dirname "$0")"
bash stop.sh
exec bash start.sh "$@"
