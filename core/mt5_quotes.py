"""core/mt5_quotes.py — цена инструментов брокера для всего, что не график.

🔴 20.08.2026. До этого модуля весь сайт брал живую цену у Yahoo, а графики —
у брокера через /api/chart/tail. По золоту это давало ДВА ЧИСЛА ПОД ОДНОЙ
ПОДПИСЬЮ: шапка 4 545 (фьючерс GC=F), график 4 487 (спот брокера) — 1.3%.
Подменой тикера не лечится: спота золота у Yahoo нет вовсе (XAUUSD=X отдаёт
404, проверено). Поэтому для инструментов из CHART_BROKER_MAP источником
становится сам брокер, а Yahoo остаётся для всего прочего (VIX, ^IXIC, пары,
которых у Ava нет).

Ключом наружу остаётся ТИКЕР YAHOO: под ним quotes.json читают sbf-header.js,
index.html, chart.html и serve.py::fetch_quotes(), а snapshot() — половина
аналитики. Менять пространство ключей ради смены источника значило бы трогать
десяток мест вместо одного.

Мост тот же rpyc-сервер в Wine-бутылке (mt5_server.py), что кормит графики.
Соединение своё на процесс: publish_quotes() крутится в quotes_loop.py, брифы
— в своих юнитах, лезть за ценой через собственный HTTP-сервер было бы кругом.

Отказ моста НЕ маскируется: функции возвращают пустой словарь, а вызывающий
обязан сказать об этом в лог. Путь, который может закончиться ничем, должен
себя обнаруживать.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("mt5_quotes")

_MT5_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
_conn = None


def _bridge():
    global _conn
    if _conn is not None:
        try:
            _conn.ping()
            return _conn
        except Exception:
            _conn = None
    import rpyc
    _conn = rpyc.classic.connect("127.0.0.1", 18812)
    _conn.modules["MetaTrader5"].initialize(path=_MT5_PATH, timeout=60000)
    return _conn


def _pairs(want: set | None):
    """[(наш ключ, имя у брокера, тикер Yahoo)] — только то, что просили."""
    from core.symbols_registry import alias_for
    from mt5_config import CHART_BROKER_MAP
    out = []
    for our, bs in CHART_BROKER_MAP.items():
        y = alias_for(our, "yahoo")
        if not y:
            continue
        if want is not None and y not in want:
            continue
        out.append((our, bs, y))
    return out


# Закрытие предыдущего дня за 15 секунд не меняется — держим его отдельно от
# тика, иначе каждый цикл котировок стоил бы лишние 2 с на мосту.
_prev_close: dict = {}
_prev_close_at = 0.0
_PREV_TTL = 600


def _daily(mt5, rpyc, pairs, now_ts, force=False):
    """{наш ключ: (закрытие предыдущего дня, закрытие текущего)}. Кэш _PREV_TTL."""
    global _prev_close, _prev_close_at
    if not force and now_ts - _prev_close_at <= _PREV_TTL:
        return _prev_close
    got = {}
    for our, bs, _y in pairs:
        try:
            r = mt5.copy_rates_from_pos(bs, mt5.TIMEFRAME_D1, 0, 2)
            if r is None or len(r) < 2:
                continue
            d = rpyc.classic.obtain(r)
            got[our] = (float(d[0]["close"]), float(d[1]["close"]))
        except Exception:
            continue
    if got:
        _prev_close, _prev_close_at = got, now_ts
    return _prev_close


def quotes(now_ts: float, want: set) -> dict:
    """Живые котировки: {тикер Yahoo: {price, change_pct, delay_sec, source}}.

    Цена — bid текущего тика (то же число, что рисует график: последняя
    незакрытая свеча закрывается по bid). change_pct — от закрытия
    ПРЕДЫДУЩЕГО ДНЯ У БРОКЕРА, а не от chartPreviousClose Yahoo: иначе
    процент считался бы от границы суток другой площадки и не сходился бы
    с тем, что видно на графике. Числа в шапке от этого заметно поехали
    (золото 20.08: +1.12% у Yahoo против -0.47% у брокера) — это не порча,
    а согласование.

    {} — мост молчит.
    """
    import rpyc
    pairs = _pairs(want)
    if not pairs:
        return {}
    conn = _bridge()
    mt5 = conn.modules["MetaTrader5"]
    mt5.initialize(path=_MT5_PATH, timeout=60000)

    daily = _daily(mt5, rpyc, pairs, now_ts)
    out = {}
    for our, bs, y in pairs:
        try:
            tick = mt5.symbol_info_tick(bs)
            if tick is None:
                continue
            price = float(tick.bid)
            if not price:
                continue
            tick_ts = int(tick.time)
        except Exception:
            continue
        pv = (daily.get(our) or (None, None))[0]
        out[y] = {
            "price": round(price, 5),
            "change_pct": round((price / pv - 1) * 100, 2) if pv else None,
            # Тик у брокера обновляется по сделкам: «задержка» здесь — простой
            # инструмента. Фронт по ней же понимает, что рынок закрыт
            # (chart.html::MARKET_CLOSED_DELAY_SEC), и на ночных индексах она
            # честно растёт, а не остаётся декларативным нулём.
            "delay_sec": max(0, int(now_ts - tick_ts)),
            "source": "mt5",
        }
    return out


def snapshot(want: set) -> dict:
    """Дневной срез в форме core.market.snapshot(): {тикер Yahoo: {price, prev,
    change_pct}} — по закрытиям D1 брокера, без обращения к тику.

    Отдельно от quotes() намеренно: снимок кормит аналитику и бриф, где
    важна сопоставимость с барами (по ним же считаются base_rate и реакции),
    а не «цена прямо сейчас». Точность как в yfinance-ветке: 4 знака для
    форекса (пипс), 2 для остального.
    """
    import rpyc
    pairs = _pairs(want)
    if not pairs:
        return {}
    conn = _bridge()
    mt5 = conn.modules["MetaTrader5"]
    mt5.initialize(path=_MT5_PATH, timeout=60000)
    daily = _daily(mt5, rpyc, pairs, time.time())
    out = {}
    for our, _bs, y in pairs:
        pair = daily.get(our)
        if not pair:
            continue
        prev, last = pair
        prec = 4 if abs(last) < 10 else 2
        out[y] = {"price": round(last, prec), "prev": round(prev, prec),
                  "change_pct": round((last / prev - 1) * 100, 2)}
    return out
