"""core/broker_catalog.py — каталог и котировки брокера (SPEC_chart_all_instruments §4 ярус 1, §5).

ОДИН ВЫЗОВ ВМЕСТО ТЫСЯЧИ. `symbols_get()` отдаёт ВЕСЬ каталог разом, и в
каждом объекте уже есть bid/ask/time/price_change. Замер 25.08 на счёте
101746781: 842 символа, 0,02 с на стороне терминала, 0,03 с с переносом
через мост. Это принципиально дешевле `copy_rates_from_pos()`, из-за
которого доливка баров идёт полчаса.

ПОЧЕМУ МОСТ НЕ ЗОВЁТСЯ ИЗ ВЕБ-ЗАПРОСА. «Без задержек» означает именно это:
страница читает снимок, а не ходит в MT5. Мост живёт в Wine, отвечает
неровно и уже бывал заблокирован зависшим прогоном. Синхронный вызов из
обработчика страницы означает, что одно зависание моста вешает сайт.

MARKET WATCH. Котировки приходят только по символам, добавленным в Market
Watch — проверено: из 842 символов вне Market Watch живую котировку не даёт
НИ ОДИН. Массовый `symbol_select` был главным риском всей затеи по спеке;
замер 25.08: выбор всех 842 занимает 1,6 с и добавляет мосту 10 МБ памяти
(0,89 -> 0,90 ГБ), 834 символа отдают котировку в течение 12 секунд.
Группами выбирать не нужно.

ИМЯ ИНСТРУМЕНТА. `description` — НЕ название: у FX там «1 Lot= 100,000 EUR».
Настоящее имя есть только у акций и ETF, в скобках в конце описания
(«1 Lot= 1,000 Shares (BAYER AG)»). Для остального имя берётся из нашего
реестра, а если и там нет — остаётся тикер. Придумывать названия нельзя.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import rpyc

from core.config import BASE_DIR
from core.symbols_registry import resolve as _resolve, _load as _load_registry


def _broker_to_canonical() -> dict[str, str]:
    """Брокерское имя -> наш канонический ключ.

    Реестра алиасов мало: у брокера индексы называются US_500/US_TECH100/US_30,
    нефть CrudeOIL, газ NATURAL_GAS — ни одно из этих имён в aliases нет, и
    resolve() их не узнаёт. Полная таблица уже существует и используется
    доливкой баров — mt5_config.bars_pull_map(); брать её, а не заводить
    третью копию соответствия.
    """
    import mt5_config
    out: dict[str, str] = {}
    for pb_name, broker_name in mt5_config.bars_pull_map().items():
        out[broker_name] = _resolve(pb_name) or pb_name
    return out

log = logging.getLogger("broker_catalog")

BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
WEB_DATA = BASE_DIR / "web" / "data"
# 🔴 ДВА ФАЙЛА, А НЕ ОДИН. Каталог (имена, категории, привязка к нашим
# инструментам) — 138 КБ и меняется раз в недели: его тянут один раз. Котировки
# — то, что опрашивается каждые 15 секунд, и в них не должно быть ни одного
# байта, который не меняется. Один общий файл означал бы 138 КБ × 240 раз в час
# на каждую открытую вкладку, а сервер (http.server) ничего не жмёт.
CATALOG_PATH = WEB_DATA / "broker_catalog.json"
OUT_PATH = WEB_DATA / "broker_quotes.json"

HOST, PORT = "127.0.0.1", 18812
RPC_TIMEOUT = 120

# Верхний уровень symbol_info().path -> наша категория. Разбираем дерево
# брокера, а не заводим свой классификатор руками (§5).
_CATEGORY = {
    "Forex": "fx",
    "CFD-Indices": "index",
    "CFD-Shares": "stock",
    "CFD-ETFs": "etf",
    "CFD-Crypto": "crypto",
    "CFD-Metals": "commodity",
    "CFD-Energies": "commodity",
    "CFD-Agricultural": "commodity",
    "CFD-Bonds": "bond",
}
_FX_PAIR_RE = re.compile(r"^[A-Z]{6}$")
_SHARE_NAME_RE = re.compile(r"\(([^)]{2,60})\)\s*$")


class BridgeUnavailable(RuntimeError):
    """Мост не ответил. Отдельный тип, чтобы вызывающий цикл отличал «MT5
    молчит» от «мы неправильно разобрали ответ» — это разные аварии."""


def categorize(path: str, name: str) -> tuple[str, str | None]:
    """(категория, подгруппа). Подгруппа — второй уровень пути: у акций и ETF
    это страна («CFD-Shares\\Germany\\_BMW.DE»), она же вкладка в интерфейсе."""
    parts = (path or "").split("\\")
    top = parts[0] if parts else ""
    sub = parts[1] if len(parts) > 2 else None
    if top in _CATEGORY:
        return _CATEGORY[top], sub
    if top == "Internal":
        # 17 из 18 — экзотические валютные пары (USDHKD, KESUSD), одна акция
        # (PNCUSD). Раскладываем по форме тикера, а не сваливаем в «прочее».
        return ("fx" if _FX_PAIR_RE.match(name or "") else "other"), None
    return "other", sub


def display_name(name: str, description: str, canonical: str | None) -> str:
    """Имя для интерфейса. Порядок предпочтений — от точного к общему."""
    m = _SHARE_NAME_RE.search(description or "")
    if m:
        return m.group(1).strip()
    if canonical:
        entry = _load_registry().get(canonical)
        if isinstance(entry, dict):
            for key in ("ru", "en"):
                if entry.get(key):
                    return entry[key]
    return name


def fetch_snapshot(select_all: bool = True) -> list[dict]:
    """Снимок всего каталога. Список сборки выполняется НА СТОРОНЕ терминала
    и переносится одним куском: 842 netref-объекта по полю за раз — это
    тысячи round-trip'ов через мост (та же причина, по которой netref-цикл
    сняли в mt5_bridge_pull.py)."""
    try:
        conn = rpyc.classic.connect(HOST, PORT)
        conn._config["sync_request_timeout"] = RPC_TIMEOUT
    except Exception as e:
        raise BridgeUnavailable(f"rpyc-мост не отвечает: {e}") from e
    try:
        conn.execute("import MetaTrader5 as m")
        if not rpyc.classic.obtain(conn.eval("m.initialize()")):
            raise BridgeUnavailable("MetaTrader5.initialize() вернул False")
        if select_all:
            # Только те, что ещё не выбраны: полный проход по 842 стоит 1,6 с,
            # а по факту добавлять почти всегда нечего.
            conn.execute(
                "_add = [s.name for s in m.symbols_get() if not s.select]\n"
                "_added = sum(1 for n in _add if m.symbol_select(n, True))")
            added = rpyc.classic.obtain(conn.namespace["_added"])
            if added:
                log.info("каталог: добавлено в Market Watch %d символов", added)
        conn.execute(
            "_rows = [(s.name, s.description, s.path, s.digits, s.bid, s.ask, "
            "int(s.time), int(s.select), s.price_change) for s in m.symbols_get()]")
        raw = rpyc.classic.obtain(conn.namespace["_rows"])
    except BridgeUnavailable:
        raise
    except Exception as e:
        raise BridgeUnavailable(f"снимок не снят: {e}") from e
    finally:
        try:
            conn.close()
        except Exception:
            pass

    broker_map = _broker_to_canonical()
    out = []
    for name, desc, path, digits, bid, ask, ts, selected, chg in raw:
        canonical = broker_map.get(name) or _resolve(name)
        category, subgroup = categorize(path, name)
        out.append({
            "broker_symbol": name,
            "canonical": canonical,
            "display_name": display_name(name, desc, canonical),
            "category": category,
            "subgroup": subgroup,
            "digits": digits,
            "is_selected": int(bool(selected)),
            # 🔴 quote_ts=None, а не 0 и не «сейчас»: «котировка не приходила»
            # обязано отличаться от «котировка нулевая». Ноль здесь означал бы
            # 1970 год и в интерфейсе выглядел бы как данные.
            "quote_ts": ts or None,
            "bid": bid or None,
            "ask": ask or None,
            "chg_pct": chg,
        })
    return out


def upsert(con: sqlite3.Connection, rows: list[dict], now_ts: int | None = None) -> tuple[int, int]:
    """(новых, обновлённых). Пропавшие из symbols_get() строки НЕ удаляются:
    у них просто перестаёт двигаться last_seen_ts."""
    now = int(now_ts or time.time())
    known = {r[0] for r in con.execute("SELECT broker_symbol FROM broker_symbols")}
    new = upd = 0
    for r in rows:
        if r["broker_symbol"] in known:
            con.execute(
                "UPDATE broker_symbols SET canonical=?, display_name=?, category=?, "
                "subgroup=?, digits=?, is_selected=?, bid=?, ask=?, chg_pct=?, "
                "quote_ts=COALESCE(?, quote_ts), last_seen_ts=? WHERE broker_symbol=?",
                (r["canonical"], r["display_name"], r["category"], r["subgroup"],
                 r["digits"], r["is_selected"], r["bid"], r["ask"], r["chg_pct"],
                 r["quote_ts"], now, r["broker_symbol"]))
            upd += 1
        else:
            con.execute(
                "INSERT INTO broker_symbols (broker_symbol, canonical, display_name, "
                "category, subgroup, digits, is_selected, quote_ts, bid, ask, chg_pct, "
                "first_seen_ts, last_seen_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["broker_symbol"], r["canonical"], r["display_name"], r["category"],
                 r["subgroup"], r["digits"], r["is_selected"], r["quote_ts"], r["bid"],
                 r["ask"], r["chg_pct"], now, now))
            new += 1
    con.commit()
    return new, upd


def _atomic_write(path: Path, payload: dict) -> Path:
    """Через временный файл и replace: страница опрашивает снимок каждые 15
    секунд, и попасть на полузаписанный JSON — вопрос времени, не везения."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    tmp.replace(path)
    return path


def publish_catalog(rows: list[dict], path: Path = CATALOG_PATH) -> Path:
    """Состав каталога: имена, категории, привязка к нашим инструментам.
    Страница тянет его один раз."""
    by_cat: dict[str, int] = {}
    for r in rows:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
    return _atomic_write(path, {
        "updated": datetime.now(timezone.utc).isoformat(),
        "source": "AvaTrade MT5 (Ava-Demo 1-MT5) через rpyc-мост",
        "count": len(rows),
        "categories": by_cat,
        "items": [{
            "symbol": r["broker_symbol"],
            "name": r["display_name"],
            "canonical": r["canonical"],
            "category": r["category"],
            "subgroup": r["subgroup"],
            "digits": r["digits"],
        } for r in rows],
    })


def publish_quotes(rows: list[dict], path: Path = OUT_PATH) -> Path:
    """Только то, что меняется. Ключи короткие — здесь это не микрооптимизация,
    а треть веса файла, который тянут 240 раз в час.

    q=null означает «котировка не приходила» и обязано отличаться от нуля: цена
    ноль — это данные, отсутствие цены — нет. Ровно на этом различии сайт уже
    обжигался, когда мёртвый ряд был неотличим от живого.
    """
    return _atomic_write(path, {
        "updated": datetime.now(timezone.utc).isoformat(),
        "quoted": sum(1 for r in rows if r["quote_ts"]),
        "count": len(rows),
        "items": [[r["broker_symbol"], r["bid"], r["ask"], r["chg_pct"], r["quote_ts"]]
                  for r in rows],
        "fields": ["symbol", "bid", "ask", "chg_pct", "quote_ts"],
    })


def connect_db() -> sqlite3.Connection:
    con = sqlite3.connect(str(BOT_DB), timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    return con
