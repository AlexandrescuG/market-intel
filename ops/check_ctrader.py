#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ops/check_ctrader.py — проверка ключей cTrader Open API.

Ничего не торгует и ничего не меняет. Спрашивает у API четыре вещи подряд и
на каждой умеет отличить отказ от успеха:

  1. авторизация приложения          -> верны ли Client ID / Secret;
  2. СПИСОК СЧЕТОВ ПО ТОКЕНУ         -> какие счета этот токен вообще видит;
  3. авторизация конкретного счёта   -> доступен ли тот, что записан в .env;
  4. детали счёта и список символов  -> живой ли он и какой это брокер.

🔴 ДВЕ ОШИБКИ ПЕРВОЙ ВЕРСИИ, 31.08.2026. Обе мои, обе одного класса.

Первая: шаг 2 отсутствовал вовсе. Я сразу авторизовал счёт из .env, хотя у
API есть прямой вопрос «какие счета покрывает токен»
(`ProtoOAGetAccountListByAccessTokenReq`) — вместо догадки можно было
спросить. Именно этот шаг сразу показал бы, что счёт из .env токену не
принадлежит.

Вторая, хуже: список символов читался как `getattr(r, "symbol", [])`, а
вердикт «ВСЁ РАБОТАЕТ» печатался без проверки количества. В результате при
нуле инструментов скрипт бодро отрапортовал об успехе. `getattr` с пустым
значением по умолчанию ГЛОТАЛ `ProtoOAErrorRes` — у ошибки поля `symbol`
нет. Проверка, которая проходит на пустом ответе, хуже отсутствующей: она
создаёт уверенность на ровном месте.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, "/mnt/sbfdata/sbf-platform/market_intel")

from ctrader_open_api import Client, EndPoints, Protobuf, TcpProtocol  # noqa: E402
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *      # noqa: E402,F403
from ctrader_open_api.messages.OpenApiMessages_pb2 import *            # noqa: E402,F403
from twisted.internet import reactor                                   # noqa: E402


def env(name: str, required: bool = True) -> str:
    val = os.environ.get(name, "")
    if not val:
        for line in Path("/mnt/sbfdata/sbf-platform/market_intel/.env"
                         ).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                val = line.split("=", 1)[1].strip()
                break
    if required and not val:
        print(f"✗ в .env нет {name} — заполните через ops/set_ctrader_env.sh")
        sys.exit(1)
    return val


CLIENT_ID = env("CTRADER_CLIENT_ID")
SECRET = env("CTRADER_CLIENT_SECRET")
TOKEN = env("CTRADER_ACCESS_TOKEN")
WANT_ID = int(env("CTRADER_ACCOUNT_ID"))
HOST = env("CTRADER_HOST", required=False) or EndPoints.PROTOBUF_DEMO_HOST
PORT = int(env("CTRADER_PORT", required=False) or EndPoints.PROTOBUF_PORT)

print(f"хост   : {HOST}:{PORT}   ({'ДЕМО' if 'demo' in HOST else '🔴 РЕАЛ'})")
print(f"счёт   : {WANT_ID}  (из .env)")
print(f"client : {CLIENT_ID[:8]}…\n")

client = Client(HOST, PORT, TcpProtocol)
state = {"ok": False}


def stop():
    if reactor.running:
        reactor.stop()


def fail(step: str, err) -> None:
    print(f"\n✗ {step}\n  {err}")
    state["ok"] = False
    stop()


def check(msg, expect: str, step: str):
    """Тип ответа проверяется ЯВНО. Ошибка приходит другим сообщением, и без
    этой проверки она молча превращается в пустой результат."""
    r = Protobuf.extract(msg)
    kind = type(r).__name__
    if kind != expect:
        fail(f"{step}: вместо {expect} пришло {kind}",
             f"code={getattr(r, 'errorCode', '?')} · "
             f"{getattr(r, 'description', '')}")
        return None
    return r


def on_symbols(msg):
    r = check(msg, "ProtoOASymbolsListRes", "список символов")
    if r is None:
        return
    syms = list(r.symbol)
    print(f"  инструментов: {len(syms)} активных, "
          f"{len(list(getattr(r, 'archivedSymbol', [])))} архивных")
    if not syms:
        fail("список символов ПУСТ",
             "счёт авторизуется, но инструментов у него нет. Так ведёт себя "
             "Sandbox-счёт: он не подключён ни к какому брокеру.")
        return
    for s in syms[:8]:
        print(f"    {s.symbolId:>8}  {s.symbolName}")
    if len(syms) > 8:
        print(f"    … и ещё {len(syms) - 8}")
    print("\n✓ ВСЁ РАБОТАЕТ. Ключи верные, счёт живой, символы отдаются.")
    state["ok"] = True
    stop()


def on_trader(msg):
    r = check(msg, "ProtoOATraderRes", "детали счёта")
    if r is None:
        return
    t = r.trader
    money = 10 ** (getattr(t, "moneyDigits", 2) or 2)
    broker = getattr(t, "brokerName", "") or "(брокер не указан)"
    print(f"  брокер : {broker}")
    print(f"  баланс : {getattr(t, 'balance', 0) / money:.2f}")
    print(f"  плечо  : {getattr(t, 'leverageInCents', 0) // 100}")
    if "fxpro" not in broker.lower():
        print(f"  ⚠ брокер не похож на FxPro — проверьте, тот ли это счёт")
    req = ProtoOASymbolsListReq()                                   # noqa: F405
    req.ctidTraderAccountId = WANT_ID
    client.send(req).addCallbacks(on_symbols, lambda e: fail("список символов", e))


def on_account_auth(msg):
    r = check(msg, "ProtoOAAccountAuthRes", "авторизация счёта")
    if r is None:
        return
    print("✓ счёт авторизован")
    req = ProtoOATraderReq()                                        # noqa: F405
    req.ctidTraderAccountId = WANT_ID
    client.send(req).addCallbacks(on_trader, lambda e: fail("детали счёта", e))


def on_account_list(msg):
    """Главный диагностический шаг: что этот токен вообще видит."""
    r = check(msg, "ProtoOAGetAccountListByAccessTokenRes", "список счетов")
    if r is None:
        return
    accs = list(r.ctidTraderAccount)
    print(f"✓ токен покрывает счетов: {len(accs)}")
    for a in accs:
        aid = int(a.ctidTraderAccountId)
        live = getattr(a, "isLive", False)
        mark = "  ← из .env" if aid == WANT_ID else ""
        print(f"    {aid}  {'РЕАЛ' if live else 'демо'}{mark}")
    if not accs:
        fail("токен не покрывает ни одного счёта",
             "так выглядит Sandbox-токен: он выдан к тестовому окружению, "
             "а не к вашему cTID с торговыми счетами.")
        return
    if WANT_ID not in [int(a.ctidTraderAccountId) for a in accs]:
        fail(f"счёт {WANT_ID} из .env НЕ входит в список токена",
             "возьмите ctidTraderAccountId из списка выше и перезапишите "
             "CTRADER_ACCOUNT_ID, либо получите токен под нужный cTID.")
        return
    req = ProtoOAAccountAuthReq()                                   # noqa: F405
    req.ctidTraderAccountId = WANT_ID
    req.accessToken = TOKEN
    client.send(req).addCallbacks(on_account_auth,
                                  lambda e: fail("авторизация счёта", e))


def on_app_auth(msg):
    r = check(msg, "ProtoOAApplicationAuthRes", "авторизация приложения")
    if r is None:
        return
    print("✓ приложение авторизовано (Client ID и Secret верные)")
    req = ProtoOAGetAccountListByAccessTokenReq()                   # noqa: F405
    req.accessToken = TOKEN
    client.send(req).addCallbacks(on_account_list,
                                  lambda e: fail("список счетов по токену", e))


def connected(_):
    req = ProtoOAApplicationAuthReq()                               # noqa: F405
    req.clientId = CLIENT_ID
    req.clientSecret = SECRET
    client.send(req).addCallbacks(
        on_app_auth, lambda e: fail("авторизация приложения", e))


def disconnected(_, reason):
    if not state["ok"]:
        print(f"соединение закрыто: {reason}")


client.setConnectedCallback(connected)
client.setDisconnectedCallback(disconnected)
client.startService()
reactor.run()
sys.exit(0 if state["ok"] else 1)
