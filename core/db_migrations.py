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
    (17, "cycle_runs.profile",
     "ALTER TABLE cycle_runs ADD COLUMN profile TEXT"),
    # §3 SPEC_mt5_cost_calibration_2026-08-18.md. Таблица ОТДЕЛЬНАЯ от
    # forecasts: связь по forecast_id, но никакого влияния обратно.
    # Контур калибрует core/costs.py и не участвует ни в резолюции, ни в
    # bss, ни в форвард-треке — «если изменится хоть одна цифра
    # трек-рекорда, это дефект, а не фича» (§0 спеки).
    #
    # order_status NOT NULL без DEFAULT намеренно, по той же причине, по
    # которой обязателен status_label в сообщениях: состояние «непонятно,
    # что произошло» не должно быть представимо.
    (18, "cost_observations",
     """CREATE TABLE IF NOT EXISTS cost_observations (
          id INTEGER PRIMARY KEY,
          forecast_id TEXT,
          created_ts INTEGER NOT NULL,
          account INTEGER NOT NULL,
          server TEXT NOT NULL,
          symbol TEXT NOT NULL,
          broker_symbol TEXT NOT NULL,
          tf TEXT NOT NULL,
          direction TEXT NOT NULL,
          volume REAL NOT NULL,
          magic INTEGER NOT NULL,
          pred_cost_price REAL,
          pred_swap_night REAL,
          pred_spread_atr REAL,
          req_price REAL,
          req_ts INTEGER,
          ticket INTEGER,
          deal_entry_price REAL,
          deal_exit_price REAL,
          commission REAL,
          swap REAL,
          spread_at_entry REAL,
          slippage_entry REAL,
          nights_held INTEGER,
          closed_ts INTEGER,
          order_status TEXT NOT NULL,
          note TEXT
        )"""),
    (19, "cost_observations: индексы для добора закрытых и отчёта",
     "CREATE INDEX IF NOT EXISTS idx_cost_obs_open "
     "ON cost_observations(order_status, ticket)"),
    # SPEC_brief_outliers_2026-08-25.md §2.3
    (20, "market_outliers: аномальные движения из скринеров",
     """CREATE TABLE IF NOT EXISTS market_outliers (
          id INTEGER PRIMARY KEY,
          first_seen_ts INTEGER NOT NULL,
          last_seen_ts  INTEGER NOT NULL,
          symbol TEXT NOT NULL,
          name TEXT,
          asset_class TEXT NOT NULL,
          chg_pct REAL NOT NULL,
          price REAL,
          dollar_volume REAL,
          screener TEXT,
          peak_chg_pct REAL,
          news_cluster_id INTEGER,
          alerted_ts INTEGER,
          alert_suppressed TEXT,
          alert_chg_pct REAL,
          brief_date TEXT
        )"""),
    (21, "market_outliers: один инструмент — одна запись в сутки",
     "CREATE UNIQUE INDEX IF NOT EXISTS idx_outlier_day "
     "ON market_outliers(symbol, date(first_seen_ts,'unixepoch'))"),
    (22, "market_outliers: выборка неотправленных",
     "CREATE INDEX IF NOT EXISTS idx_outlier_pending "
     "ON market_outliers(alerted_ts, last_seen_ts)"),
    # §3.1: темы-всплески. Кластер живёт отдельно от новостей — одна тема
    # собирает много заголовков, и связь с выбросом цены (news_cluster_id
    # выше) должна указывать на ТЕМУ, а не на конкретную публикацию.
    (23, "news_clusters: темы со всплеском охвата",
     """CREATE TABLE IF NOT EXISTS news_clusters (
          id INTEGER PRIMARY KEY,
          created_ts INTEGER NOT NULL,
          day TEXT NOT NULL,
          kind TEXT NOT NULL,
          key TEXT NOT NULL,
          label TEXT,
          publishers INTEGER NOT NULL,
          items INTEGER NOT NULL,
          sample_title TEXT,
          sample_url TEXT,
          outlier_symbol TEXT,
          summary TEXT,
          summary_status TEXT,
          brief_date TEXT
        )"""),
    (24, "news_clusters: одна тема на сутки",
     "CREATE UNIQUE INDEX IF NOT EXISTS idx_news_cluster_day "
     "ON news_clusters(day, kind, key)"),
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
