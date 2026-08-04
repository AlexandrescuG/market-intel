"""
Обработка очереди raw_items → posts → постинг через Telethon.


Алгоритм:
  1. Берём непроверенные raw_items (не в posts) по ts ASC.
  2. Роутер: сейчас только 'free_text'.
  3. Форматтер → текст поста.
  4. Дедуп через content_hash (окно DEDUP_WINDOW_H).
  5. Запись в posts(queued).
  6. Flush очереди: posts WHERE status='queued' ORDER BY created_ts ASC,
     отправка с паузой POST_INTERVAL сек, обновление status='posted'.
"""
from __future__ import annotations

import asyncio
import logging
import time

try:
    from deep_translator import GoogleTranslator
    _translator = GoogleTranslator(source="auto", target="ru")
    _TRANSLATE = True
except Exception:
    _TRANSLATE = False

from news_pipeline import config
from news_pipeline.db import get_conn
from news_pipeline.formatter import (
    content_hash,
    fmt_free_text,
    normalize_title,
)

log = logging.getLogger("newspipe.poster")

# Заголовки содержащие эти подстроки → skipped (личные финансы / реклама)
_SKIP_TITLE = [
    "credit card", "кредитная карт", "mortgage", "ипотека",
    "best car insurance", "auto insurance", "personal loan",
    "savings account", "checking account", "refinance",
    "how to merge finances", "wedding", "свадьб",
    "best travel rewards", "cash back", "sign-up bonus",
    # обзоры продуктов
    "cards review", "card review", "cards 2.0 review",
    "review: are they", "is it worth", "which is better",
    # советы личных финансов
    "how to budget", "how to save", "how to invest for beginners",
    "best way to pay off",
]


# ── Роутер (v1: только free_text) ────────────────────────────────────────────

def _route(item: dict) -> str:
    return "free_text"


def _translate(title: str, lang: str) -> str:
    if not _TRANSLATE or lang == "ru" or lang == "ro":
        return title
    try:
        return _translator.translate(title) or title
    except Exception:
        return title


def _should_skip_title(title: str) -> bool:
    tl = title.lower()
    return any(s in tl for s in _SKIP_TITLE)


# ── Дедуп ────────────────────────────────────────────────────────────────────

def _is_dup(conn, chash: str) -> bool:
    cutoff = int(time.time()) - config.DEDUP_WINDOW_H * 3600
    row = conn.execute(
        "SELECT 1 FROM posts WHERE content_hash=? AND created_ts>=?",
        (chash, cutoff),
    ).fetchone()
    return row is not None


# ── Группировка ───────────────────────────────────────────────────────────────
GROUP_MIN = 3    # минимум items для группировки в одно сообщение
GROUP_MAX = 8    # максимум строк в групповом посте


def _fmt_grouped(items: list[dict], source: dict) -> str:
    """
    Несколько заголовков из одного источника → один пост:
    ❗️🇬🇧#тег

    • Заголовок 1 (url)
    • Заголовок 2 (url)
    """
    from news_pipeline.formatter import importance_emoji, detect_flag

    first = items[0]
    cat = source["category"]
    imp = importance_emoji(cat, first["title"])
    flag = detect_flag(first["url"], first["title"])
    tags = source["default_tags"]
    header = f"{imp}{flag}{tags}".strip()

    lines = [header, ""]
    for it in items[:GROUP_MAX]:
        t = it["_translated_title"]
        url = it["url"]
        lbl = url.split("/")[2].replace("www.", "").split(".")[0] if url else source["ref"]
        if url:
            lines.append(f"• {t} ({url})")
        else:
            lines.append(f"• {t}")
    return "\n".join(lines)


# ── Конвертация raw_items → posts ─────────────────────────────────────────────

def process_raw() -> int:
    """Берёт новые raw_items и кладёт в очередь posts. Возвращает кол-во добавленных."""
    added = 0
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT r.id, r.source_id, r.ext_id, r.ts, r.title, r.body,
                   r.url, r.fetched_at,
                   s.category, s.default_tags, s.ref as source_ref, s.lang as src_lang
            FROM raw_items r
            JOIN sources s ON s.id = r.source_id
            WHERE NOT EXISTS (
                SELECT 1 FROM posts p
                WHERE p.source_id = r.source_id
                  AND p.url = r.url
                  AND p.url != ''
            )
            ORDER BY r.source_id, r.ts ASC
            LIMIT 300
        """).fetchall()

        # группируем по source_id
        by_source: dict[int, list[dict]] = {}
        for row in rows:
            d = dict(row)
            by_source.setdefault(d["source_id"], []).append(d)

        for source_id, items in by_source.items():
            first = items[0]
            source = {
                "id": source_id,
                "ref": first["source_ref"],
                "category": first["category"],
                "default_tags": first["default_tags"],
                "lang": first["src_lang"],
            }

            # переводим заголовки и фильтруем мусор
            valid = []
            for item in items:
                title = _translate(item["title"], item["src_lang"])
                if _should_skip_title(title):
                    continue
                item["_translated_title"] = title
                valid.append(item)

            if not valid:
                continue

            if len(valid) >= GROUP_MIN:
                # группируем в одно сообщение
                chash = content_hash(
                    f"group:{source_id}:" + "|".join(it["ext_id"] for it in valid[:GROUP_MAX])
                )
                if _is_dup(conn, chash):
                    continue
                text = _fmt_grouped(valid, source)
                conn.execute(
                    "INSERT OR IGNORE INTO posts"
                    "(type, text, source_id, url, content_hash, created_ts, status)"
                    "VALUES (?,?,?,?,?,?,?)",
                    ("free_text", text, source_id, valid[0]["url"],
                     chash, int(time.time()), "queued"),
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    added += 1
                    # помечаем все items как обработанные через фиктивные skipped посты
                    for it in valid[1:]:
                        skip_hash = "skip:" + content_hash(it["url"] or it["title"])
                        conn.execute(
                            "INSERT OR IGNORE INTO posts"
                            "(type, text, source_id, url, content_hash, created_ts, status)"
                            "VALUES (?,?,?,?,?,?,?)",
                            ("free_text", "", source_id, it["url"],
                             skip_hash, int(time.time()), "skipped"),
                        )
            else:
                # по одному
                for item in valid:
                    title = item["_translated_title"]
                    text = fmt_free_text(
                        title=title,
                        url=item["url"],
                        source=source,
                        category=item["category"],
                    )
                    if text is None:
                        conn.execute(
                            "INSERT OR IGNORE INTO posts"
                            "(type, text, source_id, url, content_hash, created_ts, status)"
                            "VALUES (?,?,?,?,?,?,?)",
                            ("free_text", "", source_id, item["url"],
                             "skip:" + content_hash(item["url"] or item["title"]),
                             int(time.time()), "skipped"),
                        )
                        continue
                    chash = content_hash(normalize_title(title))
                    if _is_dup(conn, chash):
                        continue
                    conn.execute(
                        "INSERT OR IGNORE INTO posts"
                        "(type, text, source_id, url, content_hash, created_ts, status)"
                        "VALUES (?,?,?,?,?,?,?)",
                        ("free_text", text, source_id, item["url"],
                         chash, int(time.time()), "queued"),
                    )
                    if conn.execute("SELECT changes()").fetchone()[0]:
                        added += 1

        conn.commit()
    log.info("process_raw: +%d queued", added)
    return added


# ── Флаш очереди через Telethon ───────────────────────────────────────────────

async def flush_queue(client) -> int:
    target = config.TARGET_CHANNEL
    posted = 0
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, text FROM posts WHERE status='queued' ORDER BY created_ts ASC"
        ).fetchall()

    for row in rows:
        post_id, text = row["id"], row["text"]
        if not text.strip():
            with get_conn() as conn:
                conn.execute(
                    "UPDATE posts SET status='skipped' WHERE id=?", (post_id,)
                )
                conn.commit()
            continue
        try:
            await client.send_message(target, text, parse_mode="md", link_preview=False)
            with get_conn() as conn:
                conn.execute(
                    "UPDATE posts SET status='posted', posted_ts=? WHERE id=?",
                    (int(time.time()), post_id),
                )
                conn.commit()
            posted += 1
            log.info("✅ posted id=%d to %s", post_id, target)
            await asyncio.sleep(config.POST_INTERVAL)
        except Exception as e:
            log.error("send_message failed id=%d: %s", post_id, e)
            await asyncio.sleep(5)

    return posted
