"""
core/smc.py — WP3.2 SPEC_alpha_engine_implementation.md.

Порт `SBFGrafik.detectSMC` (`web/assets/grafik-engine.js:528-609`) в Python
— интерфейс как у `core/patterns.detect()`: `detect(ohlcv) -> [{event,
ts, direction, ...}]`. Расчёт, не рендер: после порта `chart.html`
переводится на этот же Python-эндпоинт (как уже сделано для свечных
паттернов — та же развилка, что зафиксирована комментарием в
`chart.html:431-432` про `detectCandles`). `SBFGrafik.detectSMC` остаётся
только для образовательной галереи (§3 спеки, "что не трогать").

СНЯТО ограничение JS-версии, недопустимое в расчёте (§WP3.2 спеки):
  - FVG/OB в JS отдают только последние 5/3 "для читаемости" — здесь ВСЮ
    историю.
  - BOS в JS считается только относительно ПОСЛЕДНЕГО значимого свинга,
    находит только ПЕРВЫЙ пробой после него (`break` в цикле) — то есть
    максимум один bull- и один bear-BOS за вызов. Для бэктеста этого
    недостаточно: здесь `bos_choch_events()` идёт по ВСЕЙ последовательности
    свингов и репортит каждый пробой.

ДОБАВЛЕНО сверх JS-версии (по видеоматериалу практикующего трейдера,
§1.9 спеки — SMC PRO Algorithm показывал именно эти элементы):
  - choch: смена характера — пробой ПРОТИВ текущего направления структуры,
    а не в его продолжение (BOS). Механически то же самое (закрытие бара
    за значимым свингом), различие чисто в текущем trend-state.
  - liquidity_pool: кластеры равных хаёв/лоёв (где логически стоят стопы).
  - sweep: прокол пула ликвидности с разворотом закрытием обратно за
    уровень — описан в глоссарии (`grafik-engine.js:190`), но никогда не
    детектился нигде в коде.
  - detect_mtf_fvg: тот же FVG-детектор на СТАРШЕМ ТФ, сшитый по времени
    с рабочим рядом (для мультитаймфреймового режима, как в видеоматериале
    — FVG на 15m/1h/4h/D одновременно).

Анти-lookahead: свинг ПРИЗНАЁТСЯ только через `lookback` баров ПОСЛЕ
экстремума (тот же принцип, что `sr_levels_job._fractals`/`FRACTAL_CONFIRM`,
и тот же класс бага, что уже был найден и исправлен в
`core/patterns.py::_detect_double_extremes` — см. комментарий там).
Каждая свинг-точка несёт `confirm_ts` ОТДЕЛЬНО от `ts` самого экстремума;
все события выше репортятся с `confirm_ts`, не с `ts` пика/дна.
"""
from __future__ import annotations

DEFAULT_LOOKBACK = 5
LIQUIDITY_TOLERANCE_ATR_MULT = 0.15  # [ДОПУЩЕНИЕ] не откалибровано, WP3.2
SWEEP_REVERSAL_BARS = 3              # [ДОПУЩЕНИЕ] не откалибровано, WP3.2
SWEEP_SEARCH_BARS = 50               # окно поиска прокола после формирования пула


def _atr14(candles):
    if len(candles) < 15:
        return None
    trs = [candles[0]["h"] - candles[0]["l"]]
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-14:]) / 14


def swing_points(candles: list[dict], lookback: int = DEFAULT_LOOKBACK) -> tuple[list[dict], list[dict]]:
    """([highs], [lows]) — фракталы: строгий экстремум в окне
    [i-lookback, i+lookback]. confirm_ts = ts бара, через который свинг
    стал известен (i+lookback), НЕ ts самого экстремума — см. докстринг
    модуля про анти-lookahead."""
    n = len(candles)
    highs, lows = [], []
    for i in range(lookback, n - lookback):
        hi, lo = candles[i]["h"], candles[i]["l"]
        is_h = all(candles[j]["h"] < hi for j in range(i - lookback, i + lookback + 1) if j != i)
        is_l = all(candles[j]["l"] > lo for j in range(i - lookback, i + lookback + 1) if j != i)
        if is_h:
            highs.append({"i": i, "ts": candles[i]["ts"], "confirm_ts": candles[i + lookback]["ts"], "y": hi})
        if is_l:
            lows.append({"i": i, "ts": candles[i]["ts"], "confirm_ts": candles[i + lookback]["ts"], "y": lo})
    return highs, lows


def structure_events(highs: list[dict], lows: list[dict]) -> list[dict]:
    """HH/LH на хаях, HL/LL на лоях. ts=confirm_ts."""
    out = []
    for k in range(1, len(highs)):
        bull = highs[k]["y"] > highs[k - 1]["y"]
        out.append({"event": "hh" if bull else "lh", "ts": highs[k]["confirm_ts"],
                    "y": highs[k]["y"], "direction": "bullish" if bull else "bearish"})
    for k in range(1, len(lows)):
        bull = lows[k]["y"] > lows[k - 1]["y"]
        out.append({"event": "hl" if bull else "ll", "ts": lows[k]["confirm_ts"],
                    "y": lows[k]["y"], "direction": "bullish" if bull else "bearish"})
    out.sort(key=lambda e: e["ts"])
    return out


def bos_choch_events(candles: list[dict], highs: list[dict], lows: list[dict]) -> list[dict]:
    """ПОЛНАЯ историческая серия BOS/CHoCH (JS-версия — только последний
    свинг, только первый пробой после него, см. докстринг модуля).

    Механика: последовательно по барам держим текущий "активный" уровень
    (последний ПОДТВЕРЖДЁННЫЙ свинг-хай/лоу, ещё не пробитый). Закрытие
    бара за уровнем -- пробой; если пробой ПО направлению текущего
    trend-state -- BOS (продолжение), если ПРОТИВ -- CHoCH (смена
    характера), и trend-state переключается. Первый пробой в истории
    (trend ещё не определён) классифицируется как BOS -- нечего менять."""
    points = sorted(
        [{"ts": h["confirm_ts"], "y": h["y"], "kind": "high"} for h in highs] +
        [{"ts": l["confirm_ts"], "y": l["y"], "kind": "low"} for l in lows],
        key=lambda p: p["ts"],
    )
    by_ts: dict[int, list[dict]] = {}
    for p in points:
        by_ts.setdefault(p["ts"], []).append(p)

    events = []
    trend = None
    last_high, last_low = None, None
    high_broken, low_broken = True, True
    for c in candles:
        for p in by_ts.get(c["ts"], []):
            if p["kind"] == "high":
                last_high, high_broken = p["y"], False
            else:
                last_low, low_broken = p["y"], False
        if last_low is not None and not low_broken and c["c"] < last_low:
            low_broken = True
            is_choch = trend == "bullish"
            events.append({"event": "choch" if is_choch else "bos", "ts": c["ts"],
                           "y": last_low, "direction": "bearish"})
            trend = "bearish"
        if last_high is not None and not high_broken and c["c"] > last_high:
            high_broken = True
            is_choch = trend == "bearish"
            events.append({"event": "choch" if is_choch else "bos", "ts": c["ts"],
                           "y": last_high, "direction": "bullish"})
            trend = "bullish"
    events.sort(key=lambda e: e["ts"])
    return events


def fvg_events(candles: list[dict]) -> list[dict]:
    """FVG — 3-свечной разрыв. Вся история (JS ограничивает 5 последних
    "для читаемости" — см. докстринг модуля)."""
    out = []
    for i in range(2, len(candles)):
        a, ci = candles[i - 2], candles[i]
        if ci["l"] > a["h"]:
            out.append({"event": "fvg", "ts": ci["ts"], "top": ci["l"], "bottom": a["h"], "direction": "bullish"})
        elif ci["h"] < a["l"]:
            out.append({"event": "fvg", "ts": ci["ts"], "top": a["l"], "bottom": ci["h"], "direction": "bearish"})
    return out


def detect_mtf_fvg(candles_by_tf: dict[str, list[dict]]) -> list[dict]:
    """FVG на каждом переданном ТФ отдельно, помечен своим tf — для
    мультитаймфреймового режима (видеоматериал §1.9: FVG на 15m/1h/4h/D
    одновременно). candles_by_tf: {"H1": [...], "H4": [...], ...}."""
    out = []
    for tf, candles in candles_by_tf.items():
        for e in fvg_events(candles):
            out.append({**e, "tf": tf})
    out.sort(key=lambda e: e["ts"])
    return out


def ob_events(candles: list[dict]) -> list[dict]:
    """OB — последняя противоположная свеча перед импульсом (>1.5x
    диапазона предыдущей свечи). Вся история (JS ограничивает 3)."""
    out = []
    for i in range(1, len(candles)):
        ci, pi = candles[i], candles[i - 1]
        if pi["h"] == pi["l"]:
            continue
        impulse = abs(ci["c"] - ci["o"])
        prev_range = pi["h"] - pi["l"]
        if ci["c"] > ci["o"] and impulse > prev_range * 1.5 and pi["c"] < pi["o"]:
            out.append({"event": "ob", "ts": pi["ts"], "top": pi["h"], "bottom": pi["l"], "direction": "bullish"})
        elif ci["c"] < ci["o"] and impulse > prev_range * 1.5 and pi["c"] > pi["o"]:
            out.append({"event": "ob", "ts": pi["ts"], "top": pi["h"], "bottom": pi["l"], "direction": "bearish"})
    return out


def liquidity_pools(candles: list[dict], highs: list[dict], lows: list[dict],
                     tolerance: float | None = None) -> list[dict]:
    """Кластеры свингов в пределах tolerance друг от друга — "равные
    хаи/лои", где логически стоят стопы. direction — сторона ожидаемого
    разворота ПОСЛЕ прокола (равные хаи -> прокол+разворот вниз =
    bearish), не направление самого пула."""
    if tolerance is None:
        atr = _atr14(candles)
        tolerance = (atr or 0) * LIQUIDITY_TOLERANCE_ATR_MULT
        if tolerance <= 0:
            return []

    def cluster(points, direction):
        pools = []
        pts = sorted(points, key=lambda p: p["y"])
        cur = []
        for p in pts:
            if cur and abs(p["y"] - cur[-1]["y"]) > tolerance:
                if len(cur) >= 2:
                    pools.append({"event": "liquidity_pool", "ts": max(x["confirm_ts"] for x in cur),
                                  "y": sum(x["y"] for x in cur) / len(cur), "direction": direction, "n": len(cur)})
                cur = [p]
            else:
                cur.append(p)
        if len(cur) >= 2:
            pools.append({"event": "liquidity_pool", "ts": max(x["confirm_ts"] for x in cur),
                          "y": sum(x["y"] for x in cur) / len(cur), "direction": direction, "n": len(cur)})
        return pools

    out = cluster(highs, "bearish") + cluster(lows, "bullish")
    out.sort(key=lambda e: e["ts"])
    return out


def sweep_events(candles: list[dict], pools: list[dict],
                  reversal_bars: int = SWEEP_REVERSAL_BARS,
                  search_bars: int = SWEEP_SEARCH_BARS) -> list[dict]:
    """Прокол уровня пула + разворот (закрытие обратно за уровень) в
    пределах reversal_bars после прокола, который сам должен случиться в
    пределах search_bars после формирования пула. Описан в глоссарии
    (grafik-engine.js:190), но не детектился нигде — см. докстринг модуля."""
    out = []
    ts_to_idx = {c["ts"]: i for i, c in enumerate(candles)}
    for pool in pools:
        level = pool["y"]
        start_i = ts_to_idx.get(pool["ts"])
        if start_i is None:
            continue
        for i in range(start_i + 1, min(start_i + 1 + search_bars, len(candles))):
            c = candles[i]
            poked = (pool["direction"] == "bearish" and c["h"] > level) or \
                    (pool["direction"] == "bullish" and c["l"] < level)
            if not poked:
                continue
            for k in range(1, reversal_bars + 1):
                if i + k >= len(candles):
                    break
                reverted = (pool["direction"] == "bearish" and candles[i + k]["c"] < level) or \
                           (pool["direction"] == "bullish" and candles[i + k]["c"] > level)
                if reverted:
                    out.append({"event": "sweep", "ts": candles[i + k]["ts"], "y": level,
                               "direction": pool["direction"]})
                    break
            break
    out.sort(key=lambda e: e["ts"])
    return out


def detect(ohlcv: list[dict], lookback: int = DEFAULT_LOOKBACK) -> list[dict]:
    """[{event, ts, direction, ...}] — единый вход, интерфейс как у
    core.patterns.detect(). event ∈ {hh,lh,hl,ll,bos,choch,fvg,ob,
    liquidity_pool,sweep}."""
    if len(ohlcv) < lookback * 2 + 1:
        return []
    highs, lows = swing_points(ohlcv, lookback)
    out = []
    out += structure_events(highs, lows)
    out += bos_choch_events(ohlcv, highs, lows)
    out += fvg_events(ohlcv)
    out += ob_events(ohlcv)
    pools = liquidity_pools(ohlcv, highs, lows)
    out += pools
    out += sweep_events(ohlcv, pools)
    out.sort(key=lambda e: e["ts"])
    return out
