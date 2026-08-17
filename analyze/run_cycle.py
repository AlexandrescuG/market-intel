#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/run_cycle.py — WP4.6 SPEC_alpha_engine_wp4_continuous_cycle.md,
оркестратор непрерывного цикла. Один процесс = один профиль = один tf
(--profile d1|h4|h1, см. CYCLE_PROFILES ниже), три независимых systemd timer.

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
🔴 14.08: единая частота 5 прогонов/сутки на все 3 tf разом сменилась
разделением по горизонтам (CYCLE_PROFILES) -- прямой вывод из разового
скрипта /tmp/.../scratchpad/h1_grid_coverage.py (эта же 5-часовая сетка
захватывала лишь 19.3% реальных H1-триггеров паттернов, 80.7% пропадали
между тиками незамеченными). Новое правило: интервал цикла не должен
превышать интервал самого быстрого анализируемого tf -- иначе это не
мониторинг, а выборочное подглядывание. Каждый профиль -- один tf, свой
маленький срез bundle (см. analyze/bundle.py::ALL_SECTIONS), свой systemd
timer с собственной частотой (~/.config/systemd/user/sbf-alpha-cycle-{d1,h4,h1}.timer).
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
from analyze import notify_gdenigi as _notify
from analyze import resolve as _resolve
from analyze import validate as _validate
from core import db as _core_db
from core import db_migrations as _db_migrations

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
FOCUS_UNIVERSE_V1 = ["GOLD", "EURUSD", "USDJPY", "USDCNY", "USDZAR"]

# tfs -- см. gate.py::_TF_TO_PB/decide(). sections -- см. bundle.py::ALL_SECTIONS,
# необязательные секции этого профиля (focus всегда считается). interval_sec --
# ожидаемый шаг МЕЖДУ прогонами этого профиля (соответствует systemd OnCalendar
# ниже) -- используется только для gap-детектора алерта, не читается gate/bundle.
# calendar_horizon_sec -- окно "на сколько вперёд" в calendar-секции, равно
# interval_sec (события не задваиваются и не пропадают между соседними
# прогонами ОДНОГО профиля).
CYCLE_PROFILES: dict[str, dict] = {
    "d1": {"tfs": ("D1",), "sections": ("calendar", "news", "macro", "watch", "calibration"),
           "calendar_horizon_sec": 86400, "interval_sec": 86400},
    "h4": {"tfs": ("H4",), "sections": ("calendar", "news", "watch"),
           "calendar_horizon_sec": 14400, "interval_sec": 14400},
    "h1": {"tfs": ("H1",), "sections": ("news",),
           "calendar_horizon_sec": None, "interval_sec": 3600},
}

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS cycle_runs (
      run_id TEXT PRIMARY KEY, started_ts INTEGER, finished_ts INTEGER,
      exit_code INTEGER, profile TEXT, gated_symbols TEXT,
      bundle_chars INTEGER, input_tokens INTEGER, output_tokens INTEGER,
      model TEXT, forecasts_written INTEGER, validation_failed INTEGER,
      duration_sec REAL, notes TEXT
    );
"""


def init_schema(con: sqlite3.Connection) -> None:
    con.executescript(_SCHEMA)
    con.commit()
    _db_migrations.apply_all(con)  # миграция №17: cycle_runs.profile на БД, где таблица уже была без неё


def _recent_exit_codes(con: sqlite3.Connection, profile: str, n: int = 3) -> list[int]:
    rows = con.execute(
        "SELECT exit_code FROM cycle_runs WHERE profile=? ORDER BY started_ts DESC LIMIT ?", (profile, n)
    ).fetchall()
    return [r[0] for r in rows]


def _last_run_ts(con: sqlite3.Connection, profile: str) -> int | None:
    row = con.execute("SELECT MAX(started_ts) FROM cycle_runs WHERE profile=?", (profile,)).fetchone()
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
    ap.add_argument("--profile", required=True, choices=sorted(CYCLE_PROFILES),
                     help="d1 (раз/сутки) | h4 (каждые 4ч) | h1 (каждый час) -- см. CYCLE_PROFILES")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--universe", nargs="+", default=FOCUS_UNIVERSE_V1)
    args = ap.parse_args()
    profile_cfg = CYCLE_PROFILES[args.profile]

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

        gate_result = _gate.decide(con, args.universe, started_ts, tfs=profile_cfg["tfs"])
        gated_symbols = gate_result["gated"]

        bundle_result = _bundle.build_bundle(
            con, gate_result, args.universe, started_ts, tfs=profile_cfg["tfs"],
            sections=profile_cfg["sections"],
            calendar_horizon_sec=profile_cfg["calendar_horizon_sec"] or _bundle.CYCLE_HORIZON_SEC)
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

                # Пункт 5 SPEC_alpha_engine_finish_handoff: прогнозы агента идут
                # в тот же outbox, что и Signals, с той же обязательной
                # status_label. Отправляет не этот код, а sbf-outbox-sender.timer.
                if val["written_details"]:
                    notified = _notify.send_written_forecasts(con, val["written_details"])
                    notes.append(f"outbox: {notified['enqueued']} прогноз(ов)")
                    if notified["failed"]:
                        exit_code = max(exit_code, 1)
                        notes.append(f"outbox_failed={notified['failed']}")
    except Exception as e:
        exit_code = 3
        notes.append(f"CRASH: {type(e).__name__}: {e}")
        if args.verbose:
            traceback.print_exc()

    finished_ts = int(time.time())
    duration_sec = round(finished_ts - started_ts, 2)

    try:
        con.execute(
            """INSERT INTO cycle_runs (run_id, started_ts, finished_ts, exit_code, profile, gated_symbols,
                                        bundle_chars, input_tokens, output_tokens, model,
                                        forecasts_written, validation_failed, duration_sec, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, started_ts, finished_ts, exit_code, args.profile,
             json.dumps(gated_symbols, ensure_ascii=False),
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
        _core_db.heartbeat(f"alpha_cycle_{args.profile}", ok=(exit_code != 3),
                            error="; ".join(notes)[:500] if exit_code == 3 else "")
    except Exception:
        pass

    should_alert = exit_code == 3
    if not should_alert:
        recent = _recent_exit_codes(con, args.profile, 3)
        if len(recent) == 3 and all(c == 3 for c in recent):
            should_alert = True
        # last_ts включает ЭТОТ прогон (уже вставлен выше) -- сравниваем со
        # ВТОРЫМ по свежести ЭТОГО ЖЕ профиля, иначе разрыв всегда будет "0"
        # от самого себя. Порог -- 2.5×interval_sec, масштабируется под
        # частоту профиля (H1: >2.5ч простоя тревожит, D1: >2.5 суток).
        prev_runs = con.execute(
            "SELECT started_ts FROM cycle_runs WHERE run_id != ? AND profile=? ORDER BY started_ts DESC LIMIT 1",
            (run_id, args.profile),
        ).fetchone()
        gap_threshold = 2.5 * profile_cfg["interval_sec"]
        if prev_runs and (started_ts - prev_runs[0]) > gap_threshold:
            should_alert = True
    if should_alert:
        _alert(f"[{args.profile}] run_id={run_id} exit_code={exit_code} notes={'; '.join(notes)}", args.verbose)

    con.close()
    if args.verbose:
        print(json.dumps({
            "run_id": run_id, "profile": args.profile, "exit_code": exit_code, "gated": gated_symbols,
            "bundle_chars": bundle_chars, "forecasts_written": forecasts_written,
            "validation_failed": validation_failed, "duration_sec": duration_sec,
            "cycle_runs_ok": cycle_runs_ok, "notes": notes,
        }, ensure_ascii=False, indent=2))
    sys.exit(0)  # 0/1/2/3 -- штатные исходы, не провал systemd-юнита


if __name__ == "__main__":
    main()
