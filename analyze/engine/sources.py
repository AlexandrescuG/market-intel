#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/engine/sources.py — четыре источника сигналов под общим контрактом.

Каждый источник обязан вернуть полностью годный `Signal`: со стопом, целью,
ATR и горизонтом. Если посчитать барьеры нельзя — источник молчит, а не
перекладывает это на исполнителя.

ПРО ДЕДУПЛИКАЦИЮ, ГЛАВНОЕ В ЭТОМ ФАЙЛЕ
У каждого источника свой масштаб времени, и `dedup_key` обязан ему
соответствовать, иначе повторяется история gold_oil: условие «нефть выше,
чем месяц назад» держится в среднем 4.7 недели, вход делался раз в час, и
118 сделок оказались ОДНИМ эпизодом режима, исполненным 118 раз. Поэтому:

  forecasts — ключ по id прогноза (прогноз одноразовый по построению);
  patterns  — ключ по бару, на котором паттерн сформировался;
  macro     — ключ по ЭПИЗОДУ режима, а не по бару: один вход на эпизод;
  gate      — ключ по бару срабатывания.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time

import core.price_bars as _pb
from analyze.engine.contracts import LONG, SHORT, Signal
from core.patterns import PATTERNS, detect as detect_patterns
from core.symbols_registry import alias_for

TF_SEC = {"1h": 3600, "4h": 14400, "1d": 86400}
TF_CANON = {"H1": "1h", "H4": "4h", "D1": "1d", "1h": "1h", "4h": "4h", "1d": "1d"}

# Инструменты, по которым движок вообще имеет право торговать: те, что есть
# и в price_bars, и в карте брокера. Список сознательно узкий — расширять
# его нужно вместе с проверкой, что у брокера есть эти символы.
#
# 🔴 16.09 добавлен NG (природный газ, у брокера NATURAL_GAS). Проверено
# перед добавлением, а не после: символ есть у брокера, бары есть в
# price_bars (1h с 18.02.2026, 1d с 30.12.2019), минимальный лот стоит
# 1.70 USD при стопе 1.5 ATR.
#
# Газ приходит со СВОИМ пределом издержек (risk.SPREAD_RISK_OVERRIDE): его
# спред — 41% риска при общем пороге 12%, и без послабления инструмент был
# бы включён и молча отвергал каждый сигнал. Послабление узкое и временное,
# правильный выход — геометрия на 4h; см. комментарий у порога.
UNIVERSE = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCNY", "USDZAR", "NG"]

# Геометрия по умолчанию для источников, у которых своей нет.
DEF_STOP_ATR = 1.5
DEF_RR = 2.0
DEF_HORIZON_BARS = 24


def _key(*parts) -> str:
    raw = "|".join(str(p) for p in parts)
    return f"{parts[0]}:{hashlib.sha1(raw.encode()).hexdigest()[:16]}"


def atr(candles: list[dict], i: int, period: int = 14) -> float | None:
    if i < period:
        return None
    tr = [max(candles[k]["h"] - candles[k]["l"],
              abs(candles[k]["h"] - candles[k - 1]["c"]),
              abs(candles[k]["l"] - candles[k - 1]["c"]))
          for k in range(i - period + 1, i + 1)]
    v = sum(tr) / period
    return v if v > 0 else None


def _last_closed(candles: list[dict], tf: str) -> int | None:
    """Индекс последнего ЗАКРЫВШЕГОСЯ бара.

    Доливка кладёт и текущий формирующийся бар. Брать `len-2` вслепую
    безопасно, но когда последний бар уже закрыт — это выбрасывает свежий
    бар и добавляет к задержке целый период на ровном месте."""
    if not candles:
        return None
    i = len(candles) - 1
    if candles[i]["ts"] + TF_SEC.get(tf, 3600) > int(time.time()):
        i -= 1
    return i if i >= 0 else None


def _geometry(price: float, a: float, direction: str,
              stop_atr: float = DEF_STOP_ATR, rr: float = DEF_RR):
    """Барьеры от ЦЕНЫ, симметрично для обеих сторон.

    🔴 Считать от цены, а не от закрытия сигнального бара — урок 19.08:
    между ними лежит весь разрыв доливки, и реальное RR уезжало с 0.5 до
    0.38, а в журнал ложилось не то, что торговалось."""
    d = stop_atr * a
    if direction == LONG:
        return price - d, price + rr * d
    return price + d, price - rr * d


# ─── 1. прогнозы альфа-движка ───────────────────────────────────────────────

def from_forecasts(con: sqlite3.Connection, *, max_age_sec: int = 3 * 3600) -> list[Signal]:
    """Готовые прогнозы модели: symbol/direction/entry/stop/target уже есть.

    Берём только свежие и ещё не истёкшие: прогноз с горизонтом в прошлом
    исполнять бессмысленно, а `valid_until` для того и писался."""
    now = int(time.time())
    rows = con.execute(
        "SELECT id, created_ts, symbol, horizon, direction, conviction, entry, stop, "
        "target, valid_until FROM forecasts WHERE created_ts >= ? ORDER BY created_ts",
        (now - max_age_sec,)).fetchall()
    out: list[Signal] = []
    for fid, cts, symbol, horizon, direction, conv, entry, stop, target, valid in rows:
        if symbol not in UNIVERSE or None in (entry, stop, target):
            continue
        tf = TF_CANON.get(horizon or "H1", "1h")
        d = LONG if str(direction).lower() in ("bullish", "long", "buy") else SHORT
        a = abs(entry - stop) / DEF_STOP_ATR
        if a <= 0:
            continue
        horizon_sec = max(int((valid or 0) - now), TF_SEC[tf] * 4)
        out.append(Signal(
            strategy="alpha_forecast", symbol=symbol, tf=tf, direction=d,
            bar_ts=int(cts), ref_price=float(entry), stop=float(stop),
            target=float(target), atr=a, horizon_sec=horizon_sec,
            dedup_key=_key("alpha_forecast", fid),
            confidence=float(conv or 0.0),
            features={"forecast_id": fid, "conviction": conv, "horizon": horizon}))
    return out


# ─── 2. свечные паттерны по барам брокера ───────────────────────────────────

def _levels(con: sqlite3.Connection, symbol: str) -> list[dict]:
    try:
        rows = con.execute(
            "SELECT price, tolerance, kind FROM sr_levels WHERE symbol=? AND broken=0",
            (symbol,)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [{"price": r[0], "tolerance": r[1], "kind": r[2]} for r in rows]


def from_patterns(con: sqlite3.Connection, *, tfs=("1h", "4h")) -> list[Signal]:
    """core.patterns по данным MT5.

    Берём только паттерн НА ПОСЛЕДНЕМ закрытом баре: детектор возвращает всю
    историю совпадений, и без этого фильтра движок при первом же запуске
    попытался бы войти по всем паттернам за два года разом.

    Нейтральные по направлению паттерны (inside_bar, doji, break_retest)
    пропускаем: у них нет стороны, а угадывать её здесь — это придумать
    стратегию, которой никто не проверял."""
    out: list[Signal] = []
    for symbol in UNIVERSE:
        levels = _levels(con, symbol)
        for tf in tfs:
            candles = _pb.load_candles(symbol, tf)
            if not candles or len(candles) < 60:
                continue
            i = _last_closed(candles, tf)
            if i is None or i < 30:
                continue
            a = atr(candles, i)
            if not a:
                continue
            bar_ts = candles[i]["ts"]
            price = candles[i]["c"]
            for ev in detect_patterns(candles[: i + 1], levels):
                if ev["ts"] != bar_ts:
                    continue
                meta = PATTERNS.get(ev["pattern_key"], {})
                direction = ev.get("direction") or meta.get("direction")
                if direction == "bullish":
                    d = LONG
                elif direction == "bearish":
                    d = SHORT
                else:
                    continue
                stop, target = _geometry(price, a, d)
                out.append(Signal(
                    strategy=f"pattern_{ev['pattern_key']}", symbol=symbol, tf=tf,
                    direction=d, bar_ts=bar_ts, ref_price=price, stop=stop,
                    target=target, atr=a,
                    horizon_sec=DEF_HORIZON_BARS * TF_SEC[tf],
                    dedup_key=_key(f"pattern_{ev['pattern_key']}", symbol, tf, bar_ts),
                    features={"pattern": ev["pattern_key"]}))
    return out


# ─── 2б. те же паттерны, но только в «правильной» зоне у уровня ─────────────
#
# 🔴 17.09, по совету практика и ПО ЗАМЕРУ, а не по совету.
#
# Практик торгует от уровней: часовик, окно около недели, реакция рынка плюс
# объёмы и стакан. Двух его ног у нас нет физически — проверено: Ava
# отказывает в market_book_add, Daoti отдаёт пустой стакан, real_volume всюду
# ноль. Поэтому воспроизводим единственный доступный слой — расстояние от
# входа до сильного уровня — и проверяем, несёт ли оно информацию.
#
# Замер (ops/measure_levels.py, 1h, издержки учтены, сопровождение включено):
#
#   EURUSD  вход ближе 0.25 ATR к уровню   EV +0.0461 [+0.0184 .. +0.0737]
#           общий EV                       +0.0159 [-0.0110 .. +0.0428]
#   NG      вход в 1–2 ATR ОТ уровня       EV +0.2390 [+0.1229 .. +0.3550]
#           ближе 0.25 ATR                 +0.0667 [-0.0443 .. +0.1776]
#
# То есть по валюте близость помогает, а по газу наоборот — лучше работают
# входы МЕЖДУ уровнями. Наивное «торгуем от уровня» данные не подтверждают,
# поэтому зона задаётся для каждого инструмента отдельно и только там, где
# измерена. Проверено на устойчивость по половинам истории: держится в обеих.
#
# 🔴 ЭТО ФИЛЬТР, А НЕ НОВЫЙ ИСТОЧНИК. В замере направление входа задавали
# паттерны, и никакого своего правила стороны здесь нет. Придумать его —
# значит торговать то, чего не мерили.
#
# 🔴 ПЕРЕМЕР 17.09 ПОСЛЕ ПОЧИНКИ ДЕТЕКТОРА. Первые числа были получены на
# сломанном определении фрактала (нестрогое сравнение соседей), и часть из
# них не подтвердилась. Что осталось после починки:
#
#   EURUSD  ближе 0.25 ATR   EV +0.0420 [+0.0143 .. +0.0696]  общий +0.0159
#           по половинам     +0.0302 и +0.0531, обе выше общего
#   NG      ближе 0.25 ATR   EV +0.0787 [-0.0329 .. +0.1903]  общий +0.1310
#           дальше 0.25 ATR  по половинам +0.2369 и +0.1097 — вторая
#                            половина интервалом накрывает ноль
#
# Отсюда два РАЗНЫХ по силе вывода, и смешивать их нельзя:
#   · по EURUSD близость к уровню помогает и держится в обеих половинах —
#     это отбор, ему можно верить осторожно;
#   · по газу «1-2 ATR лучше всего» РАССЫПАЛОСЬ: после починки корзины
#     0.25-2.0 неотличимы друг от друга, а во второй половине истории
#     преимущество теряет значимость. Осталось только то, что вход ВПЛОТНУЮ
#     к уровню слабее прочих. Поэтому здесь не отбор зоны, а ИСКЛЮЧЕНИЕ
#     ближней — утверждение слабее, и записано слабее.
LEVEL_ZONE = {
    "EURUSD": (0.0, 0.25),     # отбор: близость помогает
    "NG": (0.25, 2.0),         # исключение: вплотную к уровню хуже
}
LEVEL_WINDOW = 168        # около недели часовых баров
LEVEL_FRACTAL = 2
LEVEL_MIN_TOUCH = 2
LEVEL_KEEP = 6


def strong_levels(candles: list[dict], i: int, a: float) -> list[float]:
    """Сильные уровни, видимые на момент бара i.

    Только закрытые бары ДО сигнального: иначе это подглядывание.

    Первая версия замера брала все фракталы окна подряд, и в ближнюю корзину
    попадало 84% сделок — такой «фильтр» не отделяет ничего. Поэтому фракталы
    схлопываются в кластеры по 0.25 ATR, и остаются только те, которых рынок
    касался не меньше двух раз."""
    lo = max(LEVEL_FRACTAL, i - LEVEL_WINDOW)
    raw = []
    for k in range(lo, i - LEVEL_FRACTAL):
        # 🔴 Сравнение СТРОГОЕ. С нестрогим (<=) на ровном участке каждый бар
        # оказывается одновременно и максимумом, и минимумом: соседи равны,
        # условие выполняется для всех. Поймано тестом на плоском ряде — из
        # шестидесяти одинаковых баров детектор сделал два «уровня» с
        # полусотней касаний каждый. На живых данных точные равенства редки,
        # но затяжной боковик давал бы ту же выдумку уровней из ничего.
        hi = candles[k]["h"]
        if all(candles[k + d]["h"] < hi
               for d in range(-LEVEL_FRACTAL, LEVEL_FRACTAL + 1) if d):
            raw.append(hi)
        low = candles[k]["l"]
        if all(candles[k + d]["l"] > low
               for d in range(-LEVEL_FRACTAL, LEVEL_FRACTAL + 1) if d):
            raw.append(low)
    if not raw or not a:
        return []
    tol = 0.25 * a
    clusters: list[list[float]] = []
    for p in sorted(raw):
        if clusters and p - clusters[-1][-1] <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    strong = [(len(c), sum(c) / len(c)) for c in clusters if len(c) >= LEVEL_MIN_TOUCH]
    strong.sort(reverse=True)
    return [p for _, p in strong[:LEVEL_KEEP]]


def from_level_zone(con: sqlite3.Connection) -> list[Signal]:
    """Паттерновые сигналы, прошедшие фильтр по расстоянию до уровня.

    Отдельная стратегия со своей кривой R — чтобы через 30-50 сделок можно
    было сравнить её с родительскими паттернами и понять, переносится ли
    эффект с истории на форвард. Идёт в тени: на истории он держится, но мы
    уже обжигались на том, что история и форвард расходятся."""
    out: list[Signal] = []
    for s in from_patterns(con, tfs=("1h",)):
        zone = LEVEL_ZONE.get(s.symbol)
        if not zone:
            continue
        candles = _pb.load_candles(s.symbol, s.tf)
        i = _last_closed(candles, s.tf) if candles else None
        if i is None or i < LEVEL_FRACTAL + 5:
            continue
        lv = strong_levels(candles, i, s.atr)
        if not lv:
            continue
        d = min(abs(s.ref_price - x) for x in lv) / s.atr
        if not (zone[0] <= d < zone[1]):
            continue
        out.append(Signal(
            strategy="level_zone", symbol=s.symbol, tf=s.tf,
            direction=s.direction, bar_ts=s.bar_ts, ref_price=s.ref_price,
            stop=s.stop, target=s.target, atr=s.atr, horizon_sec=s.horizon_sec,
            dedup_key=_key("level_zone", s.symbol, s.tf, s.bar_ts),
            features={"parent": s.strategy, "level_dist_atr": round(d, 3),
                      "levels": len(lv)}))
    return out


# ─── 3. макро-режимы ────────────────────────────────────────────────────────

def _macro_series(con: sqlite3.Connection, code: str, ts: int, n: int) -> list[float]:
    """N последних значений, известных на момент ts.

    Отсчёт по РАЗЛИЧНЫМ датам периода, внутри даты — последняя ревизия.
    🔴 27.08: раньше здесь был `ORDER BY asof_ts DESC LIMIT n` по строкам, а
    бэкфилл FRED сложил историю под считанные даты публикации (у нефти
    19 119 строк на одной 2011-04-06). «N публикаций назад» означало «N-я
    строка неупорядоченного списка», и значение скакало без связи с рынком."""
    rows = con.execute(
        "SELECT value FROM (SELECT ts, value, ROW_NUMBER() OVER "
        "(PARTITION BY ts ORDER BY asof_ts DESC, rev DESC) rn "
        "FROM factor_values WHERE factor_key=? AND asof_ts<=?) "
        "WHERE rn=1 ORDER BY ts DESC LIMIT ?", (f"macro.{code}", ts, n)).fetchall()
    return [r[0] for r in rows]


# Правило: (имя, символ, фактор, окно, направление при росте фактора).
# gold_oil перенесён как есть — он единственный, кто прошёл планку издержек;
# остальные заведены как кандидаты и будут видны в журнале отдельно.
MACRO_RULES = [
    ("macro_gold_oil", "XAUUSD", "DCOILWTICO", 20, LONG),
    ("macro_gold_dxy", "XAUUSD", "DTWEXBGS", 20, SHORT),
    ("macro_eur_dxy", "EURUSD", "DTWEXBGS", 20, SHORT),
]


def from_macro(con: sqlite3.Connection, *, tf: str = "1h") -> list[Signal]:
    """Режимные правила: фактор выше/ниже, чем N публикаций назад.

    🔴 ГЛАВНОЕ ОТЛИЧИЕ ОТ СТАРОГО КОНТУРА — дедупликация по ЭПИЗОДУ.
    Условие держится неделями (замер по двум годам: режим живёт в среднем
    4.7 недели), а планировщик ходит раз в час. Старый код входил на каждом
    прогоне, и 118 сделок оказались одним эпизодом режима, исполненным 118
    раз: `n_eff=30` из поправки на перекрытие всё равно льстил, честное
    число независимых наблюдений было ближе к единице.

    Здесь ключ включает момент ПЕРЕКЛЮЧЕНИЯ режима, поэтому на один эпизод
    приходится ровно один вход. Это делает выборку интерпретируемой ценой
    того, что сделок станет в разы меньше — и это правильный размен."""
    out: list[Signal] = []
    now = int(time.time())
    for name, symbol, code, back, direction_up in MACRO_RULES:
        series = _macro_series(con, code, now, back + 60)
        if len(series) < back + 2:
            continue
        state = series[0] > series[back]
        # ищем, когда состояние стало таким — это и есть начало эпизода
        episode_start = None
        for shift in range(0, len(series) - back - 1):
            prev_state = series[shift + 1] > series[shift + back + 1]
            if prev_state != state:
                episode_start = shift
                break
        if episode_start is None:
            episode_start = len(series) - back - 1
        d = direction_up if state else (SHORT if direction_up == LONG else LONG)

        candles = _pb.load_candles(symbol, tf)
        if not candles:
            continue
        i = _last_closed(candles, tf)
        if i is None or i < 30:
            continue
        a = atr(candles, i)
        if not a:
            continue
        price = candles[i]["c"]
        stop, target = _geometry(price, a, d)
        out.append(Signal(
            strategy=name, symbol=symbol, tf=tf, direction=d, bar_ts=candles[i]["ts"],
            ref_price=price, stop=stop, target=target, atr=a,
            horizon_sec=DEF_HORIZON_BARS * TF_SEC[tf],
            # ключ по эпизоду: состояние + сколько публикаций назад оно началось
            dedup_key=_key(name, symbol, int(state), f"ep{episode_start}",
                           round(series[episode_start], 4)),
            features={"factor": code, "now": series[0], "back": series[back],
                      "state_rising": state, "episode_offset": episode_start}))
    return out


# ─── 4. входы гейта ─────────────────────────────────────────────────────────

def from_gate(con: sqlite3.Connection, *, tf: str = "1h",
              lookback_sec: int = 2 * 3600) -> list[Signal]:
    """Срабатывания гейта альфа-движка как самостоятельная стратегия.

    Гейт уже считает `move_atr` и `level_break` на каждом прогоне и пишет в
    `gate_log`; здесь мы просто перестаём выбрасывать эту работу. Направление
    берём по знаку движения — гейт его не хранит, а придумывать иное правило
    значило бы завести непроверенную стратегию под видом существующей.

    `news_burst_z` из гейта здесь не участвует осознанно: он NULL во всех
    2005 строках (`state_vector.py` возвращает жёсткий None), то есть
    новостного входа в природе пока нет."""
    now = int(time.time())
    rows = con.execute(
        "SELECT symbol, tf, move_atr, level_break, calendar_prox, ts FROM gate_log "
        "WHERE ts >= ? AND gated=1 ORDER BY ts", (now - lookback_sec,)).fetchall()
    seen: set[tuple] = set()
    out: list[Signal] = []
    for symbol, gtf, move_atr, level_break, cal, ts in rows:
        if symbol not in UNIVERSE or not move_atr:
            continue
        tfc = TF_CANON.get(gtf or "H1", "1h")
        if tfc != tf:
            continue
        candles = _pb.load_candles(symbol, tf)
        if not candles:
            continue
        i = _last_closed(candles, tf)
        if i is None or i < 30:
            continue
        bar_ts = candles[i]["ts"]
        if (symbol, bar_ts) in seen:
            continue
        seen.add((symbol, bar_ts))
        a = atr(candles, i)
        if not a:
            continue
        # продолжение движения: знак move_atr задаёт сторону
        d = LONG if move_atr > 0 else SHORT
        price = candles[i]["c"]
        stop, target = _geometry(price, a, d)
        out.append(Signal(
            strategy="gate_momentum", symbol=symbol, tf=tf, direction=d,
            bar_ts=bar_ts, ref_price=price, stop=stop, target=target, atr=a,
            horizon_sec=DEF_HORIZON_BARS * TF_SEC[tf],
            dedup_key=_key("gate_momentum", symbol, tf, bar_ts),
            features={"move_atr": move_atr, "level_break": level_break,
                      "calendar_prox": cal}))
    return out


ALL_SOURCES = {
    "alpha_forecast": from_forecasts,
    "patterns": from_patterns,
    "macro": from_macro,
    "gate": from_gate,
    # 17.09: фильтр по расстоянию до уровня. Новая стратегия стартует в тени
    # (движок заводит незнакомые стратегии со статусом shadow, если не
    # передан --live), и это здесь не случайность, а замысел: эффект держится
    # на истории, форвард ещё не проверен.
    "level_zone": from_level_zone,
}


def collect(con: sqlite3.Connection, enabled: list[str] | None = None) -> list[Signal]:
    """Все сигналы одного прогона. Падение одного источника не должно
    отменять остальные — §0 общей спеки, «шаг возвращает результат, а не
    бросает»."""
    out: list[Signal] = []
    for name, fn in ALL_SOURCES.items():
        if enabled and name not in enabled:
            continue
        try:
            out.extend(fn(con))
        except Exception as e:                      # noqa: BLE001
            out.append(_failed_marker(name, e))
    return [s for s in out if s is not None]


def _failed_marker(name: str, e: Exception):
    """Источник упал — это событие, а не пустота. Возвращаем None, но
    печатаем: молча пропущенный источник неотличим от источника без
    сигналов, а это разные вещи."""
    print(f"[engine] источник {name} упал: {type(e).__name__}: {e}", flush=True)
    return None
