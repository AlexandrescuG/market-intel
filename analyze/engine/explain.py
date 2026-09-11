#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/engine/explain.py — чем движок руководствовался, входя в сделку.

ЗАЧЕМ ЭТО ОТДЕЛЬНО ОТ notify.py. Сообщение об открытии отвечает на вопрос
«что произошло»: инструмент, цена, стоп, объём. Здесь — ответ на «почему
именно это и почему сейчас», и он устроен иначе: полезен не сам факт входа,
а то, ЧТО ЕГО ЧУТЬ НЕ ОТМЕНИЛО.

Движок отвергает 94 сигнала из 100. Значит содержательная часть решения —
не «сработал паттерн», а «прошёл восемь проверок подряд, и вот с каким
запасом по каждой». Трейдеру запас важнее факта: он показывает, насколько
решение было пограничным.

🔴 ЧЕГО ЗДЕСЬ НЕТ И НЕ БУДЕТ. Ни «вероятности отработки», ни «силы
сигнала», ни поправок с потолка. 02.09 мы заглушили вещание ровно за это:
в старом сообщении самым крупным числом было «Итог с поправкой: 43.8%» —
единственное НЕизмеренное, с подписью мелким «в вердикте не участвует».
Здесь каждая строка — величина, которую движок реально считал и по которой
реально принимал решение. Если величины нет, строки нет.
"""
from __future__ import annotations

import sqlite3

from analyze.engine import risk
from analyze.engine.contracts import Signal

# Человеческие имена источников. Держим здесь, а не в контракте: контракт
# описывает механику, а это — язык, на котором с трейдером говорят.
SOURCE_RU = {
    "alpha_forecast": "прогноз модели по состоянию рынка",
    "gate_momentum": "движение больше обычного (гейт)",
    "macro_gold_oil": "макро-режим: нефть выше, чем месяц назад",
    "macro_gold_dxy": "макро-режим: доллар слабее, чем месяц назад",
    "macro_eur_dxy": "макро-режим: доллар слабее, чем месяц назад",
    "pattern_break_retest": "пробой уровня и возврат к нему",
    "pattern_bullish_engulfing": "бычье поглощение",
    "pattern_bearish_engulfing": "медвежье поглощение",
    "pattern_pin_bar_top": "пин-бар сверху",
    "pattern_pin_bar_bottom": "пин-бар снизу",
    "pattern_double_top": "двойная вершина",
    "pattern_double_bottom": "двойное дно",
    "pattern_shooting_star": "падающая звезда",
    "pattern_hammer": "молот",
}


def _bar(share: float, width: int = 10) -> str:
    """Полоска занятости лимита. Глазу нужнее числа: 'почти упёрлись'
    считывается мгновенно, а «0.83» требует сравнения с потолком."""
    share = max(0.0, min(1.0, share))
    full = int(round(share * width))
    return "█" * full + "·" * (width - full)


def explain(con: sqlite3.Connection, s: Signal, *, volume: float,
            risk_money: float, equity: float, spread: float,
            market_price: float | None) -> str:
    """Разбор принятого решения. Все числа — из самих проверок."""
    src = SOURCE_RU.get(s.strategy, s.strategy)
    side = "покупка" if s.is_long else "продажа"
    dist = s.stop_distance
    stop_atr = dist / s.atr if s.atr else 0

    lines = [
        f"📐 ПОЧЕМУ {s.symbol} {s.tf} · {side}",
        "",
        f"Основание: {src}",
        f"Бар: {s.bar_ts and __import__('datetime').datetime.utcfromtimestamp(s.bar_ts).strftime('%d.%m %H:%M')} UTC",
    ]

    # ── геометрия ───────────────────────────────────────────────────────
    lines += [
        "",
        "Геометрия",
        f"  стоп {stop_atr:.2f} ATR (предел {risk.MIN_STOP_ATR}–{risk.MAX_STOP_ATR})",
        f"  RR {s.rr:.1f} → безубыточный винрейт {100 / (1 + s.rr):.0f}%",
        f"  горизонт {s.horizon_sec // 3600} ч",
    ]

    # ── издержки: главное, что режет сделки ─────────────────────────────
    if spread and dist > 0:
        share_risk = spread / dist
        share_reward = spread / (s.rr * dist) if s.rr else 0
        lines += [
            "",
            "Издержки",
            f"  спред {spread:.5f} = {share_risk * 100:.1f}% риска "
            f"{_bar(share_risk / risk.MAX_SPREAD_SHARE_OF_RISK)} "
            f"предел {risk.MAX_SPREAD_SHARE_OF_RISK * 100:.0f}%",
            f"  он же {share_reward * 100:.1f}% награды "
            f"{_bar(share_reward / risk.MAX_SPREAD_SHARE_OF_TARGET)} "
            f"предел {risk.MAX_SPREAD_SHARE_OF_TARGET * 100:.0f}%",
        ]

    # ── размер ──────────────────────────────────────────────────────────
    lines += [
        "",
        "Размер",
        f"  {volume} лота · риск {risk_money:.2f} USD = "
        f"{risk_money / equity * 100:.2f}% счёта (норма {risk.RISK_PER_TRADE * 100:.2f}%)",
        "  объём считается ОТ стопа: шире стоп — меньше лот, цена ошибки постоянна",
    ]

    # ── снос от основания ───────────────────────────────────────────────
    if market_price is not None and dist > 0:
        drift = abs(market_price - s.ref_price) / dist
        lines += [
            "",
            f"Снос от бара-основания: {drift:.2f}R "
            f"{_bar(drift / risk.MAX_ENTRY_DRIFT_R)} предел {risk.MAX_ENTRY_DRIFT_R}R",
        ]

    # ── занятость лимитов портфеля ──────────────────────────────────────
    rows = con.execute(
        "SELECT symbol, direction, strategy, risk_money FROM engine_trades "
        "WHERE status='open' AND mode='live'").fetchall()
    same_side = sum(1 for r in rows if r[0] == s.symbol and r[1] == s.direction)
    used = sum(r[3] or 0 for r in rows)
    lines += [
        "",
        "Портфель после входа",
        f"  по {s.symbol} в сторону {side}: {same_side + 1} из "
        f"{risk.MAX_OPEN_PER_SYMBOL_SIDE} "
        f"{_bar((same_side + 1) / risk.MAX_OPEN_PER_SYMBOL_SIDE)}",
        f"  суммарный риск: {(used + risk_money) / equity * 100:.2f}% из "
        f"{risk.MAX_PORTFOLIO_RISK * 100:.0f}% "
        f"{_bar((used + risk_money) / equity / risk.MAX_PORTFOLIO_RISK)}",
    ]

    # ── трек самой стратегии ────────────────────────────────────────────
    st = con.execute(
        "SELECT cum_r, peak_r, n_closed FROM engine_strategy_state WHERE strategy=?",
        (s.strategy,)).fetchone()
    if st and st[2]:
        cum, peak, n = st[0] or 0, st[1] or 0, st[2]
        dd = cum - peak
        lines += [
            "",
            f"Трек стратегии: {cum:+.1f}R за {n} сделок · "
            f"просадка от пика {dd:.1f}R из {risk.MAX_DRAWDOWN_R:.0f}R до остановки",
        ]

    lines += [
        "",
        "Это разбор механики решения, не прогноз исхода.",
    ]
    return "\n".join(lines)
