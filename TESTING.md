# 测试与验证

自动化测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check .\web\static\app.js
```

自动化测试使用本地 HTTP 测试服务器和合成元数据，不依赖抖音账户。测试覆盖链接提取、文件名、桌面下载完整性、认证、CSRF、输入限制，以及设备直连元数据和 HTTP 重定向。`video_stream.py` 为保留的历史模块，其测试不代表当前网页仍使用视频转发。

可选手动集成检查：

```powershell
# 先在另一个窗口启动 remote_app.py，再运行
.\.venv\Scripts\python.exe -m tests.browser_remote_check
.\.venv\Scripts\python.exe -m tests.visual_simple_check
.\.venv\Scripts\python.exe -m tests.public_remote_check 'https://你的实际访问地址'
```

浏览器集成检查依赖本机 Edge。真实下载测试会向抖音请求公开作品，可能要求人工登录或验证。界面检查使用合成结果数据。生成的样本、截图与日志保存在 `tests/artifacts`，不提交到仓库。

本项目在 Windows / Python 3.12 环境完成过 13 项自动化测试及 320、390、768、1440 像素宽度的界面检查。曾通过手机视口浏览器直接从视频源站下载约 6 MB 视频，本服务的视频入口仅返回 HTTP 302，没有代理视频正文。没有在所有手机系统、运营商、视频链接或不同 IP 上完成验证，源站限制和接口变化仍可能导致失败。
