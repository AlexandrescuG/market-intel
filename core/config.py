"""Конфиг: env, пути, пороги. Один источник правды для всех модулей."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger("config")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
BRIEFS_DIR = DATA_DIR / "briefs"
REPORTS_DIR = DATA_DIR / "reports"
PROFILE_DIR = DATA_DIR / "browser_profile"
DB_PATH = DATA_DIR / "signals.db"

# PROFILE_DIR — не обычный каталог данных: в нём живёт залогиненная сессия
# X, которую нельзя восстановить автоматически. Если его нет — это авария
# (потеря сессии), а не первый запуск, поэтому громко предупреждаем, а не
# создаём тихо пустую замену (см. ЗАДАЧА_починить_ленту_X.md, 06.08.2026).
if not PROFILE_DIR.exists():
    log.warning("PROFILE_DIR отсутствует (%s) — сессия X потеряна, коллектор "
                "будет разлогинен пока профиль не восстановят вручную", PROFILE_DIR)

for d in (DATA_DIR, BRIEFS_DIR, REPORTS_DIR, PROFILE_DIR):
    d.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")

# ── Twitter/X ──────────────────────────────────────────────────────────────────
TWITTER_USERNAME = os.getenv("TWITTER_USERNAME", "")
TWITTER_PASSWORD = os.getenv("TWITTER_PASSWORD", "")

# ── Telegram ───────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")            # лента для контента (алерты)
TELEGRAM_REPORT_CHAT_ID = os.getenv("TELEGRAM_REPORT_CHAT_ID", "")  # куда слать дайджест (по умолч. = CHAT_ID)

# Публичный канал @SBFEconomics. 01.09.2026: алерты о выбросах публикуются
# сюда постом, а подписчикам бот их форвардит из канала — так у поста есть
# постоянная ссылка, и подписчик видит источник, а не пересказ.
#
# ⚠️ 01.09: getChatAdministrators по этому каналу обоим ботам отвечает 400 —
# в канал они не добавлены, значит постить и форвардить пока не могут.
# @Markgandon_bot нужен админом с правом «Публиковать сообщения»,
# @SBFAcademy_bot — участником (иначе forward_message не пройдёт). До этого
# post_sync вернёт None, channel_msg_id останется NULL, и бот отправит
# подписчику текст напрямую — доставка не ломается, просто нет поста в канале.
SBFECONOMICS_CHANNEL_ID = os.getenv("SBFECONOMICS_CHANNEL_ID", "-1002678764152")

# @gdenigi_bot -- WP4.7 SPEC_alpha_engine_wp4_continuous_cycle.md, ОТДЕЛЬНЫЙ
# бот/канал от TELEGRAM_* выше (прогнозы агента при BSS>0, не операционные
# алерты). Пусто, пока Георгий не создаст бота через @BotFather.
GDENIGI_BOT_TOKEN = os.getenv("GDENIGI_BOT_TOKEN", "")
GDENIGI_CHAT_ID = os.getenv("GDENIGI_CHAT_ID", "")

# ── Поведение ──────────────────────────────────────────────────────────────────
HEADLESS = os.getenv("HEADLESS", "false").lower() in ("1", "true", "yes")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_MINUTES", "20")) * 60
TRANSLATE = os.getenv("TRANSLATE", "true").lower() not in ("0", "false", "no")

# ── Пороги ─────────────────────────────────────────────────────────────────────
# Алерт в Telegram (real-time, для контента) — строже, чтобы не спамить.
ALERT_MIN_IMPORTANCE = float(os.getenv("ALERT_MIN_IMPORTANCE", "0.55"))
ALERT_MIN_ENGAGEMENT = int(os.getenv("ALERT_MIN_ENGAGEMENT", "2000"))
ALERT_MIN_GROWTH = int(os.getenv("ALERT_MIN_GROWTH", "1500"))
# Сохранение в БД (для дайджеста) — мягче: всё что хоть как-то про экономику.
STORE_MIN_ECON_RELEVANCE = float(os.getenv("STORE_MIN_ECON_RELEVANCE", "0.25"))

# ── Twitter: запросы по топикам (узкие и точные, без мусорных OR) ───────────────
TWITTER_QUERIES = {
    "economy": [
        '(CPI OR inflation OR "rate cut" OR "rate hike" OR FOMC OR "Federal Reserve") min_faves:500',
        '(recession OR "bond yield" OR "S&P 500" OR nasdaq OR "market crash") min_faves:500',
        '(инфляция OR "ключевая ставка" OR ФРС OR рецессия OR девальвация OR тенге) min_faves:200',
        '(bitcoin OR crypto OR "gold price" OR OPEC OR "crude oil" OR brent) min_faves:500',
    ],
    "geopolitics": [
        '(sanctions OR tariff OR "trade war" OR embargo) min_faves:500',
        '(Ukraine OR Israel OR Iran OR Taiwan OR "North Korea") (war OR strike OR missile OR ceasefire) min_faves:1000',
        '(санкции OR пошлины OR война OR перемирие OR эскалация) min_faves:300',
        '(NATO OR Kremlin OR Pentagon OR BRICS OR "G20") min_faves:1000',
    ],
}

# ── Reddit (ОТКЛЮЧЁН: заблокировали скрапинг, заменён на StockTwits) ─────────────
REDDIT_SUBS = ["wallstreetbets", "stocks", "investing", "economics"]
REDDIT_SORTS = ["hot", "rising"]
REDDIT_LIMIT = 25

# ── StockTwits: базовый watchlist (∪ кэштеги из свежих сигналов) ─────────────────
STOCKTWITS_WATCHLIST = [
    "SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "AMD", "META", "AMZN",
    "BTC.X", "ETH.X", "GLD", "USO", "DXY", "SPX", "VIX",
]

# ── RSS: мировые + региональные + рыночные ленты ────────────────────────────────
RSS_FEEDS = {
    # world / markets (EN)
    "BBC World":      "https://feeds.bbci.co.uk/news/world/rss.xml",
    "BBC Business":   "https://feeds.bbci.co.uk/news/business/rss.xml",
    "Guardian World": "https://www.theguardian.com/world/rss",
    "Al Jazeera":     "https://www.aljazeera.com/xml/rss/all.xml",
    "MarketWatch":    "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "CNBC Finance":   "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
    "Yahoo Finance":  "https://finance.yahoo.com/news/rssindex",
    # RU / CIS
    "RBC":            "https://rssexport.rbc.ru/rbcnews/news/30/full.rss",
    "Interfax":       "https://www.interfax.ru/rss.asp",
    # markets EN econ
    "Investing.com":  "https://www.investing.com/rss/news_25.rss",
    # форекс-специализированные (проверены curl -- отдают ленту)
    "FXStreet":       "https://www.fxstreet.com/rss/news",
    "ForexLive":      "https://www.forexlive.com/feed/news",
    # крипто-специализированные
    "CoinDesk":       "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "CoinTelegraph":  "https://cointelegraph.com/rss",
    # центробанки напрямую (официальные пресс-релизы, без интерпретации)
    "Fed press":      "https://www.federalreserve.gov/feeds/press_all.xml",
    "ECB press":      "https://www.ecb.europa.eu/rss/press.html",
    "BoE press":      "https://www.bankofengland.co.uk/rss/news",
}

# Google News "поиск как RSS-лента" -- агрегирует тысячи изданий по ключевому
# слову вместо одного конкретного сайта (см. rss.py: entry.source.title даёт
# РЕАЛЬНОГО публикатора каждой статьи, не "Google News"). when:2d -- не тащить
# старые вечнозелёные SEO-статьи, коллектор и так опрашивает раз в 20 мин.
def _google_news(query: str) -> str:
    from urllib.parse import quote_plus
    return (f"https://news.google.com/rss/search?q={quote_plus(query)}+when:2d"
            f"&hl=en-US&gl=US&ceid=US:en")

GOOGLE_NEWS_TOPICS = {
    "Google News: EURUSD":  "EURUSD",
    "Google News: GBPUSD":  "GBPUSD",
    "Google News: USDJPY":  "USDJPY",
    "Google News: Gold":    "gold price",
    "Google News: Oil":     "WTI crude oil",
    "Google News: Bitcoin": "Bitcoin",
    "Google News: Fed":     "Federal Reserve",
    "Google News: ECB":     "ECB interest rate",
    # SPEC_site_fixes_2026-07-29 §6: Bloomberg/Reuters закрыли публичные RSS --
    # site:-запрос к Google News даёт заголовок+ссылку (не полный текст, но
    # для панели этого достаточно), entry.source.title в rss.py резолвит
    # реального публикатора вместо "Google News: ...".
    "Google News: Reuters":   "site:reuters.com",
    "Google News: Bloomberg": "site:bloomberg.com",
    "Google News: AP":        "site:apnews.com",
    "Google News: WSJ":       "site:wsj.com",
}
RSS_FEEDS.update({name: _google_news(q) for name, q in GOOGLE_NEWS_TOPICS.items()})


# ── Запросы по инструментам витрины (09.09.2026) ─────────────────────────────
#
# 🔴 Запросов выше было восемь: EURUSD, GBPUSD, USDJPY, золото, нефть, биткоин,
# ФРС, ЕЦБ. Ровно эти инструменты и стояли в топе доски обсуждаемости, а
# остальные семьсот выглядели как «о них не пишут». Писали — мы не спрашивали.
# Общие ленты (BBC World, Guardian, Al Jazeera) закрывают макро и политику, но
# про DAX, какао или Nike в них попадается одна заметка в неделю.
#
# ПОЧЕМУ ПОРЦИЯМИ. Запросов около шестидесяти, и тянуть их все каждый цикл —
# это шестьдесят обращений к Google News раз в двадцать минут. Ходим по кругу
# порциями: полный оборот занимает несколько циклов, то есть меньше часа. Для
# счётчика упоминаний за сутки этого достаточно с запасом, а нагрузка остаётся
# на уровне сегодняшней.
#
# 🔴 Смещение считается ОТ ЧАСОВ, а не от счётчика в памяти процесса.
#
# Юнит sbf-collectors запускается таймером каждые 20 минут и каждый раз это
# НОВЫЙ процесс (Type=oneshot, run.sh --once). Счётчик в переменной модуля
# обнулялся бы при каждом запуске, круг начинался бы заново, и запросы после
# двенадцатого не опрашивались бы никогда. Снаружи это выглядело бы как
# работающая ротация: логи показывают разные ленты в пределах одного прогона.
#
# Время идёт независимо от перезапусков, поэтому окно берём от него.
NEWS_QUERIES_PER_CYCLE = int(os.getenv("NEWS_QUERIES_PER_CYCLE", "12"))
NEWS_ROTATION_STEP_SEC = int(os.getenv("NEWS_ROTATION_STEP_SEC", "1200"))  # 20 мин


def _instrument_news_queries() -> dict:
    """{имя ленты: запрос} — плоский список из data/news_queries.json."""
    path = Path(__file__).resolve().parent.parent / "data" / "news_queries.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for group, items in raw.items():
        if group.startswith("_") or not isinstance(items, dict):
            continue
        for symbol, query in items.items():
            out[f"Google News: {symbol}"] = query
    return out


INSTRUMENT_NEWS_QUERIES = _instrument_news_queries()


def rotating_news_feeds(cycle: int | None = None) -> dict:
    """Порция инструментальных запросов для этого прогона сборщика.

    cycle=None (обычный случай) — окно берётся от текущего времени, поэтому
    ротация не сбрасывается при перезапуске процесса. Явный номер передаётся
    только из тестов, где нужен предсказуемый набор.
    """
    names = sorted(INSTRUMENT_NEWS_QUERIES)
    if not names:
        return {}
    n = max(1, NEWS_QUERIES_PER_CYCLE)
    if cycle is None:
        cycle = int(time.time() // max(60, NEWS_ROTATION_STEP_SEC))
    start = (cycle * n) % len(names)
    picked = [names[(start + i) % len(names)] for i in range(min(n, len(names)))]
    out = {name: _google_news(INSTRUMENT_NEWS_QUERIES[name]) for name in picked}
    out.update(_ticker_feeds(picked))
    return out


# ── Тикерные ленты Yahoo ────────────────────────────────────────────────────
#
# 🔴 ЗАЧЕМ, если поиск Google News по инструменту уже есть.
#
# Замер 10.09.2026 по ленте #APPLE: 22 из 30 новостей пришли ссылками
# news.google.com. У такой ссылки фотографии не будет НИКОГДА — адрес статьи
# в ней не лежит (внутри base64 идентификатор, а не URL), страница рисуется
# скриптом и og-тегов не содержит. То есть новостная сетка по популярной
# акции была обречена состоять из логотипов.
#
# Тикерная лента Yahoo отдаёт то же самое прямыми ссылками на издания:
# проверено на AAPL — 20 записей, из шести проверенных превью нашлось у пяти.
# Клик при этом ведёт на статью, а не через редирект.
#
# Google-поиск не убираем: он ловит то, чего у Yahoo нет (русскоязычные
# издания, нишевые сайты). Две ленты на инструмент дают дубли, но дубли
# склеиваются на выдаче, и из копий выбирается та, что с фотографией и
# прямой ссылкой (serve.py::_dedupe_feed).
_YAHOO_TICKER_FEED = ("https://feeds.finance.yahoo.com/rss/2.0/headline"
                      "?s={t}&region=US&lang=en-US")
_TICKER_RE = re.compile(r"^[A-Z][A-Z.\-]{0,6}$")


def _catalog_tickers() -> dict:
    """{имя инструмента в наших запросах: биржевой тикер}.

    У акций в каталоге поле name и есть тикер (#APPLE → AAPL). Берём только
    их: для сырья и валют тикерной ленты у Yahoo в этом виде нет, а
    подставлять туда GC=F значит получать ленту не про то.
    """
    try:
        raw = json.loads((BASE_DIR / "web" / "data" / "broker_catalog.json")
                         .read_text(encoding="utf-8"))
    except Exception:
        return {}
    items = raw.get("items", raw) if isinstance(raw, dict) else raw
    out = {}
    for it in items:
        if it.get("category") != "stock":
            continue
        t = (it.get("name") or "").strip().upper()
        if _TICKER_RE.match(t):
            out[it["symbol"]] = t
    return out


def _ticker_feeds(picked: list[str]) -> dict:
    """Ключи запросов выглядят как «Google News: #APPLE» — символ после
    двоеточия. Без этого разбора совпадений с каталогом не будет ни одного,
    и функция молча вернёт пустоту (проверено: 0 из 12 в первой версии)."""
    тикеры = _catalog_tickers()
    out = {}
    for name in picked:
        символ = name.split(":", 1)[-1].strip() if ":" in name else name.strip()
        t = тикеры.get(символ)
        if t:
            out[f"Yahoo {t}"] = _YAHOO_TICKER_FEED.format(t=t)
    return out
RSS_TREND_WINDOW_HOURS = int(os.getenv("RSS_TREND_WINDOW_HOURS", "24"))

# ── SBFCRM — новые регистрации платформы как лиды (27.08.2026) ───────────────
# Пароль в .env кладёт владелец (tools/crm_setup.sh) — в репозитории его нет.
# Без него core/crm_leads.is_configured() вернёт False и интеграция молчит.
SBFCRM_URL         = os.getenv("SBFCRM_URL", "https://crm.sbf.md")
SBFCRM_EMAIL       = os.getenv("SBFCRM_EMAIL", "")
SBFCRM_PASSWORD    = os.getenv("SBFCRM_PASSWORD", "")
SBFCRM_ASSIGNEE_ID = os.getenv("SBFCRM_ASSIGNEE_ID", "")
