#!/bin/bash
# macOS 双击启动：Finder 里双击本文件即可
set -e
cd "$(dirname "$0")"

if [ ! -x "start.sh" ]; then
  chmod +x start.sh
fi

./start.sh
open "http://127.0.0.1:${PORT:-9100}/" 2>/dev/null || true

echo
echo "如果浏览器没有自动打开，请手动访问 http://127.0.0.1:${PORT:-9100}/"
echo "按回车关闭这个窗口。"
read -r _
