"""SBF_Charts_Layer3_Spec, Фаза 3: словарная (не ML) разметка bull/bear по
тексту, RU+EN. Простое сравнение количества совпадений — намеренно (спека
прямым текстом запрещает вводить ML). Акцептанс спеки требует ручной сверки
20 сообщений с совпадением ≥70% — см. scratchpad-тест, использованный при
разработке; словарь подбирался под реальные тексты twitter/telegram этого
проекта, не абстрактно.
"""
import re

_BULL_EN = [
    "bullish", "bull run", "mooning", "to the moon", "buy the dip", "buying",
    "long", "breakout", "rally", "rallying", "pump", "pumping", "uptrend",
    "rocket", "all-time high", "ath", "accumulate", "accumulating",
    "undervalued", "higher", "surge", "surging", "soar", "soaring", "gains",
    "green", "outperform", "upgrade", "bull market", "strength", "recovery",
    "rebound", "hodl", "hodling",
]
_BEAR_EN = [
    "bearish", "dump", "dumping", "sell-off", "selloff", "crash", "crashing",
    "correction", "downtrend", "tank", "tanking", "plunge", "plunging",
    "drop", "dropping", "decline", "declining", "overvalued", "lower",
    "capitulation", "red", "underperform", "downgrade", "bear market",
    "weakness", "sell off", "collapse", "slump", "recession fears",
]
_BULL_RU = [
    "бычий", "бычьи", "лонг", "покупа", "растёт", "рост", "выросл", "ракета",
    "пробой вверх", "накопление", "недооценен", "зелён", "профит", "отскок",
    "рекорд", "рекордный", "укрепля", "укрепил", "вверх", "восстановлен",
]
_BEAR_RU = [
    "медвежий", "медвежьи", "шорт", "продава", "падает", "падение", "упал",
    "обвал", "коррекция", "слив", "переоценен", "красн", "убыток", "просад",
    "вниз", "снижен", "ослаб", "распродаж", "паник",
]

_BULL_RE = re.compile("|".join(re.escape(w) for w in _BULL_EN + _BULL_RU), re.I)
_BEAR_RE = re.compile("|".join(re.escape(w) for w in _BEAR_EN + _BEAR_RU), re.I)


def classify_text(text: str) -> str | None:
    """'bull' | 'bear' | None (нейтрально/не размечено). Считаем количество
    совпадений с каждым словарём — не первое слово, а большинство, чтобы
    заголовок с одним случайным упоминанием на фоне трёх явных не переворачивал
    знак."""
    if not text:
        return None
    bull_hits = len(_BULL_RE.findall(text))
    bear_hits = len(_BEAR_RE.findall(text))
    if bull_hits == 0 and bear_hits == 0:
        return None
    if bull_hits > bear_hits:
        return "bull"
    if bear_hits > bull_hits:
        return "bear"
    return None


def detect_divergence(scores_24h: list, price_change: float, atr: float | None) -> bool:
    """|score_avg_24h| > 0.5 при |изменении цены за 24h| < 0.3×ATR — спека
    Фазы 3. Для бейджа («настроение и цена расходятся»), не для сигнала.
    scores_24h — часовые score БЕЗ пропущенных часов (вызывающая сторона не
    должна передавать точки-пропуски как 0)."""
    if not scores_24h or not atr or atr <= 0:
        return False
    avg = sum(scores_24h) / len(scores_24h)
    return abs(avg) > 0.5 and abs(price_change) < 0.3 * atr
