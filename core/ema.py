"""core/ema.py — WP4 (SPEC_alpha_engine_implementation.md, вектор состояния §4.A
проектной спеки «Агент-прогнозист»).

EMA20 существовал только в JS-оверлее графика (`web/assets/grafik-engine.js:58`,
`function ema(a,p){var k=2/(p+1),o=[],pr;for(...)...}`) — как фактор в Python
не было вообще. Здесь — тот же порт формулы, не переизобретение: одна и та
же EWMA, чтобы график и агент считали одно и то же число (принцип «один
детектор — три потребителя» из проектной спеки §7).

Честный ноль lookahead: EMA(k) на баре i зависит только от close[i] и
EMA[i-1] — рекуррентная формула математически не видит будущего, поэтому
считать весь ряд один раз (`ema_series`) и потом индексировать по i даёт
ТОЧНО то же число, что пересчёт "только по префиксу до i" на каждый вызов —
дешевле, не менее честно.
"""
from __future__ import annotations


def ema_series(closes: list[float], period: int = 20) -> list[float]:
    """EMA(period) по всей серии, seed = closes[0] (как в grafik-engine.js)."""
    if not closes:
        return []
    k = 2 / (period + 1)
    out = [closes[0]]
    for c in closes[1:]:
        out.append(c * k + out[-1] * (1 - k))
    return out


def ema20_state(candles: list[dict], i: int, ema_ser: list[float] | None = None,
                 atr_val: float | None = None, slope_lookback: int = 3) -> dict | None:
    """{"side": "above"|"below", "dist_atr": float, "slope": "up"|"down"|"flat"}
    на баре i. dist_atr нормализован на atr_val (передаётся явно — та же
    политика, что в labeler.py: ATR считает вызывающий код, здесь не
    выдумывается второй способ посчитать ATR). ema_ser — предвычисленный
    ряд (build_indicator_cache) для батч-режима (base_rate.py перебирает
    тысячи исторических i на ОДНОМ candles — пересчёт ema_series на каждый
    вызов был бы O(n) на строку, O(n²) суммарно); при None считается
    заново — удобно для разовых live-вызовов (q_snapshot.py).

    None, если i < period (разогрев) или atr_val отсутствует — не
    подставляем частичное/неполное значение."""
    if i < 20 or atr_val is None or atr_val <= 0:
        return None
    closes = [c["c"] for c in candles[: i + 1]]
    ser = ema_ser if ema_ser is not None else ema_series(closes, period=20)
    if len(ser) <= i or i < slope_lookback:
        return None
    price = candles[i]["c"]
    ema_now = ser[i]
    ema_prev = ser[i - slope_lookback]
    dist_atr = (price - ema_now) / atr_val
    slope_atr = (ema_now - ema_prev) / atr_val
    # [ДОПУЩЕНИЕ] порог "flat" — 0.1 ATR за slope_lookback баров, не откалибровано
    slope = "up" if slope_atr > 0.1 else ("down" if slope_atr < -0.1 else "flat")
    return {"side": "above" if price >= ema_now else "below",
            "dist_atr": round(dist_atr, 4), "slope": slope}
