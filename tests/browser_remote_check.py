"""Manual integration QA against an owned localhost remote-app instance."""
import json
import time
from urllib.parse import urlsplit
from pathlib import Path

from playwright.sync_api import sync_playwright
from web_server import load_access


def main():
    artifacts = Path(__file__).parent / "artifacts"
    artifacts.mkdir(exist_ok=True)
    server_folders = [Path.home() / "Downloads" / "抖音视频", Path(__file__).resolve().parent.parent / "downloads"]
    def server_videos():
        return {(str(p), p.stat().st_size) for folder in server_folders if folder.exists() for p in folder.rglob("*") if p.is_file() and p.suffix in (".mp4", ".part")}
    before = server_videos()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True, has_touch=True)
        page = context.new_page()
        errors = []
        origin_hosts = set()
        file_statuses = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        def record(response):
            host = urlsplit(response.url).hostname
            if host and host != "127.0.0.1" and response.status in (200, 206) and "video" in response.headers.get("content-type", ""):
                origin_hosts.add(host)
            if response.url.startswith("http://127.0.0.1:7860/files/"):
                file_statuses.append(response.status)
        page.on("response", record)
        page.goto("http://127.0.0.1:7860")
        page.screenshot(path=str(artifacts / "手机登录页.png"), full_page=True)
        page.locator("#password").fill(load_access()["password"])
        page.locator("#login-button").click()
        page.locator("#workspace").wait_for(state="visible")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Mobile horizontal overflow"
        page.screenshot(path=str(artifacts / "手机下载页.png"), full_page=True)
        page.locator("#share-text").fill("https://www.douyin.com/video/6961737553342991651")
        page.locator("#submit-button").click()
        page.locator(".job").first.wait_for()
        deadline = time.monotonic() + 160
        while time.monotonic() < deadline:
            state = page.locator(".job").first.get_attribute("data-state")
            if state in ("ready", "failed", "cancelled"):
                break
            page.wait_for_timeout(1000)
        assert state == "ready", page.locator(".job").first.inner_text()
        assert server_videos() == before, "Server saved a video during parsing"
        page.locator("#notice").wait_for(state="hidden", timeout=12000)
        page.screenshot(path=str(artifacts / "手机下载完成.png"), full_page=True)
        with page.expect_download() as download_info:
            page.get_by_role("button", name="直接下载", exact=False).first.click()
        download = download_info.value
        downloaded = artifacts / "phone-download-check.mp4"
        download.save_as(downloaded)
        assert downloaded.stat().st_size > 100000
        assert server_videos() == before, "Server saved a video during streaming"
        page.get_by_role("button", name="预览", exact=True).first.click()
        page.locator("#preview-video").wait_for()
        for _ in range(80):
            if page.locator("#preview-video").evaluate("v => v.readyState >= 1"):
                break
            page.wait_for_timeout(100)
        assert page.locator("#preview-video").evaluate("v => v.duration > 0")
        page.locator("#close-preview").click()
        page.locator("#logout-button").click()
        page.locator("#login-panel").wait_for(state="visible")
        assert not errors, errors
        assert origin_hosts, "No direct video request from visitor browser"
        assert all(s == 302 for s in file_statuses), "Server relayed video data"
        browser.close()
        print(json.dumps({"mobile_width":390,"download_bytes":downloaded.stat().st_size,"server_video_files_added":0,"origin_hosts":sorted(origin_hosts),"server_file_responses":file_statuses,"video_metadata":True,"js_errors":errors},ensure_ascii=False))


if __name__ == "__main__":
    main()
