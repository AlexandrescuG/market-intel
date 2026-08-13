#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/agent/run_analyst.py — WP4.3 SPEC_alpha_engine_implementation.md
(механика вызова — WP7.1 "analyst"/WP7.5/WP7.6).

Собирает промпт для ОДНОГО сработавшего барьерного сигнала (symbol/tf/
pattern уже найден вызывающим кодом или проверяется здесь на последнем
баре), вызывает `claude -p` headless с узким allowlist (только q_*.py) и
строгой JSON-схемой (`--json-schema`, обнаружен живой проверкой CLI 12.08 —
надёжнее обходного пути news_digest_job.py "модель пишет файл, Python
перечитывает"). Модель НЕ придумывает entry/stop/target/base_rate — те уже
посчитаны Python (WP7.4) — модель возвращает только adjustment/thesis/
cited_factors/novel_risk/final_p.

Провал (timeout/невалидный JSON/бизнес-правило) -> forecast НЕ пишется,
инцидент -> agent_calls. Успех -> write_forecast + agent_calls(ok).

Использование:
  python3 tools/agent/run_analyst.py --symbol GOLD --tf H4 \
      --pattern bearish_engulfing --atr-mult 1.5 --rr 2.0 --horizon-bars 30 \
      --dry-run
  # без --dry-run: реальный вызов claude -p, тратит API-бюджет
  # (--max-budget-usd ограничивает сверху за один вызов).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from analyze.base_rate import lookup_base_rate
from analyze.forecast_journal import init_schema, write_forecast
from analyze.labeler import config_key as _config_key, _atr14, _barriers, _SIGNAL_TF_SECONDS
from analyze.state_vector import build_state_vector_live, build_indicator_cache
from core.costs import entry_cost_price
from core.patterns import detect as detect_patterns
from core.symbols_registry import alias_for
import core.price_bars as _price_bars

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
_TF_TO_PB = {"H1": "1h", "H4": "4h", "D1": "1d"}
_TOOLS_DIR = Path(__file__).parent
_MARKET_INTEL_ROOT = Path(__file__).parent.parent.parent
CLAUDE_BIN = str(Path.home() / ".local" / "bin" / "claude")
CLAUDE_TIMEOUT_SEC = 90
ADJUSTMENT_CAP = 0.15
# 🔴 Найдено живой проверкой 12.08: БЕЗ явного --model дефолт headless
# claude -p в этом окружении -- Opus (дорогая, 1M-контекст) -- тривиальный
# тестовый вызов стоил $0.27! Haiku на том же вызове -- $0.0007 (~400x
# дешевле). Для analyst-роли (WP7.1: "узкий, дешёвый, предсказуемый",
# недетерминизм -- помеха) фиксируем ПОЛНЫМ именем, не алиасом "haiku" --
# поведение не должно меняться молча при выходе новой версии.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# 🔴 Живая проверка 12.08: модель по своей инициативе вызвала ОТНОСИТЕЛЬНЫЙ
# путь ("python3 tools/agent/q_snapshot.py ...", не абсолютный) -- получила
# permission_denied на паттерн с одним только абсолютным путём. Разрешаем
# обе формы; subprocess.run ниже явно задаёт cwd=_MARKET_INTEL_ROOT, чтобы
# относительный путь резолвился туда же, куда его резолвит сама модель.
_ALLOWED_TOOLS = [
    f"Bash(python3 {_TOOLS_DIR}/q_snapshot.py *)",
    f"Bash(python3 {_TOOLS_DIR}/q_base_rate.py *)",
    f"Bash(python3 {_TOOLS_DIR}/q_news.py *)",
    "Bash(python3 tools/agent/q_snapshot.py *)",
    "Bash(python3 tools/agent/q_base_rate.py *)",
    "Bash(python3 tools/agent/q_news.py *)",
]
_DISALLOWED_TOOLS = ["Bash(sqlite3 *)", "Bash(rm *)", "Write", "Edit"]

_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "adjustment": {"type": "number", "minimum": -1, "maximum": 1},
        "adjustment_reason": {"type": "string"},
        "cited_factors": {"type": "array", "items": {"type": "string"}},
        "novel_risk": {"type": ["string", "null"]},
        "final_p": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "thesis": {"type": "string"},
        "invalidation": {"type": "string"},
    },
    "required": ["adjustment", "adjustment_reason", "cited_factors", "thesis", "invalidation"],
}


def _load_levels(con: sqlite3.Connection, canonical_symbol: str) -> list[dict]:
    try:
        rows = con.execute(
            "SELECT price, tolerance, kind FROM sr_levels WHERE symbol=? AND broken=0", (canonical_symbol,)
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [{"price": r[0], "tolerance": r[1], "kind": r[2]} for r in rows]


def _past_calibration_note(con: sqlite3.Connection, event_key: str) -> str:
    rows = con.execute(
        """SELECT f.conviction, o.status, o.r_realized FROM forecasts f
           JOIN forecast_outcomes o ON f.id = o.forecast_id
           WHERE f.event_key = ? AND o.status != 'censored'
           ORDER BY f.created_ts DESC LIMIT 20""",
        (event_key,),
    ).fetchall()
    briers = [(1.0 - c) ** 2 if status == "win" else c ** 2
              for c, status, _ in rows if c is not None]
    if not briers:
        return "Нет прошлой истории высказываний по этому event_key — это будет первое."
    avg_brier = sum(briers) / len(briers)
    return (f"На последних {len(briers)} закрытых высказываниях по этому event_key твой "
            f"средний Brier(final_p) = {avg_brier:.3f} (0 — идеально, 0.25 — как монетка).")


def build_context(canonical_symbol: str, tf: str, pattern_key: str,
                   atr_mult: float, rr: float, horizon_bars: int) -> dict | None:
    """Механическая часть (Python, WP7.4) — entry/stop/target/valid_until,
    вектор состояния, базовая ставка. None, если паттерн НЕ сработал на
    последнем баре — нечего анализировать."""
    pb_tf = _TF_TO_PB[tf]
    all_candles = _price_bars.load_candles(canonical_symbol, pb_tf)
    if not all_candles:
        return None
    # 🔴 REVIEW_wp4_cycle_2026-08-13.md §1: тот же баг, что был в gate.py --
    # без фильтра "i = len(candles)-1" брал сегодняшний, ещё формирующийся
    # D1-бар (train/serve skew против base_rate, посчитанной на закрытых
    # барах). Фильтр по образцу build_brief_v2.py:208.
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    candles = [c for c in all_candles
               if datetime.fromtimestamp(c["ts"], tz=timezone.utc).strftime("%Y-%m-%d") < today_str]
    if len(candles) < 30:
        return None
    con = sqlite3.connect(str(_BOT_DB), timeout=5)
    try:
        init_schema(con)  # forecasts/agent_calls читаются ниже (_past_calibration_note)
        levels = _load_levels(con, canonical_symbol)
        events = detect_patterns(candles, levels)
        i = len(candles) - 1
        last_ts = candles[i]["ts"]
        # 🔴 Найдено 13.08 при проектировании continuous-cycle: раньше
        # направление читалось из СТАТИЧЕСКОГО PATTERNS[pattern_key]["direction"]
        # -- для break_retest это всегда "neutral" в реестре, хотя реальные
        # occurrence несут настоящее bullish/bearish (пробой вверх/вниз).
        # Из-за этого break_retest НИКОГДА не проходил проверку ниже и
        # никогда не предлагался агенту, хотя детектор его реально находит.
        # Направление -- из САМОГО события (симметрично label_symbol()/
        # report.py._pattern_occurrence_keys), не из статического реестра.
        last_events = [e for e in events if e["ts"] == last_ts and e["pattern_key"] == pattern_key
                       and e["direction"] in ("bullish", "bearish")]
        if not last_events:
            return None  # паттерн не сработал на последнем баре
        direction = last_events[0]["direction"]

        atr_val = _atr14(candles, i)
        if not atr_val or atr_val <= 0:
            return None
        entry = candles[i]["c"]
        upper, lower = _barriers(entry, direction, atr_val, atr_mult, rr)
        stop, target = (lower, upper) if direction == "bullish" else (upper, lower)
        signal_tf_seconds = _SIGNAL_TF_SECONDS[tf]
        valid_until = last_ts + horizon_bars * signal_tf_seconds
        config_key = _config_key(atr_mult, rr, horizon_bars)
        event_key = f"barrier:{config_key}"

        pb_symbol = alias_for(canonical_symbol, "price_bars") or canonical_symbol
        cache = build_indicator_cache(candles)
        state = build_state_vector_live(canonical_symbol, pb_symbol, tf, candles, con, cache=cache)
        base = lookup_base_rate(con, pattern_key, direction, canonical_symbol, tf, config_key, state)
        calibration_note = _past_calibration_note(con, event_key)

        return {
            "symbol": canonical_symbol, "tf": tf, "pattern_key": pattern_key, "direction": direction,
            "event_key": event_key, "config_key": config_key, "entry": entry, "stop": stop,
            "target": target, "valid_until": valid_until, "created_ts": last_ts,
            "atr_val": atr_val, "state": state, "base_rate": base,
            "calibration_note": calibration_note,
        }
    finally:
        con.close()


def build_prompt(ctx: dict) -> str:
    base = ctx["base_rate"]
    base_desc = ("недостаточно данных (n=%d на самом грубом уровне отката)" % base["n"]
                 if base["insufficient"] else
                 f"{base['p']:.4f} (n={base['n']}, CI95=[{base['ci95_lo']:.1f}%, {base['ci95_hi']:.1f}%], "
                 f"backoff_level={base['backoff_level']}, dropped={base['dropped']})")
    return f"""Ты — analyst-роль калибровочного контура WP4 (SPEC_alpha_engine_implementation.md).
ТЫ НЕ ПРОИЗВОДИШЬ ВЕРОЯТНОСТЬ С НУЛЯ. Ты вносишь ОГРАНИЧЕННУЮ поправку к
уже посчитанной эмпирической базовой ставке.

Сигнал: {ctx['symbol']} {ctx['tf']}, паттерн {ctx['pattern_key']}, направление {ctx['direction']}.
Механически посчитано (НЕ пересчитывай, эти числа фиксированы): entry={ctx['entry']:.5f},
stop={ctx['stop']:.5f}, target={ctx['target']:.5f}, valid_until={ctx['valid_until']} (unix ts),
event_key={ctx['event_key']}.

Базовая ставка (эмпирика, Python, WP4.2): {base_desc}.

Вектор состояния сейчас: {json.dumps(ctx['state'], ensure_ascii=False)}.

{ctx['calibration_note']}

Тебе доступны read-only инструменты (можешь перепроверить любое число выше,
но НЕ обязан):
  python3 {_TOOLS_DIR}/q_snapshot.py --symbol {ctx['symbol']} --tf {ctx['tf']}
  python3 {_TOOLS_DIR}/q_base_rate.py --symbol {ctx['symbol']} --tf {ctx['tf']} --pattern {ctx['pattern_key']} --direction {ctx['direction']} --atr-mult <a> --rr <r> --horizon-bars <h>
  python3 {_TOOLS_DIR}/q_news.py --symbol {ctx['symbol']} --hours 6

ЖЁСТКИЕ ПРАВИЛА КОНТРАКТА (нарушение -> твой ответ будет отклонён целиком):
  - |adjustment| > 0.15 (15 процентных пунктов) ТОЛЬКО если cited_factors
    непусто и явно называет фактор ИЗ вектора состояния выше, который это
    обосновывает — голая уверенность не даёт права на большую поправку;
  - если базовая ставка "недостаточно данных" — final_p ДОЛЖЕН быть null,
    можешь писать только novel_risk и thesis, НЕ число;
  - final_p (если не null) должен равняться base_rate.p + adjustment (с
    точностью округления) — не изобретай отдельное число;
  - novel_risk — то, чего вектор состояния не покрывает вообще (геополитика,
    внеплановое решение ЦБ), НЕ конвертируется в число, только текст.

Верни СТРОГО JSON по схеме (adjustment, adjustment_reason, cited_factors,
novel_risk, final_p, thesis, invalidation)."""


def _validate_business_rules(resp: dict, base: dict) -> tuple[bool, str]:
    adjustment = resp.get("adjustment", 0.0)
    cited = resp.get("cited_factors") or []
    final_p = resp.get("final_p")

    if abs(adjustment) > ADJUSTMENT_CAP and not cited:
        return False, f"|adjustment|={abs(adjustment):.3f} > {ADJUSTMENT_CAP} без cited_factors"
    if base["insufficient"] and final_p is not None:
        return False, "base_rate=insufficient, но final_p не null"
    if not base["insufficient"] and final_p is not None:
        expected = round(base["p"] + adjustment, 4)
        if abs(final_p - expected) > 0.01:
            return False, f"final_p={final_p} не согласуется с base_rate.p+adjustment={expected}"
    return True, ""


def run(canonical_symbol: str, tf: str, pattern_key: str, atr_mult: float, rr: float,
        horizon_bars: int, dry_run: bool, max_budget_usd: float, verbose: bool,
        model: str = DEFAULT_MODEL) -> str | None:
    ctx = build_context(canonical_symbol, tf, pattern_key, atr_mult, rr, horizon_bars)
    if ctx is None:
        print(f"{pattern_key} не сработал на последнем баре {canonical_symbol} {tf} — нет сигнала для анализа.")
        return None

    prompt = build_prompt(ctx)
    if dry_run:
        print("=== PROMPT ===")
        print(prompt)
        print("\n=== JSON SCHEMA ===")
        print(json.dumps(_JSON_SCHEMA, ensure_ascii=False, indent=2))
        return None

    call_id = str(uuid.uuid4())
    t0 = time.time()
    cmd = [CLAUDE_BIN, "-p", prompt,
           "--allowedTools", *_ALLOWED_TOOLS,
           "--disallowedTools", *_DISALLOWED_TOOLS,
           "--output-format", "json",
           "--json-schema", json.dumps(_JSON_SCHEMA),
           "--max-budget-usd", str(max_budget_usd),
           "--model", model]
    try:
        proc = subprocess.run(cmd, timeout=CLAUDE_TIMEOUT_SEC, capture_output=True, text=True,
                               check=False, cwd=str(_MARKET_INTEL_ROOT))
    except (subprocess.TimeoutExpired, OSError) as e:
        _log_call(call_id, ctx, prompt, "", None, time.time() - t0, -1, "timeout", str(e), model=model)
        print(f"claude -p не уложился/упал: {e}")
        return None

    duration_ms = int((time.time() - t0) * 1000)
    if proc.returncode != 0:
        _log_call(call_id, ctx, prompt, proc.stdout, None, duration_ms, proc.returncode,
                   "cli_error", proc.stderr[:2000], model=model)
        print(f"claude -p вернул код {proc.returncode}: {proc.stderr[:500]}")
        return None

    try:
        envelope = json.loads(proc.stdout)
        # structured_output -- уже разобранный dict (надёжнее двойного
        # JSON-в-строке через "result", найдено живой проверкой 12.08).
        if isinstance(envelope, dict) and envelope.get("structured_output") is not None:
            resp = envelope["structured_output"]
        else:
            resp = envelope.get("result") if isinstance(envelope, dict) else envelope
            if isinstance(resp, str):
                resp = json.loads(resp)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        _log_call(call_id, ctx, prompt, proc.stdout, None, duration_ms, proc.returncode,
                   "schema_reject", f"невалидный JSON: {e}", model=model)
        print(f"невалидный JSON от claude -p: {e}")
        return None

    ok, reason = _validate_business_rules(resp, ctx["base_rate"])
    if not ok:
        _log_call(call_id, ctx, prompt, proc.stdout, resp, duration_ms, proc.returncode,
                   "business_reject", reason, model=model)
        print(f"бизнес-правило нарушено, forecast не записан: {reason}")
        return None

    con = sqlite3.connect(str(_BOT_DB))
    init_schema(con)
    # 🔴 Живая проверка 12.08: forecast_factors.value REAL по DDL, но
    # большинство вектора состояния -- категориальные бакеты (строки:
    # "above"/"trend"/"q3"). SQLite использует type affinity, НЕ строгую
    # типизацию -- REAL-колонка спокойно хранит TEXT без потери (проверено:
    # typeof(value) вернул 'text' для строки). Раньше здесь стояла
    # isinstance-проверка "число или None", отбрасывавшая ВСЕ строковые
    # бакеты в None -- реальная потеря данных, не защита.
    factors = [{"factor_key": k, "value": v,
                "zscore": None, "weight": 1.0 if k in (resp.get("cited_factors") or []) else 0.0}
               for k, v in ctx["state"].items()]
    factors.append({"factor_key": "_meta.atr_val", "value": ctx["atr_val"], "zscore": None, "weight": None})
    base = ctx["base_rate"]
    if not base["insufficient"]:
        factors += [
            {"factor_key": "_meta.base_rate", "value": base["p"], "zscore": None, "weight": None},
            {"factor_key": "_meta.base_n", "value": base["n"], "zscore": None, "weight": None},
            {"factor_key": "_meta.base_backoff_level", "value": base["backoff_level"], "zscore": None, "weight": None},
            {"factor_key": "_meta.adjustment", "value": resp.get("adjustment"), "zscore": None, "weight": None},
        ]
    thesis_full = (f"{resp.get('thesis', '')}\n[adjustment_reason] {resp.get('adjustment_reason', '')}\n"
                   f"[novel_risk] {resp.get('novel_risk') or '—'}")
    forecast = {
        "symbol": ctx["symbol"], "horizon": ctx["tf"], "event_key": ctx["event_key"],
        "direction": ctx["direction"], "conviction": resp.get("final_p"),
        "entry": ctx["entry"], "entry_kind": "close", "stop": ctx["stop"], "target": ctx["target"],
        "valid_until": ctx["valid_until"], "invalidation": resp.get("invalidation"),
        "thesis": thesis_full, "model_version": model,
    }
    fid = write_forecast(con, forecast, factors)
    con.execute("UPDATE forecasts SET created_ts=? WHERE id=?", (ctx["created_ts"], fid))
    con.commit()
    cost_usd = envelope.get("total_cost_usd") if isinstance(envelope, dict) else None
    _log_call(call_id, ctx, prompt, proc.stdout, resp, duration_ms, proc.returncode, "ok", "", fid, cost_usd, con, model)
    con.close()
    print(f"forecast записан: {fid}")
    return fid


def _log_call(call_id: str, ctx: dict, prompt: str, raw_response: str, parsed: dict | None,
               duration_ms: float, exit_code: int, status: str, reason: str,
               forecast_id: str | None = None, cost_usd: float | None = None,
               con: sqlite3.Connection | None = None, model: str | None = None) -> None:
    owns_con = con is None
    con = con or sqlite3.connect(str(_BOT_DB))
    init_schema(con)
    con.execute(
        """INSERT INTO agent_calls (call_id, ts, symbol, tf, event_key, forecast_id, model_version,
                                     prompt, raw_response, tool_calls_json, duration_ms, cost_usd,
                                     exit_code, validation_status, validation_reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (call_id, int(time.time()), ctx["symbol"], ctx["tf"], ctx["event_key"], forecast_id, model,
         prompt, raw_response, None, int(duration_ms), cost_usd, exit_code, status, reason),
    )
    con.commit()
    if owns_con:
        con.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--tf", required=True, choices=list(_TF_TO_PB))
    ap.add_argument("--pattern", required=True)
    ap.add_argument("--atr-mult", required=True, type=float)
    ap.add_argument("--rr", required=True, type=float)
    ap.add_argument("--horizon-bars", required=True, type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-budget-usd", type=float, default=0.10)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    run(args.symbol, args.tf, args.pattern, args.atr_mult, args.rr, args.horizon_bars,
        args.dry_run, args.max_budget_usd, args.verbose, model=args.model)


if __name__ == "__main__":
    main()
