#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/engine/run.py — один прогон движка.

Порядок шагов не произвольный:

  1. СВЕДЕНИЕ прежде решений. Правила остановки считаются по журналу, и
     если сначала открывать новое, а потом сводить старое, стоп-кран
     сработает на сделку позже, чем должен. Тот же порядок и по той же
     причине, что в strategy_monitor.
  2. Сбор сигналов из всех источников.
  3. Решение по каждому: дедуп -> состояние стратегии -> геометрия ->
     размер -> портфельные лимиты -> снос цены.
  4. Исполнение принятых.

Каждый шаг возвращает результат, а не бросает: падение одного источника
или одного символа не имеет права отменить весь цикл.

Коды выхода: 0 — прогон полный, 1 — с пропусками, 2 — мост недоступен,
3 — не смогли даже записать журнал (вот это уже инцидент).
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

sys.path.insert(0, "/mnt/sbfdata/sbf-platform/market_intel")

from analyze.engine import execution, ledger, risk, sources          # noqa: E402
from analyze.engine.contracts import Decision, ST_HALTED, ST_LIVE, ST_SHADOW  # noqa: E402
from analyze.mt5_safety import SafetyRefusal                          # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | [engine] %(message)s")
log = logging.getLogger("engine")


def decide(con, s, equity, symbol_info, tick, default_status: str, *,
           mt5=None, bsym: str = "", free_margin: float = 0.0) -> Decision:
    """Все запреты по одному сигналу. Возвращает Decision всегда — отказ
    это тоже решение, и он обязан попасть в журнал с причиной.

    Порядок дешёвых проверок перед дорогими: дедуп и геометрия считаются
    у нас, `margin_gate` ходит в терминал."""
    if ledger.already_taken(con, s.dedup_key):
        return Decision(s, False, "dedup: по этому основанию уже входили")
    state = ledger.ensure_strategy(con, s.strategy, default_status)
    market_price = None
    if tick is not None:
        market_price = float(tick.ask if s.is_long else tick.bid)
    try:
        risk.strategy_gate(state)
        risk.geometry_gate(s)
        risk.cost_gate(s, tick)
        risk.broker_barrier_gate(s, symbol_info, tick)
        volume, risk_money = risk.position_volume(s, equity, symbol_info)
        risk.opposite_open(con, s)
        risk.portfolio_gate(con, s, equity, risk_money)
        if market_price is not None:
            risk.drift_gate(s, market_price)
        if mt5 is not None and market_price is not None:
            risk.margin_gate(mt5, bsym, volume, s.is_long, market_price, free_margin)
    except risk.RiskRefusal as e:
        return Decision(s, False, f"{e.status}: {e}")
    return Decision(s, True, "принят", volume=volume, risk_money=risk_money)


def run(*, dry: bool, live: bool, enabled: list[str] | None, verbose: bool) -> int:
    con = ledger.connect()
    ledger.init(con)

    default_status = ST_LIVE if live else ST_SHADOW
    exit_code = 0

    try:
        with execution.Bridge() as (mt5, conn):
            execution.preflight_account(mt5)

            st = execution.settle(con, mt5, conn)
            log.info("сведение: закрыто=%d по горизонту=%d потеряшек=%d",
                     st["closed"], st["by_horizon"], st["orphans"])
            for name, why in st["halted"]:
                log.error("остановлена %s: %s", name, why)

            sh = execution.settle_shadow(con)
            if sh["closed"]:
                log.info("теневых разрешено: %d", sh["closed"])

            mg = execution.manage_open(con, mt5, conn)
            if mg["moved"] or mg["errors"]:
                log.info("сопровождение: стопов перенесено=%d ошибок=%d",
                         mg["moved"], mg["errors"])

            acc = mt5.account_info()
            equity = float(getattr(acc, "equity", 0.0) or 0.0)
            free_margin = float(getattr(acc, "margin_free", 0.0) or 0.0)
            server = getattr(acc, "server", None)
            if equity <= 0:
                log.error("equity не получена — решения не принимаются")
                return 2

            signals = sources.collect(con, enabled)
            log.info("сигналов собрано: %d (источники: %s)", len(signals),
                     ", ".join(sorted({s.strategy for s in signals})) or "нет")

            taken = 0
            for s in signals:
                try:
                    bsym = execution.broker_symbol(con, s.symbol, server)
                except SafetyRefusal as e:
                    ledger.record_decision(con, Decision(s, False, f"{e.status}: {e}"))
                    exit_code = 1
                    continue
                mt5.symbol_select(bsym, True)
                si = mt5.symbol_info(bsym)
                tick = mt5.symbol_info_tick(bsym)
                if si is None:
                    ledger.record_decision(
                        con, Decision(s, False, f"bad_symbol: {bsym} нет у брокера"))
                    exit_code = 1
                    continue

                d = decide(con, s, equity, si, tick, default_status,
                           mt5=mt5, bsym=bsym, free_margin=free_margin)
                if verbose or d.accepted:
                    log.info("%s %s/%s %s -> %s", s.strategy, s.symbol, s.tf,
                             s.direction, d.reason)
                if dry and d.accepted:
                    # 🔴 В журнал уходит НЕ «принят»: dry-run ордеров не шлёт,
                    # и записать его как состоявшийся вход значит соврать
                    # самим себе. Ровно на этом 28.08 первый боевой прогон
                    # отвалился весь: 16 сигналов из 21 упёрлись в дедуп по
                    # следам предыдущего dry-run.
                    d.accepted = False
                    d.reason = (f"dry_run: вошли бы объёмом {d.volume:.2f} "
                                f"при риске {d.risk_money:.2f}")
                sid = ledger.record_decision(con, d)
                if not d.accepted:
                    if dry:
                        log.info("  dry-run: объём %.2f, риск %.2f, стоп %.5f цель %.5f",
                                 d.volume, d.risk_money, s.stop, s.target)
                    continue

                strat_live = ledger.ensure_strategy(
                    con, s.strategy, default_status)["status"] == ST_LIVE
                ok, msg = execution.execute(con, mt5, conn, sid, d,
                                            live=strat_live, bsym=bsym)
                log.info("  исполнение (%s): %s", "live" if strat_live else "shadow", msg)
                if ok:
                    taken += 1
                else:
                    exit_code = 1

            log.info("взято сделок: %d, equity %.2f", taken, equity)
    except SafetyRefusal as e:
        log.error("предохранитель: %s — %s", e.status, e)
        return 2
    except Exception as e:                                  # noqa: BLE001
        log.error("мост/цикл упал: %s: %s", type(e).__name__, e)
        return 2
    finally:
        con.close()
    return exit_code


def report() -> int:
    con = ledger.connect()
    ledger.init(con)
    rows = ledger.strategy_report(con)
    if not rows:
        print("журнал движка пуст")
        return 0
    print(f"{'стратегия':26}{'режим':9}{'сделок':>7}{'W':>5}{'L':>5}"
          f"{'сумма R':>10}{'пик R':>9}{'просадка':>10}{'откр':>6}")
    for r in rows:
        dd = (r["cum_r"] or 0) - (r["peak_r"] or 0)
        print(f"{r['strategy']:26}{r['status']:9}{r['n_closed']:>7}{r['wins']:>5}"
              f"{r['losses']:>5}{r['cum_r'] or 0:>10.2f}{r['peak_r'] or 0:>9.2f}"
              f"{dd:>10.2f}{r['open']:>6}")
        if r["halt_reason"]:
            print(f"    остановлена: {r['halt_reason']}")
    n, acc = con.execute("SELECT count(*), sum(accepted) FROM engine_signals").fetchone()
    print(f"\nсигналов всего {n}, принято {acc or 0}")
    print("причины отказов:")
    for reason, k in con.execute(
            "SELECT substr(reason,1,instr(reason||':',':')-1) rr, count(*) FROM engine_signals "
            "WHERE accepted=0 GROUP BY rr ORDER BY count(*) DESC LIMIT 12"):
        print(f"   {reason or '?':24} {k}")
    con.close()
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Торговый движок SBF: сигналы -> риск -> ордера")
    p.add_argument("--dry-run", action="store_true",
                   help="решения принимаются и пишутся в журнал, ордера не шлются")
    p.add_argument("--live", action="store_true",
                   help="новые стратегии стартуют сразу в режиме live (иначе shadow)")
    p.add_argument("--sources", default="",
                   help="через запятую: alpha_forecast,patterns,macro,gate")
    p.add_argument("--report", action="store_true", help="показать сводку и выйти")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    if a.report:
        sys.exit(report())
    enabled = [x.strip() for x in a.sources.split(",") if x.strip()] or None
    sys.exit(run(dry=a.dry_run, live=a.live, enabled=enabled, verbose=a.verbose))


if __name__ == "__main__":
    main()
