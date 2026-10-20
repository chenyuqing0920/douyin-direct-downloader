"""Retain distribution notices alongside the Windows bundle."""
import importlib.metadata
import shutil
import sys
from pathlib import Path

target = Path(sys.argv[1]) / "第三方许可证"
for name in ("flask", "werkzeug", "jinja2", "markupsafe", "itsdangerous", "click", "blinker", "waitress", "qrcode", "pillow", "yt-dlp", "playwright", "pyee", "greenlet", "typing_extensions"):
    dist = importlib.metadata.distribution(name)
    for item in dist.files or []:
        if item.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")):
            source = Path(dist.locate_file(item))
            if source.is_file():
                folder = target / name
                folder.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, folder / item.name)
cloudflare_license = Path(__file__).parent / "cloudflared-LICENSE.txt"
if cloudflare_license.exists():
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cloudflare_license, target / "cloudflared-LICENSE.txt")
