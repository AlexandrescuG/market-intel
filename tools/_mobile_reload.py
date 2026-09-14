"""Перезагрузить страницу на телефоне МИМО кэша и показать отказы сети.

🔴 Зачем отдельно. Статика отдаётся с Cache-Control: max-age=300, поэтому
проверка сразу после правки меряет старую копию скрипта и честно показывает
старую ошибку. Ждать пять минут — значит каждый раз гадать, дождался ли;
Page.reload с ignoreCache снимает вопрос.
"""
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mobile_walk_device import Вкладка, устройство  # noqa: E402

url = sys.argv[1]
d = устройство()
subprocess.run(["adb", "-s", d, "forward", "tcp:9222",
                "localabstract:chrome_devtools_remote"], check=False)
with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=6) as r:
    вкладки = json.load(r)
наши = [t for t in вкладки if t.get("type") == "page"
        and "sbfconsult.com" in t.get("url", "")]
if not наши:
    print("вкладки сайта не видно")
    sys.exit(1)

в = Вкладка(наши[0]["webSocketDebuggerUrl"])
в.вызов("Page.navigate", url=url)
в.подождать(6)
в.чисто()
в.вызов("Page.reload", ignoreCache=True)
в.подождать(12)
print(f"после перезагрузки без кэша: {url}")
print(f"  ошибок: {len(в.ошибки)}")
for e in в.ошибки[:5]:
    print("   ", e[:120])
print(f"  отказов: {len(в.отказы)}")
for o in в.отказы[:5]:
    print("   ", o[:120])
