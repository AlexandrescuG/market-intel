#!/usr/bin/env python3
"""
Сцена ch5_coldopen_day — глава 5, cold open «У прилива есть таблица» (§3.0).

Одни реальные сутки золота, 48 получасовых баров. День выбирается как
МЕДИАННЫЙ по дневному диапазону — намеренно не рекордный. Спека формулирует это
прямо: «день выбран как типичный, а не как рекордный», и подпись об этом обязана
попасть на экран, иначе мы врём выборкой в главе про честность выборок.

Заодно считает два числа, на которых держится текст cold open:
  · quiet_third_range — суммарный ход за первую треть суток (00:00–07:59 UTC)
  · peak_bar_range    — ход самого крупного бара суток
Оба уходят в meta и рендерятся из данных, руками в тексте их нет.

Вход:  web/data/ohlc_GOLD_M30.json
Выход: web/data/edu_scenes/ch5_coldopen_day.json

Запуск: python3 tools/edu_build/build_ch5_coldopen_day.py
"""
import datetime
import json
import pathlib
import statistics

ROOT = pathlib.Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
OUT = WEB / "data" / "edu_scenes" / "ch5_coldopen_day.json"

ASSET = "GOLD"
MIN_BARS = 40          # сутки должны быть полными, иначе «типичность» ни о чём
QUIET_HOURS = range(0, 8)


def iso(ts):
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    raw = json.loads((WEB / "data" / f"ohlc_{ASSET}_M30.json").read_text(encoding="utf-8"))
    candles = raw["candles"] if isinstance(raw, dict) else raw

    days = {}
    for c in candles:
        ts = datetime.datetime.fromtimestamp(c["time"], datetime.timezone.utc).replace(tzinfo=None)
        days.setdefault(ts.date(), []).append((ts, c))
    for v in days.values():
        v.sort(key=lambda x: x[0])

    full = {d: v for d, v in days.items() if len(v) >= MIN_BARS}
    if not full:
        raise SystemExit("нет ни одних полных суток в бэкфилле")

    ranges = {d: max(c["high"] for _, c in v) - min(c["low"] for _, c in v) for d, v in full.items()}
    med = statistics.median(ranges.values())
    day = min(ranges, key=lambda d: abs(ranges[d] - med))     # ближайший к медиане
    bars = full[day]

    quiet = [c for ts, c in bars if ts.hour in QUIET_HOURS]
    quiet_range = (max(c["high"] for c in quiet) - min(c["low"] for c in quiet)) if quiet else None
    peak_ts, peak_c = max(bars, key=lambda x: x[1]["high"] - x[1]["low"])
    peak_range = peak_c["high"] - peak_c["low"]
    peak_vs_quiet = round(peak_range / quiet_range, 2) if quiet_range else None

    # Cold open текст (ch5.js) утверждает "бар больше первой трети" — это
    # верно не для каждого отобранного (медианного) дня. Ветка текста должна
    # идти из peak_vs_quiet, а не быть написанной один раз под драматичный день.
    if peak_vs_quiet is None:
        coldopen_key = "quiet"
    elif peak_vs_quiet >= 1.5:
        coldopen_key = "dramatic"
    elif peak_vs_quiet >= 1.0:
        coldopen_key = "close"
    else:
        coldopen_key = "quiet"

    out = {
        "meta": {
            "symbol": ASSET, "granularity": "M30",
            "date": day.isoformat(), "range": [day.isoformat(), day.isoformat()],
            "day_range": round(ranges[day], 2),
            "median_day_range": round(med, 2),
            "days_considered": len(full),
            "quiet_third_range": round(quiet_range, 2) if quiet_range is not None else None,
            "peak_bar_time": iso(peak_ts),
            "peak_bar_range": round(peak_range, 2),
            "peak_vs_quiet": peak_vs_quiet,
            "coldopen_key": coldopen_key,
            "selection": "median_day_range",
            "selection_note_ru": "День выбран как типичный по дневному диапазону, а не как рекордный.",
            "selection_note_ro": "Ziua a fost aleasă ca tipică după intervalul zilnic, nu ca record.",
            "selection_note_en": "Day picked as typical by daily range — deliberately not the loudest.",
            "reconstruction": False,
            "source": "market_intel MT5 backfill (web/data/ohlc_GOLD_M30.json), реальные M30 OHLC.",
        },
        "candles": [{"time": iso(ts), "open": c["open"], "high": c["high"],
                     "low": c["low"], "close": c["close"]} for ts, c in bars],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"день {day}: диапазон {ranges[day]:.2f} (медиана по {len(full)} дням {med:.2f})")
    print(f"первая треть суток: {quiet_range:.2f} · крупнейший бар {iso(peak_ts)}: {peak_range:.2f}")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
