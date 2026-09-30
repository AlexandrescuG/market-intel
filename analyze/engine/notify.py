#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/engine/notify.py — сообщения о РЕАЛЬНЫХ сделках движка.

Заменяет вещание погипотезных прогнозов, отключённое 02.09. Разница
принципиальная: раньше уходили гипотезы («вот что могло бы сработать»,
по 40-80 в день, включая встречные пары по одному бару), теперь уходит
факт — что движок открыл и что из этого вышло.

ЧТО В СООБЩЕНИИ И ЧЕГО В НЁМ НЕТ.

Есть: инструмент, направление, цена входа, стоп, цель, объём, риск в
деньгах, стратегия. То есть ровно то, по чему сделку можно повторить или
проверить.

Нет: «вероятности», «поправки агента» и прочих чисел, которые нечем
подтвердить. Старое сообщение ставило самое крупное число — «Итог с
поправкой» — рядом с подписью мелким «не измерена, в вердикте не
участвует». Показывать догадку крупнее измерения хуже, чем не показывать
её вовсе.

Сообщений теперь ровно столько, сколько сделок: несколько в день вместо
восьмидесяти.
"""
from __future__ import annotations

import sqlite3

from analyze.engine.contracts import LONG

_SIDE = {LONG: "покупка", "short": "продажа"}
_REASON = {
    "stop": "по стопу", "target": "по цели",
    "shadow_stop": "по стопу (тень)", "shadow_target": "по цели (тень)",
    "shadow_horizon": "по горизонту (тень)",
    "horizon": "по горизонту", "closed": "закрыта",
}


def _fmt(x: float, digits: int = 5) -> str:
    return f"{x:.{digits}f}".rstrip("0").rstrip(".")


def opened(trade: dict, strategy_state: dict | None = None) -> str:
    """Сообщение об открытии. Пишется по факту исполнения, а не по решению:
    между «решили войти» и «вошли» лежит отказ брокера, и путать их нельзя
    (на этом 28.08 движок отчитался «взято сделок: 0» и выглядел рабочим)."""
    s = trade
    side = _SIDE.get(s["direction"], s["direction"])
    rr = (abs(s["target"] - s["entry_price"]) / abs(s["entry_price"] - s["stop"])
          if s.get("entry_price") and s.get("stop") else 0)
    lines = [
        f"🟢 ОТКРЫТА · {s['symbol']} {s['tf']} · {side}",
        f"вход {_fmt(s['entry_price'])} · стоп {_fmt(s['stop'])} · "
        f"цель {_fmt(s['target'])}  (RR {rr:.1f})",
        f"объём {s['volume']} · риск {s['risk_money']:.2f} USD",
        f"стратегия {s['strategy']}",
    ]
    if strategy_state and strategy_state.get("n_closed"):
        lines.append(f"её кривая: {strategy_state['cum_r']:+.1f}R "
                     f"за {strategy_state['n_closed']} сделок")
    return "\n".join(lines)


def closed(trade: dict, r: float, strategy_state: dict | None = None) -> str:
    """Сообщение о закрытии. R — в единицах риска, а не в деньгах: объём у
    нас плавает вместе с волатильностью, и денежные исходы между собой не
    сравнимы."""
    s = trade
    side = _SIDE.get(s["direction"], s["direction"])
    why = _REASON.get(s.get("close_reason", ""), s.get("close_reason") or "закрыта")
    mark = "✅" if r > 0 else "🔻"
    lines = [
        f"{mark} ЗАКРЫТА · {s['symbol']} {s['tf']} · {side} · {why}",
        f"{_fmt(s['entry_price'])} → {_fmt(s['exit_price'])} · {r:+.2f}R",
        f"стратегия {s['strategy']}",
    ]
    if strategy_state:
        dd = (strategy_state.get("cum_r") or 0) - (strategy_state.get("peak_r") or 0)
        lines.append(f"её кривая: {strategy_state.get('cum_r', 0):+.1f}R "
                     f"за {strategy_state.get('n_closed', 0)} сделок · "
                     f"просадка от пика {dd:+.1f}R")
    return "\n".join(lines)


def stop_moved(trade: dict, old_stop: float, new_stop: float, why: str) -> str:
    """Сообщение о переносе стопа — то, чего раньше не было вовсе.

    Отдельным сообщением, а не молча: перенос меняет риск уже открытой
    сделки, и владелец должен видеть это в тот момент, когда оно произошло,
    а не обнаруживать постфактум по журналу."""
    return (f"🛡 СТОП ПЕРЕНЕСЁН · {trade['symbol']} {trade['tf']}\n"
            f"{_fmt(old_stop)} → {_fmt(new_stop)}  ({why})\n"
            f"стратегия {trade['strategy']}")


def send(con: sqlite3.Connection, text: str, label: str = "сделка") -> str | None:
    """В тот же общий outbox, что и остальное. Реальная отправка — в
    `outbox.send_pending()`, здесь только постановка в очередь."""
    from analyze import outbox as _outbox
    try:
        return _outbox.enqueue(con, source="engine", status_label=label, payload=text)
    except Exception as e:                                          # noqa: BLE001
        # Не роняем торговый цикл из-за уведомления: сделка важнее письма.
        # Но и не молчим — в лог попадёт.
        print(f"[notify] не удалось поставить в очередь: {e}", flush=True)
        return None
