#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/ctrader/session.py — синхронная обёртка над Twisted-клиентом.

ЗАЧЕМ. Официальный SDK асинхронный, а вся наша работа пакетная: раз в час
долить бары, отправить ордер, свести результаты. Писать колбэки на каждый
такой сценарий — значит размазать логику по вложенным функциям и потерять
обработку ошибок. Здесь реактор поднимается один раз, сценарий выполняется
последовательно, реактор гасится.

КАК УСТРОЕНА СИНХРОННОСТЬ. Реактор поднимается ОДИН раз в фоновом потоке и
живёт до конца процесса; вызывающий код остаётся в главном потоке и
блокируется на каждом запросе через `blockingCallFromThread`.

🔴 Первая версия делала иначе — крутила `reactor.run()` до ответа и
останавливала его. Это работает ровно один раз: `reactor.stop()`
необратим, и второй запрос падает с `ReactorNotRestartable`. Причём я сам
описал это ограничение в этом же докстринге абзацем ниже и всё равно
написал код, который на него наступает. Комментарий о грабле не защищает
от грабли — защищает только проверка, поэтому теперь есть тест.

Следствие, которое стоит помнить: реактор один на процесс, поэтому
`Session` можно открывать и закрывать сколько угодно раз, но параллельно
работающих сессий в одном процессе быть не должно.

ОШИБКА ЭТО ОТВЕТ, А НЕ ПУСТОТА. Любой ответ проверяется по типу сообщения:
`ProtoOAErrorRes` приходит отдельным типом, и без явной сверки он молча
превращается в «данных нет». Ровно на этом 31.08 сгорела первая версия
ops/check_ctrader.py — печатала «всё работает» при нуле инструментов.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from ctrader_open_api import Client, EndPoints, Protobuf, TcpProtocol
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *   # noqa: F403
from ctrader_open_api.messages.OpenApiMessages_pb2 import *         # noqa: F403
from twisted.internet import reactor
from twisted.internet.threads import blockingCallFromThread

_ENV = Path("/mnt/sbfdata/sbf-platform/market_intel/.env")

CONNECT_TIMEOUT = 30
REQUEST_TIMEOUT = 45

_reactor_lock = threading.Lock()
_reactor_thread: threading.Thread | None = None


def _start_reactor() -> None:
    """Поднять реактор в фоновом потоке ровно один раз за процесс."""
    global _reactor_thread
    with _reactor_lock:
        if _reactor_thread is not None and _reactor_thread.is_alive():
            return
        _reactor_thread = threading.Thread(
            target=reactor.run, kwargs={"installSignalHandlers": False},
            name="ctrader-reactor", daemon=True)
        _reactor_thread.start()
        deadline = time.time() + 10
        while not reactor.running:
            if time.time() > deadline:
                raise CTraderError("REACTOR", "реактор не запустился", "старт")
            time.sleep(0.01)


class CTraderError(RuntimeError):
    """Отказ на стороне API. Несёт код и описание — молчаливый пропуск
    запрещён, причина обязана дойти до журнала."""

    def __init__(self, code, description, step=""):
        super().__init__(f"{step}: {code} · {description}".strip(": "))
        self.code, self.description, self.step = code, description, step


def env(name: str, default: str = "", required: bool = True) -> str:
    val = os.environ.get(name, "")
    if not val and _ENV.exists():
        for line in _ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                val = line.split("=", 1)[1].strip()
                break
    val = val or default
    if required and not val:
        raise CTraderError("NO_CONFIG", f"в .env нет {name}")
    return val


class Session:
    """Одна сессия: соединение + авторизация приложения + авторизация счёта.

    Использование:

        with Session() as s:
            bars = s.trendbars(symbol_id=41, period="H1", count=500)

    Внутри — синхронные вызовы: каждый `request()` блокирует до ответа.
    Это осознанно: у нас пакетные задачи, параллелить нечего, а линейный
    код читается и отлаживается несравнимо проще.
    """

    def __init__(self, account_id: int | None = None, host: str | None = None):
        self.client_id = env("CTRADER_CLIENT_ID")
        self.secret = env("CTRADER_CLIENT_SECRET")
        self.token = env("CTRADER_ACCESS_TOKEN")
        self.account_id = int(account_id or env("CTRADER_ACCOUNT_ID"))
        self.host = host or env("CTRADER_HOST", EndPoints.PROTOBUF_DEMO_HOST, False)
        self.port = int(env("CTRADER_PORT", str(EndPoints.PROTOBUF_PORT), False))
        self.is_demo = "demo" in self.host
        self._client = None
        self._symbols: dict[str, int] | None = None

    # ── работа с реактором ──────────────────────────────────────────────

    def __enter__(self):
        _start_reactor()
        self._client = Client(self.host, self.port, TcpProtocol)
        ready = threading.Event()
        self._client.setConnectedCallback(lambda _: ready.set())
        self._client.setDisconnectedCallback(lambda *a: None)
        reactor.callFromThread(self._client.startService)
        if not ready.wait(CONNECT_TIMEOUT):
            raise CTraderError("TIMEOUT",
                               f"нет соединения с {self.host}:{self.port} "
                               f"за {CONNECT_TIMEOUT} с", "соединение")
        self._auth()
        return self

    def __exit__(self, *exc):
        # Реактор НЕ гасим: он один на процесс и переживает сессию.
        # Останавливаем только клиента — иначе следующая сессия в этом же
        # процессе упёрлась бы в ReactorNotRestartable.
        try:
            reactor.callFromThread(self._client.stopService)
        except Exception:
            pass
        return False

    def request(self, req, step: str = "", timeout: int = REQUEST_TIMEOUT):
        """Отправить сообщение и дождаться ответа, сверив его тип.

        Таймаут обязателен: без него зависший ответ вешает юнит навсегда, а
        systemd покажет `active` — тот самый случай, когда молчание
        неотличимо от работы. Ровно так 26.08 семь часов простоял мост MT5."""
        step = step or type(req).__name__

        def send():
            d = self._client.send(req)
            d.addTimeout(timeout, reactor)
            return d

        try:
            msg = blockingCallFromThread(reactor, send)
        except Exception as e:                                     # noqa: BLE001
            raise CTraderError("TRANSPORT", f"{type(e).__name__}: {e}", step) from e

        r = Protobuf.extract(msg)
        # 🔴 У отказа НЕ ОДНА форма. Первая версия знала только
        # `ProtoOAErrorRes`, и отвергнутый ордер вернулся как
        # `ProtoOAOrderErrorEvent` — проверка его пропустила, скрипт
        # отрапортовал «ордер принят», а позиции не было. Третий раз за день
        # один и тот же класс: проверка знает одну форму неудачи и потому
        # молча пропускает остальные. Поэтому здесь не перечисление типов, а
        # признак: есть поле `errorCode` — значит отказ.
        code = getattr(r, "errorCode", None)
        if code:
            raise CTraderError(code, getattr(r, "description", ""), step)
        return r

    # ── живые котировки ─────────────────────────────────────────────────

    def spot(self, symbol: str, timeout: int = 15) -> tuple[float, float]:
        """Текущие bid/ask. Возвращает (bid, ask).

        🔴 Нужно именно это, а не закрытие последнего бара. Первая попытка
        отправить ордер привязала стоп к закрытию H1 (4420.15) при рынке на
        4375 — брокер отверг заявку как `TRADING_BAD_STOPS`, потому что стоп
        для покупки оказался выше цены входа. Это тот же дефект, что чинили
        в движке 31.08: барьеры считаются от ЦЕНЫ ВХОДА, а бар — не цена.

        Котировки приходят событием, а не ответом на запрос, поэтому здесь
        временный обработчик сообщений, а не обычный `request`."""
        sid = self.symbol_id(symbol)
        got = threading.Event()
        box: dict[str, float] = {}

        def on_message(_client, message):
            if message.payloadType != ProtoOASpotEvent().payloadType:  # noqa: F405
                return
            ev = Protobuf.extract(message)
            if ev.symbolId != sid:
                return
            if ev.HasField("bid"):
                box["bid"] = ev.bid / 100_000.0
            if ev.HasField("ask"):
                box["ask"] = ev.ask / 100_000.0
            if "bid" in box and "ask" in box:
                got.set()

        self._client.setMessageReceivedCallback(on_message)
        try:
            req = ProtoOASubscribeSpotsReq(                           # noqa: F405
                ctidTraderAccountId=self.account_id)
            req.symbolId.append(sid)
            self.request(req, f"подписка на котировки {symbol}")
            if not got.wait(timeout):
                raise CTraderError("NO_QUOTE",
                                   f"{symbol}: котировка не пришла за {timeout} с "
                                   f"(рынок закрыт?)", "котировка")
            return box["bid"], box["ask"]
        finally:
            self._client.setMessageReceivedCallback(lambda *a: None)
            try:
                u = ProtoOAUnsubscribeSpotsReq(                       # noqa: F405
                    ctidTraderAccountId=self.account_id)
                u.symbolId.append(sid)
                self.request(u, "отписка")
            except CTraderError:
                pass

    def _auth(self):
        a = ProtoOAApplicationAuthReq()                              # noqa: F405
        a.clientId, a.clientSecret = self.client_id, self.secret
        self.request(a, "авторизация приложения")
        b = ProtoOAAccountAuthReq()                                  # noqa: F405
        b.ctidTraderAccountId, b.accessToken = self.account_id, self.token
        self.request(b, "авторизация счёта")

    # ── прикладные запросы ──────────────────────────────────────────────

    def symbols(self) -> dict[str, int]:
        """Имя инструмента -> symbolId. Кэшируется на сессию."""
        if self._symbols is None:
            r = self.request(ProtoOASymbolsListReq(                  # noqa: F405
                ctidTraderAccountId=self.account_id), "список символов")
            self._symbols = {s.symbolName: s.symbolId for s in r.symbol}
            if not self._symbols:
                raise CTraderError("EMPTY", "брокер не отдал ни одного инструмента",
                                   "список символов")
        return self._symbols

    def symbol_id(self, name: str) -> int:
        """🔴 Без тихого фолбэка. Неизвестное имя — отказ, а не догадка:
        у Ava золото называется `GOLD`, у FxPro `XAUUSD`, и фолбэк
        «вернём как есть» дал бы пустые данные, неотличимые от «рынок молчит»."""
        s = self.symbols()
        if name not in s:
            raise CTraderError("NO_SYMBOL", f"{name} нет у брокера", "поиск символа")
        return s[name]

    def trader(self):
        return self.request(ProtoOATraderReq(                        # noqa: F405
            ctidTraderAccountId=self.account_id), "детали счёта").trader
