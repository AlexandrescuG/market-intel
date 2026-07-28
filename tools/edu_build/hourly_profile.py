#!/usr/bin/env python3
"""
Почасовой профиль волатильности по нашему бэкфиллу MT5 — глава 5 «Глобальные Часы».

Вход:  web/data/ohlc_{ASSET}_M30.json   (формат {"candles":[{time,open,high,low,close}, ...]},
                                         time — unix seconds UTC)
Выход: web/data/edu_stats/hourly_profile.json
       web/data/edu_stats/hourly_profile.csv   (для кнопки «Скачать наши числа»)

Все числа блока §3.4 главы 5 берутся отсюда. Руками в тексте главы чисел нет.

──────────────────────────────────────────────────────────────────────────────
ОТКЛОНЕНИЕ ОТ СПЕКИ, найденное при разведке (SPEC_edu_level5_global_clocks.md §3.4)
──────────────────────────────────────────────────────────────────────────────
Спека говорит: «двенадцать инструментов, получасовые бары с 2018 года, 88.9 МБ»
и просит тепловую карту 24×N, где N — годы 2018…2026.

Проверено по файлам: бэкфилл M30 покрывает примерно 2026-05-13 → 2026-07-25.
GOLD — 4468 баров, EURUSD — 5640, BTC — 5622. Восьми лет истории на диске нет,
есть около десяти недель. Тот же паттерн, что в build_ch4_nfp_gap.py: спеку
проверяем, а не выполняем вслепую.

Что из этого следует и как это здесь решено:

1. Ось «годы» заменена на АВТОМАТИЧЕСКИЙ выбор периода (см. bucket_of):
   ≥ 2 полных года данных → карта по годам (как в спеке);
   иначе                  → карта по календарным месяцам.
   Когда бэкфилл дорастёт, скрипт сам переключится, править ничего не нужно.

2. В JSON пишется блок coverage (первая/последняя дата, число дней, баров,
   периодов) и список warnings. Фронт ОБЯЗАН отрисовать coverage в честной
   плашке под тепловой картой. Это прямое требование §8: «ни одного числа,
   написанного руками» работает только вместе с «объём выборки на виду».

3. Утверждение спеки «закономерность держится 8 из 8 лет» на текущих данных
   недоказуемо. Скрипт считает years_consistent/years_total по фактическим
   периодам и выставляет warning "short_history". Текст главы должен читать
   это поле, а не утверждать устойчивость по годам.
──────────────────────────────────────────────────────────────────────────────

Запуск:  python3 tools/edu_build/hourly_profile.py
"""
import collections
import csv
import datetime
import json
import pathlib
import random
import statistics

ROOT = pathlib.Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
OUT = WEB / "data" / "edu_stats"

# Порядок важен: первый инструмент — дефолтный в UI главы.
ASSETS = ["GOLD", "EURUSD", "USDJPY", "BTC", "SPX", "WTI"]

MIN_BARS_PER_CELL = 30      # клетка карты не показывается при меньшей выборке
MIN_BARS_PER_SUBSET = 20    # то же для разрезов (пятница / день NFP)
YEARS_FOR_YEAR_BUCKETS = 2  # с какого объёма истории переходим на разбивку по годам


# ─────────────────────────────────────────────────────────────── загрузка

def load(asset, tf="M30"):
    """Терпимый загрузчик: {"candles":[...]} | {"bars":[...]} | [[t,o,h,l,c], ...]."""
    p = WEB / "data" / f"ohlc_{asset}_{tf}.json"
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("candles") or raw.get("bars") or raw.get("data") or []
    out = []
    for b in raw:
        if isinstance(b, dict):
            t = b.get("time", b.get("t", b.get("date")))
            h = b.get("high", b.get("h"))
            l = b.get("low", b.get("l"))
        else:
            t, h, l = b[0], b[2], b[3]
        if t is None or h is None or l is None:
            continue
        if isinstance(t, (int, float)):
            ts = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).replace(tzinfo=None)
        else:
            ts = datetime.datetime.fromisoformat(str(t).replace("Z", ""))
        out.append((ts, float(h), float(l)))
    out.sort(key=lambda x: x[0])
    return out


# ─────────────────────────────────────────────────────────── разбиение оси

def bucket_mode(bars):
    """'year' если истории хватает, иначе 'month'. Решение принимается по данным."""
    if not bars:
        return "month"
    span_days = (bars[-1][0] - bars[0][0]).days
    return "year" if span_days >= YEARS_FOR_YEAR_BUCKETS * 365 else "month"


def bucket_of(ts, mode):
    return str(ts.year) if mode == "year" else f"{ts.year}-{ts.month:02d}"


# ─────────────────────────────────────────────────────────────── профиль

def profile(bars, mode):
    """cells[period][hour] = {median_pts, share_of_day, n}

    share_of_day = медиана диапазона бара / медианный ДНЕВНОЙ диапазон того же
    периода. Нормировка обязательна: золото по 2000 и по 3500 даёт несравнимые
    абсолютные пункты, а доля сравнима.
    """
    by_cell = collections.defaultdict(list)
    day_hi_lo = collections.defaultdict(lambda: collections.defaultdict(lambda: [None, None]))

    for ts, h, l in bars:
        per = bucket_of(ts, mode)
        by_cell[(per, ts.hour)].append(h - l)
        d = day_hi_lo[per][ts.date()]
        d[0] = h if d[0] is None else max(d[0], h)
        d[1] = l if d[1] is None else min(d[1], l)

    norm = {}
    for per, days in day_hi_lo.items():
        rngs = [hi - lo for hi, lo in days.values() if hi is not None and lo is not None]
        norm[per] = statistics.median(rngs) if rngs else 1.0

    cells = collections.defaultdict(dict)
    for (per, hh), vals in by_cell.items():
        if len(vals) < MIN_BARS_PER_CELL:
            continue
        med = statistics.median(vals)
        cells[per][hh] = {
            "median_pts": round(med, 5),
            "share_of_day": round(med / norm[per], 4) if norm[per] else None,
            "n": len(vals),
        }
    return dict(cells), norm, day_hi_lo


def day_peak_shares(bars, peak_hour):
    """На каждый календарный день: доля бара в peak_hour от полного дневного
    диапазона (High-Low) этого же дня. Нужна как ряд НЕЗАВИСИМЫХ по дням
    наблюдений для перестановочного теста ниже -- агрегированная по часу
    медиана (как в profile()) для этого не годится, там дни уже смешаны.
    """
    day_range = collections.defaultdict(lambda: [None, None])
    day_peak_bar = {}
    for ts, h, l in bars:
        d = ts.date()
        r = day_range[d]
        r[0] = h if r[0] is None else max(r[0], h)
        r[1] = l if r[1] is None else min(r[1], l)
        if ts.hour == peak_hour:
            day_peak_bar[d] = h - l
    out = {}
    for d, (hi, lo) in day_range.items():
        rng = (hi - lo) if (hi is not None and lo is not None) else None
        if rng and d in day_peak_bar:
            out[d] = day_peak_bar[d] / rng
    return out


def permutation_verdict(a, b, iterations=3000, seed=42):
    """Честный непараметрический тест на разницу медиан двух независимых
    выборок (Пятница/NFP vs Обычный день), без scipy: перемешиваем объединённый
    пул, пересчитываем разницу медиан iterations раз, p = доля перестановок
    с |diff| >= наблюдаемой. При n=2 (день NFP) тест валиден, но почти не
    имеет мощности -- корректно вернёт "незначимо", а не выдуманную уверенность.
    """
    if len(a) < 2 or len(b) < 2:
        return {"n_a": len(a), "n_b": len(b), "delta": None, "p_value": None, "significant": False}
    observed = statistics.median(a) - statistics.median(b)
    pool = list(a) + list(b)
    na = len(a)
    rng = random.Random(seed)
    extreme = 0
    for _ in range(iterations):
        rng.shuffle(pool)
        da = statistics.median(pool[:na]) - statistics.median(pool[na:])
        if abs(da) >= abs(observed):
            extreme += 1
    p = extreme / iterations
    return {"n_a": na, "n_b": len(b), "delta": round(observed, 4), "p_value": round(p, 4), "significant": p < 0.05}


def subsets(bars, peak_hour):
    """Разрезы: пятница · первая пятница месяца (прокси дня NFP) · обычные дни.
    Плюс перестановочный вердикт "отличается ли разрез от обычного дня в
    globalном пиковом часе" -- нужен заголовкам блока (§3.1 спеки: заголовок
    не должен утверждать больше, чем показывает выборка).
    """
    def prof(sel):
        acc = collections.defaultdict(list)
        for ts, h, l in bars:
            if sel(ts):
                acc[ts.hour].append(h - l)
        return {hh: round(statistics.median(v), 5)
                for hh, v in acc.items() if len(v) >= MIN_BARS_PER_SUBSET}

    def counts(sel):
        return len({ts.date() for ts, _, _ in bars if sel(ts)})

    is_nfp = lambda d: d.weekday() == 4 and d.day <= 7
    is_fri = lambda d: d.weekday() == 4
    is_reg = lambda d: (not is_nfp(d)) and d.weekday() < 4

    is_nfp_ts = lambda ts: is_nfp(ts.date()) if hasattr(ts, "date") else is_nfp(ts)
    is_fri_ts = lambda ts: is_fri(ts.date()) if hasattr(ts, "date") else is_fri(ts)
    is_reg_ts = lambda ts: is_reg(ts.date()) if hasattr(ts, "date") else is_reg(ts)

    day_shares = day_peak_shares(bars, peak_hour)
    fri_vals = [v for d, v in day_shares.items() if is_fri(d)]
    nfp_vals = [v for d, v in day_shares.items() if is_nfp(d)]
    reg_vals = [v for d, v in day_shares.items() if is_reg(d)]

    return {
        "friday": {"profile": prof(is_fri_ts), "n_days": counts(is_fri_ts),
                   "vs_regular": permutation_verdict(fri_vals, reg_vals)},
        "nfp_day": {"profile": prof(is_nfp_ts), "n_days": counts(is_nfp_ts),
                    "vs_regular": permutation_verdict(nfp_vals, reg_vals)},
        "regular_day": {"profile": prof(is_reg_ts), "n_days": counts(is_reg_ts)},
    }


def analyse(asset, bars):
    mode = bucket_mode(bars)
    cells, _, day_hi_lo = profile(bars, mode)
    if not cells:
        return None

    pooled = collections.defaultdict(list)
    for per, hours in cells.items():
        for hh, v in hours.items():
            if v["share_of_day"] is not None:
                pooled[hh].append(v["share_of_day"])
    avg = {hh: round(statistics.mean(v), 4) for hh, v in pooled.items()}
    if not avg:
        return None

    peak = max(avg, key=avg.get)
    trough = min(avg, key=avg.get)

    # устойчивость: в скольких периодах локальный пик попал в ±2 часа от общего
    consistent = 0
    for per, hours in cells.items():
        if not hours:
            continue
        local_peak = max(hours, key=lambda h: hours[h]["share_of_day"] or 0)
        if min(abs(local_peak - peak), 24 - abs(local_peak - peak)) <= 2:
            consistent += 1

    n_days = sum(len(d) for d in day_hi_lo.values())
    first, last = bars[0][0], bars[-1][0]

    warnings = []
    if mode == "month":
        warnings.append("short_history")            # истории < 2 лет, ось = месяцы
    if len(cells) < 3:
        warnings.append("few_periods")              # устойчивость почти не проверяема
    if n_days < 250:
        warnings.append("under_one_year")

    return {
        "bucket": mode,
        "by_period": cells,
        "avg_share": avg,
        "subsets": subsets(bars, peak),
        "peak_hour": peak,
        "trough_hour": trough,
        "peak_share": round(avg[peak] * 100, 1),
        "trough_share": round(avg[trough] * 100, 1),
        "peak_ratio": round(avg[peak] / avg[trough], 1) if avg[trough] else None,
        "periods_consistent": consistent,
        "periods_total": len(cells),
        # алиасы под плейсхолдеры спеки {{years_consistent}} / {{years_total}}
        "years_consistent": consistent,
        "years_total": len(cells),
        "coverage": {
            "first": first.strftime("%Y-%m-%d"),
            "last": last.strftime("%Y-%m-%d"),
            "n_days": n_days,
            "n_bars": len(bars),
            "n_periods": len(cells),
            "span_days": (last - first).days,
        },
        "warnings": warnings,
        "total_bars": len(bars),
    }


# ─────────────────────────────────────────────────────────────────── main

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {}
    rows = [["asset", "period", "hour_utc", "median_range", "share_of_day", "n"]]

    for a in ASSETS:
        bars = load(a)
        if not bars:
            print(f"  ! {a}: данных нет, пропускаю")
            continue
        res = analyse(a, bars)
        if not res:
            print(f"  ! {a}: выборка меньше порога ({len(bars)} баров), пропускаю")
            continue
        for per, hours in res["by_period"].items():
            for hh, v in hours.items():
                rows.append([a, per, hh, v["median_pts"], v["share_of_day"], v["n"]])
        payload[a] = res
        print(f"  ✓ {a}: пик {res['peak_hour']}:00 UTC ({res['peak_share']}%), "
              f"тихо {res['trough_hour']}:00 UTC ({res['trough_share']}%), "
              f"×{res['peak_ratio']}, устойчиво {res['periods_consistent']}/{res['periods_total']} "
              f"[{res['bucket']}] · {res['coverage']['first']}→{res['coverage']['last']}"
              + (f" · warnings: {','.join(res['warnings'])}" if res["warnings"] else ""))

    if not payload:
        raise SystemExit("нечего писать: ни одного инструмента с достаточной выборкой")

    spans = [v["coverage"] for v in payload.values()]
    payload["_meta"] = {
        "built": datetime.date.today().isoformat(),
        "tf": "M30",
        "metric": "медиана диапазона (High−Low) бара M30, нормировка на медианный дневной диапазон периода",
        "not_measured": "объём и спред — в спотовом форексе единого объёма нет, история спреда в OHLC не хранится",
        "coverage_first": min(s["first"] for s in spans),
        "coverage_last": max(s["last"] for s in spans),
        "assets": [a for a in payload if a != "_meta"],
    }

    (OUT / "hourly_profile.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    with (OUT / "hourly_profile.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)

    print(f"→ {OUT / 'hourly_profile.json'}")
    print(f"→ {OUT / 'hourly_profile.csv'} ({len(rows) - 1} строк)")


if __name__ == "__main__":
    main()
