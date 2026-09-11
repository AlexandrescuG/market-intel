#!/usr/bin/env python3
"""Разовый пересчёт истории Эпицентра под канонические имена.

ЗАЧЕМ. До 11.09.2026 упоминания считались под двумя именами на один актив:
«#NVIDIA» из разметки по словарю и «NVDA» из кештегов. Счётчик исправлен, но
в pulse_scores лежат 93 старых среза, собранных по старому правилу, — а из
них рисуется спарклайн за сутки и берётся сравнение «сутки назад». Пока
история не пересчитана, на графике живого инструмента будет провал там, где
на самом деле были упоминания, записанные под вторым именем.

🔴 ПЕРЕСЧИТЫВАЕМ, А НЕ СКЛЕИВАЕМ. Соблазн был сложить строки-близнецы и
переписать score суммой — но score это отношение, и знаменатель у близнецов
разный. Складывать отношения нельзя. Зато исходные данные никуда не делись:
и упоминания, и окно нормы восстанавливаются из signals по любому прошлому
моменту. Поэтому каждый срез считается заново теми же формулами, что и
живой прогон, — просто задним числом.

Побочный эффект, названный честно: прошлое пересчитывается по СЕГОДНЯШНИМ
правилам тегирования (включая фильтр заметок об отчётности, которого 10.09
ещё не было). История станет не «той, что была показана», а «той, что была
бы показана, будь правила такими с самого начала». Для графика нормы это
лучше: он перестанет сравнивать разнородные сутки.

Запуск: python3 tools/pulse_rebuild_history.py [--dry]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pulse_job as pj  # noqa: E402
from core.config import DB_PATH  # noqa: E402


def пересчитать(dry: bool = False) -> int:
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    срезы = [r[0] for r in con.execute(
        "SELECT DISTINCT ts FROM pulse_scores ORDER BY ts").fetchall()]
    print(f"срезов в истории: {len(срезы)}")
    if not срезы:
        return 0

    cats = pj._catalog_categories()
    blocked = pj._blocked()
    iso = lambda сек: datetime.fromtimestamp(сек, timezone.utc).isoformat()
    hours = pj.BASELINE_DAYS * 24 - pj.BURST_LOOKBACK_HOURS

    записано = 0
    for n, ts in enumerate(срезы, 1):
        h1 = iso(ts - pj.BURST_LOOKBACK_HOURS * 3600)
        d1 = iso(ts - pj.BOARD_WINDOW_HOURS * 3600)
        d7 = iso(ts - pj.BASELINE_DAYS * 86400)
        # Верхняя граница окна тоже нужна: иначе в «час перед срезом»
        # попадут новости, пришедшие уже ПОСЛЕ него.
        до = iso(ts)
        m1 = _окно(con, h1, до)
        m24 = _окно(con, d1, до)
        m7 = _окно(con, d7, до)

        строки = []
        for symbol in set(m7) | set(m24):
            if symbol in blocked:
                continue
            a, b, c = len(m1.get(symbol, ())), len(m24.get(symbol, ())), len(m7.get(symbol, ()))
            baseline = max(max(c - a, 0) / hours, pj.MIN_BASELINE)
            строки.append((symbol, pj._classify(symbol, cats), ts,
                           a, baseline, a / baseline, b))
        if dry:
            print(f"  [{n}/{len(срезы)}] {datetime.fromtimestamp(ts)}: {len(строки)} строк")
            continue
        con.execute("DELETE FROM pulse_scores WHERE ts=?", (ts,))
        con.executemany(
            "INSERT OR REPLACE INTO pulse_scores"
            "(symbol, category, ts, mentions, baseline, score, mentions_24h) "
            "VALUES(?,?,?,?,?,?,?)", строки)
        con.commit()
        записано += len(строки)
        if n % 10 == 0 or n == len(срезы):
            print(f"  [{n}/{len(срезы)}] записано строк всего: {записано}")
    con.close()
    return записано


def _окно(con, с_iso: str, до_iso: str) -> dict:
    """{канон: множество uid} за окно [с, до) — теги и кештеги вместе."""
    теги: dict[str, set] = {}
    for sym, uid in con.execute(
            """SELECT t.symbol, t.news_uid FROM news_instrument_tags t
               JOIN signals s ON s.uid = t.news_uid
               WHERE s.first_seen >= ? AND s.first_seen < ?""", (с_iso, до_iso)):
        теги.setdefault(pj.symbol_alias.canon(sym), set()).add(uid)

    import json
    кеш: dict[str, set] = {}
    for uid, raw in con.execute(
            "SELECT uid, cashtags FROM signals WHERE first_seen >= ? AND first_seen < ?",
            (с_iso, до_iso)):
        try:
            for t in json.loads(raw or "[]"):
                кеш.setdefault(pj.symbol_alias.canon(t), set()).add(uid)
        except (ValueError, TypeError):
            continue
    return pj._merge(теги, кеш)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="посчитать, но не писать")
    a = ap.parse_args()
    print(f"готово, строк записано: {пересчитать(a.dry)}")
