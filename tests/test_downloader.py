import functools
import http.server
import json
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import build_opener

from downloader import Cancelled, DownloadError, Video, _muxed_urls, detail_from_html, download_video, extract_any_links, extract_links, safe_name, video_id, walk_details


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class DownloaderTests(unittest.TestCase):
    def test_share_text_and_domain_validation(self):
        self.assertEqual(extract_links("分享 3.2 https://v.douyin.com/abc/。 打开抖音"), ["https://v.douyin.com/abc/"])
        with self.assertRaises(DownloadError):
            extract_links("https://douyin.com.evil.test/video/123")
        self.assertEqual(len(extract_links("https://www.douyin.com/video/123 https://www.douyin.com/video/123")), 1)

    def test_any_links_multi_platform(self):
        self.assertEqual(extract_any_links("看这个 https://www.bilibili.com/video/BV1xx411c7mu/ 不错"),
                         ["https://www.bilibili.com/video/BV1xx411c7mu/"])
        self.assertEqual(extract_any_links("https://www.tiktok.com/@a/video/123"),
                         ["https://www.tiktok.com/@a/video/123"])
        # Douyin links still win when mixed with other platforms.
        mixed = "https://www.bilibili.com/video/BV1xx411c7mu/ https://v.douyin.com/abc/"
        self.assertEqual(extract_any_links(mixed), ["https://v.douyin.com/abc/"])
        with self.assertRaises(DownloadError):
            extract_any_links("没有任何链接")

    def test_muxed_url_picking(self):
        data = {"formats": [
            {"url": "https://cdn.example/v-only.mp4", "vcodec": "avc1", "acodec": "none", "height": 1080},
            {"url": "https://cdn.example/low.mp4", "vcodec": "avc1", "acodec": "mp4a", "height": 360, "ext": "mp4"},
            {"url": "https://cdn.example/high.mp4", "vcodec": "avc1", "acodec": "mp4a", "height": 720, "ext": "mp4"},
        ]}
        picked = _muxed_urls(data)
        self.assertEqual([f["url"] for f in picked],
                         ["https://cdn.example/high.mp4", "https://cdn.example/low.mp4"])

    def test_identifiers(self):
        self.assertEqual(video_id("https://www.douyin.com/?modal_id=123"), "123")
        self.assertEqual(video_id("https://www.iesdouyin.com/share/video/456/"), "456")
        self.assertIsNone(video_id("https://www.douyin.com/user/123"))

    def test_extract_only_requested_video(self):
        detail = {"aweme_id": "123", "desc": "测试视频", "video": {"play_addr": {"url_list": ["https://cdn.example/video.mp4"]}}}
        data = {"loaderData": [{"aweme_id": "999", "video": {}}, detail]}
        self.assertEqual(walk_details(data, "123"), detail)
        info = detail_from_html("<script>window._ROUTER_DATA = " + json.dumps(data) + ";</script>", "123")
        self.assertEqual(info.id, "123")
        self.assertIsNone(detail_from_html("<script>window._ROUTER_DATA = " + json.dumps(data) + ";</script>", "456"))

    def test_safe_windows_names(self):
        self.assertEqual(safe_name("CON"), "_CON")
        self.assertNotIn("/", safe_name("标题/内容:测试?"))
        self.assertEqual(safe_name("..."), "抖音视频")

    def test_download_atomic_cancel_and_backup(self):
        # Real HTTP I/O checks file integrity, wrong content, duplicate handling and cancellation.
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as output:
            payload = struct.pack(">I", 24) + b"ftypisom" + b"\x00" * 12 + b"sample" * 50000
            Path(source, "video.mp4").write_bytes(payload)
            Path(source, "bad.html").write_text("<html>login</html>")
            handler = functools.partial(QuietHandler, directory=source)
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                info = Video("123", "中文标题", [base + "/bad.html", base + "/video.mp4"])
                cancel = threading.Event()
                opener = build_opener()
                result = download_video(info, output, lambda *a: None, cancel, opener)
                self.assertEqual(result.read_bytes(), payload)
                result2 = download_video(info, output, lambda *a: None, cancel, opener)
                self.assertNotEqual(result, result2)
                def stop(*args):
                    cancel.set()
                with self.assertRaises(Cancelled):
                    download_video(info, output, stop, cancel, opener)
                self.assertEqual(len(list(Path(output).glob("*.mp4"))), 2)
                self.assertEqual(list(Path(output).glob("*.part")), [])
                cancel.clear()
                with self.assertRaises(DownloadError):
                    download_video(Video("123", "bad", [base + "/bad.html"]), output, lambda *a: None, cancel, opener)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
