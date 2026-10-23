#!/usr/bin/env bash
# 在 Linux 上准备并启动网页版（对应 Windows 的 安装依赖.ps1 + 启动手机远程版）。
# 用法：./run_linux.sh [--port 8080] [--with-tunnel]
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if [ ! -x .venv/bin/python ]; then
    "$PYTHON_BIN" -m venv .venv
fi
.venv/bin/python -m pip install -q -r requirements.txt

# 解析抖音的第三级回退需要一个真实浏览器；服务器上用 Playwright 的 Chromium（无头）。
if [ ! -d "${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}" ] || \
   ! ls "${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}" 2>/dev/null | grep -q chromium; then
    .venv/bin/python -m playwright install chromium
fi

PORT=7860
WITH_TUNNEL=0
while [ $# -gt 0 ]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --with-tunnel) WITH_TUNNEL=1; shift ;;
        *) echo "未知参数：$1" >&2; exit 2 ;;
    esac
done

if [ "$WITH_TUNNEL" = "1" ]; then
    CLOUDFLARED="${CLOUDFLARED:-cloudflared}"
    command -v "$CLOUDFLARED" >/dev/null 2>&1 || {
        echo "找不到 cloudflared，请先从 https://github.com/cloudflare/cloudflared/releases 下载 Linux 版本。" >&2
        exit 1
    }
    .venv/bin/python linux_server.py --port "$PORT" &
    SERVER_PID=$!
    trap 'kill $SERVER_PID 2>/dev/null || true' EXIT
    sleep 2
    "$CLOUDFLARED" tunnel --no-autoupdate --protocol http2 --url "http://127.0.0.1:$PORT"
else
    exec .venv/bin/python linux_server.py --port "$PORT"
fi
