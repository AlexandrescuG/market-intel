#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/gate.py — WP4.2 SPEC_alpha_engine_wp4_continuous_cycle.md.

Решает, звать ли агента вообще, и по каким инструментам. Никогда не
бросает исключение наверх (§0 спеки: "скрипты не дают ошибки") — сбой на
одном символе -> запись в per_symbol[symbol]["error"], остальные символы
разбираются как обычно.

Порог v1 — ХАРДКОД (OR по отдельным полям), не калиброванный перцентиль:
калибровка (`tools/agent/attention_trigger.calibrate_threshold`) требует
историю scores, которой пока физически нет — она появится только после
того, как `gate_log` накопится за 1-2 недели эксплуатации. `total_score`
(attention_score()) считается и логируется КАЖДЫЙ раз именно для этого —
но НЕ он определяет `gated` в v1, определяют явные пороги ниже. Обе вещи
разведены сознательно, не спутать: score — для будущей калибровки,
OR-условие — для сегодняшнего решения.

break_retest -- направление берётся из САМОГО события (e["direction"]),
не из статического core.patterns.PATTERNS -- тот же баг, найденный и
исправленный 13.08 в tools/agent/run_analyst.py (там direction="neutral"
в реестре у break_retest не давал ему НИКОГДА пройти фильтр).
"""
from __future__ import annotations

import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze.base_rate import lookup_base_rate
from analyze.labeler import config_key as _config_key, _atr14, _barriers, _SIGNAL_TF_SECONDS
from analyze.state_vector import build_indicator_cache, build_state_vector_live, calendar_prox_minutes
from core.patterns import detect as detect_patterns
from core.symbols_registry import alias_for
from tools.agent.attention_trigger import attention_score
import core.price_bars as _price_bars

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
_TF_TO_PB = {"D1": "1d"}  # v1 -- только D1 (см. план, экономика lookup_base_rate)

# Тот же конфиг, что WP2.5 baseline -- наиболее изученный, не изобретаем
# отдельную сетку для гейта.
_GATE_CONFIG = (1.5, 2.0, 30)

# v1 [ДОПУЩЕНИЕ]: OR по отдельным порогам, не единый score-порог -- см.
# докстринг модуля. Числа -- те же, что предложены при проектировании,
# не откалиброваны на исторических данных (их пока нет).
_THRESH_MOVE_ATR = 1.0
_THRESH_CALENDAR_MIN = 15.0
_THRESH_BASE_RATE_SHIFT = 0.05

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS gate_base_rate_prev (
      symbol TEXT, tf TEXT, pattern_key TEXT, direction TEXT, config_key TEXT,
      p REAL, n INTEGER, backoff_level INTEGER, updated_ts INTEGER,
      PRIMARY KEY (symbol, tf, pattern_key, direction, config_key)
    );
    CREATE TABLE IF NOT EXISTS gate_last_bar (
      symbol TEXT, tf TEXT, ts INTEGER, close REAL, atr14 REAL, updated_ts INTEGER,
      PRIMARY KEY (symbol, tf)
    );
    CREATE TABLE IF NOT EXISTS gate_log (
      run_id TEXT, symbol TEXT, tf TEXT, move_atr REAL, news_burst_z REAL,
      calendar_prox REAL, base_rate_shift REAL, level_break REAL,
      total_score REAL, threshold REAL, gated INTEGER, ts INTEGER
    );
"""


def init_schema(con: sqlite3.Connection) -> None:
    con.executescript(_SCHEMA)
    con.commit()


def _load_levels(con: sqlite3.Connection, canonical_symbol: str) -> list[dict]:
    try:
        rows = con.execute(
            "SELECT price, tolerance, kind FROM sr_levels WHERE symbol=? AND broken=0", (canonical_symbol,)
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [{"price": r[0], "tolerance": r[1], "kind": r[2]} for r in rows]


def _get_prev_bar(con: sqlite3.Connection, symbol: str, tf: str) -> tuple[float, float] | None:
    row = con.execute(
        "SELECT close, atr14 FROM gate_last_bar WHERE symbol=? AND tf=?", (symbol, tf)
    ).fetchone()
    return (row[0], row[1]) if row else None


def _update_last_bar(con: sqlite3.Connection, symbol: str, tf: str, ts: int,
                      close: float, atr_val: float | None, now_ts: int) -> None:
    con.execute(
        "INSERT OR REPLACE INTO gate_last_bar (symbol, tf, ts, close, atr14, updated_ts) VALUES (?,?,?,?,?,?)",
        (symbol, tf, ts, close, atr_val, now_ts),
    )


def _get_prev_base_rate(con: sqlite3.Connection, symbol: str, tf: str, pattern_key: str,
                         direction: str, config_key: str) -> float | None:
    row = con.execute(
        "SELECT p FROM gate_base_rate_prev WHERE symbol=? AND tf=? AND pattern_key=? AND direction=? AND config_key=?",
        (symbol, tf, pattern_key, direction, config_key),
    ).fetchone()
    return row[0] if row else None


def _update_base_rate_cache(con: sqlite3.Connection, symbol: str, tf: str, pattern_key: str,
                             direction: str, config_key: str, p: float, n: int,
                             backoff_level: int, now_ts: int) -> None:
    con.execute(
        """INSERT OR REPLACE INTO gate_base_rate_prev
           (symbol, tf, pattern_key, direction, config_key, p, n, backoff_level, updated_ts)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (symbol, tf, pattern_key, direction, config_key, p, n, backoff_level, now_ts),
    )


def _symbol_step(con: sqlite3.Connection, symbol: str, tf: str, now_ts: int) -> dict:
    """Один символ, полностью в try/except у вызывающего -- см. decide().

    🔴 Найдено ревью 13.08 (REVIEW_wp4_cycle_2026-08-13.md §1), подтверждено
    живьём (GOLD: последний бар price_bars ts=13.08 00:00 UTC, сейчас
    11:39 UTC -- формирующаяся свеча): раньше candles НЕ фильтровались по
    закрытости, `i = len(candles)-1` брал СЕГОДНЯШНИЙ, ещё формирующийся
    D1-бар. Train/serve skew -- lookup_base_rate() ищет по ЗАКРЫТЫМ
    историческим барам (labeler.py), а живой candidate снимался с
    открытого -- плюс репейнт (паттерн на открытом баре может появиться и
    исчезнуть между циклами). Тот же класс ошибки, что уже был в
    Signals/monitor.py (`iloc[-1]` на формирующемся баре). Фильтр -- по
    образцу build_brief_v2.py:208 (сравнение UTC-дат строками, не now_ts
    внутри -- используем ПЕРЕДАННЫЙ now_ts, не datetime.now(), симметрично
    bundle.py's принципу явного времени для детерминизма)."""
    pb_tf = _TF_TO_PB[tf]
    all_candles = _price_bars.load_candles(symbol, pb_tf)
    if not all_candles:
        return {"ok": False, "error": f"нет данных {symbol} {tf}"}
    today_str = datetime.fromtimestamp(now_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    candles = [c for c in all_candles
               if datetime.fromtimestamp(c["ts"], tz=timezone.utc).strftime("%Y-%m-%d") < today_str]
    if len(candles) < 30:
        return {"ok": False, "error": f"нет закрытых баров {symbol} {tf} (после фильтра сегодняшнего дня)"}
    i = len(candles) - 1
    last = candles[i]
    atr_val = _atr14(candles, i)

    prev_bar = _get_prev_bar(con, symbol, tf)
    move_atr = 0.0
    if prev_bar and prev_bar[1] and atr_val:
        move_atr = round((last["c"] - prev_bar[0]) / prev_bar[1], 4)
    _update_last_bar(con, symbol, tf, last["ts"], last["c"], atr_val, now_ts)

    levels = _load_levels(con, symbol)
    events = detect_patterns(candles, levels)
    last_events = [e for e in events if e["ts"] == last["ts"] and e["direction"] in ("bullish", "bearish")]
    level_break = 1.0 if any(e["pattern_key"] == "break_retest" for e in last_events) else 0.0

    cal_min = calendar_prox_minutes(con, last["ts"], as_of_ts=None)

    pb_symbol = alias_for(symbol, "price_bars") or symbol
    cache = build_indicator_cache(candles)
    state = build_state_vector_live(symbol, pb_symbol, tf, candles, con, cache=cache)

    ckey = _config_key(*_GATE_CONFIG)
    candidates = []
    max_shift = 0.0
    for e in last_events:
        base = lookup_base_rate(con, e["pattern_key"], e["direction"], symbol, tf, ckey, state)
        shift = 0.0
        if not base["insufficient"]:
            prev_p = _get_prev_base_rate(con, symbol, tf, e["pattern_key"], e["direction"], ckey)
            if prev_p is not None:
                shift = round(base["p"] - prev_p, 4)
            _update_base_rate_cache(con, symbol, tf, e["pattern_key"], e["direction"], ckey,
                                     base["p"], base["n"], base["backoff_level"], now_ts)
        max_shift = max(max_shift, abs(shift))
        # entry/stop/target/valid_until -- механически (WP4.3: "модель не
        # придумывает цены, они уже посчитаны Python"), симметрично старому
        # tools/agent/run_analyst.py::build_context(). entry_kind="close"
        # (та же конвенция, что labeler.py::label_one).
        atr_mult, rr, horizon_bars = _GATE_CONFIG
        upper, lower = _barriers(last["c"], e["direction"], atr_val, atr_mult, rr)
        stop, target = (lower, upper) if e["direction"] == "bullish" else (upper, lower)
        valid_until = last["ts"] + horizon_bars * _SIGNAL_TF_SECONDS[tf]
        candidates.append({
            "pattern_key": e["pattern_key"], "direction": e["direction"], "config_key": ckey,
            "base_rate": base, "shift": shift,
            "entry": last["c"], "entry_kind": "close", "stop": stop, "target": target,
            "valid_until": valid_until, "created_ts": last["ts"], "atr_val": atr_val,
        })

    score = attention_score(move_atr, news_burst_z=None, calendar_prox_minutes=cal_min,
                             base_rate_shift=max_shift, level_break=level_break)
    gated = (level_break == 1.0 or abs(move_atr) >= _THRESH_MOVE_ATR
             or (cal_min is not None and cal_min < _THRESH_CALENDAR_MIN)
             or abs(max_shift) >= _THRESH_BASE_RATE_SHIFT)

    return {
        "ok": True, "state": state, "candidates": candidates, "gated": gated,
        "score": score, "breakdown": {"move_atr": move_atr, "calendar_prox": cal_min,
                                       "base_rate_shift": max_shift, "level_break": level_break},
    }


def decide(con: sqlite3.Connection, universe: list[str], now_ts: int,
           budget_calls_per_day: int = 5) -> dict:
    """{"run_id", "gated": [...], "per_symbol": {...}, "model_should_run": bool}.
    Никогда не raise -- каждый символ независим."""
    init_schema(con)
    run_id = str(uuid.uuid4())
    per_symbol: dict[str, dict] = {}
    gated: list[str] = []
    for symbol in universe:
        try:
            result = _symbol_step(con, symbol, "D1", now_ts)
        except Exception as e:
            result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        per_symbol[symbol] = result
        if result.get("ok") and result.get("gated"):
            gated.append(symbol)
        bd = result.get("breakdown", {})
        con.execute(
            """INSERT INTO gate_log (run_id, symbol, tf, move_atr, news_burst_z, calendar_prox,
                                      base_rate_shift, level_break, total_score, threshold, gated, ts)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, symbol, "D1", bd.get("move_atr"), None, bd.get("calendar_prox"),
             bd.get("base_rate_shift"), bd.get("level_break"), result.get("score"),
             None, int(bool(result.get("gated"))), now_ts),
        )
    con.commit()
    return {"run_id": run_id, "gated": gated, "per_symbol": per_symbol,
            "model_should_run": len(gated) > 0}


def main() -> None:
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", nargs="+", default=["GOLD", "EURUSD", "USDJPY", "USDCNY", "USDZAR"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(str(_BOT_DB))
    now_ts = int(time.time())
    if args.dry_run:
        init_schema(con)
        for sym in args.universe:
            r = _symbol_step(con, sym, "D1", now_ts)
            print(f"{sym}: ok={r.get('ok')} gated={r.get('gated')} score={r.get('score')} "
                  f"breakdown={r.get('breakdown')}")
            for c in r.get("candidates", []):
                print(f"    candidate: {c['pattern_key']} {c['direction']} base_rate={c['base_rate']}")
        con.rollback()  # dry-run: не фиксируем gate_last_bar/gate_base_rate_prev/gate_log
    else:
        result = decide(con, args.universe, now_ts)
        print(json.dumps({"run_id": result["run_id"], "gated": result["gated"],
                           "model_should_run": result["model_should_run"]}, ensure_ascii=False))
    con.close()


if __name__ == "__main__":
    main()
