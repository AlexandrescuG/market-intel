"""core/trend_regime.py — WP4 (вектор состояния §4.A проектной спеки
«Агент-прогнозист»: "regime: trend | range (Hurst/ADX)").

НЕ то же самое, что `core/regime.py::detect_regime()` — тот отвечает на
другой вопрос (макро risk-on/off по VIX/DXY/кривой доходности, рынок в
целом). Здесь — трендовость КОНКРЕТНОГО инструмента на конкретном баре,
через ADX(14) (классика Уайлдера) — выбран вместо Hurst-экспоненты: у ADX
нет отдельной статистической процедуры оценки (R/S-анализ, DFA) со своей
погрешностью на малых окнах, а формула уже стандартна и проверяема построчно.
[ДОПУЩЕНИЕ] выбор ADX, не Hurst — задокументировано, не молчаливое решение.
"""
from __future__ import annotations

_PERIOD = 14


def _true_range(h: float, l: float, prev_c: float) -> float:
    return max(h - l, abs(h - prev_c), abs(l - prev_c))


def adx14_series(candles: list[dict]) -> list[float | None]:
    """ADX(14) по Уайлдеру на всей серии сразу — эффективно для батч-режима
    (base_rate.py перебирает тысячи исторических i на одном candles).
    Честный ноль lookahead: adx[i] зависит только от баров <= i (рекуррентное
    сглаживание Уайлдера, как ATR, но с warmup 2×period — сначала 14 баров
    на первую сумму +DM/-DM/TR, затем ещё 14 на сглаживание самого DX).
    None до i >= 2*_PERIOD (не подставляем частичное значение)."""
    n = len(candles)
    out: list[float | None] = [None] * n
    if n < 2 * _PERIOD + 1:
        return out

    plus_dm, minus_dm, tr = [0.0], [0.0], [0.0]  # индекс 0 -- нет предыдущего бара
    for i in range(1, n):
        up_move = candles[i]["h"] - candles[i - 1]["h"]
        down_move = candles[i - 1]["l"] - candles[i]["l"]
        plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0.0)
        minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0.0)
        tr.append(_true_range(candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]))

    # Первое сглаженное значение -- простая сумма первых _PERIOD баров (i=1.._PERIOD)
    sm_plus = sum(plus_dm[1:_PERIOD + 1])
    sm_minus = sum(minus_dm[1:_PERIOD + 1])
    sm_tr = sum(tr[1:_PERIOD + 1])
    dx_series: list[float | None] = [None] * n

    def _dx(sp: float, sm: float, st: float) -> float | None:
        if st <= 0:
            return None
        plus_di = 100 * sp / st
        minus_di = 100 * sm / st
        denom = plus_di + minus_di
        return 100 * abs(plus_di - minus_di) / denom if denom > 0 else 0.0

    dx_series[_PERIOD] = _dx(sm_plus, sm_minus, sm_tr)
    for i in range(_PERIOD + 1, n):
        # Уайлдер: smoothed[i] = smoothed[i-1] - smoothed[i-1]/period + current[i]
        sm_plus = sm_plus - sm_plus / _PERIOD + plus_dm[i]
        sm_minus = sm_minus - sm_minus / _PERIOD + minus_dm[i]
        sm_tr = sm_tr - sm_tr / _PERIOD + tr[i]
        dx_series[i] = _dx(sm_plus, sm_minus, sm_tr)

    # ADX -- сглаженное по Уайлдеру среднее DX за period, начиная как простая
    # средняя первых period значений DX (i от _PERIOD до 2*_PERIOD-1), дальше рекуррентно.
    valid_dx = [dx_series[j] for j in range(_PERIOD, 2 * _PERIOD) if dx_series[j] is not None]
    if len(valid_dx) < _PERIOD:
        return out
    adx = sum(valid_dx) / _PERIOD
    out[2 * _PERIOD - 1] = round(adx, 4)
    for i in range(2 * _PERIOD, n):
        dx_i = dx_series[i]
        if dx_i is None:
            continue
        adx = (adx * (_PERIOD - 1) + dx_i) / _PERIOD
        out[i] = round(adx, 4)
    return out


def trend_or_range(candles: list[dict], i: int, threshold: float = 25.0,
                    adx_ser: list[float | None] | None = None) -> str | None:
    """"trend" если ADX14>=threshold, иначе "range". [ДОПУЩЕНИЕ] порог 25 --
    стандартная эвристика Уайлдера, не откалибрована на этих данных. None,
    если ADX не определён на этом баре (разогрев)."""
    ser = adx_ser if adx_ser is not None else adx14_series(candles)
    if i < 0 or i >= len(ser) or ser[i] is None:
        return None
    return "trend" if ser[i] >= threshold else "range"
