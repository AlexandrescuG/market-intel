#!/usr/bin/env python3
"""
surprise_reaction.py — глава 6 «Пульс Новостей», §3.4 спеки
(SPEC_edu_level6_news_pulse.md). Соединяет прогноз/факт релизов (econ_events)
с уже измеренной реакцией цены (event_reactions, Layer1 Фаза 2) и считает
нормированный сюрприз — ядро главы.

Вход:  bot.db (econ_events, event_reactions, event_instrument_map, price_bars)
Выход: web/data/edu_stats/surprise_reaction.json

──────────────────────────────────────────────────────────────────────────────
ОТКЛОНЕНИЯ ОТ СПЕКИ, НАЙДЕННЫЕ РАЗВЕДКОЙ (тот же приём, что в build_ch2_
calendar_matrix.py и hourly_profile.py — сверяем реальные данные, а не
доверяем описанию спеки вслепую)
──────────────────────────────────────────────────────────────────────────────

1. Спека предполагает нормировку сюрприза на историю ОДНОГО event_key через
   econ_event_history. Проверено: у econ_event_history почти нет event_key с
   ≥12 наблюдениями (там хранятся РЕВИЗИИ одного конкретного релиза, а не
   серия релизов во времени). Настоящая серия по типу события лежит в самих
   econ_events (каждый месяц — новая строка с тем же нормализованным типом,
   но другим event_key). Поэтому стандартное отклонение сюрприза считается
   по группе normalize_event_type(indicator/title), а не по event_key.

2. Спека боялась суффиксов K/M/B/% в actual/forecast и просила парсер с учётом
   отброшенных строк. Проверено: 100% значений actual в econ_events — простые
   числа ("56.21", "-22.1"), без единого символа-суффикса. parse_failed_share
   в выходном JSON всё равно считается и публикуется честно, но парсер сейчас
   не отбрасывает почти ничего.

3. Найден и исправлен реальный баг в core/event_types.py: паттерн "non-farm"
   без слова "payroll"/уточнения ловил "Nonfarm Productivity QoQ" (другая
   единица измерения — % QoQ, не тысячи рабочих мест) в тот же ковш "nfp", что
   и настоящий Non Farm Payrolls. Затрагивает и живой event_reactions_job.py
   (Layer1) — не только эту главу. Пофикшено точечно (негативный lookahead на
   "productivity"), остальные написания (Payrolls, Employment Change, Private)
   остались в ковше.

4. weight в event_instrument_map для GOLD (US, CN) УЖЕ проставлен — в отличие
   от того, что писала спека §4.1 ("для золота связка неполная"). Проверено
   прямым SELECT. Ничего чинить в этой части не пришлось.

Запуск: python3 tools/edu_build/surprise_reaction.py
"""
import datetime
import json
import pathlib
import sqlite3
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
OUT = WEB / "data" / "edu_stats" / "surprise_reaction.json"
BOT_DB = pathlib.Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

sys.path.insert(0, str(ROOT))
from core.event_types import normalize_event_type  # noqa: E402

MIN_TYPE_HISTORY = 12       # минимум наблюдений в типе, чтобы считать sigma (спека §4.2)
MIN_CELL_N = 4               # порог показа клетки матрицы силы (как в предыдущих главах)
_SOURCE_PRIORITY = {"curated_official": 0, "forexfactory": 1, "tradingview": 2}
_CHART_TO_PRICE_BARS_SYMBOL = {"GOLD": "XAUUSD"}
_PIP_SCALE = {"EURUSD": 10000, "GBPUSD": 10000, "USDJPY": 100}

FRESH_SYMBOLS_FALLBACK = ["GOLD", "EURUSD", "USDJPY", "DXY", "SPX", "BTC"]


def _pip_scale(sym):
    return _PIP_SCALE.get(sym, 1)


def _numeric(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


RECENT_DAYS_FOR_RANGE = 250  # ~год торговых дней


def median_daily_range(con, symbol):
    """Медианный дневной диапазон по ПОСЛЕДНИМ ~году баров, не по всей истории.

    price_bars для XAUUSD тянется с 2018-го, когда золото стоило ~1300 -- за
    это время цена выросла более чем втрое (сейчас ~4000+), и абсолютные
    пункты дневного диапазона тех лет несравнимы с сегодняшними. Взятие
    медианы по всей истории занижало знаменатель в ~3-4 раза и раздувало
    move_30m_norm до абсурдных значений (>20 вместо честных долей единицы) --
    тот же класс проблемы, что нормировка по годам в hourly_profile.py
    (глава 5), найдено на первом же прогоне этого скрипта.
    """
    price_symbol = _CHART_TO_PRICE_BARS_SYMBOL.get(symbol, symbol)
    rows = con.execute(
        "SELECT h,l FROM price_bars WHERE symbol=? AND tf='1d' ORDER BY ts DESC LIMIT ?",
        (price_symbol, RECENT_DAYS_FOR_RANGE),
    ).fetchall()
    if not rows:
        return None
    # event_reactions.true_range уже домножен на _pip_scale(symbol) (см.
    # event_reactions_job.py) -- тот же множитель нужен и здесь, иначе для
    # FX-пар пипсовое true_range делится на "сырой" ценовой диапазон
    # (например 0.0123) и даёт абсурдные тысячи вместо честной доли.
    scale = _pip_scale(symbol)
    rngs = [(r["h"] - r["l"]) * scale for r in rows if r["h"] is not None and r["l"] is not None]
    return statistics.median(rngs) if rngs else None


def fetch_events(con):
    return con.execute("""
        SELECT event_key, country, title, indicator, actual, forecast, impact,
               scheduled_ts, source
        FROM econ_events
        WHERE actual IS NOT NULL AND actual != ''
          AND forecast IS NOT NULL AND forecast != ''
          AND scheduled_ts IS NOT NULL
        ORDER BY scheduled_ts ASC
    """).fetchall()


def dedup_by_day(rows):
    """Один релиз из нескольких источников (FF/TV) -- берём приоритетный,
    как в build_ch2_calendar_matrix.py и event_reactions_job.py."""
    groups = {}
    parse_failed = 0
    kept = []
    for r in rows:
        a, f = _numeric(r["actual"]), _numeric(r["forecast"])
        if a is None or f is None:
            parse_failed += 1
            continue
        day = r["scheduled_ts"] // 86400
        et = normalize_event_type(r["indicator"] or r["title"])
        key = (et, r["country"], day, r["indicator"] or r["title"])
        cur = groups.get(key)
        if cur is None or _SOURCE_PRIORITY.get(r["source"], 9) < _SOURCE_PRIORITY.get(cur["source"], 9):
            groups[key] = r
    kept = list(groups.values())
    return kept, parse_failed, len(rows)


def instrument_map(con):
    rows = con.execute("SELECT country, symbol, weight FROM event_instrument_map WHERE weight >= 1").fetchall()
    m = {}
    for r in rows:
        m.setdefault(r["country"], []).append(r["symbol"])
    return m


def event_reaction(con, event_key, symbol, release_ts, window):
    row = con.execute(
        "SELECT pips, true_range, dir, close_dir FROM event_reactions "
        "WHERE event_key=? AND symbol=? AND release_ts=? AND window=?",
        (event_key, symbol, release_ts, window),
    ).fetchone()
    return row


def main():
    con = sqlite3.connect(str(BOT_DB))
    con.row_factory = sqlite3.Row

    raw = fetch_events(con)
    deduped, parse_failed, total_raw = dedup_by_day(raw)
    print(f"события: {total_raw} строк -> {len(deduped)} после дедупа, {parse_failed} не распарсились")

    # ── stdev сюрприза по нормализованному типу (не по event_key -- см. docstring п.1)
    by_type_surprises = {}
    for r in deduped:
        et = normalize_event_type(r["indicator"] or r["title"])
        by_type_surprises.setdefault(et, []).append(_numeric(r["actual"]) - _numeric(r["forecast"]))

    type_std = {}
    for et, vals in by_type_surprises.items():
        if len(vals) >= MIN_TYPE_HISTORY:
            sd = statistics.pstdev(vals)
            if sd > 0:
                type_std[et] = sd
    print(f"типов событий с достаточной историей (n>={MIN_TYPE_HISTORY}): {len(type_std)} из {len(by_type_surprises)}")
    for et, sd in sorted(type_std.items(), key=lambda x: -len(by_type_surprises[x[0]]))[:12]:
        print(f"  {et}: n={len(by_type_surprises[et])} std={sd:.3f}")

    daily_range_cache = {}
    def get_range(sym):
        if sym not in daily_range_cache:
            daily_range_cache[sym] = median_daily_range(con, sym)
        return daily_range_cache[sym]

    imap = instrument_map(con)

    scatter = []
    strength_acc = {}  # (event_type, symbol) -> list of move_30m_norm
    dir_checks = []     # (predicted_down_on_beat, actual_dir) for GOLD only, per spec framing
    sim_candidates = {"big_positive": [], "big_negative": [], "zero": [], "dir_mismatch": []}

    for r in deduped:
        et = normalize_event_type(r["indicator"] or r["title"])
        sd = type_std.get(et)
        if sd is None:
            continue
        a, f = _numeric(r["actual"]), _numeric(r["forecast"])
        surprise = a - f
        surprise_sigma = surprise / sd
        symbols = imap.get(r["country"], [])
        for sym in symbols:
            rr = get_range(sym)
            if not rr:
                continue
            row30 = event_reaction(con, r["event_key"], sym, r["scheduled_ts"], "30m")
            if row30 is None:
                continue
            move_30m_norm = row30["true_range"] / rr if rr else None
            dir_match = None
            if sym == "GOLD" and abs(surprise_sigma) > 1e-9:
                predicted_dir = "down" if surprise > 0 else "up"
                dir_match = (row30["dir"] == predicted_dir)
                dir_checks.append(dir_match)
            scatter.append({
                "date": datetime.datetime.utcfromtimestamp(r["scheduled_ts"]).strftime("%Y-%m-%d"),
                "event_key": r["event_key"], "event_type": et,
                "title": r["indicator"] or r["title"], "symbol": sym,
                "surprise_sigma": round(surprise_sigma, 3),
                "move_30m_norm": round(move_30m_norm, 4) if move_30m_norm is not None else None,
                "dir_match": dir_match,
            })
            if move_30m_norm is not None:
                strength_acc.setdefault((et, sym), []).append(move_30m_norm)
            if sym == "GOLD" and move_30m_norm is not None:
                rec = {"event_key": r["event_key"], "date": datetime.datetime.utcfromtimestamp(r["scheduled_ts"]).strftime("%Y-%m-%d"),
                       "forecast": f, "actual": a, "surprise_sigma": round(surprise_sigma, 3),
                       "actual_move_30m": round(move_30m_norm, 4), "release_ts": r["scheduled_ts"]}
                if surprise_sigma > 1.5:
                    sim_candidates["big_positive"].append(rec)
                elif surprise_sigma < -1.5:
                    sim_candidates["big_negative"].append(rec)
                elif abs(surprise_sigma) < 0.15:
                    sim_candidates["zero"].append(rec)
                if dir_match is False and abs(surprise_sigma) > 0.8:
                    sim_candidates["dir_mismatch"].append(rec)

    print(f"scatter точек: {len(scatter)}")

    # ── bins по |surprise_sigma| (GOLD + всё вместе, как просит спека -- по модулю)
    bin_edges = [0, 0.5, 1.0, 1.5, 2.0, 99]
    bins = []
    for lo, hi in zip(bin_edges[:-1], bin_edges[1:]):
        vals = [abs(p["move_30m_norm"]) for p in scatter if p["move_30m_norm"] is not None and lo <= abs(p["surprise_sigma"]) < hi]
        bins.append({"from": lo, "to": (hi if hi < 99 else None), "median_move": round(statistics.median(vals), 4) if vals else None, "n": len(vals)})

    small = [abs(p["move_30m_norm"]) for p in scatter if p["move_30m_norm"] is not None and abs(p["surprise_sigma"]) < 0.5]
    large = [abs(p["move_30m_norm"]) for p in scatter if p["move_30m_norm"] is not None and abs(p["surprise_sigma"]) > 2.0]

    # ── by_impact
    by_impact = {"high": [], "medium": [], "low": []}
    for r in deduped:
        et = normalize_event_type(r["indicator"] or r["title"])
        if type_std.get(et) is None:
            continue
        imp = (r["impact"] or "low").lower()
        for sym in imap.get(r["country"], []):
            row30 = event_reaction(con, r["event_key"], sym, r["scheduled_ts"], "30m")
            if row30 is None:
                continue
            rr = get_range(sym)
            if not rr:
                continue
            mv = row30["true_range"] / rr
            by_impact.setdefault(imp, []).append(mv)
    by_impact_out = {}
    for k in ("high", "medium", "low"):
        vals = by_impact.get(k, [])
        if vals:
            vals_sorted = sorted(vals)
            n = len(vals_sorted)
            q1 = vals_sorted[n // 4]
            q3 = vals_sorted[(3 * n) // 4]
            by_impact_out[k] = {"median_move": round(statistics.median(vals_sorted), 4), "iqr": [round(q1, 4), round(q3, 4)], "n": n}
        else:
            by_impact_out[k] = {"median_move": None, "iqr": [None, None], "n": 0}

    # ── направление: доля совпадений знака (GOLD), Wilson CI95 как в главе 5
    def wilson(k, n, z=1.96):
        if n == 0:
            return [None, None]
        p = k / n
        d = 1 + z * z / n
        c = p + z * z / (2 * n)
        s = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5
        return [round(100 * (c - s) / d, 1), round(100 * (c + s) / d, 1)]

    n_dir = len(dir_checks)
    hits = sum(1 for x in dir_checks if x)
    hit_rate = round(100 * hits / n_dir, 1) if n_dir else None
    ci = wilson(hits, n_dir)
    if n_dir == 0:
        verdict = "coin_flip"
    elif ci[0] <= 50 <= ci[1]:
        verdict = "coin_flip"
    elif abs(hit_rate - 50) < 15:
        verdict = "weak_tilt"
    else:
        verdict = "strong_tilt"

    # ── матрица силы
    strength_matrix = []
    for (et, sym), vals in strength_acc.items():
        n = len(vals)
        strength_matrix.append({
            "event_type": et, "symbol": sym,
            "median_move": round(statistics.median(vals), 4) if n else None,
            "n": n, "shown": n >= MIN_CELL_N,
        })

    def pick(bucket, kind):
        """Берём медианный по |surprise_sigma| случай в корзине -- типичный, а
        не самый эффектный, тот же принцип, что в build_ch5_coldopen_day.py."""
        items = sim_candidates[bucket]
        if not items:
            return None
        items_sorted = sorted(items, key=lambda x: abs(x["surprise_sigma"]))
        chosen = items_sorted[len(items_sorted) // 2]
        return {**chosen, "kind": kind}

    sim_releases = []
    for bucket, kind in (("big_positive", "big_positive"), ("big_negative", "big_negative"),
                          ("zero", "zero"), ("dir_mismatch", "dir_mismatch")):
        c = pick(bucket, kind)
        if c:
            # достаём реальные свечи для симулятора из price_bars вокруг release_ts
            price_symbol = _CHART_TO_PRICE_BARS_SYMBOL.get("GOLD", "GOLD")
            rows = con.execute(
                "SELECT ts,o,h,l,c FROM price_bars WHERE symbol=? AND tf='30m' AND ts BETWEEN ? AND ? ORDER BY ts",
                (price_symbol, c["release_ts"] - 3600, c["release_ts"] + 3600 * 2),
            ).fetchall()
            c["candles"] = [{"time": datetime.datetime.utcfromtimestamp(x["ts"]).strftime("%Y-%m-%dT%H:%M:%SZ"),
                              "open": x["o"], "high": x["h"], "low": x["l"], "close": x["c"]} for x in rows]
            del c["release_ts"]
            sim_releases.append(c)

    con.close()

    coverage_first = min(r["scheduled_ts"] for r in deduped)
    coverage_last = max(r["scheduled_ts"] for r in deduped)

    payload = {
        "_meta": {
            "built": datetime.date.today().isoformat(),
            "coverage_first": datetime.datetime.utcfromtimestamp(coverage_first).strftime("%Y-%m-%d"),
            "coverage_last": datetime.datetime.utcfromtimestamp(coverage_last).strftime("%Y-%m-%d"),
            "coverage_days": (coverage_last - coverage_first) // 86400,
            "n_releases": len(scatter),
            "n_event_keys": len(set(p["event_key"] for p in scatter)),
            "parse_failed_share": round(parse_failed / total_raw, 4) if total_raw else 0.0,
            "windows": ["30m", "60m"],
            "note_not_measured": "спред в момент публикации не измерен — истории спреда нет",
            "min_cell_n": MIN_CELL_N,
        },
        "scatter": scatter,
        "bins": bins,
        "by_impact": by_impact_out,
        "direction": {"hit_rate": hit_rate, "n": n_dir, "ci95": ci, "verdict_key": verdict},
        "strength_matrix": strength_matrix,
        "sim_releases": sim_releases,
        "move_small_large": {
            "move_small": round(statistics.median(small), 4) if small else None, "n_small": len(small),
            "move_large": round(statistics.median(large), 4) if large else None, "n_large": len(large),
            "move_ratio": round(statistics.median(large) / statistics.median(small), 2) if small and large and statistics.median(small) else None,
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print(f"направление: hit_rate={hit_rate}% n={n_dir} CI95={ci} verdict={verdict}")
    print(f"матрица силы: {len(strength_matrix)} клеток, показано {sum(1 for x in strength_matrix if x['shown'])}")
    print(f"sim_releases: {[s['kind'] for s in sim_releases]}")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
