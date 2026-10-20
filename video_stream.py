"""Bounded, disk-free relay for MP4 responses and mobile byte-range requests."""
from __future__ import annotations

import http.cookiejar
import re
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from downloader import DownloadError, UA, check_cancel

CHUNK_SIZE = 64 * 1024


class StreamUnavailable(DownloadError):
    pass


class InvalidRange(DownloadError):
    def __init__(self, content_range=None):
        super().__init__("不支持该视频分段请求，请重新解析或下载。")
        self.content_range = content_range


class VideoStream:
    def __init__(self, response, prefix, expected):
        self.response, self.prefix, self.expected = response, prefix, expected
        self.status = response.status
        self.headers = {name: response.headers[name] for name in ("Content-Length", "Content-Range", "Accept-Ranges") if response.headers.get(name)}
        self.closed = False

    def chunks(self, cancel):
        count = 0
        try:
            check_cancel(cancel)
            if self.prefix:
                count += len(self.prefix)
                yield self.prefix
                self.prefix = b""
            while True:
                check_cancel(cancel)
                chunk = self.response.read(CHUNK_SIZE)
                if not chunk:
                    break
                count += len(chunk)
                yield chunk
            if self.expected is not None and count != self.expected:
                raise OSError("上游视频传输中断")
        finally:
            self.close()

    def close(self):
        if not self.closed:
            self.closed = True
            self.response.close()


def open_video_stream(info, range_header=None, head=False, opener=None):
    if range_header and not re.fullmatch(r"bytes=(?:\d+-\d*|-\d+)", range_header):
        raise InvalidRange()
    if opener is None:
        jar = http.cookiejar.CookieJar()
        for cookie in info.cookies:
            jar.set_cookie(cookie)
        opener = build_opener(HTTPCookieProcessor(jar))
    last_error = None
    for url in info.urls:
        response = None
        try:
            headers = {"User-Agent": UA, "Referer": "https://www.douyin.com/", **info.headers,
                       "Accept-Encoding": "identity"}
            if range_header:
                headers["Range"] = range_header
            response = opener.open(Request(url, headers=headers, method="HEAD" if head else "GET"), timeout=20)
            if response.status not in (200, 206):
                raise StreamUnavailable("视频地址暂时不可用")
            kind = response.headers.get("Content-Type", "").lower().split(";")[0]
            if kind not in ("video/mp4", "application/octet-stream", "binary/octet-stream", "video/quicktime"):
                raise StreamUnavailable("视频地址返回了非视频内容，请重新解析")
            start = 0
            if response.status == 206:
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+|\*)", response.headers.get("Content-Range", ""))
                if not match or not range_header:
                    raise StreamUnavailable("视频分段响应不正确，请重新解析")
                start = int(match[1])
                end = int(match[2])
                if end < start:
                    raise StreamUnavailable("视频分段响应不正确")
                if not range_header.startswith("bytes=-") and start != int(range_header[6:].split("-")[0]):
                    raise StreamUnavailable("视频分段位置不正确")
            length = response.headers.get("Content-Length")
            expected = int(length) if length is not None else None
            if expected is not None and expected <= 0:
                raise StreamUnavailable("视频内容为空")
            prefix = b"" if head else response.read(min(CHUNK_SIZE, expected or CHUNK_SIZE))
            if not head and (not prefix or (start == 0 and len(prefix) >= 12 and b"ftyp" not in prefix[:64])):
                raise StreamUnavailable("返回内容不是 MP4 视频")
            return VideoStream(response, prefix, expected)
        except HTTPError as exc:
            if exc.code == 416:
                last_error = InvalidRange(exc.headers.get("Content-Range"))
            else:
                last_error = exc
            exc.close()
        except Exception as exc:
            last_error = exc
        if response is not None:
            response.close()
    if isinstance(last_error, InvalidRange):
        raise last_error
    raise StreamUnavailable("视频地址已失效或网络中断，请点击“重新解析”后再下载。") from last_error
