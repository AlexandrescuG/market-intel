#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/notify_gdenigi.py — WP4.7 SPEC_alpha_engine_wp4_continuous_cycle.md,
пересмотрено WP6.3 SPEC_alpha_engine_wp6_volatility.md (15.08).

Рельсы для вывода в @gdenigi_bot — ОТДЕЛЬНЫЙ канал от core/telegram.py
(тот шлёт дневной дайджест и операционные алерты на TELEGRAM_*; этот —
прогнозы агента, условие допуска другое и назначение другое). С 15.08 —
ЕДИНЫЙ канал вместе с Signals (`/mnt/sbfdata/Signals/monitor.py`): оба
пишут в `analyze/outbox.py::enqueue()`, один отправщик (`outbox.send_pending`)
шлёт. Реальный токен создаёт Георгий через @BotFather -- до этого
GDENIGI_BOT_TOKEN пуст, outbox копится, ничего реально не уходит (не баг).

🔴 15.08: BSS>0 БОЛЬШЕ НЕ гейт доставки (было -- eligible_families()
решала, отправлять ли вообще) -- теперь гейт STATUS_LABEL (см.
determine_status_label ниже). Доставлять себе можно что угодно; то, что
обязано пережить весь путь -- явная метка "измерено или нет". eligible_families()
оставлена (переиспользуется determine_status_label), но её результат больше
не решает "слать/не слать".
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze.calibration_report import build_report
from tools.edu_build.pattern_reality import wilson

# WP6.5 (Core-лог 15.08): объединённый pooled-тест (symbols И tfs вместе,
# m=9, а не 27) на честной геометрии входа (next_open) дал 0/9 candidate,
# ВСЕ статистически значимо ОТРИЦАТЕЛЬНЫ (winrate 30-32%, CI не пересекает
# 0 в плюс) -- не "недостаточно данных", а измеренное отсутствие edge.
# Любой сигнал направленных паттернов (Signals: engulfing/hammer/double_top/
# etc) сейчас несёт эту метку. Пересмотреть ТОЛЬКО при новом объединённом
# тесте (analyze/baseline_report.py --pool-tfs), не по желанию/интуиции.
DIRECTIONAL_PATTERNS_STATUS_LABEL = "ТЕСТ · преимущество не подтверждено"


def eligible_families(con: sqlite3.Connection, families: list[str] | None = None) -> set[str]:
    """BSS(final_p) > 0 вне обучающей выборки -- см. calibration_report.build_report().
    families=None -- проверить только "barrier" (единственное реализованное
    семейство на 13.08). Больше не гейт доставки (см. докстринг модуля) --
    переиспользуется determine_status_label()."""
    out = set()
    for fam in (families or ["barrier"]):
        report = build_report(con, family=fam, since_ts=None)
        bss = report.get("bss_final_p")
        if bss is not None and bss > 0:
            out.add(fam)
    return out


# [ДОПУЩЕНИЕ] симметрично MIN_SAMPLE=20 в Signals/tracker.py -- ниже этого
# BSS технически вычислим, но статистически бессмысленный шум (n=12 дал
# bss=-0.77, что выглядит как уверенное "нет edge", а реально означает
# "рано делать любой вывод"). Живой прогон 15.08 поймал это ДО того, как
# такое сообщение ушло бы с неверной уверенностью.
MIN_N_FOR_LABEL = 20


def determine_status_label(con: sqlite3.Connection, family: str = "barrier") -> str:
    """3 метки (WP6.3, обязательное требование, NOT NULL):
    - "ТЕСТ · n недостаточно" -- разрешённых прогнозов семейства меньше
      MIN_N_FOR_LABEL или BSS не определён (climatology неизвестна);
    - "ИЗМЕРЕНО · BSS=<x>, n=<n>" -- BSS>0 вне обучающей выборки;
    - "ТЕСТ · преимущество не подтверждено" -- BSS<=0 (измерено, но не
      подтвердило edge)."""
    report = build_report(con, family=family, since_ts=None)
    n = report.get("n_resolved", 0)
    bss = report.get("bss_final_p")
    if n < MIN_N_FOR_LABEL or bss is None:
        return "ТЕСТ · n недостаточно"
    if bss > 0:
        return f"ИЗМЕРЕНО · BSS={bss:.3f}, n={n}"
    return "ТЕСТ · преимущество не подтверждено"


_SIGNALS_DB = Path("/mnt/sbfdata/Signals/signal_outcomes.sqlite")


def signals_forward_track_line() -> str:
    """"текущий форвард-трек одной строкой" (WP6.3 §"Что в сообщении") --
    обязателен на КАЖДОМ сообщении единого канала, не только Signals-своих:
    "тогда ни один сигнал не смотрится в отрыве от того, как система
    справляется в целом". Кросс-проектное чтение (Signals -- отдельный git-
    репозиторий) -- та же инфраструктурная связь, что уже есть в обратную
    сторону (market_intel пишет resolve_only.py в директорию Signals).
    Read-only, недоступность БД не должна ронять формирование сообщения."""
    try:
        con = sqlite3.connect(f"file:{_SIGNALS_DB}?mode=ro", uri=True, timeout=5)
        rows = dict(con.execute("SELECT status, COUNT(*) FROM signals GROUP BY status").fetchall())
        con.close()
    except Exception:
        return "форвард-трек Signals: недоступен"
    wins, losses = rows.get("WIN", 0), rows.get("LOSS", 0)
    decided = wins + losses
    if decided == 0:
        return "форвард-трек Signals: n=0 (разрешённых сделок ещё нет)"
    winrate = wins / decided
    ci_lo, ci_hi = wilson(wins, decided)
    breakeven = 1 / (1 + 2.0)  # rr=2.0 -- дефолт tracker.py::barriers()
    return (f"форвард-трек Signals: {wins}W/{losses}L, {winrate:.1%}, "
            f"CI95 [{ci_lo:.1f}%, {ci_hi:.1f}%], безубыток {breakeven:.1%}")


def format_message(forecast: dict, base: dict, status_label: str, outcome_hint: str | None = None) -> str:
    """Событие+горизонт, вероятность С ИНТЕРВАЛОМ И n (не голое число) ИЛИ
    честное "не определена", база и поправка агента раздельно, условие
    инвалидации, status_label (WP6.3, обязателен), форвард-трек одной
    строкой. base=None или base["insufficient"]=True -- "не определена",
    не выдуманное число."""
    lines = [f"📊 {forecast['symbol']} {forecast.get('horizon', '?')} — {forecast['event_key']}"]
    if base is None or base.get("insufficient"):
        lines.append("Базовая ставка: не определена (недостаточно исторических данных)")
    else:
        p = forecast.get("conviction")
        ci_lo, ci_hi, n = base.get("ci95_lo"), base.get("ci95_hi"), base.get("n")
        if p is None or ci_lo is None or ci_hi is None or n is None:
            raise ValueError("format_message: base не insufficient, но conviction/ci95/n не заданы")
        lines.append(f"Вероятность: {p:.1%} (CI95 [{ci_lo:.1f}%, {ci_hi:.1f}%], n={n})")
        lines.append(f"База: {base.get('p', 0):.1%} + поправка агента: {(p - base.get('p', 0)):+.1%}")
    lines.append(f"Инвалидация: {forecast.get('invalidation', '—')}")
    if outcome_hint:
        lines.append(outcome_hint)
    lines.append(status_label)
    lines.append(signals_forward_track_line())
    lines.append("\n<i>Это информация о вероятностях, не рекомендация к сделке.</i>")
    return "\n".join(lines)


def send_forecast(con: sqlite3.Connection, forecast: dict, base: dict) -> str:
    """Пишет в analyze/outbox.py вместо прямой отправки (WP6.3, единый
    канал с Signals, 15.08) -- реальная доставка (или тихий no-op без
    токена) происходит централизованно в outbox.send_pending(), не здесь.
    family="barrier" -- единственное реализованное семейство forecasts на
    сегодня, см. analyze/forecast_journal.py."""
    from analyze import outbox as _outbox
    status_label = determine_status_label(con, family="barrier")
    text = format_message(forecast, base, status_label)
    return _outbox.enqueue(con, source="agent", status_label=status_label, payload=text)
