"""WP3 — Табло верификации. Замыкает петлю прогноз → реальный исход.

Наблюдения парсятся из утреннего отчёта (секция НОВЫЕ_НАБЛЮДЕНИЯ),
сверяются с yfinance при наступлении checkpoint-даты.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, date, timedelta, timezone

from core.config import DB_PATH
from core import credibility


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return sqlite3.connect(DB_PATH)


# ─── Парсинг отчёта ────────────────────────────────────────────────────────────

_OBS_RE = re.compile(
    r"\|\s*(?P<date>\d{4}-\d{2}-\d{2})\s*\|\s*(?P<text>[^|]+?)\s*\|\s*(?P<checkpoint>\d{4}-\d{2}-\d{2})\s*\|",
    re.MULTILINE,
)
_TICKER_RE = re.compile(r"\b([A-Z]{2,5}(?:\.[A-Z]{1,2})?)\b")


def _guess_ticker(text: str, cashtags: list[str]) -> str | None:
    if cashtags:
        return cashtags[0]
    m = _TICKER_RE.search(text)
    return m.group(1) if m else None


def _guess_direction(text: str) -> str:
    tl = text.lower()
    if any(w in tl for w in ["рост", "вырастет", "up", "выше", "выработает", "bullish", "↑"]):
        return "up"
    if any(w in tl for w in ["падение", "упадёт", "down", "ниже", "bearish", "↓"]):
        return "down"
    return "range"


def parse_observations(report_path: str, source_handle: str = "llm") -> int:
    """Извлечь наблюдения из секции НОВЫЕ_НАБЛЮДЕНИЯ отчёта. Вернуть кол-во."""
    try:
        text = open(report_path, encoding="utf-8").read()
    except FileNotFoundError:
        return 0

    # Вырезать секцию
    section_match = re.search(
        r"(?:НОВЫЕ_НАБЛЮДЕНИЯ|NEW_OBSERVATIONS)(.*?)(?:\n##|\Z)",
        text, re.DOTALL | re.IGNORECASE,
    )
    if not section_match:
        return 0

    section = section_match.group(1)
    matches = list(_OBS_RE.finditer(section))
    if not matches:
        return 0

    from core.market import snapshot, to_ticker
    added = 0

    with _db() as db:
        for m in matches:
            obs_text = m.group("text").strip()
            checkpoint = m.group("checkpoint")
            ticker_guess = _guess_ticker(obs_text, [])

            # Получить baseline
            baseline = None
            if ticker_guess:
                try:
                    snap = snapshot([to_ticker(ticker_guess)])
                    for v in snap.values():
                        baseline = v.get("price")
                        break
                except Exception:
                    pass

            db.execute(
                """INSERT OR IGNORE INTO observations
                   (created, source_handle, text, ticker, baseline,
                    checkpoint, direction, status)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (_now(), source_handle, obs_text, ticker_guess,
                 baseline, checkpoint,
                 _guess_direction(obs_text), "pending")
            )
            added += 1
        db.commit()

    return added


def resolve_due() -> int:
    """Проверить все наблюдения с наступившим checkpoint. Вернуть кол-во resolved."""
    today = date.today().isoformat()
    resolved = 0

    with _db() as db:
        due = db.execute(
            "SELECT * FROM observations WHERE status='pending' AND checkpoint <= ?",
            (today,)
        ).fetchall()
        cols = [c[0] for c in db.execute("SELECT * FROM observations LIMIT 0").description]

    from core.market import snapshot, to_ticker

    for row in due:
        obs = dict(zip(cols, row))
        ticker = obs.get("ticker")
        baseline = obs.get("baseline")
        direction = obs.get("direction", "range")
        status = "unverifiable"
        resolved_val = None

        if ticker and baseline:
            try:
                snap = snapshot([to_ticker(ticker)])
                current = next(iter(snap.values()), {}).get("price")
                if current is not None:
                    move = (current - baseline) / baseline * 100
                    resolved_val = round(move, 3)
                    if direction == "up":
                        status = "confirmed" if move > 0.5 else "refuted"
                    elif direction == "down":
                        status = "confirmed" if move < -0.5 else "refuted"
                    else:
                        status = "confirmed" if abs(move) < 3 else "refuted"
            except Exception:
                pass

        with _db() as db:
            db.execute(
                "UPDATE observations SET status=?, resolved=?, resolved_at=? WHERE id=?",
                (status, resolved_val, _now(), obs["id"])
            )
            db.commit()

        if status in ("confirmed", "refuted") and obs.get("source_handle"):
            credibility.record_outcome(obs["source_handle"], status == "confirmed")

        resolved += 1

    return resolved


def scorecard() -> dict:
    with _db() as db:
        rows = db.execute(
            "SELECT status, COUNT(*) as n FROM observations GROUP BY status"
        ).fetchall()
    counts = {r[0]: r[1] for r in rows}
    total = sum(counts.values())
    confirmed = counts.get("confirmed", 0)
    refuted = counts.get("refuted", 0)
    done = confirmed + refuted
    return {
        "total": total,
        "confirmed": confirmed,
        "refuted": refuted,
        "pending": counts.get("pending", 0),
        "unverifiable": counts.get("unverifiable", 0),
        "hit_rate": round(confirmed / done, 3) if done else None,
    }


def recent_observations(limit: int = 20) -> list[dict]:
    with _db() as db:
        cur = db.execute(
            "SELECT * FROM observations ORDER BY created DESC LIMIT ?", (limit,)
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
