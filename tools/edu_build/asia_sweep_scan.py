#!/usr/bin/env python3
"""
Проверка утверждения «лондонский прокол диапазона Азии обычно ложный» —
глава 5 «Глобальные Часы», блок AMD (§3.7), сцена (§3.8), тренажёр (§3.9).

Вход:  web/data/ohlc_GOLD_M30.json
Выход: web/data/edu_stats/asia_sweep.json   — доли исходов + 6 дней для тренажёра
       web/data/edu_scenes/ch5_london_sweep.json — сцена SceneEngine (mode "event")

ПРАВИЛА ЗАФИКСИРОВАНЫ ДО ПОДСЧЁТА и не меняются после того, как увидим ответ.
Это единственная защита от подгонки критерия под желаемый результат — и ровно
то, чему учит сама глава.

    Азиатский диапазон : 00:00–06:59 UTC (максимум/минимум за окно)
    Окно прокола       : 07:00–08:59 UTC (открытие Лондона + первый час)
    Момент оценки      : последний бар с часом ≤ 20:00 UTC (конец US-сессии)

    continuation — закрытие ЗА пробитой границей (пробой оказался истинным)
    reversal     — закрытие по ДРУГУЮ сторону диапазона (прокол оказался ложным)
    neutral      — закрытие внутри диапазона
    Дни, где пробиты обе границы или ни одной, из выборки исключаются.

ЧЕСТНОСТЬ ВЫБОРКИ. Бэкфилл M30 на 27.07.2026 покрывает ~2026-05-13 → 2026-07-25
(см. комментарий в hourly_profile.py). Это порядка полусотни торговых дней, а не
восьми лет, как предполагала спека. Поэтому скрипт:
  · всегда пишет n_days и доверительный интервал Уилсона для каждой доли;
  · выставляет verdict_key = "small_sample", когда дней меньше SMALL_SAMPLE;
  · НЕ округляет проблему — фронт обязан отрисовать n рядом с процентами.
Публикуем то число, которое получилось, вместе с тем, насколько ему можно верить.

Запуск:  python3 tools/edu_build/asia_sweep_scan.py
"""
import datetime
import json
import math
import pathlib
import statistics

ROOT = pathlib.Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
OUT_STATS = WEB / "data" / "edu_stats" / "asia_sweep.json"
OUT_SCENE = WEB / "data" / "edu_scenes" / "ch5_london_sweep.json"

ASSET = "GOLD"
ASIA = range(0, 7)
LONDON = range(7, 9)
US_END = 20
MIN_ASIA_BARS = 10       # неполный азиатский диапазон — день выбрасываем
SMALL_SAMPLE = 100       # ниже этого числа дней вердикт помечается как ненадёжный


# ─────────────────────────────────────────────────────────────── загрузка

def load_days():
    raw = json.loads((WEB / "data" / f"ohlc_{ASSET}_M30.json").read_text(encoding="utf-8"))
    candles = raw["candles"] if isinstance(raw, dict) else raw
    days = {}
    for c in candles:
        ts = datetime.datetime.fromtimestamp(c["time"], datetime.timezone.utc).replace(tzinfo=None)
        days.setdefault(ts.date(), []).append({
            "ts": ts, "o": float(c["open"]), "h": float(c["high"]),
            "l": float(c["low"]), "c": float(c["close"]),
        })
    for d in days.values():
        d.sort(key=lambda b: b["ts"])
    return dict(sorted(days.items()))


# ───────────────────────────────────────────────────────────── классификация

def classify(bars):
    """→ (outcome, info) или (None, None), если день не попадает в выборку."""
    asia = [b for b in bars if b["ts"].hour in ASIA]
    if len(asia) < MIN_ASIA_BARS:
        return None, None
    hi = max(b["h"] for b in asia)
    lo = min(b["l"] for b in asia)
    if hi <= lo:
        return None, None

    lon = [b for b in bars if b["ts"].hour in LONDON]
    if not lon:
        return None, None
    up = max(b["h"] for b in lon) > hi
    down = min(b["l"] for b in lon) < lo
    if up == down:                      # обе границы или ни одной
        return ("no_sweep", {"hi": hi, "lo": lo, "dir": None}) if not up else (None, None)

    tail = [b for b in bars if b["ts"].hour <= US_END]
    if not tail:
        return None, None
    close = tail[-1]["c"]

    if up:
        outcome = "continuation" if close > hi else ("reversal" if close < lo else "neutral")
        sweep_bar = next(b for b in lon if b["h"] > hi)
    else:
        outcome = "continuation" if close < lo else ("reversal" if close > hi else "neutral")
        sweep_bar = next(b for b in lon if b["l"] < lo)

    return outcome, {
        "hi": round(hi, 2), "lo": round(lo, 2),
        "dir": "up" if up else "down",
        "sweep_ts": sweep_bar["ts"],
        "close": round(close, 2),
        "amplitude": round(abs(close - (hi if up else lo)), 2),
        "range": round(hi - lo, 2),
    }


def wilson(k, n, z=1.96):
    """Доверительный интервал Уилсона — честнее нормального при малых n."""
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    s = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round(100 * (c - s) / d, 1), round(100 * (c + s) / d, 1)]


def iso(ts):
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def day_payload(date, bars, info, outcome):
    return {
        "date": date.isoformat(),
        "outcome": outcome,
        "asia_high": info["hi"],
        "asia_low": info["lo"],
        "sweep_dir": info["dir"],
        "sweep_time": iso(info["sweep_ts"]) if info.get("sweep_ts") else None,
        "close": info.get("close"),
        "candles": [{"time": iso(b["ts"]), "open": b["o"], "high": b["h"],
                     "low": b["l"], "close": b["c"]} for b in bars],
    }


# ─────────────────────────────────────────────────────────────────── main

def main():
    days = load_days()
    buckets = {"continuation": [], "reversal": [], "neutral": [], "no_sweep": []}
    skipped = 0

    for date, bars in days.items():
        outcome, info = classify(bars)
        if outcome is None:
            skipped += 1
            continue
        buckets[outcome].append((date, bars, info))

    swept = sum(len(buckets[k]) for k in ("continuation", "reversal", "neutral"))
    total_days = swept + len(buckets["no_sweep"])
    if swept == 0:
        raise SystemExit("в выборке нет ни одного дня с проколом — проверь бэкфилл")

    pct = lambda k: round(100 * len(buckets[k]) / swept, 1)
    shares = {
        "reversal_pct": pct("reversal"),
        "continuation_pct": pct("continuation"),
        "neutral_pct": pct("neutral"),
    }
    ci = {
        "reversal": wilson(len(buckets["reversal"]), swept),
        "continuation": wilson(len(buckets["continuation"]), swept),
    }

    # вердикт: ключ для i18n + русский фолбэк. Текст на трёх языках — во фронте.
    overlap = not (ci["reversal"][0] > ci["continuation"][1]
                   or ci["continuation"][0] > ci["reversal"][1])
    if swept < SMALL_SAMPLE:
        verdict_key = "small_sample"
    elif overlap:
        verdict_key = "no_edge"
    elif shares["reversal_pct"] > shares["continuation_pct"]:
        verdict_key = "reversal_tilt"
    else:
        verdict_key = "continuation_tilt"

    verdict_ru = {
        "small_sample": (f"Выборки пока мало: {swept} дней с проколом. "
                         f"На таком объёме разница между {shares['reversal_pct']}% и "
                         f"{shares['continuation_pct']}% статистически неотличима от случайной — "
                         f"доверительные интервалы перекрываются. Мы публикуем то, что есть, "
                         f"и пересчитаем, когда бэкфилл вырастет."),
        "no_edge": ("Перевеса нет: доверительные интервалы двух исходов перекрываются. "
                    "Сам по себе прокол не даёт преимущества — решать должно что-то ещё."),
        "reversal_tilt": ("Перевес в сторону разворота есть, но он далёк от «всегда» "
                          "и всё равно требует проверки на своей серии сделок."),
        "continuation_tilt": ("Перевес в сторону ПРОДОЛЖЕНИЯ — то есть ровно против "
                              "популярного утверждения, что лондонский прокол обычно ложный."),
    }[verdict_key]

    # 6 дней для тренажёра: 2 разворота, 2 продолжения, 1 нейтральный, 1 без прокола.
    # Отбираем МЕДИАННЫЕ по амплитуде, а не самые эффектные: тренажёр должен учить
    # типичному дню, иначе он снова учит суеверию.
    def pick(kind, k):
        items = buckets[kind]
        if not items:
            return []
        if kind == "no_sweep":
            mid = len(items) // 2
            return [(d, b, i) for d, b, i in items[mid:mid + k]]
        items = sorted(items, key=lambda x: x[2]["amplitude"])
        mid = len(items) // 2
        lo = max(0, mid - k // 2)
        return items[lo:lo + k]

    sample = []
    for kind, k in (("reversal", 2), ("continuation", 2), ("neutral", 1), ("no_sweep", 1)):
        for date, bars, info in pick(kind, k):
            info = dict(info)
            if kind == "no_sweep":
                asia = [b for b in bars if b["ts"].hour in ASIA]
                info = {"hi": round(max(b["h"] for b in asia), 2),
                        "lo": round(min(b["l"] for b in asia), 2),
                        "dir": None, "close": round(bars[-1]["c"], 2)}
            sample.append(day_payload(date, bars, info, kind))

    stats = {
        "meta": {
            "built": datetime.date.today().isoformat(),
            "asset": ASSET, "tf": "M30",
            "rules": {"asia_utc": "00:00-06:59", "london_utc": "07:00-08:59",
                      "evaluated_at_utc": f"{US_END}:00"},
            "rules_fixed_before_counting": True,
            "first": min(days).isoformat(), "last": max(days).isoformat(),
        },
        "total_days": total_days,
        "sweep_days": swept,
        "sweep_pct": round(100 * swept / total_days, 1) if total_days else None,
        "no_sweep_days": len(buckets["no_sweep"]),
        "skipped_days": skipped,
        "counts": {k: len(v) for k, v in buckets.items()},
        **shares,
        "ci95": ci,
        "verdict_key": verdict_key,
        "verdict_ru": verdict_ru,
        "small_sample": swept < SMALL_SAMPLE,
        "sample_days": sample,
    }

    OUT_STATS.parent.mkdir(parents=True, exist_ok=True)
    OUT_STATS.write_text(json.dumps(stats, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # ── сцена §3.8: один реальный день с проколом, медианный по амплитуде
    pool = ([(d, b, i, "reversal") for d, b, i in buckets["reversal"]]
            + [(d, b, i, "continuation") for d, b, i in buckets["continuation"]])
    pool.sort(key=lambda x: x[2]["amplitude"])
    date, bars, info, outcome = pool[len(pool) // 2]
    scene = {
        "meta": {
            "symbol": ASSET, "granularity": "M30", "date": date.isoformat(),
            "range": [date.isoformat(), date.isoformat()],
            "marker_time": iso(info["sweep_ts"]),
            "marker_label": (f"{iso(info['sweep_ts'])[11:16]} UTC — цена вышла за "
                             f"{'верхнюю' if info['dir'] == 'up' else 'нижнюю'} границу "
                             f"азиатского диапазона ({info['lo']}–{info['hi']})"),
            "asia_high": info["hi"], "asia_low": info["lo"],
            "sweep_dir": info["dir"], "outcome": outcome,
            "reconstruction": False,
            "source": ("market_intel MT5 backfill (web/data/ohlc_GOLD_M30.json), реальные M30 OHLC. "
                       "День отобран как МЕДИАННЫЙ по амплитуде среди дней с проколом — "
                       "намеренно не самый эффектный."),
        },
        "candles": [{"time": iso(b["ts"]), "open": b["o"], "high": b["h"],
                     "low": b["l"], "close": b["c"]} for b in bars],
    }
    OUT_SCENE.parent.mkdir(parents=True, exist_ok=True)
    OUT_SCENE.write_text(json.dumps(scene, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"дней всего: {total_days} (пропущено неполных: {skipped})")
    print(f"с проколом: {swept} ({stats['sweep_pct']}%) · без прокола: {len(buckets['no_sweep'])}")
    print(f"  разворот    {shares['reversal_pct']}%  CI95 {ci['reversal']}")
    print(f"  продолжение {shares['continuation_pct']}%  CI95 {ci['continuation']}")
    print(f"  нейтрально  {shares['neutral_pct']}%")
    print(f"вердикт: {verdict_key} — {verdict_ru}")
    print(f"дней в тренажёре: {len(sample)} ({[d['outcome'] for d in sample]})")
    print(f"→ {OUT_STATS}")
    print(f"→ {OUT_SCENE} (день {date})")


if __name__ == "__main__":
    main()
