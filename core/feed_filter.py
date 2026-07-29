"""P0-2 §2.2 — фильтр и маркер достоверности для домашней ленты сигналов
(publish_signals() -> signals.json -> renderSignals() на index.html).

Три правила из спеки, шаги 2-4:
  2. Маркер достоверности у каждой карточки: quotes / media / social_unverified
     -- тот же трёхзначный словарь, что уже даёт SPEC_morning_brief_v2.md §2
     блок 5 (см. analyze/prompt.md ALLOWED_CONFIDENCE, web/index.html confMap).
     "quotes" сюда не присваивается: у брифа это подтверждено СОБСТВЕННЫМ
     расчётом (ATR/аномалия), у сырого сигнала из RSS/твиттера такой проверки
     нет -- честно только media/social_unverified.
  3. Фильтр: без тикера -- не показывать; капс/BREAKING -- понижать в выдаче,
     не скрывать; политические маркеры -- отсекать. Пороги в JSON-конфиге,
     не в коде (feed_filter_config.json), чтобы точки отсечения можно было
     подвинуть без правки логики.
  4. Связка с отчётом: если сегодняшний brief_today.json пометил сюжет как
     social_unverified, а тикер сюжета совпадает с тикером карточки -- карточка
     наследует эту пометку (report_note). Проверено на реальных данных
     28.07.2026: контекст брифа "слух о продаже $1,25 млрд Биткоина китом не
     подтверждён" (confidence=social_unverified) -- ровно пример из спеки.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from core.config import BASE_DIR
from core.credibility import is_tier1_source

_CONFIG_PATH = Path(__file__).with_name("feed_filter_config.json")
_BRIEF_PATH = BASE_DIR / "web" / "data" / "brief_today.json"

_DEFAULT_CONFIG = {
    "require_cashtag": True,
    "caps_ratio_downrank": 0.5,
    "caps_min_letters": 12,
    "breaking_keywords": ["BREAKING", "СРОЧНО", "URGENT", "ALERT", "ВНИМАНИЕ"],
    "political_keywords": [],
}

# Ограниченный, явно неполный список алиасов тикер -> корни слов для сопоставления
# с прозой брифа (там "Биткоин", а не "BTC"). Раздутый NLP-матчер тут избыточен --
# это вспомогательная UI-пометка, а не источник истины; список можно пополнять.
_CASHTAG_ALIASES = {
    "BTC": ["биткоин", "bitcoin"],
    "ETH": ["эфир", "ethereum"],
    "SOL": ["солана", "solana"],
    "XRP": ["рипл", "ripple", "xrp"],
    "GOLD": ["золот", "\\bgold\\b", "\\bxau\\b"],
    "SILVER": ["серебр", "\\bsilver\\b", "\\bxag\\b"],
    "WTI": ["нефт", "\\boil\\b", "\\bwti\\b"],
    "EURUSD": ["\\beur\\b", "евро"],
    "GBPUSD": ["\\bgbp\\b", "фунт"],
    "SPX": ["s&p", "спондап", "\\bspx\\b"],
    "NASDAQ": ["nasdaq", "насдак"],
    "DXY": ["\\bdxy\\b", "доллар"],
}


def load_config() -> dict:
    try:
        cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    return {**_DEFAULT_CONFIG, **cfg}


def confidence_for(source: str, author: str) -> str:
    if source == "rss" or is_tier1_source(author):
        return "media"
    return "social_unverified"


def _is_press_or_tier1(it: dict) -> bool:
    """SPEC_site_fixes_2026-07-29 §6 п.2: правило require_cashtag писалось
    против анонимных твиттер-аккаунтов -- к Reuters/BBC оно неприменимо.
    Тот же критерий, что уже использует confidence_for() (rss ИЛИ tier1-твиттер),
    переиспользуется тут и как критерий квоты изданий (п.1)."""
    return it.get("source") == "rss" or is_tier1_source(it.get("author"))


def _caps_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 1:
        return 0.0
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters)


def _is_shouty(text: str, cfg: dict) -> bool:
    if any(kw in text for kw in cfg["breaking_keywords"]):
        return True
    letters = [c for c in text if c.isalpha()]
    if len(letters) < cfg["caps_min_letters"]:
        return False
    return _caps_ratio(text) >= cfg["caps_ratio_downrank"]


def _is_political(text: str, cfg: dict) -> bool:
    low = text.lower()
    # \b, не голое "in": короткие ключи вроде "war" иначе ловят "warning" —
    # \b в Python re работает и на кириллице (граница по \w).
    return any(re.search(r"\b" + re.escape(kw.lower()) + r"\b", low) for kw in cfg["political_keywords"])


def _load_unverified_report_terms() -> list[str]:
    """Тексты context-пунктов сегодняшнего брифа с confidence=social_unverified —
    против них ищем совпадение по тикеру (см. _CASHTAG_ALIASES)."""
    try:
        brief = json.loads(_BRIEF_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [c["text"] for c in (brief.get("context") or []) if c.get("confidence") == "social_unverified"]


def _report_flag_for(cashtags: list[str], unverified_texts: list[str]) -> str | None:
    for tag in cashtags:
        patterns = _CASHTAG_ALIASES.get(tag.upper())
        if not patterns:
            continue
        for text in unverified_texts:
            low = text.lower()
            if any(re.search(p, low) for p in patterns):
                return text
    return None


def apply_feed_rules(items: list[dict], limit: int, require_cashtag: bool | None = None,
                      press_quota: int = 0) -> list[dict]:
    """items -- вывод _sig() из publish.py (source, author, text, cashtags, ...).
    Возвращает отфильтрованный, помеченный и переупорядоченный список, уже
    обрезанный до `limit`.

    require_cashtag: переопределяет конфиг для конкретного измерения ленты.
    [ДОПУЩЕНИЕ] Литеральное "без тикера — не показывать" применено только к
    economy/crowd (publish.py) -- проверка на реальных данных 28.07.2026
    показала, что измерение geopolitics структурно СОСТОИТ из новостей без
    финансового тикера (Нетаньяху/Иран/санкции и т.п. -- контекст риска, а не
    сигнал по конкретному инструменту): 0 из 48 сырых записей имели cashtags.
    Применить требование тут буквально значило бы полностью обнулить вкладку
    геополитики, а не убрать мусор -- это регрессия рабочей фичи, не фикс.
    Политический фильтр и понижение капса/BREAKING применяются везде, включая
    geopolitics -- это и есть настоящая цель находки (см. пример спеки).

    press_quota (SPEC_site_fixes_2026-07-29 §6 п.1): минимум столько позиций
    от прессы/tier1 в результате, даже если ранжирование по importance их
    вытеснило -- ранжированием эту задачу не решить, пока RSS структурно не
    имеет вовлечённости. 0 (по умолчанию) -- поведение не меняется, для
    измерений, где пресса не ожидается (напр. "Соцсети" -- см. §7: вкладка
    сознательно осталась чисто социальной, квота была бы противоречием)."""
    cfg = load_config()
    need_cashtag = cfg["require_cashtag"] if require_cashtag is None else require_cashtag
    unverified_texts = _load_unverified_report_terms()

    kept, shouty = [], []
    for it in items:
        cashtags = it.get("cashtags") or []
        press = _is_press_or_tier1(it)
        if need_cashtag and not cashtags and not press:
            continue
        text = it.get("text") or ""
        if _is_political(text, cfg):
            continue

        it = dict(it)
        it["confidence"] = confidence_for(it.get("source"), it.get("author"))
        flag = _report_flag_for(cashtags, unverified_texts)
        if flag:
            it["report_note"] = flag

        (shouty if _is_shouty(text, cfg) else kept).append(it)

    ordered = kept + shouty
    result = ordered[:limit]

    if press_quota:
        press_in_result = sum(1 for it in result if _is_press_or_tier1(it))
        if press_in_result < press_quota:
            need = press_quota - press_in_result
            extra_press = [it for it in ordered[limit:] if _is_press_or_tier1(it)][:need]
            if extra_press:
                non_press_idx = [i for i, it in enumerate(result) if not _is_press_or_tier1(it)]
                drop_n = min(len(extra_press), len(non_press_idx))
                drop_idx = set(non_press_idx[-drop_n:]) if drop_n else set()
                result = [it for i, it in enumerate(result) if i not in drop_idx] + extra_press

    return result
