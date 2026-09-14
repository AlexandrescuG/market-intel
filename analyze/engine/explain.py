#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/engine/explain.py — чек-лист входа для @gdenigi_bot.

ЭТО НЕ СИГНАЛ, И ЭТО КОНСТРУКТИВНОЕ РЕШЕНИЕ, А НЕ ОГОВОРКА.

В сообщении намеренно НЕТ цены входа, стопа и цели. Не потому что их
жалко, а потому что с ними сообщение становится инструкцией «войди сюда,
стоп туда» — то есть сигналом, который читатель может скопировать. Нам
нужно обратное: показать, ЧТО и с каким запасом проверено, чтобы трейдер
видел устройство решения, а не его копировал.

Геометрия поэтому выражена в ATR и в R — величинах относительных. Они
объясняют форму сделки и ничего не говорят о том, куда ставить ордер.

ЧТО ЗДЕСЬ СОДЕРЖАТЕЛЬНОГО. Движок отвергает 94 сигнала из 100, и
«паттерн сработал» ничего не сообщает — паттерны срабатывают постоянно.
Сообщает ЗАПАС по каждой из восьми проверок: он показывает, насколько
вход был пограничным и что именно отклонит следующий такой сигнал.

🔴 ЧЕГО ЗДЕСЬ НЕТ И НЕ БУДЕТ. Ни «вероятности отработки», ни «силы
сигнала», ни поправок. 02.09 вещание глушили ровно за это: там самым
крупным числом было «Итог с поправкой: 43.8%» — единственное
НЕизмеренное, с подписью мелким «в вердикте не участвует». Правило:
нет величины, по которой движок реально принимал решение, — нет строки.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3

from analyze.engine import risk
from analyze.engine.contracts import Signal

# Человеческие имена источников. Живут здесь, а не в контракте: контракт
# описывает механику, а это — язык, на котором говорят с трейдером.
SOURCE_RU = {
    "alpha_forecast": "прогноз модели по состоянию рынка",
    "gate_momentum": "движение крупнее обычного (гейт внимания)",
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

# Доля лимита, после которой пункт помечается как пограничный. Не косметика:
# «прошли, но впритык» и «прошли с запасом» — разные состояния, и читатель
# должен различать их взглядом, а не арифметикой в уме.
TIGHT = 0.8


def _mark(used_share: float) -> str:
    return "⚠" if used_share >= TIGHT else "✓"


def _row(mark: str, name: str, detail: str) -> str:
    return f"{mark} {name:<24} {detail}"


def checklist(con: sqlite3.Connection, s: Signal, *, volume: float,
              risk_money: float, equity: float, spread: float,
              market_price: float | None) -> str:
    """Чек-лист принятого решения. Все числа — из самих проверок."""
    src = SOURCE_RU.get(s.strategy, s.strategy)
    side = "покупка" if s.is_long else "продажа"
    dist = s.stop_distance
    rows, notes = [], []

    head = [
        f"🧭 ЧЕК-ЛИСТ ВХОДА · {s.symbol} {s.tf} · {side}",
        f"основание: {src}",
    ]
    if s.bar_ts:
        bar = _dt.datetime.fromtimestamp(s.bar_ts, _dt.UTC)
        head.append(f"бар: {bar:%d.%m %H:%M} UTC")
    head.append("")

    # 1. свежесть основания
    if market_price is not None and dist > 0:
        drift = abs(market_price - s.ref_price) / dist
        share = drift / risk.MAX_ENTRY_DRIFT_R
        rows.append(_row(_mark(share), "основание свежее",
                         f"снос {drift:.2f}R из {risk.MAX_ENTRY_DRIFT_R}R"))
        if share >= TIGHT:
            notes.append("Цена заметно ушла от бара-основания — вход хуже расчётного.")

    # 2. геометрия
    stop_atr = dist / s.atr if s.atr else 0
    be = 100 / (1 + s.rr) if s.rr else 0
    rows.append(_row("✓", "геометрия",
                     f"стоп {stop_atr:.2f} ATR (норма "
                     f"{risk.MIN_STOP_ATR}–{risk.MAX_STOP_ATR}), RR {s.rr:.1f}"))

    # 3. издержки — главное, что режет сделки
    if spread and dist > 0:
        sr = spread / dist
        sw = spread / (s.rr * dist) if s.rr else 0
        share = max(sr / risk.MAX_SPREAD_SHARE_OF_RISK,
                    sw / risk.MAX_SPREAD_SHARE_OF_TARGET)
        rows.append(_row(_mark(share), "издержки",
                         f"спред {sr * 100:.1f}% риска из "
                         f"{risk.MAX_SPREAD_SHARE_OF_RISK * 100:.0f}%, "
                         f"{sw * 100:.1f}% награды из "
                         f"{risk.MAX_SPREAD_SHARE_OF_TARGET * 100:.0f}%"))
        if sr >= 0.08:
            notes.append(f"Спред забирает {sr * 100:.0f}% риска — сделка стартует "
                         f"заметно ниже нуля.")

    # 4. размер
    share_risk = risk_money / equity if equity else 0
    rows.append(_row("✓", "размер от риска",
                     f"{share_risk * 100:.2f}% счёта (норма "
                     f"{risk.RISK_PER_TRADE * 100:.2f}%), {volume} лота"))

    # 5-6. портфельные лимиты
    # Тот же источник, что у портфельного лимита: чек-лист обязан показывать
    # числа, по которым движок реально принимал решение, а не их копию.
    open_rows = risk.open_risk_rows(con)
    same_side = sum(1 for r in open_rows if r[0] == s.symbol and r[1] == s.direction)
    n_side = same_side + 1
    share = n_side / risk.MAX_OPEN_PER_SYMBOL_SIDE
    rows.append(_row(_mark(share), "лимит по инструменту",
                     f"{n_side} из {risk.MAX_OPEN_PER_SYMBOL_SIDE} в эту сторону"))
    if n_side >= risk.MAX_OPEN_PER_SYMBOL_SIDE:
        notes.append(f"Лимит по {s.symbol} в сторону «{side}» исчерпан — следующий "
                     f"такой сигнал будет отклонён.")

    used = sum(r[3] or 0 for r in open_rows) + risk_money
    pf = used / equity if equity else 0
    share = pf / risk.MAX_PORTFOLIO_RISK
    rows.append(_row(_mark(share), "риск портфеля",
                     f"{pf * 100:.2f}% из {risk.MAX_PORTFOLIO_RISK * 100:.0f}%"))
    if share >= 1.0:
        notes.append("Портфельный лимит риска выбран полностью — новые входы "
                     "закрыты до закрытия текущих.")

    # 7. состояние стратегии
    st = con.execute(
        "SELECT cum_r, peak_r, n_closed FROM engine_strategy_state WHERE strategy=?",
        (s.strategy,)).fetchone()
    if st and st[2]:
        cum, peak, n = st[0] or 0, st[1] or 0, st[2]
        dd = abs(cum - peak)
        share = dd / risk.MAX_DRAWDOWN_R
        rows.append(_row(_mark(share), "стратегия в работе",
                         f"{cum:+.1f}R за {n} сделок, просадка {dd:.1f}R из "
                         f"{risk.MAX_DRAWDOWN_R:.0f}R"))
        if n < 30:
            notes.append(f"У стратегии всего {n} закрытых сделок — о её качестве "
                         f"судить рано.")
    else:
        rows.append(_row("⚠", "стратегия в работе", "закрытых сделок ещё нет"))
        notes.append("Первая сделка стратегии: трека нет, сравнивать не с чем.")

    # 8. толкование, которого не видно из чисел
    if s.rr:
        notes.insert(0, f"Безубыточный винрейт при RR {s.rr:.1f} — {be:.0f}%: "
                        f"конфигурация окупается, если отрабатывает примерно "
                        f"каждая {round(100 / be) if be else 0}-я сделка.")

    out = head + rows
    if notes:
        out += ["", "Что это значит"]
        out += [f"• {n}" for n in notes]
    out += ["", "Разбор механики решения. Не рекомендация и не сигнал;",
            "цены входа и барьеров здесь намеренно не приводятся."]
    return "\n".join(out)
