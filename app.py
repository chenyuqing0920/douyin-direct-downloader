from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from downloader import DATA, Cancelled, DownloadError, Resolver, download_video, extract_links, login_browser


class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.closing = False
        self.last_progress = 0
        root.title("抖音视频下载器 · 本地版")
        root.geometry("1000x860")
        root.minsize(850, 840)
        root.configure(bg="#111827")
        self.folder = tk.StringVar(value=str(Path.home() / "Downloads" / "抖音视频"))
        try:
            self.folder.set(json.loads((DATA / "settings.json").read_text("utf-8"))["folder"])
        except (OSError, ValueError, KeyError):
            pass
        self.status = tk.StringVar(value="准备就绪 · 粘贴分享链接即可开始")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#111827")
        style.configure("TLabel", background="#111827", foreground="#e5e7eb", font=("Microsoft YaHei UI", 10))
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(14, 9), background="#273449", foreground="#ffffff", borderwidth=0)
        style.map("TButton", background=[("active", "#374b66"), ("disabled", "#273449")], foreground=[("disabled", "#778396")])
        style.configure("Accent.TButton", background="#087f8c", foreground="white")
        style.map("Accent.TButton", background=[("active", "#0795a4"), ("disabled", "#273449")])
        style.configure("Treeview", background="#1b2536", fieldbackground="#1b2536", foreground="#e5e7eb", rowheight=34, font=("Microsoft YaHei UI", 9), borderwidth=0)
        style.configure("Treeview.Heading", background="#273449", foreground="#cbd5e1", font=("Microsoft YaHei UI", 9), padding=8)
        style.map("Treeview", background=[("selected", "#164e63")])
        style.configure("TEntry", fieldbackground="#1b2536", foreground="white", padding=8)
        style.configure("Horizontal.TProgressbar", troughcolor="#273449", background="#24c4cc", borderwidth=0)
        frame = ttk.Frame(root, padding=28)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="抖音视频下载", font=("Microsoft YaHei UI", 25, "bold")).pack(anchor="w")
        ttk.Label(frame, text="粘贴链接，保存到你的电脑。", foreground="#94a3b8").pack(anchor="w", pady=(3, 20))
        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Label(row, text="01  视频链接 / 分享文案", font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        self.paste_btn = ttk.Button(row, text="粘贴剪贴板", command=self.paste)
        self.paste_btn.pack(side="right")
        self.input = tk.Text(frame, height=4, bg="#1b2536", fg="#f1f5f9", insertbackground="#24c4cc", relief="flat", font=("Microsoft YaHei UI", 11), padx=14, pady=12, wrap="word", undo=True)
        self.input.pack(fill="x", pady=(8, 6))
        ttk.Label(frame, text="支持 v.douyin.com 短链接、完整视频链接；多条链接可一起粘贴。", foreground="#94a3b8", font=("Microsoft YaHei UI", 9)).pack(anchor="w")
        ttk.Label(frame, text="02  保存位置", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", pady=(18, 8))
        row = ttk.Frame(frame)
        row.pack(fill="x")
        self.folder_entry = ttk.Entry(row, textvariable=self.folder)
        self.folder_entry.pack(side="left", fill="x", expand=True)
        self.choose_btn = ttk.Button(row, text="更改位置", command=self.choose)
        self.choose_btn.pack(side="left", padx=8)
        ttk.Button(row, text="打开文件夹", command=self.open_folder).pack(side="left")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=18)
        self.start_btn = ttk.Button(row, text="开始下载", style="Accent.TButton", command=self.start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(row, text="取消", state="disabled", command=self.cancel.set)
        self.stop_btn.pack(side="left", padx=8)
        self.login_btn = ttk.Button(row, text="登录抖音 / 更新登录状态", command=self.login)
        self.login_btn.pack(side="right")
        self.table = ttk.Treeview(frame, columns=("link", "state"), show="headings", height=4)
        self.table.heading("link", text="视频 / 文件")
        self.table.heading("state", text="状态")
        self.table.column("link", width=640)
        self.table.column("state", width=155, stretch=False)
        self.table.pack(fill="both", expand=True)
        self.bar = ttk.Progressbar(frame, mode="determinate")
        self.bar.pack(fill="x", pady=(15, 8))
        ttk.Label(frame, textvariable=self.status, wraplength=890, foreground="#67e8f9").pack(anchor="w")
        self.logbox = tk.Text(frame, height=4, bg="#111827", fg="#94a3b8", relief="flat", font=("Microsoft YaHei UI", 9), state="disabled", wrap="word")
        self.logbox.pack(fill="x", pady=(8, 0))
        ttk.Label(frame, text="视频直接保存到本机。若抖音要求登录或验证，请在弹出的独立浏览器内完成。", foreground="#64748b", font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(8, 0))
        self.input.focus_set()
        root.bind("<Control-Return>", lambda _: self.start())
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)

    def paste(self):
        try:
            value = self.root.clipboard_get()
            self.input.delete("1.0", "end")
            self.input.insert("1.0", value)
        except tk.TclError:
            messagebox.showinfo("剪贴板", "剪贴板内没有可粘贴的文字。")

    def choose(self):
        folder = filedialog.askdirectory(title="选择视频保存文件夹")
        if folder:
            self.folder.set(folder)

    def open_folder(self):
        try:
            folder = Path(self.folder.get()).expanduser().resolve()
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(folder)
        except OSError as exc:
            messagebox.showerror("无法打开文件夹", str(exc))

    def set_busy(self, value):
        self.busy = value
        for button in (self.start_btn, self.login_btn, self.choose_btn, self.paste_btn, self.folder_entry):
            button.configure(state="disabled" if value else "normal")
        self.input.configure(state="disabled" if value else "normal")
        self.stop_btn.configure(state="normal" if value else "disabled")
        if value:
            self.cancel.clear()

    def emit(self, message):
        self.events.put(("log", str(message)))

    def start(self):
        if self.busy:
            return
        try:
            links = extract_links(self.input.get("1.0", "end"))
            if not self.folder.get().strip():
                raise DownloadError("请选择保存位置")
            folder = Path(self.folder.get()).expanduser().resolve()
            folder.mkdir(parents=True, exist_ok=True)
            # Detect unwritable folders before resolving any video.
            import tempfile
            with tempfile.TemporaryFile(dir=folder):
                pass
            DATA.mkdir(parents=True, exist_ok=True)
            (DATA / "settings.json").write_text(json.dumps({"folder": str(folder)}, ensure_ascii=False), "utf-8")
        except (DownloadError, OSError) as exc:
            messagebox.showerror("请检查输入", str(exc))
            return
        self.table.delete(*self.table.get_children())
        rows = [(self.table.insert("", "end", values=(link, "等待中")), link) for link in links]
        self.bar["value"] = 0
        self.set_busy(True)
        threading.Thread(target=self.run_downloads, args=(rows, folder), daemon=True).start()

    def progress(self, done, total, speed):
        now = time.monotonic()
        if now - self.last_progress > .15 or done == total:
            self.last_progress = now
            self.events.put(("progress", (done, total, speed)))

    def run_downloads(self, rows, folder):
        success, failure = 0, 0
        try:
            resolver = Resolver(self.emit, self.cancel)
            for index, (row, link) in enumerate(rows):
                if self.cancel.is_set():
                    for pending, _ in rows[index:]:
                        self.events.put(("row", (pending, None, "已取消")))
                    break
                self.events.put(("reset", None))
                self.events.put(("row", (row, None, "解析中")))
                try:
                    info = resolver.resolve(link)
                    self.events.put(("row", (row, info.title, "下载中")))
                    path = download_video(info, folder, self.progress, self.cancel)
                    self.events.put(("row", (row, path.name, "已完成")))
                    self.emit(f"已保存：{path}")
                    success += 1
                except Cancelled:
                    self.events.put(("row", (row, None, "已取消")))
                except Exception as exc:
                    failure += 1
                    self.events.put(("row", (row, None, "下载失败")))
                    self.emit(str(exc) if isinstance(exc, DownloadError) else "处理失败，请检查网络和保存位置后重试。")
            self.events.put(("done", f"任务结束 · 成功 {success} 个，失败 {failure} 个" + (" · 已取消剩余任务" if self.cancel.is_set() else "")))
        except Exception:
            self.events.put(("done", "任务异常结束，请重试。"))

    def login(self):
        if self.busy:
            return
        self.set_busy(True)
        def worker():
            try:
                login_browser(self.emit, self.cancel)
                self.events.put(("done", "浏览器已关闭，登录状态保存在本机；可以开始下载。"))
            except Exception as exc:
                self.events.put(("done", str(exc) if isinstance(exc, DownloadError) else "浏览器启动失败，请关闭之前的独立浏览器后重试。"))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self.status.set(value)
                    self.logbox.configure(state="normal")
                    self.logbox.insert("end", f"{time.strftime('%H:%M:%S')}  {value}\n")
                    self.logbox.see("end")
                    self.logbox.configure(state="disabled")
                elif kind == "row":
                    row, title, state = value
                    old = self.table.item(row, "values")
                    self.table.item(row, values=(title or old[0], state))
                elif kind == "reset":
                    self.bar["value"] = 0
                elif kind == "progress":
                    done, total, speed = value
                    self.bar["value"] = done / total * 100 if total else 0
                    self.status.set(f"下载中 · {done / 1048576:.1f} MB" + (f" / {total / 1048576:.1f} MB" if total else "") + f" · {speed / 1048576:.1f} MB/s")
                elif kind == "done":
                    self.status.set(value)
                    self.set_busy(False)
                    if self.closing:
                        self.root.destroy()
                        return
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def close(self):
        if self.busy:
            self.closing = True
            self.cancel.set()
            self.status.set("正在取消任务并关闭，请稍候…")
        else:
            self.root.destroy()


def main():
    # PowerShell redirection can select GBK; video titles often contain emoji.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="抖音视频本地下载器")
    parser.add_argument("--url", help="命令行下载：视频链接或分享文案")
    parser.add_argument("--output", default=str(Path.home() / "Downloads" / "抖音视频"))
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.url:
        cancel = threading.Event()
        try:
            for link in extract_links(args.url):
                info = Resolver(print, cancel).resolve(link)
                result = download_video(info, args.output, lambda a, b, c: None, cancel)
                print(f"已保存：{result}")
        except (DownloadError, KeyboardInterrupt) as exc:
            print(f"下载失败：{exc}", file=sys.stderr)
            return 1
        return 0
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    if args.smoke_test:
        root.after(1200, root.destroy)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
