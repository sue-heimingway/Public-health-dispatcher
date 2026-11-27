"""GovOS · 启动入口

    python run.py                 # 本机演示，自动开浏览器
    python run.py --lan           # 局域网可访问
    python run.py --port 8781     # 换端口
    python run.py --no-browser
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    if sys.version_info < (3, 10):
        print(f"[需要 Python 3.10+] 当前 {sys.version.split()[0]}")
        raise SystemExit(1)

    parser = argparse.ArgumentParser(description="GovOS 社会治理诉求分流中枢")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--lan", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.lan:
        os.environ["GOV_HOST"] = "0.0.0.0"

    from app.server import serve  # noqa: E402

    serve(args.host, args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
