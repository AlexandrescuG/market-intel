"""Собрать HTML всех 15 глав тем же кодом, что и сервер, — во временную папку.

Главы 6-15 закрыты пейволлом; замерять их надо не в обход гейта на живом
сайте, а собрав страницу локально. Файлы кладутся в /tmp и никуда не
публикуются.
"""
import sys
from pathlib import Path

ROOT = Path("/mnt/sbfdata/sbf-platform/market_intel")
sys.path.insert(0, str(ROOT))

import serve  # noqa: E402  (под __main__-гардом, сервер не поднимает)

OUT = Path("/tmp/sbf_audit_chapters")
OUT.mkdir(exist_ok=True)

serve._precompile_all()
for ch in range(1, 16):
    try:
        html = serve._build_edu_page(ch, "ru").decode("utf-8")
        (OUT / f"ch{ch}.html").write_text(html, encoding="utf-8")
        print(f"глава {ch}: {len(html)} символов")
    except Exception as e:
        print(f"глава {ch}: ОШИБКА {str(e)[:120]}", file=sys.stderr)
