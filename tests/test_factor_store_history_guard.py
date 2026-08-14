"""Тест на защиту от lookahead через "снэпшот"-семейства факторов (history=0).

14.08: ревью нашло, что `factor_keys_without_history()` (написана 12.08,
§4 ревью) физически существовала, но ни разу не вызывалась ни одним
реальным потребителем — защита была подключена только к `snapshot_for_
backtest()`, которую тоже никто не вызывал. С этой правкой фильтр встроен
в саму `snapshot()` при любом as_of не None (см. её докстринг) — этот тест
подтверждает эмпирически, а не только "код выглядит правильным", что
исторический вызов реально не может получить non-history фактор, даже
если тот формально проходит проверку asof_ts<=as_of.

_connect() жёстко привязан к _BOT_DB (нет параметра тестовой БД) —
monkeypatch на временный файл, не трогаем прод. db_migrations.apply_all()
пропущен (no-op) -- миграция №15 (factor_registry.history) уже включена
прямо в _SCHEMA этого модуля, свежесозданной таблице она не нужна, а
apply_all() на голой БД падает на таблицах других миграций (см. Core-лог
13.08, тот же обходной путь, что уже использовался для forecast_journal)."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import core.db_migrations as db_migrations
import core.factor_store as factor_store


def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_factor_store.db"
    monkeypatch.setattr(factor_store, "_BOT_DB", db_path)
    monkeypatch.setattr(db_migrations, "apply_all", lambda con: [])
    return db_path


def test_snapshot_as_of_none_returns_non_history_factor(tmp_path, monkeypatch):
    """Live-режим (as_of=None) НЕ фильтрует -- это не бэктест, репейнт
    неактуален, снэпшот "как сейчас" -- ровно то, что и нужно."""
    _isolated_db(tmp_path, monkeypatch)
    factor_store.register_factor("sentiment.score", family="sentiment", history=False)
    factor_store.put_many([{"symbol": "GOLD", "tf": "D1", "ts": 100, "factor_key": "sentiment.score",
                             "value": 0.5, "asof_ts": 100}])

    result = factor_store.snapshot("GOLD", "D1", 100, as_of=None)
    assert result == {"sentiment.score": 0.5}


def test_snapshot_as_of_filters_non_history_factor(tmp_path, monkeypatch):
    """Ядро защиты: as_of не None -- исторический вызов -- non-history
    factor_key ИСКЛЮЧЁН из результата, даже если формально asof_ts<=as_of."""
    _isolated_db(tmp_path, monkeypatch)
    factor_store.register_factor("sentiment.score", family="sentiment", history=False)
    factor_store.register_factor("ema20_dist_atr", family="trend", history=True)
    factor_store.put_many([
        {"symbol": "GOLD", "tf": "D1", "ts": 100, "factor_key": "sentiment.score",
         "value": 0.5, "asof_ts": 100},
        {"symbol": "GOLD", "tf": "D1", "ts": 100, "factor_key": "ema20_dist_atr",
         "value": 1.2, "asof_ts": 100},
    ])

    result = factor_store.snapshot("GOLD", "D1", 100, as_of=100)
    assert result == {"ema20_dist_atr": 1.2}
    assert "sentiment.score" not in result


def test_snapshot_for_backtest_requires_as_of():
    """Обязательный as_of в сигнатуре -- бэктест-код, забывший его передать,
    получает TypeError на месте вызова, а не тихий live-режим."""
    import inspect
    sig = inspect.signature(factor_store.snapshot_for_backtest)
    assert sig.parameters["as_of"].default is inspect.Parameter.empty


def test_snapshot_for_backtest_delegates_same_filter(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)
    factor_store.register_factor("news.pulse_score", family="news", history=False)
    factor_store.put_many([{"symbol": "GOLD", "tf": "D1", "ts": 100, "factor_key": "news.pulse_score",
                             "value": 3.0, "asof_ts": 100}])

    result = factor_store.snapshot_for_backtest("GOLD", "D1", 100, as_of=100)
    assert result == {}
