#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
factor_repack_job.py — WP1.5 SPEC_alpha_engine_implementation.md.

Переупаковка 9 существующих семейств факторов (проектная спека §3) в
`factor_store` (WP1.3). Джобы-источники продолжают писать в свои таблицы как
раньше — этот скрипт ТОЛЬКО читает их и добавляет запись в factor_values с
честным asof_ts. Ничего не пересчитывает заново.

Две категории по природе данных (решение Георгия 08.08 — см. Core-лог):

  A. Настоящий временной ряд, один бар -> одно значение, без lookahead:
     price (OHLCV/ATR из price_bars), calendar (econ_events — first_seen
     реальный), macro (FRED — _updated реальный).

  B. Агрегированная статистика, пересчитываемая ЦЕЛИКОМ джобом периодически
     (нет собственного per-bar ts): levels, pattern, vol, event-reaction,
     sentiment, news. Здесь используется "фото-снэпшот на последний бар":
     ts = ts последнего известного бара на момент записи, asof_ts = момент
     запуска ЭТОГО repack-прогона (не бар, не история — статистика "как
     она выглядит прямо сейчас"). История таких факторов не восстанавливается
     задним числом — она уже лежит в исходных таблицах (pattern_stats,
     sr_levels, ...), дублировать её в factor_values не входит в задачу.

Таблицы sr_levels/confluence_zones/pattern_stats/hourly_vol_profile/
day_thermo/event_reaction_stats ключуются КАНОНИЧЕСКИМ именем реестра
("GOLD"), не price_bars-именем ("XAUUSD") — см. WP1.2. factor_store,
наоборот, живёт в price_bars-пространстве (Acceptance WP1 явно использует
'XAUUSD'). Конвертация — alias_for(canonical, "price_bars") на входе в
каждую функцию ниже.

Использование:
  python3 factor_repack_job.py [--verbose]
"""
import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core import factor_store as fs
from core.symbols_registry import alias_for, _load as _load_registry
import core.price_bars as _price_bars

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
_SIGNALS_DB = Path("/mnt/sbfdata/sbf-platform/market_intel/data/signals.db")
_MACRO_JSON = Path(__file__).parent / "web" / "data" / "macro.json"


def _pb(canonical: str) -> str:
    return alias_for(canonical, "price_bars") or canonical


def _iso_to_ts(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


# ───────────────────────────────────────────── A. настоящий временной ряд ──

def repack_price(verbose=False) -> int:
    """price: ATR14, дневной диапазон, из price_bars. asof_ts = ts (закрытие
    бара) — ATR на баре i считается по барам <= i, честный ноль lookahead.

    🔴 Инкрементально: первая версия пересчитывала ВСЮ историю на каждый
    прогон — при ежедневном таймере это плодит новую ревизию на каждый бар
    каждый день без всякой пользы (пойман до продакшена: второй ручной
    прогон удвоил factor_values за секунды). Теперь только бары новее уже
    записанного максимума по (symbol,tf) -- 14 баров до него читаются
    заново для честного ATR-окна, но НЕ пишутся повторно."""
    fs.register_factor("price.atr14", "price", "ATR(14) на баре", "points",
                        tf_native="varies", source_job="factor_repack_job.repack_price")
    fs.register_factor("price.range", "price", "High-Low бара", "points",
                        tf_native="varies", source_job="factor_repack_job.repack_price")
    con = sqlite3.connect(str(_BOT_DB))
    con.execute("PRAGMA busy_timeout=60000")
    n = 0
    try:
        for pb_sym, tf in con.execute(
            "SELECT DISTINCT symbol, tf FROM price_bars"
        ).fetchall():
            last_done = con.execute(
                "SELECT MAX(ts) FROM factor_values WHERE symbol=? AND tf=? AND factor_key='price.range'",
                (pb_sym, tf)).fetchone()[0]
            if last_done is not None:
                seed = con.execute(
                    "SELECT ts FROM price_bars WHERE symbol=? AND tf=? AND ts<=? ORDER BY ts DESC LIMIT 14",
                    (pb_sym, tf, last_done)).fetchall()
                floor_ts = seed[-1][0] if len(seed) == 14 else 0
            else:
                floor_ts = 0
            rows = con.execute(
                "SELECT ts,h,l,c FROM price_bars WHERE symbol=? AND tf=? AND ts>=? ORDER BY ts ASC",
                (pb_sym, tf, floor_ts)).fetchall()
            if len(rows) < 15:
                continue
            batch = []
            trs = []
            prev_c = None
            for ts, h, l, c in rows:
                h, l, c = float(h), float(l), float(c)
                tr = max(h - l, abs(h - prev_c), abs(l - prev_c)) if prev_c is not None else h - l
                trs.append(tr)
                if len(trs) > 14:
                    trs.pop(0)
                atr = sum(trs) / len(trs) if len(trs) == 14 else None
                prev_c = c
                if last_done is not None and ts <= last_done:
                    continue  # только ATR-разогрев, уже записано раньше
                if atr is not None:
                    batch.append({"symbol": pb_sym, "tf": tf, "ts": ts,
                                  "factor_key": "price.atr14", "value": round(atr, 6), "asof_ts": ts})
                batch.append({"symbol": pb_sym, "tf": tf, "ts": ts,
                              "factor_key": "price.range", "value": round(h - l, 6), "asof_ts": ts})
            if batch:
                n += fs.put_many(batch)
            if verbose:
                print(f"  price {pb_sym} {tf}: +{len(batch)} новых значений")
    finally:
        con.close()
    return n


def repack_calendar(verbose=False) -> int:
    """calendar: минуты до релиза (по состоянию на момент самого релиза —
    т.е. знание "когда он случится" появляется по факту записи в econ_events,
    first_seen). Один "виртуальный бар" на событие -- ts=scheduled_ts,
    _GLOBAL по стране (события не привязаны к конкретному инструменту без
    отдельной event_instrument_map, которой в схеме нет)."""
    fs.register_factor("calendar.importance", "calendar", "impact релиза календаря", "ordinal",
                        source_job="factor_repack_job.repack_calendar")
    con = sqlite3.connect(str(_BOT_DB))
    con.execute("PRAGMA busy_timeout=60000")
    n = 0
    try:
        rows = con.execute(
            "SELECT country, scheduled_ts, impact, first_seen FROM econ_events "
            "WHERE scheduled_ts IS NOT NULL AND first_seen IS NOT NULL"
        ).fetchall()
        batch = []
        for country, ts, impact, first_seen in rows:
            try:
                ts_i = int(ts)
                asof = _iso_to_ts(first_seen) if isinstance(first_seen, str) else int(first_seen)
            except (ValueError, TypeError):
                continue
            imp_val = {"high": 3, "medium": 2, "low": 1}.get(str(impact).lower(), 0)
            symbol = f"{fs.GLOBAL_SYMBOL}.{country}" if country else fs.GLOBAL_SYMBOL
            batch.append({"symbol": symbol, "tf": "event", "ts": ts_i,
                          "factor_key": "calendar.importance", "value": imp_val, "asof_ts": asof})
        n = fs.put_many(batch)
        if verbose:
            print(f"  calendar: {n} событий")
    finally:
        con.close()
    return n


def repack_macro(verbose=False) -> int:
    """macro: FRED-серии (CPI, unemployment, Fed rate, 10Y-2Y, ...).
    _GLOBAL — макро не привязано к инструменту. ts = период, к которому
    относится значение (FRED "date"); asof_ts = когда МЫ его закешировали
    (_updated) — честно, потому что дата релиза статистики почти всегда
    позже периода, который она описывает."""
    if not _MACRO_JSON.exists():
        return 0
    d = json.loads(_MACRO_JSON.read_text())
    updated = d.get("_updated")
    if not updated:
        return 0
    asof = _iso_to_ts(updated)
    batch = []
    for series_id, entry in d.items():
        if series_id == "_updated" or not isinstance(entry, dict):
            continue
        date = entry.get("date")
        value = entry.get("value")
        if date is None or value is None:
            continue
        try:
            ts = int(datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
        fs.register_factor(f"macro.{series_id}", "macro", entry.get("label", series_id),
                            "index", source_job="factor_repack_job.repack_macro")
        batch.append({"symbol": fs.GLOBAL_SYMBOL, "tf": "1d", "ts": ts,
                      "factor_key": f"macro.{series_id}", "value": float(value), "asof_ts": asof})
    n = fs.put_many(batch)
    if verbose:
        print(f"  macro: {n} серий")
    return n


# ──────────────────────────────────────── B. агрегат, фото-снэпшот на бар ──

def _last_bar_ts(pb_sym: str, tf: str, con: sqlite3.Connection) -> int | None:
    row = con.execute(
        "SELECT MAX(ts) FROM price_bars WHERE symbol=? AND tf=?", (pb_sym, tf)
    ).fetchone()
    return row[0] if row else None


def repack_levels(now_ts: int, verbose=False) -> int:
    """levels: sr_levels (D1-только, см. sr_levels_job) + confluence_zones —
    снэпшот на последний D1-бар, asof_ts=сейчас (момент этого repack-прогона)."""
    fs.register_factor("levels.nearest_touches", "levels", "касания ближайшего S/R уровня",
                        "count", tf_native="1d", source_job="factor_repack_job.repack_levels",
                        history=False)
    fs.register_factor("levels.confluence_score", "levels", "максимальный скор зоны внимания",
                        "score", tf_native="1d", source_job="factor_repack_job.repack_levels",
                        history=False)
    con = sqlite3.connect(str(_BOT_DB))
    con.execute("PRAGMA busy_timeout=60000")
    n = 0
    try:
        for canonical in _price_bars.available_symbols("1d"):
            pb_sym = _pb(canonical)
            last_ts = _last_bar_ts(pb_sym, "1d", con)
            if last_ts is None:
                continue
            price_row = con.execute(
                "SELECT c FROM price_bars WHERE symbol=? AND tf='1d' ORDER BY ts DESC LIMIT 1", (pb_sym,)
            ).fetchone()
            price = float(price_row[0]) if price_row else None
            batch = []
            if price is not None:
                lvl = con.execute(
                    "SELECT price, touches FROM sr_levels WHERE symbol=? AND broken=0 "
                    "ORDER BY ABS(price-?) ASC LIMIT 1", (canonical, price)
                ).fetchone()
                if lvl:
                    batch.append({"symbol": pb_sym, "tf": "1d", "ts": last_ts,
                                  "factor_key": "levels.nearest_touches", "value": float(lvl[1]),
                                  "asof_ts": now_ts})
            zone = con.execute(
                "SELECT MAX(score) FROM confluence_zones WHERE symbol=?", (canonical,)
            ).fetchone()
            if zone and zone[0] is not None:
                batch.append({"symbol": pb_sym, "tf": "1d", "ts": last_ts,
                              "factor_key": "levels.confluence_score", "value": float(zone[0]),
                              "asof_ts": now_ts})
            n += fs.put_many(batch)
            if verbose and batch:
                print(f"  levels {canonical}->{pb_sym}: {len(batch)} значений")
    finally:
        con.close()
    return n


def repack_pattern(now_ts: int, verbose=False) -> int:
    """pattern: pattern_stats.agree_share_5 — снэпшот на последний бар ТФ,
    один factor_key на pattern_key (напр. pattern.bearish_engulfing.agree5)."""
    con = sqlite3.connect(str(_BOT_DB))
    con.execute("PRAGMA busy_timeout=60000")
    n = 0
    try:
        rows = con.execute(
            "SELECT pattern_key, symbol, tf, agree_share_5, n FROM pattern_stats "
            "WHERE agree_share_5 IS NOT NULL"
        ).fetchall()
        tf_map = {"H1": "1h", "H4": "4h", "D1": "1d"}
        batch = []
        seen_keys = set()
        for pattern_key, canonical, tf, agree5, pn in rows:
            pb_sym = _pb(canonical)
            pb_tf = tf_map.get(tf)
            if pb_tf is None:
                continue
            last_ts = _last_bar_ts(pb_sym, pb_tf, con)
            if last_ts is None:
                continue
            fkey = f"pattern.{pattern_key}.agree5"
            if fkey not in seen_keys:
                fs.register_factor(fkey, "pattern", f"согласованность {pattern_key} через 5 баров",
                                    "share", tf_native=tf, source_job="factor_repack_job.repack_pattern",
                                    history=False)
                seen_keys.add(fkey)
            batch.append({"symbol": pb_sym, "tf": pb_tf, "ts": last_ts,
                          "factor_key": fkey, "value": float(agree5), "asof_ts": now_ts})
        n = fs.put_many(batch)
        if verbose:
            print(f"  pattern: {n} значений ({len(seen_keys)} pattern_key)")
    finally:
        con.close()
    return n


def repack_vol(now_ts: int, verbose=False) -> int:
    """vol: hourly_vol_profile (типичный диапазон в ЭТОТ час суток) +
    day_thermo.range_pctl/dvol_pctl — снэпшот на последний бар."""
    fs.register_factor("vol.hourly_avg_range", "vol", "типичный диапазон этого часа (90д)",
                        "points", tf_native="30m", source_job="factor_repack_job.repack_vol",
                        history=False)
    fs.register_factor("vol.day_range_pctl", "vol", "перцентиль дневного диапазона", "pct",
                        tf_native="1d", source_job="factor_repack_job.repack_vol",
                        history=False)
    con = sqlite3.connect(str(_BOT_DB))
    con.execute("PRAGMA busy_timeout=60000")
    n = 0
    try:
        for canonical in _price_bars.available_symbols("30m"):
            pb_sym = _pb(canonical)
            last_ts = _last_bar_ts(pb_sym, "30m", con)
            if last_ts is None:
                continue
            hour_utc = datetime.fromtimestamp(last_ts, tz=timezone.utc).hour
            prof = con.execute(
                "SELECT avg_range FROM hourly_vol_profile WHERE symbol=? AND hour_utc=?",
                (canonical, hour_utc)).fetchone()
            batch = []
            if prof and prof[0] is not None:
                batch.append({"symbol": pb_sym, "tf": "30m", "ts": last_ts,
                              "factor_key": "vol.hourly_avg_range", "value": float(prof[0]),
                              "asof_ts": now_ts})
            thermo = con.execute(
                "SELECT range_pctl FROM day_thermo WHERE symbol=? ORDER BY ts DESC LIMIT 1",
                (canonical,)).fetchone()
            if thermo and thermo[0] is not None:
                d1_ts = _last_bar_ts(pb_sym, "1d", con)
                if d1_ts is not None:
                    batch.append({"symbol": pb_sym, "tf": "1d", "ts": d1_ts,
                                  "factor_key": "vol.day_range_pctl", "value": float(thermo[0]),
                                  "asof_ts": now_ts})
            n += fs.put_many(batch)
    finally:
        con.close()
    if verbose:
        print(f"  vol: {n} значений")
    return n


def repack_event_reaction(now_ts: int, verbose=False) -> int:
    """event-reaction: event_reaction_stats.baseline_ratio_30m — насколько
    типичная реакция на этот тип события превышает фоновую волатильность
    этого часа. Снэпшот на последний D1-бар (это свойство инструмента в
    целом, не конкретного internal бара)."""
    fs.register_factor("event_reaction.baseline_ratio_30m", "event-reaction",
                        "во сколько раз реакция на событие превышает фон часа", "ratio",
                        source_job="factor_repack_job.repack_event_reaction",
                        history=False)
    con = sqlite3.connect(str(_BOT_DB))
    con.execute("PRAGMA busy_timeout=60000")
    n = 0
    try:
        rows = con.execute(
            "SELECT symbol, AVG(baseline_ratio_30m) FROM event_reaction_stats "
            "WHERE baseline_ratio_30m IS NOT NULL GROUP BY symbol"
        ).fetchall()
        batch = []
        for canonical, avg_ratio in rows:
            pb_sym = _pb(canonical)
            last_ts = _last_bar_ts(pb_sym, "1d", con)
            if last_ts is None or avg_ratio is None:
                continue
            batch.append({"symbol": pb_sym, "tf": "1d", "ts": last_ts,
                          "factor_key": "event_reaction.baseline_ratio_30m",
                          "value": float(avg_ratio), "asof_ts": now_ts})
        n = fs.put_many(batch)
        if verbose:
            print(f"  event-reaction: {n} символов")
    finally:
        con.close()
    return n


def repack_sentiment(now_ts: int, verbose=False) -> int:
    """sentiment: sentiment_hourly.score — снэпшот последнего часа с данными.
    Покрытие сейчас тонкое (только BTC на момент внедрения WP1.5) — честно
    репакуется что есть, не выдумывается для остальных."""
    fs.register_factor("sentiment.score", "sentiment", "почасовой bull/bear score толпы",
                        "score", tf_native="1h", source_job="factor_repack_job.repack_sentiment",
                        history=False)
    con = sqlite3.connect(str(_BOT_DB))
    con.execute("PRAGMA busy_timeout=60000")
    n = 0
    try:
        rows = con.execute(
            "SELECT symbol, ts_hour, score FROM sentiment_hourly "
            "WHERE score IS NOT NULL ORDER BY ts_hour DESC"
        ).fetchall()
        seen = set()
        batch = []
        for sym, ts_hour, score in rows:
            if sym in seen:
                continue  # только последний час на символ
            seen.add(sym)
            try:
                ts_i = int(ts_hour) if not isinstance(ts_hour, str) else _iso_to_ts(ts_hour)
            except (ValueError, TypeError):
                continue
            batch.append({"symbol": sym, "tf": "1h", "ts": ts_i,
                          "factor_key": "sentiment.score", "value": float(score), "asof_ts": now_ts})
        n = fs.put_many(batch)
        if verbose:
            print(f"  sentiment: {n} символов")
    finally:
        con.close()
    return n


def repack_news(now_ts: int, verbose=False) -> int:
    """news: pulse_scores.score — только те тикеры pulse, что совпадают с
    нашим реестром (pulse покрывает широкий рынок акций, наш реестр — нет).
    news_bursts сейчас пуста (0 строк на момент внедрения) — честно, репак
    отдаёт 0 без выдумки."""
    fs.register_factor("news.pulse_score", "news", "интенсивность упоминаний cashtag", "score",
                        source_job="factor_repack_job.repack_news",
                        history=False)
    registry = _load_registry()
    known_pb_syms = {entry.get("price_bars", k) for k, entry in registry.items() if isinstance(entry, dict)}
    con_sig = sqlite3.connect(str(_SIGNALS_DB))
    con_sig.execute("PRAGMA busy_timeout=60000")
    n = 0
    try:
        rows = con_sig.execute(
            "SELECT symbol, ts, score FROM pulse_scores WHERE score IS NOT NULL ORDER BY ts DESC"
        ).fetchall()
        seen = set()
        batch = []
        for sym, ts, score in rows:
            if sym not in known_pb_syms or sym in seen:
                continue
            seen.add(sym)
            try:
                ts_i = int(ts) if not isinstance(ts, str) else _iso_to_ts(ts)
            except (ValueError, TypeError):
                continue
            batch.append({"symbol": sym, "tf": "event", "ts": ts_i,
                          "factor_key": "news.pulse_score", "value": float(score), "asof_ts": now_ts})
        n = fs.put_many(batch)
        if verbose:
            print(f"  news: {n} символов (из {len(rows)} строк pulse_scores, большинство вне реестра)")
    finally:
        con_sig.close()
    return n


def run(verbose: bool = False) -> dict:
    now_ts = int(time.time())
    results = {
        "price": repack_price(verbose),
        "calendar": repack_calendar(verbose),
        "macro": repack_macro(verbose),
        "levels": repack_levels(now_ts, verbose),
        "pattern": repack_pattern(now_ts, verbose),
        "vol": repack_vol(now_ts, verbose),
        "event_reaction": repack_event_reaction(now_ts, verbose),
        "sentiment": repack_sentiment(now_ts, verbose),
        "news": repack_news(now_ts, verbose),
    }
    if verbose:
        print("итог:", results, "всего:", sum(results.values()))
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    run(verbose=args.verbose)
