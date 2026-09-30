#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/state_vector.py — WP4 (SPEC_alpha_engine_implementation.md), вектор
состояния §4.A проектной спеки «Агент-прогнозист».

🔴 Найдено при проектировании (12.08, тот же класс бага, что history=False
в core/factor_store.py утром этой сессии): `sr_levels` хранит ТЕКУЩИЙ список
уровней (`broken=0`) — не point-in-time историю. Использовать его для
восстановления "какие уровни были видны в момент исторического ts" (нужно
`base_rate.py` для честного поиска базовой ставки) означало бы lookahead —
уровень, актуальный сегодня, молча подставился бы под сигнал 2019 года.

Поэтому ДВА разных сборщика, не один:
  - `build_state_vector_live()` — для промпта агента / `q_snapshot.py`,
    "как всё выглядит ПРЯМО СЕЙЧАС" — включает `level_dist_atr_bucket`
    (текущие уровни против текущей цены — это не lookahead, просто описание
    настоящего момента).
  - `build_state_vector_historical()` — для `base_rate.py` (перебор
    `labels` в поиске базовой ставки) — БЕЗ `level_dist_atr_bucket` вообще
    (ключа нет в словаре, не `None` — это принципиально другое "отсутствует",
    чем `news_burst_z`/`positioning`, у которых данных просто пока нет, но
    измерить не lookahead). `calendar_prox` в историческом режиме фильтрует
    `econ_events` по `first_seen <= ts` — иначе тихий lookahead будущих
    объявлений календаря (та же дисциплина, что `factor_repack_job.py::repack_calendar`).

EMA20/ADX14/ATR14 честно историчны (рекуррентные формулы, зависят только от
баров <= i) — участвуют в обоих режимах без оговорок.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.ema import ema_series, ema20_state
from core.trend_regime import adx14_series, trend_or_range
from core.sessions import session_at
from analyze.labeler import _atr14

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")


# ─────────────────────────────────────────────────── дискретизация (§план) ──

def bucket_ema20_dist_atr(x: float) -> str:
    """[ДОПУЩЕНИЕ] ±0.5 = половина среднего бара (сам ATR); ±1.5 =
    labeler.py GRID atr_mult=1.5 — расстояние, на котором система сама
    расставляет стопы. Фиксировано, не пересчитывается динамически
    (forecasts иммутабельна — бакет не должен менять смысл задним числом)."""
    if x < -1.5:
        return "far_below"
    if x < -0.5:
        return "near_below"
    if x <= 0.5:
        return "at"
    if x <= 1.5:
        return "near_above"
    return "far_above"


def bucket_level_dist_atr(x: float) -> str:
    """[ДОПУЩЕНИЕ] 0.25 = sr_levels_job.py:138 tolerance=atr*0.25 (то же
    определение "касания уровня"). Геометрический шаг (×3) — правоскошенная
    величина, равные ОТНОШЕНИЯ дают сопоставимую плотность выборки."""
    if x < 0.25:
        return "touching"
    if x < 0.75:
        return "close"
    if x < 2.0:
        return "nearby"
    return "far"


def bucket_vol_pctl(x: float) -> str:
    """Перцентиль уже 0..100 по построению — фиксированные срезы не
    переобучаются (в отличие от квантиля по сырым ATR)."""
    if x < 20:
        return "q1_low"
    if x < 40:
        return "q2"
    if x < 60:
        return "q3"
    if x < 80:
        return "q4"
    return "q5_high"


def bucket_calendar_prox(minutes: float | None) -> str:
    """[ДОПУЩЕНИЕ] геометрический шаг ×4 — high-impact релизы редки
    (тонкий пик у нуля на фоне длинных тихих участков). None и ">=1440" —
    один терминальный бакет ("календарь сейчас не фактор" — один факт)."""
    if minutes is None or minutes >= 1440:
        return "quiet"
    if minutes < 15:
        return "imminent"
    if minutes < 60:
        return "close"
    if minutes < 240:
        return "same_session"
    return "same_day"


# ───────────────────────────────────────────────────── индикаторный кэш ──

def build_indicator_cache(candles: list[dict]) -> dict:
    """{"atr14": [...], "ema20": [...], "adx14": [...]} — считается ОДИН
    раз на весь candles-массив (symbol,tf), переиспользуется и для live
    (последний индекс), и для батч-перебора истории в base_rate.py — без
    этого пересчёт на КАЖДУЮ historical-строку был бы O(n) -> O(n²) суммарно."""
    closes = [c["c"] for c in candles]
    atr14 = [_atr14(candles, i) for i in range(len(candles))]
    ema20 = ema_series(closes, period=20)
    adx14 = adx14_series(candles)
    return {"atr14": atr14, "ema20": ema20, "adx14": adx14}


def _vol_percentile(atr_ser: list[float | None], i: int, window: int = 60) -> float | None:
    """Симметрично day_thermo_job.py:_range_percentile, но на окне,
    заканчивающемся на i (не на конце всего массива) — нужно для
    исторического переиспользования, не только "последний бар"."""
    if i < 0 or i >= len(atr_ser) or atr_ser[i] is None:
        return None
    lo = max(0, i - window + 1)
    win = [a for a in atr_ser[lo:i + 1] if a is not None]
    if len(win) < 2:
        return None
    today = atr_ser[i]
    return round(100.0 * sum(1 for a in win if a <= today) / len(win), 1)


def load_high_impact_events(con: sqlite3.Connection) -> list[tuple[int, int]]:
    """🔴 REVIEW_wp4_cycle_2026-08-13.md §5: устраняет N+1 -- раньше
    calendar_prox_minutes() делала SQL-запрос к econ_events НА КАЖДУЮ
    историческую строку внутри base_rate.py._collect_rows() (тысячи
    запросов на один lookup_base_rate() при H1/H4 -- живой замер: 15.8с на
    один вызов на H1 GOLD). [(scheduled_ts, first_seen)] для ВСЕХ
    high-impact событий -- 548 строк на 13.08.2026, загружаются ОДИН раз
    вызывающим кодом (`_collect_rows` перед циклом по символам), не на
    каждую строку."""
    rows = con.execute(
        "SELECT scheduled_ts, first_seen FROM econ_events "
        "WHERE impact='high' AND scheduled_ts IS NOT NULL AND first_seen IS NOT NULL"
    ).fetchall()
    return [(int(s), int(f)) for s, f in rows]


def _calendar_prox_from_events(events: list[tuple[int, int]], ts: int, as_of_ts: int | None) -> float | None:
    """IN-MEMORY версия -- events уже загружены (load_high_impact_events).
    as_of_ts — честная историческая точка отсечения по first_seen (не видим
    объявления, сделанные ПОЗЖЕ ts); as_of_ts=None -- live (всё известное сейчас)."""
    candidates = [s for s, f in events if f <= as_of_ts] if as_of_ts is not None else [s for s, _ in events]
    if not candidates:
        return None
    return round(min(abs(s - ts) / 60.0 for s in candidates), 1)


def calendar_prox_minutes(con: sqlite3.Connection, ts: int, as_of_ts: int | None) -> float | None:
    """Однократный (live) вызов -- сама загружает события. Для батча
    (base_rate.py, много строк за один вызов) используй
    `load_high_impact_events()` один раз + `_calendar_prox_from_events()` —
    см. докстринг `load_high_impact_events`, иначе фикс N+1 не работает."""
    return _calendar_prox_from_events(load_high_impact_events(con), ts, as_of_ts)


def _nearest_level_dist_atr(con: sqlite3.Connection, canonical_symbol: str,
                             price: float, atr_val: float | None) -> float | None:
    """⚠️ ТОЛЬКО для live — см. докстринг модуля (нет point-in-time истории уровней)."""
    if atr_val is None or atr_val <= 0:
        return None
    row = con.execute(
        "SELECT price FROM sr_levels WHERE symbol=? AND broken=0 ORDER BY ABS(price-?) ASC LIMIT 1",
        (canonical_symbol, price),
    ).fetchone()
    if not row:
        return None
    return abs(price - row[0]) / atr_val


def _common_fields(candles: list[dict], i: int, cache: dict, events: list[tuple[int, int]],
                    ts: int, as_of_ts: int | None) -> dict:
    from datetime import datetime, timezone
    atr_val = cache["atr14"][i]
    ema_st = ema20_state(candles, i, ema_ser=cache["ema20"], atr_val=atr_val)
    regime = trend_or_range(candles, i, adx_ser=cache["adx14"])
    vol_pctl = _vol_percentile(cache["atr14"], i)
    cal_min = _calendar_prox_from_events(events, ts, as_of_ts)
    d = datetime.fromtimestamp(ts, tz=timezone.utc)
    return {
        "atr14": atr_val,
        "session": session_at(d.date(), d.hour),
        "ema20_side": ema_st["side"] if ema_st else None,
        "ema20_dist_atr_bucket": bucket_ema20_dist_atr(ema_st["dist_atr"]) if ema_st else None,
        "ema20_slope": ema_st["slope"] if ema_st else None,
        "trend_regime": regime,
        "vol_bucket": bucket_vol_pctl(vol_pctl) if vol_pctl is not None else None,
        "calendar_prox_bucket": bucket_calendar_prox(cal_min),
        # физически отсутствуют на 12.08.2026 -- честный None, не выдумка
        # (news_bursts пуста, sentiment_hourly -- только BTC, COT/funding нет):
        "news_burst_z": None,
        "sentiment_score": None,
        "positioning": None,
    }


def build_state_vector_live(canonical_symbol: str, pb_symbol: str, tf: str,
                             candles: list[dict], con: sqlite3.Connection,
                             cache: dict | None = None,
                             events: list[tuple[int, int]] | None = None) -> dict:
    """Полный вектор "как сейчас" — включает level_dist_atr_bucket. events —
    предзагруженный load_high_impact_events(); None -- загружается здесь
    (однократный live-вызов, N+1 не актуален)."""
    i = len(candles) - 1
    cache = cache or build_indicator_cache(candles)
    events = events if events is not None else load_high_impact_events(con)
    ts = candles[i]["ts"]
    fields = _common_fields(candles, i, cache, events, ts, as_of_ts=None)
    fields["level_dist_atr_bucket"] = None
    lvl = _nearest_level_dist_atr(con, canonical_symbol, candles[i]["c"], fields["atr14"])
    if lvl is not None:
        fields["level_dist_atr_bucket"] = bucket_level_dist_atr(lvl)
    return {"symbol": canonical_symbol, "tf": tf, "ts": ts, **fields}


def build_state_vector_historical(canonical_symbol: str, tf: str, i: int,
                                   candles: list[dict], cache: dict,
                                   events: list[tuple[int, int]]) -> dict:
    """Вектор для base_rate.py — БЕЗ level_dist_atr_bucket (см. докстринг
    модуля), calendar_prox честно отфильтрован по first_seen<=ts бара i.
    events -- ОБЯЗАТЕЛЬНЫЙ, без дефолта: вызывающий код (`base_rate.py`)
    должен загрузить `load_high_impact_events()` ОДИН раз на весь
    lookup_base_rate(), не на каждую строку -- иначе фикс N+1 молча
    перестаёт работать при следующей правке."""
    ts = candles[i]["ts"]
    fields = _common_fields(candles, i, cache, events, ts, as_of_ts=ts)
    return {"symbol": canonical_symbol, "tf": tf, "ts": ts, **fields}
