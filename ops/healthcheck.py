#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ops/healthcheck.py — надзор за собственными остановками.

SPEC_supervision_2026-08-26 §5.

ЗАЧЕМ. За август один и тот же класс ошибки вылез шесть раз: `run_cycle` с
exit(0) при отказе (цикл стоял двое суток, systemd видел успех); `.catch` с
пустым объектом на /brokers; `Trigger: n/a` у таймера при активном сервисе;
26 инструментов, двенадцать дней рисовавших август настоящим; мост MT5,
семь часов простоявший active-но-мёртвым после перезагрузки; и
broker_catalog_loop, который по замыслу кричит РОВНО ОДИН раз и дальше
молчит — 495 отказов подряд ушли в тишину. Каждый раз замечал человек.

ЧТО ПРОВЕРЯЕТ. Две вещи, как в спеке, плюс третью, которой спека не знала:
  1. Юниты — по ops/units.txt (единый список, §4.2).
  2. Свежесть данных — price_bars, quotes.json, ohlc_*_H1.json, heartbeats.
  3. 🔴 Живость МОСТА, а не его процесса. Именно этого не хватило 26.08.

ЧЕГО НЕ ДЕЛАЕТ. Ничего не чинит. Надзор, который сам перезапускает сервисы,
маскирует причину циклом перезапусков — ровно то, о чём предупреждает §2.3
спеки. Задача этого файла — сделать тихую остановку громкой, и только.

Запуск:
    python3 -m ops.healthcheck            # проверить и, если надо, дать алерт
    python3 -m ops.healthcheck --dry-run  # напечатать отчёт, ничего не слать
    python3 -m ops.healthcheck --verbose  # печатать и то, что в порядке

Код выхода: 0 — расхождений нет; 1 — есть; 2 — сам надзор сломался.
"""
from __future__ import annotations

import argparse
import asyncio
import glob as globmod
import json
import logging
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

log = logging.getLogger("healthcheck")

CONFIG_PATH = Path(__file__).resolve().parent / "healthcheck_config.json"


# ─────────────────────────────────────────────────────────────────────────────
# Находки
# ─────────────────────────────────────────────────────────────────────────────

class Finding:
    """Одно расхождение. `key` — устойчивый идентификатор для антиспама:
    он должен быть одинаковым у одной и той же проблемы в разных прогонах,
    иначе каждый тик будет считаться новой бедой и антиспам не сработает."""

    def __init__(self, key: str, text: str):
        self.key = key
        self.text = text

    def __repr__(self) -> str:                                # pragma: no cover
        return f"<Finding {self.key}: {self.text}>"


def _age(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 90:
        return f"{seconds} с"
    if seconds < 5400:
        return f"{seconds // 60} мин"
    if seconds < 172800:
        return f"{seconds // 3600} ч"
    return f"{seconds // 86400} сут"


# ─────────────────────────────────────────────────────────────────────────────
# Юниты
# ─────────────────────────────────────────────────────────────────────────────

def parse_units(path: Path) -> list[dict]:
    """Разбор ops/units.txt. Формат см. в шапке самого файла."""
    units = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 3:
            raise ValueError(f"{path}:{lineno}: ждал минимум 3 колонки, вижу {raw!r}")
        unit, role, max_idle = parts[0], parts[1], parts[2]
        if role not in ("daemon", "timer", "off"):
            raise ValueError(f"{path}:{lineno}: неизвестная роль {role!r}")
        units.append({
            "unit": unit,
            "role": role,
            "max_idle": int(max_idle),
            "flags": set(parts[3:]),
        })
    return units


def _sc(*args: str) -> str:
    """systemctl --user, всегда без пейджера и без падения на ненулевом коде."""
    try:
        r = subprocess.run(["systemctl", "--user", "--no-pager", *args],
                           capture_output=True, text=True, timeout=30)
        return (r.stdout or "").strip()
    except Exception as e:                                    # pragma: no cover
        log.warning("systemctl %s: %s", " ".join(args), e)
        return ""


def _parse_stamp(v: str) -> float | None:
    """systemd печатает штампы как "Wed 2026-08-26 09:44:00 EEST"."""
    m = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", v or "")
    if not m:
        return None
    try:
        naive = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        return naive.replace(tzinfo=datetime.now().astimezone().tzinfo).timestamp()
    except Exception:
        return None


def _last_run_ts(service: str, timer: str | None = None) -> float | None:
    """Когда прогон в последний раз ЗАПУСКАЛСЯ.

    🔴 Спека предлагает мерить это по InactiveExitTimestamp сервиса, но у
    user-менеджера это поле обнуляется при перезагрузке: после ребута
    недельный sbf-pattern-stats выглядит «не запускался ни разу», и надзор
    поднимает ложную тревогу по всем редким таймерам разом. Поймано первым
    же прогоном 26.08.

    LastTriggerUSec самого ТАЙМЕРА переживает перезагрузку (systemd хранит
    его на диске для Persistent=true), поэтому он и основной источник.
    InactiveExitTimestamp остаётся запасным — для ручных запусков сервиса
    в обход таймера."""
    stamps = []
    if timer:
        stamps.append(_parse_stamp(_sc("show", "-p", "LastTriggerUSec", "--value", timer)))
    stamps.append(_parse_stamp(_sc("show", "-p", "InactiveExitTimestamp", "--value", service)))
    real = [s for s in stamps if s]
    return max(real) if real else None


def check_units(units: list[dict], verbose: bool) -> list[Finding]:
    out: list[Finding] = []
    now = time.time()
    for u in units:
        name, role = u["unit"], u["role"]
        active = _sc("is-active", name) or "unknown"

        if role == "off":
            # Обратная проверка: карта говорит «выключен» — значит включённым
            # он тоже быть не должен, иначе карта врёт.
            if active == "active":
                out.append(Finding(f"unit-off-{name}",
                                   f"{name}: помечен в units.txt как выключённый, но он active — "
                                   f"карта запуска разошлась с реальностью"))
            elif verbose:
                print(f"  ok   {name}: выключён, как и задумано")
            continue

        if active != "active":
            out.append(Finding(f"unit-down-{name}",
                               f"{name}: не запущен (состояние {active})"))
            continue

        if role == "daemon":
            if verbose:
                print(f"  ok   {name}: active")
            continue

        # role == timer: сам таймер жив, но стреляет ли он?
        service = name[:-len(".timer")] + ".service"
        state = _sc("is-active", service) or "unknown"
        if state == "failed" and "allow-failed" not in u["flags"]:
            msg = _sc("show", "-p", "Result", "--value", service)
            out.append(Finding(f"unit-failed-{service}",
                               f"{service}: последний прогон закончился ошибкой (Result={msg or '?'})"))
        if state == "activating":
            # 🔴 Тот самый зависший прогон: сервис вечно «стартует», а таймер
            # из-за этого не выстрелит больше никогда.
            started = _last_run_ts(service, name)
            if started and now - started > u["max_idle"]:
                out.append(Finding(f"unit-stuck-{service}",
                                   f"{service}: висит в activating уже {_age(now - started)} — "
                                   f"таймер заблокирован и больше не стреляет"))
                continue

        last = _last_run_ts(service, name)
        if last is None:
            out.append(Finding(f"unit-never-{service}",
                               f"{service}: таймер активен, но сервис не запускался ни разу"))
        elif now - last > u["max_idle"]:
            out.append(Finding(f"unit-idle-{service}",
                               f"{service}: последний прогон {_age(now - last)} назад "
                               f"(предел {_age(u['max_idle'])})"))
        elif verbose:
            print(f"  ok   {name}: прогон {_age(now - last)} назад")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Свежесть данных
# ─────────────────────────────────────────────────────────────────────────────

def check_price_bars(cfg: dict, verbose: bool) -> tuple[list[Finding], bool]:
    """Возвращает (находки, рынок_открыт).

    🔴 «Рынок открыт» здесь ИЗМЕРЯЕТСЯ свидетелями, а не объявляется по
    календарю сессий. Крипта идёт тем же конвейером MT5 → price_bars, но
    торгуется круглосуточно: если она свежая, а форекс стоит — рынок закрыт,
    и молчать правильно. Если стоит и она — сломан конвейер, и молчать
    нельзя. Второго календаря сессий в проекте не заводим (§5 спеки)."""
    out: list[Finding] = []
    db = Path(cfg["db"])
    if not db.exists():
        return [Finding("bars-db", f"price_bars: база {db} не найдена")], True

    tf = cfg["timeframe"]
    max_age = cfg["max_age_sec"]
    ignore = set(cfg.get("ignore_symbols", []))
    witnesses = set(cfg.get("witness_symbols", []))
    now = time.time()

    con = sqlite3.connect(str(db), timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    try:
        rows = con.execute(
            "SELECT symbol, MAX(ts) FROM price_bars WHERE tf=? GROUP BY symbol", (tf,)
        ).fetchall()
    finally:
        con.close()

    if not rows:
        return [Finding("bars-empty", f"price_bars: ни одного бара с tf={tf}")], True

    if verbose:
        # Ни одно исключение не должно быть молчаливым: заглушённый символ
        # печатаем с его настоящим возрастом, чтобы «известная дыра» не
        # превратилась незаметно в «дыра, про которую все забыли».
        for s, ts in sorted(rows):
            if s in ignore:
                print(f"  ok   price_bars {s}: заглушён по known_gaps, "
                      f"фактически {_age(now - ts)}")

    ages = {s: now - ts for s, ts in rows if s not in ignore}
    if not ages:
        return [Finding("bars-empty", f"price_bars: после исключений не осталось символов")], True

    # Три РАЗНЫХ вопроса, которые легко склеить в один и получить ложный вывод
    # (склеил при первой сборке 26.08 и поймал на синтетике):
    #
    #   1. Жив ли конвейер?      — свежа ли крипта: она торгуется 24/7.
    #   2. Открыт ли рынок?      — свеж ли ХОТЬ ОДИН форекс-символ.
    #   3. Что именно встало?    — список отставших.
    #
    # Свежая крипта НЕ означает «рынок открыт»: в воскресенье BTC идёт, а
    # форекс стоит, и это норма. Молчать можно ровно в одном сочетании:
    # конвейер жив И форекса свежего нет вовсе (значит, встал весь разом —
    # так выглядит закрытие, а не поломка).
    witness_ages = [a for s, a in ages.items() if s in witnesses]
    fx_ages = {s: a for s, a in ages.items() if s not in witnesses}

    if witness_ages:
        pipeline_alive = min(witness_ages) <= max_age
    else:
        # Свидетелей нет — отличить закрытие от поломки нечем. Строгость
        # тихо занижать нельзя: считаем конвейер мёртвым и говорим обо всём.
        pipeline_alive = False
        out.append(Finding("bars-no-witness",
                           "price_bars: ни одного символа-свидетеля "
                           f"({', '.join(sorted(witnesses))}) — отличить закрытый "
                           "рынок от вставшего конвейера нечем"))

    market_open = any(a <= max_age for a in fx_ages.values())
    # Форекс встал ВЕСЬ и при этом крипта идёт — это выходные, а не авария.
    quiet_market = pipeline_alive and fx_ages and not market_open

    stale = sorted((s for s, a in ages.items() if a > max_age),
                   key=lambda s: -ages[s])
    stale_w = [s for s in stale if s in witnesses]
    stale_fx = [s for s in stale if s not in witnesses]

    if stale_w:
        # Крипта не спит никогда: её отставание — всегда поломка.
        head = ", ".join(f"{s} ({_age(ages[s])})" for s in stale_w)
        out.append(Finding("bars-stale-witness-" + ",".join(sorted(stale_w)),
                           f"price_bars ({tf}): встали круглосуточные символы — {head}. "
                           f"Это не выходные, это конвейер"))

    if stale_fx and not quiet_market:
        head = ", ".join(f"{s} ({_age(ages[s])})" for s in stale_fx[:6])
        more = f" и ещё {len(stale_fx) - 6}" if len(stale_fx) > 6 else ""
        # Ключ по СОСТАВУ, а не по возрасту: иначе каждый тик — «новая» беда
        # и антиспам не сработает ни разу.
        out.append(Finding("bars-stale-" + ",".join(sorted(stale_fx)),
                           f"price_bars ({tf}): встали {len(stale_fx)} символов — {head}{more}"))
    elif stale_fx and verbose:
        print(f"  ok   price_bars: форекс стоит весь ({len(stale_fx)} символов), "
              f"крипта свежая — рынок закрыт")
    elif not stale and verbose:
        print(f"  ok   price_bars: все {len(ages)} символов свежие")

    return out, not quiet_market


def check_quotes_json(cfg: dict, verbose: bool) -> list[Finding]:
    path = BASE / cfg["path"]
    if not path.exists():
        return [Finding("quotes-missing", f"{cfg['path']}: файла нет")]
    try:
        upd = json.loads(path.read_text(encoding="utf-8"))["updated"]
        ts = datetime.fromisoformat(upd).timestamp()
    except Exception as e:
        return [Finding("quotes-broken", f"{cfg['path']}: не читается поле updated ({e})")]
    age = time.time() - ts
    if age > cfg["max_age_sec"]:
        return [Finding("quotes-stale",
                        f"{cfg['path']}: обновлён {_age(age)} назад "
                        f"(предел {_age(cfg['max_age_sec'])}) — quotes_loop встал")]
    if verbose:
        print(f"  ok   {cfg['path']}: {_age(age)} назад")
    return []


def check_broker_quotes(cfg: dict, verbose: bool) -> list[Finding]:
    """🔴 Каталог брокера — 842 котировки левой панели графика.

    Это самая широкая поверхность с ценами в проекте, и до 26.08 её не
    сторожило НИЧЕГО. В тот день broker_catalog_loop не мог достучаться до
    моста семь часов подряд: по замыслу он кричит ровно один раз после
    четвёртого отказа и дальше молчит, чтобы не забить лог. Сервис при этом
    оставался active, файл просто перестал переписываться, и панель показывала
    вчерашние цены без единого признака, что они вчерашние.

    Меряем ДВЕ вещи, потому что одной мало:
      • `updated` — пишет ли цикл вообще (то, что встало 26.08);
      • `quoted` — сколько символов реально отдали цену. Мост может отвечать,
        а терминал вернуть пустой Market Watch: файл свежий, а внутри дыра.

    Возраст самих котировок (`quote_ts`) НЕ проверяем: у акций и ETF из этого
    каталога он честно старый вне часов их биржи — медиана 11,5 ч в обычный
    рабочий день. Порог по нему был бы вечно ложным."""
    path = BASE / cfg["path"]
    if not path.exists():
        return [Finding("bq-missing", f"{cfg['path']}: файла нет — левая панель графика пуста")]
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(d["updated"]).timestamp()
        quoted, count = int(d.get("quoted", 0)), int(d.get("count", 0))
    except Exception as e:
        return [Finding("bq-broken", f"{cfg['path']}: не читается ({e})")]

    out = []
    age = time.time() - ts
    if age > cfg["max_age_sec"]:
        out.append(Finding("bq-stale",
                           f"{cfg['path']}: обновлён {_age(age)} назад "
                           f"(предел {_age(cfg['max_age_sec'])}) — broker_catalog_loop "
                           f"не пишет, а сервис при этом active"))
    if count and quoted < count * cfg["min_quoted_ratio"]:
        out.append(Finding("bq-thin",
                           f"{cfg['path']}: цену отдали только {quoted} из {count} "
                           f"инструментов — Market Watch терминала пуст или наполовину"))
    if not out and verbose:
        print(f"  ok   {cfg['path']}: {_age(age)} назад, котируется {quoted}/{count}")
    return out


def check_registry(cfg: dict, verbose: bool) -> list[Finding]:
    """🔴 Сверка «что сайт обещает» с «что есть».

    Проверки выше идут ОТ ДАННЫХ: они видят символ, только если он уже лежит
    в price_bars или для него уже опубликован ohlc-файл. Символ, который
    добавили в реестр сайта и забыли завести источник, для них не существует
    вовсе — и молчание выглядит как здоровье.

    Здесь наоборот: идём ОТ РЕЕСТРА web/data/symbols.json. Всё, у чего стоит
    `chart: true`, сайт предлагает нарисовать — значит, часовые бары обязаны
    быть. Так поймались USDBRL/USDCZK/USDKRW: страница их предлагает, publish
    переписывает их файлы каждые пять минут, а часовых баров у них ноль.

    known_gaps — то же, что строки `off` в units.txt: дыра, о которой знают,
    с причиной. Молча исключать нельзя, поэтому при --verbose они печатаются
    всегда."""
    reg_path = BASE / cfg["registry"]
    db = Path(cfg["db"])
    if not reg_path.exists():
        return [Finding("reg-missing", f"{cfg['registry']}: реестра символов нет")]
    try:
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
    except Exception as e:
        return [Finding("reg-broken", f"{cfg['registry']}: не читается ({e})")]

    gaps = cfg.get("known_gaps", {})
    tf = cfg["timeframe"]
    con = sqlite3.connect(str(db), timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    try:
        have = {s for (s,) in con.execute(
            "SELECT DISTINCT symbol FROM price_bars WHERE tf=?", (tf,))}
    finally:
        con.close()

    missing = []
    for key, meta in sorted(reg.items()):
        if not isinstance(meta, dict) or not meta.get("chart"):
            continue
        pb = meta.get("price_bars") or key
        if pb in have:
            continue
        if pb in gaps or key in gaps:
            if verbose:
                print(f"  ok   реестр {key}: известная дыра — {gaps.get(pb) or gaps.get(key)}")
            continue
        missing.append((key, pb))

    if not missing:
        if verbose:
            print(f"  ok   реестр: у всех символов с chart:true есть бары {tf}")
        return []
    names = ", ".join(f"{k} ({pb})" for k, pb in missing)
    return [Finding("reg-nobars-" + ",".join(sorted(k for k, _ in missing)),
                    f"реестр сайта обещает график, а баров {tf} нет вовсе: {names}. "
                    f"Страница рисует их из старого ohlc-файла")]


def check_ohlc_json(cfg: dict, market_open: bool, verbose: bool) -> list[Finding]:
    """Свежесть витрины графика. При закрытом рынке молчим по той же логике,
    что и в check_price_bars — источник у этих файлов тот же."""
    ignore = set(cfg.get("ignore_symbols", []))
    max_age = cfg["max_age_sec"]
    now = time.time()
    stale = []
    checked = 0
    for f in sorted(globmod.glob(str(BASE / cfg["glob"]))):
        sym = Path(f).stem.split("_")[1]
        if sym in ignore:
            continue
        try:
            candles = json.loads(Path(f).read_text(encoding="utf-8")).get("candles") or []
            if not candles:
                stale.append((sym, None))
                continue
            checked += 1
            age = now - float(candles[-1]["time"])
            if age > max_age:
                stale.append((sym, age))
        except Exception as e:
            stale.append((sym, None))
            log.warning("ohlc %s: %s", f, e)

    if not stale:
        if verbose:
            print(f"  ok   ohlc_*_H1.json: все {checked} файлов свежие")
        return []
    if not market_open and all(a is not None for _, a in stale):
        if verbose:
            print(f"  ok   ohlc_*_H1.json: {len(stale)} стоят, рынок закрыт")
        return []
    names = ", ".join(f"{s} ({_age(a) if a else 'нет свечей'})" for s, a in stale[:6])
    more = f" и ещё {len(stale) - 6}" if len(stale) > 6 else ""
    return [Finding("ohlc-stale-" + ",".join(sorted(s for s, _ in stale)),
                    f"ohlc_*_H1.json: встали {len(stale)} — {names}{more}")]


def check_heartbeats(cfg: dict, verbose: bool) -> list[Finding]:
    """Компоненты, которые сами отмечаются в таблице heartbeats.

    Смотрим на last_ok, а не на last_run: прогон, который каждый раз падает,
    исправно обновляет last_run и снаружи выглядит живым."""
    db = BASE / cfg["db"]
    if not db.exists():
        return [Finding("hb-db", f"heartbeats: базы {db} нет")]
    ignore = set(cfg.get("ignore_components", []))
    now = time.time()
    out = []
    con = sqlite3.connect(str(db), timeout=30)
    try:
        rows = con.execute(
            "SELECT component, last_run, last_ok, last_error, error_count FROM heartbeats"
        ).fetchall()
    except sqlite3.Error as e:
        con.close()
        return [Finding("hb-read", f"heartbeats: не читается ({e})")]
    con.close()

    for comp, last_run, last_ok, last_error, err_count in rows:
        if comp in ignore:
            continue
        try:
            ok_ts = datetime.fromisoformat(last_ok).timestamp() if last_ok else None
        except Exception:
            ok_ts = None
        if ok_ts is None:
            out.append(Finding(f"hb-never-{comp}",
                               f"heartbeat {comp}: успешных прогонов не было вовсе"
                               + (f" — {str(last_error)[:120]}" if last_error else "")))
        elif now - ok_ts > cfg["max_age_sec"]:
            out.append(Finding(f"hb-stale-{comp}",
                               f"heartbeat {comp}: последний успех {_age(now - ok_ts)} назад"
                               + (f", ошибок подряд {err_count}" if err_count else "")
                               + (f" — {str(last_error)[:120]}" if last_error else "")))
        elif verbose:
            print(f"  ok   heartbeat {comp}: успех {_age(now - ok_ts)} назад")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Мост MT5
# ─────────────────────────────────────────────────────────────────────────────

_PROBE = r"""
import sys
from rpyc.utils.classic import connect
try:
    c = connect("%s", %d)
    c.execute("import MetaTrader5 as m")
    ok = c.eval("bool(m.initialize())")
    ti = c.eval("(m.terminal_info() is not None) and bool(m.terminal_info().connected)")
    c.close()
    print("OK" if (ok and ti) else "DEAD")
except Exception as e:
    print("ERR %%s: %%s" %% (type(e).__name__, e))
"""


def check_bridge(cfg: dict, verbose: bool) -> list[Finding]:
    """🔴 Проверка, которой не хватило 26.08.

    sbf-mt5-bridge.service семь часов был active (running) — процесс
    python.exe жил, порт слушался, TCP-соединения принимались. Но каждый
    вызов внутрь MetaTrader5 истекал по таймауту: терминал в бутылке завис
    ещё на старте. Проверка юнита это НЕ видит по определению — она смотрит
    на процесс, а сломано было то, что за ним.

    Пробуем в отдельном процессе с жёстким пределом: rpyc.classic.connect не
    даёт задать таймаут рукопожатия, и зависший мост подвесил бы сам надзор.
    Один короткий заход раз в 15 минут мост не нагружает."""
    host, port = cfg["host"], int(cfg["port"])
    code = _PROBE % (host, port)
    py = BASE / ".venv" / "bin" / "python3"
    try:
        r = subprocess.run([str(py), "-c", code], capture_output=True, text=True,
                           timeout=cfg["timeout_sec"], cwd=str(BASE))
        answer = (r.stdout or "").strip().splitlines()[-1] if r.stdout.strip() else ""
    except subprocess.TimeoutExpired:
        return [Finding("bridge-hang",
                        f"мост MT5: юнит active, но не ответил за {cfg['timeout_sec']} с — "
                        f"терминал в бутылке завис. Лечится "
                        f"`systemctl --user restart sbf-mt5-bridge.service`")]
    except Exception as e:
        return [Finding("bridge-probe", f"мост MT5: проверку не удалось выполнить ({e})")]

    if answer == "OK":
        if verbose:
            print("  ok   мост MT5: отвечает, терминал подключён")
        return []
    if answer == "DEAD":
        return [Finding("bridge-dead",
                        "мост MT5: отвечает, но MetaTrader5.initialize() или "
                        "terminal_info().connected — ложь. Терминал не залогинен")]
    return [Finding("bridge-err", f"мост MT5: {answer or 'пустой ответ пробы'}")]


# ─────────────────────────────────────────────────────────────────────────────
# Антиспам и доставка
# ─────────────────────────────────────────────────────────────────────────────

def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def decide_messages(findings: list[Finding], state: dict, repeat_after: int,
                    now: float) -> tuple[list[str], list[str], dict]:
    """Возвращает (новые_и_повторы, восстановления, новое_состояние).

    🔴 Правило антиспама, без которого канал перестают читать:
      • о новой проблеме — один раз, сразу;
      • о продолжающейся — не чаще раза в repeat_after, с указанием, сколько
        она уже длится (иначе повтор неотличим от новой);
      • об исчезнувшей — ровно одно сообщение «восстановилось».
    """
    seen = {f.key: f for f in findings}
    alerts: list[str] = []
    recovered: list[str] = []
    new_state: dict = {}

    for key, f in seen.items():
        prev = state.get(key)
        if prev is None:
            alerts.append("🔴 " + f.text)
            new_state[key] = {"first": now, "last_sent": now, "text": f.text}
        else:
            first = prev.get("first", now)
            if now - prev.get("last_sent", 0) >= repeat_after:
                alerts.append(f"🔴 (длится {_age(now - first)}) " + f.text)
                new_state[key] = {"first": first, "last_sent": now, "text": f.text}
            else:
                new_state[key] = {"first": first,
                                  "last_sent": prev.get("last_sent", now),
                                  "text": f.text}

    for key, prev in state.items():
        if key not in seen:
            first = prev.get("first")
            dur = f" (длилось {_age(now - first)})" if first else ""
            recovered.append(f"🟢 восстановилось{dur}: {prev.get('text', key)}")

    return alerts, recovered, new_state


def send(lines: list[str]) -> bool:
    """В операционный канал — туда же, куда дневной дайджест."""
    from core.telegram import send_report
    text = "*Надзор SBF*\n\n" + "\n\n".join(lines)
    try:
        asyncio.run(send_report(text))
        return True
    except Exception as e:
        log.error("не смог отправить алерт в Telegram: %s", e)
        return False


# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Надзор за остановками (SPEC_supervision_2026-08-26 §5)")
    ap.add_argument("--dry-run", action="store_true", help="только напечатать, ничего не слать")
    ap.add_argument("--verbose", action="store_true", help="печатать и то, что в порядке")
    ap.add_argument("--config", default=str(CONFIG_PATH))
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")

    try:
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
        units = parse_units(BASE / cfg["units_file"])
    except Exception as e:
        # 🔴 Сам надзор обязан падать громко. Тихо вернуть 0 здесь означало бы
        # «всё хорошо» ровно в тот момент, когда проверять перестали вовсе.
        print(f"НАДЗОР СЛОМАН: не читается конфиг или список юнитов: {e}", file=sys.stderr)
        return 2

    findings: list[Finding] = []
    try:
        findings += check_units(units, args.verbose)
        bars, market_open = check_price_bars(cfg["price_bars"], args.verbose)
        findings += bars
        findings += check_quotes_json(cfg["quotes_json"], args.verbose)
        findings += check_broker_quotes(cfg["broker_quotes"], args.verbose)
        findings += check_registry(cfg["registry_coverage"], args.verbose)
        findings += check_ohlc_json(cfg["ohlc_json"], market_open, args.verbose)
        findings += check_bridge(cfg["bridge"], args.verbose)
        findings += check_heartbeats(cfg["heartbeats"], args.verbose)
    except Exception as e:
        print(f"НАДЗОР СЛОМАН: проверка упала: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    if args.verbose or args.dry_run:
        print(f"\nРынок по свидетелям: {'открыт' if market_open else 'закрыт'}")
        print(f"Расхождений: {len(findings)}")
        for f in findings:
            print("  🔴", f.text)

    acfg = cfg["alerts"]
    state_path = BASE / acfg["state_path"]
    state = load_state(state_path)
    now = time.time()
    alerts, recovered, new_state = decide_messages(findings, state, acfg["repeat_after_sec"], now)

    if args.dry_run:
        print("\n--- было бы отправлено ---")
        for line in alerts + recovered:
            print(line)
        if not (alerts or recovered):
            print("(ничего)")
        return 1 if findings else 0

    if alerts or recovered:
        if not send(alerts + recovered):
            # Не смогли доставить — не помечаем как отправленное, чтобы
            # следующий тик попробовал снова, а не «проглотил» проблему.
            return 2
    save_state(state_path, new_state)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
