"""Торговые сессии (SBF_Charts_Layer3_Spec, Фаза 2): границы Азия/Лондон/NY
в UTC с учётом перехода на летнее время. Азия (Токио) DST не наблюдает —
границы фиксированы круглый год. Лондон — правило EU (последнее воскресенье
марта/октября), Нью-Йорк — правило US (второе воскресенье марта / первое
воскресенье ноября). Часы, заданные в спеке (Лондон 07-16, NY 12-21 UTC) —
это летние (DST) значения; зимой оба сдвигаются на +1ч UTC.

Используется и джобом (нет — джоб считает профиль по часам, DST его не
касается), и API (`/api/chart/sessions`, поле `sessions_today`). Рендер
самих полос на графике для ПРОИЗВОЛЬНОГО видимого дня (не только сегодня —
пользователь может проскроллить график к историческим датам через переход
DST) сознательно продублирован в JS (`chart.html`) теми же правилами: это
не избыточность, а необходимость — нельзя обслужить произвольную дату через
один API-round-trip на каждый видимый день без ощутимой задержки рендера.
"""
from datetime import date, timedelta


def _last_sunday(year: int, month: int) -> date:
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)
    return last_day - timedelta(days=(last_day.weekday() - 6) % 7)


def _nth_sunday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    first_sunday = first + timedelta(days=(6 - first.weekday()) % 7)
    return first_sunday + timedelta(weeks=n - 1)


def eu_dst_active(d: date) -> bool:
    return _last_sunday(d.year, 3) <= d < _last_sunday(d.year, 10)


def us_dst_active(d: date) -> bool:
    return _nth_sunday(d.year, 3, 2) <= d < _nth_sunday(d.year, 11, 1)


def session_bounds_utc(d: date) -> dict:
    """{'asia': (0,8), 'london': (from,to), 'ny': (from,to)} — часы UTC [from,to)."""
    london = (7, 16) if eu_dst_active(d) else (8, 17)
    ny = (12, 21) if us_dst_active(d) else (13, 22)
    return {"asia": (0, 8), "london": london, "ny": ny}


def session_at(d: date, hour: int) -> str | None:
    """SBF_Charts_Layer4_Spec, Фаза 2 (контекст-строка карточки сделки):
    какая сессия шла в конкретный час UTC конкретной даты — 'asia'/'london'/
    'ny'/'overlap' или None (между Азией и Лондоном, ~ничья зона рынка)."""
    b = session_bounds_utc(d)
    in_london = b["london"][0] <= hour < b["london"][1]
    in_ny = b["ny"][0] <= hour < b["ny"][1]
    if in_london and in_ny:
        return "overlap"
    if in_london:
        return "london"
    if in_ny:
        return "ny"
    if b["asia"][0] <= hour < b["asia"][1]:
        return "asia"
    return None
