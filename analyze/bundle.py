#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/bundle.py — WP4.1 SPEC_alpha_engine_wp4_continuous_cycle.md.

Единственный источник того, что видит модель. Секции по убыванию важности
(режется снизу при переполнении BUNDLE_CHAR_LIMIT): gaps -> focus ->
calendar -> news -> macro -> watch -> calibration.

§0 спеки: "скрипты не дают ошибки" — каждый под-шаг обёрнут в _step(),
провал пишется в gaps, никогда не бросается наверх. now_ts — явный
параметр (не datetime.now() внутри) — иначе Acceptance "два прогона на
неизменных данных дают идентичный пакет" непроверяем.

Не пересчитывает то, что уже посчитал gate.py для per_symbol (state,
candidates, move_atr) — берёт готовое.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze.calibration_report import build_report as _calibration_build_report
from analyze.forecast_journal import init_schema as _init_forecast_schema
from core.config import DB_PATH as _SIGNALS_DB
from core.event_types import normalize_event_type

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
_MACRO_JSON = Path(__file__).parent.parent / "web" / "data" / "macro.json"
_REGIME_JSON = Path(__file__).parent.parent / "web" / "data" / "regime.json"
_CYCLE_DIR = Path(__file__).parent.parent / "data" / "cycle"

CYCLE_HORIZON_SEC = 5 * 3600  # частота цикла (WP4.6: 5 прогонов/сутки)
BUNDLE_CHAR_LIMIT = 25_000  # [ДОПУЩЕНИЕ] ~2.5 симв/токен для русского; калибровать по реальному usage
NEWS_MAX_ITEMS = 20


def _step(name: str, fn, *args, **kwargs) -> dict:
    """§0: контракт {"ok","data","error","degraded"} — fn НИКОГДА не должна
    уронить весь build_bundle, даже если сама fn не позаботилась об этом."""
    try:
        return {"ok": True, "data": fn(*args, **kwargs), "error": None, "degraded": False}
    except Exception as e:
        return {"ok": False, "data": None, "error": f"{name}: {type(e).__name__}: {e}", "degraded": True}


def _focus_section(gate_result: dict) -> dict:
    """Берёт ГОТОВОЕ из gate.decide() -- state_vector + candidates + base_rate
    по каждому gated (symbol,tf). Не пересчитывает. Ключ -- составной
    "symbol:tf" (один символ может пройти гейт на нескольких ТФ
    одновременно), но symbol/tf также явно дублируются полями внутри --
    модель должна вернуть tf в своём ответе (см. agent_run.py), не
    восстанавливать его разбором ключа."""
    out = {}
    for key in gate_result["gated"]:
        per = gate_result["per_symbol"].get(key, {})
        if not per.get("ok"):
            continue
        symbol, tf = key.rsplit(":", 1)
        out[key] = {"symbol": symbol, "tf": tf, "state": per["state"], "candidates": per["candidates"]}
    return out


def _calendar_section(con: sqlite3.Connection, universe: list[str], now_ts: int, horizon_sec: int) -> list[dict]:
    rows = con.execute(
        "SELECT country, title, indicator, scheduled_ts FROM econ_events "
        "WHERE impact='high' AND scheduled_ts BETWEEN ? AND ? AND first_seen IS NOT NULL "
        "ORDER BY scheduled_ts ASC",
        (now_ts, now_ts + horizon_sec),
    ).fetchall()
    out = []
    for country, title, indicator, scheduled_ts in rows:
        event_type = normalize_event_type(indicator or title)
        countries = con.execute(
            "SELECT symbol FROM event_instrument_map WHERE country=? AND weight>=1", (country,)
        ).fetchall()
        relevant = [s[0] for s in countries if s[0] in universe]
        if not relevant:
            continue
        reactions = {}
        for sym in relevant:
            r = con.execute(
                "SELECT n, avg_move_30m, baseline_ratio_30m FROM event_reaction_stats "
                "WHERE event_type=? AND symbol=?", (event_type, sym),
            ).fetchone()
            if r:
                reactions[sym] = {"n": r[0], "avg_move_30m": r[1], "baseline_ratio_30m": r[2]}
        out.append({"title": title, "event_type": event_type, "country": country,
                     "scheduled_ts": scheduled_ts, "reactions": reactions})
    return out


def _news_section(universe: list[str], hours: int = 6, max_items: int = NEWS_MAX_ITEMS) -> list[dict]:
    """Симметрично tools/agent/q_news.py, но по ВСЕМ focus-символам разом,
    отбор по importance (WP4.1: "отобранные по importance, максимум 20")."""
    con = sqlite3.connect(str(_SIGNALS_DB), timeout=5)
    con.execute("PRAGMA query_only = ON")
    try:
        sql_prefilter = (datetime.now(timezone.utc) - timedelta(hours=max(hours, 24))).isoformat()
        placeholders = ",".join("?" for _ in universe)
        rows = con.execute(
            f"""SELECT s.title, s.url, s.first_seen, s.importance, t.symbol FROM news_instrument_tags t
                JOIN signals s ON s.uid = t.news_uid
                WHERE t.symbol IN ({placeholders}) AND s.last_seen >= ?
                ORDER BY s.importance DESC, s.first_seen DESC LIMIT ?""",
            (*universe, sql_prefilter, max_items * 3),
        ).fetchall()
    finally:
        con.close()
    cutoff_ts = datetime.now(timezone.utc).timestamp() - hours * 3600
    out = []
    seen_titles = set()
    for title, url, first_seen, importance, symbol in rows:
        try:
            ts = datetime.fromisoformat(first_seen).timestamp()
        except (ValueError, TypeError):
            continue
        if ts < cutoff_ts or title in seen_titles:
            continue
        seen_titles.add(title)
        out.append({"title": title, "url": url, "ts": int(ts), "importance": importance, "symbol": symbol})
        if len(out) >= max_items:
            break
    return out


def _macro_section() -> dict:
    """Читает уже готовый кэш (web/data/macro.json) -- не пересчитывает,
    не дёргает FRED напрямую (сетевой вызов внутри build_bundle нарушил бы §0)."""
    if not _MACRO_JSON.exists():
        return {}
    d = json.loads(_MACRO_JSON.read_text())
    return {k: v for k, v in d.items() if k != "_updated"}


def _watch_section(gate_result: dict, universe: list[str], tfs: tuple[str, ...]) -> list[dict]:
    out = []
    for sym in universe:
        for tf in tfs:
            key = f"{sym}:{tf}"
            if key in gate_result["gated"]:
                continue
            per = gate_result["per_symbol"].get(key, {})
            if not per.get("ok"):
                out.append({"symbol": sym, "tf": tf, "note": "нет данных"})
                continue
            bd = per.get("breakdown", {})
            out.append({"symbol": sym, "tf": tf, "move_atr": bd.get("move_atr"), "score": per.get("score")})
    return out


def _render_md(bundle: dict) -> str:
    lines = [f"# Bundle {bundle['generated_at_iso']}", ""]
    lines.append("## gaps")
    if bundle["gaps"]:
        for g in bundle["gaps"]:
            lines.append(f"- {g}")
    else:
        lines.append("- (нет)")
    lines.append("")
    lines.append("## focus")
    if bundle["focus"]:
        for f in bundle["focus"].values():
            lines.append(f"### {f['symbol']} {f['tf']}")
            lines.append(f"вектор состояния: {json.dumps(f['state'], ensure_ascii=False)}")
            for c in f["candidates"]:
                lines.append(f"- кандидат {c['pattern_key']} {c['direction']} config={c['config_key']} "
                              f"tf={f['tf']}: base_rate={json.dumps(c['base_rate'], ensure_ascii=False)}")
    else:
        lines.append("(гейт никого не пропустил)")
    lines.append("")
    lines.append("## calendar")
    for ev in bundle["calendar"]:
        lines.append(f"- {ev['title']} ({ev['country']}, ts={ev['scheduled_ts']}): reactions={ev['reactions']}")
    if not bundle["calendar"]:
        lines.append("(нет high-impact релизов в горизонте цикла)")
    lines.append("")
    lines.append("## news")
    for n in bundle["news"]:
        lines.append(f"- [{n['symbol']}] {n['title']} ({n['url']})")
    if not bundle["news"]:
        lines.append("(нет свежих заголовков по focus-инструментам)")
    lines.append("")
    lines.append("## macro")
    for k, v in bundle["macro"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## watch")
    for w in bundle["watch"]:
        lines.append(f"- {w}")
    lines.append("")
    lines.append("## calibration")
    lines.append(json.dumps(bundle["calibration"], ensure_ascii=False))
    return "\n".join(lines)


def _truncate(bundle: dict, char_limit: int) -> tuple[dict, list[str]]:
    """Режет секции 3-7 (calendar/news/macro/watch/calibration) снизу при
    переполнении -- gaps/focus (1-2) никогда не трогаются."""
    notes = []
    order = ["watch", "macro", "news", "calendar"]  # режем в этом порядке -- watch первым
    for key in order:
        rendered = _render_md(bundle)
        if len(rendered) <= char_limit:
            break
        section = bundle.get(key)
        if isinstance(section, list) and section:
            removed = len(section) - max(0, len(section) // 2)
            notes.append(f"секция {key} усечена, показано {len(section) - removed} из {len(section)}")
            bundle[key] = section[: len(section) - removed] if removed < len(section) else []
        elif isinstance(section, dict) and section:
            keys = list(section.keys())
            half = keys[: len(keys) // 2]
            notes.append(f"секция {key} усечена, показано {len(half)} из {len(keys)}")
            bundle[key] = {k: section[k] for k in half}
    return bundle, notes


def build_bundle(con: sqlite3.Connection, gate_result: dict, universe: list[str], now_ts: int,
                  tfs: tuple[str, ...] = ("D1", "H4", "H1")) -> dict:
    _init_forecast_schema(con)  # calibration-секция читает forecasts/forecast_outcomes
    generated_at_iso = datetime.fromtimestamp(now_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    steps = {
        "focus": _step("focus", _focus_section, gate_result),
        "calendar": _step("calendar", _calendar_section, con, universe, now_ts, CYCLE_HORIZON_SEC),
        "news": _step("news", _news_section, universe),
        "macro": _step("macro", _macro_section),
        "watch": _step("watch", _watch_section, gate_result, universe, tfs),
        "calibration": _step("calibration", _calibration_build_report, con, "barrier", None),
    }

    gaps = [f"{name}: {r['error']}" for name, r in steps.items() if not r["ok"]]
    for key, per in gate_result["per_symbol"].items():
        if not per.get("ok"):
            gaps.append(f"{key}: {per.get('error', 'нет данных')}")

    bundle = {
        "generated_at_iso": generated_at_iso, "generated_at_ts": now_ts,
        "gaps": gaps,
        "focus": steps["focus"]["data"] or {},
        "calendar": steps["calendar"]["data"] or [],
        "news": steps["news"]["data"] or [],
        "macro": steps["macro"]["data"] or {},
        "watch": steps["watch"]["data"] or [],
        "calibration": steps["calibration"]["data"] or {},
    }
    bundle, trunc_notes = _truncate(bundle, BUNDLE_CHAR_LIMIT)
    bundle["gaps"].extend(trunc_notes)

    md = _render_md(bundle)
    return {"json": bundle, "md": md, "meta": {"bundle_chars": len(md), "truncated": trunc_notes}}


def write_bundle(result: dict, now_ts: int) -> tuple[Path, Path]:
    _CYCLE_DIR.mkdir(parents=True, exist_ok=True)
    iso = datetime.fromtimestamp(now_ts, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = _CYCLE_DIR / f"bundle_{iso}.json"
    md_path = _CYCLE_DIR / f"bundle_{iso}.md"
    json_path.write_text(json.dumps(result["json"], ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(result["md"], encoding="utf-8")
    return json_path, md_path


def main() -> None:
    import argparse
    import time
    from analyze import gate as _gate

    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", nargs="+", default=["GOLD", "EURUSD", "USDJPY", "USDCNY", "USDZAR"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(str(_BOT_DB))
    now_ts = int(time.time())
    gate_result = _gate.decide(con, args.universe, now_ts)
    result = build_bundle(con, gate_result, args.universe, now_ts)
    print(f"bundle_chars={result['meta']['bundle_chars']} truncated={result['meta']['truncated']}")
    print(f"gaps: {result['json']['gaps']}")
    if args.dry_run:
        print("\n=== MD ===")
        print(result["md"])
        con.rollback()
    else:
        json_path, md_path = write_bundle(result, now_ts)
        print(f"written: {json_path}, {md_path}")
    con.close()


if __name__ == "__main__":
    main()
