"""Сборка дневного брифа (06:00). Читает сигналы за окно, агрегирует, пишет
структурный markdown, который потом читает claude -p.

Бриф НЕ анализирует — он только раскладывает факты так, чтобы LLM было удобно:
  - топ-сигналы по трём измерениям (экономика / геополитика / толпа)
  - повестка СМИ (что чаще всего гонят ленты)
  - тепловая карта тикеров (что обсуждают трейдеры)
  - «на что реагируют сильнее всего» (по engagement)
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from core import db
from core.config import BRIEFS_DIR
from collectors.rss import media_agenda


def _fmt_signal(s: dict, idx: int) -> str:
    eng = f" · 👁 {s['engagement']:,}" if s["engagement"] else ""
    rep = f" · 💬 {s['replies']:,}" if s["replies"] else ""
    tags = json.loads(s["cashtags"] or "[]")
    tagstr = f" · {' '.join('$' + t for t in tags)}" if tags else ""
    head = (s["title"] or s["text"] or "").replace("\n", " ").strip()[:240]
    src = s["source"]
    who = f"@{s['author']}" if src == "twitter" else s["author"]
    return (f"{idx}. [{src}] {who} · imp={s['importance']:.2f} "
            f"· econ={s['econ_relevance']:.2f} · crowd={s['crowd_intensity']:.2f}"
            f"{eng}{rep}{tagstr}\n"
            f"   {head}\n   {s['url']}")


def _section(title: str, dimension: str, hours: int, limit: int) -> str:
    rows = db.top_by_dimension(hours, dimension, limit)
    if not rows:
        return f"## {title}\n_(нет сигналов за окно)_\n"
    body = "\n".join(_fmt_signal(s, i + 1) for i, s in enumerate(rows))
    return f"## {title}  ({len(rows)} сигналов)\n{body}\n"


def build(hours: int = 24) -> Path:
    db.init_db()
    all_signals = db.recent_since(hours)
    by_source = {}
    for s in all_signals:
        by_source[s["source"]] = by_source.get(s["source"], 0) + 1

    parts: list[str] = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parts.append(f"# RAW BRIEF · {today} · окно {hours}ч")
    parts.append(f"Всего сигналов: {len(all_signals)} "
                 f"({', '.join(f'{k}={v}' for k, v in sorted(by_source.items()))})\n")

    # реальное состояние рынка — ВВЕРХУ, как якорь верификации
    try:
        from core.market import market_state_block
        heat_tags = [t for t, _c, _i in db.cashtag_heatmap(hours, limit=10)]
        parts.append(market_state_block(extra_tags=heat_tags))
    except Exception as e:
        parts.append(f"_(market-state недоступен: {e})_\n")

    # Focus Engine (SPEC_focus_engine.md §9) — инструмент(ы) дня, выбранные
    # focus_batch_job.py (запускается ДО этого скрипта, см. run_daily.sh шаг
    # 0) как наиболее отклонившиеся от СВОЕЙ нормы сегодня. Собираем
    # scope='default' И каждый персональный scope с активным watchlist/пином
    # (тоже получает source="batch" от того же джоба раз в день) — иначе
    # залогиненный пользователь со своим watchlist никогда не видит LLM-разбор,
    # только шаблон (нашли по жалобе на "куцую" карточку). Дедуп по символу:
    # если несколько scope сошлись на одном и том же инструменте, в брифе
    # он один, разбор потом тоже пишется один раз на символ, не на scope.
    try:
        from core import focus_db
        seen = {}
        scope_keys = ["default"] + [f"user:{uid}" for uid in focus_db.active_user_scopes()]
        for scope_key in scope_keys:
            state = focus_db.load_focus_state(scope_key)
            if state and state.symbol and state.source == "batch":
                if state.symbol not in seen or (state.anomaly or 0) > (seen[state.symbol][1] or 0):
                    seen[state.symbol] = (state.symbol, state.anomaly)
        if seen:
            lines = [f"## 🎯 В ФОКУСЕ СЕГОДНЯ (Focus Engine)\n"]
            for symbol, anomaly_v in seen.values():
                inst = focus_db.load_instrument(symbol)
                name = inst["name"] if inst else symbol
                mult = round(anomaly_v, 1) if anomaly_v is not None else "?"
                lines.append(
                    f"- **{name}** ({symbol}): аномальность ×{mult} относительно "
                    f"обычной волатильности (ATR14). Выбран по овернайт-гэпу/"
                    f"утреннему диапазону, не по абсолютной величине хода."
                )
            parts.append("\n".join(lines) + "\n")
    except Exception as e:
        parts.append(f"_(focus-engine недоступен: {e})_\n")

    parts.append(_section("💰 ЭКОНОМИКА", "economy", hours, 20))
    parts.append(_section("🌍 ГЕОПОЛИТИКА", "geopolitics", hours, 20))

    # психология толпы — по силе эмоции, поверх любой темы
    crowd_rows = db.top_by_crowd(hours, limit=15)
    if crowd_rows:
        body = "\n".join(_fmt_signal(s, i + 1) for i, s in enumerate(crowd_rows))
        parts.append(f"## 🔥 ПСИХОЛОГИЯ ТОЛПЫ (по силе эмоции/реакции)  "
                     f"({len(crowd_rows)} сигналов)\n{body}\n")

    # повестка СМИ
    agenda = media_agenda(hours, top=20)
    if agenda:
        parts.append("## 📰 ПОВЕСТКА СМИ (частота терминов в RSS)\n"
                     + "\n".join(f"  {c:3}× {t}" for t, c in agenda) + "\n")

    # тикеры
    heat = db.cashtag_heatmap(hours, limit=20)
    if heat:
        parts.append("## 📈 ТЕПЛОВАЯ КАРТА ТИКЕРОВ (упоминания · ср. importance)\n"
                     + "\n".join(f"  ${t:6} {c:3}× · imp~{imp:.2f}"
                                 for t, c, imp in heat) + "\n")

    # на что реагируют сильнее всего
    most_react = sorted(all_signals, key=lambda s: s["engagement"], reverse=True)[:10]
    if most_react and most_react[0]["engagement"]:
        parts.append("## 🌊 МАКСИМАЛЬНАЯ РЕАКЦИЯ (по engagement)\n"
                     + "\n".join(_fmt_signal(s, i + 1)
                                 for i, s in enumerate(most_react)) + "\n")

    out = BRIEFS_DIR / f"brief_{today}.md"
    out.write_text("\n".join(parts), encoding="utf-8")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    args = ap.parse_args()
    path = build(args.hours)
    print("brief →", path)
    print("─" * 60)
    print(path.read_text(encoding="utf-8")[:2000])
