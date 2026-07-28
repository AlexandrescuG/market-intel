#!/usr/bin/env python3
"""
build_ch6_release_day.py — глава 6, cold open «Все знали дату. Никто не знал
числа.» (§3.0 SPEC_edu_level6_news_pulse.md).

Берёт реальный день с релизом высокой важности из surprise_reaction.json
(sim_releases уже содержит реальные свечи вокруг релиза — переиспользуем тот
же отбор, не считаем заново), выбирает МЕДИАННЫЙ по величине реакции среди
релизов высокой важности (не самый громкий — см. §3.0 примечание спеки).

Вход:  web/data/edu_stats/surprise_reaction.json (уже посчитан surprise_reaction.py)
       + bot.db (price_bars, для полных суток вокруг релиза — sim_releases
         хранит только ±1..2 часа, здесь нужны полные сутки для ленты cold open)
Выход: web/data/edu_scenes/ch6_release_day.json

Запуск: python3 tools/edu_build/build_ch6_release_day.py
"""
import datetime
import json
import pathlib
import sqlite3
import statistics

ROOT = pathlib.Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
STATS_IN = WEB / "data" / "edu_stats" / "surprise_reaction.json"
OUT = WEB / "data" / "edu_scenes" / "ch6_release_day.json"
BOT_DB = pathlib.Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

QUIET_HOURS = range(0, 8)  # первая треть суток, как в build_ch5_coldopen_day.py


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    stats = json.loads(STATS_IN.read_text(encoding="utf-8"))
    # high-impact GOLD точки из scatter (импакт не хранится в scatter напрямую --
    # используем by_impact для честности, но для отбора конкретного дня берём
    # тот же пул кандидатов, что собрал surprise_reaction.py для симулятора:
    # это уже отфильтрованные высокоимпактные релизы (см. sim_releases logic).
    candidates = [s for s in stats["sim_releases"] if s["kind"] in ("big_positive", "big_negative")]
    if not candidates:
        raise SystemExit("нет кандидатов high-impact в surprise_reaction.json — прогнать surprise_reaction.py заново")

    moves = sorted(candidates, key=lambda c: abs(c["actual_move_30m"]))
    chosen = moves[len(moves) // 2]  # медианный по величине реакции, не самый громкий

    release_ts = None
    # release_ts был удалён из sim_releases при сериализации -- вычислим заново
    # по дате из candles: первая свеча минус смещение до начала окна ±1ч в
    # surprise_reaction.py. Проще и надёжнее: найти release_ts напрямую в БД
    # по event_key + дате.
    con = sqlite3.connect(str(BOT_DB))
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT scheduled_ts, title, country FROM econ_events WHERE event_key=? AND actual=? ORDER BY scheduled_ts LIMIT 1",
        (chosen["event_key"], str(chosen["actual"]) if chosen["actual"] != int(chosen["actual"]) else str(int(chosen["actual"]))),
    ).fetchone()
    if row is None:
        # fallback: любой scheduled_ts для этого event_key в тот день
        day_guess = datetime.datetime.strptime(chosen["date"], "%Y-%m-%d")
        lo = int(day_guess.replace(tzinfo=datetime.timezone.utc).timestamp())
        hi = lo + 86400
        row = con.execute(
            "SELECT scheduled_ts, title, country FROM econ_events WHERE event_key=? AND scheduled_ts BETWEEN ? AND ? LIMIT 1",
            (chosen["event_key"], lo, hi),
        ).fetchone()
    release_ts = row["scheduled_ts"]
    event_title = row["title"] or chosen["event_key"]
    event_country = row["country"] or ""

    day_start = (release_ts // 86400) * 86400
    day_end = day_start + 86400

    rows = con.execute(
        "SELECT ts,o,h,l,c FROM price_bars WHERE symbol='XAUUSD' AND tf='30m' AND ts BETWEEN ? AND ? ORDER BY ts",
        (day_start, day_end),
    ).fetchall()
    con.close()

    if len(rows) < 40:
        raise SystemExit(f"неполные сутки для release_ts={release_ts} ({len(rows)} баров) -- выбрать другой день вручную")

    candles = [{"time": iso(r["ts"]), "open": r["o"], "high": r["h"], "low": r["l"], "close": r["c"]} for r in rows]
    quiet = [r for r in rows if datetime.datetime.fromtimestamp(r["ts"], datetime.timezone.utc).hour in QUIET_HOURS]
    # Средний диапазон ОДНОГО бара в тихие часы -- сравнение "этот бар в X раз
    # больше типичного тихого бара", а не "больше N часов вместе": сумма или
    # общий high-low за 8 часов почти всегда больше одного 30-мин бара просто
    # за счёт дрейфа по многим барам -- не то сравнение, которое несёт мысль
    # cold open. Отношение (не сумма) работает честно на любой реально
    # выбранный день, не только на специально подобранный.
    quiet_avg_bar = statistics.mean(r["h"] - r["l"] for r in quiet) if quiet else None
    release_bar = min(rows, key=lambda r: abs(r["ts"] - release_ts))
    release_bar_range = release_bar["h"] - release_bar["l"]
    peak_vs_quiet = round(release_bar_range / quiet_avg_bar, 2) if quiet_avg_bar else None

    out = {
        "meta": {
            "symbol": "GOLD", "granularity": "M30",
            "date": datetime.datetime.fromtimestamp(day_start, datetime.timezone.utc).strftime("%Y-%m-%d"),
            "range": [datetime.datetime.fromtimestamp(day_start, datetime.timezone.utc).strftime("%Y-%m-%d")] * 2,
            "marker_time": iso(release_bar["ts"]),
            # SPEC_ch6_debug.md §5: раньше здесь стоял event_key -- внутренний
            # хеш из БД, ничего не говорящий читателю ("3e12899063bcbe7c0bbe").
            # Теперь -- название события и страна; хеш переехал в event_key
            # отдельным полем (для data-event-key в разметке, не на экран).
            "marker_label": f"{event_country + ' · ' if event_country else ''}{event_title}",
            "marker_event_key": chosen["event_key"],
            "surprise_sigma": chosen["surprise_sigma"],
            "release_bar_range": round(release_bar_range, 2),
            "quiet_hours": len(QUIET_HOURS),
            "quiet_avg_bar_range": round(quiet_avg_bar, 2) if quiet_avg_bar else None,
            "peak_vs_quiet": peak_vs_quiet,
            "reconstruction": False,
            "selection": "median_reaction_high_impact",
            "selection_note_ru": "Релиз выбран как типичный по силе реакции среди релизов высокой важности, а не как рекордный.",
            "selection_note_ro": "Publicația a fost aleasă ca tipică după forța reacției printre publicațiile de impact mare, nu ca record.",
            "selection_note_en": "The release was picked as typical by reaction strength among high-impact releases — deliberately not the loudest.",
            "source": "market_intel MT5 backfill (price_bars, XAUUSD M30) + econ_events/event_reactions (bot.db).",
        },
        "candles": candles,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"день {out['meta']['date']}: релиз {chosen['event_key']} ({chosen['surprise_sigma']}σ), "
          f"бар релиза {release_bar_range:.2f}, средний тихий бар {quiet_avg_bar:.2f}, "
          f"peak_vs_quiet={peak_vs_quiet}" if quiet_avg_bar else "")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
