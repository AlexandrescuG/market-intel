#!/usr/bin/env python3
"""
news_digest_job.py — SPEC_site_fixes_2026-07-29.md §8.

Офлайн-джоб (раз в час, см. sbf-news-digest.timer): читает RSS-сигналы за
последний час из signals.db, просит claude -p headless составить короткую
сводку "что сейчас происходит" и пишет web/data/news_digest.json.

Числа (items_used, sources, updated) считает код, не модель — модель пишет
только текст (тот же принцип, что build_brief_v2.py/llm_context.py). Текст
проходит validate() на выходе: словами прогноза/рекомендации/будущим временем
рядом с "%" датасайт превращать в подателя инвестрекомендаций нельзя. Провал
валидации или падение claude -p -- не пустая панель и не сырой вывод модели,
а предыдущая сводка с "stale": true (см. run()).

Использование:
  python3 news_digest_job.py [--verbose]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent))
from core.config import BASE_DIR, DATA_DIR, DB_PATH  # noqa: E402

WEB_DATA = BASE_DIR / "web" / "data"
OUT_PATH = WEB_DATA / "news_digest.json"
DRAFT_PATH = DATA_DIR / "reports" / "news_digest_draft.json"
REJECTED_LOG = DATA_DIR / "reports" / "news_digest_rejected.log"

CLAUDE_BIN = str(Path.home() / ".local" / "bin" / "claude")
CLAUDE_TIMEOUT_SEC = 55  # спека: "джоб отрабатывает за минуту"

MAX_LEN = 400
LOOKBACK_HOURS = 1
MAX_HEADLINES = 60  # ограничиваем промпт разумным размером, не тащим весь час буквально

EMPTY_HOUR_TEXT_RU = "За последний час не собрано публикаций, о которых стоило бы сообщить отдельно."

# Лексикон, не ML — тот же подход, что core/scoring.py/core/feed_filter.py.
_FORECAST_WORDS = [
    "ожидается", "ожидаем", "ожидают", "прогноз", "прогнозирует", "прогнозируют",
    "цель по цене", "target price",
    "вырастет", "вырастут", "упадёт", "упадет", "упадут", "снизится", "снизятся",
    "повысится", "повысятся", "подорожает", "подешевеет", "продолжит", "продолжится",
    "будет расти", "будет падать", "поднимется", "опустится", "может вырасти",
    "может упасть", "ожидать", "expected", "expects", "forecast", "will rise",
    "will fall", "will continue", "likely to",
]
_RECO_WORDS = [
    "покупать", "продавать", "стоит купить", "стоит продать", "рекомендуем",
    "рекомендация", "точка входа", "buy", "sell", "recommend",
]
_FUTURE_TENSE_NEAR_PCT = [
    "ожидается", "продолжит", "вырастет", "упадёт", "упадет", "будет", "прогноз",
    "составит", "достигнет", "expected", "will",
]
_PCT_RE = re.compile(r"\d+([.,]\d+)?\s*%")


def validate(text) -> str | None:
    """None -- сводка отклонена, вызывающий код решает, что делать (см. run()).
    По образцу analyze/llm_context.py:42-64 -- форма/содержание, не бросает исключение."""
    if not isinstance(text, str):
        return None
    t = text.strip()
    if not t or len(t) > MAX_LEN:
        return None
    low = t.lower()
    if any(w in low for w in _FORECAST_WORDS):
        return None
    if any(w in low for w in _RECO_WORDS):
        return None
    for m in _PCT_RE.finditer(low):
        window = low[max(0, m.start() - 40): m.end() + 40]
        if any(tok in window for tok in _FUTURE_TENSE_NEAR_PCT):
            return None
    return t


def _recent_rss(hours: int = LOOKBACK_HOURS) -> list[dict]:
    """last_seen -- когда сигнал последний раз задет upsert'ом, а НЕ когда
    статья опубликована: RSS-агрегаторы (особенно Google News, when:2d) отдают
    одни и те же топ-статьи много циклов сбора подряд, каждый такой upsert
    двигает last_seen на "сейчас" независимо от возраста статьи. Настоящее
    время публикации -- raw.published (rss.py пишет его при первом сборе,
    _entry_time() из feed) -- фильтруем по нему, last_seen тут только широкий
    SQL-предфильтр, чтобы не сканировать всю таблицу."""
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    sql_prefilter = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    rows = con.execute(
        """SELECT title, topic_hint, author, url, raw FROM signals
           WHERE source='rss' AND last_seen >= ? ORDER BY last_seen DESC""",
        (sql_prefilter,),
    ).fetchall()
    con.close()
    cutoff_ts = time.time() - hours * 3600
    out = []
    for r in rows:
        try:
            raw = json.loads(r["raw"] or "{}")
        except (json.JSONDecodeError, TypeError):
            raw = {}
        published_ts = raw.get("published")
        if not published_ts or published_ts < cutoff_ts:
            continue
        domain = raw.get("domain") or ""
        if not domain and r["url"]:
            try:
                domain = urlparse(r["url"]).netloc.removeprefix("www.")
            except ValueError:
                domain = ""
        out.append({
            "title": r["title"] or "",
            "outlet": r["topic_hint"] or r["author"] or "",
            "domain": domain,
        })
    return out


def _call_claude(headlines: list[dict], verbose: bool = False) -> str | None:
    """claude -p headless, по образцу analyze/run_daily.sh:32-49 -- модель
    пишет свой ответ в файл (Write), тут же читаем и возвращаем его "text".
    None на падении/таймауте/отсутствии файла -- run() решает, что делать."""
    lines = [f"- [{h['outlet'] or h['domain'] or '?'}] {h['title']}" for h in headlines[:MAX_HEADLINES]]
    headlines_block = "\n".join(lines)

    prompt = f"""Ты составляешь короткую почасовую сводку новостного фона для финансового
образовательного сайта. Правило Voice SBF: коротко, лаконично, исчерпывающе.

ВХОД -- заголовки RSS за последний час (без полных текстов):
{headlines_block}

ПРАВИЛА (обязательны, без исключений):
- не длиннее 400 знаков, 2-3 предложения;
- только то, что произошло, и кого/чего это касается -- факт, не интерпретация;
- БЕЗ оценочных прилагательных ("резкий", "мощный", "тревожный", "исторический");
- БЕЗ прогнозов и будущего времени ("ожидается", "продолжит", "вырастет", "упадёт", "может");
- БЕЗ рекомендаций, уровней входа, "стоит", "рекомендуем";
- если ничего существенного нет -- одна короткая строка об этом, растягивать запрещено;
- только факты из списка выше, ничего от себя.

Запиши результат СТРОГО в виде JSON-файла {DRAFT_PATH} (Write) с единственным
полем "text" -- твоя сводка одной строкой. Верни в stdout только путь к файлу."""

    env = {**os.environ, "PATH": f"{Path.home()}/.local/bin:{os.environ.get('PATH', '')}"}
    try:
        DRAFT_PATH.parent.mkdir(parents=True, exist_ok=True)
        if DRAFT_PATH.exists():
            DRAFT_PATH.unlink()  # не читать чужой старый черновик, если claude -p упадёт до Write
        subprocess.run(
            [CLAUDE_BIN, "-p", prompt, "--allowedTools", "Write", "--output-format", "text"],
            timeout=CLAUDE_TIMEOUT_SEC, capture_output=True, text=True, check=False, env=env,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        if verbose:
            print(f"claude -p упал/не уложился в таймаут: {e}", file=sys.stderr)
        return None

    try:
        draft = json.loads(DRAFT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    text = draft.get("text")
    return text if isinstance(text, str) else None


def _load_previous() -> dict | None:
    try:
        return json.loads(OUT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write(payload: dict) -> None:
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run(verbose: bool = False) -> int:
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    headlines = _recent_rss()
    items_used = len(headlines)
    sources = sorted({h["domain"] for h in headlines if h["domain"]})

    if items_used == 0:
        _write({
            "updated": now_iso, "text": EMPTY_HOUR_TEXT_RU,
            "items_used": 0, "sources": [], "stale": False,
        })
        if verbose:
            print("digest: пустой час, канонический текст без вызова модели")
        return 0

    raw_text = _call_claude(headlines, verbose=verbose)
    validated = validate(raw_text) if raw_text is not None else None

    if validated is not None:
        _write({
            "updated": now_iso, "text": validated,
            "items_used": items_used, "sources": sources, "stale": False,
        })
        if verbose:
            print(f"digest: OK, {items_used} новостей, {len(sources)} изданий -> {validated!r}")
        return 0

    # Провал (валидация или claude -p) -- предыдущая сводка с stale=true,
    # НЕ трогаем её "updated" (панель показывает время ПОСЛЕДНЕГО успешного
    # обновления, не время неудачной попытки). Отклонённый текст -- в лог
    # целиком, по нему правится промпт (спека §8, требование явное).
    if raw_text is not None:
        REJECTED_LOG.parent.mkdir(parents=True, exist_ok=True)
        with REJECTED_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{now_iso}\t{raw_text!r}\n")
        if verbose:
            print(f"digest: ОТКЛОНЕНО валидатором: {raw_text!r}", file=sys.stderr)
    elif verbose:
        print("digest: claude -p не вернул текст (упал/таймаут)", file=sys.stderr)

    prev = _load_previous()
    if prev is not None:
        prev["stale"] = True
        _write(prev)
    else:
        _write({"updated": now_iso, "text": "", "items_used": 0, "sources": [], "stale": True})
    return 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    # run()==1 (провал валидации/claude -p, откат на предыдущую сводку) -- это
    # штатный, ожидаемый исход (см. docstring run()), не ошибка сервиса: не
    # дёргаем sys.exit(1), иначе systemd считал бы обычный "пустой" момент падением.
    run(verbose=args.verbose)


if __name__ == "__main__":
    main()
