"""core/crypto_feed.py — свечи по криптовалютам с бирж, а не от брокера.

ЗАЧЕМ. У брокера часть монет мертва: SHIBUSD не обновлялся 121 день, BTGUSD,
ETHBTC, MELANIAUSD и PAX_GOLD не отдают баров вовсе. На графике это выглядело
как «по этому инструменту данных нет» — честно, но бесполезно: данные есть, их
бесплатно отдаёт любая крупная биржа.

ВЫБОР ИСТОЧНИКА (разбор 07.09.2026, живыми запросами с этого сервера):

  Binance — основной. Отдельный хост `data-api.binance.vision` официально
  задокументирован как market-data-only и не требует ни ключа, ни регистрации.
  1000 баров за запрос, 6000 единиц веса в минуту на IP (свечи весят 2, то
  есть ~3000 запросов), все восемь наших таймфреймов включая H4, история с
  даты листинга. Молдовы нет в списке запрещённых стран, проверено ответом 200
  с боевого сервера.

  Gate.io — запасной, и не просто дубль. Это единственная из восьми
  проверенных бирж, где живы ВСЕ мёртвые у брокера символы: BTG не знают ни
  Kraken, ни OKX, ни Bybit, ни Coinbase, KuCoin отдаёт по нему строку из одних
  null, а Binance — цену из октября 2022 под видом текущей.

  Отвергнуты: OKX и Coinbase — их соглашения прямо запрещают показывать
  рыночные данные третьим лицам, причём OKX отдельно оговаривает, что запрет
  распространяется и на публичные эндпоинты. MEXC запрещает сайты, которые
  зарабатывают на данных. Kraken отдаёт ровно 720 баров без возможности уйти
  назад — на H1 это 30 дней, на M15 неделя. CoinGecko на бесплатном тарифе не
  отдаёт дневки вовсе.

  ⚠️ Ни одна биржа не даёт явного права публиковать свои котировки на
  коммерческом сайте. У Binance и Gate в действующих документах нет прямого
  запрета (у Binance он был и был удалён в 2023), у остальных — есть. Это
  меньший риск, а не разрешение; решение о лицензии на данные — за владельцем.

ГРАБЛИ, ЗАЛОЖЕННЫЕ В КОД:

  • Порядок полей у Gate перевёрнут и объём стоит ПЕРЕД ценами:
    [ts, quote_vol, Close, High, Low, Open, base_vol, closed]. Перепутать
    close и open здесь легче лёгкого — отсюда явные индексы с комментарием.
  • Время: Binance в миллисекундах, Gate в секундах.
  • Незакрытый бар: Gate помечает строкой "false" в последнем поле. Отдавать
    его нельзя — он перерисуется.
  • Тихо мёртвый символ. У Binance 2290 пар из 3652 в статусе BREAK, и
    /ticker/price по такой паре бодро отдаёт цену из позапрошлого года. Ровно
    тот же класс отказа, что и SHIBUSD у брокера. Проверка на входе его не
    ловит — ловит только сравнение времени последнего бара с текущим, см.
    _is_stale().
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

log = logging.getLogger("crypto_feed")

_UA = "Mozilla/5.0 (compatible; SBFIntelligence/1.0; +https://lp.sbfconsult.com)"
_TIMEOUT = 15

# Наши таймфреймы → имена интервалов у бирж. У Gate H4 называется так же, у
# Binance тоже — это одна из причин, по которой обе прошли отбор: Coinbase
# Exchange, например, не умеет ни M30, ни H4, ни W1 вовсе.
_BINANCE_TF = {"M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m",
               "H1": "1h", "H4": "4h", "D1": "1d", "W1": "1w"}
_GATE_TF = {"M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m",
            "H1": "1h", "H4": "4h", "D1": "1d", "W1": "7d"}

# Насколько свежим должен быть последний бар, чтобы считать символ живым.
# Три таймфрейма с запасом: рынок крипты круглосуточный, отставание на три бара
# означает, что пару перестали торговать, а не выходные.
_TF_SEC = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800,
           "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800}
_STALE_FACTOR = 3


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _is_stale(bars: list, tf: str) -> bool:
    """Последний бар слишком стар — символ мёртв, что бы ни отвечал эндпоинт цены."""
    if not bars:
        return True
    age = time.time() - bars[-1]["time"]
    return age > _TF_SEC.get(tf, 86400) * _STALE_FACTOR


def _binance(pair: str, tf: str, limit: int) -> list:
    iv = _BINANCE_TF.get(tf)
    if not iv:
        return []
    url = (f"https://data-api.binance.vision/api/v3/klines"
           f"?symbol={pair}&interval={iv}&limit={min(limit, 1000)}")
    raw = _get(url)
    if not isinstance(raw, list):
        return []
    out = []
    for k in raw:
        try:
            out.append({"time": int(k[0]) // 1000, "open": float(k[1]), "high": float(k[2]),
                        "low": float(k[3]), "close": float(k[4])})
        except (IndexError, TypeError, ValueError):
            continue
    return out


def _gate(pair: str, tf: str, limit: int) -> list:
    iv = _GATE_TF.get(tf)
    if not iv:
        return []
    url = (f"https://api.gateio.ws/api/v4/spot/candlesticks"
           f"?currency_pair={pair}&interval={iv}&limit={min(limit, 1000)}")
    raw = _get(url)
    if not isinstance(raw, list):
        return []
    out = []
    for k in raw:
        try:
            # 🔴 Порядок полей Gate: [ts, quote_vol, CLOSE, HIGH, LOW, OPEN,
            # base_vol, closed]. Объём стоит вторым, а OHLC хранится как C,H,L,O.
            if len(k) >= 8 and str(k[7]).lower() == "false":
                continue          # незакрытый бар — перерисуется, брать нельзя
            out.append({"time": int(k[0]), "open": float(k[5]), "high": float(k[3]),
                        "low": float(k[4]), "close": float(k[2])})
        except (IndexError, TypeError, ValueError):
            continue
    return out


def klines(sources: dict, tf: str, limit: int = 1000) -> tuple[list, str | None]:
    """Свечи по инструменту. sources — {"binance": "SHIBUSDT", "gate": "SHIB_USDT"}.

    Возвращает (бары, имя источника). Порядок фиксированный: сначала Binance
    (глубже история и выше лимиты), потом Gate. Пустой или протухший ответ
    первого — не отказ, а повод спросить второго: именно так закрывается BTG,
    по которому Binance отдаёт бары из 2022 года.
    """
    for name, fetch in (("binance", _binance), ("gate", _gate)):
        pair = sources.get(name)
        if not pair:
            continue
        try:
            bars = fetch(pair, tf, limit)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError) as e:
            log.warning("%s %s %s: %s", name, pair, tf, e)
            continue
        if not bars:
            continue
        if _is_stale(bars, tf):
            log.info("%s %s %s: последний бар от %s — пропускаю источник",
                     name, pair, tf,
                     time.strftime("%Y-%m-%d", time.gmtime(bars[-1]["time"])))
            continue
        return bars, name
    return [], None
