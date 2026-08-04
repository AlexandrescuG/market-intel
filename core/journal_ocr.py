"""
journal_ocr.py — OCR-пайплайн: скриншот → список сделок.

Поддерживает MT4/MT5 History and Terminal screenshots.
Возвращает список dict-сделок, готовых для add_trade().
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


def _preprocess(img):
    """Контраст и grayscale для лучшего OCR."""
    from PIL import Image, ImageFilter, ImageEnhance

    img = img.convert("L")                          # grayscale
    img = img.resize(
        (img.width * 2, img.height * 2), Image.LANCZOS  # upscale 2×
    )
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = img.filter(ImageFilter.SHARPEN)
    return img


def _parse_float(s: str) -> float | None:
    s = s.replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_ts(s: str) -> str | None:
    """
    Пробуем несколько форматов MT4/MT5:
      2024.01.15 10:30:00
      2024-01-15 10:30
      15.01.2024 10:30
    Возвращаем ISO: 2024-01-15T10:30:00
    """
    fmts = [
        "%Y.%m.%d %H:%M:%S",
        "%Y.%m.%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
    ]
    s = s.strip()
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
    return None


# Паттерн строки MT5 History Tab:
#   Ticket | Open Time | Type | Size | Symbol | Price | S/L | T/P | Close Time | Price | Commission | Swap | Profit
#   123456  2024.01.15 10:30:00  buy  0.10  EURUSD  1.09500  0.00  0.00  2024.01.15 14:20:00  1.09750  -0.70  0.00  25.00
_ROW_RE = re.compile(
    r"""
    (?P<ticket>\d+)\s+
    (?P<open_d>\d{4}[\.\-]\d{2}[\.\-]\d{2}\s+\d{2}:\d{2}(?::\d{2})?)\s+
    (?P<dir>buy|sell)\s+
    (?P<size>\d+\.?\d*)\s+
    (?P<symbol>[A-Z]{3,8}(?:USD|EUR|GBP|JPY|CAD|AUD|NZD|CHF|=F|=X|-USD)?)\s+
    (?P<entry>[\d\.]+)\s+
    [\d\.]+\s+[\d\.]+\s+                              # SL, TP
    (?P<close_d>\d{4}[\.\-]\d{2}[\.\-]\d{2}\s+\d{2}:\d{2}(?::\d{2})?)\s+
    (?P<exit>[\d\.]+)\s+
    (?P<comm>[\-\d\.]+)\s+
    [\-\d\.]+\s+                                       # swap
    (?P<profit>[\-\d\.]+)
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Упрощённый паттерн (без ticket): open | type | size | symbol | price → close | profit
_SIMPLE_RE = re.compile(
    r"""
    (?P<open_d>\d{4}[\.\-]\d{2}[\.\-]\d{2}\s+\d{2}:\d{2}(?::\d{2})?)\s+
    (?P<dir>buy|sell)\s+
    (?P<size>\d+\.?\d*)\s+
    (?P<symbol>[A-Z]{3,8})\s+
    (?P<entry>[\d\.]+).*?
    (?P<close_d>\d{4}[\.\-]\d{2}[\.\-]\d{2}\s+\d{2}:\d{2}(?::\d{2})?)\s+
    (?P<exit>[\d\.]+)\s+
    (?P<profit>[\-\d\.]+)
    """,
    re.VERBOSE | re.IGNORECASE | re.DOTALL,
)


def _extract_from_text(text: str) -> list[dict]:
    trades = []

    for m in _ROW_RE.finditer(text):
        open_ts  = _parse_ts(m.group("open_d"))
        close_ts = _parse_ts(m.group("close_d"))
        if not open_ts or not close_ts:
            continue
        entry = _parse_float(m.group("entry"))
        exit_ = _parse_float(m.group("exit"))
        size  = _parse_float(m.group("size"))
        pnl   = _parse_float(m.group("profit"))
        comm  = _parse_float(m.group("comm")) or 0.0
        if None in (entry, exit_, size, pnl):
            continue
        trades.append({
            "symbol":      m.group("symbol").upper(),
            "dir":         m.group("dir").lower(),
            "entry_price": entry,
            "exit_price":  exit_,
            "size":        size,
            "open_ts":     open_ts,
            "close_ts":    close_ts,
            "pnl":         pnl,
            "fees":        abs(comm),
            "source":      "ocr",
        })

    if not trades:
        for m in _SIMPLE_RE.finditer(text):
            open_ts  = _parse_ts(m.group("open_d"))
            close_ts = _parse_ts(m.group("close_d"))
            if not open_ts or not close_ts:
                continue
            entry = _parse_float(m.group("entry"))
            exit_ = _parse_float(m.group("exit"))
            size  = _parse_float(m.group("size"))
            pnl   = _parse_float(m.group("profit"))
            if None in (entry, exit_, size, pnl):
                continue
            trades.append({
                "symbol":      m.group("symbol").upper(),
                "dir":         m.group("dir").lower(),
                "entry_price": entry,
                "exit_price":  exit_,
                "size":        size,
                "open_ts":     open_ts,
                "close_ts":    close_ts,
                "pnl":         pnl,
                "fees":        0.0,
                "source":      "ocr",
            })

    return trades


def ocr_image(path: str | Path) -> list[dict]:
    """
    Читает изображение, запускает Tesseract, извлекает сделки.
    Возвращает список dict для add_trade().
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:
        raise RuntimeError(f"OCR недоступен: {e}")

    img = Image.open(str(path))
    img = _preprocess(img)

    config = "--psm 6 -c tessedit_char_whitelist='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz .:/-+'"
    text = pytesseract.image_to_string(img, lang="eng", config=config)
    return _extract_from_text(text)


def ocr_bytes(data: bytes, ext: str = ".png") -> list[dict]:
    """Принимает байты (из multipart upload)."""
    import io
    from PIL import Image
    img = Image.open(io.BytesIO(data))
    img = _preprocess(img)

    try:
        import pytesseract
    except ImportError as e:
        raise RuntimeError(f"OCR недоступен: {e}")

    config = "--psm 6 -c tessedit_char_whitelist='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz .:/-+'"
    text = pytesseract.image_to_string(img, lang="eng", config=config)
    return _extract_from_text(text)
