#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/notify_gdenigi.py — WP4.7 SPEC_alpha_engine_wp4_continuous_cycle.md.

Рельсы для вывода в @gdenigi_bot — ОТДЕЛЬНЫЙ канал от core/telegram.py
(тот шлёт дневной дайджест и операционные алерты на TELEGRAM_*; этот —
прогнозы агента, условие допуска другое и назначение другое, смешивать
токены/потоки нет причины).

Условие допуска (не изменилось с shadow-mode WP4): семейство уходит в бот
ТОЛЬКО там, где BSS>0 вне обучающей выборки. При forecast_outcomes=0 (как
на 13.08) eligible_families() всегда вернёт пустое множество -- это
ожидаемо, не баг. Реальный токен создаёт Георгий через @BotFather -- до
этого GDENIGI_BOT_TOKEN пуст, send_forecast() тихо не отправляет ничего
(симметрично core.telegram.send_text, которое тоже возвращается рано без
токена).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze.calibration_report import build_report


def eligible_families(con: sqlite3.Connection, families: list[str] | None = None) -> set[str]:
    """BSS(final_p) > 0 вне обучающей выборки -- см. calibration_report.build_report().
    families=None -- проверить только "barrier" (единственное реализованное
    семейство на 13.08)."""
    out = set()
    for fam in (families or ["barrier"]):
        report = build_report(con, family=fam, since_ts=None)
        bss = report.get("bss_final_p")
        if bss is not None and bss > 0:
            out.add(fam)
    return out


def format_message(forecast: dict, base: dict, outcome_hint: str | None = None) -> str:
    """Событие+горизонт, вероятность С ИНТЕРВАЛОМ И n (не голое число),
    база и поправка агента раздельно, условие инвалидации, ссылка на
    новость если участвовала. Голое число без интервала физически не
    собрать этой функцией -- ci95_lo/ci95_hi/n обязательны на входе."""
    p = forecast.get("conviction")
    ci_lo, ci_hi, n = base.get("ci95_lo"), base.get("ci95_hi"), base.get("n")
    if p is None or ci_lo is None or ci_hi is None or n is None:
        raise ValueError("format_message требует conviction+ci95_lo+ci95_hi+n -- голое число не отправляем")
    lines = [
        f"📊 {forecast['symbol']} {forecast.get('horizon', '?')} — {forecast['event_key']}",
        f"Вероятность: {p:.1%} (CI95 [{ci_lo:.1f}%, {ci_hi:.1f}%], n={n})",
        f"База: {base.get('p', 0):.1%} + поправка агента: {(p - base.get('p', 0)):+.1%}",
        f"Инвалидация: {forecast.get('invalidation', '—')}",
    ]
    if outcome_hint:
        lines.append(outcome_hint)
    lines.append("\n_Это информация о вероятностях, не рекомендация к сделке._")
    return "\n".join(lines)


async def send_forecast(forecast: dict, base: dict) -> None:
    """Тихо не отправляет ничего без токена (симметрично core.telegram.send_text)."""
    from core.config import GDENIGI_BOT_TOKEN, GDENIGI_CHAT_ID
    if not GDENIGI_BOT_TOKEN or not GDENIGI_CHAT_ID:
        return
    import httpx
    text = format_message(forecast, base)
    async with httpx.AsyncClient(timeout=15) as c:
        await c.post(f"https://api.telegram.org/bot{GDENIGI_BOT_TOKEN}/sendMessage",
                     json={"chat_id": GDENIGI_CHAT_ID, "text": text, "parse_mode": "Markdown"})
