#!/usr/bin/env python3
"""tools/ctrader_symbols_dump.py — выгрузить список инструментов cTrader в JSON.

Нужен, чтобы сопоставить каталог витрины (842 инструмента AvaTrade в
broker_symbols) с тем, что реально отдаёт счёт cTrader. Сопоставление делается
по именам, и делать его вслепую нельзя: у брокеров разные написания
(#BOEING против BA), а тихий фолбэк «возьмём имя как есть» уже однажды дал бы
пустые графики по всему золоту.

Пишет data/ctrader_symbols.json: [{symbolId, name, description, enabled, ...}]

Учётные данные берутся из .env (CTRADER_*), в аргументы не выносятся.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

from ctrader_open_api import Client, EndPoints, Protobuf, TcpProtocol
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAccountAuthReq, ProtoOAAccountAuthRes, ProtoOAApplicationAuthReq,
    ProtoOAApplicationAuthRes, ProtoOASymbolsListReq, ProtoOASymbolsListRes)
from twisted.internet import reactor

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "ctrader_symbols.json"


def env() -> dict:
    d = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("CTRADER_") and "=" in line:
            k, v = line.split("=", 1)
            d[k] = v.strip()
    return d


E = env()
state = {"rc": 1}


def on_connected(client):
    r = ProtoOAApplicationAuthReq()
    r.clientId = E["CTRADER_CLIENT_ID"]
    r.clientSecret = E["CTRADER_CLIENT_SECRET"]
    client.send(r)


def on_message(client, message):
    pt = message.payloadType
    if pt == ProtoOAApplicationAuthRes().payloadType:
        r = ProtoOAAccountAuthReq()
        r.ctidTraderAccountId = int(E["CTRADER_ACCOUNT_ID"])
        r.accessToken = E["CTRADER_ACCESS_TOKEN"]
        client.send(r)
    elif pt == ProtoOAAccountAuthRes().payloadType:
        r = ProtoOASymbolsListReq()
        r.ctidTraderAccountId = int(E["CTRADER_ACCOUNT_ID"])
        # includeArchivedSymbols по умолчанию False — архивные нам не нужны,
        # график по делистингованному инструменту это ровно тот «мёртвый фид»,
        # от которого мы уходим.
        client.send(r)
    elif pt == ProtoOASymbolsListRes().payloadType:
        res = Protobuf.extract(message)
        rows = []
        for s in res.symbol:
            rows.append({
                "symbolId": int(s.symbolId),
                "name": s.symbolName,
                "description": getattr(s, "description", ""),
                "enabled": bool(getattr(s, "enabled", True)),
                "categoryId": int(getattr(s, "symbolCategoryId", 0) or 0),
                "baseAssetId": int(getattr(s, "baseAssetId", 0) or 0),
                "quoteAssetId": int(getattr(s, "quoteAssetId", 0) or 0),
            })
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  инструментов выгружено: {len(rows)} -> {OUT}")
        state["rc"] = 0
        if reactor.running:
            reactor.callLater(0, reactor.stop)


def main() -> int:
    host = (EndPoints.PROTOBUF_DEMO_HOST if E.get("CTRADER_DEMO", "1") == "1"
            else EndPoints.PROTOBUF_LIVE_HOST)
    client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
    client.setConnectedCallback(on_connected)
    client.setDisconnectedCallback(lambda c, r: None)
    client.setMessageReceivedCallback(on_message)
    client.startService()
    reactor.callLater(45, lambda: reactor.running and reactor.stop())
    reactor.run()
    return state["rc"]


if __name__ == "__main__":
    raise SystemExit(main())
