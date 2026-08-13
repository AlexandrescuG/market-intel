"""core/db_migrations.py — WP1.4 SPEC_alpha_engine_implementation.md.

Версионированный механизм вместо N независимых копий одного и того же
списка `ALTER TABLE ... ADD COLUMN` в try/except pass. Было дублировано в
`serve.py` (14 колонок) и `event_reactions_job.py` (12 колонок) -- списки
УЖЕ разошлись: serve.py знает про `median_move_30m`/`median_atr_30m`,
event_reactions_job.py — нет (см. Core-лог 08.08, найдено при сведении).

MIGRATIONS — пронумерованный список шагов. Правила:
  - новые миграции дописываются В КОНЕЦ с следующим номером;
  - уже применённые НЕ редактируются и не удаляются (история);
  - apply_all() идемпотентна: колонка, добавленная старым try/except-кодом
    до появления этого модуля, просто помечается применённой, а не рушит
    прогон повторной попыткой ADD COLUMN.

`econ_event_history`, объявленная в двух местах с разными типами (TEXT в
calendar_pull.py, было REAL в serve.py) — уже исправлена отдельной сессией
06.08.2026 (см. Core-лог), здесь не трогается; но именно этот класс ошибки
(DDL не меняет тип задним числом, только PRAGMA table_info покажет реальность)
ровно то, для чего нужен versioned-механизм на будущее.
"""
from __future__ import annotations

import sqlite3

# (version, description, ddl)
MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "event_reaction_stats.median_move_30m",
     "ALTER TABLE event_reaction_stats ADD COLUMN median_move_30m REAL"),
    (2, "event_reaction_stats.median_atr_30m",
     "ALTER TABLE event_reaction_stats ADD COLUMN median_atr_30m REAL"),
    (3, "event_reaction_stats.hourly_baseline_30m",
     "ALTER TABLE event_reaction_stats ADD COLUMN hourly_baseline_30m REAL"),
    (4, "event_reaction_stats.baseline_ratio_30m",
     "ALTER TABLE event_reaction_stats ADD COLUMN baseline_ratio_30m REAL"),
    (5, "event_reaction_stats.period_from",
     "ALTER TABLE event_reaction_stats ADD COLUMN period_from TEXT"),
    (6, "event_reaction_stats.period_to",
     "ALTER TABLE event_reaction_stats ADD COLUMN period_to TEXT"),
    (7, "event_reaction_stats.avg_move_4h",
     "ALTER TABLE event_reaction_stats ADD COLUMN avg_move_4h REAL"),
    (8, "event_reaction_stats.max_move_4h",
     "ALTER TABLE event_reaction_stats ADD COLUMN max_move_4h REAL"),
    (9, "event_reaction_stats.n_beat",
     "ALTER TABLE event_reaction_stats ADD COLUMN n_beat INT"),
    (10, "event_reaction_stats.beat_up_share",
     "ALTER TABLE event_reaction_stats ADD COLUMN beat_up_share REAL"),
    (11, "event_reaction_stats.beat_down_share",
     "ALTER TABLE event_reaction_stats ADD COLUMN beat_down_share REAL"),
    (12, "event_reaction_stats.n_miss",
     "ALTER TABLE event_reaction_stats ADD COLUMN n_miss INT"),
    (13, "event_reaction_stats.miss_up_share",
     "ALTER TABLE event_reaction_stats ADD COLUMN miss_up_share REAL"),
    (14, "event_reaction_stats.miss_down_share",
     "ALTER TABLE event_reaction_stats ADD COLUMN miss_down_share REAL"),
    (15, "factor_registry.history",
     "ALTER TABLE factor_registry ADD COLUMN history INTEGER DEFAULT 1"),
    (16, "forecasts.call_id",
     "ALTER TABLE forecasts ADD COLUMN call_id TEXT"),
]


def apply_all(con: sqlite3.Connection) -> list[int]:
    """Применяет все шаги MIGRATIONS, которых нет в schema_version.
    Возвращает номера версий, применённые В ЭТОМ вызове (обычно пусто —
    штатный случай, схема уже актуальна)."""
    con.execute(
        "CREATE TABLE IF NOT EXISTS schema_version "
        "(version INTEGER PRIMARY KEY, applied_ts INTEGER, description TEXT)"
    )
    applied = {r[0] for r in con.execute("SELECT version FROM schema_version")}
    newly_applied = []
    for version, description, ddl in MIGRATIONS:
        if version in applied:
            continue
        try:
            con.execute(ddl)
        except sqlite3.OperationalError as e:
            # Колонка уже есть — добавлена старым try/except-кодом ДО того,
            # как появился этот модуль. Не аварийно, просто фиксируем номер.
            if "duplicate column" not in str(e).lower():
                raise
        con.execute(
            "INSERT INTO schema_version (version, applied_ts, description) "
            "VALUES (?, strftime('%s','now'), ?)",
            (version, description),
        )
        newly_applied.append(version)
    con.commit()
    return newly_applied
