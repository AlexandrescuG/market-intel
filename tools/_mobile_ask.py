"""Разовый вопрос открытой на телефоне вкладке: python3 tools/_mobile_ask.py <url> <js-файл>"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mobile_walk_device import Вкладка, устройство  # noqa: E402
import subprocess
import urllib.request

url = sys.argv[1]
js = Path(sys.argv[2]).read_text(encoding="utf-8")

d = устройство()
subprocess.run(["adb", "-s", d, "forward", "tcp:9222",
                "localabstract:chrome_devtools_remote"], check=False)
with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=6) as r:
    вкладки = json.load(r)
наши = [t for t in вкладки if t.get("type") == "page"
        and "sbfconsult.com" in t.get("url", "")]
if not наши:
    print("вкладки сайта не видно"); sys.exit(1)
в = Вкладка(наши[0]["webSocketDebuggerUrl"])
в.вызов("Page.navigate", url=url)
в.подождать(8)
о = в.вызов("Runtime.evaluate", expression=js, returnByValue=True)
print(о.get("result", {}).get("result", {}).get("value"))
