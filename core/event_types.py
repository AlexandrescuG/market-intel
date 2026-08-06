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
    # Заявки на пособие по безработице — семья из трёх РАЗНЫХ показателей
    # (первичные / продолжающиеся / среднее за 4 недели), выходящих в один
    # и тот же час (обычно US, четверг). Порядок важен: сначала самые
    # специфичные, иначе "continuing"/"4-week" тоже попали бы в "initial" по
    # общему слову "claims". Найдено вживую (СПЕКА_графики_и_починка_
    # календаря.md §3): TradingView зовёт первичные "Initial Jobless Claims",
    # Forexfactory — "Unemployment Claims" — разные строки, один и тот же
    # релиз; без этой нормализации event_key/event_type их не видели дублем,
    # и любая статистика реакции на событие считала его дважды.
    (re.compile(r"(4|four)[-\s]?week.{0,20}(jobless|unemployment)\s+claims|(jobless|unemployment)\s+claims.{0,20}(4|four)[-\s]?week", re.I), "jobless_claims_4wk_avg"),
    (re.compile(r"continuing\s+(jobless\s+)?claims", re.I), "jobless_claims_continuing"),
    (re.compile(r"initial\s+jobless\s+claims|\bunemployment\s+claims\b|\bjobless\s+claims\b", re.I), "jobless_claims_initial"),
    # "unemployment" сам по себе раньше ловил разом ставку, изменение числа
    # безработных И заявки на пособие (уже перехвачены выше) — три РАЗНЫХ
    # показателя в одном ковше. Разведены; общий "unemployment" остаётся
    # честным фоллбеком для того, что не подошло ни под один частный случай.
    (re.compile(r"unemployment\s+rate", re.I), "unemployment_rate"),
    (re.compile(r"unemployment\s+change", re.I), "unemployment_change"),
    (re.compile(r"unemployment", re.I), "unemployment"),
]


def normalize_event_type(indicator_or_title: str) -> str:
    s = (indicator_or_title or "").strip()
    for pat, label in _EVENT_TYPE_PATTERNS:
        if pat.search(s):
            return label
    return re.sub(r"\s+", " ", s.lower()).strip()
