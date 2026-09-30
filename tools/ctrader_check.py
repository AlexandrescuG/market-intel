#!/usr/bin/env python3
"""tools/ctrader_check.py — проверка доступа к cTrader Open API.

Отвечает на единственный вопрос: работают ли выданные учётные данные и
отдаёт ли брокер свечи. Запускается из tools/ctrader_setup.sh ДО записи в .env,
а потом — руками, когда надо убедиться, что доступ ещё жив.

Читает clientId/clientSecret/accessToken из окружения (CT_*), а не из
аргументов командной строки: аргументы видны в `ps` любому пользователю
машины.

Коды возврата: 0 — всё хорошо, 1 — не работает. Отдельного «частично» нет:
если авторизация прошла, а свечи не пришли, это уже неисправность, а не
полумера.
"""
from __future__ import annotations

import os
import sys
import time

from ctrader_open_api import Client, EndPoints, Protobuf, TcpProtocol
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAccountAuthReq, ProtoOAAccountAuthRes, ProtoOAApplicationAuthReq,
    ProtoOAApplicationAuthRes, ProtoOAGetAccountListByAccessTokenReq,
    ProtoOAGetAccountListByAccessTokenRes, ProtoOAGetTrendbarsReq,
    ProtoOAGetTrendbarsRes, ProtoOASymbolsListReq, ProtoOASymbolsListRes)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod
from twisted.internet import reactor

CLIENT_ID = os.environ.get("CT_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("CT_CLIENT_SECRET", "").strip()
ACCESS_TOKEN = os.environ.get("CT_ACCESS_TOKEN", "").strip()
HOST_TYPE = os.environ.get("CT_HOST", "demo").strip().lower()

state = {"rc": 1, "account": None, "symbols": 0, "bars": 0, "probe": None}


def fail(msg: str) -> None:
    print(f"  НЕ РАБОТАЕТ: {msg}")
    stop()


def stop() -> None:
    if reactor.running:
        reactor.callLater(0, reactor.stop)


def on_connected(client):
    req = ProtoOAApplicationAuthReq()
    req.clientId = CLIENT_ID
    req.clientSecret = CLIENT_SECRET
    client.send(req)


def on_disconnected(client, reason):
    pass


def on_message(client, message):
    pt = message.payloadType

    if pt == ProtoOAApplicationAuthRes().payloadType:
        print("  приложение авторизовано")
        r = ProtoOAGetAccountListByAccessTokenReq()
        r.accessToken = ACCESS_TOKEN
        client.send(r)
        return

    if pt == ProtoOAGetAccountListByAccessTokenRes().payloadType:
        res = Protobuf.extract(message)
        accs = list(res.ctidTraderAccount)
        if not accs:
            return fail("токен верный, но к нему не привязано ни одного счёта")
        # Живой счёт предпочтительнее демо: котировки те же, но живой не
        # протухает от бездействия так, как учебный.
        acc = next((a for a in accs if getattr(a, "isLive", False)), accs[0])
        state["account"] = int(acc.ctidTraderAccountId)
        print(f"  счетов у токена: {len(accs)}, беру {state['account']}"
              f" ({'живой' if getattr(acc, 'isLive', False) else 'демо'})")
        r = ProtoOAAccountAuthReq()
        r.ctidTraderAccountId = state["account"]
        r.accessToken = ACCESS_TOKEN
        client.send(r)
        return

    if pt == ProtoOAAccountAuthRes().payloadType:
        print("  счёт авторизован")
        r = ProtoOASymbolsListReq()
        r.ctidTraderAccountId = state["account"]
        client.send(r)
        return

    if pt == ProtoOASymbolsListRes().payloadType:
        res = Protobuf.extract(message)
        syms = list(res.symbol)
        state["symbols"] = len(syms)
        print(f"  инструментов у брокера: {len(syms)}")
        # Пробуем EURUSD — он есть у любого брокера; если нет, берём первый.
        pick = next((s for s in syms if s.symbolName.upper() == "EURUSD"), None) or (syms[0] if syms else None)
        if pick is None:
            return fail("список инструментов пуст")
        state["probe"] = pick.symbolName
        r = ProtoOAGetTrendbarsReq()
        r.ctidTraderAccountId = state["account"]
        r.symbolId = pick.symbolId
        r.period = ProtoOATrendbarPeriod.H1
        now_ms = int(time.time() * 1000)
        r.fromTimestamp = now_ms - 20 * 24 * 3600 * 1000
        r.toTimestamp = now_ms
        client.send(r)
        return

    if pt == ProtoOAGetTrendbarsRes().payloadType:
        res = Protobuf.extract(message)
        bars = list(res.trendbar)
        state["bars"] = len(bars)
        if not bars:
            return fail(f"свечи по {state['probe']} не пришли")
        last = bars[-1]
        ts = int(last.utcTimestampInMinutes) * 60
        print(f"  свечи H1 по {state['probe']}: {len(bars)} шт, "
              f"последняя {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(ts))}")
        state["rc"] = 0
        stop()
        return


def on_error(failure):
    fail(str(failure)[:200])


def main() -> int:
    if not (CLIENT_ID and CLIENT_SECRET and ACCESS_TOKEN):
        print("  НЕ РАБОТАЕТ: не заданы CT_CLIENT_ID / CT_CLIENT_SECRET / CT_ACCESS_TOKEN")
        return 1
    host = (EndPoints.PROTOBUF_LIVE_HOST if HOST_TYPE == "live"
            else EndPoints.PROTOBUF_DEMO_HOST)
    print(f"  подключаюсь к {host}:{EndPoints.PROTOBUF_PORT}")
    client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
    client.setConnectedCallback(on_connected)
    client.setDisconnectedCallback(on_disconnected)
    client.setMessageReceivedCallback(on_message)
    client.startService()
    # Ограничение по времени: без него зависшее соединение держало бы скрипт
    # (и владельца) неопределённо долго, а «висит» и «не работает» для того,
    # кто ждёт ответа, — одно и то же.
    reactor.callLater(40, stop)
    reactor.run()
    return state["rc"]


if __name__ == "__main__":
    raise SystemExit(main())
