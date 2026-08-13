#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/run_cycle.py — WP4.6 SPEC_alpha_engine_wp4_continuous_cycle.md,
оркестратор непрерывного цикла (sbf-alpha-cycle.timer, 5 раз/сутки).

Python, не bash — §0 спеки ("шаг возвращает {ok,data,error,degraded},
никогда не raise") контролируется try/except внутри одного процесса
точнее, чем `||`-цепочкой в bash (там теряется структура — видно только
"упал/не упал процесс", не "что именно из данных отсутствует").

Коды выхода (§6 спеки), записываются в cycle_runs, НЕ в sys.exit —
0/1/2/3 все штатные исходы для systemd (симметрично news_digest_job.py's
`stale`, не провал юнита); ненулевой sys.exit только если фатально не
удалось даже записать cycle_runs.
  0 — полный прогон
  1 — прогон с пропусками (часть источников недоступна / часть кандидатов отклонена)
  2 — гейт не пропустил, модель не звалась (норма, не инцидент)
  3 — пакет не собрался вообще / необработанное исключение (алерт человеку)
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import traceback
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze import agent_run as _agent_run
from analyze import bundle as _bundle
from analyze import gate as _gate
from analyze import resolve as _resolve
from analyze import validate as _validate
from core import db as _core_db

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
FOCUS_UNIVERSE_V1 = ["GOLD", "EURUSD", "USDJPY", "USDCNY", "USDZAR"]

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS cycle_runs (
      run_id TEXT PRIMARY KEY, started_ts INTEGER, finished_ts INTEGER,
      exit_code INTEGER, gated_symbols TEXT,
      bundle_chars INTEGER, input_tokens INTEGER, output_tokens INTEGER,
      model TEXT, forecasts_written INTEGER, validation_failed INTEGER,
      duration_sec REAL, notes TEXT
    );
"""


def init_schema(con: sqlite3.Connection) -> None:
    con.executescript(_SCHEMA)
    con.commit()


def _recent_exit_codes(con: sqlite3.Connection, n: int = 3) -> list[int]:
    rows = con.execute(
        "SELECT exit_code FROM cycle_runs ORDER BY started_ts DESC LIMIT ?", (n,)
    ).fetchall()
    return [r[0] for r in rows]


def _last_run_ts(con: sqlite3.Connection) -> int | None:
    row = con.execute("SELECT MAX(started_ts) FROM cycle_runs").fetchone()
    return row[0] if row and row[0] is not None else None


def _alert(message: str, verbose: bool) -> None:
    """exit_code=3 (или 3 подряд, или разрыв >12ч) -- единственное, что
    будит человека. core.telegram/TELEGRAM_REPORT_CHAT_ID -- операционный
    алерт человеку, НЕ @gdenigi_bot (разные назначения, разные каналы,
    см. WP4.7). Отказ отправки НЕ должен ронять сам цикл."""
    try:
        import asyncio
        from core.telegram import send_text
        from core.config import TELEGRAM_REPORT_CHAT_ID
        asyncio.run(send_text(f"⚠️ alpha_cycle: {message}", chat_id=TELEGRAM_REPORT_CHAT_ID))
    except Exception as e:
        if verbose:
            print(f"алерт не отправлен: {e}", file=sys.stderr)


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--universe", nargs="+", default=FOCUS_UNIVERSE_V1)
    args = ap.parse_args()

    run_id = str(uuid.uuid4())
    started_ts = int(time.time())
    con = sqlite3.connect(str(_BOT_DB))
    init_schema(con)

    exit_code = 0
    notes: list[str] = []
    gated_symbols: list[str] = []
    bundle_chars = 0
    input_tokens = output_tokens = None
    model = None
    forecasts_written = 0
    validation_failed = 0

    try:
        resolve_result = _resolve.run_resolve(con, args.verbose)
        notes.append(f"resolved={resolve_result['n_resolved']}")

        gate_result = _gate.decide(con, args.universe, started_ts)
        gated_symbols = gate_result["gated"]

        bundle_result = _bundle.build_bundle(con, gate_result, args.universe, started_ts)
        bundle_chars = bundle_result["meta"]["bundle_chars"]
        if bundle_result["json"]["gaps"]:
            exit_code = max(exit_code, 1)
            notes.append(f"gaps={bundle_result['json']['gaps']}")
        _, md_path = _bundle.write_bundle(bundle_result, started_ts)

        if not gate_result["model_should_run"]:
            exit_code = max(exit_code, 2)
            notes.append("гейт никого не пропустил")
        else:
            agent_result = _agent_run.call_agent(md_path)
            model = agent_result.get("model")
            input_tokens = agent_result.get("input_tokens")
            output_tokens = agent_result.get("output_tokens")
            if not agent_result.get("ok"):
                exit_code = max(exit_code, 1)
                notes.append(f"agent_run отказ: {agent_result.get('error')}")
                # Всё равно логируем провал в agent_calls -- полезно для аудита.
                val = _validate.run_validate(con, bundle_result["json"], agent_result)
            else:
                val = _validate.run_validate(con, bundle_result["json"], agent_result)
                forecasts_written = len(val["written"])
                validation_failed = val["validation_failed"]
                if validation_failed > 0:
                    exit_code = max(exit_code, 1)
                    notes.append(f"validation_failed={validation_failed}")
    except Exception as e:
        exit_code = 3
        notes.append(f"CRASH: {type(e).__name__}: {e}")
        if args.verbose:
            traceback.print_exc()

    finished_ts = int(time.time())
    duration_sec = round(finished_ts - started_ts, 2)

    try:
        con.execute(
            """INSERT INTO cycle_runs (run_id, started_ts, finished_ts, exit_code, gated_symbols,
                                        bundle_chars, input_tokens, output_tokens, model,
                                        forecasts_written, validation_failed, duration_sec, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, started_ts, finished_ts, exit_code, json.dumps(gated_symbols, ensure_ascii=False),
             bundle_chars, input_tokens, output_tokens, model, forecasts_written, validation_failed,
             duration_sec, "; ".join(notes)[:2000]),
        )
        con.commit()
        cycle_runs_ok = True
    except Exception as e:
        cycle_runs_ok = False
        if args.verbose:
            print(f"не удалось записать cycle_runs: {e}", file=sys.stderr)

    try:
        _core_db.heartbeat("alpha_cycle", ok=(exit_code != 3),
                            error="; ".join(notes)[:500] if exit_code == 3 else "")
    except Exception:
        pass

    should_alert = exit_code == 3
    if not should_alert:
        recent = _recent_exit_codes(con, 3)
        if len(recent) == 3 and all(c == 3 for c in recent):
            should_alert = True
        last_ts = _last_run_ts(con)
        # last_ts включает ЭТОТ прогон (уже вставлен выше) -- сравниваем со
        # ВТОРЫМ по свежести, иначе разрыв всегда будет "0" от самого себя.
        prev_runs = con.execute(
            "SELECT started_ts FROM cycle_runs WHERE run_id != ? ORDER BY started_ts DESC LIMIT 1", (run_id,)
        ).fetchone()
        if prev_runs and (started_ts - prev_runs[0]) > 12 * 3600:
            should_alert = True
    if should_alert:
        _alert(f"run_id={run_id} exit_code={exit_code} notes={'; '.join(notes)}", args.verbose)

    con.close()
    if args.verbose:
        print(json.dumps({
            "run_id": run_id, "exit_code": exit_code, "gated": gated_symbols,
            "bundle_chars": bundle_chars, "forecasts_written": forecasts_written,
            "validation_failed": validation_failed, "duration_sec": duration_sec,
            "cycle_runs_ok": cycle_runs_ok, "notes": notes,
        }, ensure_ascii=False, indent=2))
    sys.exit(0)  # 0/1/2/3 -- штатные исходы, не провал systemd-юнита


if __name__ == "__main__":
    main()
