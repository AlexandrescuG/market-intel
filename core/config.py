"""Конфиг: env, пути, пороги. Один источник правды для всех модулей."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
BRIEFS_DIR = DATA_DIR / "briefs"
REPORTS_DIR = DATA_DIR / "reports"
PROFILE_DIR = DATA_DIR / "browser_profile"
DB_PATH = DATA_DIR / "signals.db"
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
ALERT_MIN_RSS_RELEVANCE = float(os.getenv("ALERT_MIN_RSS_RELEVANCE", "0.60"))

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

# ── Reddit: сабреддиты трейдеров/инвесторов ─────────────────────────────────────
REDDIT_SUBS = [
    "wallstreetbets", "stocks", "investing", "StockMarket", "options",
    "economics", "Economics", "finance", "SecurityAnalysis", "Daytrading",
    "cryptocurrency", "Bitcoin", "geopolitics", "wallstreetbetsELITE",
]
REDDIT_SORTS = ["hot", "rising"]   # rising ловит то, что ВЗЛЕТАЕТ прямо сейчас
REDDIT_LIMIT = 25                  # постов на сабреддит/сортировку

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
}
RSS_TREND_WINDOW_HOURS = int(os.getenv("RSS_TREND_WINDOW_HOURS", "24"))
