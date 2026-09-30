#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/validate.py — WP4.4 SPEC_alpha_engine_wp4_continuous_cycle.md.

Из tools/agent/run_analyst.py сюда переехали бизнес-правила + запись
(write_forecast+agent_calls), расширенные под массив кандидатов (не один
сигнал). Новое правило, которого не было при "один сигнал = один вызов":
литеральная сверка base_rate/base_n/base_backoff_level из ответа модели
против того, что РЕАЛЬНО было в bundle -- расхождение -- отдельная пометка
инцидента ("модель уточнила базовую ставку"), не рутинный reject.

Один невалидный кандидат не блокирует остальные -- итерируем поштучно.
Одна строка agent_calls на ВЕСЬ вызов (не на forecast) -- FK на "многое"
живёт в forecasts.call_id (миграция №16, core/db_migrations.py).
"""
from __future__ import annotations

import sqlite3
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze.forecast_journal import init_schema, write_forecast

ADJUSTMENT_CAP = 0.15


def _find_bundle_candidate(bundle_json: dict, cand: dict) -> dict | None:
    """🔴 REVIEW_wp4_cycle_2026-08-13.md §5, разблокировано фиксом N+1:
    ключ focus теперь "symbol:tf" (один символ может пройти гейт на
    нескольких tf одновременно) -- модель обязана вернуть "tf" (см.
    agent_run.py JSON-схему), иначе кандидат не находится вообще
    (симметрично тому, как отсутствие/несовпадение любого другого
    natural-key поля уже не находит кандидата)."""
    focus = bundle_json.get("focus", {}) or {}
    key = f"{cand.get('symbol')}:{cand.get('tf')}"
    symbol_focus = focus.get(key, {})
    for c in symbol_focus.get("candidates", []):
        if (c.get("pattern_key") == cand.get("pattern_key")
                and c.get("direction") == cand.get("direction")
                and c.get("config_key") == cand.get("config_key")):
            return c
    return None


def _is_duplicate(con: sqlite3.Connection, symbol: str, horizon: str, event_key: str,
                   direction: str, created_ts: int) -> bool:
    """🔴 REVIEW_wp4_cycle_2026-08-13.md §2: один прогноз на (symbol, tf,
    bar_ts, event, direction) -- при 5 циклах/сутки и D1-баре тот же
    сигнал иначе даёт до 5 почти одинаковых строк, резолвер закроет их
    одинаково, n завышен. Явная проверка ДО записи (не просто отлов
    IntegrityError на UNIQUE INDEX) -- понятный reason в rejected."""
    row = con.execute(
        "SELECT 1 FROM forecasts WHERE symbol=? AND horizon=? AND event_key=? AND direction=? AND created_ts=?",
        (symbol, horizon, event_key, direction, created_ts),
    ).fetchone()
    return row is not None


def _validate_one(cand: dict, bundle_cand: dict | None) -> tuple[bool, str]:
    """Возвращает (ok, reason). reason непусто и при ok=True в одном
    случае -- "модель уточнила base_rate" -- см. вызывающий код: это
    отдельная пометка инцидента, а не обычный reject."""
    if bundle_cand is None:
        return False, "кандидат не найден в bundle (symbol/pattern_key/direction/config_key не совпадают)"

    base = bundle_cand["base_rate"]
    if not base["insufficient"]:
        for field, bundle_val in (("base_rate", base["p"]), ("base_n", base["n"]),
                                   ("base_backoff_level", base["backoff_level"])):
            model_val = cand.get(field)
            if model_val is None:
                return False, f"модель не вернула {field}"
            mismatch = (abs(model_val - bundle_val) > 0.001 if field == "base_rate"
                        else model_val != bundle_val)
            if mismatch:
                return False, f"модель уточнила {field}: bundle={bundle_val} модель={model_val}"

    adjustment = cand.get("adjustment", 0.0)
    cited = cand.get("cited_factors") or []
    final_p = cand.get("final_p")
    if abs(adjustment) > ADJUSTMENT_CAP and not cited:
        return False, f"|adjustment|={abs(adjustment):.3f} > {ADJUSTMENT_CAP} без cited_factors"
    if base["insufficient"] and final_p is not None:
        return False, "base_rate=insufficient, но final_p не null"
    if not base["insufficient"] and final_p is not None:
        expected = round(base["p"] + adjustment, 4)
        if abs(final_p - expected) > 0.01:
            return False, f"final_p={final_p} не согласуется с base_rate.p+adjustment={expected}"
    return True, ""


def _write_one(con: sqlite3.Connection, cand: dict, bundle_cand: dict, call_id: str,
               model_version: str) -> str:
    state = bundle_cand.get("_state", {})
    factors = [{"factor_key": k, "value": v, "zscore": None,
                "weight": 1.0 if k in (cand.get("cited_factors") or []) else 0.0}
               for k, v in state.items()]
    base = bundle_cand["base_rate"]
    if not base["insufficient"]:
        factors += [
            {"factor_key": "_meta.base_rate", "value": base["p"], "zscore": None, "weight": None},
            {"factor_key": "_meta.base_n", "value": base["n"], "zscore": None, "weight": None},
            {"factor_key": "_meta.base_backoff_level", "value": base["backoff_level"], "zscore": None, "weight": None},
            {"factor_key": "_meta.adjustment", "value": cand.get("adjustment"), "zscore": None, "weight": None},
        ]
    if bundle_cand.get("atr_val") is not None:
        factors.append({"factor_key": "_meta.atr_val", "value": bundle_cand["atr_val"], "zscore": None, "weight": None})

    thesis_full = (f"{cand.get('thesis', '')}\n[adjustment_reason] {cand.get('adjustment_reason', '')}\n"
                   f"[novel_risk] {cand.get('novel_risk') or '—'}")
    forecast = {
        "symbol": cand["symbol"], "horizon": cand["tf"], "event_key": f"barrier:{cand['config_key']}",
        "direction": cand["direction"], "conviction": cand.get("final_p"),
        "entry": bundle_cand["entry"], "entry_kind": bundle_cand["entry_kind"],
        "stop": bundle_cand["stop"], "target": bundle_cand["target"],
        "valid_until": bundle_cand["valid_until"], "invalidation": cand.get("invalidation"),
        "thesis": thesis_full, "model_version": model_version, "call_id": call_id,
    }
    fid = write_forecast(con, forecast, factors)
    con.execute("UPDATE forecasts SET created_ts=? WHERE id=?", (bundle_cand["created_ts"], fid))
    return fid


def _log_call(con: sqlite3.Connection, call_id: str, agent_result: dict,
              validation_status: str, validation_reason: str) -> None:
    """forecast_id/symbol/tf/event_key -- NULL при bundle-вызове (0-3
    forecast на один вызов, не 1:1) -- FK на "многое" живёт в
    forecasts.call_id (миграция №16), не утрамбован здесь списком
    (см. докстринг модуля)."""
    con.execute(
        """INSERT INTO agent_calls (call_id, ts, symbol, tf, event_key, forecast_id, model_version,
                                     prompt, raw_response, tool_calls_json, duration_ms, cost_usd,
                                     exit_code, validation_status, validation_reason)
           VALUES (?, ?, NULL, NULL, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (call_id, int(time.time()), agent_result.get("model"),
         None, agent_result.get("raw_stdout", "")[:20000], None,
         agent_result.get("duration_ms"), agent_result.get("cost_usd"),
         agent_result.get("exit_code"), validation_status, validation_reason[:2000]),
    )


def run_validate(con: sqlite3.Connection, bundle_json: dict, agent_result: dict) -> dict:
    """Возвращает {"written": [...], "rejected": [...], "validation_failed": int}.
    Никогда не raise -- любой провал agent_result уже оформлен как {"ok": False}."""
    init_schema(con)
    call_id = str(uuid.uuid4())

    if not agent_result.get("ok"):
        status = "timeout" if agent_result.get("exit_code") == -1 else "cli_error"
        _log_call(con, call_id, agent_result, status, agent_result.get("error", "") or "")
        con.commit()
        return {"written": [], "written_details": [], "rejected": [],
                "validation_failed": 0, "call_id": call_id}

    # bundle_cand.["_state"] -- пришиваем вектор состояния символа к каждому
    # его кандидату один раз, чтобы _write_one() не таскал bundle_json целиком.
    focus = bundle_json.get("focus", {}) or {}
    for f in focus.values():
        for c in f.get("candidates", []):
            c["_state"] = f.get("state", {})

    written, rejected = [], []
    # written_details -- id записанного прогноза рядом с ЕГО базовой ставкой.
    # Нужен для доставки (notify_gdenigi.send_written_forecasts): базовая
    # ставка с CI и n живёт только в бандле, в таблицу forecasts она не
    # попадает, а сообщение обязано нести "вероятность С ИНТЕРВАЛОМ И n,
    # не голое число" (WP6.3). Собирается здесь, потому что это единственная
    # точка, где прогноз и его bundle_cand уже сопоставлены.
    written_details = []
    for cand in agent_result.get("forecasts", []):
        bundle_cand = _find_bundle_candidate(bundle_json, cand)
        ok, reason = _validate_one(cand, bundle_cand)
        if not ok:
            rejected.append({"candidate": cand, "reason": reason})
            continue
        horizon = cand["tf"]  # H1/H4/D1 -- реальный tf кандидата, не хардкод (см. §5 ревью 13.08)
        event_key = f"barrier:{cand['config_key']}"
        if _is_duplicate(con, cand["symbol"], horizon, event_key, cand["direction"], bundle_cand["created_ts"]):
            rejected.append({"candidate": cand, "reason": "дубль: прогноз на этот бар уже записан "
                                                            "(естественный ключ symbol+horizon+event_key+direction+created_ts)"})
            continue
        fid = _write_one(con, cand, bundle_cand, call_id, agent_result.get("model", "unknown"))
        written.append(fid)
        written_details.append({"id": fid, "base": bundle_cand.get("base_rate")})

    validation_status = "ok" if written or not agent_result.get("forecasts") else "business_reject"
    validation_reason = "; ".join(r["reason"] for r in rejected)[:2000] if rejected else ""
    _log_call(con, call_id, agent_result, validation_status, validation_reason)
    con.commit()
    return {"written": written, "written_details": written_details,
            "rejected": rejected, "validation_failed": len(rejected), "call_id": call_id}
