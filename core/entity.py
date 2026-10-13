"""core/entity.py — реквизиты юрлица и блок «Реквизиты» в подвал.

🔴 ЗАЧЕМ ОТДАВАТЬ ЭТО СЕРВЕРОМ, А НЕ РИСОВАТЬ СКРИПТОМ.
Закон Молдовы об электронной торговле (№ 284/2004) требует «лёгкого,
прямого и постоянного» доступа к сведениям о поставщике услуг: полное
наименование с организационно-правовой формой, IDNO, юридический адрес,
электронная почта и телефон, причём на румынском. Блок, который рисует
JavaScript, этому не отвечает: без JS его нет, а ИИ-краулеры JavaScript
не исполняют вовсе (это уже проверено на текстовом слое — им страница
глоссария была видна на 63 знака из 1497). Поэтому блок уходит в HTML
на сервере, как и навигация.

🔴 ВСТАВКА ОДНА НА ВСЕ СТРАНИЦЫ, А НЕ В ШАБЛОНАХ.
Тот же довод, что у навигации в serve.py: реквизиты нужны КАЖДОЙ
странице, а забытый в одном шаблоне блок глазами не виден. Семнадцать
шаблонов — семнадцать шансов забыть.

Факты лежат в web/data/entity.json (один источник), подписи — в i18n,
потому что подписи переводятся, а IDNO нет.
"""
from __future__ import annotations

import html as _html
import json
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
ФАЙЛ = КОРЕНЬ / "web/data/entity.json"

_кэш: dict | None = None


def данные() -> dict:
    """Реквизиты из entity.json. Читаются один раз за жизнь процесса:
    файл рукописный, крон его не переписывает."""
    global _кэш
    if _кэш is None:
        _кэш = json.loads(ФАЙЛ.read_text(encoding="utf-8"))
    return _кэш


def адрес(lang: str) -> str:
    д = данные()
    return д["адрес"].get(lang) or д["адрес"]["ru"]


def блок(lang: str, t) -> str:
    """HTML блока реквизитов. `t` — функция перевода i18n.t(ключ, lang).

    Порядок полей повторяет порядок в законе, чтобы при проверке было
    видно, что ничего не пропущено: наименование, IDNO, адрес, почта,
    телефон.
    """
    д = данные()
    э = _html.escape
    юр = э(д["юрлицо"]["краткое"])
    бренд = э(д["бренд"])
    почта = э(д["почта"])
    тел = э(д["телефон"])
    тел_url = э(д["телефон_tel"])

    # 🔴 Бренд и юрлицо названы ОДНОЙ фразой и рядом. Разведённые по
    # разным местам, они читаются как две разные компании — и человеком,
    # и ассистентом; именно это расхождение и пришлось объяснять в
    # llms.txt отдельной строкой.
    строки = [
        f'<strong>{бренд}</strong> — {t("req.brand_of", lang)} {юр}',
        f'IDNO {э(д["idno"])} · LEI {э(д["lei"])}',
        э(адрес(lang)),
        f'<a href="mailto:{почта}" style="color:inherit">{почта}</a>'
        f' · <a href="tel:{тел_url}" style="color:inherit">{тел}</a>',
    ]
    пункты = "".join(f"<div>{с}</div>" for с in строки)
    return (
        '<footer class="sbf-req" style="max-width:960px;margin:28px auto 0;'
        'padding:18px 14px calc(22px + env(safe-area-inset-bottom));'
        'border-top:1px solid var(--line,#E7DFCF);font-size:12px;line-height:1.7;'
        'color:var(--muted,#716A5A);font-family:Montserrat,sans-serif">'
        f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:.05em;color:var(--gold-text,#866A19);margin-bottom:6px">'
        f'{э(t("req.title", lang))}</div>'
        f'{пункты}'
        "</footer>"
    )
