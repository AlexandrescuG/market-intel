"""Логирование с защитой от утечки секретов.

Главное: глушим INFO-логи httpx/httpcore (они печатали полный URL Telegram с
токеном в монитор.log — это и есть та утечка). Плюс фильтр, который маскирует
любой bot<digits>:<token> на случай, если он всё же попадёт в строку лога.
"""
from __future__ import annotations

import logging
import re
import sys

from core.config import DATA_DIR

_TOKEN_RE = re.compile(r"bot\d{6,}:[A-Za-z0-9_\-]{20,}")


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _TOKEN_RE.sub("bot<REDACTED>", record.msg)
        return True


def setup(name: str = "monitor") -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(DATA_DIR / "monitor.log", encoding="utf-8"),
        ],
    )
    # httpx/httpcore печатают URL запроса на INFO → токен в логах. Глушим.
    for noisy in ("httpx", "httpcore", "hpack", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    log = logging.getLogger(name)
    redact = _RedactFilter()
    for h in logging.getLogger().handlers:
        h.addFilter(redact)
    return log
