#!/usr/bin/env bash
# 整机卸载（Linux / macOS）：和 start.sh / stop.sh 同一个位置、同一个用法。
#
#   ./uninstall.sh                 交互确认后删掉整个工作台
#   ./uninstall.sh --keep-models   保留 models/ 与各引擎自己的 models
#   ./uninstall.sh --keep-data     连 data/（账号、知识库、日志、配置）一起保留
#   ./uninstall.sh --dry-run       只列清单，不动手
#   ./uninstall.sh --yes           跳过手输 UNINSTALL（给脚本调用）
#
# 做的事：停 systemd/cron/launchd 自启 → 停服务 → 关掉工作台拉起的引擎进程
#         → 删桌面图标 → 删目录。不碰系统里另行安装的 Ollama / LM Studio。
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
YES=0; KEEP_DATA=0; KEEP_MODELS=0; DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y) YES=1 ;;
    --keep-data) KEEP_DATA=1 ;;
    --keep-models) KEEP_MODELS=1 ;;
    --dry-run) DRY_RUN=1 ;;
    *) echo "未知参数：$arg"; exit 2 ;;
  esac
done
cd "$ROOT" || exit 1

echo ""
echo "  本地 AI 工作台 · 整机卸载"
echo "  工作台目录：$ROOT"
echo ""
echo "  会删：程序本体、控制台前端、虚拟环境、platforms、临时解压、日志"
if [ "$KEEP_MODELS" = "1" ]; then echo "  保留：models/ 与各引擎的 models"; else echo "  会删：models/ 与各引擎的 models（想留着加 --keep-models）"; fi
if [ "$KEEP_DATA" = "1" ]; then echo "  保留：data/（账号、知识库、日志、配置）"; else echo "  会删：data/（账户、知识库、日志；想留着加 --keep-data）"; fi
echo "  不碰：系统里单独装的 Ollama / LM Studio"
echo ""

if [ "$DRY_RUN" = "1" ]; then
  echo "  --dry-run：只列清单"
  for f in "$ROOT"/* "$ROOT"/.[!.]*; do
    [ -e "$f" ] || continue
    base="$(basename "$f")"
    [ "$KEEP_DATA" = "1" ] && [ "$base" = "data" ] && { echo "    保留 $f"; continue; }
    [ "$KEEP_MODELS" = "1" ] && [ "$base" = "models" ] && { echo "    保留 $f"; continue; }
    echo "    删除 $f"
  done
  echo ""
  exit 0
fi

if [ "$YES" != "1" ]; then
  printf "  这一步不可恢复。确认请输入 UNINSTALL（直接回车取消）："
  read -r ANSWER
  if [ "$ANSWER" != "UNINSTALL" ]; then echo "  已取消，什么都没删。"; exit 0; fi
fi

echo ""
echo "  [1/4] 撤掉开机自启"
if command -v systemctl >/dev/null 2>&1; then
  systemctl --user disable --now local-ai-workbench.service >/dev/null 2>&1
  systemctl disable --now local-ai-workbench.service >/dev/null 2>&1
fi
if [ -f "$HOME/.config/systemd/user/local-ai-workbench.service" ]; then
  rm -f "$HOME/.config/systemd/user/local-ai-workbench.service"; echo "    已删用户级 systemd 单元"
fi
if [ -f "/etc/systemd/system/local-ai-workbench.service" ]; then
  sudo rm -f "/etc/systemd/system/local-ai-workbench.service" && echo "    已删系统级 systemd 单元"
fi
if command -v crontab >/dev/null 2>&1; then
  crontab -l 2>/dev/null | grep -v "local-ai-workbench autostart" | grep -v "run.py --port" | crontab - 2>/dev/null && echo "    已清 crontab 自启行"
fi
if [ -f "$HOME/Library/LaunchAgents/com.local-ai-workbench.plist" ]; then
  launchctl unload "$HOME/Library/LaunchAgents/com.local-ai-workbench.plist" >/dev/null 2>&1
  rm -f "$HOME/Library/LaunchAgents/com.local-ai-workbench.plist"; echo "    已删 LaunchAgent"
fi

echo "  [2/4] 停止服务与引擎进程"
if [ -x "$ROOT/stop.sh" ]; then "$ROOT/stop.sh" >/dev/null 2>&1; fi
sleep 2
# 只结束可执行文件位于工作台目录里的进程
ps -eo pid=,comm=,args= 2>/dev/null | while read -r pid comm args; do
  case "$args" in
    "$ROOT"/*|*"$ROOT"/run.py*|*"$ROOT"/platforms/*)
      echo "    结束 $comm (PID $pid)"
      kill -TERM "$pid" 2>/dev/null || true
      sleep 1
      kill -KILL "$pid" 2>/dev/null || true
      ;;
  esac
done

echo "  [3/4] 删桌面图标"
for dir in "$HOME/Desktop" "$HOME/桌面" "/usr/share/applications"; do
  [ -d "$dir" ] || continue
  find "$dir" -maxdepth 1 -name "*.desktop" 2>/dev/null | while read -r f; do
    if grep -qi "local-ai-workbench\|$ROOT" "$f" 2>/dev/null; then rm -f "$f"; echo "    已删 $f"; fi
  done
done

echo "  [4/4] 删目录"
fail=""
rm_child() {
  if ! rm -rf "$1" 2>/dev/null; then fail="$fail $1"; fi
}
for f in "$ROOT"/* "$ROOT"/.[!.]*; do
  [ -e "$f" ] || continue
  base="$(basename "$f")"
  [ "$base" = "." ] && continue
  [ "$base" = ".." ] && continue
  [ "$KEEP_DATA" = "1" ] && [ "$base" = "data" ] && { echo "    保留 $f"; continue; }
  [ "$KEEP_MODELS" = "1" ] && [ "$base" = "models" ] && { echo "    保留 $f"; continue; }
  if [ "$base" = "platforms" ] && [ "$KEEP_MODELS" = "1" ]; then
    for p in "$f"/*; do
      [ -e "$p" ] || continue
      if [ -d "$p/models" ]; then
        find "$p" -mindepth 1 -maxdepth 1 ! -name models -exec rm -rf {} + 2>/dev/null
        echo "    保留 $p/models"
      else
        rm_child "$p"
      fi
    done
    continue
  fi
  rm_child "$f"
  echo "    已删 $f"
done

echo ""
if [ -n "$fail" ]; then
  echo "  以下内容没删掉（可能被占用），请手动删除："
  for x in $fail; do echo "    $x"; done
  exit 1
fi
if [ "$KEEP_DATA" = "1" ] || [ "$KEEP_MODELS" = "1" ]; then
  echo "  程序已删除；按参数保留的内容仍在 $ROOT"
else
  if rmdir "$ROOT" 2>/dev/null; then
    echo "  工作台已完全卸载，$ROOT 目录已删除。"
  else
    echo "  $ROOT 还有残留（脚本自身所在目录），手动 rm -rf \"$ROOT\" 即可。"
  fi
fi
echo ""
