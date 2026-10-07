#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ops/pulse.py — пульс торговли. Один вопрос, один ответ: ИДУТ торги или НЕТ.

🔴 Зачем это существует. С 18 по 29 сентября 2026 торговля стояла одиннадцать
дней, и я узнал об этом от владельца, а не от системы. При этом система
сообщала об отказе исправно: 48 сообщений в сутки, 811 за двенадцать дней,
все доставлены. Именно поэтому ни одно не было прочитано.

Вывод, из которого сделан этот файл: надзор ломается не от нехватки
сообщений, а от их однообразия. Поэтому здесь ровно наоборот:

  · СОСТОЯНИЕ, а не события. Одна строка: «торги идут» или «не идут, потому
    что ...». Не отчёт о прогоне, не список ошибок — вердикт.
  · Сообщение уходит, когда вердикт МЕНЯЕТСЯ, а не когда он повторяется.
    Плюс один раз в сутки — «жив», чтобы молчание нельзя было спутать с
    исправностью.
  · Что можно поднять, пульс поднимает сам: мёртвый мост рестартится, и об
    этом сообщается фактом, а не просьбой.

Ограничение, которое надо знать: пульс отвечает на вопрос «доходит ли дело
до ордера», а не «хорошо ли торгует». Прибыльность — не его дело.

Запуск: раз в час таймером sbf-pulse.timer. Без аргументов — проверить и
сообщить при смене вердикта. С --говори — сообщить всегда (для проверки).
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/mnt/sbfdata/sbf-platform/market_intel")
sys.path.insert(0, str(ROOT))

STATE = ROOT / "data" / "engine" / "pulse_state.json"

# Столько часов без НОВОЙ сделки считается нормой, а не отказом. Взято не из
# головы: в спокойные периоды движок штатно молчит, поэтому «сделок нет»
# само по себе не диагноз. Отказ — это когда не работает ПУТЬ до ордера.
# Поэтому по сделкам порог мягкий, а по прогонам и мосту — жёсткий.
TRADE_SILENCE_ALARM_H = 72.0
# Прогон обязан быть: таймер часовой, два пропуска — уже неисправность.
RUN_SILENCE_ALARM_H = 3.0

ACCOUNT_UNITS = {
    "demo": ("sbf-engine.service", "sbf-mt5-bridge.service", 18812),
    "real": ("sbf-engine@real.service", "sbf-mt5-bridge-real.service", 18813),
}


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    """systemctl --user с явной шиной.

    🔴 Без XDG_RUNTIME_DIR/DBUS_SESSION_BUS_ADDRESS `systemctl --user`
    возвращает 0, ничего не сделав — на этом уже горели: sbf-start-all.sh
    рапортовал об успехе, не запустив ни одного юнита."""
    env = dict(os.environ)
    uid = os.getuid()
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
    return subprocess.run(["systemctl", "--user", *args],
                          capture_output=True, text=True, timeout=60, env=env)


def port_alive(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def last_run_age_h(unit: str) -> float | None:
    """Часы с последнего запуска юнита. None — если запусков не было вовсе."""
    out = _systemctl("show", unit, "-p", "ExecMainExitTimestampMonotonic",
                     "-p", "InactiveExitTimestamp", "--value")
    lines = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    for ln in lines:
        if ln in ("0", "n/a", ""):
            continue
        try:
            import datetime as dt
            ts = subprocess.run(["date", "-d", ln, "+%s"], capture_output=True,
                                text=True, timeout=10)
            if ts.returncode == 0:
                return (time.time() - int(ts.stdout.strip())) / 3600.0
            del dt
        except Exception:                                        # noqa: BLE001
            continue
    return None


def check_account(account: str) -> tuple[bool, list[str], list[str]]:
    """(идут ли торги, причины отказа, что починено на месте)."""
    engine_unit, bridge_unit, port = ACCOUNT_UNITS[account]
    bad: list[str] = []
    fixed: list[str] = []

    if not port_alive(port):
        # Самовосстановление. Мост — единственная точка, где «поднять
        # заново» безопасно и однозначно: он не принимает решений, он
        # соединение. Именно его смерть 18.09 остановила реальный счёт на
        # одиннадцать дней при том, что юнита у него тогда вообще не было.
        r = _systemctl("restart", bridge_unit)
        time.sleep(25)
        if port_alive(port):
            fixed.append(f"{bridge_unit} был мёртв — поднят, порт {port} слушает")
        else:
            bad.append(f"мост {bridge_unit} не поднимается (порт {port} молчит, "
                       f"rc={r.returncode})")

    en = _systemctl("is-enabled", f"{engine_unit.replace('.service', '.timer')}")
    if en.stdout.strip() != "enabled":
        bad.append(f"таймер движка {account} не enabled ({en.stdout.strip()!r})")

    age = last_run_age_h(engine_unit)
    if age is None:
        bad.append(f"движок {account} не запускался ни разу")
    elif age > RUN_SILENCE_ALARM_H:
        bad.append(f"движок {account} не запускался {age:.1f} ч")

    return (not bad), bad, fixed


def journal_state() -> tuple[dict, list[str]]:
    """Что видно в журнале: последняя сделка, открытые, остановленные."""
    from analyze.engine import ledger
    bad: list[str] = []
    con = ledger.connect()
    info: dict = {}
    for acc in ("demo", "real"):
        row = con.execute(
            "SELECT max(req_ts) FROM engine_trades WHERE account=? AND mode='live'",
            (acc,)).fetchone()
        last = (row and row[0]) or 0
        age = (time.time() - last) / 3600.0 if last else None
        # 🔴 Только mode='live'. Теневые сделки тоже «открыты», но у брокера
        # их нет — и первая же версия пульса показала 11 против 7 у брокера.
        # Число, которое не сходится с терминалом, хуже отсутствующего:
        # по нему нельзя понять, расходится журнал с брокером или нет.
        opened = con.execute(
            "SELECT count(*) FROM engine_trades "
            "WHERE account=? AND status='open' AND mode='live'",
            (acc,)).fetchone()[0]
        halted = [r[0] for r in con.execute(
            "SELECT strategy FROM engine_strategy_state "
            "WHERE account=? AND status='halted'", (acc,))]
        info[acc] = {"last_trade_h": age, "open": opened, "halted": halted}
        if age is not None and age > TRADE_SILENCE_ALARM_H:
            bad.append(f"по {acc} нет новых сделок {age / 24:.1f} сут")
        if halted:
            info[acc]["halted_note"] = ", ".join(halted)
    return info, bad


# Котировка старше этого — уже не котировка. Выходные учитываются отдельно:
# в субботу-воскресенье рынок стоит законно, и тревожить незачем.
QUOTE_STALE_ALARM_MIN = 90.0

# Канонический символ -> как он зовётся у брокера этого счёта берём из
# mt5_config, а не угадываем: у Daoti имена с точкой.
PROBE_SYMBOL = "EURUSD"


def feed_fresh(account: str) -> list[str]:
    """Идут ли по счёту ЖИВЫЕ котировки.

    🔴 07.10, И ЭТО САМЫЙ ДОРОГОЙ ПРОПУСК ПУЛЬСА. Реальный счёт стоял СЕМЬ
    СУТОК: с 30.09 19:54 брокер перестал присылать тики, и любой запрос —
    перенос стопа, закрытие по горизонту, новый вход — отбивался с
    `retcode=10006`, потому что был построен на недельных ценах.

    Пульс всё это время писал «торги идут». Он проверял порт моста, живость
    юнита и наличие прогонов — и всё это было в порядке. Терминал отвечал
    `connected=True`. Не работали только САМИ ДАННЫЕ.

    Это тот же класс отказа, что одиннадцатидневный простой 18-29.09:
    исправна каждая часть, не исправно целое. Разница в том, что тогда
    отсутствовал надзор, а здесь надзор был и смотрел не туда. Проверять
    надо не «жив ли канал», а «свежо ли то, что по нему пришло».

    Отдельно стоит знать: equity, которую показывает терминал в таком
    состоянии, посчитана по мёртвым ценам и НЕ является правдой. 07.10
    терминал реала показывал +38.60 плавающего по ценам недельной
    давности — число, по которому нельзя судить ни о чём."""
    from analyze.mt5_calibration import Bridge
    from analyze.engine.accounts import ACCOUNTS
    from mt5_config import symbol_map_for

    acc = ACCOUNTS[account]
    try:
        with Bridge(port=acc.port, lock=acc.lock) as (m, conn):
            srv = m.account_info().server
            sym = symbol_map_for(srv).get(PROBE_SYMBOL, PROBE_SYMBOL)
            tick = m.symbol_info_tick(sym)
            if tick is None:
                return [f"{account}: брокер не отдаёт тик по {sym}"]
            age_min = (time.time() - float(tick.time)) / 60.0
    except Exception as e:                                       # noqa: BLE001
        return [f"{account}: котировки не проверить — {e}"]

    # Выходные: рынок стоит законно. Пятница 21:00 UTC — воскресенье 21:00 UTC
    # грубо; запас в сутки с каждой стороны, чтобы не спорить с праздниками.
    import datetime as dt
    wd = dt.datetime.now(dt.timezone.utc).weekday()      # 5=сб, 6=вс
    if wd >= 5 and age_min < 3 * 24 * 60:
        return []
    if age_min > QUOTE_STALE_ALARM_MIN:
        return [f"{account}: КОТИРОВКИ МЁРТВЫЕ — последний тик по {sym} "
                f"{age_min / 60:.1f} ч назад. Брокер отбивает любой запрос "
                f"(retcode=10006), equity в терминале посчитана по этим "
                f"старым ценам и неверна. Это сторона брокера, не наша."]
    return []


def degraded() -> list[str]:
    """Что отвалилось, НЕ остановив торговлю.

    🔴 29.09, найдено при разборе простоя и прямо отвечает на вопрос «а если
    Клод снова будет не оплачен». Движок от меня не зависит — проверено, в
    analyze/engine ни одной ссылки на агента. Но источник `alpha_forecast`
    читает таблицу forecasts, а её наполняет agent_run через claude CLI.
    Окно свежести — три часа: как только агент отваливается, источник
    перестаёт давать сигналы МОЛЧА, и это выглядит как «сигналов нет».

    Замерено на 29.09: alpha_forecast — 20.3% сделок демо и 9.3% реала,
    вклад +0.59 R на 46 сделках, то есть около нуля. Поэтому это именно
    урезание, а не отказ: торговать без него можно, не знать об этом нельзя.

    Разделение на «не идут» и «урезано» здесь принципиально. Если валить в
    одну кучу, оператор привыкнет видеть красный при работающей торговле —
    и это ровно тот путь, которым 811 алертов стали фоном."""
    from analyze.engine import ledger
    out: list[str] = []
    con = ledger.connect()
    row = con.execute("SELECT max(created_ts) FROM forecasts").fetchone()
    age_h = (time.time() - ((row and row[0]) or 0)) / 3600.0
    # 3 ч — окно, которым источник сам отбирает прогнозы (sources.from_forecasts).
    if age_h > 3.0 and not forecasts_off_by_decision():
        out.append(
            f"источник alpha_forecast молчит: прогнозов нет {age_h:.1f} ч "
            f"(наполняет agent_run через claude CLI — проверьте оплату/доступ). "
            f"Остальные источники работают, это ~20% потока сигналов")
    return out


def forecasts_off_by_decision() -> bool:
    """Выключен ли поставщик прогнозов СОЗНАТЕЛЬНО.

    🔴 07.10, правка собственной ошибки через час после её внесения.
    Я добавил жёлтый вердикт «alpha_forecast молчит — проверьте оплату», не
    посмотрев, что 01.10 владелец ВЫКЛЮЧИЛ alpha_cycle решением: 77% расхода
    модели на источник, который торговал в минус (-2.03 R на 57 сделках).
    То есть пульс просил бы починить то, что намеренно убрано, — и просил бы
    каждые сутки, вечно.

    Это ровно та болезнь, от которой пульс и сделан: сообщение, на которое
    нечего ответить, превращается в фон и уносит с собой внимание к
    настоящим. Поэтому источник правды тот же, что и для юнитов, —
    `ops/units.txt` с ролью `off`."""
    try:
        txt = (ROOT / "ops" / "units.txt").read_text(encoding="utf-8")
    except OSError:
        return False
    for line in txt.splitlines():
        s = line.strip()
        if s.startswith("#") or "sbf-alpha-cycle" not in s:
            continue
        # формат: <юнит> <роль> <макс_простой> # комментарий
        parts = s.split()
        if len(parts) >= 2 and parts[1] == "off":
            return True
    return False


def guard_state() -> list[str]:
    """Держит ли что-нибудь входы намеренно."""
    from analyze.engine.run import dirty_engine_files, guard_verdict
    dirty = dirty_engine_files()
    if not dirty:
        return []
    blocked, why = guard_verdict(dirty)
    return [f"входы приостановлены предохранителем: {why}"] if blocked else []


def build() -> tuple[str, str]:
    """(вердикт-ключ, текст сообщения). Ключ — то, по чему ловим смену."""
    bad: list[str] = []
    fixed: list[str] = []
    for acc in ("demo", "real"):
        ok, b, f = check_account(acc)
        bad += b
        fixed += f
    bad += guard_state()
    # Свежесть котировок — в ОТКАЗ, а не в урезание: без живых цен брокер
    # отбивает всё, то есть торгов нет, сколько бы юнитов ни было живо.
    for acc in ("demo", "real"):
        bad += feed_fresh(acc)
    try:
        info, jb = journal_state()
        bad += jb
    except Exception as e:                                       # noqa: BLE001
        info = {}
        bad.append(f"журнал не читается: {e}")
    try:
        weak = degraded()
    except Exception as e:                                       # noqa: BLE001
        weak = [f"проверка урезания не прошла: {e}"]

    if bad:
        head = "🔴 ТОРГИ НЕ ИДУТ"
    elif weak:
        head = "🟡 Торги идут, но урезаны"
    else:
        head = "🟢 Торги идут"
    # Ключ включает и урезание: переход «всё хорошо» -> «урезано» это смена
    # вердикта и обязан прийти сообщением, иначе тихая деградация останется
    # тихой — а именно она и стоила одиннадцати дней.
    key = "|".join(["СТОП" if bad else "ИДУТ"] + sorted(bad) + sorted(weak))

    lines = [head]
    for b in bad:
        lines.append(f"· {b}")
    for w in weak:
        lines.append(f"🟡 {w}")
    if fixed:
        lines.append("")
        for f in fixed:
            lines.append(f"🔧 {f}")
    if info:
        lines.append("")
        for acc, d in info.items():
            a = d["last_trade_h"]
            when = "никогда" if a is None else (
                f"{a:.1f} ч назад" if a < 48 else f"{a / 24:.1f} сут назад")
            h = f", остановлено: {d['halted_note']}" if d.get("halted_note") else ""
            lines.append(f"{acc}: последняя сделка {when}, открыто {d['open']}{h}")
    lines.append("")
    lines.append("Что делать, если стоит: ops/RUNBOOK_торги.md")
    return key, "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--говори", action="store_true",
                    help="сообщить независимо от смены вердикта")
    ap.add_argument("--молча", action="store_true",
                    help="только напечатать, ничего не отправлять")
    a = ap.parse_args()

    key, text = build()
    print(text)

    prev = {}
    try:
        prev = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        pass
    changed = prev.get("key") != key
    # Раз в сутки — «жив», иначе тишину не отличить от исправности.
    daily_due = (time.time() - float(prev.get("sent_ts") or 0)) > 23.5 * 3600

    STATE.parent.mkdir(parents=True, exist_ok=True)
    send = a.говори or (changed or daily_due) and not a.молча
    if send:
        try:
            from analyze.outbox import enqueue_ops
            prefix = "" if changed else "(суточная сводка)\n"
            enqueue_ops(prefix + text, source="pulse")
        except Exception as e:                                    # noqa: BLE001
            print(f"пульс: сообщение не ушло: {e}", file=sys.stderr)
            send = False
    STATE.write_text(json.dumps(
        {"key": key, "ts": time.time(),
         "sent_ts": time.time() if send else prev.get("sent_ts") or 0},
        ensure_ascii=False), encoding="utf-8")
    return 0 if key.startswith("ИДУТ") else 1


if __name__ == "__main__":
    raise SystemExit(main())
