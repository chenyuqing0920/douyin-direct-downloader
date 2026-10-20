import http.server
import re
import threading
import unittest
from unittest.mock import patch

from downloader import Video
from video_stream import CHUNK_SIZE, InvalidRange, StreamUnavailable, open_video_stream


class RangeServer:
    def __init__(self):
        self.payload = b"\x00\x00\x00\x18ftypisom" + b"x" * (2 * 1024 * 1024)
        self.requests = []
        owner = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_HEAD(self): self.serve(True)
            def do_GET(self): self.serve(False)
            def serve(self, head):
                owner.requests.append((self.command, self.headers.get("Range")))
                payload = owner.payload
                if self.path == "/bad":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", "4")
                    self.end_headers()
                    if not head: self.wfile.write(b"oops")
                    return
                start, end = 0, len(payload) - 1
                value = self.headers.get("Range")
                if value:
                    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
                    if match[1]:
                        start = int(match[1])
                        if match[2]: end = min(end, int(match[2]))
                    else:
                        start = max(0, len(payload) - int(match[2]))
                    if start > end:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{len(payload)}")
                        self.end_headers()
                        return
                self.send_response(206 if value else 200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(end - start + 1))
                self.send_header("Accept-Ranges", "bytes")
                if value: self.send_header("Content-Range", f"bytes {start}-{end}/{len(payload)}")
                self.end_headers()
                if not head:
                    try: self.wfile.write(payload[start:end + 1])
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/video"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.server = RangeServer()
        self.info = Video("123", "视频", [self.server.url])

    def tearDown(self): self.server.close()

    def test_lazy_stream_and_disconnect_cleanup_without_disk(self):
        with patch("builtins.open", side_effect=AssertionError("Video relay must not open files")):
            source = open_video_stream(self.info)
            self.assertLessEqual(len(source.prefix), CHUNK_SIZE)
            iterator = source.chunks(threading.Event())
            self.assertEqual(next(iterator), self.server.payload[:CHUNK_SIZE])
            self.assertEqual(source.response.length, len(self.server.payload) - CHUNK_SIZE)
            iterator.close()
            self.assertTrue(source.closed)

    def test_mobile_ranges_and_complete_stream(self):
        source = open_video_stream(self.info)
        self.assertEqual(b"".join(source.chunks(threading.Event())), self.server.payload)
        for value, expected in (("bytes=0-1", self.server.payload[:2]), ("bytes=100-199", self.server.payload[100:200]), ("bytes=-24", self.server.payload[-24:])):
            source = open_video_stream(self.info, value)
            self.assertEqual(source.status, 206)
            self.assertEqual(b"".join(source.chunks(threading.Event())), expected)
        with self.assertRaises(InvalidRange): open_video_stream(self.info, "bytes=0-10,20-30")
        with self.assertRaises(InvalidRange): open_video_stream(self.info, "bytes=99999999-")

    def test_backup_address_and_reject_html(self):
        bad = self.server.url.replace("/video", "/bad")
        with self.assertRaises(StreamUnavailable): open_video_stream(Video("1", "bad", [bad]))
        source = open_video_stream(Video("1", "ok", [bad, self.server.url]))
        self.assertEqual(b"".join(source.chunks(threading.Event())), self.server.payload)


if __name__ == "__main__": unittest.main()
