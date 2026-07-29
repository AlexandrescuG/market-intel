#!/usr/bin/env python3
"""
analyze/build_brief_v2.py — SPEC_morning_brief_v2.md: детерминированный сборщик
блоков 1 (календарь), 2 (отчётности), 3 (вчера вне своей нормы), 4 (фигуры).

Ничего здесь не решает языковая модель — все числа посчитаны кодом. Пишет
web/data/brief_today.json. Блок 5 (заголовок + 3 пункта контекста) дописывает
analyze/llm_context.py ПОВЕРХ уже написанного этим скриптом файла (см.
run_daily.sh, шаги 1b/4).

Блок 6 ("Твоё") сюда сознательно НЕ входит: это персональные данные одного
пользователя, они не могут жить в одном статическом файле, который отдаётся
всем посетителям сайта одинаково (тот же путь, что market.json/report.json —
без авторизации). Блок 6 остаётся отдельным живым запросом к
/api/journal/brief (core/journal_brief.py), как и раньше.

build_brief.py (старый, сырой соцдайджест) НЕ заменяется этим файлом — он
по-прежнему нужен и для сырого дайджеста, который читает llm_context.py/
prompt.md, и для секции "В ФОКУСЕ СЕГОДНЯ", от которой зависит уже живая
карточка "В фокусе" (renderFocusCard()). Оба остаются в run_daily.sh.

Использование:
  python3 -m analyze.build_brief_v2 [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import BASE_DIR                                    # noqa: E402
from core.calendar_api import query_events, instruments_for_country, _BOT_DB  # noqa: E402
from core.event_types import normalize_event_type                   # noqa: E402
from core.movers import full_universe_moves                         # noqa: E402
from core.focus import DEFAULT_UNIVERSE                              # noqa: E402
from core.patterns import PATTERNS                                  # noqa: E402
from pattern_stats_job import _load_candles                         # noqa: E402
from core.patterns import detect                                    # noqa: E402

WEB_DATA = BASE_DIR / "web" / "data"

CALENDAR_CAP = 6
MOVERS_CAP = 3
PATTERNS_CAP = 4
MIN_REACTION_N = 5
MIN_PATTERN_N = 15
MOVERS_STALE_DAYS = 3   # старше -- не "вчера", а дыра в MT5-фиде (см. docs/BRIEF_V2_PROGRESS.md)

_CALENDAR_TERMS_JS = BASE_DIR / "web" / "edu" / "assets" / "calendar-terms.js"
_INDICATOR_KEY_RE = re.compile(r'^\s*"((?:[^"\\]|\\.)*)":\s*\{', re.MULTILINE)
_GOV_SPEECH_RE = re.compile(r'^(\S+) Gov (\S+) (Speech|Speaks)$')
_SPEECH_SUFFIX_RE = re.compile(r'\s+(Speech|Speaks|Speak)$', re.IGNORECASE)


@lru_cache(maxsize=1)
def _known_indicators() -> frozenset[str]:
    """Ключи CALENDAR_TERMS (web/edu/assets/calendar-terms.js) -- источник
    истины для перевода названий календаря на фронте (translatedEventName()).
    Файл -- JS, не JSON (ru/ro тут голые идентификаторы, не строки), поэтому
    не json.loads, а regex по кавычкам верхнего уровня словаря; для
    диагностики "есть ли перевод" этого достаточно, полный JS-парсер не нужен."""
    try:
        text = _CALENDAR_TERMS_JS.read_text(encoding="utf-8")
    except OSError:
        return frozenset()
    return frozenset(m.group(1) for m in _INDICATOR_KEY_RE.finditer(text))


def _has_translation(indicator: str | None) -> bool:
    """Зеркалит ветвление translatedEventName() в calendar-terms.js: словарь,
    либо служебный catch-all 'Calendar', либо общий шаблон речей глав ЦБ
    (SPEC_site_fixes_2026-07-29 §2 п.4, _govSpeechFallback на фронте)."""
    if not indicator or indicator == "Calendar":
        return True
    if indicator in _known_indicators():
        return True
    return bool(_GOV_SPEECH_RE.match(indicator))


def _dedup_key(e: dict) -> tuple:
    """Источник календаря иногда шлёт одно и то же событие дважды под разными
    indicator (найдено: "RBA Gov Bullock Speech" и "RBA Gov Bullock Speaks" в
    одну и ту же минуту -- разный глагол, то же событие). Схлопываем по
    (страна, время, нормализованная метка без разницы Speech/Speaks/Speak)."""
    label = (e.get("indicator") or e.get("title") or "").strip()
    label = _SPEECH_SUFFIX_RE.sub(" Speech", label).lower()
    return (e.get("country"), e.get("ts_utc") or e.get("scheduled_ts"), label)


def _today_str(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d")


def _reaction_stats(event_type: str, symbols: list[str]) -> dict | None:
    """Лучшая (наибольший n) статистика реакции среди инструментов события.
    n<5 -- median_atr_30m обнуляется (спека: "мало данных", не число), n сам
    остаётся -- пригодится, если фронт захочет показать "мало данных (n=3)"."""
    if not symbols:
        return None
    con = sqlite3.connect(str(_BOT_DB))
    con.row_factory = sqlite3.Row
    try:
        best = None
        for sym in symbols:
            row = con.execute(
                """SELECT n, median_atr_30m FROM event_reaction_stats
                   WHERE event_type=? AND symbol=? ORDER BY n DESC LIMIT 1""",
                (event_type, sym),
            ).fetchone()
            if row and (best is None or row["n"] > best["n"]):
                best = {"symbol": sym, "n": row["n"], "median_atr_30m": row["median_atr_30m"]}
    finally:
        con.close()
    if best and best["n"] < MIN_REACTION_N:
        best["median_atr_30m"] = None
    return best


def build_calendar_block(today: str) -> tuple[list[dict], int, list[str]]:
    """Блок 1. Возвращает (топ-N строк, число ещё оставшихся низкой важности,
    индикаторы без перевода в CALENDAR_TERMS -- SPEC_site_fixes_2026-07-29 §2)."""
    all_today = query_events(date=today, limit=200)
    high_med = [e for e in all_today if e.get("impact") in ("high", "medium")]
    high_med.sort(key=lambda e: e.get("scheduled_ts") or 0)

    deduped = []
    seen = set()
    for e in high_med:
        key = _dedup_key(e)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)

    untranslated = sorted({
        e["indicator"] for e in deduped
        if e.get("indicator") and not _has_translation(e.get("indicator"))
    })

    rows = []
    for e in deduped[:CALENDAR_CAP]:
        symbols = instruments_for_country(e["country"], min_weight=1)
        etype = normalize_event_type(e.get("indicator") or e.get("title") or "")
        rows.append({
            "ts_utc": e.get("ts_utc"),
            "scheduled_ts": e.get("scheduled_ts"),
            "country": e["country"],
            "title": e.get("title"),
            "indicator": e.get("indicator"),
            "impact": e.get("impact"),
            "forecast": e.get("forecast"),
            "previous": e.get("previous"),
            "symbols": symbols,
            "past_reaction": _reaction_stats(etype, symbols),
        })
    return rows, max(0, len(deduped) - CALENDAR_CAP), untranslated


def _event_for_symbol_on(day: str, symbol: str) -> dict | None:
    """Было ли вчера high/medium-событие, влияющее на symbol (weight>=1)?
    Для саб-строки блока 3 ("на релизе X в 15:30" / "без события в календаре")."""
    day_events = [e for e in query_events(date=day, limit=200)
                  if e.get("impact") in ("high", "medium")]
    for e in day_events:
        if symbol in instruments_for_country(e["country"], min_weight=1):
            return {"title": e.get("title"), "ts_utc": e.get("ts_utc")}
    return None


def build_movers_block(today: str) -> dict:
    """Блок 3. Сортировка по ratio (отклонение от своей нормы), не по %."""
    moves = full_universe_moves(DEFAULT_UNIVERSE, today)
    cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=MOVERS_STALE_DAYS)).strftime("%Y-%m-%d")
    moves = [m for m in moves if m["bar_date"] >= cutoff and m["ratio"] is not None]

    up = sorted([m for m in moves if m["chg_pct"] > 0], key=lambda m: m["ratio"], reverse=True)[:MOVERS_CAP]
    down = sorted([m for m in moves if m["chg_pct"] < 0], key=lambda m: m["ratio"], reverse=True)[:MOVERS_CAP]

    for m in up + down:
        m["event"] = _event_for_symbol_on(m["bar_date"], m["symbol"])

    return {"up": up, "down": down}


def build_patterns_block(today: str, symbols: list[str] | None = None) -> list[dict]:
    """Блок 4. Только паттерн на ПОСЛЕДНЕМ ЗАКРЫТОМ D1-баре (не вся история и
    не сегодняшняя ещё формирующаяся свеча -- publish.py обновляет
    ohlc_*_D1.json каждые 5 мин круглосуточно, см. core.focus.wilder_atr's
    as_of_date) и только со статистикой n>=15 -- иначе это уже сигнал, не факт
    (см. спеку §2)."""
    symbols = symbols or DEFAULT_UNIVERSE
    con = sqlite3.connect(str(_BOT_DB))
    con.row_factory = sqlite3.Row
    out = []
    try:
        for sym in symbols:
            candles = _load_candles(sym, "D1")
            if not candles:
                continue
            closed = [c for c in candles
                      if datetime.fromtimestamp(c["ts"], tz=timezone.utc).strftime("%Y-%m-%d") < today]
            if len(closed) < 20:
                continue
            events = detect(closed)
            if not events:
                continue
            last_ts = closed[-1]["ts"]
            recent = [e for e in events if e["ts"] == last_ts]
            for e in recent:
                row = con.execute(
                    """SELECT n, agree_share_5 FROM pattern_stats
                       WHERE pattern_key=? AND symbol=? AND tf='D1'""",
                    (e["pattern_key"], sym),
                ).fetchone()
                if not row or row["n"] < MIN_PATTERN_N:
                    continue  # без статистики паттерн не показываем вовсе (спека §2, §5)
                out.append({
                    "symbol": sym, "tf": "D1",
                    "pattern_key": e["pattern_key"],
                    "display_name_ru": PATTERNS.get(e["pattern_key"], {}).get("display_name_ru", e["pattern_key"]),
                    "direction": e["direction"],
                    "ts": e["ts"],
                    "agree_share_5": row["agree_share_5"],
                    "n": row["n"],
                })
    finally:
        con.close()
    out.sort(key=lambda r: (r["ts"], r["n"]), reverse=True)
    return out[:PATTERNS_CAP]


def _crowd_mentions_24h(limit: int = 40) -> set[str]:
    """cashtag_heatmap уже есть (core/db.py) -- тикеры, о которых пишут в
    соцсетях за 24ч. Обёрнуто в try/except: signals.db периодически
    залочен конкурентными коллекторами (проверено эмпирически), транзиентная
    ошибка здесь не должна валить весь бриф."""
    try:
        from core.db import cashtag_heatmap
        return {t for t, _cnt, _imp in cashtag_heatmap(24, limit=limit)}
    except Exception:
        return set()


def build_earnings_block(today: str) -> list[dict]:
    """Блок 2, вариант A (SPEC_morning_brief_v2.md §2, [РЕШЕНИЕ]): ручной
    web/data/earnings_calendar.json, схема полей совместима с будущей
    earnings_events (вариант B). Файла может не быть или быть пустым -- тогда
    блок пуст, никаких выдуманных тикеров (см. docs/BRIEF_V2_PROGRESS.md).

    Правило «интересных» (спека §2): пересечение крупной капитализации
    (market_cap_rank в файле, меньше = крупнее) и упоминаний в соцсетях за
    24ч (cashtag_heatmap). Ватчлист пользователя сюда НЕ входит -- это
    глобальный файл без авторизации (см. build_patterns_block же решение);
    персонализация — дело фронтенда/Блока 6, не этого файла. Если
    пересечение пусто -- просто крупнейшие по капитализации из отчитывающихся.
    """
    f = WEB_DATA / "earnings_calendar.json"
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    tomorrow = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    rows = [r for r in data.get("earnings", []) if r.get("report_date") in (today, tomorrow)]
    if not rows:
        return []

    mentioned = _crowd_mentions_24h()
    interesting = [r for r in rows if r.get("ticker", "").upper() in mentioned]
    pool = interesting if interesting else rows

    pool.sort(key=lambda r: (r.get("report_date"),
                              0 if r.get("session") == "pre" else 1,
                              r.get("market_cap_rank") if r.get("market_cap_rank") is not None else 9999))
    return pool[:5]


def build(date: str | None = None) -> dict:
    today = date or _today_str()

    calendar_rows, calendar_more, calendar_untranslated = build_calendar_block(today)
    earnings_rows = build_earnings_block(today)
    movers = build_movers_block(today)
    pattern_rows = build_patterns_block(today)

    empty_blocks = []
    if not calendar_rows:
        empty_blocks.append("calendar")
    if not earnings_rows:
        empty_blocks.append("earnings")
    if not movers["up"] and not movers["down"]:
        empty_blocks.append("movers")
    if not pattern_rows:
        empty_blocks.append("patterns")

    return {
        "date": today,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "calendar": calendar_rows,
        "calendar_more": calendar_more,
        "untranslated": calendar_untranslated,
        "earnings": earnings_rows,
        "movers": movers,
        "patterns": pattern_rows,
        "_meta": {
            "empty_blocks": empty_blocks,
            "sources": {
                "calendar": "econ_events + event_reaction_stats (bot.db)",
                "earnings": "web/data/earnings_calendar.json (ручной, вариант A)",
                "movers": "ohlc_{symbol}_D1.json + core.focus.yesterday_deviation",
                "patterns": "core.patterns.detect() + pattern_stats (bot.db), n>=15",
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="YYYY-MM-DD, по умолчанию сегодня UTC")
    args = parser.parse_args()

    payload = build(args.date)
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    out = WEB_DATA / "brief_today.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"build_brief_v2: wrote {out} "
          f"(calendar={len(payload['calendar'])}, earnings={len(payload['earnings'])}, "
          f"movers up/down={len(payload['movers']['up'])}/{len(payload['movers']['down'])}, "
          f"patterns={len(payload['patterns'])}, empty={payload['_meta']['empty_blocks']})",
          file=sys.stderr)
    if payload["untranslated"]:
        print(f"build_brief_v2: WARNING calendar indicators without a translation "
              f"in calendar-terms.js: {payload['untranslated']}", file=sys.stderr)


if __name__ == "__main__":
    main()
