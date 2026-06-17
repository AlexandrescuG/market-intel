"""Сборка дневного брифа (06:00). Читает сигналы за окно, агрегирует, пишет
структурный markdown, который потом читает claude -p.

Бриф НЕ анализирует — он только раскладывает факты так, чтобы LLM было удобно.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from core import db
from core.config import BRIEFS_DIR, DATA_DIR
from collectors.rss import media_agenda

OBSERVATIONS_PATH = DATA_DIR / "observations.md"

# Источники RSS, которые считаются агентствами (не первоисточник, но репортаж)
_RSS_WIRE = {"BBC World", "BBC Business", "Guardian World", "Al Jazeera",
             "CNBC Finance", "Yahoo Finance", "MarketWatch", "RBC",
             "Interfax", "Investing.com"}


def _credibility_tag(s: dict) -> str:
    """Тег достоверности по типу источника и характеристикам сигнала."""
    src = s["source"]
    crowd = s.get("crowd_intensity", 0) or 0

    if src == "rss":
        # RSS от агентств — репортаж, не первоисточник
        return "[СООБЩЕНИЕ]"
    if src == "twitter":
        if crowd >= 0.45:
            return "[НАСТРОЕНИЕ]"
        return "[СЛУХ]"
    if src == "reddit":
        if crowd >= 0.45:
            return "[НАСТРОЕНИЕ]"
        return "[СЛУХ]"
    return "[СЛУХ]"


def _fmt_signal(s: dict, idx: int) -> str:
    tag = _credibility_tag(s)
    eng = f" · 👁 {s['engagement']:,}" if s["engagement"] else ""
    rep = f" · 💬 {s['replies']:,}" if s["replies"] else ""
    tags = json.loads(s["cashtags"] or "[]")
    tagstr = f" · {' '.join('$' + t for t in tags)}" if tags else ""
    head = (s["title"] or s["text"] or "").replace("\n", " ").strip()[:240]
    src = s["source"]
    who = f"@{s['author']}" if src == "twitter" else s["author"]
    return (f"{idx}. {tag} [{src}] {who} · imp={s['importance']:.2f} "
            f"· econ={s['econ_relevance']:.2f} · crowd={s['crowd_intensity']:.2f}"
            f"{eng}{rep}{tagstr}\n"
            f"   {head}\n   {s['url']}")


def _section(title: str, dimension: str, hours: int, limit: int) -> str:
    rows = db.top_by_dimension(hours, dimension, limit)
    if not rows:
        return f"## {title}\n_(нет сигналов за окно)_\n"
    body = "\n".join(_fmt_signal(s, i + 1) for i, s in enumerate(rows))
    return f"## {title}  ({len(rows)} сигналов)\n{body}\n"


def _observations_section(limit: int = 14) -> str:
    """Читает последние N наблюдений из observations.md для включения в бриф."""
    if not OBSERVATIONS_PATH.exists():
        OBSERVATIONS_PATH.write_text(
            "# История наблюдений\n"
            "_Заполняется автоматически из дневных отчётов._\n\n",
            encoding="utf-8",
        )
        return ""
    lines = OBSERVATIONS_PATH.read_text(encoding="utf-8").splitlines()
    # берём строки вида "YYYY-MM-DD | ..."
    obs = [l for l in lines if l.strip() and l[:4].isdigit() and "|" in l]
    if not obs:
        return ""
    recent = obs[-limit:]
    return (
        "## 🔭 ИСТОРИЯ НАБЛЮДЕНИЙ (для раздела «Табло»)\n"
        + "\n".join(recent)
        + "\n"
    )


def build(hours: int = 24) -> Path:
    db.init_db()
    all_signals = db.recent_since(hours)
    by_source: dict[str, int] = {}
    for s in all_signals:
        by_source[s["source"]] = by_source.get(s["source"], 0) + 1

    parts: list[str] = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parts.append(f"# RAW BRIEF · {today} · окно {hours}ч")
    parts.append(
        f"Всего сигналов: {len(all_signals)} "
        f"({', '.join(f'{k}={v}' for k, v in sorted(by_source.items()))})\n"
    )

    # Теги достоверности — легенда
    parts.append(
        "**Теги достоверности:** "
        "[ДАННЫЕ] официальная публикация (дата+эмитент) · "
        "[СООБЩЕНИЕ] репортаж агентства · "
        "[СЛУХ] единичный пост/инсайд · "
        "[НАСТРОЕНИЕ] эмоция/engagement без фактуры\n"
    )

    # История наблюдений для раздела «Табло»
    obs = _observations_section()
    if obs:
        parts.append(obs)

    parts.append(_section("💰 ЭКОНОМИКА", "economy", hours, 20))
    parts.append(_section("🌍 ГЕОПОЛИТИКА", "geopolitics", hours, 20))

    # психология толпы
    crowd_rows = db.top_by_crowd(hours, limit=15)
    if crowd_rows:
        body = "\n".join(_fmt_signal(s, i + 1) for i, s in enumerate(crowd_rows))
        parts.append(
            f"## 🔥 ПСИХОЛОГИЯ ТОЛПЫ (по силе эмоции/реакции)  "
            f"({len(crowd_rows)} сигналов)\n{body}\n"
        )

    # повестка СМИ
    agenda = media_agenda(hours, top=20)
    if agenda:
        parts.append(
            "## 📰 ПОВЕСТКА СМИ (частота терминов в RSS)\n"
            + "\n".join(f"  {c:3}× {t}" for t, c in agenda)
            + "\n"
        )

    # тикеры
    heat = db.cashtag_heatmap(hours, limit=20)
    if heat:
        parts.append(
            "## 📈 ТЕПЛОВАЯ КАРТА ТИКЕРОВ (упоминания · ср. importance)\n"
            + "\n".join(f"  ${t:6} {c:3}× · imp~{imp:.2f}" for t, c, imp in heat)
            + "\n"
        )

    # максимальная реакция
    most_react = sorted(all_signals, key=lambda s: s["engagement"], reverse=True)[:10]
    if most_react and most_react[0]["engagement"]:
        parts.append(
            "## 🌊 МАКСИМАЛЬНАЯ РЕАКЦИЯ (по engagement)\n"
            + "\n".join(_fmt_signal(s, i + 1) for i, s in enumerate(most_react))
            + "\n"
        )

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
