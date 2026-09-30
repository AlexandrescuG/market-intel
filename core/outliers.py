"""core/outliers.py — аномальные движения цены (SPEC_brief_outliers_2026-08-25 §2).

ЗАЧЕМ. Утренний брифинг строился только из наших 25 макроинструментов, и
событие вроде «Moderna выросла в моменте на сотню процентов» не могло попасть
в него ни при каких условиях — не потому что порог высокий, а потому что за
пределы своего списка система не смотрела вовсе.

Источник — готовые скринеры Yahoo (весь рынок США без собственного обхода
тысяч тикеров) плюс срез спота Bybit по крипте.

🔴 Проверено 25.08 на живых данных: `yfinance` 1.4.1, API — `yf.screen(name)`
(в старых версиях был `yf.Screener`, спека просила это выяснить до
проектирования). Прямой HTTP к `query*.finance.yahoo.com` не понадобился.
Крипты среди предопределённых скринеров Yahoo НЕТ вообще (`yf.screen`
принимает только Equity/Fund/ETF-запросы) — отсюда отдельный источник.

Bybit здесь — это НЕ возврат к тому, что убрали 20.08. Тогда сокет Bybit
подменял цену НАШИХ инструментов поверх баров брокера; здесь это срез всего
рынка (549 пар одним запросом) для поиска чужих движений, а цену наших
инструментов он по-прежнему не трогает.

ПОЧЕМУ ФИЛЬТРЫ ПО ЦЕНЕ И ОБЪЁМУ ТОРГОВ ОБЯЗАТЕЛЬНЫ. Без них скринер день за
днём выдаёт копеечные бумаги с ростом 300% при объёме торгов в сто тысяч
долларов. Это не рыночное событие, а шум, и он утопит настоящие находки. Замер
25.08: в `day_gainers` минимальный дневной объём 203 тыс. при медиане 108 млн —
то есть отсекаемый хвост там есть всегда.

ТЕРМИНОЛОГИЯ (02.09, поправка владельца). `dollar_volume` — это ОБЪЁМ ТОРГОВ в
деньгах (цена × regularMarketVolume), сколько прошло через сделки с бумагой за
день. Не «оборот»: оборотом компании называют её выручку, деньги внутри
бизнеса, — это другое число из другого источника. В текстах наружу писать
«объём торгов».
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

log = logging.getLogger("outliers")

_CONFIG_PATH = Path(__file__).with_name("outliers_config.json")

EQUITY_SCREENERS = ("day_gainers", "day_losers")
_BYBIT_TICKERS = "https://api.bybit.com/v5/market/tickers?category=spot"

# Сколько строк просить у скринера. Yahoo сортирует по модулю изменения, так
# что настоящие выбросы всегда в начале; 100 — с запасом, замер 25.08 показал
# 78 строк во всей выдаче day_gainers.
_SCREENER_COUNT = 100


class SourceFailed(RuntimeError):
    """Источник не ответил. Отдельный тип, чтобы вызывающий джоб мог отличить
    «сегодня выбросов нет» от «мы сегодня не смотрели» — §7 спеки: путь,
    который может закончиться ничем, обязан себя обнаруживать."""


_DEFAULT_CONFIG = {
    "equity": {"abs_chg_pct": 20.0, "min_price_usd": 1.0, "min_dollar_volume": 5_000_000},
    "crypto": {"abs_chg_pct": 30.0, "min_dollar_volume": 20_000_000},
    "max_alerts_per_day": 5,
    "repeat_step_fraction": 0.5,
    "quiet_mode_until": "2026-09-01",
    "alert_target": "subscribers",
    "subscriber_quiet_hours": [22, 8],
}


def load_config() -> dict:
    try:
        cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("outliers_config.json не прочитан (%s) — значения по умолчанию", e)
        cfg = {}
    merged = {**_DEFAULT_CONFIG, **{k: v for k, v in cfg.items() if not k.startswith("_")}}
    for section in ("equity", "crypto"):
        merged[section] = {**_DEFAULT_CONFIG[section], **(cfg.get(section) or {})}
    return merged


def _peak_pct(prev_close, high, low, chg_pct):
    """«Рост В МОМЕНТЕ» — прямое требование владельца. Если писать только
    последнее значение, к вечеру от находки останется +12%, и завтрашний
    брифинг соврёт о масштабе. Берём экстремум в СТОРОНУ движения: для роста
    максимум дня, для падения минимум."""
    try:
        prev = float(prev_close)
        if not prev:
            return None
        edge = float(high) if (chg_pct or 0) >= 0 else float(low)
        return round((edge / prev - 1) * 100, 2)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def fetch_equity(cfg: dict) -> tuple[list[dict], bool]:
    """(строки за порогом, открыт ли рынок США).

    Открытость НЕ вычисляется по календарю и не берётся из чужого признака
    свежести баров: каждая котировка скринера несёт `marketState` — это
    измеренный факт из тех же данных, которые мы и так забираем.
    """
    import yfinance as yf

    thr = cfg["equity"]
    rows, states, failures = [], set(), []
    for screener in EQUITY_SCREENERS:
        try:
            payload = yf.screen(screener, count=_SCREENER_COUNT)
            quotes = (payload or {}).get("quotes") or []
        except Exception as e:
            failures.append(f"{screener}: {type(e).__name__} {e}")
            continue
        for q in quotes:
            states.add(q.get("marketState") or "")
            price = q.get("regularMarketPrice")
            vol = q.get("regularMarketVolume")
            chg = q.get("regularMarketChangePercent")
            if price is None or chg is None:
                continue
            dollar_volume = float(price) * float(vol or 0)
            if abs(float(chg)) < thr["abs_chg_pct"]:
                continue
            if float(price) < thr["min_price_usd"]:
                continue
            if dollar_volume < thr["min_dollar_volume"]:
                continue
            rows.append({
                "symbol": q["symbol"],
                "name": q.get("longName") or q.get("shortName") or q["symbol"],
                "asset_class": "equity",
                "chg_pct": round(float(chg), 2),
                "price": round(float(price), 4),
                "dollar_volume": round(dollar_volume),
                # 02.09: капитализация идёт рядом с объёмом торгов — одно
                # число без другого вводит в заблуждение («$694 млн» читается
                # как размер компании, хотя это дневной объём торгов). Скринер
                # отдаёт marketCap в том же ответе, отдельный запрос не нужен.
                "market_cap": (round(float(q["marketCap"]))
                               if q.get("marketCap") is not None else None),
                "screener": screener,
                "peak_chg_pct": _peak_pct(q.get("regularMarketPreviousClose"),
                                          q.get("regularMarketDayHigh"),
                                          q.get("regularMarketDayLow"), chg),
            })
    if failures and len(failures) == len(EQUITY_SCREENERS):
        raise SourceFailed("скринеры Yahoo не ответили: " + "; ".join(failures))
    if failures:
        log.warning("outliers: часть скринеров не ответила: %s", "; ".join(failures))
    market_open = bool(states & {"REGULAR", "PRE", "POST"})
    return rows, market_open


def fetch_crypto(cfg: dict) -> list[dict]:
    thr = cfg["crypto"]
    try:
        r = httpx.get(_BYBIT_TICKERS, timeout=15)
        r.raise_for_status()
        listing = r.json()["result"]["list"]
    except Exception as e:
        raise SourceFailed(f"Bybit не ответил: {type(e).__name__} {e}") from e

    rows = []
    for t in listing:
        sym = t.get("symbol") or ""
        # Котируем к USDT: пары к BTC/ETH дают то же движение дважды и
        # засоряют выдачу, а сравнивать их порог по объёму торгов не с чем.
        if not sym.endswith("USDT"):
            continue
        try:
            chg = float(t["price24hPcnt"]) * 100
            turnover = float(t["turnover24h"])
            price = float(t["lastPrice"])
        except (KeyError, TypeError, ValueError):
            continue
        if abs(chg) < thr["abs_chg_pct"] or turnover < thr["min_dollar_volume"]:
            continue
        rows.append({
            "symbol": sym,
            "name": sym[:-4],
            "asset_class": "crypto",
            "chg_pct": round(chg, 2),
            "price": price,
            "dollar_volume": round(turnover),
            "screener": "bybit_spot",
            "peak_chg_pct": _peak_pct(t.get("prevPrice24h"), t.get("highPrice24h"),
                                      t.get("lowPrice24h"), chg),
        })
    return rows


def upsert(con, rows: list[dict], now_ts: int | None = None) -> tuple[int, int]:
    """(новых, обновлённых). Один инструмент — одна запись в сутки.

    `peak_chg_pct` только РАСТЁТ по модулю: скан раз в 15 минут видит цену на
    момент опроса, а пик между опросами иначе потерялся бы.
    """
    now = int(now_ts or time.time())
    new = updated = 0
    for r in rows:
        cur = con.execute(
            "SELECT id, peak_chg_pct FROM market_outliers "
            "WHERE symbol=? AND date(first_seen_ts,'unixepoch')=date(?,'unixepoch')",
            (r["symbol"], now),
        ).fetchone()
        peak = r.get("peak_chg_pct")
        if cur is None:
            con.execute(
                "INSERT INTO market_outliers (first_seen_ts, last_seen_ts, symbol, name, "
                "asset_class, chg_pct, price, dollar_volume, screener, peak_chg_pct, "
                "market_cap) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (now, now, r["symbol"], r["name"], r["asset_class"], r["chg_pct"],
                 r["price"], r["dollar_volume"], r["screener"], peak,
                 r.get("market_cap")),
            )
            new += 1
        else:
            oid, old_peak = cur
            if peak is None or (old_peak is not None and abs(old_peak) >= abs(peak)):
                peak = old_peak
            con.execute(
                "UPDATE market_outliers SET last_seen_ts=?, chg_pct=?, price=?, "
                "dollar_volume=?, screener=?, peak_chg_pct=?, "
                # COALESCE: у крипты market_cap нет вовсе, и пустое значение
                # не должно затирать уже записанное по акции.
                "market_cap=COALESCE(?, market_cap) WHERE id=?",
                (now, r["chg_pct"], r["price"], r["dollar_volume"], r["screener"], peak,
                 r.get("market_cap"), oid),
            )
            updated += 1
    con.commit()
    return new, updated


def today_rows(con, now_ts: int | None = None) -> list[dict]:
    now = int(now_ts or time.time())
    cur = con.execute(
        "SELECT id, symbol, name, asset_class, chg_pct, peak_chg_pct, price, "
        "dollar_volume, market_cap, screener, first_seen_ts, last_seen_ts, alerted_ts, "
        "alert_suppressed, news_cluster_id FROM market_outliers "
        "WHERE date(first_seen_ts,'unixepoch')=date(?,'unixepoch') "
        "ORDER BY abs(peak_chg_pct) DESC, abs(chg_pct) DESC",
        (now,),
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
