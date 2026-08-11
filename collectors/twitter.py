"""Twitter/X-коллектор. Рефактор твоего monitor.py под единый конвейер.

Сохранено: cloakbrowser-логин, парсинг статей, скриншот, алерт в Telegram.
Изменено:
  - пишет в core.db (единые сигналы), а не в свою таблицу
  - узкие запросы из config.TWITTER_QUERIES вместо одного широкого OR
  - фильтр по econ_relevance (мусор уровня «серьга подмигнула» не проходит)
  - алерт по importance, а не по сырым лайкам
  - лог не палит токен (см. core.logging_setup)
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import cloakbrowser

from core import db, scoring
from core.config import (ALERT_MIN_ENGAGEMENT, ALERT_MIN_GROWTH,
                         ALERT_MIN_IMPORTANCE, STORE_MIN_ECON_RELEVANCE,
                         TRANSLATE, TWITTER_PASSWORD, TWITTER_QUERIES,
                         TWITTER_USERNAME)
from core.telegram import send_photo, send_text

log = logging.getLogger("twitter")
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)


# ─── перевод (как у тебя) ───────────────────────────────────────────────────────
def _is_russian(t: str) -> bool:
    return sum(1 for c in t if "Ѐ" <= c <= "ӿ") / max(len(t), 1) > 0.25


async def _translate(text: str) -> str | None:
    if not TRANSLATE or not text or _is_russian(text):
        return None
    try:
        from deep_translator import GoogleTranslator
        loop = asyncio.get_event_loop()
        tr = await loop.run_in_executor(
            _pool, lambda: GoogleTranslator(source="auto", target="ru").translate(text[:1500]))
        return tr if tr and tr.strip() != text.strip() else None
    except Exception as e:
        log.debug("translate failed: %s", e)
        return None


# ─── парсинг (перенесён из monitor.py, без изменений логики) ─────────────────────
def _parse_count(raw: str) -> int:
    s = raw.strip().replace(",", "").replace(" ", "").replace("\xa0", "")
    m = re.match(r"^([\d.]+)([KkMmBb]?)$", s)
    if not m:
        return 0
    val, suf = float(m.group(1)), m.group(2).upper()
    return int(val * {"K": 1e3, "M": 1e6, "B": 1e9}.get(suf, 1))


async def _btn_count(article, testid: str) -> int:
    btn = await article.query_selector(f'button[data-testid="{testid}"]')
    if not btn:
        return 0
    aria = await btn.get_attribute("aria-label") or ""
    m = re.search(r"([\d,]+(?:\.\d+)?[KkMm]?)", aria)
    if m:
        return _parse_count(m.group(1).replace(",", ""))
    span = await btn.query_selector('span[data-testid="app-text-transition-container"]')
    if span:
        return _parse_count((await span.inner_text()).strip())
    return 0


_MAX_AGE_HOURS = 36  # принимаем твиты не старше 36 часов


async def _extract(page) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_MAX_AGE_HOURS)
    out = []
    for article in await page.query_selector_all('article[data-testid="tweet"]'):
        try:
            tid = turl = pub_dt = None
            for link in await article.query_selector_all('a[href*="/status/"]'):
                href = await link.get_attribute("href") or ""
                m = re.search(r"/status/(\d+)", href)
                if m:
                    tid = m.group(1)
                    turl = f"https://x.com{href}" if href.startswith("/") else href
                    time_el = await link.query_selector("time")
                    if time_el:
                        dt_attr = await time_el.get_attribute("datetime") or ""
                        try:
                            pub_dt = datetime.fromisoformat(dt_attr.replace("Z", "+00:00"))
                        except ValueError:
                            pass
                        break
            if not tid:
                continue
            # Отбрасываем старые твиты
            if pub_dt and pub_dt < cutoff:
                log.debug("skip old tweet %s published %s", tid, pub_dt.date())
                continue
            author = ""
            ub = await article.query_selector('[data-testid="User-Name"]')
            if ub:
                for a in await ub.query_selector_all("a"):
                    h = (await a.get_attribute("href") or "").strip("/").split("/")[-1]
                    if h and "/" not in h:
                        author = h
                        break
            text = ""
            te = await article.query_selector('[data-testid="tweetText"]')
            if te:
                text = (await te.inner_text()).strip()
            out.append({
                "tweet_id": tid, "author": author, "text": text, "url": turl,
                "pub_date": pub_dt.isoformat() if pub_dt else None,
                "likes": await _btn_count(article, "like"),
                "retweets": await _btn_count(article, "retweet"),
                "replies": await _btn_count(article, "reply"),
            })
        except Exception as e:
            log.debug("skip article: %s", e)
    return out


# ─── логин (перенесён) ──────────────────────────────────────────────────────────
async def _ensure_login(page) -> bool:
    await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=40_000)
    await asyncio.sleep(3)
    if "login" not in page.url and "i/flow" not in page.url:
        return True
    if not TWITTER_USERNAME or not TWITTER_PASSWORD:
        log.error("not logged in and no credentials")
        await send_text("⚠️ Twitter/X: сессия разлогинена, автологин не настроен (нет TWITTER_USERNAME/PASSWORD) — сбор твитов не идёт")
        return False
    try:
        await page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded", timeout=40_000)
        await asyncio.sleep(2)
        inp = await page.wait_for_selector('input[autocomplete="username"]', timeout=12_000)
        await inp.fill(TWITTER_USERNAME); await asyncio.sleep(0.5)
        await page.keyboard.press("Enter"); await asyncio.sleep(2.5)
        try:
            await page.wait_for_selector('input[data-testid="ocfEnterTextTextInput"]', timeout=4_000)
            log.warning("verification challenge — заполни вручную, жду 90с"); await asyncio.sleep(90)
        except Exception:
            pass
        pwd = await page.wait_for_selector('input[type="password"]', timeout=12_000)
        await pwd.fill(TWITTER_PASSWORD); await asyncio.sleep(0.5)
        await page.keyboard.press("Enter"); await asyncio.sleep(6)
        if "home" in page.url:
            return True
        log.info("жду 60с на ручной 2FA…"); await asyncio.sleep(60)
        ok = "home" in page.url
        if not ok:
            await send_text("⚠️ Twitter/X: автологин не прошёл (2FA/challenge?) — сбор твитов не идёт")
        return ok
    except Exception as e:
        log.error("login error: %s", e)
        await send_text(f"⚠️ Twitter/X: ошибка логина — {e}")
        return False


async def _screenshot(ctx, url: str) -> bytes | None:
    page = await ctx.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=35_000)
        await asyncio.sleep(3)
        art = await page.wait_for_selector('article[data-testid="tweet"]', timeout=15_000)
        await art.scroll_into_view_if_needed(); await asyncio.sleep(1.5)
        return await art.screenshot(type="png")
    except Exception as e:
        log.warning("screenshot %s: %s", url, e)
        return None
    finally:
        await page.close()


def _fmt(n: int) -> str:
    return f"{n/1e6:.1f}M" if n >= 1e6 else f"{n/1e3:.1f}K" if n >= 1e3 else str(n)


async def _caption(tw: dict, dim: str) -> str:
    tr = await _translate(tw["text"][:200])
    tline = f"\n\n🇷🇺 {tr.strip()}" if tr else ""
    icon = {"economy": "💰", "geopolitics": "🌍", "crowd": "🔥"}.get(dim, "📊")
    return (f"{icon} <b>@{tw['author']}</b>{tline}\n\n"
            f"❤️ {_fmt(tw['likes'])}   🔁 {_fmt(tw['retweets'])}\n{tw['url']}")


async def _scan_query(page, dimension: str, query: str) -> list[dict]:
    # since: вчера — не брать твиты старше вчерашнего дня
    since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    dated_query = f"{query} since:{since}"
    # f=live — вкладка "Latest", не "Top" (Top показывает хиты за всё время)
    url = f"https://x.com/search?q={quote_plus(dated_query)}&src=typed_query&f=live"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=40_000)
    except Exception as e:
        log.warning("nav timeout (non-fatal): %s", e)
    await asyncio.sleep(4)
    for _ in range(4):
        await page.keyboard.press("End"); await asyncio.sleep(1.5)
    tweets = await _extract(page)
    for t in tweets:
        t["dimension_hint"] = dimension
        t["query"] = query
    return tweets


_consecutive_empty_cycles = 0


async def collect_with_context(ctx) -> int:
    """Один прогон по всем запросам. Пишет сигналы, шлёт алерты. Возвращает #алертов."""
    db.init_db()
    page = await ctx.new_page()
    alerts = 0
    total_tweets = 0
    try:
        if not await _ensure_login(page):
            return 0
        pending = []
        for dimension, queries in TWITTER_QUERIES.items():
            for q in queries:
                tweets = await _scan_query(page, dimension, q)
                total_tweets += len(tweets)
                log.info("twitter [%s] %d tweets", dimension, len(tweets))
                for tw in tweets:
                    eng = tw["likes"] + tw["retweets"]
                    res = db.upsert(
                        source="twitter", source_id=tw["tweet_id"],
                        author=tw["author"], text=tw["text"], url=tw["url"],
                        engagement=eng, replies=tw["replies"],
                        topic_hint=tw["query"], lang="",
                    )
                    # отсев мусора по econ_relevance
                    if res["econ_relevance"] < STORE_MIN_ECON_RELEVANCE:
                        continue
                    # алерт для контента: важно И (ново ИЛИ заметно подросло)
                    if res["importance"] >= ALERT_MIN_IMPORTANCE and eng >= ALERT_MIN_ENGAGEMENT \
                       and (res["is_new"] or res["growth"] >= ALERT_MIN_GROWTH):
                        pending.append((tw, res))
                        db.mark_alerted(res["uid"], eng)

        # дедуп по tweet_id, топ по importance
        seen = set(); uniq = []
        for tw, res in sorted(pending, key=lambda x: x[1]["importance"], reverse=True):
            if tw["tweet_id"] in seen:
                continue
            seen.add(tw["tweet_id"]); uniq.append((tw, res))

        for tw, res in uniq[:12]:  # потолок, чтобы не залить ленту
            log.info("ALERT @%s imp=%.2f eng=%d", tw["author"], res["importance"],
                     tw["likes"] + tw["retweets"])
            cap = await _caption(tw, res["dimension"])
            photo = await _screenshot(ctx, tw["url"])
            await (send_photo(photo, cap) if photo else send_text(cap))
            await asyncio.sleep(1)
            alerts += 1
        if not uniq:
            log.info("twitter: нет новых важных тредов")

        global _consecutive_empty_cycles
        if total_tweets == 0:
            _consecutive_empty_cycles += 1
            log.warning("twitter: 0 постов за весь цикл (подряд: %d)", _consecutive_empty_cycles)
            if _consecutive_empty_cycles == 2:
                await send_text(
                    "⚠️ Twitter/X: 0 постов два цикла подряд — похоже на разлогин "
                    "или блокировку, а не на тишину. Проверь сессию (data/browser_profile)."
                )
        else:
            _consecutive_empty_cycles = 0
    finally:
        await page.close()
    return alerts


if __name__ == "__main__":
    from core.config import HEADLESS, PROFILE_DIR
    from core.logging_setup import setup
    setup("twitter")

    async def _main():
        ctx = await cloakbrowser.launch_persistent_context_async(
            user_data_dir=str(PROFILE_DIR), headless=HEADLESS,
            locale="en-US", timezone="Europe/Moscow",
            viewport={"width": 1280, "height": 900})
        try:
            await collect_with_context(ctx)
        finally:
            await ctx.close()
    asyncio.run(_main())
