"""Windows control panel for the mobile site and its outbound HTTPS tunnel."""
from __future__ import annotations

import argparse
import json
import os
import queue
import re
import secrets
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from downloader import DATA, Cancelled, DownloadError, login_browser
from web_server import Jobs, create_app, load_access


def resource_path(relative):
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / relative


class RemoteApp:
    def __init__(self, root, local_only=False):
        self.root, self.local_only = root, local_only
        self.events = queue.Queue()
        self.process = None
        self.server = None
        self.jobs = None
        self.closed = False
        self.login_cancel = threading.Event()
        self.login_thread = None
        self.access = load_access()
        self.password = tk.StringVar(value=self.access["password"])
        self.address = tk.StringVar(value="正在准备远程连接…")
        self.status = tk.StringVar(value="正在启动本地服务")
        root.title("抖音下载 · 手机远程版")
        root.geometry("800x800")
        root.minsize(740, 760)
        root.configure(bg="#0c171b")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#0c171b")
        style.configure("TLabel", background="#0c171b", foreground="#edf0eb", font=("Microsoft YaHei UI", 10))
        style.configure("TButton", background="#293e43", foreground="#edf0eb", padding=(12, 9), font=("Microsoft YaHei UI", 10))
        style.map("TButton", background=[("active", "#3a535a")])
        style.configure("TEntry", fieldbackground="#15262b", foreground="#edf0eb", padding=10)
        frame = ttk.Frame(root, padding=28)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="手机也能下载抖音视频", font=("Microsoft YaHei UI", 23, "bold")).pack(anchor="w")
        ttk.Label(frame, text="手机用流量也能访问 · 保持本窗口运行", foreground="#a6b8bc").pack(anchor="w", pady=(5, 22))
        ttk.Label(frame, text="手机访问网址", foreground="#c8ef94").pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(8, 16))
        ttk.Entry(row, textvariable=self.address, state="readonly", font=("Segoe UI", 11)).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="复制网址", command=lambda: self.copy(self.address.get())).pack(side="left", padx=(8, 0))
        ttk.Label(frame, text="访问密码（在手机网页输入）", foreground="#c8ef94").pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(8, 16))
        self.password_entry = ttk.Entry(row, textvariable=self.password, state="readonly", show="●", font=("Segoe UI", 11))
        self.password_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="显示 / 隐藏", command=self.toggle_password).pack(side="left", padx=8)
        ttk.Button(row, text="复制密码", command=lambda: self.copy(self.password.get())).pack(side="left")
        middle = ttk.Frame(frame)
        middle.pack(fill="x")
        self.qr_label = ttk.Label(middle, text="连接成功后会显示二维码", anchor="center")
        self.qr_label.pack(side="left", padx=(0, 22), pady=4)
        steps = ttk.Frame(middle)
        steps.pack(side="left", fill="both", expand=True, pady=8)
        ttk.Label(steps, text="01  手机扫码打开网页\n\n02  输入上方访问密码\n\n03  粘贴抖音链接并解析\n\n04  直接下载到手机", font=("Microsoft YaHei UI", 11)).pack(anchor="w")
        ttk.Label(frame, textvariable=self.status, foreground="#c8ef94", wraplength=710).pack(anchor="w", pady=(16, 8))
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=8)
        ttk.Button(row, text="电脑打开网页", command=self.open_site).pack(side="left")
        self.login_btn = ttk.Button(row, text="登录抖音 / 完成验证", command=self.login)
        self.login_btn.pack(side="left", padx=8)
        ttk.Label(frame, text="仅解析地址；访客设备直连视频源站，电脑不下载、不转发视频。", foreground="#c8ef94", wraplength=710).pack(anchor="w", pady=8)
        self.logs = tk.Text(frame, height=5, bg="#15262b", fg="#a6b8bc", relief="flat", font=("Microsoft YaHei UI", 9), wrap="word", state="disabled", padx=10, pady=10)
        self.logs.pack(fill="both", expand=True, pady=(4, 12))
        ttk.Label(frame, text="网址为临时地址，重新连接后可能变化。关闭窗口即停止远程访问。\n二维码只包含网址；请单独保管密码。登录和验证码需在电脑完成。", foreground="#748d94", font=("Microsoft YaHei UI", 9), wraplength=710).pack(anchor="w")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)
        root.after(150, self.start)

    def copy(self, value):
        if not value.startswith("正在"):
            self.root.clipboard_clear()
            self.root.clipboard_append(value)
            self.root.update()

    def toggle_password(self):
        self.password_entry.configure(show="" if self.password_entry.cget("show") else "●")

    def open_site(self):
        if self.server:
            webbrowser.open(f"http://127.0.0.1:{self.server.effective_port}")

    def log(self, value):
        self.events.put(("log", str(value)))

    def start(self):
        from waitress import create_server
        try:
            self.jobs = Jobs(on_log=self.log)
            app = create_app(self.jobs, self.password.get(), resource_path("web"))
            # Fixed loopback port avoids exposing the password gate on the LAN.
            self.server = create_server(app, host="127.0.0.1", port=7860, threads=8,
                                        max_request_body_size=16384, channel_timeout=60,
                                        outbuf_high_watermark=128 * 1024, outbuf_overflow=1024 * 1024,
                                        clear_untrusted_proxy_headers=False)
            threading.Thread(target=self.server.run, daemon=True).start()
            self.status.set("本地网页已启动，正在连接外网…")
            if self.local_only:
                self.set_address("http://127.0.0.1:7860")
                self.status.set("本地测试模式：尚未建立远程连接")
            else:
                threading.Thread(target=self.tunnel, daemon=True).start()
        except Exception as exc:
            self.status.set("启动失败：本地端口可能已被占用，请关闭先前的远程版。")
            self.log(str(exc))

    def tunnel(self):
        tool = resource_path("tools/cloudflared.exe")
        if not tool.exists():
            self.events.put(("status", "缺少远程连接组件，请运行“准备远程版.ps1”后重试。"))
            return
        config = DATA / "remote-tunnel.yml"
        config.write_text("no-autoupdate: true\n", "utf-8")
        args = [str(tool), "tunnel", "--config", str(config), "--no-autoupdate", "--protocol", "http2",
                "--url", "http://127.0.0.1:7860", "--metrics", "127.0.0.1:0"]
        try:
            self.process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            text=True, encoding="utf-8", errors="replace",
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            # The URL and diagnostic lines are local control-panel state, never public assets.
            for line in self.process.stdout:
                if self.closed:
                    break
                match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
                if match:
                    self.events.put(("address", match[0]))
                if "Registered tunnel connection" in line:
                    self.events.put(("status", "远程连接已就绪 · 手机可使用流量扫码访问"))
                if "ERR" in line:
                    self.log("远程连接重试中，请检查电脑网络。")
            if not self.closed:
                self.events.put(("status", "远程连接已断开，请关闭并重新打开远程版。"))
        except Exception as exc:
            self.events.put(("status", "远程连接失败；本地网页仍可使用。请检查网络后重新启动。"))
            self.log(type(exc).__name__)

    def set_address(self, url):
        import qrcode
        from PIL import ImageTk
        self.address.set(url)
        (DATA / "remote-state.json").write_text(json.dumps({"url": url, "pid": os.getpid()}, ensure_ascii=False), "utf-8")
        qr = qrcode.QRCode(box_size=5, border=3)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#102126", back_color="#edf4e7").convert("RGB")
        img = img.resize((205, 205))
        self.qr_image = ImageTk.PhotoImage(img)
        self.qr_label.configure(image=self.qr_image, text="")

    def login(self):
        if not self.jobs or (self.login_thread and self.login_thread.is_alive()):
            return
        self.login_btn.configure(state="disabled")
        self.login_cancel.clear()
        def worker():
            try:
                self.log("正在等待当前下载任务完成，再打开登录浏览器…")
                with self.jobs.browser_lock:
                    if not self.closed:
                        login_browser(self.log, self.login_cancel)
                self.log("登录浏览器已关闭，可以在手机上重新提交下载。")
            except Exception as exc:
                self.log(str(exc) if isinstance(exc, DownloadError) else "登录浏览器启动失败，请重试。")
            finally:
                self.events.put(("login-done", None))
        self.login_thread = threading.Thread(target=worker, daemon=True)
        self.login_thread.start()

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "address":
                    self.set_address(value)
                elif kind == "status":
                    self.status.set(value)
                elif kind == "login-done":
                    self.login_btn.configure(state="normal")
                elif kind == "log":
                    self.logs.configure(state="normal")
                    self.logs.insert("end", time.strftime("%H:%M:%S") + "  " + value + "\n")
                    self.logs.see("end")
                    self.logs.configure(state="disabled")
        except queue.Empty:
            pass
        if not self.closed:
            self.root.after(150, self.poll)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.login_cancel.set()
        if self.jobs:
            self.jobs.stop()
        if self.process and self.process.poll() is None:
            self.process.terminate()
        if self.server:
            self.server.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    panel = RemoteApp(root, local_only=args.local_only or args.smoke_test)
    if args.smoke_test:
        root.after(2500, panel.close)
    root.mainloop()


if __name__ == "__main__":
    main()
