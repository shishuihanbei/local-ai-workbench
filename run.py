#!/usr/bin/env python
"""启动入口：python run.py [--host 0.0.0.0] [--port 9000] [--reload]"""
from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn  # noqa: E402

from backend.config import load_config  # noqa: E402


def main() -> None:
    cfg = load_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=cfg.get("host", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(cfg.get("port", 9000)))
    ap.add_argument("--reload", action="store_true")
    ap.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    args = ap.parse_args()
    # 让内网穿透等运行期功能拿到真实监听端口（start 脚本可能用 --port 覆盖配置默认值）
    os.environ["WORKBENCH_PORT"] = str(args.port)
    if args.open:
        webbrowser.open(f"http://127.0.0.1:{args.port}")
    uvicorn.run("backend.main:app", host=args.host, port=args.port,
                reload=args.reload, log_level=cfg.get("log_level", "info").lower(),
                access_log=False)


if __name__ == "__main__":
    main()
