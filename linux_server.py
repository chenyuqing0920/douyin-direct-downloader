"""Headless Linux/macOS entry point for the direct-download web app.

The Windows control panel (remote_app.py) needs a desktop: Tkinter window,
cloudflared.exe and PowerShell helpers. A Linux server has none of those, so
this entry point runs the same Flask/Waitress web service directly:

    .venv/bin/python linux_server.py                # http://127.0.0.1:7860
    .venv/bin/python linux_server.py --port 8080

The access password comes from DOUYIN_ACCESS_PASSWORD when set, otherwise it
is generated once and stored in the data directory (see downloader.DATA),
exactly like the Windows version. It is printed to this process's console
only, so the operator can log in; it is never served over HTTP. Put a tunnel
or reverse proxy (e.g. cloudflared) in front of the loopback port to make the
page reachable from the internet, as the Windows version does.
"""
from __future__ import annotations

import argparse
import os
import signal
import sys

from downloader import DATA
from web_server import Jobs, create_app, load_access


def main():
    parser = argparse.ArgumentParser(description="随手存 · 抖音视频下载（Linux 网页服务）")
    parser.add_argument("--host", default="127.0.0.1",
                        help="监听地址，默认只监听本机 127.0.0.1，由隧道/反向代理对外")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()

    from waitress import create_server

    password = os.environ.get("DOUYIN_ACCESS_PASSWORD") or load_access()["password"]
    jobs = Jobs(on_log=lambda message: print(f"[jobs] {message}", flush=True))
    app = create_app(jobs, password)
    server = create_server(app, host=args.host, port=args.port, threads=8,
                           max_request_body_size=16384, channel_timeout=60,
                           outbuf_high_watermark=128 * 1024,
                           outbuf_overflow=1024 * 1024,
                           clear_untrusted_proxy_headers=False)

    def shutdown(signum, _frame):
        print(f"收到信号 {signum}，正在关闭服务…", flush=True)
        jobs.stop()
        server.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    print(f"数据目录：{DATA}", flush=True)
    print(f"网页服务已启动：http://{args.host}:{server.effective_port}", flush=True)
    print(f"访问密码（仅显示在本机控制台）：{password}", flush=True)
    try:
        server.run()
    finally:
        jobs.stop()


if __name__ == "__main__":
    main()
