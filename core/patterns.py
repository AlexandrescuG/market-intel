"""
core/patterns.py — SBF_Charts_Layer2_Spec, Фаза 3, Шаг 1.

Единый интерфейс детекции паттернов (детерминированные правила, без ML):
  detect(ohlcv, levels=None) -> [{pattern_key, ts, direction}]

ohlcv: [{ts,o,h,l,c}] отсортировано по ts возрастанию.
levels (опционально, только для break_retest): [{price,tolerance,kind}] —
исторические уровни из sr_levels (Фаза 1, sr_levels_job.py).

И бэктест-джоб (pattern_stats_job.py), и live-рендер (serve.py'ы
/api/chart/patterns) используют ЭТУ функцию — единый источник паттернов
для всей платформы (см. Acceptance спеки).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from sr_levels_job import _atr14, _fractals, FRACTAL_CONFIRM  # noqa: E402

PATTERNS = {
    "bearish_engulfing": {"display_name_ru": "Медвежье поглощение", "direction": "bearish"},
    "bullish_engulfing": {"display_name_ru": "Бычье поглощение", "direction": "bullish"},
    "pin_bar_top":       {"display_name_ru": "Пин-бар сверху", "direction": "bearish"},
    "pin_bar_bottom":    {"display_name_ru": "Пин-бар снизу", "direction": "bullish"},
    "inside_bar":        {"display_name_ru": "Внутренний бар", "direction": "neutral"},
    "double_top":        {"display_name_ru": "Двойная вершина", "direction": "bearish"},
    "double_bottom":     {"display_name_ru": "Двойное дно", "direction": "bullish"},
    "break_retest":      {"display_name_ru": "Пробой с ретестом", "direction": "neutral"},
}

MIN_CANDLES = 20
DOUBLE_MIN_GAP, DOUBLE_MAX_GAP = 5, 30
BREAK_RETEST_WINDOW = 5


def _body(c):
    return abs(c["c"] - c["o"])


def _range(c):
    return c["h"] - c["l"]


def _is_bull(c):
    return c["c"] >= c["o"]


def _detect_engulfing(candles):
    out = []
    for i in range(1, len(candles)):
        p, c = candles[i - 1], candles[i]
        bp = _body(p)
        if bp <= 0:
            continue
        if not _is_bull(p) and _is_bull(c) and c["o"] <= p["c"] and c["c"] >= p["o"] and _body(c) > bp * 1.02:
            out.append({"pattern_key": "bullish_engulfing", "ts": c["ts"], "direction": "bullish"})
        if _is_bull(p) and not _is_bull(c) and c["o"] >= p["c"] and c["c"] <= p["o"] and _body(c) > bp * 1.02:
            out.append({"pattern_key": "bearish_engulfing", "ts": c["ts"], "direction": "bearish"})
    return out


def _detect_pin_bars(candles):
    """Тень >= 2x тела, тело в верхней/нижней трети диапазона (см. спеку)."""
    out = []
    for c in candles:
        b, r = _body(c), _range(c)
        if b <= 0 or r <= 0:
            continue
        body_top, body_bottom = max(c["o"], c["c"]), min(c["o"], c["c"])
        upper_shadow, lower_shadow = c["h"] - body_top, body_bottom - c["l"]
        in_lower_third = (body_top - c["l"]) <= r / 3
        in_upper_third = (c["h"] - body_bottom) <= r / 3
        if upper_shadow >= b * 2 and in_lower_third:
            out.append({"pattern_key": "pin_bar_top", "ts": c["ts"], "direction": "bearish"})
        if lower_shadow >= b * 2 and in_upper_third:
            out.append({"pattern_key": "pin_bar_bottom", "ts": c["ts"], "direction": "bullish"})
    return out


def _detect_inside_bar(candles):
    out = []
    for i in range(1, len(candles)):
        p, c = candles[i - 1], candles[i]
        if c["h"] <= p["h"] and c["l"] >= p["l"]:
            out.append({"pattern_key": "inside_bar", "ts": c["ts"], "direction": "neutral"})
    return out


def _detect_double_extremes(candles):
    """double_top/double_bottom: два fractal-экстремума в пределах 0.3*ATR
    друг от друга, 5-30 свечей между ними."""
    out = []
    atr = _atr14(candles)
    if not atr:
        return out
    tolerance = atr * 0.3
    fr = _fractals(candles)
    highs = [(i, p) for i, p, k in fr if k == "high"]
    lows = [(i, p) for i, p, k in fr if k == "low"]

    def pairs(points, pattern_key, direction):
        res = []
        for a in range(len(points)):
            i1, p1 = points[a]
            for b in range(a + 1, len(points)):
                i2, p2 = points[b]
                gap = i2 - i1
                if gap > DOUBLE_MAX_GAP:
                    break  # points отсортированы по индексу — дальше только больше gap
                if gap < DOUBLE_MIN_GAP:
                    continue
                if abs(p1 - p2) <= tolerance:
                    # Фрактал в i2 подтверждается только через FRACTAL_CONFIRM свечей
                    # ПОСЛЕ него (см. _fractals — экстремум признаётся, только если
                    # следующие 3 свечи ниже/выше). Если бы паттерн репортился с
                    # ts=candles[i2] и бэктест мерил close через 3/5/10 свечей ОТ
                    # этой же точки, часть "будущего" уже гарантированно заложена
                    # в сам критерий детекции — классический lookahead bias
                    # (проверено эмпирически: agree_share ~70-77% на реальных
                    # данных против ~45-54% у всех остальных паттернов, пока не
                    # нашёл и не поправил). Репортим момент ПОДТВЕРЖДЕНИЯ, не пик.
                    confirm_idx = i2 + FRACTAL_CONFIRM
                    if confirm_idx >= len(candles):
                        continue
                    res.append({"pattern_key": pattern_key, "ts": candles[confirm_idx]["ts"], "direction": direction})
        return res

    out += pairs(highs, "double_top", "bearish")
    out += pairs(lows, "double_bottom", "bullish")
    return out


def _detect_break_retest(candles, levels):
    """Пробой уровня Фазы 1 + ретест в пределах 5 свечей."""
    out = []
    if not levels:
        return out
    for lv in levels:
        price, tol, kind = lv["price"], lv["tolerance"], lv["kind"]
        half = tol / 2
        broke_idx, broke_dir = None, None
        for i, c in enumerate(candles):
            if broke_idx is None:
                broke_down = kind in ("support", "flip") and c["c"] < price - half
                broke_up = kind in ("resistance", "flip") and c["c"] > price + half
                if broke_down or broke_up:
                    broke_idx = i
                    broke_dir = "bearish" if broke_down else "bullish"
                continue
            if i - broke_idx > BREAK_RETEST_WINDOW:
                broke_idx = None
                continue
            if (price - half) <= c["h"] and (price + half) >= c["l"]:
                out.append({"pattern_key": "break_retest", "ts": c["ts"], "direction": broke_dir})
                broke_idx = None
    return out


def detect(ohlcv, levels=None):
    if len(ohlcv) < MIN_CANDLES:
        return []
    out = []
    out += _detect_engulfing(ohlcv)
    out += _detect_pin_bars(ohlcv)
    out += _detect_inside_bar(ohlcv)
    out += _detect_double_extremes(ohlcv)
    out += _detect_break_retest(ohlcv, levels)
    out.sort(key=lambda e: e["ts"])
    return out
