"""publish.py — мост backend→фронт. Превращает БД + рынок + технику в статический
JSON, который читает дашборд на lp.sbfconsult.com.

Полностью детерминированно, без LLM. Гоняется по расписанию (каждые 5-10 мин).
Сайт ничего не вычисляет — только отдаёт эти артефакты.

Пишет в web/data/:
  market.json     — состояние рынка + Crypto F&G
  technical.json  — TC-подобные карточки по watchlist
  signals.json    — топ-сигналы по измерениям
  buzz.json       — тепловая карта тикеров (для пузырей)
  report.json     — мета последнего утреннего отчёта + markdown
  meta.json       — когда что обновлялось (для индикаторов свежести на сайте)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from core import db
from core import symbols as _symbols
from core.config import BASE_DIR, REPORTS_DIR

log = logging.getLogger("publish")

WEB_DATA = BASE_DIR / "web" / "data"
WEB_DATA.mkdir(parents=True, exist_ok=True)

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

# Фиксированный список тикеров для технических карточек (строго этот порядок)
TECH_BASE = [
    "GC=F", "SI=F",
    "BTC-USD", "ETH-USD", "SOL-USD",
    "EURUSD=X", "GBPUSD=X",
    "^GSPC", "^NDX", "^DJI",
    "CL=F", "NG=F",
]

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(name: str, payload: dict) -> None:
    (WEB_DATA / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("wrote %s", name)


def publish_market() -> None:
    from core.market import snapshot, crypto_fear_greed, DASHBOARD
    # "name" — фолбэк на случай, если фронт грузится без SBFSymbols (тот
    # переозвучивает по window.SBFSymbols.symbolName на нужном языке сам,
    # см. SPEC_symbol_names.md §3); здесь всегда русское имя реестра.
    snap = snapshot(DASHBOARD)
    items = [{"name": _symbols.symbol_name(t, mode="name"), "ticker": t, **snap.get(t, {})}
             for t in DASHBOARD if snap.get(t, {}).get("price") is not None]
    _write("market.json", {"updated": _now(), "items": items,
                           "fear_greed": crypto_fear_greed()})


def publish_technical() -> None:
    from core.technical import analyze
    cards = []
    for t in TECH_BASE:
        a = analyze(t)
        if a:
            a["name"] = _symbols.symbol_name(t, mode="name")  # читабельное имя из реестра
            cards.append(a)
    _write("technical.json", {"updated": _now(), "cards": cards})


def publish_signals() -> None:
    # P0-2 §2.2 шаги 2-4: маркер достоверности + фильтр (без тикера — не
    # показывать, капс/BREAKING — понизить, политическое — отсечь) + связка
    # с брифом. Правила берут кандидатов с запасом (лимит ×4 к отображаемому),
    # т.к. часть будет отфильтрована — иначе после фильтра карточек может
    # остаться меньше 12 даже когда сырых сигналов достаточно.
    from core.feed_filter import apply_feed_rules
    DISPLAY_LIMIT = 12
    # SPEC_site_fixes_2026-07-29 §6 п.1: квота, не ранжирование -- пока
    # importance для RSS ниже вовлечённости твитов, ранжирование одно эту
    # задачу не решает. Не применяется к "Соцсети" (crowd) -- та вкладка
    # сознательно осталась чисто социальной (см. §7).
    PRESS_QUOTA = 4
    out = {}
    for dim in ("economy", "geopolitics"):
        candidates = [_sig(s) for s in db.top_by_dimension(24, dim, DISPLAY_LIMIT * 4)]
        # geopolitics по данным структурно без тикеров (см. feed_filter.py) --
        # там штамп "нет тикера" убил бы вкладку целиком, требование ослаблено
        # сознательно, политический фильтр остаётся в силе.
        out[dim] = apply_feed_rules(candidates, DISPLAY_LIMIT, require_cashtag=(dim != "geopolitics"),
                                     press_quota=PRESS_QUOTA)
    crowd_candidates = [_sig(s) for s in db.top_by_crowd(24, DISPLAY_LIMIT * 4)]
    out["crowd"] = apply_feed_rules(crowd_candidates, DISPLAY_LIMIT)
    _write("signals.json", {"updated": _now(), **out})


def _sig(s: dict) -> dict:
    # SPEC_site_fixes_2026-07-29 §6 п.4: для Google-News-статей s["url"] -- это
    # редирект через news.google.com, не первоисточник, поэтому домен из URL
    # был бы неверным ("news.google.com"). rss.py уже резолвит настоящий домен
    # издания (entry.source.href) и кладёт в raw -- используем его, если есть.
    try:
        raw = json.loads(s.get("raw") or "{}")
    except (json.JSONDecodeError, TypeError):
        raw = {}
    return {
        "source": s["source"], "author": s["author"],
        "outlet": s.get("topic_hint") or "",
        "domain": raw.get("domain") or "",
        "text": (s["title"] or s["text"])[:280], "url": s["url"],
        "importance": s["importance"], "econ": s["econ_relevance"],
        "crowd": s["crowd_intensity"], "engagement": s["engagement"],
        "cashtags": json.loads(s["cashtags"] or "[]"),
    }


def publish_buzz() -> None:
    heat = db.cashtag_heatmap(24, limit=40)
    _write("buzz.json", {"updated": _now(),
                         "tickers": [{"tag": t, "mentions": c, "importance": imp}
                                     for t, c, imp in heat]})


def publish_report() -> None:
    reports = sorted(REPORTS_DIR.glob("report_*.md"))
    if not reports:
        _write("report.json", {"updated": None, "markdown": "", "date": None})
        return
    latest = reports[-1]
    _write("report.json", {
        "updated": _now(),
        "date": latest.stem.replace("report_", ""),
        "markdown": latest.read_text(encoding="utf-8"),
    })


def publish_stories() -> None:
    from core.stories import active_stories, attach_market, rebuild_stories
    rebuild_stories(hours=48)
    stories = [attach_market(s) for s in active_stories(limit=12)]
    _write("stories.json", {"updated": _now(), "stories": stories})


def publish_regime() -> None:
    from core.regime import detect_regime
    _write("regime.json", detect_regime())


def publish_verification() -> None:
    from core.verification import scorecard, recent_observations, resolve_due
    resolve_due()
    _write("verification.json", {
        "updated": _now(),
        "scorecard": scorecard(),
        "recent": recent_observations(limit=15),
    })


def publish_macro() -> None:
    from core.fred import macro_snapshot
    _write("macro.json", macro_snapshot())


def publish_divergence() -> None:
    from core.divergence import sentiment_price_divergence, changes_since
    _write("divergence.json", {
        "updated": _now(),
        "divergences": sentiment_price_divergence(),
        "changes": changes_since(),
    })


def publish_anomalies() -> None:
    from core.anomaly import anomalies, update_baselines
    update_baselines()
    _write("anomalies.json", {"updated": _now(), "anomalies": anomalies()})


def publish_charts() -> None:
    """OHLC + уровни для интерактивных Lightweight Charts, из price_bars.

    WP1.2 SPEC_alpha_engine_implementation.md: раньше был Yahoo (yfinance) для
    большинства символов + отдельная publish_charts_mt5() из price_bars только
    для USDRUB/USDKZT/USDJPY -- ДВА несвязанных пространства цен (§1.2 спеки).
    Теперь единственный источник для всех символов -- price_bars. Нативная
    гранулярность 15m/1h/4h есть только у 5-6 инструментов покрытия Daoti
    (проверено при миграции, см. Core-лог 08.08); там, где её нет -- H1/H4
    ресэмплятся из 30m, W1 -- из D1. Та же техника, что раньше уже применялась
    здесь для H4-из-H1 на Yahoo-данных, просто теперь применяется шире и из
    честного единственного источника, а не из двух вперемешку.
    M15 намеренно НЕ синтезируется ресэмплом -- из более грубого ТФ более
    мелкий получить нельзя, там где нативных 15m-баров нет, файл просто не
    пишется (тот же принцип "без выдумки", что уже был в publish_charts_mt5).
    """
    import sqlite3
    import pandas as pd
    from mt5_config import RECENT_BARS
    from core.technical import pivots as calc_pivots, _rsi, patterns as _tech_patterns
    from core.price_bars import available_symbols
    from core.symbols_registry import alias_for

    # Сколько свечей уходит в файл. Ключи — веб-таймфреймы, значения берём из
    # той же карты, по которой качаются бары из моста: один предел на оба конца
    # конвейера, а не два разных числа в разных файлах.
    _WEB_TF_LIMIT = {"M15": RECENT_BARS.get("15m", 3000),
                     "M30": RECENT_BARS.get("30m", 3000),
                     "H1":  RECENT_BARS.get("1h", 3000),
                     "H4":  RECENT_BARS.get("4h", 2000),
                     "D1":  RECENT_BARS.get("1d", 2000),
                     "W1":  RECENT_BARS.get("1w", 1000)}

    def _frame(con, pb_sym, tf):
        rows = con.execute(
            "SELECT ts,o,h,l,c,v FROM price_bars WHERE symbol=? AND tf=? ORDER BY ts ASC",
            (pb_sym, tf)).fetchall()
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=["ts", "Open", "High", "Low", "Close", "Volume"])
        return df.astype({"Open": float, "High": float, "Low": float, "Close": float, "Volume": float})

    def _resample(df, rule):
        idx = pd.to_datetime(df["ts"], unit="s", utc=True)
        agg = df.set_index(idx).resample(rule).agg(
            {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
        ).dropna(subset=["Open"])
        out = agg.reset_index(names="ts")
        # 🔴 pandas 3.0: datetime64 по умолчанию в секундах, не в наносекундах —
        # старое ".astype('int64') // 10**9" делило уже-секунды ещё раз на
        # 10**9 и давало ts=1 для каждой строки. Эпоха вычитанием — не зависит
        # от того, в чём именно pandas хранит разрешение сейчас или потом.
        out["ts"] = ((out["ts"] - pd.Timestamp("1970-01-01", tz="UTC"))
                     // pd.Timedelta(seconds=1)).astype("int64")
        return out

    def _rows_from(df, intraday):
        candles, vol = [], []
        for _, r in df.iterrows():
            ts, o, h, l, c = int(r["ts"]), float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"])
            t = ts if intraday else pd.Timestamp(ts, unit="s", tz="utc").strftime("%Y-%m-%d")
            up = c >= o
            candles.append({"time": t, "open": round(o, 4), "high": round(h, 4),
                             "low": round(l, 4), "close": round(c, 4)})
            vol.append({"time": t, "value": int(r["Volume"] or 0),
                        "color": "rgba(30,142,90,.5)" if up else "rgba(192,57,43,.5)"})
        return candles, vol

    con = sqlite3.connect(str(_BOT_DB))
    try:
        for canonical in available_symbols("1d"):
            pb_sym = alias_for(canonical, "price_bars") or canonical
            d1 = _frame(con, pb_sym, "1d")
            if d1 is None:
                continue
            price = float(d1["Close"].iloc[-1])
            pv = calc_pivots(
                float(d1["High"].iloc[-2]), float(d1["Low"].iloc[-2]), float(d1["Close"].iloc[-2])
            ) if len(d1) >= 2 else calc_pivots(
                float(d1["High"].max()), float(d1["Low"].min()), price)
            rsi_val = round(_rsi(d1["Close"]), 1)
            ma20 = float(d1["Close"].rolling(20).mean().iloc[-1])
            ma50 = float(d1["Close"].rolling(50).mean().iloc[-1]) if len(d1) >= 50 else ma20
            mom = price - float(d1["Close"].iloc[-11]) if len(d1) > 11 else 0.0
            bull = sum([price > pv["PP"], ma20 > ma50, mom > 0, rsi_val > 50])
            bias = ("техническая картина бычья" if bull >= 3
                    else "техническая картина медвежья" if bull <= 1
                    else "смешанная / нейтральная")
            pats = _tech_patterns(d1) if len(d1) >= 2 else []

            levels = [
                ("R2", pv["R2"], "#c0392b"), ("R1", pv["R1"], "#c0392b"),
                ("PP", pv["PP"], "#C9A227"),
                ("S1", pv["S1"], "#1e8e5a"), ("S2", pv["S2"], "#1e8e5a"),
            ]
            nearest = min(levels, key=lambda L: abs(L[1] - price))
            meta = {
                "ticker": pb_sym, "label": canonical,
                "last": round(price, 4), "rsi": rsi_val, "bias": bias, "patterns": pats,
                "levels": [{"name": n, "price": round(v, 4), "color": c} for n, v, c in levels],
                "nearest": {"name": nearest[0], "price": round(nearest[1], 4),
                            "dist_pct": round((price - nearest[1]) / price * 100, 2)},
            }

            m30 = _frame(con, pb_sym, "30m")
            m15 = _frame(con, pb_sym, "15m")
            h1_native = _frame(con, pb_sym, "1h")
            h1 = h1_native if h1_native is not None else (_resample(m30, "1h") if m30 is not None else None)
            h4_native = _frame(con, pb_sym, "4h")
            h4 = h4_native if h4_native is not None else (_resample(h1, "4h") if h1 is not None else None)
            w1_native = _frame(con, pb_sym, "1w")
            w1 = w1_native if w1_native is not None else _resample(d1, "1W")

            for web_tf, df, intraday in (
                ("M15", m15, True), ("M30", m30, True), ("H1", h1, True),
                ("H4", h4, True), ("D1", d1, False), ("W1", w1, False),
            ):
                fname = f"ohlc_{canonical}_{web_tf}.json"
                if df is None or df.empty:
                    # 🔴 Найдено при миграции: раньше M15 шёл из Yahoo для всех
                    # 31 символа, у price_bars нативные 15m есть только у 5.
                    # Без явного удаления старый Yahoo-файл остался бы на диске
                    # НАВСЕГДА нетронутым (_write просто не перезаписал бы его)
                    # -- график показывал бы протухающий M15 молча. "Честно
                    # без выдумки" должно значить "нет файла", а не "старый файл".
                    (WEB_DATA / fname).unlink(missing_ok=True)
                    continue
                # 🔴 В файл идёт хвост, а не вся история.
                #
                # Выгрузка была без предела: ohlc_GOLD_M30.json — 100 796 свечей
                # с 2018 года, 22.7 МБ, и браузер скачивал их целиком при каждом
                # переключении на M30. Вся выкладка занимала 251 МБ. На телефоне
                # это просто не открывалось за разумное время.
                #
                # Пределы те же, что уже действуют при выкачке из моста
                # (mt5_config.RECENT_BARS) — чтобы «глубина графика» не значила в
                # двух местах разное. Три тысячи получасовых свечей это больше
                # трёх месяцев: на экране всё равно помещается пара сотен.
                #
                # Обрезается ТОЛЬКО то, что пишется в файл. Пивоты, RSI, MA50 и
                # паттерны выше посчитаны по полному ряду и не меняются.
                keep = _WEB_TF_LIMIT.get(web_tf)
                out_df = df.tail(keep) if keep else df
                candles, vol = _rows_from(out_df, intraday)
                _write(fname, {**meta, "interval": web_tf, "candles": candles, "volume": vol})
    finally:
        con.close()


# SPEC_fix_live_chart.md §5: состояние отката переживает между вызовами
# publish_quotes() — сама функция дёргается раз в 15с из одного долгоживущего
# процесса (quotes_loop.py), поэтому модульные переменные, а не локальные,
# иначе после каждого вызова откат обнулялся бы сам собой.
_quotes_backoff_until = 0.0
_quotes_consecutive_429 = 0


def publish_quotes() -> None:
    """Быстрые котировки для live-обновления графика и строки (каждые 15 с).
    Пишет web/data/quotes.json:
    {"quotes": {"GC=F": {"price": ..., "change_pct": ..., "delay_sec": ...}, ...}}
    Использует прямые HTTP запросы к Yahoo Finance v8 — обходит кеш yfinance."""
    import requests
    from concurrent.futures import ThreadPoolExecutor
    from core.market import DASHBOARD

    global _quotes_backoff_until, _quotes_consecutive_429

    now_ts = datetime.now(timezone.utc).timestamp()
    if now_ts < _quotes_backoff_until:
        log.debug("publish_quotes: в откате ещё %.0fс (429 подряд: %d) — цикл пропущен",
                   _quotes_backoff_until - now_ts, _quotes_consecutive_429)
        return  # quotes.json не трогаем — "updated" честно стареет, §4 подхватит на фронте

    syms = list(dict.fromkeys(
        DASHBOARD + ["GC=F", "SI=F", "ETH-USD", "SOL-USD",
                     "EURUSD=X", "GBPUSD=X", "CL=F", "NG=F"]
    ))
    _HDR = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://finance.yahoo.com",
    }

    def _fetch(sym):
        # SPEC_fix_live_chart.md §5: НЕ менять на /v7/finance/quote ради
        # "оптимизации" одного meta.regularMarketPrice вместо range=2d&interval=1d —
        # v7 требует cookie+crumb (отдельный запрос за crumb, сессионные куки,
        # хрупче к смене API Yahoo). Здесь стоит рабочий обход без авторизации,
        # цена той же точности. Дороже по байтам, но не по надёжности.
        try:
            r = requests.get(
                f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}",
                params={"range": "2d", "interval": "1d"},
                headers=_HDR,
                timeout=6,
            )
            if r.status_code == 429:
                return sym, "429"
            if not r.ok:
                log.debug("publish_quotes: %s HTTP %d", sym, r.status_code)
                return sym, None
            meta = r.json()["chart"]["result"][0]["meta"]
            price = float(meta["regularMarketPrice"])
            prev = meta.get("chartPreviousClose")
            chg = round((price / prev - 1) * 100, 2) if prev else None
            # SPEC_fix_live_chart.md §6.1: задержка измеренная, не декларируемая —
            # regularMarketTime это момент последней сделки на бирже по Yahoo,
            # разница с моментом нашего запроса и есть наблюдаемая задержка.
            trade_ts = meta.get("regularMarketTime")
            delay_sec = max(0, int(now_ts - trade_ts)) if trade_ts else None
            return sym, {"price": round(price, 4), "change_pct": chg, "delay_sec": delay_sec}
        except requests.exceptions.Timeout:
            log.debug("publish_quotes: %s таймаут", sym)
            return sym, None
        except Exception as e:
            log.debug("publish_quotes: %s ошибка: %s", sym, e)
            return sym, None

    out = {}
    n_429 = 0
    n_fail = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for sym, val in ex.map(_fetch, syms):
            if val == "429":
                n_429 += 1
            elif val is None:
                n_fail += 1
            else:
                out[sym] = val

    # SPEC_fix_live_chart.md §5: 429 почти всегда бьёт по всем параллельным
    # запросам разом (один IP, один клиент) — не подсимвольная блокировка,
    # поэтому откладываем цикл целиком, а не пытаемся слить частичный успех.
    if n_429:
        _quotes_consecutive_429 += 1
        backoff_sec = min(300, 15 * (2 ** _quotes_consecutive_429))
        _quotes_backoff_until = now_ts + backoff_sec
        log.warning("publish_quotes: 429 от Yahoo на %d/%d тикеров, откат на %ds (подряд: %d)",
                    n_429, len(syms), backoff_sec, _quotes_consecutive_429)
        return  # quotes.json не пишем в этом цикле вообще
    if _quotes_consecutive_429:
        log.info("publish_quotes: 429 прекратились после %d циклов отката", _quotes_consecutive_429)
    _quotes_consecutive_429 = 0
    if n_fail:
        log.debug("publish_quotes: %d/%d тикеров не ответили (не 429 — таймаут/ошибка)", n_fail, len(syms))

    # Инструменты брокера — ценой брокера, поверх Yahoo. См. core/mt5_quotes.py.
    try:
        from core import mt5_quotes
        broker = mt5_quotes.quotes(now_ts, set(syms))
    except Exception as e:
        broker = {}
        log.warning("publish_quotes: мост MT5 недоступен (%s) — цены остались "
                    "от Yahoo, по золоту это фьючерс против спота на графике", e)
    if broker:
        out.update(broker)
    else:
        log.warning("publish_quotes: мост MT5 не дал ни одной цены — "
                    "quotes.json целиком от Yahoo")

    _write("quotes.json", {"updated": _now(), "quotes": out})


def publish_health() -> None:
    from core import db as _db
    beats = _db.get_heartbeats()
    _write("health.json", {"updated": _now(), "components": beats})


def publish_all() -> None:
    db.init_db()

    # Быстрые (рынок, сигналы)
    fast_fns = (publish_market, publish_technical, publish_signals,
                publish_buzz, publish_report)
    # Медленнее / зависят от истории
    # publish_calendar() удалена (СПЕКА_календарь_и_движения_рынка.md §2.4):
    # читала мёртвую таблицу `calendar` в signals.db (её писал только
    # collect_calendar(), которого никто не вызывал) и писала пустышку
    # web/data/calendar.json, которую не читал ни один фронтенд-код —
    # реальный календарь в econ_events, отдаётся через /api/calendar/events
    # и build_brief_v2.py. Файл calendar.json удалён вместе с функцией.
    slow_fns = (publish_stories, publish_regime, publish_verification,
                publish_macro, publish_divergence,
                publish_anomalies, publish_health, publish_charts)

    layers = []
    for fn in fast_fns + slow_fns:
        try:
            fn()
            layers.append(fn.__name__.replace("publish_", ""))
        except Exception as e:
            log.error("%s failed: %s", fn.__name__, e)

    db.heartbeat("publish", ok=True)
    _write("meta.json", {"updated": _now(), "layers": layers})


if __name__ == "__main__":
    from core.logging_setup import setup
    setup("publish")
    publish_all()
    print("published →", WEB_DATA)
