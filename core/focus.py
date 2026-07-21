"""core/focus.py — Focus Engine: чистая арифметика (ATR/аномальность/гистерезис).

SPEC_focus_engine.md. Инвариант спеки (§0): Focus Engine — не LLM, разрешён
пересчёт в рантайме. Эта функция намеренно БЕЗ обращения к БД — принимает уже
загруженные кандидаты, отдаёт решение. Загрузка/запись (load_watchlist,
load_live, load_atr_today, commit в БД) — забота вызывающего кода
(focus_batch_job.py / focus_live.py), не этого модуля. Так select_focus()
проверяется синтетическими данными без поднятия БД.
"""
from __future__ import annotations

from dataclasses import dataclass

# ── Гистерезис (§4, значения из спеки — не приближение) ─────────────────────
SWITCH_MARGIN = 0.15    # претендент должен превзойти действующий на 15%
MIN_HOLD_SEC = 1800     # минимум 30 мин удержания перед сменой
CALM_FLOOR = 1.30       # ниже этого — «спокойный рынок», сильного фокуса нет

# ── Вселенная по умолчанию (§2) — существующие 15 инструментов графика +
# DXY (добавляется в publish.py's WATCH, см. шаг 2 плана). USDJPY/USDRUB/
# USDKZT (MT5) не имеют живого фида (§11) -- участвуют только в batch-подборе.
DEFAULT_UNIVERSE = [
    "GOLD", "SILVER", "BTC", "ETH", "SOL",
    "EURUSD", "GBPUSD", "SPX", "NASDAQ", "DJI",
    "WTI", "NG", "DXY", "USDJPY", "USDRUB", "USDKZT",
]

# Инструменты без живого интрадей-фида (MT5, тянутся раз в 30 мин с
# удалённого Windows-бокса) -- см. instrument.live_capable.
NO_LIVE_FEED = {"USDJPY", "USDRUB", "USDKZT"}


def true_range(high: float, low: float, prev_close: float) -> float:
    """§1: TR_t = max(high-low, |high-prev_close|, |low-prev_close|)."""
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def wilder_atr(candles: list[dict], n: int = 14, as_of_date: str | None = None) -> float | None:
    """§1.1: ATR по Уайлдеру. candles -- по возрастанию даты, каждый:
    {'date': 'YYYY-MM-DD', 'h':.., 'l':.., 'c':..}.

    as_of_date исключает ещё не закрытую "сегодняшнюю" свечу -- ATR(N) должен
    быть базой из ЗАКРЫТЫХ дней, иначе сегодняшний частичный диапазон
    просачивается в свой же знаменатель (publish.py обновляет
    ohlc_*_D1.json каждые 5 мин круглосуточно, поэтому в 06:00 для FX/
    металлов частичная "сегодняшняя" свеча уже существует).

    Инициализация: ATR_1 = среднее(TR_1..TR_N). Далее рекурсия Уайлдера:
    ATR_t = (ATR_(t-1)*(N-1) + TR_t) / N. Нужно >= N+1 закрытых свечей.
    """
    if as_of_date:
        candles = [c for c in candles if c["date"] < as_of_date]
    if len(candles) < n + 1:
        return None
    trs = [true_range(candles[i]["h"], candles[i]["l"], candles[i - 1]["c"])
           for i in range(1, len(candles))]
    atr = sum(trs[:n]) / n
    for tr in trs[n:]:
        atr = (atr * (n - 1) + tr) / n
    return atr


def running_tr(day_high: float, day_low: float, prev_close: float) -> float:
    """§1.2: runningTR = max(day_high, prev_close) − min(day_low, prev_close).
    НЕ day_high-day_low -- включает овернайт-гэп от вчерашнего закрытия."""
    return max(day_high, prev_close) - min(day_low, prev_close)


def anomaly(running_tr_value: float | None, atr: float | None) -> float | None:
    """§1.3: anomaly = runningTR / ATR(N)."""
    if running_tr_value is None or not atr:
        return None
    return running_tr_value / atr


@dataclass
class FocusState:
    scope_key: str
    symbol: str | None
    anomaly: float | None
    decided_at: int
    source: str   # 'batch' | 'live' | 'pin' | 'calm'


def _to_calm(scope_key: str, current: FocusState | None, now: int) -> FocusState:
    # §7 + edge case §11 ("Все закрыты → calm, а не пусто"): и "нет кандидатов"
    # (keep_or_calm), и "лучший кандидат ниже CALM_FLOOR" (set_calm) в спеке
    # оба ведут в calm-состояние -- разница в имени helper'ов не описана
    # отдельно, трактуем как один и тот же переход. Если уже calm -- не
    # дёргаем decided_at, чтобы "спокоен с ..." не скакал каждый цикл.
    if current and current.source == "calm":
        return FocusState(scope_key, None, None, current.decided_at, "calm")
    return FocusState(scope_key, None, None, now, "calm")


def select_focus(
    scope_key: str,
    candidates: list[tuple[str, float | None]],
    pinned_symbol: str | None,
    current: FocusState | None,
    now: int,
    new_source: str = "live",
) -> FocusState:
    """Прямой перевод псевдокода §10. candidates -- уже отфильтрованы
    вызывающим кодом по session_state=='open' и наличию ATR (эта функция не
    трогает БД); каждый элемент (symbol, anomaly_or_None).

    new_source -- какой source проставлять при НОВОМ выборе (первый пик или
    смена фокуса): focus_batch_job.py вызывает с new_source="batch" (у него
    current всегда None -- это единственный контекст, где рождается
    "batch"-пик дня), focus_live.py -- с дефолтным "live". Сам псевдокод §10
    один на оба контекста, различие только в этом параметре.
    """
    if pinned_symbol:
        return FocusState(scope_key, pinned_symbol, None, now, "pin")

    cands = [(sym, a) for sym, a in candidates if a is not None]
    if not cands:
        return _to_calm(scope_key, current, now)

    cands.sort(key=lambda c: c[1], reverse=True)
    top_sym, top_a = cands[0]
    if top_a < CALM_FLOOR:
        return _to_calm(scope_key, current, now)

    cand_map = dict(cands)
    if current is None or current.source == "calm" or current.symbol not in cand_map:
        return FocusState(scope_key, top_sym, top_a, now, new_source)

    if now - current.decided_at < MIN_HOLD_SEC:
        return FocusState(scope_key, current.symbol, cand_map[current.symbol],
                           current.decided_at, current.source)

    if top_sym == current.symbol:
        return FocusState(scope_key, top_sym, top_a, current.decided_at, current.source)

    if top_a > current.anomaly * (1 + SWITCH_MARGIN):
        return FocusState(scope_key, top_sym, top_a, now, new_source)

    return FocusState(scope_key, current.symbol, cand_map[current.symbol],
                       current.decided_at, current.source)
