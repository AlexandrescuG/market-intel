#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Регрессия, найденная ручным аудитом 17.08 (пункт 9 SPEC_alpha_engine_finish_handoff).

С 15.08 агент отвечал HTTP 403 на КАЖДОМ автономном прогоне по таймеру — 47
вызовов за двое суток, ноль записанных прогнозов. Не заметили, потому что
отказ agent_run даёт exit_code=1, а алерт слался только при 3, и run_cycle
всегда завершается sys.exit(0) — systemd видел успех.

Здесь проверяется, что детектор ловит устойчивую техническую недоступность
и НЕ срабатывает на штатной работе валидатора (дубли, business_reject).
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze.run_cycle import _agent_unreachable_streak

_DDL = """CREATE TABLE agent_calls (
  call_id TEXT PRIMARY KEY, ts INTEGER, validation_status TEXT, raw_response TEXT)"""


def _con(statuses):
    """statuses — от старых к новым."""
    con = sqlite3.connect(":memory:")
    con.execute(_DDL)
    for i, st in enumerate(statuses):
        con.execute("INSERT INTO agent_calls (call_id, ts, validation_status, raw_response) "
                    "VALUES (?,?,?,?)", (f"c{i}", 1000 + i, st, '{"api_error_status":403}'))
    con.commit()
    return con


def test_три_отказа_подряд_дают_алерт():
    msg = _agent_unreachable_streak(_con(["ok", "cli_error", "cli_error", "cli_error"]), 3)
    assert msg is not None, "устойчивая недоступность агента не поднимает алерт"
    assert "403" in msg, f"в алерт не попал текст ошибки: {msg}"


def test_таймаут_считается_недоступностью():
    assert _agent_unreachable_streak(_con(["timeout", "cli_error", "timeout"]), 3) is not None


def test_business_reject_не_поднимает_алерт():
    """Дубли и отклонённые кандидаты — штатная работа валидатора. Алерт на них
    приучил бы игнорировать алерты вообще."""
    assert _agent_unreachable_streak(_con(["business_reject"] * 5), 3) is None


def test_успешный_вызов_сбрасывает_серию():
    assert _agent_unreachable_streak(_con(["cli_error", "cli_error", "ok"]), 3) is None


def test_мало_вызовов_не_алертит():
    """Свежая БД с двумя отказами — ещё не «устойчиво», ждём третьего."""
    assert _agent_unreachable_streak(_con(["cli_error", "cli_error"]), 3) is None
