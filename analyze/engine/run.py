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

from analyze.engine import accounts, execution, explain, ledger, notify, risk, sources          # noqa: E402
from analyze.engine.contracts import Decision, ST_HALTED, ST_LIVE, ST_SHADOW  # noqa: E402
from analyze.mt5_safety import SafetyRefusal                          # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | [engine] %(message)s")
log = logging.getLogger("engine")


ENGINE_DIR = "analyze/engine"


def dirty_engine_files() -> list[str]:
    """Файлы движка, изменённые в рабочем дереве и не закоммиченные.

    🔴 14.09. sbf-engine.service запускает код ПРЯМО ИЗ рабочего дерева, и
    /home/sbf/market_intel — симлинк на него же. В тот день правка риск-модуля
    уехала в бой на полпути: прогон в 15:03 подхватил снятый запрет на
    встречные входы раньше, чем были дописаны тесты. Обошлось, но повезло.

    Дерево общее для нескольких чатов сразу — в момент находки в нём было 39
    незакоммиченных файлов от параллельной работы. То есть это не разовая
    неосторожность, а устройство: любая правка здесь через час торгует.

    Смотрим ТОЛЬКО на файлы движка. Остальное дерево живёт своей жизнью, и
    останавливать торговлю из-за правки в вёрстке сайта — это тот самый
    ложный отказ, который потом отключают целиком.

    Отказ git'а не блокирует торговлю: предохранитель полезный, но не
    критичный, и падать из-за него хуже, чем не сработать.

    🔴 29.09, ДОРОГОЙ УРОК. Этот предохранитель ОСТАНОВИЛ ТОРГОВЛЮ НА
    ОДИННАДЦАТЬ ДНЕЙ. Смотрел он на весь каталог движка, а в каталоге лежит
    `leg_correlation.json` — файл, который система пересчитывает САМА
    еженедельным таймером sbf-leg-corr. После пересчёта 20.09 файл стал
    «незакоммиченной правкой», входы приостановились, и так 25+ прогонов
    подряд: последняя сделка 18.09, дальше тишина.

    Снаружи это выглядело как «торги остановились», и искать причину пошли
    бы куда угодно, только не в защиту от недоделанных правок.

    Правило теперь: смотреть ТОЛЬКО на исходники (*.py). Данные, которые
    движок порождает сам, правкой кода не являются по определению. Это не
    ослабление — защита ровно от того, ради чего писалась: полуготовый код.

    Общий урок, который стоит дороже конкретной строки: предохранитель,
    способный молча остановить основную работу, опаснее того, от чего он
    защищает, — если у него нет собственного срока годности. Поэтому ниже
    ещё и ограничение по времени."""
    import subprocess
    try:
        out = subprocess.run(
            # quotepath=false: иначе git экранирует кириллицу в именах
            # восьмеричными кодами, и алерт в боте приходит нечитаемым.
            ["git", "-C", "/mnt/sbfdata/sbf-platform/market_intel",
             "-c", "core.quotepath=false",
             "status", "--porcelain", "--", ENGINE_DIR],
            capture_output=True, text=True, timeout=20)
        if out.returncode != 0:
            return []
        files = [ln[3:].strip() for ln in out.stdout.splitlines() if ln.strip()]
        return [f for f in files if f.endswith(".py")]
    except Exception:                                           # noqa: BLE001
        return []


def market_price_of(s, tick):
    """Цена, по которой реально входим: ask на покупку, bid на продажу."""
    if tick is None:
        return None
    return float(tick.ask if s.is_long else tick.bid)


def decide(con, s, equity, symbol_info, tick, default_status: str, *,
           mt5=None, bsym: str = "", free_margin: float = 0.0,
           acc=None, dry: bool = False) -> Decision:
    """Все запреты по одному сигналу. Возвращает Decision всегда — отказ
    это тоже решение, и он обязан попасть в журнал с причиной.

    Порядок дешёвых проверок перед дорогими: дедуп и геометрия считаются
    у нас, `margin_gate` ходит в терминал."""
    name = acc.name if acc else "demo"
    if ledger.already_taken(con, s.dedup_key, name):
        return Decision(s, False, "dedup: по этому основанию уже входили")
    state = ledger.ensure_strategy(con, s.strategy, default_status, name,
                                   create=not dry)
    market_price = None
    if tick is not None:
        market_price = float(tick.ask if s.is_long else tick.bid)
    try:
        risk.strategy_gate(state)
        risk.geometry_gate(s)
        risk.cost_gate(s, tick)
        risk.broker_barrier_gate(s, symbol_info, tick)
        volume, risk_money = risk.position_volume(
            s, equity, symbol_info, acc.risk_per_trade if acc else None)
        # 🔴 14.09: здесь стоял запрет `opposite_open` — встречный вход по тому
        # же инструменту отклонялся ради чистоты измерения. Снят: R считается
        # по ценам самой сделки и от чужой позиции не зависит (см.
        # risk.crossing_trade). Вместо запрета — нетто-учёт в portfolio_gate
        # и пометка пересечения в журнале.
        risk.portfolio_gate(con, s, equity, risk_money, name)
        if market_price is not None:
            risk.drift_gate(s, market_price)
        if mt5 is not None and market_price is not None:
            risk.margin_gate(mt5, bsym, volume, s.is_long, market_price, free_margin)
    except risk.RiskRefusal as e:
        return Decision(s, False, f"{e.status}: {e}")
    return Decision(s, True, "принят", volume=volume, risk_money=risk_money)


def run(*, dry: bool, live: bool, enabled: list[str] | None, verbose: bool,
        account: str = "demo") -> int:
    acc = accounts.get(account)
    con = ledger.connect()
    ledger.init(con)
    log.info("счёт %s: риск %.2f%% на сделку, инструменты %s",
             acc.name, acc.risk_per_trade * 100, ", ".join(acc.symbols))

    default_status = ST_LIVE if live else ST_SHADOW
    exit_code = 0

    # Правка в дереве приостанавливает НОВЫЕ входы, но не сведение и не
    # сопровождение: незакрытые позиции нельзя бросать из-за того, что
    # кто-то правит код. Останавливаем ровно то, что можно отложить.
    dirty = dirty_engine_files() if not dry else []
    if dirty:
        log.warning("ПРАВКА В ДЕРЕВЕ: %s — новые входы приостановлены, "
                    "сведение и сопровождение работают", ", ".join(dirty))
        # 🔴 29.09: НЕ ЧАЩЕ РАЗА В СУТКИ. Прежняя версия слала алерт каждый
        # прогон — 48 штук в день на два счёта, 811 за двенадцать дней. Все
        # доставлены, и именно поэтому не прочитаны: предохранитель кричал
        # так часто, что сам сделал себя фоном. Сообщение, которое повторяется
        # каждый час без изменений, — это не предупреждение, а шум.
        try:
            from analyze.outbox import enqueue_ops
            since = con.execute(
                "SELECT max(created_ts) FROM outbox WHERE payload LIKE "
                "'%входы приостановлены%'").fetchone()
            last = (since and since[0]) or 0
            hours = (time.time() - last) / 3600.0 if last else 1e9
            if hours >= 24:
                # Сколько это уже длится — по дате первой блокировки подряд.
                age = (f", и это длится уже {int(hours / 24)} сут"
                       if last and hours > 48 else "")
                enqueue_ops(
                    f"⏸ Движок: новые входы приостановлены{age} — в дереве "
                    f"незакоммиченные ИСХОДНИКИ движка:\n" +
                    "\n".join(f"· {f}" for f in dirty) +
                    "\n\nСведение и сопровождение работают как обычно. "
                    "Закоммитьте или откатите правку, чтобы вернуть входы.\n"
                    "Повторю не раньше чем через сутки.")
        except Exception as e:                                  # noqa: BLE001
            log.warning("алерт о правке не ушёл: %s", e)

    try:
        with execution.Bridge(acc.port, acc.lock) as (mt5, conn):
            execution.preflight_account(mt5, acc)

            # 🔴 Снятие остановок, сделанных по уже не действующему порогу.
            # 07.09 порог подняли с 8 до 20 R, а стратегии, остановленные до
            # правки, остались стоять: правило изменилось, последствия нет.
            # pattern_break_retest простоял шесть дней в плюсе (+11 R), и за
            # это время движок отверг 851 сигнал с «стратегия остановлена».
            for name, dd, old, new in ledger.resume_stale_halts(
                    con, acc.max_drawdown_r, acc.name):
                log.warning("ВОЗОБНОВЛЕНА %s: просадка %.2fR укладывается в нынешний "
                            "предел %.0fR (была остановлена по порогу %s)",
                            name, dd, new, f"{old:.0f}R" if old else "неизвестному")

            st = execution.settle(con, mt5, conn, acc.name, acc.max_drawdown_r)
            log.info("сведение: закрыто=%d по горизонту=%d потеряшек=%d",
                     st["closed"], st["by_horizon"], st["orphans"])
            for name, why in st["halted"]:
                log.error("остановлена %s: %s", name, why)

            sh = execution.settle_shadow(con, acc.name, acc.max_drawdown_r)
            if sh["closed"]:
                log.info("теневых разрешено: %d", sh["closed"])

            mg = execution.manage_open(con, mt5, conn, acc.name)
            if mg["moved"] or mg["errors"]:
                log.info("сопровождение: стопов перенесено=%d ошибок=%d",
                         mg["moved"], mg["errors"])

            # 🔴 Имя ДРУГОЕ, чем у профиля счёта: 16.09 профиль назывался
            # `acc`, и эта строка его затирала — сухой прогон реального счёта
            # упал с «AccountInfo object has no attribute symbols».
            ainfo = mt5.account_info()
            equity = float(getattr(ainfo, "equity", 0.0) or 0.0)
            free_margin = float(getattr(ainfo, "margin_free", 0.0) or 0.0)
            server = getattr(ainfo, "server", None)
            if equity <= 0:
                log.error("equity не получена — решения не принимаются")
                return 2

            signals = sources.collect(con, enabled)
            before = len(signals)
            # Набор инструментов — свойство счёта: на реальном нет золота
            # (не влезает в минимальный лот) и пока нет газа.
            signals = [s for s in signals if s.symbol in acc.symbols]
            if before != len(signals):
                log.info("отсеяно не по профилю счёта: %d", before - len(signals))
            log.info("сигналов собрано: %d (источники: %s)", len(signals),
                     ", ".join(sorted({s.strategy for s in signals})) or "нет")

            taken = 0
            for s in signals:
                try:
                    bsym = execution.broker_symbol(con, s.symbol, server)
                except SafetyRefusal as e:
                    ledger.record_decision(con, Decision(s, False, f"{e.status}: {e}"), acc.name)
                    exit_code = 1
                    continue
                mt5.symbol_select(bsym, True)
                si = mt5.symbol_info(bsym)
                tick = mt5.symbol_info_tick(bsym)
                if si is None:
                    ledger.record_decision(
                        con, Decision(s, False, f"bad_symbol: {bsym} нет у брокера"), acc.name)
                    exit_code = 1
                    continue

                d = decide(con, s, equity, si, tick, default_status,
                           mt5=mt5, bsym=bsym, free_margin=free_margin, acc=acc,
                           dry=dry)
                if dirty and d.accepted:
                    d.accepted = False
                    d.reason = ("maintenance: правка движка в дереве, "
                                "новые входы приостановлены")
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
                sid = ledger.record_decision(con, d, acc.name)
                if not d.accepted:
                    if dry:
                        log.info("  dry-run: объём %.2f, риск %.2f, стоп %.5f цель %.5f",
                                 d.volume, d.risk_money, s.stop, s.target)
                    continue

                strat_live = ledger.ensure_strategy(
                    con, s.strategy, default_status, acc.name)["status"] == ST_LIVE
                ok, msg = execution.execute(con, mt5, conn, sid, d,
                                            live=strat_live, bsym=bsym,
                                            account=acc.name)
                log.info("  исполнение (%s): %s", "live" if strat_live else "shadow", msg)
                if ok:
                    taken += 1
                    if strat_live:
                        # Чек-лист входа — ЕДИНСТВЕННОЕ сообщение по открытию.
                        # Сознательно без цен входа, стопа и цели: с ними это
                        # была бы инструкция «войди сюда, стоп туда», то есть
                        # сигнал. Нужно обратное — показать устройство решения.
                        try:
                            spread = (abs(float(tick.ask) - float(tick.bid))
                                      if tick else 0.0)
                            notify.send(con, explain.checklist(
                                con, s, volume=d.volume, risk_money=d.risk_money,
                                equity=equity, spread=spread,
                                market_price=market_price_of(s, tick)),
                                "чек-лист входа")
                        except Exception as e:            # noqa: BLE001
                            # Чек-лист — не повод ронять торговый цикл:
                            # сделка важнее письма.
                            log.warning("чек-лист не собрался: %s", e)
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


def report(account: str = "demo") -> int:
    con = ledger.connect()
    ledger.init(con)
    rows = ledger.strategy_report(con, account)
    print(f"счёт: {account}\n")
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
    n, acc = con.execute("SELECT count(*), sum(accepted) FROM engine_signals "
                         "WHERE account=?", (account,)).fetchone()
    print(f"\nсигналов всего {n}, принято {acc or 0}")
    print("причины отказов:")
    for reason, k in con.execute(
            "SELECT substr(reason,1,instr(reason||':',':')-1) rr, count(*) FROM engine_signals "
            "WHERE accepted=0 AND account=? GROUP BY rr ORDER BY count(*) DESC LIMIT 12",
            (account,)):
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
    p.add_argument("--account", default="demo",
                   help="профиль счёта: demo | real (analyze/engine/accounts.py)")
    a = p.parse_args()
    if a.report:
        sys.exit(report(a.account))
    enabled = [x.strip() for x in a.sources.split(",") if x.strip()] or None
    sys.exit(run(dry=a.dry_run, live=a.live, enabled=enabled, verbose=a.verbose,
                 account=a.account))


if __name__ == "__main__":
    main()
