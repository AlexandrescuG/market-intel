#!/usr/bin/env python3
"""
confluence_job.py — SBF_Charts_Layer2_Spec, Фаза 2 («зоны внимания»).

Офлайн-джоб (раз в сутки вслед за sr_levels_job.py — конфлюэнс использует
исторические уровни Фазы 1, + пивоты меняются раз в период тоже раз в сутки
на D1): чистая агрегация уже посчитанных факторов (уровень / пивот / круглое
число / недельный-месячный экстремум) в зоны повышенного внимания рынка.

Использование:
  python3 confluence_job.py [--verbose]
"""
import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sr_levels_job import _load_d1_candles, _atr14, _WEB_DATA

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

CLUSTER_WINDOW_ATR_MULT = 0.3
ZONE_MIN_SCORE = 2.5
MAX_ZONES = 4
MAX_DIST_ATR_MULT = 3
LEVEL_MIN_TOUCHES = 3

# Шаг "круглого числа" на инструмент — фигуры для форекса, кратные для
# остальных (см. Фаза 2 спеки). Инструменты без записи здесь просто не
# участвуют в этом факторе (не критично — остальные 3 фактора работают).
ROUND_STEP = {
    "EURUSD": 0.0050, "GBPUSD": 0.0050, "USDJPY": 0.50, "DXY": 0.50,
    "GOLD": 50, "SILVER": 1,
    "SPX": 100, "NASDAQ": 100, "DJI": 100, "VIX": 5,
    "BTC": 1000, "ETH": 100, "SOL": 10,
    "WTI": 5, "NG": 0.5,
    "USDRUB": 1, "USDKZT": 10, "USDZAR": 1, "USDCNY": 0.1, "USDAED": 0.1,
}


def _sr_levels(symbol: str):
    con = sqlite3.connect(str(_BOT_DB))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT price, touches FROM sr_levels WHERE symbol=? AND broken=0 AND touches>=?",
            (symbol, LEVEL_MIN_TOUCHES),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    con.close()
    return [(r["price"], 1.0, "level", {"touches": r["touches"]}) for r in rows]


def _pivot_factors(symbol: str):
    f = _WEB_DATA / f"ohlc_{symbol}_D1.json"
    if not f.exists():
        return []
    try:
        levels = json.loads(f.read_text()).get("levels") or []
    except (json.JSONDecodeError, OSError):
        return []
    weight = {"PP": 1.0, "S1": 1.0, "R1": 1.0, "S2": 0.5, "R2": 0.5}
    out = []
    for L in levels:
        w = weight.get(L.get("name"))
        if w is None:
            continue
        out.append((L["price"], w, "pivot", {"name": L["name"]}))
    return out


def _round_number_factors(symbol: str, price: float, atr: float):
    step = ROUND_STEP.get(symbol)
    if not step:
        return []
    span = atr * MAX_DIST_ATR_MULT
    lo, hi = price - span, price + span
    start = (lo // step) * step
    out = []
    n = start
    while n <= hi:
        if lo <= n <= hi:
            out.append((n, 1.0, "round", None))
        n += step
    return out


def _week_month_extremes(candles):
    """High/low прошлой ЗАВЕРШЁННОЙ недели и месяца (не текущей незакрытой)."""
    out = []
    by_week, by_month = {}, {}
    for c in candles:
        d = datetime.fromtimestamp(c["ts"], timezone.utc).date()
        wk = (d.isocalendar()[0], d.isocalendar()[1])
        mo = (d.year, d.month)
        by_week.setdefault(wk, []).append(c)
        by_month.setdefault(mo, []).append(c)
    weeks = sorted(by_week.keys())
    months = sorted(by_month.keys())
    if len(weeks) >= 2:
        wk_candles = by_week[weeks[-2]]  # последняя ЗАВЕРШЁННАЯ неделя
        out.append((max(c["h"] for c in wk_candles), 1.0, "week_high", None))
        out.append((min(c["l"] for c in wk_candles), 1.0, "week_low", None))
    if len(months) >= 2:
        mo_candles = by_month[months[-2]]
        out.append((max(c["h"] for c in mo_candles), 1.0, "month_high", None))
        out.append((min(c["l"] for c in mo_candles), 1.0, "month_low", None))
    return out


def _cluster_factors(points, window):
    """points: [(price, weight, kind, params)] -> жадная кластеризация по ЯКОРЮ
    (первому элементу кластера), не по последнему добавленному — см. фикс
    того же бага в sr_levels_job.py._cluster: цепочка по последнему элементу
    даёт неограниченно широкие кластеры при плотных равномерных факторах
    (типичный случай — пивоты примерно равноудалены друг от друга)."""
    pts = sorted(points, key=lambda p: p[0])
    clusters, cur = [], None
    for p in pts:
        if cur and (p[0] - cur[0][0]) <= window:
            cur.append(p)
        else:
            cur = [p]
            clusters.append(cur)
    return clusters


def compute_symbol(symbol: str, verbose=False):
    candles = _load_d1_candles(symbol)
    if not candles or len(candles) < 20:
        return []
    atr = _atr14(candles)
    if not atr:
        return []
    price = candles[-1]["c"]

    factors = []
    factors += _sr_levels(symbol)
    factors += _pivot_factors(symbol)
    factors += _round_number_factors(symbol, price, atr)
    factors += _week_month_extremes(candles)
    if not factors:
        return []

    window = atr * CLUSTER_WINDOW_ATR_MULT
    clusters = _cluster_factors(factors, window)

    max_dist = atr * MAX_DIST_ATR_MULT
    zones = []
    for cluster in clusters:
        score = sum(w for _, w, _, _ in cluster)
        if score < ZONE_MIN_SCORE:
            continue
        price_low = min(p for p, _, _, _ in cluster)
        price_high = max(p for p, _, _, _ in cluster)
        mid = (price_low + price_high) / 2
        if abs(mid - price) > max_dist:
            continue
        # Раньше факторы схлопывались в готовые русские строки ("Пивот PP")
        # и цена внутри каждого фактора терялась -- карточка могла показать
        # только название, не число (SPEC_chart_fixes_and_staged_signup.md §1).
        # kind — машиночитаемый тип для перевода на фронте (i18n, 3 языка),
        # params — что нужно этому типу для форматирования строки.
        factors = [
            {"price": round(p, 6), "kind": kind, **({"params": params} if params else {})}
            for p, _, kind, params in cluster
        ]
        zones.append({
            "symbol": symbol, "price_low": round(price_low, 6), "price_high": round(price_high, 6),
            "score": round(score, 2), "factors": factors,
        })
    zones.sort(key=lambda z: z["score"], reverse=True)
    zones = zones[:MAX_ZONES]
    if verbose:
        print(f"  {symbol}: {len(zones)} зон внимания (из {len(clusters)} кластеров, price={price:.4f}, ATR={atr:.4f})")
    return zones


def run(verbose: bool = False) -> int:
    con = sqlite3.connect(str(_BOT_DB))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS confluence_zones(
          symbol TEXT, price_low REAL, price_high REAL, score REAL,
          factors TEXT, computed_ts INT,
          PRIMARY KEY(symbol, price_low));
    """)
    con.commit()

    now_ts = int(time.time())
    import glob
    symbols = sorted({Path(f).stem.replace("ohlc_", "").replace("_D1", "")
                       for f in glob.glob(str(_WEB_DATA / "ohlc_*_D1.json"))})

    written = 0
    for symbol in symbols:
        zones = compute_symbol(symbol, verbose)
        con.execute("DELETE FROM confluence_zones WHERE symbol=?", (symbol,))
        for z in zones:
            con.execute(
                "INSERT INTO confluence_zones(symbol, price_low, price_high, score, factors, computed_ts) "
                "VALUES(?,?,?,?,?,?)",
                (z["symbol"], z["price_low"], z["price_high"], z["score"], json.dumps(z["factors"], ensure_ascii=False), now_ts),
            )
            written += 1
    con.commit()
    con.close()
    if verbose:
        print(f"готово: {written} зон записано по {len(symbols)} символам")
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    run(verbose=args.verbose)
