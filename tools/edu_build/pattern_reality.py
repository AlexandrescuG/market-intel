#!/usr/bin/env python3
"""
pattern_reality.py — глава 7 «Институциональный след», §3.5/§4.2
(SPEC_edu_level7_institutional_footprint.md).

Выгружает pattern_stats (уже посчитан живым джобом pattern_stats_job.py,
Layer2 Ф3, крон раз в неделю) в формат главы: Wilson CI95 на agree_share_5,
verdict_key для СВОДКИ (не по клетке — по всей таблице), пул по паттерну
для вывода 2 про break_retest.

Вход:  bot.db (pattern_stats)
Выход: web/data/edu_stats/pattern_reality.json + .csv

Запуск: python3 tools/edu_build/pattern_reality.py
"""
import csv
import datetime
import json
import pathlib
import sqlite3
import statistics

ROOT = pathlib.Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
OUT_JSON = WEB / "data" / "edu_stats" / "pattern_reality.json"
OUT_CSV = WEB / "data" / "edu_stats" / "pattern_reality.csv"
BOT_DB = pathlib.Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

MIN_N_SHOWN = 15
HIGHLIGHT_PATTERN = "break_retest"

DISPLAY_NAMES = {
    "ru": {
        "bearish_engulfing": "Медвежье поглощение", "bullish_engulfing": "Бычье поглощение",
        "pin_bar_top": "Пин-бар сверху", "pin_bar_bottom": "Пин-бар снизу",
        "double_top": "Двойная вершина", "double_bottom": "Двойное дно",
        "break_retest": "Пробой с ретестом",
    },
    "ro": {
        "bearish_engulfing": "Înghițire bearish", "bullish_engulfing": "Înghițire bullish",
        "pin_bar_top": "Pin-bar sus", "pin_bar_bottom": "Pin-bar jos",
        "double_top": "Vârf dublu", "double_bottom": "Fund dublu",
        "break_retest": "Spargere cu retest",
    },
    "en": {
        "bearish_engulfing": "Bearish engulfing", "bullish_engulfing": "Bullish engulfing",
        "pin_bar_top": "Pin bar top", "pin_bar_bottom": "Pin bar bottom",
        "double_top": "Double top", "double_bottom": "Double bottom",
        "break_retest": "Break and retest",
    },
}


def wilson(k, n, z=1.96):
    if not n:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    s = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5
    return [round(100 * (c - s) / d, 1), round(100 * (c + s) / d, 1)]


def main():
    con = sqlite3.connect(str(BOT_DB))
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM pattern_stats").fetchall()
    con.close()

    cells = []
    by_pattern_pool = {}  # pattern_key -> [ (agree_share_5, n), ... ] for shown cells only
    for r in rows:
        if r["agree_share_5"] is None:
            continue
        n = r["n"]
        shown = n >= MIN_N_SHOWN
        k_agree = round(r["agree_share_5"] * n)  # хиты как целое число для Уилсона
        ci = wilson(k_agree, n) if shown else [None, None]
        cells.append({
            "pattern_key": r["pattern_key"],
            "display_name_ru": DISPLAY_NAMES["ru"].get(r["pattern_key"], r["pattern_key"]),
            "display_name_ro": DISPLAY_NAMES["ro"].get(r["pattern_key"], r["pattern_key"]),
            "display_name_en": DISPLAY_NAMES["en"].get(r["pattern_key"], r["pattern_key"]),
            "symbol": r["symbol"], "tf": r["tf"], "n": n,
            "agree_5": r["agree_share_5"], "ci95": ci,
            "avg_move_5": r["avg_move_5"], "max_adverse_5": r["max_adverse_5"],
            "shown": shown,
        })
        if shown:
            by_pattern_pool.setdefault(r["pattern_key"], []).append((r["agree_share_5"], n))

    # ── Пул по паттерну (вывод 1 и 2): агрегирую все symbol/tf для паттерна,
    # взвешивая по n -- иначе редкие паттерны с сотней наблюдений на BTC H1
    # тонули бы в шуме одной строки, а не давали честную общую картину.
    pattern_pooled = {}
    for pk, obs in by_pattern_pool.items():
        total_n = sum(n for _, n in obs)
        weighted = sum(a * n for a, n in obs) / total_n if total_n else None
        pattern_pooled[pk] = {"agree_5": round(weighted, 4) if weighted is not None else None, "n": total_n}

    agree_values = [v["agree_5"] for v in pattern_pooled.values() if v["agree_5"] is not None]
    agree_min = round(min(agree_values) * 100, 1) if agree_values else None
    agree_max = round(max(agree_values) * 100, 1) if agree_values else None
    n_total = sum(v["n"] for v in pattern_pooled.values())

    # verdict_key на уровне СВОДКИ (не клетки): смотрим на разброс пулов
    # относительно 50% -- диапазон 46.8-51.3 (проверено на реальном прогоне)
    # это не "смешанно", это плотная полоса вокруг случайности.
    spread_from_50 = max(abs(v * 100 - 50) for v in agree_values) if agree_values else 0
    if spread_from_50 <= 8:
        verdict_key = "coin_flip"
    elif spread_from_50 <= 15:
        verdict_key = "weak_tilt"
    else:
        verdict_key = "mixed"

    hi = pattern_pooled.get(HIGHLIGHT_PATTERN, {"agree_5": None, "n": 0})

    # ── Вывод 3: adverse/move ratio. Считается ПО КЛЕТКЕ (adverse и move в
    # одних и тех же единицах символа), затем медиана по клеткам -- пулить
    # сырые значения по всем символам нельзя, доллары BTC и пипсы USDJPY
    # несравнимы напрямую (нашёл при первом прогоне: наивный n-взвешенный пул
    # по сырым величинам давал искажённое число, потому что крупные абсолютные
    # значения BTC/ETH задавливали остальные символы).
    ratios = [c["max_adverse_5"] / c["avg_move_5"] for c in cells
              if c["shown"] and c["avg_move_5"]]
    adverse_ratio = round(statistics.median(ratios), 3) if ratios else None

    payload = {
        "_meta": {
            "built": datetime.date.today().isoformat(),
            "tfs": ["H1", "H4", "D1"],
            "n_total": n_total, "min_n_shown": MIN_N_SHOWN,
            "lookahead_fix_note_ru": "double_top/double_bottom считаются от подтверждения фрактала (confirm_idx = пик + FRACTAL_CONFIRM свечей), а не от самого пика — иначе agree_share на этих двух паттернах выходил ~70-77% вместо честных ~45-54%, потому что часть будущего уже была заложена в момент детекции.",
        },
        "cells": cells,
        "pattern_pooled": {pk: v for pk, v in pattern_pooled.items()},
        "summary": {
            "agree_min": agree_min, "agree_max": agree_max, "n_total": n_total,
            "verdict_key": verdict_key,
            "adverse_move_ratio": adverse_ratio,
            "highlight": {"pattern_key": HIGHLIGHT_PATTERN,
                          "agree_5": round(hi["agree_5"] * 100, 1) if hi["agree_5"] is not None else None,
                          "n": hi["n"]},
        },
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["pattern_key", "symbol", "tf", "n", "agree_share_5", "ci95_low", "ci95_high", "avg_move_5", "max_adverse_5", "shown"])
        for c in cells:
            w.writerow([c["pattern_key"], c["symbol"], c["tf"], c["n"], c["agree_5"],
                        c["ci95"][0], c["ci95"][1], c["avg_move_5"], c["max_adverse_5"], c["shown"]])

    print(f"клеток: {len(cells)}, показано (n>={MIN_N_SHOWN}): {sum(1 for c in cells if c['shown'])}")
    print(f"диапазон согласованности по паттернам (пул): {agree_min}%–{agree_max}%, n_total={n_total}, verdict={verdict_key}")
    print(f"break_retest (highlight): {payload['summary']['highlight']}")
    print(f"→ {OUT_JSON}\n→ {OUT_CSV}")


if __name__ == "__main__":
    main()
