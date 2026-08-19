#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/strategy_monitor.py — самообновление форвард-проверки.

Замыкает петлю: сделка закрылась -> результат добран -> метрики пересчитаны
-> применены правила остановки -> при необходимости вызван агент для разбора.

ГРАНИЦА АВТОМАТИЗАЦИИ (§4 pregeg 2026-08-19_forward_stopping.md).
Система накапливает, считает, останавливает и разбирает. Она НЕ меняет
условие входа, геометрию, инструмент и размер. Вывод агента ложится в
analyze/proposals/ как предложение и проходит обычный путь: пререгистрация,
m заранее, критерий до прогона.

Причина не в осторожности, а в арифметике: гипотеза, выведенная из
последних 20 сделок и сразу применённая, не будет проверена никогда — у неё
не останется данных, которых она не видела. Разница между «система учится»
и «система подгоняется» ровно в этом.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
PROPOSALS = Path(__file__).parent / "proposals"

PLANKA_ATR = 0.036          # §2 пререгистрации: издержки XAUUSD
MIN_N_CHECK = 20
MIN_N_STOP = 30
MIN_N_CONFIRM = 50
MAX_DRAWDOWN_ATR = -15.0

log = logging.getLogger("strategy_monitor")


def closed_trades(con: sqlite3.Connection) -> list[dict]:
    """Закрытые сделки стратегии, с результатом в ATR."""
    rows = con.execute(
        "SELECT id, deal_entry_price, deal_exit_price, note, closed_ts "
        "FROM cost_observations WHERE order_status='closed' AND note LIKE '%strategy=gold_oil%' "
        "ORDER BY closed_ts").fetchall()
    out = []
    for oid, entry, exit_, note, cts in rows:
        if entry is None or exit_ is None:
            continue
        atr = None
        for part in (note or "").split():
            if part.startswith("atr="):
                try:
                    atr = float(part[4:])
                except ValueError:
                    pass
        if not atr:
            continue
        out.append({"id": oid, "r_atr": (exit_ - entry) / atr, "closed_ts": cts,
                    "divergence": "divergence=1" in (note or "")})
    return out


def metrics(trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0}
    vals = [t["r_atr"] for t in trades]
    mean = sum(vals) / n
    if n > 1:
        sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1))
        se = sd / math.sqrt(n)
    else:
        se = float("inf")
    return {"n": n, "ev": mean, "total": sum(vals),
            "ci_lo": mean - 1.96 * se, "ci_hi": mean + 1.96 * se,
            "wins": sum(1 for v in vals if v > 0)}


def apply_rules(m: dict) -> tuple[str, str]:
    """Правила §3 пререгистрации. Порядок важен: остановки проверяются
    раньше подтверждения."""
    if m["n"] < MIN_N_CHECK:
        return "накопление", f"n={m['n']} < {MIN_N_CHECK}, правила ещё не применяются"
    if m["total"] <= MAX_DRAWDOWN_ATR:
        return "СТОП-ПРОСАДКА", f"суммарно {m['total']:.2f} ATR <= {MAX_DRAWDOWN_ATR}"
    if m["n"] >= MIN_N_STOP and m["ci_hi"] < PLANKA_ATR:
        return "СТОП-УБЫТОК", (f"верх CI95 {m['ci_hi']:+.4f} ниже планки {PLANKA_ATR} "
                               f"при n={m['n']} — признак опровергнут форвардом")
    if m["n"] >= MIN_N_CONFIRM and m["ci_lo"] > PLANKA_ATR:
        return "ПОДТВЕРЖДЁН", f"низ CI95 {m['ci_lo']:+.4f} выше планки при n={m['n']}"
    return "продолжать", f"n={m['n']}, EV={m['ev']:+.4f}, CI95 [{m['ci_lo']:+.4f}, {m['ci_hi']:+.4f}]"


def stop_trading(reason: str) -> None:
    """Останавливает таймер стратегии. Обратимо одной командой — намеренно
    не удаляем юнит, чтобы решение можно было пересмотреть осознанно."""
    subprocess.run(["systemctl", "--user", "disable", "--now", "sbf-live-strategy.timer"],
                   capture_output=True)
    log.error("ТОРГОВЛЯ ОСТАНОВЛЕНА: %s", reason)


def alert(text: str) -> None:
    try:
        import asyncio

        from core.config import TELEGRAM_REPORT_CHAT_ID
        from core.telegram import send_text
        asyncio.run(send_text(f"📉 strategy_monitor: {text}", chat_id=TELEGRAM_REPORT_CHAT_ID))
    except Exception as e:
        log.error("алерт не отправлен: %s", e)


def ask_agent(m: dict, trades: list[dict]) -> str | None:
    """Содержательный разбор. Агенту явно запрещено предлагать изменения как
    решённые — только гипотезы с указанием, на скольких сделках основаны."""
    div = [t["r_atr"] for t in trades if t["divergence"]]
    nodiv = [t["r_atr"] for t in trades if not t["divergence"]]
    prompt = f"""Разбери форвард-проверку торговой гипотезы. Отвечай по-русски, кратко.

Гипотеза: золото (XAUUSD), только лонг, вход когда нефть (DCOILWTICO) выше
значения 20 публикаций назад. Стоп 2.0 ATR, цель 1.0 ATR, горизонт 12 баров H1.
Порог безубыточности с учётом спреда: EV > {PLANKA_ATR} ATR за сделку.

Накоплено: n={m['n']}, EV={m['ev']:+.4f} ATR, CI95 [{m['ci_lo']:+.4f}, {m['ci_hi']:+.4f}],
суммарно {m['total']:+.2f} ATR, выигрышных {m['wins']}.

Подгруппы (разведочные, не пререгистрированы):
  расхождение (нефть растёт, золото ещё нет): n={len(div)}, EV={sum(div)/len(div):+.4f} ATR
  совместный рост:                            n={len(nodiv)}, EV={(sum(nodiv)/len(nodiv) if nodiv else 0):+.4f} ATR

Вопросы:
1. Что говорят эти числа — и чего они НЕ говорят при таком n?
2. Есть ли основания считать подгруппы различающимися, или разница в пределах шума?
3. Какие гипотезы стоит поставить в очередь на пререгистрацию?

ЖЁСТКО: не предлагай менять условие входа, геометрию или инструмент как
решённое действие. Любое предложение — гипотеза, требующая пререгистрации и
проверки на данных, которых она не видела. Прямо указывай, на скольких
сделках основан каждый вывод."""
    try:
        r = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True, timeout=300)
        return r.stdout.strip() if r.returncode == 0 else f"агент недоступен: {r.stderr[:200]}"
    except Exception as e:
        return f"агент недоступен: {type(e).__name__}: {e}"


def run(with_agent: bool) -> int:
    con = sqlite3.connect(str(BOT_DB), timeout=30)
    trades = closed_trades(con)
    m = metrics(trades)
    if m["n"] == 0:
        log.info("закрытых сделок стратегии пока нет")
        con.close()
        return 2

    verdict, why = apply_rules(m)
    log.info("n=%d EV=%+.4f ATR суммарно=%+.2f -> %s (%s)",
             m["n"], m["ev"], m["total"], verdict, why)

    if verdict.startswith("СТОП"):
        stop_trading(why)
        alert(f"{verdict}. {why}")
    elif verdict == "ПОДТВЕРЖДЁН":
        alert(f"{verdict}. {why}")

    if with_agent and m["n"] >= MIN_N_CHECK:
        PROPOSALS.mkdir(exist_ok=True)
        text = ask_agent(m, trades)
        p = PROPOSALS / f"{time.strftime('%Y-%m-%d')}_forward_review.md"
        p.write_text(
            f"# Разбор форварда — {time.strftime('%Y-%m-%d %H:%M')}\n\n"
            f"n={m['n']}, EV={m['ev']:+.4f} ATR, CI95 [{m['ci_lo']:+.4f}, {m['ci_hi']:+.4f}], "
            f"суммарно {m['total']:+.2f} ATR\n\n"
            f"Вердикт правил §3: **{verdict}** — {why}\n\n"
            f"> Ниже — ПРЕДЛОЖЕНИЯ агента. Ни одно не применяется автоматически.\n"
            f"> Чтобы стать стратегией, гипотеза проходит пререгистрацию.\n\n{text}\n",
            encoding="utf-8")
        log.info("разбор записан: %s", p)

    con.close()
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-agent", action="store_true", help="вызвать агента для разбора")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | [monitor] %(message)s")
    sys.exit(run(args.with_agent))


if __name__ == "__main__":
    main()
