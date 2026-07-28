#!/usr/bin/env python3
"""
xray_days.py — глава 7 «Институциональный след», §3.7/§4.3
(SPEC_edu_level7_institutional_footprint.md). Строит данные для
перевёрнутого интерактива «Рентген»: зоны считаются по ФИКСИРОВАННЫМ
правилам модели (круглые уровни с шагом по инструменту + край диапазона
предыдущей сессии), НЕ по реальным заявкам — реальных заявок у нас нет и
быть не может (только дилер видит свою книгу условных ордеров).

Правило фиксируется ДО подсчёта, дни берутся ПОСЛЕДОВАТЕЛЬНО (последние 6
полных торговых дней с данными), исход каждого дня — то, что фактически
произошло на реальных H1-свечах. Подгонки под желаемое распределение нет:
сколько дней из шести совпало с моделью, столько и публикуется.

Вход:  web/data/ohlc_GOLD_H1.json, ohlc_GOLD_D1.json
Выход: web/data/edu_stats/xray_days.json + web/data/edu_scenes/ch7_xray.json

Запуск: python3 tools/edu_build/xray_days.py
"""
import datetime
import json
import pathlib
import statistics

ROOT = pathlib.Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
H1_IN = WEB / "data" / "ohlc_GOLD_H1.json"
D1_IN = WEB / "data" / "ohlc_GOLD_D1.json"
OUT_STATS = WEB / "data" / "edu_stats" / "xray_days.json"
OUT_SCENE = WEB / "data" / "edu_scenes" / "ch7_xray.json"

ROUND_STEP = 50          # шаг "круглых" уровней золота, $ (психологические уровни 4000/4050/...)
ZONE_TOL = 4.0           # допуск касания зоны, $
REVERSAL_BARS = 6        # горизонт проверки исхода после касания, H1-баров
REVERSAL_THRESHOLD = ZONE_TOL * 2  # на сколько нужно уйти от зоны, чтобы засчитать разворот
N_DAYS = 6


def day_key(ts):
    if isinstance(ts, str):
        return ts[:10]
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d")


def round_levels_near(lo, hi, step, pad):
    start = int((lo - pad) // step) * step
    end = int((hi + pad) // step + 1) * step
    return list(range(start, end + step, step))


def find_touch_and_outcome(bars, zones):
    """Первое касание любой зоны в течение дня + исход через REVERSAL_BARS баров."""
    for i, c in enumerate(bars):
        for z in zones:
            if (c["low"] - ZONE_TOL) <= z <= (c["high"] + ZONE_TOL):
                # касание. Определяем сторону подхода по цене закрытия предыдущего бара.
                prior_close = bars[i - 1]["close"] if i > 0 else c["open"]
                approached_from_below = prior_close < z
                horizon = bars[i:i + REVERSAL_BARS + 1]
                if len(horizon) < 2:
                    continue
                end_close = horizon[-1]["close"]
                if approached_from_below:
                    reversed_ = (z - end_close) >= REVERSAL_THRESHOLD
                    broke_through = (end_close - z) >= REVERSAL_THRESHOLD
                else:
                    reversed_ = (end_close - z) >= REVERSAL_THRESHOLD
                    broke_through = (z - end_close) >= REVERSAL_THRESHOLD
                outcome = "reversed" if reversed_ else ("broke_through" if broke_through else "inconclusive")
                return {
                    "touch_time": c["time"], "zone_price": z,
                    "approached_from_below": approached_from_below,
                    "outcome": outcome, "hit": outcome == "reversed",
                }
    return None


def main():
    h1_raw = json.loads(H1_IN.read_text())
    h1 = h1_raw["candles"]
    # SPEC_ch7_debug.md §2 / chapters/SHARED.md §3.3: тиковый объём уже лежит
    # рядом со свечами в ohlc_*.json, курс его нигде не использует. Для главы
    # про институциональный след это ближайшая наблюдаемая мера активности --
    # подшиваем к каждой свече сцены по совпадению time.
    volume_by_time = {v["time"]: v["value"] for v in h1_raw.get("volume", [])}
    d1 = json.loads(D1_IN.read_text())["candles"]

    by_day_h1 = {}
    for c in h1:
        by_day_h1.setdefault(day_key(c["time"]), []).append(c)
    for k in by_day_h1:
        by_day_h1[k].sort(key=lambda c: c["time"])

    d1_by_day = {day_key(c["time"]): c for c in d1}
    all_days_sorted = sorted(by_day_h1.keys())

    # Последние N_DAYS ПОЛНЫХ торговых дней (>=18 H1 баров, чтобы отсечь
    # неполные пограничные сутки датасета), у которых есть предыдущий D1-бар
    # для края диапазона предыдущей сессии.
    candidate_days = [d for d in all_days_sorted if len(by_day_h1[d]) >= 18]
    candidate_days = candidate_days[:-1] if candidate_days and candidate_days[-1] == all_days_sorted[-1] and len(by_day_h1[all_days_sorted[-1]]) < 24 else candidate_days
    selected_days = candidate_days[-N_DAYS:]

    results = []
    for idx, dk in enumerate(selected_days):
        bars = by_day_h1[dk]
        day_lo = min(c["low"] for c in bars)
        day_hi = max(c["high"] for c in bars)

        prev_idx = all_days_sorted.index(dk) - 1
        prev_dk = all_days_sorted[prev_idx] if prev_idx >= 0 else None
        prev_d1 = d1_by_day.get(prev_dk) if prev_dk else None

        zones = round_levels_near(day_lo, day_hi, ROUND_STEP, pad=ROUND_STEP)
        zone_kinds = [{"price": float(z), "kind": "round_number"} for z in zones]
        if prev_d1:
            zone_kinds.append({"price": prev_d1["high"], "kind": "prev_session_high"})
            zone_kinds.append({"price": prev_d1["low"], "kind": "prev_session_low"})

        zone_prices = [z["price"] for z in zone_kinds]
        touch = find_touch_and_outcome(bars, zone_prices)

        results.append({
            "date": dk,
            "candles": [{"time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"],
                         "volume": volume_by_time.get(c["time"])} for c in bars],
            "zones": zone_kinds,
            "touch": touch,
        })

    n_scored = sum(1 for r in results if r["touch"] and r["touch"]["outcome"] != "inconclusive")
    n_hit = sum(1 for r in results if r["touch"] and r["touch"]["hit"])
    xray_hit = n_hit  # из шести -- используется как {{xray_hit}} в тексте главы

    stats_out = {
        "_meta": {
            "built": datetime.date.today().isoformat(),
            "symbol": "GOLD", "granularity": "H1",
            "round_step": ROUND_STEP, "zone_tolerance": ZONE_TOL,
            "reversal_horizon_bars": REVERSAL_BARS, "reversal_threshold": REVERSAL_THRESHOLD,
            "selection": "last_6_consecutive_trading_days",
            "n_days": len(results), "n_scored": n_scored, "n_hit": n_hit,
            "xray_hit": xray_hit,
            "note_ru": "Зоны — фиксированные круглые уровни ($50 шаг) и границы диапазона предыдущей сессии, а не реальные заявки. Дни отобраны как последние 6 подряд с полными данными, исход — фактический на реальных H1-свечах.",
        },
        "days": [{"date": r["date"], "touch": r["touch"], "n_zones": len(r["zones"])} for r in results],
    }
    OUT_STATS.parent.mkdir(parents=True, exist_ok=True)
    OUT_STATS.write_text(json.dumps(stats_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    scene_out = {
        "meta": {
            "symbol": "GOLD", "granularity": "H1",
            "days": [r["date"] for r in results],
            "xray_hit": xray_hit, "n_days": len(results),
            "selection_note_ru": "Шесть последовательных торговых дней, отобраны без учёта исхода.",
            "selection_note_ro": "Șase zile de tranzacționare consecutive, alese fără a ține cont de rezultat.",
            "selection_note_en": "Six consecutive trading days, picked without regard to the outcome.",
        },
        "days": results,
    }
    OUT_SCENE.parent.mkdir(parents=True, exist_ok=True)
    OUT_SCENE.write_text(json.dumps(scene_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"дней отобрано: {len(results)} ({selected_days[0]} → {selected_days[-1]})")
    for r in results:
        t = r["touch"]
        desc = "нет касания" if not t else f"{t['outcome']} @ {t['zone_price']}"
        print(f"  {r['date']}: {desc}")
    print(f"xray_hit = {xray_hit} из {len(results)} (scored: {n_scored})")
    print(f"→ {OUT_STATS}\n→ {OUT_SCENE}")


if __name__ == "__main__":
    main()
