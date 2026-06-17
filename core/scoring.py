"""Скоринг сигналов — единый «мозг» системы.

Решает три вещи одинаково для всех источников (twitter / reddit / rss):
  1. dimension     — к какому измерению относится: economy | geopolitics | crowd
  2. econ_relevance— насколько это вообще про деньги/экономику/геополитику (0..1)
  3. crowd_intensity — насколько это «психология толпы»: эмоция + реакция (0..1)
  4. importance    — итоговый вес для ранжирования

Подход намеренно прозрачный (взвешенные лексиконы, без ML): легко
дотюнить под себя, работает оффлайн, объяснимо. Веса меняй в LEXICONS / WEIGHTS.
"""
from __future__ import annotations

import math
import re

# ─── Лексиконы: (измерение → категория → [(термин, вес)]) ───────────────────────
# Термины ищутся как подстроки в lower-case тексте. Веса 1–3 по «силе» сигнала.
# Двуязычно (EN/RU), т.к. твоя лента смешанная.

LEXICONS: dict[str, dict[str, list[tuple[str, float]]]] = {
    "economy": {
        "monetary": [
            ("federal reserve", 3), ("the fed", 3), (" fed ", 2), ("fomc", 3),
            ("interest rate", 3), ("rate cut", 3), ("rate hike", 3), ("ecb", 2),
            ("central bank", 2), ("ставка", 2), ("ключевая ставка", 3), ("фрс", 3),
            ("цб ", 2), ("инфляц", 3), ("inflation", 3), ("cpi", 3), ("ppi", 2),
            ("disinflation", 2), ("дефляц", 2), ("quantitative", 2), (" liquidity", 1),
        ],
        "markets": [
            ("s&p 500", 3), ("s&p", 2), ("nasdaq", 3), ("dow jones", 2),
            ("dow ", 1), ("russell", 2), ("nikkei", 2), ("ftse", 2),
            ("stock market", 3), ("stocks", 2), ("equit", 2), ("акци", 2),
            ("биржа", 2), ("индекс", 1), ("фондов", 2), ("bond yield", 3),
            ("treasury", 2), ("гособлигац", 2), ("доходност", 1), ("vix", 2),
            ("sell-off", 2), ("selloff", 2), ("rally", 1), ("bear market", 3),
            ("bull market", 2), ("market crash", 3), ("обвал", 2), ("коррекци", 1),
        ],
        "crypto": [
            ("bitcoin", 2), ("btc", 2), ("ethereum", 2), ("eth ", 1),
            ("crypto", 2), ("криптовалют", 2), ("крипт", 1), ("altcoin", 2),
            ("stablecoin", 2), ("etf", 2), ("halving", 2), ("defi", 1),
        ],
        "commodities": [
            ("crude oil", 3), ("brent", 3), ("wti", 2), ("нефть", 3),
            ("natural gas", 2), ("газ ", 1), ("gold price", 3), ("gold", 1),
            ("золот", 2), ("silver", 1), ("opec", 3), ("опек", 3),
            ("copper", 2), ("uranium", 2), ("commodit", 2), ("сырьев", 2),
        ],
        "fx": [
            ("dollar", 2), ("доллар", 2), ("евро", 1), ("euro ", 1),
            ("currency", 2), ("валют", 2), ("forex", 2), ("yuan", 2),
            ("юан", 2), ("devaluation", 3), ("девальвац", 3), ("тенге", 3),
            ("рубл", 2), ("exchange rate", 2), ("курс ", 1), ("peg", 1),
        ],
        "macro": [
            ("recession", 3), ("рецесси", 3), ("gdp", 2), ("ввп", 2),
            ("unemployment", 2), ("безработиц", 2), ("jobs report", 3),
            ("nonfarm", 3), ("payroll", 2), ("debt ceiling", 3), ("дефолт", 3),
            ("default", 2), ("bankruptcy", 2), ("банкрот", 2), ("stagflation", 3),
            ("soft landing", 2), ("hard landing", 2), ("credit", 1), ("кризис", 2),
        ],
        "corporate": [
            ("earnings", 2), ("quarterly results", 2), ("отчётност", 1),
            ("ipo", 2), ("buyback", 2), ("dividend", 1), ("дивиденд", 1),
            ("merger", 2), ("acquisition", 2), ("layoff", 2), ("увольнени", 1),
            ("guidance", 1), ("downgrade", 2), ("upgrade", 1),
        ],
    },
    "geopolitics": {
        "conflict": [
            ("war", 2), ("война", 2), ("missile", 2), ("ракет", 2),
            ("airstrike", 3), ("strike on", 2), ("удар по", 2), ("invasion", 3),
            ("вторжени", 3), ("offensive", 2), ("наступлени", 2), ("ceasefire", 3),
            ("перемири", 3), ("nuclear", 2), ("ядерн", 2), ("drone", 1),
            ("беспилотник", 1), ("escalation", 2), ("эскалац", 2),
        ],
        "actors": [
            ("nato", 2), ("нато", 2), ("kremlin", 2), ("кремль", 2),
            ("pentagon", 2), ("white house", 1), ("eu summit", 2),
            ("united nations", 1), ("оон", 1), ("g7", 2), ("g20", 2),
            ("brics", 2), ("брикс", 2), ("ukraine", 2), ("украин", 2),
            ("russia", 1), ("россия", 1), ("china", 1), ("китай", 1),
            ("israel", 2), ("израил", 2), ("iran", 2), ("иран", 2),
            ("taiwan", 2), ("тайван", 2), ("north korea", 2), ("кндр", 2),
        ],
        "sanctions": [
            ("sanction", 3), ("санкци", 3), ("embargo", 3), ("эмбарго", 3),
            ("tariff", 3), ("тариф", 2), ("пошлин", 2), ("trade war", 3),
            ("торговая война", 3), ("export ban", 3), ("экспортн", 1),
            ("blacklist", 2), ("frozen assets", 2), ("заморож", 2),
        ],
        "politics": [
            ("election", 2), ("выбор", 1), ("coup", 3), ("переворот", 3),
            ("impeach", 2), ("protest", 2), ("протест", 2), ("референдум", 2),
            ("referendum", 2), ("regime", 1), ("госпереворот", 3),
        ],
    },
    # «crowd» — не тема, а МАРКЕР эмоции/реакции. Используется отдельно ниже,
    # но держим тут для классификации «о чём твит по эмоциональной окраске».
    "crowd": {
        "fear": [
            ("panic", 3), ("паник", 3), ("crash", 2), ("крах", 3), ("обвал", 2),
            ("collapse", 3), ("коллапс", 2), ("meltdown", 3), ("disaster", 2),
            ("катастроф", 2), ("blood", 1), ("кров", 1), ("плач", 1),
            ("капитуляц", 2), ("capitulation", 2), ("fear", 1), ("страх", 1),
        ],
        "greed": [
            ("moon", 1), ("to the moon", 3), ("ракета", 1), ("euphoria", 3),
            ("эйфори", 3), ("fomo", 3), ("all in", 2), ("ва-банк", 2),
            ("100x", 2), ("озолот", 2), ("бум", 1), ("boom", 1), ("hype", 2),
            ("хайп", 2), ("mania", 2), ("мани", 1),
        ],
        "tribal": [
            ("everyone", 1), ("все ", 1), ("nobody", 1), ("никто", 1),
            ("they don't want you", 2), ("от вас скрывают", 3), ("проснит", 2),
            ("wake up", 2), ("the truth", 1), ("правда в том", 2),
            ("mainstream media", 2), ("сми скрыва", 3), ("шок", 1), ("shocking", 1),
        ],
    },
}

# Вклад измерений в econ_relevance (геополитика тоже двигает рынки)
DIM_ECON_WEIGHT = {"economy": 1.0, "geopolitics": 0.6, "crowd": 0.15}

# Веса итогового importance
WEIGHTS = {
    "econ_relevance": 0.45,
    "engagement": 0.30,   # лог-нормированный
    "virality": 0.15,     # прирост реакций между прогонами
    "crowd": 0.10,
}

_CASHTAG_RE = re.compile(r"[\$＄]([A-Za-z]{1,5})(?![A-Za-z])")
_PERCENT_RE = re.compile(r"\d+([.,]\d+)?\s?%")
_MONEY_RE = re.compile(r"[€$£¥₽]\s?\d|\d+\s?(млрд|млн|трлн|billion|million|trillion|bn|trn)\b", re.I)
_NUM_RE = re.compile(r"\b\d{2,}\b")


def _hits(text_lc: str, terms: list[tuple[str, float]]) -> float:
    return sum(w for term, w in terms if term in text_lc)


def classify(text: str) -> tuple[str, dict[str, float]]:
    """Вернуть (доминирующее_измерение, {economy, geopolitics, crowd})."""
    lc = f" {text.lower()} "
    scores = {"economy": 0.0, "geopolitics": 0.0, "crowd": 0.0}
    for dim, cats in LEXICONS.items():
        for terms in cats.values():
            scores[dim] += _hits(lc, terms)
    # доминирующее измерение по «содержательным» (не crowd) если они есть
    content = {k: scores[k] for k in ("economy", "geopolitics")}
    if max(content.values()) > 0:
        dim = max(content, key=content.get)
    else:
        dim = "crowd" if scores["crowd"] > 0 else "economy"
    return dim, scores


def cashtags(text: str) -> list[str]:
    """$AAPL, $BTC … → ['AAPL','BTC'] (uppercase, dedup, отсекаем мусор)."""
    out, seen = [], set()
    for m in _CASHTAG_RE.finditer(text):
        t = m.group(1).upper()
        if t not in seen and not t.isdigit():
            seen.add(t)
            out.append(t)
    return out


def econ_relevance(text: str, scores: dict[str, float] | None = None) -> float:
    """0..1 — насколько сигнал относится к экономике/геополитике.

    Это главный анти-шум фильтр. 'Earring just winked at the camera' → ~0.
    """
    if scores is None:
        _, scores = classify(text)
    lex = sum(scores[d] * w for d, w in DIM_ECON_WEIGHT.items())
    # бонусы за «рыночные» структуры в тексте
    struct = 0.0
    if _CASHTAG_RE.search(text):
        struct += 2.0
    if _PERCENT_RE.search(text):
        struct += 1.0
    if _MONEY_RE.search(text):
        struct += 1.5
    raw = lex + struct
    return round(math.tanh(raw / 6.0), 3)  # squash в 0..1


def crowd_intensity(text: str, engagement: int = 0, replies: int = 0) -> float:
    """0..1 — «психология толпы»: эмоциональный заряд + структура реакции.

    Высоко, когда: много эмоц-лексики, КАПС, '!!!', высокий отклик при коротком
    содержании, перекос replies/likes (срач) — всё это маркеры толпы, а не сути.
    """
    lc = text.lower()
    emo = sum(_hits(lc, terms) for terms in LEXICONS["crowd"].values())
    n = max(len(text), 1)
    caps = sum(1 for c in text if c.isupper()) / n
    bangs = text.count("!") + text.count("?")
    emoji = sum(1 for c in text if ord(c) > 0x1F000)
    # «реактивность»: много отклика на мало текста
    react = math.log1p(engagement) / max(math.log1p(n), 1.0)
    flame = (replies / max(engagement, 1)) if engagement else 0  # доля споров
    raw = emo + caps * 4 + min(bangs, 5) * 0.4 + min(emoji, 6) * 0.3 \
        + react * 1.2 + min(flame, 1.0) * 1.5
    return round(math.tanh(raw / 7.0), 3)


def importance(
    text: str,
    engagement: int,
    replies: int = 0,
    virality: float = 0.0,
) -> dict:
    """Полный скоринг сигнала. Возвращает все метрики + итоговый importance 0..1."""
    dim, scores = classify(text)
    er = econ_relevance(text, scores)
    ci = crowd_intensity(text, engagement, replies)
    eng_norm = math.tanh(math.log1p(engagement) / 11.0)  # ~11 = log(60k)
    vir_norm = math.tanh(virality / 5000.0)
    imp = (
        WEIGHTS["econ_relevance"] * er
        + WEIGHTS["engagement"] * eng_norm
        + WEIGHTS["virality"] * vir_norm
        + WEIGHTS["crowd"] * ci
    )
    return {
        "dimension": dim,
        "dim_scores": scores,
        "econ_relevance": er,
        "crowd_intensity": ci,
        "cashtags": cashtags(text),
        "importance": round(imp, 4),
    }


if __name__ == "__main__":
    # быстрый дымовой тест
    samples = [
        "Earring just winked at the camera",
        "BREAKING: The Fed signals a 50bps rate cut as CPI drops to 2.1%",
        "PANIC SELLING!!! $SPY crashing -4%, everyone is dumping, this is the END",
        "Россия и Украина: новые санкции ЕС ударят по экспорту нефти на $30 млрд",
        "тенге обвалился к доллару на 8%, девальвация ускоряется",
        "just had a great coffee this morning lol",
    ]
    for s in samples:
        r = importance(s, engagement=12000, replies=800, virality=2000)
        print(f"[{r['dimension']:11}] econ={r['econ_relevance']:.2f} "
              f"crowd={r['crowd_intensity']:.2f} imp={r['importance']:.2f} "
              f"tags={r['cashtags']}  | {s[:50]}")
