"""Password protected mobile interface. Only loopback is exposed to the tunnel."""
from __future__ import annotations

import hashlib
import hmac
import json
import queue
import secrets
import threading
import time
from collections import deque
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request
from urllib.parse import urlsplit
from werkzeug.security import check_password_hash, generate_password_hash

from downloader import DATA, Cancelled, DownloadError, Resolver, extract_any_links, safe_name

class LinkExpired(DownloadError):
    pass


def direct_links(info):
    urls = []
    for url in info.urls:
        try:
            value = urlsplit(url)
            if value.scheme == "https" and value.hostname and not value.username and not value.password and value.port in (None, 443) and url not in urls:
                urls.append(url)
        except ValueError:
            continue
    return urls[:16]


def load_access(data_dir=DATA):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "remote-access.json"
    if path.exists():
        return json.loads(path.read_text("utf-8"))
    value = {"password": secrets.token_urlsafe(15)}
    # This local file is read by the PC control panel only, never served by HTTP.
    with path.open("x", encoding="utf-8") as f:
        json.dump(value, f)
    return value


class Jobs:
    def __init__(self, resolver_factory=Resolver, on_log=None):
        self.resolver_factory = resolver_factory
        self.on_log = on_log or (lambda _: None)
        self.lock = threading.RLock()
        self.queue = queue.Queue()
        self.items = {}
        self.stopping = threading.Event()
        self.active_cancel = None
        self.browser_lock = threading.Lock()
        self.worker = threading.Thread(target=self.run, daemon=True)
        self.worker.start()

    def submit(self, links):
        with self.lock:
            if self.stopping.is_set():
                raise DownloadError("服务正在关闭")
            if sum(x["state"] in ("queued", "resolving") for x in self.items.values()) + len(links) > 30:
                raise DownloadError("队列最多容纳 30 个任务，请等待完成后再提交。")
            if len(self.items) + len(links) > 500:
                raise DownloadError("解析记录已达到 500 条；请重启远程版清理列表。手机内已下载的视频不受影响。")
            result = []
            for link in links:
                key = secrets.token_hex(12)
                job = {"id": key, "title": "等待解析", "link": link, "state": "queued", "message": "等待解析",
                       "created": time.time(), "cancel": threading.Event()}
                self.items[key] = job
                self.queue.put(key)
                result.append(key)
            return result

    def update(self, key, **values):
        with self.lock:
            self.items[key].update(values)

    def snapshots(self):
        with self.lock:
            return [{k: v for k, v in job.items() if k not in ("cancel", "info")} for job in reversed(list(self.items.values()))]

    def cancel(self, key):
        with self.lock:
            job = self.items.get(key)
            if not job:
                return False
            job["cancel"].set()
            if job["state"] in ("queued", "ready"):
                job.update(state="cancelled", message="已取消")
            return True

    def video(self, key):
        with self.lock:
            job = self.items.get(key)
            if not job or job["state"] != "ready" or job["cancel"].is_set():
                return None
            if time.time() - job["resolved"] > 15 * 60:
                raise LinkExpired("解析链接已过期，请点击“重新解析”再下载。")
            return job["info"], job["cancel"]

    def run(self):
        while not self.stopping.is_set():
            try:
                key = self.queue.get(timeout=.3)
            except queue.Empty:
                continue
            job = self.items[key]
            cancel = job["cancel"]
            if cancel.is_set():
                continue
            self.active_cancel = cancel
            try:
                with self.browser_lock:
                    if cancel.is_set() or self.stopping.is_set():
                        raise Cancelled("已取消")
                    self.update(key, state="resolving", message="正在解析视频")
                    def log(message):
                        self.update(key, message=str(message))
                        self.on_log(str(message))
                    info = self.resolver_factory(log, cancel).resolve(job["link"])
                    if cancel.is_set():
                        raise Cancelled("已取消")
                    self.update(key, title=info.title, state="ready", info=info, resolved=time.time(),
                                message="已解析，访客设备直接从视频源站下载")
                self.on_log(f"已解析：{info.title}（只提供地址，不转发视频）")
            except Cancelled:
                self.update(key, state="cancelled", message="已取消")
            except Exception as exc:
                self.update(key, state="failed", message=str(exc) if isinstance(exc, DownloadError) else "解析失败，请检查电脑网络后重试。")
            finally:
                self.active_cancel = None

    def stop(self):
        self.stopping.set()
        with self.lock:
            for job in self.items.values():
                job["cancel"].set()


def create_app(jobs, password, resources=None):
    resources = Path(resources or Path(__file__).parent / "web")
    app = Flask(__name__, template_folder=str(resources / "templates"), static_folder=str(resources / "static"))
    app.config.update(MAX_CONTENT_LENGTH=16 * 1024)
    password_hash = generate_password_hash(password)
    sessions = {}
    lock = threading.RLock()
    attempts = deque()
    cookie_name = "douyin_remote_session"

    def authorized():
        token = request.cookies.get(cookie_name, "")
        key = hashlib.sha256(token.encode()).hexdigest()
        with lock:
            session = sessions.get(key)
            if session and session["expires"] > time.time():
                return session
            sessions.pop(key, None)
        return None

    def protect(function):
        @wraps(function)
        def inner(*args, **kwargs):
            if not authorized():
                return jsonify(error="请先输入访问密码"), 401
            return function(*args, **kwargs)
        return inner

    @app.before_request
    def check_origin():
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            # JSON-only mutations prevent cross-site form submissions, including login CSRF.
            if not request.is_json:
                return jsonify(error="请求格式不正确"), 415
            origin = request.headers.get("Origin")
            if origin:
                from urllib.parse import urlsplit
                if urlsplit(origin).netloc != request.host:
                    return jsonify(error="请求来源不匹配"), 403
            if request.path != "/api/login":
                session = authorized()
                supplied = request.headers.get("X-CSRF-Token", "")
                if not session:
                    return jsonify(error="请先登录"), 401
                if not hmac.compare_digest(supplied, session["csrf"]):
                    return jsonify(error="页面已过期，请刷新后重试"), 403

    @app.after_request
    def secure_headers(response):
        # Windows registry sometimes maps .js to text/plain. Keep nosniff and fix the MIME type.
        if request.endpoint == "static":
            if request.path.endswith(".js"):
                response.headers["Content-Type"] = "text/javascript; charset=utf-8"
            elif request.path.endswith(".css"):
                response.headers["Content-Type"] = "text/css; charset=utf-8"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self' https: blob:; connect-src 'self' https:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    @app.errorhandler(413)
    def too_large(_):
        return jsonify(error="分享文案过长，请分批提交"), 413

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.post("/api/login")
    def login():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(error="请求格式不正确"), 400
        supplied = body.get("password", "")
        if not isinstance(supplied, str) or len(supplied) > 128:
            return jsonify(error="密码格式不正确"), 400
        now = time.time()
        with lock:
            while attempts and attempts[0] < now - 60:
                attempts.popleft()
            if len(attempts) >= 8:
                return jsonify(error="尝试次数过多，请 1 分钟后重试"), 429
            attempts.append(now)
        if not check_password_hash(password_hash, supplied):
            return jsonify(error="密码不正确，请查看电脑上的远程版窗口"), 401
        token = secrets.token_urlsafe(32)
        session = {"csrf": secrets.token_urlsafe(24), "expires": now + 12 * 3600}
        with lock:
            for old in list(sessions):
                if sessions[old]["expires"] <= now:
                    sessions.pop(old)
            if len(sessions) >= 32:
                sessions.pop(next(iter(sessions)))
            sessions[hashlib.sha256(token.encode()).hexdigest()] = session
        response = jsonify(ok=True, csrf=session["csrf"])
        secure = request.is_secure or request.headers.get("X-Forwarded-Proto") == "https"
        response.set_cookie(cookie_name, token, max_age=12 * 3600, httponly=True, secure=secure, samesite="Strict", path="/")
        return response

    @app.get("/api/session")
    @protect
    def session_info():
        return jsonify(ok=True, csrf=authorized()["csrf"])

    @app.post("/api/logout")
    @protect
    def logout():
        token = request.cookies.get(cookie_name, "")
        with lock:
            sessions.pop(hashlib.sha256(token.encode()).hexdigest(), None)
        response = jsonify(ok=True)
        response.delete_cookie(cookie_name)
        return response

    @app.get("/api/jobs")
    @protect
    def list_jobs():
        return jsonify(jobs=jobs.snapshots())

    @app.post("/api/jobs")
    @protect
    def new_jobs():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("text"), str):
            return jsonify(error="请输入视频链接或分享文案"), 400
        try:
            links = extract_any_links(body["text"])
            if len(links) > 20:
                raise DownloadError("每次最多提交 20 个视频链接")
            return jsonify(ids=jobs.submit(links)), 202
        except DownloadError as exc:
            return jsonify(error=str(exc)), 400

    @app.post("/api/jobs/<key>/cancel")
    @protect
    def cancel_job(key):
        return (jsonify(ok=True), 200) if jobs.cancel(key) else (jsonify(error="任务不存在"), 404)

    def direct_info(key):
        try:
            video = jobs.video(key)
        except LinkExpired as exc:
            return None, (jsonify(error=str(exc)), 410)
        if not video:
            return None, (jsonify(error="链接尚未解析完成或任务不存在，请重新解析"), 404)
        info, _ = video
        urls = direct_links(info)
        if not urls:
            return None, (jsonify(error="源站没有返回可直接访问的 HTTPS 地址。此模式不会改用电脑转发。"), 422)
        return {"urls": urls, "filename": f"{safe_name(info.title)}_{info.id}.mp4", "delivery": "direct-origin"}, None

    @app.get("/api/jobs/<key>/direct")
    @protect
    def direct_metadata(key):
        data, error = direct_info(key)
        return error if error else jsonify(data)

    @app.get("/files/<key>")
    @protect
    def video_file(key):
        # Only a redirect. The PC never opens, HEADs, buffers or relays the video URL.
        data, error = direct_info(key)
        if error:
            return error
        index = request.args.get("source", default=0, type=int)
        if index is None or not 0 <= index < len(data["urls"]):
            return jsonify(error="视频地址编号不正确"), 400
        response = redirect(data["urls"][index], code=302)
        response.headers["X-Video-Delivery"] = "direct-origin"
        return response

    return app
