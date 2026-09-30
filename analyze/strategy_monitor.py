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
HORIZON_SEC = 12 * 3600     # 12 баров H1 — горизонт из пререгистрации

log = logging.getLogger("strategy_monitor")


def reconcile(con: sqlite3.Connection, positions) -> int:
    """Позиции у брокера, которых нет в журнале, — завести и закричать.

    🔴 19.08 18:02: ордер ушёл, позиция 67494399 открылась, а INSERT упал с
    "database is locked". Порядок в live_strategy с тех пор исправлен, но
    сверка нужна всё равно: между «отправили» и «записали» всегда остаётся
    окно, а любая ненайденная позиция выпадает и из горизонта, и из EV —
    молча, потому что искать её никто не станет.

    Пропущенная сделка не смещает ожидание (замок не знает, куда пойдёт
    цена), но она занимает место под потолком открытых позиций и живёт без
    горизонта. ATR восстанавливается из price_bars на момент открытия — то
    же вычисление, что в live_strategy, поэтому величина настоящая, а не
    придуманная; помечается orphan=1, чтобы разбор мог её отделить."""
    import core.price_bars as _pb
    from analyze.live_strategy import atr as _atr

    known = {r[0] for r in con.execute(
        "SELECT ticket FROM cost_observations WHERE ticket IS NOT NULL")}
    found = 0
    for pos in positions:
        t = int(pos.ticket)
        if t in known:
            continue
        opened = int(getattr(pos, "time", 0))
        c = _pb.load_candles("XAUUSD", "1h")
        i = max((k for k in range(len(c)) if c[k]["ts"] + 3600 <= opened), default=None)
        a = _atr(c, i) if i is not None else None
        note = (f"strategy=gold_oil orphan=1 atr={a:.4f} horizon_bars=12 "
                f"bar_ts={c[i]['ts']} | восстановлена сверкой: ордер прошёл, "
                f"строка журнала не записалась" if a else
                "strategy=gold_oil orphan=1 | восстановлена сверкой, ATR не определён")
        from analyze.mt5_calibration import record
        record(con, forecast_id=None, account=0, server="Ava-Demo 1-MT5", symbol="XAUUSD",
               broker_symbol=str(pos.symbol), tf="H1", direction="bullish",
               volume=float(pos.volume), ticket=t, deal_entry_price=float(pos.price_open),
               req_price=float(pos.price_open), req_ts=opened, created_ts=opened,
               order_status="sent", note=note)
        found += 1
        log.error("позиция %s была у брокера без строки в журнале — заведена сверкой", t)
        alert(f"позиция {t} ({pos.symbol} по {pos.price_open}) открылась без записи в "
              f"журнале и восстановлена сверкой. Проверьте, не повторяется ли.")
    return found


def settle(con: sqlite3.Connection) -> tuple[int, int]:
    """Закрыть сделки, дожившие до горизонта, и добрать закрывшиеся.

    🔴 19.08: горизонт не исполнялся вообще. У брокера стояли стоп и цель,
    и позиция висела до одного из них — хоть неделю. А §2 пререгистрации
    считает ожидание с горизонтом: «незакрытые по горизонту сделки входят
    по цене закрытия горизонта». Без этого замерялась бы другая величина:
    геометрия без горизонта — это RR 0.5 со стопом вдвое дальше цели, у неё
    доля выигрышных заведомо выше, и накопленное EV сравнивалось бы с
    планкой, посчитанной не для неё. Правила §3 при этом срабатывали бы
    штатно — просто не по той стратегии.

    Делается в одном сеансе с добором: правило, применённое к данным до
    добора, срабатывает на сделку позже, чем должно."""
    from analyze.mt5_calibration import Bridge, close_position, collect_closed
    from analyze.mt5_safety import our_positions

    tickets = {r[0] for r in con.execute(
        "SELECT ticket FROM cost_observations WHERE order_status='sent' "
        "AND ticket IS NOT NULL AND note LIKE '%strategy=gold_oil%'")}
    closed_by_horizon, collected = 0, 0
    try:
        with Bridge() as (mt5, conn):
            now = int(time.time())
            mine = our_positions(mt5.positions_get())
            if reconcile(con, mine):
                # заведённые сверкой тикеты нужны сразу, иначе горизонт
                # применится к ним только на следующем прогоне
                tickets |= {r[0] for r in con.execute(
                    "SELECT ticket FROM cost_observations WHERE order_status='sent' "
                    "AND ticket IS NOT NULL AND note LIKE '%strategy=gold_oil%'")}
            for pos in mine:
                if int(pos.ticket) not in tickets:
                    continue
                age = now - int(getattr(pos, "time", now))
                if age < HORIZON_SEC:
                    continue
                ok, err = close_position(conn, mt5, pos)
                if ok:
                    closed_by_horizon += 1
                    log.info("горизонт исчерпан (%.1f ч) — закрыт %s", age / 3600, pos.ticket)
                else:
                    # Молчать здесь нельзя: позиция за горизонтом продолжает
                    # жить и её исход попадёт в журнал как исход стратегии,
                    # которой он не принадлежит.
                    log.error("НЕ закрыт по горизонту %s: %s", pos.ticket, err)
                    alert(f"сделка {pos.ticket} за горизонтом ({age / 3600:.1f} ч) "
                          f"не закрывается: {err}")
            collected = collect_closed(mt5, con)
    except Exception as e:
        log.error("сведение не выполнено: %s: %s", type(e).__name__, e)
        alert(f"мост MT5 недоступен, горизонт и добор не отработали: {type(e).__name__}: {e}")
    return closed_by_horizon, collected


def closed_trades(con: sqlite3.Connection) -> list[dict]:
    """Закрытые сделки стратегии, с результатом в ATR."""
    rows = con.execute(
        "SELECT id, deal_entry_price, deal_exit_price, note, closed_ts, created_ts "
        "FROM cost_observations WHERE order_status='closed' AND note LIKE '%strategy=gold_oil%' "
        "ORDER BY closed_ts").fetchall()
    out = []
    for oid, entry, exit_, note, cts, ots in rows:
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
                    "open_ts": ots,
                    "divergence": "divergence=1" in (note or "")})
    return out


def _mean_overlap(trades: list[dict]) -> float:
    """Сколько сделок в среднем жило одновременно.

    Стратегия входит раз в час, а горизонт — 12 часов, поэтому сделки
    перекрываются по построению. Замер 25.08 на 73 сделках: в среднем 3.93
    одновременно, максимум 10."""
    ev = []
    for t in trades:
        o = t.get("open_ts") or t["closed_ts"]
        ev.append((o, 1))
        ev.append((t["closed_ts"], -1))
    ev.sort()
    span = ev[-1][0] - ev[0][0]
    if span <= 0:
        return 1.0
    cur = area = 0
    prev = ev[0][0]
    for ts, d in ev:
        area += cur * (ts - prev)
        cur += d
        prev = ts
    return max(1.0, area / span)


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
    # 🔴 25.08: CI считался как для НЕЗАВИСИМЫХ наблюдений, а сделки
    # перекрываются — одна и та же цена золота входит в исход сразу нескольких.
    # На 73 сделках наивный CI95 дал [+0.0295, +0.5759] при планке 0.036: нижняя
    # граница разошлась с планкой на 0.007 ATR. Ещё чуть-чуть — и правило §3
    # объявило бы признак ПОДТВЕРЖДЁННЫМ по перекрывающимся наблюдениям, то есть
    # по одному и тому же движению рынка, посчитанному четыре раза.
    # Поправка: эффективный размер выборки n/k, где k — среднее перекрытие;
    # SE растёт в sqrt(k) раз. С k=3.93 тот же интервал становится
    # [-0.2391, +0.8445] — то есть ноль внутри, подтверждать нечего.
    # Поправка ТОЛЬКО ужесточает: интервал шире, подтвердить труднее,
    # остановить по убытку — тоже труднее. В сторону «раньше остановиться»
    # она не двигает, поэтому не может создать ложную остановку.
    k = _mean_overlap(trades) if n > 1 else 1.0
    se_eff = se * math.sqrt(k)
    return {"n": n, "ev": mean, "total": sum(vals),
            "ci_lo": mean - 1.96 * se_eff, "ci_hi": mean + 1.96 * se_eff,
            "ci_lo_naive": mean - 1.96 * se, "ci_hi_naive": mean + 1.96 * se,
            "overlap": k, "n_eff": n / k,
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
    return "продолжать", (f"n={m['n']}, EV={m['ev']:+.4f}, CI95 [{m['ci_lo']:+.4f}, "
                         f"{m['ci_hi']:+.4f}] (перекрытие {m.get('overlap', 1):.1f}x, "
                         f"n_eff={m.get('n_eff', m['n']):.0f})")


def stop_trading(reason: str) -> None:
    """Останавливает таймер стратегии. Обратимо одной командой — намеренно
    не удаляем юнит, чтобы решение можно было пересмотреть осознанно."""
    subprocess.run(["systemctl", "--user", "disable", "--now", "sbf-live-strategy.timer"],
                   capture_output=True)
    log.error("ТОРГОВЛЯ ОСТАНОВЛЕНА: %s", reason)


def alert(text: str) -> None:
    """В @gdenigi_bot, через общую очередь — тот же канал, что и у прогнозов."""
    from analyze.outbox import enqueue_ops
    if enqueue_ops(f"📉 strategy_monitor: {text}") is None:
        log.error("алерт ушёл запасным каналом или не ушёл вовсе: %s", text)


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
    by_horizon, collected = settle(con)
    if by_horizon or collected:
        log.info("закрыто по горизонту=%d добрано=%d", by_horizon, collected)
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
