"""Local Douyin resolver and atomic MP4 downloader. No hosted parsing service."""
from __future__ import annotations

import html
import http.cookiejar
import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Version/17.5 Mobile/15E148 Safari/604.1"
DATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "DouyinLocalDownloader"


class DownloadError(Exception):
    pass


class Cancelled(DownloadError):
    pass


def check_cancel(cancel):
    if cancel.is_set():
        raise Cancelled("已取消")


def is_douyin(url):
    p = urlparse(url)
    return p.scheme in ("http", "https") and (p.hostname or "").lower() in {
        "douyin.com", "www.douyin.com", "v.douyin.com", "iesdouyin.com", "www.iesdouyin.com",
    } and not p.username and not p.password and p.port in (None, 80, 443)


def extract_links(text):
    links = []
    for value in re.findall(r"https?://[^\s<>\"\u3000]+", text):
        value = value.rstrip(".,;!?，。；！？、）)]}〉》'”")
        try:
            valid = is_douyin(value)
        except ValueError:
            valid = False
        if valid and value not in links:
            links.append(value)
    if not links:
        raise DownloadError("没有找到抖音链接。请粘贴抖音的“复制链接”分享文案或视频网址。")
    return links


def video_id(url):
    match = re.search(r"/(?:share/)?(?:video|note)/(\d+)", urlparse(url).path)
    if match:
        return match[1]
    q = parse_qs(urlparse(url).query)
    for key in ("modal_id", "aweme_id", "vid"):
        value = q.get(key, [""])[0]
        if value.isdigit():
            return value
    return None


def safe_name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")[:70].rstrip(" .")
    if not value:
        return "抖音视频"
    if value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        value = "_" + value
    return value


@dataclass
class Video:
    id: str
    title: str
    urls: list[str]
    headers: dict = field(default_factory=dict)
    cookies: list = field(default_factory=list)


def walk_details(data, wanted):
    """Only accept the requested post; recommendation responses are ignored."""
    if isinstance(data, dict):
        if str(data.get("aweme_id", "")) == wanted and isinstance(data.get("video"), dict):
            return data
        for child in data.values():
            found = walk_details(child, wanted)
            if found:
                return found
    elif isinstance(data, list):
        for child in data:
            found = walk_details(child, wanted)
            if found:
                return found
    return None


def from_detail(detail):
    v = detail["video"]
    addresses = []
    # Prefer the ordinary H.264 playback stream when the site supplies one.
    addresses.append(v.get("play_addr_h264", {}))
    for rate in sorted(v.get("bit_rate") or [], key=lambda x: x.get("bit_rate", 0), reverse=True):
        if not rate.get("is_bytevc1") and not rate.get("is_h265"):
            addresses.append(rate.get("play_addr", {}))
    addresses.extend([v.get("play_addr", {}), v.get("download_addr", {})])
    urls = []
    for addr in addresses:
        for url in addr.get("url_list", []):
            if isinstance(url, str) and url.startswith(("https://", "http://")) and url not in urls:
                urls.append(url)
    if not urls:
        raise DownloadError("该作品没有可下载的视频，可能是图文作品或作品已不可访问。")
    return Video(str(detail["aweme_id"]), detail.get("desc") or "抖音视频", urls)


def detail_from_html(page, wanted):
    # Published mobile pages use _ROUTER_DATA; older pages use RENDER_DATA.
    for match in re.finditer(r"(?:window\.)?_ROUTER_DATA\s*=\s*", page):
        try:
            data, _ = json.JSONDecoder().raw_decode(page[match.end():].lstrip())
            found = walk_details(data, wanted)
            if found:
                return from_detail(found)
        except (ValueError, TypeError):
            pass
    for content in re.findall(r'<script\b[^>]*>(.*?)</script>', page, re.S | re.I):
        for raw in (content.strip(), unquote(html.unescape(content.strip()))):
            try:
                found = walk_details(json.loads(raw), wanted)
                if found:
                    return from_detail(found)
            except (ValueError, TypeError):
                pass
    return None


class Resolver:
    def __init__(self, log, cancel, browser_timeout=100):
        self.log, self.cancel, self.browser_timeout = log, cancel, browser_timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.jar))

    def resolve(self, url):
        check_cancel(self.cancel)
        if not is_douyin(url):
            raise DownloadError("仅支持抖音链接")
        wanted = video_id(url)
        if not wanted:
            self.log("正在展开分享短链接…")
            try:
                with self.opener.open(Request(url, headers={"User-Agent": MOBILE_UA}), timeout=20) as response:
                    target = response.url
                    if not is_douyin(target):
                        raise DownloadError("分享链接跳转到了非抖音页面")
                    wanted = video_id(target)
            except DownloadError:
                raise
            except Exception as exc:
                raise DownloadError("短链接无法打开，请检查网络或使用完整视频网址。") from exc
        if not wanted:
            raise DownloadError("链接中没有找到视频编号；请使用单个视频的分享链接。")
        self.log(f"正在解析视频 {wanted}…")
        mobile = f"https://www.iesdouyin.com/share/video/{wanted}/"
        try:
            with self.opener.open(Request(mobile, headers={"User-Agent": MOBILE_UA}), timeout=15) as response:
                info = detail_from_html(response.read(8 * 1024 * 1024).decode("utf-8", "replace"), wanted)
            if info:
                info.headers = {"User-Agent": MOBILE_UA, "Referer": "https://www.douyin.com/"}
                info.cookies = list(self.jar)
                return info
        except DownloadError:
            raise
        except Exception:
            pass
        check_cancel(self.cancel)
        # yt-dlp remains replaceable through requirements.txt / the update script.
        self.log("分享页未返回视频，尝试开源解析引擎…")
        try:
            import yt_dlp
            class Quiet:
                def debug(self, msg): pass
                def warning(self, msg): pass
                def error(self, msg): pass
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "logger": Quiet(), "socket_timeout": 12,
                                     "retries": 0, "extractor_retries": 0, "noplaylist": True}) as ydl:
                data = ydl.extract_info(f"https://www.douyin.com/video/{wanted}", download=False)
            formats = [f for f in data.get("formats", []) if f.get("url") and f.get("vcodec") != "none"
                       and f.get("acodec") != "none" and f.get("ext") == "mp4"]
            formats.sort(key=lambda f: (f.get("height") or 0, f.get("tbr") or 0), reverse=True)
            if formats:
                return Video(wanted, data.get("title") or "抖音视频", [f["url"] for f in formats],
                             {**data.get("http_headers", {}), **formats[0].get("http_headers", {})}, list(ydl.cookiejar))
        except Exception:
            pass
        check_cancel(self.cancel)
        return self.browser_resolve(wanted)

    def browser_resolve(self, wanted):
        from playwright.sync_api import Error as BrowserError, sync_playwright
        self.log("正在打开独立浏览器解析；如页面要求验证或登录，请在浏览器内完成。")
        with sync_playwright() as p:
            context = launch_browser(p)
            try:
                page = context.new_page()
                # Parsing only needs page/API metadata; do not cache video playback on the PC.
                network = context.new_cdp_session(page)
                network.send("Network.enable")
                network.send("Network.setBlockedURLs", {"urls": ["*.mp4*", "*douyinvod.com/*", "*bytevod.com/*", "*zjcdn.com/*", "*douyincdn.com/*", "*toutiaovod.com/*"]})
                found = []
                def receive(response):
                    if "/aweme/" in response.url and "application/json" in response.headers.get("content-type", ""):
                        try:
                            detail = walk_details(response.json(), wanted)
                            if detail:
                                found.append(from_detail(detail))
                        except Exception:
                            pass
                page.on("response", receive)
                target = f"https://www.douyin.com/video/{wanted}"
                try:
                    page.goto(target, wait_until="domcontentloaded", timeout=35000)
                except Exception:
                    if page.is_closed():
                        raise DownloadError("浏览器已关闭，请重试")
                deadline = time.monotonic() + self.browser_timeout
                while time.monotonic() < deadline:
                    check_cancel(self.cancel)
                    if page.is_closed():
                        raise DownloadError("浏览器已关闭，请重试")
                    if not found:
                        try:
                            content = page.content()
                        except BrowserError as exc:
                            if "navigat" in str(exc).lower():
                                page.wait_for_timeout(300)
                                continue
                            raise
                        info = detail_from_html(content, wanted)
                        if info:
                            found.append(info)
                    if found:
                        info = found[0]
                        info.headers = {"User-Agent": page.evaluate("navigator.userAgent"), "Referer": target}
                        info.cookies = browser_cookies(context.cookies())
                        return info
                    page.wait_for_timeout(500)
                raise DownloadError("未取得视频。请点击“登录抖音”，完成验证后关闭浏览器，再重试。作品也可能已删除、私密或不是视频。")
            finally:
                context.close()


def launch_browser(playwright):
    DATA.mkdir(parents=True, exist_ok=True)
    errors = []
    for channel in ("msedge", "chrome"):
        try:
            return playwright.chromium.launch_persistent_context(
                str(DATA / "browser-profile"), channel=channel, headless=False,
                viewport={"width": 1100, "height": 760}, accept_downloads=False,
                args=["--autoplay-policy=user-gesture-required"])
        except Exception as exc:
            errors.append(type(exc).__name__)
    raise DownloadError("无法启动浏览器。请安装 Edge 或 Chrome，并关闭本工具先前打开的抖音浏览器后重试。")


def browser_cookies(values):
    result = []
    for c in values:
        domain = c["domain"]
        result.append(http.cookiejar.Cookie(0, c["name"], c["value"], None, False, domain,
                     domain.startswith("."), domain.startswith("."), c["path"], True,
                     c["secure"], int(c["expires"]) if c.get("expires", -1) > 0 else None,
                     False, None, None, {}, False))
    return result


def login_browser(log, cancel):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        context = launch_browser(p)
        try:
            page = context.new_page()
            log("请在独立浏览器内登录抖音，完成后关闭浏览器窗口。登录状态会保存在本机。")
            try:
                page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=35000)
            except Exception:
                pass
            while context.pages:
                check_cancel(cancel)
                try:
                    context.pages[0].wait_for_timeout(500)
                except Exception:
                    break
        finally:
            try:
                context.close()
            except Exception:
                pass


def download_video(info, folder, progress, cancel, opener=None):
    folder = Path(folder).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{safe_name(info.title)}_{info.id}"
    if opener is None:
        jar = http.cookiejar.CookieJar()
        for cookie in info.cookies:
            jar.set_cookie(cookie)
        opener = build_opener(HTTPCookieProcessor(jar))
    last_error = None
    for url in info.urls:
        check_cancel(cancel)
        temp = folder / f".{stem}.{uuid.uuid4().hex[:8]}.part"
        try:
            headers = {"User-Agent": UA, "Referer": "https://www.douyin.com/", **info.headers,
                       "Accept-Encoding": "identity"}
            with opener.open(Request(url, headers=headers), timeout=20) as response:
                if response.status != 200:
                    raise DownloadError(f"视频服务器返回 HTTP {response.status}")
                total = int(response.headers.get("Content-Length") or 0)
                kind = response.headers.get("Content-Type", "").lower()
                if any(t in kind for t in ("text/", "json", "image/")):
                    raise DownloadError("视频地址返回了网页或图片，无法保存为视频")
                received, first, started = 0, b"", time.monotonic()
                with temp.open("xb") as output:
                    while True:
                        check_cancel(cancel)
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        if not first:
                            first = chunk[:64]
                            if b"ftyp" not in first:
                                raise DownloadError("返回内容不是有效 MP4 视频")
                        output.write(chunk)
                        received += len(chunk)
                        progress(received, total, received / max(time.monotonic() - started, .01))
                if received < 32 or (total and received != total):
                    raise DownloadError("视频传输不完整，请重试")
            check_cancel(cancel)
            # Windows rename does not replace an existing file. Keep every completed copy.
            for n in range(10000):
                target = folder / f"{stem}{f' ({n})' if n else ''}.mp4"
                try:
                    if os.name != "nt" and target.exists():
                        continue
                    temp.rename(target)
                    return target
                except FileExistsError:
                    continue
            raise DownloadError("同名文件过多，请更换保存目录")
        except Cancelled:
            raise
        except Exception as exc:
            last_error = exc
        finally:
            temp.unlink(missing_ok=True)
    raise DownloadError("视频下载失败：网络中断或视频地址已过期，请重新解析后重试。") from last_error
