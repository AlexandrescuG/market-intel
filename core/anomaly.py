"""WP10 — Аномалии. Статистические всплески упоминаний/engagement по z-score."""
from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from core.config import DB_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return sqlite3.connect(DB_PATH)


def update_baselines(hours: int = 6) -> None:
    """Пересчитать распределение упоминаний/engagement по тикеру на истории
    7 дней, окнами по `hours` часов -- та же длина окна, что `anomalies()`
    использует для "текущего" среза, иначе сравнение разномасштабно.

    [ИСПРАВЛЕНО] Раньше baseline считался по ОТДЕЛЬНЫМ сигналам: каждое
    упоминание добавляло в список константу 1.0. Среднее такого списка
    всегда 1.0, а std -- всегда 0.0 (дисперсии внутри списка одинаковых
    чисел не бывает). anomalies() ниже отбраковывает всё с std < 0.1 --
    то есть КАЖДЫЙ тикер, независимо от реальной активности. anomalies.json
    был пуст не потому что аномалий не было, а потому что тест не мог
    сработать структурно ни при каких данных. Проверено на реальной БД
    (48k+ сигналов за полтора месяца): baselines.std_mentions было 0.0 для
    всех тикеров без исключения. Теперь считаем упоминания по бакетам
    длиной `hours`, mean/std -- по РАСПРЕДЕЛЕНИЮ количества упоминаний
    между бакетами (это и есть содержательный baseline).
    """
    lookback_days = 7
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    now = _now()
    bucket_seconds = hours * 3600

    with _db() as db:
        signals = db.execute(
            "SELECT cashtags, engagement, last_seen FROM signals WHERE last_seen >= ?",
            (cutoff,)
        ).fetchall()

    bucket_counts: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    bucket_eng: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))

    for cashtags_json, engagement, last_seen in signals:
        try:
            tags = json.loads(cashtags_json or "[]")
        except Exception:
            tags = []
        if not tags or not last_seen:
            continue
        try:
            ts = datetime.fromisoformat(last_seen).timestamp()
        except Exception:
            continue
        bucket = int(ts // bucket_seconds)
        for tag in tags:
            bucket_counts[tag][bucket] += 1
            bucket_eng[tag][bucket] += float(engagement or 0)

    def _stats(vals: list[float]) -> tuple[float, float]:
        n = len(vals)
        if n < 2:
            return (round(vals[0], 3) if vals else 0.0, 0.0)
        mean = sum(vals) / n
        std = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1))
        return round(mean, 3), round(std, 3)

    with _db() as db:
        for tag in set(bucket_counts) | set(bucket_eng):
            cnt_vals = list(bucket_counts[tag].values())
            eng_vals = list(bucket_eng[tag].values())
            m_cnt, s_cnt = _stats(cnt_vals)
            m_eng, s_eng = _stats(eng_vals)
            # samples = число ИСТОРИЧЕСКИХ окон по `hours` часов, где тикер
            # вообще встречался -- не число сигналов, как было раньше.
            samples = len(cnt_vals)
            db.execute(
                """INSERT INTO baselines (key, mean_mentions, std_mentions,
                   mean_engagement, std_engagement, samples, updated)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(key) DO UPDATE SET
                     mean_mentions=excluded.mean_mentions,
                     std_mentions=excluded.std_mentions,
                     mean_engagement=excluded.mean_engagement,
                     std_engagement=excluded.std_engagement,
                     samples=excluded.samples,
                     updated=excluded.updated""",
                (f"ticker:{tag}", m_cnt, s_cnt, m_eng, s_eng, samples, now)
            )
        db.commit()


def anomalies(z: float = 2.5, hours: int = 6) -> list[dict]:
    """Вернуть тикеры/термины с аномально высокой активностью за `hours` часов."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    with _db() as db:
        signals = db.execute(
            "SELECT cashtags, engagement FROM signals WHERE last_seen >= ?",
            (cutoff,)
        ).fetchall()

    current_counts: dict[str, int] = defaultdict(int)
    current_eng: dict[str, float] = defaultdict(float)
    for cashtags_json, engagement in signals:
        try:
            tags = json.loads(cashtags_json or "[]")
        except Exception:
            tags = []
        for tag in tags:
            current_counts[tag] += 1
            current_eng[tag] += float(engagement or 0)

    result = []
    with _db() as db:
        for tag, count in current_counts.items():
            row = db.execute(
                "SELECT mean_mentions, std_mentions, samples FROM baselines WHERE key=?",
                (f"ticker:{tag}",)
            ).fetchone()
            if row is None or row[2] < 5:
                continue
            mean, std, _ = row
            if std < 0.1:
                continue
            z_score = (count - mean) / std
            if z_score >= z:
                result.append({
                    "tag": tag,
                    "current": count,
                    "baseline_mean": round(mean, 2),
                    "z_score": round(z_score, 2),
                    "engagement": round(current_eng[tag], 0),
                })

    return sorted(result, key=lambda x: -x["z_score"])
