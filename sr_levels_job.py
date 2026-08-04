#!/usr/bin/env python3
"""
sr_levels_job.py — SBF_Charts_Layer2_Spec, Фаза 1 (качество уровней: касания и возраст).

Офлайн-джоб (раз в сутки + можно гонять чаще — идемпотентно, полный пересчёт
с нуля на каждый прогон, см. sbf-sr-levels.timer): для каждого инструмента с
D1 OHLCV (`web/data/ohlc_{symbol}_D1.json` — тот же файл, что рисует chart.html,
гарантирует визуальное совпадение уровней со свечами) детектирует исторические
S/R-уровни по fractal-свингам, кластеризует по ATR, считает касания/возраст/
пробитие.

Использование:
  python3 sr_levels_job.py [--verbose]
"""
import argparse
import glob
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
_WEB_DATA = Path(__file__).parent / "web" / "data"

FRACTAL_CONFIRM = 3       # свечей слева/справа для fractal high/low
MIN_TOUCHES = 2           # хранить только уровни с touches >= 2
MAX_ACTIVE_LEVELS = 12    # топ по score в отдаче API
BROKEN_RETENTION_DAYS = 30
BREAK_CONFIRM_DAYS = 2    # закрытий подряд за уровнем -> broken
TOUCH_MIN_GAP = 2         # свечей между засчитываемыми касаниями


def _load_d1_candles(symbol: str):
    f = _WEB_DATA / f"ohlc_{symbol}_D1.json"
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    out = []
    for c in data.get("candles") or []:
        t = c.get("time")
        try:
            if isinstance(t, str):
                ts = int(datetime.strptime(t, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
            else:
                ts = int(t)
            out.append({"ts": ts, "o": float(c["open"]), "h": float(c["high"]),
                        "l": float(c["low"]), "c": float(c["close"])})
        except (ValueError, TypeError, KeyError):
            continue
    out.sort(key=lambda b: b["ts"])
    return out


def _atr14(candles) -> float | None:
    if len(candles) < 15:
        return None
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-14:]) / 14


def _fractals(candles):
    """[(idx, price, 'high'|'low')] — локальный экстремум с подтверждением
    FRACTAL_CONFIRM свечей слева/справа."""
    out = []
    n = len(candles)
    for i in range(FRACTAL_CONFIRM, n - FRACTAL_CONFIRM):
        window = candles[i - FRACTAL_CONFIRM:i + FRACTAL_CONFIRM + 1]
        h, l = candles[i]["h"], candles[i]["l"]
        if h == max(c["h"] for c in window):
            out.append((i, h, "high"))
        if l == min(c["l"] for c in window):
            out.append((i, l, "low"))
    return out


def _cluster(fractals, tolerance):
    """Жадная кластеризация по цене — сравниваем с ЯКОРЕМ кластера (первым
    элементом), не с последним добавленным. Была ошибка на этапе первой
    реализации: сравнение с последним добавленным даёт "цепочку" — при плотных,
    примерно равномерно расставленных свингах (типичная ситуация) кластер
    расползается на много tolerance подряд (на реальных данных GOLD один такой
    кластер растянулся на 366 при tolerance=20 — явно не один уровень). Сравнение
    с якорем жёстко ограничивает ширину кластера сверху величиной tolerance."""
    pts = sorted(fractals, key=lambda f: f[1])
    clusters, cur = [], None
    for f in pts:
        if cur and (f[1] - cur[0][1]) <= tolerance:
            cur.append(f)
        else:
            cur = [f]
            clusters.append(cur)
    return clusters


def _score_level(candles, price, tolerance, kind, start_idx):
    """Считает касания начиная с формирования уровня. kind — исходная роль
    ('support'/'resistance'); учитывает возможный флип роли после пробоя с
    ретестом (см. Acceptance спеки: kind='flip').
    Возвращает (touches, last_touch_ts, broken, final_kind)."""
    zone_half = tolerance / 2
    touches = 0
    last_touch_idx = -999
    last_touch_ts = None
    broken = False
    consec_break = 0
    cur_kind = kind

    for i in range(start_idx, len(candles)):
        c = candles[i]
        zone_lo, zone_hi = price - zone_half, price + zone_half
        entered = (zone_lo <= c["h"] <= zone_hi) or (zone_lo <= c["l"] <= zone_hi) \
            or (c["l"] <= price <= c["h"])

        if entered and (i - last_touch_idx) >= TOUCH_MIN_GAP:
            if broken:
                # роль перевернулась после пробоя — ретест с обратной стороны
                rejected = (c["c"] < price) if cur_kind == "support" else (c["c"] > price)
            else:
                rejected = (c["c"] > price) if cur_kind == "support" else (c["c"] < price)
            if rejected:
                touches += 1
                last_touch_idx = i
                last_touch_ts = c["ts"]
                if broken:
                    cur_kind = "flip"
                broken = False
                consec_break = 0

        beyond = (c["c"] < zone_lo) if cur_kind in ("support",) else (c["c"] > zone_hi) \
            if cur_kind == "resistance" else False
        if cur_kind == "flip":
            beyond = False  # после флипа не отслеживаем повторный пробой (упрощение)
        consec_break = consec_break + 1 if beyond else 0
        if consec_break >= BREAK_CONFIRM_DAYS:
            broken = True

    return touches, last_touch_ts, broken, cur_kind


def compute_symbol(symbol: str, now_ts: int, verbose=False):
    candles = _load_d1_candles(symbol)
    if not candles or len(candles) < 2 * FRACTAL_CONFIRM + 15:
        return []
    atr = _atr14(candles)
    if not atr:
        return []
    tolerance = atr * 0.25

    fr = _fractals(candles)
    clusters = _cluster(fr, tolerance)

    levels = []
    for cluster in clusters:
        prices = [p for _, p, _ in cluster]
        kinds = [k for _, _, k in cluster]
        price = sorted(prices)[len(prices) // 2] if len(prices) % 2 else \
            (sorted(prices)[len(prices) // 2 - 1] + sorted(prices)[len(prices) // 2]) / 2
        kind = "resistance" if kinds.count("high") >= kinds.count("low") else "support"
        first_idx = min(i for i, _, _ in cluster)
        first_ts = candles[first_idx]["ts"]

        touches, last_touch_ts, broken, final_kind = _score_level(candles, price, tolerance, kind, first_idx)
        if touches < MIN_TOUCHES:
            continue
        age_days = max(1, (now_ts - first_ts) // 86400)
        levels.append({
            "symbol": symbol, "price": round(price, 6), "tolerance": round(tolerance, 6),
            "kind": final_kind, "touches": touches, "age_days": int(age_days),
            "first_ts": first_ts, "last_touch_ts": last_touch_ts,
            "broken": 1 if broken else 0, "computed_ts": now_ts,
        })
    if verbose:
        print(f"  {symbol}: {len(levels)} уровней (touches>=2), ATR14={atr:.4f}, tolerance={tolerance:.4f}")
    return levels


def run(verbose: bool = False) -> int:
    con = sqlite3.connect(str(_BOT_DB))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS sr_levels(
          id INTEGER PRIMARY KEY, symbol TEXT, price REAL, tolerance REAL,
          kind TEXT, touches INT, age_days INT, first_ts INT, last_touch_ts INT,
          broken INT DEFAULT 0, computed_ts INT);
        CREATE INDEX IF NOT EXISTS idx_sr_symbol ON sr_levels(symbol, broken);
    """)
    con.commit()

    now_ts = int(time.time())
    symbols = sorted({Path(f).stem.replace("ohlc_", "").replace("_D1", "")
                       for f in glob.glob(str(_WEB_DATA / "ohlc_*_D1.json"))})

    written = 0
    for symbol in symbols:
        levels = compute_symbol(symbol, now_ts, verbose)
        if not levels:
            continue
        # compute_symbol() пересчитывает ВСЮ историю с нуля каждый раз — фрэшь
        # результат уже содержит корректное текущее состояние (включая давно
        # сломанные уровни, раз touches>=2 всё ещё выполняется). Поэтому просто
        # заменяем весь набор строк символа целиком, не оставляя старых рядом —
        # иначе broken=1 строки дублировались бы на каждый прогон (id autoincrement,
        # естественного ключа против дублей нет). "Хранить 30 дней" реализовано
        # ниже как фильтр по свежести last_touch_ts на запись, а не отдельным
        # DELETE поверх уже одинаковых computed_ts.
        con.execute("DELETE FROM sr_levels WHERE symbol=?", (symbol,))
        for lv in levels:
            if lv["broken"] and (now_ts - (lv["last_touch_ts"] or lv["first_ts"])) > BROKEN_RETENTION_DAYS * 86400:
                continue
            con.execute(
                """INSERT INTO sr_levels(symbol, price, tolerance, kind, touches, age_days,
                   first_ts, last_touch_ts, broken, computed_ts) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (lv["symbol"], lv["price"], lv["tolerance"], lv["kind"], lv["touches"],
                 lv["age_days"], lv["first_ts"], lv["last_touch_ts"], lv["broken"], lv["computed_ts"]),
            )
            written += 1

    con.commit()
    con.close()
    if verbose:
        print(f"готово: {written} уровней записано по {len(symbols)} символам")
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    run(verbose=args.verbose)
