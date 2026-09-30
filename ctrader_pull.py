#!/usr/bin/env python3
"""ctrader_pull.py — свечи витрины из cTrader Open API в кэш графиков.

ЧТО ДЕЛАЕТ. Раз в цикл проходит по data/ctrader_map.json (80 инструментов,
сопоставленных вручную и по именам) и по каждому таймфрейму тянет трендбары,
складывая их в core/candle_cache — тот самый кэш, из которого serve.py уже
отдаёт графики. Витрина по этим инструментам перестаёт ходить в MT5 совсем.

ЧЕГО НЕ ДЕЛАЕТ — и это главное. НЕ ПИШЕТ В price_bars. Бары движка приходят
оттуда же, где исполняются сделки, и остаются на брокере MT5. Рассогласование
источника и площадки уже стоило нам 45% трек-рекорда Signals (17.08.2026),
повторять нельзя. Здесь другая задача с другими требованиями: показать график
посетителю сайта.

ПОЧЕМУ ОТДЕЛЬНЫЙ ПРОЦЕСС, А НЕ ВЫЗОВ ИЗ serve.py. cTrader Open API работает
через twisted reactor, а reactor в процессе можно запустить ровно один раз и
нельзя перезапустить. Встроить его в веб-сервер значит связать живучесть сайта
с живучестью соединения к брокеру — ровно та беда, от которой мы уходим,
только в новой обёртке. Пуллер живёт сам по себе; упал — сайт продолжает
отдавать последние свечи из кэша.

ТОКЕН. Живёт ~30 дней, refresh-токен бессрочный. Обновление делается заранее,
за неделю до конца, и новый токен дописывается в .env — иначе однажды утром
всё встанет без объяснений.

Запуск:  python3 ctrader_pull.py            # один проход и выход
         python3 ctrader_pull.py --loop      # демон (так его держит systemd)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ctrader_open_api import Client, EndPoints, Protobuf, TcpProtocol
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAccountAuthReq, ProtoOAAccountAuthRes, ProtoOAApplicationAuthReq,
    ProtoOAApplicationAuthRes, ProtoOAErrorRes, ProtoOAGetTrendbarsReq,
    ProtoOAGetTrendbarsRes)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod
from twisted.internet import reactor

from core import candle_cache

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ctrader_pull")

ROOT = pathlib.Path(__file__).resolve().parent
MAP_FILE = ROOT / "data" / "ctrader_map.json"
ENV_FILE = ROOT / ".env"

# Наши таймфреймы -> периоды cTrader. W1 брокер тоже умеет, но недельные бары
# витрине даёт статическая выкладка publish.py, дёргать их сюда незачем.
TF_MAP = {
    "M1":  (ProtoOATrendbarPeriod.M1,  60),
    "M5":  (ProtoOATrendbarPeriod.M5,  300),
    "M15": (ProtoOATrendbarPeriod.M15, 900),
    "M30": (ProtoOATrendbarPeriod.M30, 1800),
    "H1":  (ProtoOATrendbarPeriod.H1,  3600),
    "H4":  (ProtoOATrendbarPeriod.H4,  14400),
    "D1":  (ProtoOATrendbarPeriod.D1,  86400),
}
# Сколько свечей просим. Совпадает с тем, что отдавал MT5 (_MT5_COUNT в
# serve.py) и с пределами публикации — чтобы «глубина графика» не значила в
# трёх местах три разных вещи.
BARS = {"M1": 1000, "M5": 1000, "M15": 1000, "M30": 1000,
        "H1": 3000, "H4": 2000, "D1": 2000}

# 🔴 Не быстрее пяти запросов в секунду: у cTrader это документированный предел
# для исторических данных. Ставим с запасом — нас никто не торопит, а
# «ограничить доступ приложению за неразумное использование» брокер вправе.
# Пауза больше не нужна: темп задаётся окном запросов в полёте (Puller.WINDOW).
LOOP_SLEEP = 120


def env() -> dict:
    d = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    return d


class Puller:
    # 🔴 Темп подбирается на ходу, а не задан константой.
    #
    # В документации написано «5 исторических запросов в секунду», и по этой
    # цифре я поставил окно в 4 запроса. Живой прогон ответил
    # BLOCKED_PAYLOAD_TYPE «You are being rate limited»: настоящий предел у
    # этого брокера жёстче документированного. Хуже того, первая версия эти
    # ошибки не разбирала — обход просто вставал на 474 записях из 560 и стоял
    # молча, с живым соединением и юнитом в состоянии active.
    #
    # Теперь: один запрос в полёте, пауза между отправками растёт при отказе и
    # медленно возвращается обратно при успехе. Отклонённый запрос уходит НАЗАД
    # в очередь — он не выполнен, и списывать его в ошибку значит терять
    # инструмент до следующего прохода.
    WINDOW = 1
    PACE_MIN = 0.5
    PACE_MAX = 6.0
    PACE_UP = 1.6       # во столько раз замедляемся при отказе
    PACE_DOWN = 0.97    # и во столько ускоряемся после каждого успеха

    def __init__(self, once: bool):
        self.env = env()
        self.map = json.loads(MAP_FILE.read_text(encoding="utf-8"))
        self.once = once
        self.queue: list[tuple[str, dict, str]] = []
        self.pending: dict[tuple[int, int], tuple[str, str]] = {}
        self.inflight = 0
        self._last_done = -1
        self.pace = self.PACE_MIN
        self.rate_limited = 0
        self.stats = {"ok": 0, "empty": 0, "err": 0, "bars": 0}
        self.pass_started = 0.0
        self.client = None

    # ── соединение ────────────────────────────────────────────────────────
    def start(self) -> int:
        host = (EndPoints.PROTOBUF_DEMO_HOST
                if self.env.get("CTRADER_DEMO", "1") == "1"
                else EndPoints.PROTOBUF_LIVE_HOST)
        self.client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.client.setConnectedCallback(self.on_connected)
        self.client.setDisconnectedCallback(self.on_disconnected)
        self.client.setMessageReceivedCallback(self.on_message)
        self.client.startService()
        reactor.run()
        return 0

    def on_connected(self, client):
        log.info("соединение установлено, авторизую приложение")
        r = ProtoOAApplicationAuthReq()
        r.clientId = self.env["CTRADER_CLIENT_ID"]
        r.clientSecret = self.env["CTRADER_CLIENT_SECRET"]
        client.send(r)

    def on_disconnected(self, client, reason):
        # Обрыв — не повод падать: systemd поднимет, но и сам клиент
        # переподключается. Пишем в лог, чтобы обрыв был ВИДЕН: молчаливый
        # реконнект с пустым кэшем выглядит как «сайт сломался».
        log.warning("соединение потеряно: %s", str(reason)[:200])

    # ── обход ─────────────────────────────────────────────────────────────
    def build_queue(self):
        self.queue = [(bs, meta, tf) for bs, meta in sorted(self.map.items())
                      for tf in TF_MAP]
        self.stats = {"ok": 0, "empty": 0, "err": 0, "bars": 0}
        self.pending.clear()
        self.inflight = 0
        self.pass_started = time.time()
        log.info("проход: %d инструментов x %d ТФ = %d запросов",
                 len(self.map), len(TF_MAP), len(self.queue))

    def watchdog(self):
        """Сдвинуть обход, если он замер.

        🔴 Поймано на живом прогоне: обход останавливался на 474 записях из 560
        и стоял молча — юнит `active`, соединение живо, в логе ни строчки. Так
        бывает, когда на запрос не приходит НИ ответа с барами, ни ошибки:
        счётчик запросов в полёте не обнуляется, окно забито, очередь стоит.
        Это ровно тот отказ, который мы ловим в этом проекте третью неделю:
        не падение, а тишина, неотличимая от нормальной работы.

        Сторож раз в 20 с сравнивает число обработанных ответов с прошлым
        разом. Не сдвинулось — считаем повисшие запросы потерянными, освобождаем
        окно и продолжаем. Потерянный инструмент подтянется следующим проходом.
        """
        done = self.stats["ok"] + self.stats["empty"] + self.stats["err"]
        if self.queue or self.inflight:
            if done == self._last_done:
                if self.pending or self.inflight:
                    log.warning("обход замер: в полёте %d, в очереди %d — "
                                "освобождаю окно (потеряно %s)",
                                self.inflight, len(self.queue),
                                ", ".join(f"{b}/{t}" for b, t in list(self.pending.values())[:4]))
                    self.stats["err"] += len(self.pending)
                    self.pending.clear()
                    self.inflight = 0
                    self.pace = min(self.PACE_MAX, self.pace * self.PACE_UP)
                    reactor.callLater(0, self.pump)
            self._last_done = done
        reactor.callLater(20, self.watchdog)

    def pump(self):
        """Держать в полёте несколько запросов сразу.

        🔴 Первая версия ждала ответа перед отправкой следующего запроса, и
        полный обход занимал 17 минут: задержка брокера ~1.8 с на запрос, а
        560 запросов — это 560 задержек подряд. При такой скорости минутные
        свечи приезжали устаревшими на четверть часа, то есть формально
        обновлялись, а по сути врали.
        Предел брокера — 5 исторических запросов в секунду; держим 4 в полёте
        с запасом. Ответы различаем по (symbolId, period): они есть в ответе,
        поэтому очередь и не нужно держать строго последовательной.
        """
        while self.inflight < self.WINDOW and self.queue:
            self.send_one()
        if not self.queue and self.inflight == 0:
            self.finish_pass()

    def pump_later(self):
        reactor.callLater(self.pace, self.pump)

    def send_one(self):
        bs, meta, tf = self.queue.pop(0)
        period, tf_sec = TF_MAP[tf]
        key = (int(meta["ct_id"]), int(period))
        self.pending[key] = (bs, tf)
        self.inflight += 1
        r = ProtoOAGetTrendbarsReq()
        r.ctidTraderAccountId = int(self.env["CTRADER_ACCOUNT_ID"])
        r.symbolId = int(meta["ct_id"])
        r.period = period
        now_ms = int(time.time() * 1000)
        r.fromTimestamp = now_ms - BARS[tf] * tf_sec * 1000
        r.toTimestamp = now_ms
        d = self.client.send(r)
        d.addErrback(self.on_error, key)

    def finish_pass(self):
        dur = time.time() - self.pass_started
        log.info("проход закончен за %.0f с: успешно %d, пусто %d, ошибок %d, "
                 "свечей %d, отказов по темпу %d, пауза %.1f с",
                 dur, self.stats["ok"], self.stats["empty"], self.stats["err"],
                 self.stats["bars"], self.rate_limited, self.pace)
        self.rate_limited = 0
        if self.once:
            reactor.callLater(0, reactor.stop)
        else:
            reactor.callLater(LOOP_SLEEP, self.new_pass)

    def new_pass(self):
        self.build_queue()
        self.pump()

    def on_error(self, failure, key):
        bs, tf = self.pending.pop(key, ("?", "?"))
        self.inflight = max(0, self.inflight - 1)
        self.stats["err"] += 1
        log.warning("%s %s: %s", bs, tf, str(failure)[:160])
        reactor.callLater(0, self.pump)

    # ── разбор ответа ─────────────────────────────────────────────────────
    def on_message(self, client, message):
        pt = message.payloadType
        if pt == ProtoOAApplicationAuthRes().payloadType:
            r = ProtoOAAccountAuthReq()
            r.ctidTraderAccountId = int(self.env["CTRADER_ACCOUNT_ID"])
            r.accessToken = self.env["CTRADER_ACCESS_TOKEN"]
            client.send(r)
            return
        if pt == ProtoOAAccountAuthRes().payloadType:
            log.info("счёт авторизован, начинаю обход")
            self._last_done = -1
            reactor.callLater(20, self.watchdog)
            self.new_pass()
            return
        if pt == ProtoOAGetTrendbarsRes().payloadType:
            self.handle_bars(Protobuf.extract(message))
            self.pace = max(self.PACE_MIN, self.pace * self.PACE_DOWN)
            self.pump_later()
            return
        if pt == ProtoOAErrorRes().payloadType:
            # Ошибка приходит БЕЗ symbolId, привязать её к конкретному запросу
            # нельзя. Поэтому просто освобождаем одно место в окне: какой
            # именно инструмент не ответил, покажет сторож.
            err = Protobuf.extract(message)
            self.inflight = max(0, self.inflight - 1)
            code = str(getattr(err, "errorCode", ""))
            desc = str(getattr(err, "description", ""))
            # Ошибка приходит БЕЗ symbolId — привязать её к конкретному запросу
            # нельзя, поэтому возвращаем в очередь самый старый ожидающий.
            if self.pending:
                key = next(iter(self.pending))
                bs, tf = self.pending.pop(key)
                meta = self.map.get(bs)
                if meta:
                    self.queue.insert(0, (bs, meta, tf))
            if "rate limit" in desc.lower() or "BLOCKED" in code:
                self.rate_limited += 1
                self.pace = min(self.PACE_MAX, self.pace * self.PACE_UP)
                if self.rate_limited in (1, 10, 50) or self.rate_limited % 100 == 0:
                    log.warning("брокер ограничивает темп (%d раз), пауза теперь %.1f с",
                                self.rate_limited, self.pace)
            else:
                self.stats["err"] += 1
                log.warning("брокер вернул ошибку: %s %s", code, desc[:120])
            self.pump_later()
            return

    def handle_bars(self, res):
        key = (int(res.symbolId), int(res.period))
        bs, tf = self.pending.pop(key, (None, None))
        self.inflight = max(0, self.inflight - 1)
        if bs is None:
            # Ответ, которого мы не ждали. Молча выбрасывать нельзя: это
            # означало бы, что где-то разъехались ключи, а мы об этом не знаем.
            log.warning("ответ без запроса: symbolId=%s period=%s", res.symbolId, res.period)
            return
        bars = list(res.trendbar)
        if not bars:
            self.stats["empty"] += 1
            return
        candles = []
        for b in bars:
            # 🔴 Формат cTrader: low хранится целым в «пунктах», а open/high/close
            # — смещениями ОТ low. Сложить их иначе (например, взять поля как
            # готовые цены) — получить график правильной формы с неправильными
            # числами, что хуже отсутствия графика: неверные данные выглядят
            # достоверно. Делитель 100000 задан протоколом.
            low = b.low
            o = (low + b.deltaOpen) / 100000.0
            h = (low + b.deltaHigh) / 100000.0
            c = (low + b.deltaClose) / 100000.0
            candles.append({"time": int(b.utcTimestampInMinutes) * 60,
                            "open": round(o, 5), "high": round(h, 5),
                            "low": round(low / 100000.0, 5), "close": round(c, 5)})
        candle_cache.put(bs, tf, candles)
        self.stats["ok"] += 1
        self.stats["bars"] += len(candles)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true", help="работать демоном")
    args = ap.parse_args()
    e = env()
    missing = [k for k in ("CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET",
                           "CTRADER_ACCESS_TOKEN", "CTRADER_ACCOUNT_ID")
               if not e.get(k)]
    if missing:
        log.error("не настроено: %s — см. tools/ctrader_setup.sh", ", ".join(missing))
        return 1
    if not MAP_FILE.exists():
        log.error("нет %s — сначала tools/ctrader_build_map.py --write", MAP_FILE)
        return 1
    return Puller(once=not args.loop).start()


if __name__ == "__main__":
    raise SystemExit(main())
