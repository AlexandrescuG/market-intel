"""Нормализация названия календарного события в стабильный тип для группировки
исторических публикаций (SBF_Charts_Layer1_Spec, Фаза 2).

Используется и в event_reactions_job.py (агрегация по event_type), и в
serve.py (отдаётся в /api/chart/events, чтобы фронтенд не дублировал regex
и не разъезжался с джобом в написании ключей)."""
import re

_EVENT_TYPE_PATTERNS = [
    # "non[-\s]?farm" один ловил "Nonfarm Productivity QoQ" (совсем другая
    # единица измерения — % QoQ, не тысячи рабочих мест) в тот же ковш, что и
    # настоящий Non Farm Payrolls/Non-Farm Employment Change -- найдено при
    # подготовке главы 6 (surprise_reaction.py, сигма по "nfp" считалась на
    # смеси единиц). Явно исключаем "productivity", остальные написания
    # (Payrolls, Employment Change, Private) остаются в ковше.
    (re.compile(r"non[-\s]?farm(?!\s+productivity)|\bnfp\b", re.I), "nfp"),
    (re.compile(r"\bcpi\b", re.I), "cpi"),
    (re.compile(r"interest rate|rate decision", re.I), "rate"),
    (re.compile(r"\bpmi\b", re.I), "pmi"),
    (re.compile(r"\bgdp\b", re.I), "gdp"),
    (re.compile(r"unemployment", re.I), "unemployment"),
]


def normalize_event_type(indicator_or_title: str) -> str:
    s = (indicator_or_title or "").strip()
    for pat, label in _EVENT_TYPE_PATTERNS:
        if pat.search(s):
            return label
    return re.sub(r"\s+", " ", s.lower()).strip()
