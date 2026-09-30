#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/mt5_healthcheck.py — один прогон после перезапуска MT5/перемонтирования диска.

Зачем отдельный скрипт: 19-20.08 мост крашлупился 973 раза, потому что диск
/mnt/D был отмонтирован, а стартовый скрипт вместо отказа пытался создать
каталог бутылки. Systemd видел «перезапускаю», журнал молчал по существу, а
внешне всё выглядело как «MT5 иногда лежит». Проверять надо не «поднялся ли
процесс», а «отдаёт ли он ПРАВИЛЬНЫЕ данные» — это разные вопросы.

Запуск:  .venv/bin/python3 -m tools.mt5_healthcheck
Код возврата: 0 — всё чисто, 1 — есть красное.
"""
from __future__ import annotations

import datetime
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
BOTTLE = Path("/mnt/D/Bottles/Trading")
TF_SEC = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}
bad = []


def say(ok: bool, what: str, detail: str = "") -> None:
    print(f"  {'✅' if ok else '🔴'} {what}" + (f" — {detail}" if detail else ""))
    if not ok:
        bad.append(what)


def main() -> int:
    print("\n── 1. диск и бутылка ──")
    mounted = os.path.ismount("/mnt/D")
    say(mounted, "/mnt/D примонтирован",
        "" if mounted else "БЕЗ ЭТОГО ОСТАЛЬНОЕ БЕССМЫСЛЕННО: мост будет крашлупиться")
    say(BOTTLE.is_dir(), f"бутылка {BOTTLE} на месте")

    print("\n── 2. служба моста ──")
    r = subprocess.run(["systemctl", "--user", "show", "sbf-mt5-bridge.service",
                        "--property=ActiveState,NRestarts"], capture_output=True, text=True)
    props = dict(x.split("=", 1) for x in r.stdout.strip().splitlines() if "=" in x)
    say(props.get("ActiveState") == "active", "sbf-mt5-bridge активен",
        props.get("ActiveState", "?"))
    n_restarts = int(props.get("NRestarts", 0) or 0)
    say(n_restarts < 5, "мост не перезапускается по кругу", f"перезапусков: {n_restarts}")

    print("\n── 3. терминал отвечает ──")
    mt5 = None
    try:
        import rpyc
        conn = rpyc.classic.connect("127.0.0.1", 18812, keepalive=True)
        mt5 = conn.modules["MetaTrader5"]
        ok = mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe", timeout=60000)
        say(bool(ok), "MetaTrader5.initialize()", str(mt5.last_error()))
        acc, term = mt5.account_info(), mt5.terminal_info()
        say(acc is not None, "account_info()", f"счёт {getattr(acc,'login','?')} "
            f"{getattr(acc,'server','?')} equity={getattr(acc,'equity','?')}")
        say(getattr(acc, "trade_mode", 1) == 0, "счёт ДЕМО (trade_mode=0)")
        say(bool(getattr(term, "connected", False)), "терминал подключён к серверу")
        say(bool(getattr(term, "trade_allowed", False)), "AutoTrading включён",
            "" if getattr(term, "trade_allowed", False) else "включается только в GUI терминала")
    except Exception as e:
        say(False, "мост отвечает", f"{type(e).__name__}: {e}")

    print("\n── 4. символы и свежесть котировок ──")
    if mt5 is not None:
        try:
            from mt5_config import SYMBOL_MAP
            now = time.time()
            for our, broker in SYMBOL_MAP.items():
                if not mt5.symbol_select(broker, True):
                    say(False, f"{our} ({broker})", "symbol_select вернул False")
                    continue
                t = mt5.symbol_info_tick(broker)
                age = now - getattr(t, "time", 0)
                # выходные — не повод краснеть; поэтому только будни
                weekday = datetime.datetime.now().weekday() < 5
                say(age < 900 or not weekday, f"{our} ({broker}) тик свежий",
                    f"{age/60:.0f} мин назад, bid={getattr(t,'bid','?')}")
        except Exception as e:
            say(False, "обход символов", f"{type(e).__name__}: {e}")

    print("\n── 5. бары в price_bars (главное: терминал после рестарта досинхронизирует ТФ не сразу) ──")
    con = sqlite3.connect(str(BOT_DB), timeout=30)
    now = int(time.time())
    for tf, sec in TF_SEC.items():
        row = con.execute("SELECT symbol, MAX(ts) FROM price_bars WHERE tf=? AND symbol='EURUSD'",
                          (tf,)).fetchone()
        last = row[1] or 0
        lag = (now - last) / 60
        # допуск: два бара + запас на доливку
        limit = (2 * sec + 900) / 60
        say(lag <= limit, f"EURUSD {tf} свежий",
            f"последний бар {datetime.datetime.fromtimestamp(last):%d.%m %H:%M}, "
            f"отставание {lag:.0f} мин (предел {limit:.0f})")

    print("\n── 6. торговый контур ──")
    open_rows = con.execute(
        "SELECT COUNT(*) FROM cost_observations WHERE order_status='sent' "
        "AND note LIKE '%strategy=gold_oil%'").fetchone()[0]
    print(f"  ℹ️  открытых сделок стратегии в журнале: {open_rows}")
    if mt5 is not None:
        try:
            from analyze.mt5_safety import our_positions
            live = our_positions(mt5.positions_get())
            say(len(live) == open_rows, "журнал сходится с брокером",
                f"у брокера {len(live)}, в журнале {open_rows}"
                + ("" if len(live) == open_rows else " — прогоните strategy_monitor, сверка подберёт"))
            for p in live:
                print(f"      {p.ticket} {p.symbol} вход={p.price_open} sl={p.sl} tp={p.tp} "
                      f"итог={p.profit:+.2f} возраст={(now-int(p.time))/3600:.1f} ч")
        except Exception as e:
            say(False, "сверка позиций", f"{type(e).__name__}: {e}")
    con.close()

    print("\n" + ("✅ всё чисто" if not bad else f"🔴 проблемы ({len(bad)}): " + "; ".join(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
