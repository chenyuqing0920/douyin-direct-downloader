"""Verify the authenticated tunnel without exposing local credentials in output."""
import argparse
import http.cookiejar
import json
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener
from urllib.parse import urlsplit

from web_server import load_access


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    args = parser.parse_args()
    base = args.url.rstrip("/")
    jar = http.cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    with opener.open(base, timeout=25) as r:
        assert r.status == 200
    try:
        opener.open(base + "/api/jobs", timeout=25)
        raise AssertionError("Anonymous task access")
    except HTTPError as exc:
        assert exc.code == 401
    body = json.dumps({"password": load_access()["password"]}).encode()
    request = Request(base + "/api/login", data=body, headers={"Content-Type":"application/json", "Origin":base})
    with opener.open(request, timeout=25) as r:
        assert r.status == 200
        assert "Secure" in r.headers["Set-Cookie"]
        token = json.load(r)["csrf"]
    with opener.open(base + "/api/jobs", timeout=25) as r:
        jobs = json.load(r)["jobs"]
    completed = next((j for j in jobs if j["state"] == "ready"), None)
    origin_host = None
    if completed:
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args): return None
        try:
            build_opener(HTTPCookieProcessor(jar), NoRedirect()).open(base + "/files/" + completed["id"], timeout=25)
            raise AssertionError("Server returned a video body instead of redirect")
        except HTTPError as exc:
            assert exc.code == 302
            assert exc.headers["X-Video-Delivery"] == "direct-origin"
            target = exc.headers["Location"]
            assert len(exc.read()) < 10000
            exc.close()
        with opener.open(Request(target, headers={"Range":"bytes=0-127"}), timeout=25) as r:
            assert r.status == 206
            assert len(r.read()) == 128
            origin_host = urlsplit(r.url).hostname
            assert origin_host != urlsplit(base).hostname
    with opener.open(Request(base + "/api/logout", data=b"{}", headers={"Content-Type":"application/json", "Origin":base, "X-CSRF-Token":token}), timeout=25) as r:
        assert r.status == 200
    print(json.dumps({"https":True,"anonymous_blocked":True,"login":True,"secure_cookie":True,"jobs":len(jobs),"server_delivery":"302 redirect only","origin_host":origin_host,"logout":True}))


if __name__ == "__main__":
    main()
