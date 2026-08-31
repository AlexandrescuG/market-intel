#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/engine/execution.py — отправка ордеров и сведение результатов.

Мост (`Bridge`) переиспользуется из mt5_calibration — он ничей, просто
соединение. А вот отправка и закрытие свои: у калибровочных функций зашиты
`MAGIC=20260818` и комментарий `sbf_cost_calib`. Если бы движок ходил через
них, его позиции были бы неотличимы от калибровочных, и `close_aged()`
закрывал бы их по возрасту, ломая горизонт стратегии.

Почему `order_send` собирается строкой и выполняется на стороне Wine —
см. докстринг `mt5_calibration.remote_order_send`: MetaTrader5 это
C-расширение, оно проверяет аргумент через PyDict_Check, а rpyc отдаёт
прокси-объект. Единственный работающий путь — собрать словарь и вызвать
функцию одним куском кода там, где живёт модуль.
"""
from __future__ import annotations

import logging
import sqlite3
import time

from analyze.engine import ledger
from analyze.engine.contracts import ENGINE_MAGIC, Decision
from analyze.mt5_calibration import Bridge
from analyze.mt5_safety import SafetyRefusal, assert_autotrading, assert_demo
from mt5_config import symbol_map_for

log = logging.getLogger("engine.exec")

COMMENT_OPEN = "sbf_engine"
COMMENT_CLOSE = "sbf_engine_close"


def broker_symbol(con: sqlite3.Connection, canonical: str, server: str | None) -> str:
    """Каноническое имя -> имя у ЭТОГО брокера.

    🔴 Только через `mt5_config.symbol_map_for(server)`, и никакого тихого
    фолбэка «вернём как есть». Проверено на живом терминале: `XAUUSD` у Ava
    не существует, золото называется `GOLD`. Фолбэк дал бы `symbol_info()`
    равный None по всему золоту — то есть движок молча перестал бы торговать
    главный инструмент, и это выглядело бы как «сигналов нет».

    Именно этот класс ошибки — работа под именами другого брокера — сделал
    45% трек-рекорда Signals размеченными по чужому инструменту (17.08).
    Поэтому неизвестный символ здесь тоже отказ, а не догадка.

    Таблица `broker_symbols` (842 строки, снята с терминала) остаётся
    запасным путём для инструментов вне ручной карты."""
    m = symbol_map_for(server)
    if canonical in m:
        return m[canonical]
    row = con.execute(
        "SELECT broker_symbol FROM broker_symbols WHERE canonical=? LIMIT 1",
        (canonical,)).fetchone()
    if row and row[0]:
        return row[0]
    raise SafetyRefusal(
        "unmapped_symbol",
        f"{canonical} не найден в карте сервера {server!r} и в broker_symbols")


def engine_positions(positions) -> list:
    """Только наши. Чужой magic не трогаем ни при каких обстоятельствах —
    в бутылке живёт торговый EA и остатки калибровочного контура."""
    return [p for p in (positions or []) if getattr(p, "magic", None) == ENGINE_MAGIC]


def preflight_account(mt5) -> None:
    """Предохранители СЧЁТА перед каждой отправкой.

    Демо проверяется состоянием, которое возвращает сам терминал, а не
    конфигом: конфиг можно перепутать, trade_mode врать не будет.
    `account_info()=None` — тоже отказ: «не смог проверить» и «проверил,
    всё хорошо» не должны быть одним исходом."""
    assert_demo(mt5.account_info())
    assert_autotrading(mt5.terminal_info())


def send(conn, mt5, symbol: str, volume: float, is_buy: bool, price: float,
         sl: float, tp: float, digits: int):
    conn.execute("import MetaTrader5 as _m")
    conn.execute(
        "_req = {"
        "'action': _m.TRADE_ACTION_DEAL,"
        f"'symbol': {symbol!r},"
        f"'volume': {float(volume)!r},"
        f"'type': _m.ORDER_TYPE_{'BUY' if is_buy else 'SELL'},"
        f"'price': {float(price)!r},"
        "'deviation': 20,"
        f"'magic': {ENGINE_MAGIC},"
        f"'comment': {COMMENT_OPEN!r},"
        f"'sl': {round(float(sl), digits)!r},"
        f"'tp': {round(float(tp), digits)!r},"
        "'type_time': _m.ORDER_TIME_GTC}")
    check = conn.eval("_m.order_check(_req)")
    rc = getattr(check, "retcode", None)
    if rc != 0:
        return None, f"order_check retcode={rc} {getattr(check, 'comment', '')}"
    return conn.eval("_m.order_send(_req)"), None


def close(conn, mt5, position) -> tuple[bool, str]:
    ticket = int(position.ticket)
    sym = str(position.symbol)
    vol = float(position.volume)
    is_long = int(position.type) == 0
    tick = mt5.symbol_info_tick(sym)
    price = float(tick.bid if is_long else tick.ask)
    conn.execute("import MetaTrader5 as _m")
    conn.execute(
        "_creq = {"
        "'action': _m.TRADE_ACTION_DEAL,"
        f"'symbol': {sym!r},"
        f"'volume': {vol!r},"
        f"'type': _m.ORDER_TYPE_{'SELL' if is_long else 'BUY'},"
        f"'position': {ticket},"
        f"'price': {price!r},"
        "'deviation': 20,"
        f"'magic': {ENGINE_MAGIC},"
        f"'comment': {COMMENT_CLOSE!r},"
        "'type_time': _m.ORDER_TIME_GTC}")
    res = conn.eval("_m.order_send(_creq)")
    rc = getattr(res, "retcode", None)
    if rc != mt5.TRADE_RETCODE_DONE:
        return False, f"retcode={rc} {getattr(res, 'comment', '')}"
    return True, ""


def execute(con: sqlite3.Connection, mt5, conn, signal_id: int, d: Decision,
            *, live: bool, bsym: str) -> tuple[bool, str]:
    """Открыть позицию по принятому решению.

    Барьеры ставятся В ЗАЯВКЕ, а не «закроем потом сами». Без них позиция
    висит бесконечно, если наш процесс перезапустят: барьеры на стороне
    брокера переживают всё, что происходит на нашей стороне."""
    s = d.signal
    mode = "live" if live else "shadow"

    if not live:
        tid = ledger.open_trade(con, signal_id, d, mode=mode, broker_symbol=bsym,
                                req_price=s.ref_price, status="open",
                                note="теневой режим: ордер не отправлялся")
        ledger.mark_sent(con, tid, ticket=0, entry_price=s.ref_price)
        return True, "shadow"

    mt5.symbol_select(bsym, True)
    si = mt5.symbol_info(bsym)
    if si is None:
        return False, f"symbol_info({bsym}) вернул None"
    tick = mt5.symbol_info_tick(bsym)
    if tick is None:
        return False, f"symbol_info_tick({bsym}) вернул None"
    price = float(tick.ask if s.is_long else tick.bid)
    digits = int(getattr(si, "digits", 5))

    # 🔴 БАРЬЕРЫ ПЕРЕСЧИТЫВАЮТСЯ ОТ ЦЕНЫ ВХОДА, А НЕ ОТ ЗАКРЫТИЯ БАРА.
    #
    # 31.08: я воспроизвёл ровно тот дефект, который в этом же репозитории
    # был найден и исправлен 19.08 (см. live_strategy.geometry). Источник
    # считает стоп и цель от `ref_price` — закрытия сигнального бара, — а
    # ордер уходит по рынку. Между ними снос, и он ломает геометрию
    # НЕСИММЕТРИЧНО: если цена ушла в сторону цели, награда сжимается, а
    # риск растёт, то есть входим выше с более тесным стопом.
    #
    # Замерено по 22 закрытым сделкам: заявленное RR 2.0 на деле гуляло от
    # 1.135 до 3.357. Пять из шести сделок со сносом > 0.3R получили
    # фактическое RR около 1.2 — и четыре из них закрылись стопом. Средняя
    # награда на выигрышах вышла 1.73R вместо 2.0, из-за чего безубыточный
    # винрейт поднялся с 33.3% до 36.6%: почти три процентных пункта
    # преимущества сгорали ни за что.
    #
    # Геометрия сохраняется по построению: то же расстояние до стопа в ATR
    # и то же RR, но привязанные к цене, по которой реально входим.
    dist = s.stop_distance
    rr = s.rr
    if s.is_long:
        stop, target = price - dist, price + rr * dist
    else:
        stop, target = price + dist, price - rr * dist

    # 🔴 Строка журнала заводится ДО отправки. 19.08 в старом контуре порядок
    # был обратный: ордер ушёл, позиция открылась, INSERT упал с
    # "database is locked" — сделка не попала ни в журнал, ни под горизонт.
    tid = ledger.open_trade(con, signal_id, d, mode=mode, broker_symbol=bsym,
                            req_price=price, status="pending",
                            note=f"atr={s.atr:.5f} rr={rr:.2f} "
                                 f"снос={abs(price - s.ref_price) / dist:.3f}R",
                            stop=stop, target=target)

    res, err = send(conn, mt5, bsym, d.volume, s.is_long, price, stop, target, digits)
    if err or res is None or getattr(res, "retcode", None) != mt5.TRADE_RETCODE_DONE:
        reason = err or f"retcode={getattr(res, 'retcode', None)} {getattr(res, 'comment', '')}"
        ledger.mark_rejected(con, tid, reason)
        return False, reason

    ledger.mark_sent(con, tid, ticket=int(res.order), entry_price=float(res.price))
    return True, f"ticket={res.order} по {res.price}"


# ─── сведение ───────────────────────────────────────────────────────────────

def settle(con: sqlite3.Connection, mt5, conn) -> dict:
    """Свести закрытые позиции и закрыть просроченные по горизонту.

    🔴 Причина, по которой это отдельный обязательный шаг: 27.08 в старом
    контуре сведение падало с `database is locked`, и три закрытых стопа
    остались в журнале со статусом «отправлено». Метрика, по которой
    считаются стоп-краны, видела прибыли (они успевали свестись) и не видела
    свежих убытков. Смещение систематическое и в опасную сторону.

    Поэтому: сначала СВЕРКА с брокером (что журнал считает открытым, а у
    брокера уже нет), потом горизонт, и всё — с записью причины."""
    stats = {"closed": 0, "by_horizon": 0, "orphans": 0, "halted": []}
    now = int(time.time())

    live_positions = {int(p.ticket): p for p in engine_positions(mt5.positions_get())}
    open_rows = [t for t in ledger.open_trades(con) if t["mode"] == "live"]

    # 1. сведение: наших записей нет среди позиций -> позиция закрыта
    gone = [t for t in open_rows if t["ticket"] and int(t["ticket"]) not in live_positions]
    if gone:
        deals = mt5.history_deals_get(now - 30 * 86400, now + 3600) or []
        by_pos: dict[int, list] = {}
        for dl in deals:
            if getattr(dl, "magic", None) != ENGINE_MAGIC:
                continue
            by_pos.setdefault(int(getattr(dl, "position_id", 0)), []).append(dl)
        for t in gone:
            legs = by_pos.get(int(t["ticket"]), [])
            outs = [d for d in legs if int(getattr(d, "entry", 0)) == 1]
            if not outs:
                stats["orphans"] += 1
                log.warning("сделка %s закрыта у брокера, но её сделок нет в истории — "
                            "оставляю открытой до следующего прогона", t["ticket"])
                continue
            last = outs[-1]
            r = ledger.close_trade(
                con, t["id"], exit_price=float(last.price),
                profit=sum(float(d.profit) for d in outs),
                commission=sum(float(d.commission) for d in legs),
                swap=sum(float(d.swap) for d in legs),
                reason=str(getattr(last, "comment", "") or "closed"))
            st = ledger.apply_result(con, t["strategy"], r)
            stats["closed"] += 1
            _maybe_halt(con, st, stats)

    # 2. горизонт: позиция жива, но её время вышло
    for t in open_rows:
        if not t["ticket"] or int(t["ticket"]) not in live_positions:
            continue
        if (t["horizon_until"] or 0) > now:
            continue
        ok, err = close(conn, mt5, live_positions[int(t["ticket"])])
        if ok:
            stats["by_horizon"] += 1
        else:
            # Молчать нельзя: позиция за горизонтом продолжает жить, и её
            # исход попадёт в журнал как исход стратегии, которой он уже
            # не принадлежит.
            log.error("НЕ закрыт по горизонту %s: %s", t["ticket"], err)
    return stats


def _maybe_halt(con: sqlite3.Connection, state: dict, stats: dict) -> None:
    from analyze.engine.risk import drawdown_halt
    reason = drawdown_halt(state)
    if reason:
        ledger.halt(con, state["strategy"], reason)
        stats["halted"].append((state["strategy"], reason))
        log.error("СТРАТЕГИЯ ОСТАНОВЛЕНА %s: %s", state["strategy"], reason)


def settle_shadow(con: sqlite3.Connection) -> dict:
    """Теневые сделки разрешаются по реальным барам: касание стопа или цели
    внутри бара, иначе — закрытие по горизонту.

    Приоритет стопа при неоднозначности (оба барьера в одном баре) —
    осознанный пессимизм: внутрибарового порядка мы не знаем, и выбирать
    благоприятный исход значило бы завышать результат ровно там, где данных
    не хватает."""
    import core.price_bars as _pb
    stats = {"closed": 0, "halted": []}
    now = int(time.time())
    for t in [x for x in ledger.open_trades(con) if x["mode"] == "shadow"]:
        candles = _pb.load_candles(t["symbol"], t["tf"] or "1h") or []
        bars = [c for c in candles if c["ts"] >= (t["req_ts"] or 0)]
        exit_price, reason = None, None
        is_long = t["direction"] == "long"
        for c in bars:
            hit_stop = c["l"] <= t["stop"] if is_long else c["h"] >= t["stop"]
            hit_tgt = c["h"] >= t["target"] if is_long else c["l"] <= t["target"]
            if hit_stop:
                exit_price, reason = t["stop"], "shadow_stop"
                break
            if hit_tgt:
                exit_price, reason = t["target"], "shadow_target"
                break
        if exit_price is None and (t["horizon_until"] or 0) <= now and bars:
            exit_price, reason = bars[-1]["c"], "shadow_horizon"
        if exit_price is None:
            continue
        r = ledger.close_trade(con, t["id"], exit_price=exit_price, profit=0.0,
                               commission=0.0, swap=0.0, reason=reason)
        st = ledger.apply_result(con, t["strategy"], r)
        stats["closed"] += 1
        _maybe_halt(con, st, stats)
    return stats
