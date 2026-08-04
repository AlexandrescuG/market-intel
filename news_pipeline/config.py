"""Конфиг news_pipeline из .env. Единый источник правды."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ── Telethon (клиентский аккаунт «воровки») ───────────────────────────────────
TG_API_ID   = int(os.getenv("TELNEWS_API_ID", "0"))
TG_API_HASH = os.getenv("TELNEWS_API_HASH", "")
TG_SESSION  = os.getenv("TELNEWS_SESSION", str(BASE_DIR / "data" / "nevorovka_session"))

# ── Постинг ────────────────────────────────────────────────────────────────────
TARGET_CHANNEL  = os.getenv("TELNEWS_TARGET", "rostoklepestop")
POST_INTERVAL   = int(os.getenv("POST_INTERVAL_SEC", "45"))    # сек между постами

# ── Дедуп ─────────────────────────────────────────────────────────────────────
DEDUP_WINDOW_H  = int(os.getenv("DEDUP_WINDOW_HOURS", "6"))    # окно кросс-источника
PRICE_COOLDOWN  = int(os.getenv("PRICE_COOLDOWN_MIN", "60"))   # мин между ценовыми алертами

# ── RSS polling ────────────────────────────────────────────────────────────────
RSS_POLL_SEC    = int(os.getenv("RSS_POLL_SEC", "900"))         # каждые 15 мин

# ── Логирование ────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("NEWSPIPE_LOG_LEVEL", "INFO")
