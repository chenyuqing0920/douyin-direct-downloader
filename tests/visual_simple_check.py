"""Frontend QA with clearly synthetic result fixtures; no platform download needed."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from web_server import load_access


def main():
    artifacts = Path(__file__).parent / "artifacts"
    rows = []
    submitted = []
    sample = {"id":"ui-ready", "title":"收藏一段日常，留住喜欢的瞬间", "link":"https://www.douyin.com/video/123", "state":"ready", "message":"已解析，访客设备直接从视频源站下载"}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width":390,"height":844}, device_scale_factor=1, is_mobile=True, has_touch=True)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        def jobs_route(route):
            if route.request.method == "GET":
                route.fulfill(json={"jobs":rows})
            else:
                submitted.append(route.request.post_data_json["text"])
                route.fulfill(status=202,json={"ids":["ui-submitted"]})
        page.route("**/api/jobs", jobs_route)
        page.goto("http://127.0.0.1:7860")
        page.get_by_role("heading",name="抖音视频下载",exact=True).wait_for()
        assert page.locator("body").evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(250, 250, 250)"
        page.screenshot(path=str(artifacts / "简洁版-手机登录.png"), full_page=True)
        page.locator("#toggle-password").click()
        assert page.locator("#password").get_attribute("type") == "text"
        page.locator("#password").fill(load_access()["password"])
        page.locator("#login-button").click()
        page.locator("#workspace").wait_for(state="visible")
        page.screenshot(path=str(artifacts / "简洁版-手机空列表.png"), full_page=True)
        page.locator("#share-text").fill("分享 https://www.douyin.com/video/123")
        page.locator("#submit-button").click()
        page.locator("#notice").wait_for(state="visible")
        assert submitted == ["分享 https://www.douyin.com/video/123"]
        assert page.locator("#share-text").input_value() == ""
        rows.append(sample)
        page.locator("#refresh-button").click()
        page.locator(".job[data-state=ready]").wait_for()
        page.locator("#notice").wait_for(state="hidden",timeout=12000)
        results = []
        for width,height in ((320,760),(390,844),(768,1024),(1440,960)):
            page.set_viewport_size({"width":width,"height":height})
            page.wait_for_timeout(120)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Overflow at {width}"
            assert page.get_by_role("button",name="直接下载",exact=False).is_visible()
            assert page.get_by_role("button",name="预览",exact=True).is_visible()
            if width in (390,1440):
                page.screenshot(path=str(artifacts / ("简洁版-手机结果.png" if width==390 else "简洁版-桌面结果.png")),full_page=True)
            results.append(width)
        rows.append({**sample,"id":"ui-failed","state":"failed","title":"未能解析的视频","message":"链接已失效，请重新复制分享链接。"})
        page.locator("#refresh-button").click()
        page.locator(".job[data-state=failed] .job-message").wait_for(state="visible")
        page.locator("#logout-button").click()
        page.locator("#login-panel").wait_for(state="visible")
        assert not errors, errors
        browser.close()
        print(json.dumps({"viewports":results,"horizontal_overflow":False,"login":True,"form_submission":True,"result_actions":True,"error_message":True,"logout":True,"js_errors":errors,"result_data":"synthetic UI fixtures"}))


if __name__ == "__main__":
    main()
