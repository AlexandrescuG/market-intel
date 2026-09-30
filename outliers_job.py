#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""outliers_job.py — скан аномальных движений и алерты (SPEC_brief_outliers §2.4).

Запуск по таймеру раз в 15 минут: sbf-outliers.timer.

    python3 outliers_job.py                  # штатный прогон
    python3 outliers_job.py --report 15      # что близко к порогу, без записи
    python3 outliers_job.py --config x.json  # прогон с другими порогами

🔴 --report существует не для удобства. Пороги на старте заведомо не
откалиброваны (20% по акциям, 30% по крипте — взяты из головы), а неделя
тихого режима нужна ровно затем, чтобы владелец увидел РЕАЛЬНОЕ распределение
и подвинул их. Без режима «покажи, что было близко» тихая неделя показывала бы
пустоту и выглядела как «всё работает»: замер 25.08 — лучший рост дня по всему
рынку США +14,9% при пороге 20, ни одной записи. Пустой результат и
неработающий скринер обязаны выглядеть по-разному.

АДРЕСАТ АЛЕРТА. В тихом режиме — только операционный канал (общий outbox ->
@gdenigi_bot), подписчикам ничего. После `quiet_mode_until` — по
`alert_target` из конфига; решение владельца 25.08 — подписчикам. Саму
отправку подписчикам делает бот (у него аудитория и часовые пояса), здесь
строка просто остаётся неотправленной и он её забирает — см.
SBFAcademy_bot/sbfacademy/bot/outlier_push.py.

Смысл двух полей, чтобы не путать:
  alerted_ts       — когда доставлено ХОТЬ КУДА;
  alert_suppressed — почему НЕ ушло аудитории (тихий режим / лимит / дубль).
В тихом режиме заполнены оба: отправлено в операционный, придержано от
подписчиков.
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent))

from core import outliers as O
from core.db_migrations import apply_all

BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
WEB_DATA = Path(__file__).parent / "web" / "data"

log = logging.getLogger("outliers_job")

# 15.09.2026: константа удалена из постов о выбросах по решению владельца
# (см. alert_text). В картинке брифинга подпись осталась — там она часть
# нижней плашки с источником данных, а не отдельная строка в ленте, и её
# решение не касалось (brief_image_job.DISCLAIMER).


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(BOT_DB), timeout=120)
    # bot.db пишут соседние джобы — без ожидания замок чужого писателя убил бы
    # прогон (ровно так падала доливка price_bars 20.08).
    con.execute("PRAGMA busy_timeout=120000")
    apply_all(con)
    return con


def _fmt_pct(v) -> str:
    if v is None:
        return "—"
    s = f"{v:+.1f}%".replace(".", ",")
    return s.replace("-", "−", 1) if s.startswith("-") else s


def _plural(n: int, one: str, few: str, many: str) -> str:
    """«Ещё 3 инструментов» — так не говорят. Правило русского счётного
    сочетания, а не f-string с хвостом «ов»."""
    n = abs(int(n))
    if 11 <= n % 100 <= 14:
        return many
    last = n % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def _fmt_money(v) -> str:
    if not v:
        return "—"
    for unit, div in (("млрд", 1e9), ("млн", 1e6), ("тыс", 1e3)):
        if v >= div:
            return f"{v / div:.1f}".replace(".", ",") + f" {unit}"
    return str(int(v))


_QUOTES_JSON = WEB_DATA / "quotes.json"
_QUOTES_MAX_AGE = 6 * 3600      # старше — молчим, а не показываем вчерашний рынок

# Индексы фона. Для акций — американский рынок (оба скринера yfinance по нему),
# для крипты — BTC/ETH: сравнивать альткоин с S&P 500 бессмысленно.
_BACKDROP = {
    "equity": [("^GSPC", "S&P 500"), ("^NDX", "Nasdaq 100")],
    "crypto": [("BTC-USD", "Биткоин"), ("ETH-USD", "Эфириум")],
}


def _market_backdrop(asset_class: str, now_ts: int) -> str | None:
    """«Рынок вокруг» — одна строка. None, если котировок нет или они старые:
    рост бумаги на фоне вчерашнего рынка — это не фон, а выдумка."""
    try:
        raw = json.loads(_QUOTES_JSON.read_text(encoding="utf-8"))
        updated = datetime.fromisoformat(raw["updated"]).timestamp()
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
        log.warning("фон: %s не прочитан (%s)", _QUOTES_JSON, e)
        return None
    if now_ts - updated > _QUOTES_MAX_AGE:
        log.warning("фон: quotes.json старше %d ч — строку не пишем", _QUOTES_MAX_AGE // 3600)
        return None
    quotes = raw.get("quotes") or {}
    parts = []
    for sym, title in _BACKDROP.get(asset_class, _BACKDROP["equity"]):
        chg = (quotes.get(sym) or {}).get("change_pct")
        if isinstance(chg, (int, float)):
            parts.append(f"{title} {_fmt_pct(chg)}")
    return " · ".join(parts) if parts else None


def _peers_line(con, row: dict, now_ts: int) -> str | None:
    """Сколько ЕЩЁ инструментов сегодня за порогом в ту же сторону.

    Отвечает на вопрос «это движение всего рынка или этой одной бумаги» —
    единственный вид фона, который можно посчитать точно по своим данным.
    Считаем по market_outliers, то есть по прошедшим порог: строка так и
    сформулирована («за порогом»), чтобы не выдавать это за долю рынка.
    """
    day_start = now_ts - (now_ts % 86400)
    same_dir = "> 0" if row["chg_pct"] > 0 else "< 0"
    n = con.execute(
        f"SELECT count(*) FROM market_outliers WHERE last_seen_ts >= ? AND id <> ? "
        f"AND asset_class = ? AND chg_pct {same_dir}",
        (day_start, row["id"], row["asset_class"]),
    ).fetchone()[0]
    if not n:
        return None
    what = "монета" if row["asset_class"] == "crypto" else "бумага"
    plural = {"монета": ("монета", "монеты", "монет"),
              "бумага": ("бумага", "бумаги", "бумаг")}[what]
    where = "растёт" if row["chg_pct"] > 0 else "падает"
    return (f"Сегодня за порогом ещё {n} {_plural(n, *plural)} — "
            f"{where} не одна эта")


def _domain(url: str) -> str:
    """Домен без www и без зоны — как в постах канала («ch-toulon», «github»)."""
    try:
        host = urlparse(url).netloc.replace("www.", "")
        return host.split(".")[0] or host
    except Exception:
        return "источник"


def _source_link(row: dict) -> str:
    """Одна строка-ссылка внизу поста, как в остальных постах канала.

    🔴 02.09: ссылка ровно одна. Раньше их было две подряд — на новость и на
    карточку инструмента, причём подписью новости стояло имя издания из
    Yahoo («— Motley Fool»), которое в русском посте читается как непонятная
    приписка. Теперь: есть новость — ссылка ведёт на неё и подписана доменом;
    нет новости — ведёт на карточку инструмента, где числа можно проверить.
    """
    url = row.get("_news_url")
    if url:
        return f'— <a href="{url}">{_domain(url)}</a>'
    sym = row["symbol"]
    if row["asset_class"] == "crypto":
        base = sym[:-4] if sym.endswith("USDT") else sym
        return f'— <a href="https://www.bybit.com/trade/spot/{base}/USDT">bybit</a>'
    return f'— <a href="https://finance.yahoo.com/quote/{sym}">yahoo finance</a>'


def _hashtags(row: dict) -> str:
    """Шапка в стиле канала: маркер, флаг, тикер, тема."""
    up = row["chg_pct"] > 0
    if row["asset_class"] == "crypto":
        return f"{'✴️' if up else '⚠️'}#{row['symbol']} #крипто #движение"
    # Оба скринера (day_gainers/day_losers) — американский рынок.
    return f"{'✴️' if up else '⚠️'}🇺🇸#{row['symbol']} #акции #движение"


def alert_text(row: dict) -> str:
    """§2.5, формат канала @SBFEconomics (01.09.2026, решение владельца).

    Раньше это была карточка из машинных полей — тикер, процент, цена,
    оборот, время съёмки, имя скринера. Владелец: «если мы такое пишем, то
    нужно писать, на фоне чего это произошло». Голое число без фона читателю
    ничего не говорит: +24% у Fervo Energy — это ралли всего рынка, отраслевая
    история или одна бумага? Поэтому теперь под фактом идут: рынок вокруг,
    сколько ещё инструментов сегодня за порогом, и новость, если она нашлась.

    Причину НЕ придумываем и НЕ ждём: пост уходит фактом, а объяснение
    дописывается правкой, когда новость появится (refresh_published).
    """
    name = row.get("name") or row["symbol"]
    lines = [_hashtags(row)]

    move = f"{name} {_fmt_pct(row['chg_pct'])} за день"
    peak = row.get("peak_chg_pct")
    if peak is not None and abs(peak) > abs(row["chg_pct"]) + 0.5:
        move += f" (в моменте {_fmt_pct(peak)})"
    lines.append(move)
    # 🔴 02.09: было «оборот $693,7 млн» — неверное слово. Оборот компании это
    # её выручка, деньги внутри бизнеса; у нас же цена × regularMarketVolume,
    # то есть сколько денег прошло через СДЕЛКИ с бумагой за день. Пишем
    # «объём торгов». Рядом капитализация: без неё $694 млн читались как
    # размер компании, хотя капитализация FRVO — $5,8 млрд.
    facts = [f"Цена {row['price']}"]
    if row.get("market_cap"):
        facts.append(f"капитализация ${_fmt_money(row['market_cap'])}")
    facts.append(f"объём торгов за день ${_fmt_money(row.get('dollar_volume'))}")
    lines.append(", ".join(facts))

    if row.get("_backdrop"):
        lines.append(f"Рынок вокруг: {row['_backdrop']}")
    if row.get("_peers"):
        lines.append(row["_peers"])

    # 🔴 02.09: заголовка новости в посте НЕТ вообще. Он приходил из чужой
    # ленты в чужой интонации («Почему акции Fervo Energy взлетели до небес») и
    # выглядел кликбейтом посреди сухой сводки — владелец забраковал. Новость
    # никуда не делась: на неё ведёт ссылка внизу поста, и именно она заменяет
    # ссылку на карточку инструмента, когда объяснение находится.
    # 🔴 15.09: строки «Статистическое наблюдение, не рекомендация» в посте
    # больше нет — решение владельца. Она висела под каждым выбросом и в
    # ленте канала читалась как служебный штамп, а не как оговорка. Сам пост
    # и так не содержит ни оценок, ни призывов: только факт движения, цифры и
    # ссылка на источник.
    lines.append("")
    lines.append(_source_link(row))
    return "\n".join(lines)


def _quiet_mode(cfg: dict, today: date) -> bool:
    raw = cfg.get("quiet_mode_until")
    if not raw:
        return False
    try:
        return today < datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        log.warning("quiet_mode_until=%r не разбирается — считаем тихий режим выключенным", raw)
        return False


def _is_russian(t: str) -> bool:
    return sum(1 for c in t if "Ѐ" <= c <= "ӿ") / max(len(t), 1) > 0.25


# Дословный текст generic-страницы ошибки Google. deep_translator не бросает на
# неё исключение, а возвращает тело страницы как будто это перевод — ловушка
# уже описана в collectors/twitter.py, здесь тот же случай.
_GOOGLE_ERROR_SIGNATURE = "Error 500 (Server Error)"


def _ru(text: str) -> str:
    """Заголовок новости по-русски. Канал русскоязычный, а кластеры собраны из
    англоязычных лент — «Stocks making the biggest moves midday» в русском
    посте выглядит как чужая вставка. Перевод не получился — отдаём оригинал:
    английский заголовок хуже русского, но лучше отсутствующего."""
    if not text or _is_russian(text):
        return text
    text = text[:2000]

    # Два переводчика подряд, не один. 01.09 Google отдал страницу ошибки на
    # живом заголовке («Why Fervo Energy Stock Skyrocketed Today») — с одним
    # источником пост ушёл бы в русский канал с английской строкой. MyMemory
    # тот же заголовок перевёл сразу.
    try:
        from deep_translator import GoogleTranslator, MyMemoryTranslator
    except ImportError as e:
        log.warning("перевод недоступен: %s", e)
        return text

    def _google():
        return GoogleTranslator(source="auto", target="ru").translate(text)

    def _mymemory():
        return MyMemoryTranslator(source="en-US", target="ru-RU").translate(text)

    for attempt in (_google, _mymemory):
        try:
            out = attempt()
        except Exception as e:
            log.warning("перевод (%s) не удался: %s", attempt.__name__, e)
            continue
        # Результат обязан БЫТЬ русским: и страница ошибки Google, и «перевод»,
        # вернувший исходную английскую строку, одинаково означают неудачу.
        if out and _GOOGLE_ERROR_SIGNATURE not in out and _is_russian(out):
            return out
    return text


def _find_cluster_by_symbol(con, row: dict, now_ts: int):
    """Запасной поиск новости по самому инструменту.

    01.09: из четырёх выбросов дня кластер был привязан к двум. Привязка §3
    идёт по теме дня, а разовая корпоративная новость («компания X подписала
    контракт») в тему дня не попадает — при 71 живом кластере выброс всё равно
    уходил без объяснения. Здесь ищем по outlier_symbol (кластер уже помечен
    этим тикером) и по вхождению тикера/имени компании в заголовок.

    Имя компании берём ПЕРВЫМ словом (Fervo из «Fervo Energy Company»): полное
    имя в заголовках почти не встречается, а слова вроде Energy/Holding/Inc
    поймали бы пол-ленты. Слова короче четырёх букв не используем вовсе —
    ровно тот класс ложных срабатываний, что уже ловили на тикерах-омонимах.
    """
    since = now_ts - 36 * 3600
    got = con.execute(
        "SELECT label, sample_title, sample_url, publishers FROM news_clusters "
        "WHERE outlier_symbol = ? AND created_ts >= ? ORDER BY publishers DESC LIMIT 1",
        (row["symbol"], since),
    ).fetchone()
    if got:
        return got

    needles = [f"${row['symbol']}"]
    first_word = (row.get("name") or "").split()[:1]
    if first_word and len(first_word[0]) >= 4 and first_word[0].isalpha():
        needles.append(first_word[0])
    for needle in needles:
        got = con.execute(
            "SELECT label, sample_title, sample_url, publishers FROM news_clusters "
            "WHERE created_ts >= ? AND (sample_title LIKE ? OR label LIKE ?) "
            "ORDER BY publishers DESC LIMIT 1",
            (since, f"%{needle}%", f"%{needle}%"),
        ).fetchone()
        if got:
            return got
    return None


_YAHOO_NEWS_MAX_AGE = 72 * 3600


def _yahoo_news(symbol: str, now_ts: int):
    """Свежая новость по самому тикеру с Yahoo Finance.

    🔴 01.09: наши кластеры собраны из лент по ТЕМАМ ДНЯ, и корпоративная
    новость одной компании в них не попадает. По PSQL алерт написал «причина
    в новостях не найдена», хотя на карточке Yahoo лежали три заметки, прямо
    объясняющие движение («Pasqal Enters Nasdaq Price Discovery After
    Completing De-SPAC Merger»). Значит искать надо там же, где смотрит
    человек, а не только в своей базе.

    Возвращает (заголовок, ссылка, издатель) или None. Берём самую свежую и
    только если она не старше трёх суток: новость недельной давности рядом с
    сегодняшним движением — ложная связь, а не объяснение.
    """
    try:
        import yfinance as yf
        items = yf.Ticker(symbol).news or []
    except Exception as e:
        log.warning("новости Yahoo по %s не получены: %s", symbol, e)
        return None

    best = None
    for item in items:
        c = item.get("content") or item
        title = (c.get("title") or "").strip()
        if not title:
            continue
        pub = c.get("pubDate") or c.get("displayTime") or ""
        try:
            ts = int(datetime.fromisoformat(pub.replace("Z", "+00:00")).timestamp())
        except ValueError:
            continue
        if now_ts - ts > _YAHOO_NEWS_MAX_AGE:
            continue
        url = ((c.get("canonicalUrl") or {}).get("url")
               or (c.get("clickThroughUrl") or {}).get("url") or "")
        provider = ((c.get("provider") or {}).get("displayName") or "").strip()
        if best is None or ts > best[0]:
            best = (ts, title, url, provider)
    return best[1:] if best else None


def _attach_context(con, rows: list[dict], now_ts: int) -> None:
    """Фон к каждому выбросу: рынок вокруг, соседи за порогом, новость."""
    for r in rows:
        r["_backdrop"] = _market_backdrop(r["asset_class"], now_ts)
        r["_peers"] = _peers_line(con, r, now_ts)
    _attach_news(con, rows, now_ts)


def _attach_news(con, rows: list[dict], now_ts: int) -> None:
    """Одна строка объяснения, если §3 связала выброс с темой — либо если её
    нашёл запасной поиск по самому инструменту (см. _find_cluster_by_symbol)."""
    for r in rows:
        got = None
        if r.get("news_cluster_id"):
            got = con.execute(
                "SELECT label, sample_title, sample_url, publishers FROM news_clusters WHERE id=?",
                (r["news_cluster_id"],),
            ).fetchone()
        if not got:
            got = _find_cluster_by_symbol(con, r, now_ts)
        if got:
            label, title, url, publishers = got
            r["_news"] = (f"📰 {_ru(title or label or '')} — пишут {publishers} "
                          f"{_plural(publishers, 'издание', 'издания', 'изданий')}")
            r["_news_url"] = url
            continue
        # В своей базе новости нет — идём на карточку инструмента Yahoo, туда
        # же, куда пошёл бы человек. Крипту пропускаем: у bybit-тикеров на
        # Yahoo карточки нет.
        if r["asset_class"] == "crypto":
            continue
        found = _yahoo_news(r["symbol"], now_ts)
        if not found:
            continue
        title, url, _provider = found
        # Имя издания из Yahoo («Motley Fool») намеренно НЕ печатаем: в русском
        # посте оно читается как приписка неизвестно к чему. Источник и так
        # виден строкой-ссылкой внизу, доменом.
        r["_news"] = f"📰 {_ru(title)}"
        r["_news_url"] = url


def refresh_published(con, now_ts: int) -> int:
    """Дополнить уже опубликованные посты, у которых причина нашлась позже.

    01.09, требование владельца: выброс публикуется сразу, даже без объяснения
    («просто пишем тикер и обозначаем рост»), но когда новость появляется —
    пост обязан её получить. Движение видно в первые минуты, новость выходит
    через час; ждать её ради полного поста значит опоздать с самим фактом.

    Работает только по постам за сутки и только в одну сторону: строка, в
    которой объяснение уже есть, повторно не трогается. Правку поста делает
    Vorovka2 (у него Telethon-клиент), здесь только взводится флаг.
    """
    # «Объяснения ещё нет» = ссылка внизу ведёт на карточку инструмента, а не
    # на новость. Признак именно такой, потому что заголовок в посте больше не
    # печатается (02.09) — искать в тексте нечего.
    rows = con.execute(
        "SELECT id, symbol, name, asset_class, chg_pct, peak_chg_pct, price, "
        "dollar_volume, market_cap, news_cluster_id, alert_payload FROM market_outliers "
        "WHERE channel_msg_id > 0 AND last_seen_ts >= ? "
        "AND (alert_payload LIKE '%finance.yahoo.com/quote/%' "
        "     OR alert_payload LIKE '%bybit.com/trade%') "
        "ORDER BY last_seen_ts DESC",
        (now_ts - 86400,),
    ).fetchall()
    updated = 0
    for row in rows:
        r = dict(zip(("id", "symbol", "name", "asset_class", "chg_pct", "peak_chg_pct",
                      "price", "dollar_volume", "market_cap", "news_cluster_id",
                      "alert_payload"), row))
        _attach_news(con, [r], now_ts)
        if not r.get("_news_url"):
            continue
        r["_backdrop"] = _market_backdrop(r["asset_class"], now_ts)
        r["_peers"] = _peers_line(con, r, now_ts)
        con.execute("UPDATE market_outliers SET alert_payload=?, channel_edit_pending=1 "
                    "WHERE id=?", (alert_text(r), r["id"]))
        log.info("выброс %s: причина найдена позже — пост будет дополнен", r["symbol"])
        updated += 1
    if updated:
        con.commit()
    return updated


def dispatch(con, cfg: dict, now_ts: int) -> dict:
    """Разослать то, что созрело. Возвращает счётчики для лога."""
    today = datetime.fromtimestamp(now_ts, timezone.utc).date()
    quiet = _quiet_mode(cfg, today)
    step = float(cfg.get("repeat_step_fraction") or 0.5)

    rows = O.today_rows(con, now_ts)
    _attach_context(con, rows, now_ts)

    already = sum(1 for r in rows if r.get("alerted_ts"))
    cap = int(cfg.get("max_alerts_per_day") or 5)

    fresh, repeats = [], []
    for r in rows:
        thr = cfg["crypto" if r["asset_class"] == "crypto" else "equity"]["abs_chg_pct"]
        if not r.get("alerted_ts"):
            if not r.get("alert_suppressed"):
                fresh.append(r)
            continue
        # Повтор допустим, только если движение продлилось ещё на половину
        # порога — иначе это то же самое событие, а не новое.
        prev = con.execute("SELECT alert_chg_pct FROM market_outliers WHERE id=?",
                           (r["id"],)).fetchone()[0]
        if prev is not None and abs(r["chg_pct"]) >= abs(prev) + thr * step:
            repeats.append(r)

    queue = fresh + repeats
    sent = suppressed = 0
    over_cap = []

    # 🔴 Потолок считается по МЕСТУ В ОЧЕРЕДИ, а не по числу отправленных
    # отсюда. Первая версия увеличивала счётчик только в ветках, которые шлют
    # сами (тихий режим и операционный адресат); при адресате «подписчики»
    # ничего не отправляется здесь — и потолок не срабатывал вовсе, а бот
    # разослал бы сколько угодно. Бюджет один на все ветки.
    budget = max(0, cap - already)
    left_for_bot = 0

    for r in queue:
        if budget <= 0:
            over_cap.append(r)
            continue
        budget -= 1
        if quiet:
            _enqueue_operational(con, r)
            con.execute(
                "UPDATE market_outliers SET alerted_ts=?, alert_chg_pct=?, alert_suppressed=? "
                "WHERE id=?", (now_ts, r["chg_pct"], "quiet_mode", r["id"]))
            sent += 1
        elif cfg.get("alert_target") == "operational":
            _enqueue_operational(con, r)
            con.execute("UPDATE market_outliers SET alerted_ts=?, alert_chg_pct=? WHERE id=?",
                        (now_ts, r["chg_pct"], r["id"]))
            sent += 1
        else:
            # Адресат — подписчики. Формат остаётся здесь: бот не форматирует
            # алерты, иначе §2.5 жил бы в двух зонах и разошёлся на первой
            # правке.
            #
            # 🔴 01.09: сначала ПОСТ В КАНАЛ @SBFEconomics, и только потом бот
            # форвардит его подписчикам (решение владельца). У поста появляется
            # постоянная ссылка, канал ведёт свою ленту, а подписчик видит
            # первоисточник, а не пересказ.
            #
            # Публикуем НЕ отсюда: канал ведётся через Telethon-юзербота
            # Vorovka2 (@SBFEconomics — его TARGET_CHANNEL), боты в канал не
            # добавлены и Bot API туда не пишет. Здесь строка просто ложится в
            # очередь — alert_payload заполнен, channel_msg_id пуст; её
            # забирает publish_outliers() внутри уже работающего процесса
            # Vorovka2. Второй Telethon-клиент на той же сессии заводить
            # нельзя — это конфликт сессии с боевым процессом.
            con.execute("UPDATE market_outliers SET alert_payload=? WHERE id=?",
                        (alert_text(r), r["id"]))
            left_for_bot += 1

    if over_cap:
        # §2.4: при превышении не молчать и не спамить — одно сводное.
        for r in over_cap:
            con.execute("UPDATE market_outliers SET alert_suppressed=? WHERE id=?",
                        ("daily_cap", r["id"]))
            suppressed += 1
        _enqueue_operational_text(
            con, "outliers_cap",
            f"📊 Ещё {len(over_cap)} "
            f"{_plural(len(over_cap), 'инструмент', 'инструмента', 'инструментов')} "
            f"за порогом сегодня (лимит {cap} "
            f"{_plural(cap, 'алерт', 'алерта', 'алертов')} исчерпан) — "
            f"смотри блок в брифинге.")
    con.commit()
    return {"quiet": quiet, "sent": sent, "suppressed": suppressed,
            "pending_for_bot": left_for_bot}


def _enqueue_operational(con, row: dict) -> None:
    _enqueue_operational_text(con, "outliers", alert_text(row))


def _enqueue_operational_text(con, source: str, text: str) -> None:
    """Через общий outbox, а не своим httpx: токен, ретраи и история отправок
    живут в одном месте (analyze/outbox.py)."""
    from analyze import outbox
    outbox.enqueue(con, source=source, status_label="ФАКТ", payload=text)


def _link_news(con, now_ts: int) -> tuple[int, int]:
    """§3.1. Отказ здесь НЕ роняет скан: выброс без объяснения — рабочий
    случай (факт движения самоценен, придумывать причину нельзя), а вот
    молча потерянный скан был бы потерей данных."""
    from core import news_clusters as NC
    day = datetime.fromtimestamp(now_ts, timezone.utc).strftime("%Y-%m-%d")
    try:
        headlines = NC.recent_headlines(24, now_ts)
    except Exception as e:
        log.error("outliers: лента новостей недоступна (%s) — выбросы без объяснений", e)
        return 0, 0
    linked = topics = 0
    try:
        linked = NC.link_outliers(con, O.today_rows(con, now_ts), headlines, day, now_ts)
    except Exception as e:
        log.error("outliers: связь выброс-заголовок не построена: %s", e)
    try:
        topics = NC.store_topics(con, NC.topic_bursts(headlines), day, now_ts)
    except Exception as e:
        log.error("outliers: темы-всплески не посчитаны: %s", e)
    return linked, topics


def publish_json(con, cfg: dict, now_ts: int) -> Path:
    """§6. Пишется этим же джобом, а не общим publish_all(): у него свой такт
    (15 минут против часа) и свои источники."""
    rows = O.today_rows(con, now_ts)
    day = datetime.fromtimestamp(now_ts, timezone.utc).strftime("%Y-%m-%d")
    # Темы «вне контекста» кладём в ЭТОТ же файл, а не в brief_today.json:
    # бриф пересобирается раз в сутки в 06:00, а тут такт 15 минут. Иначе
    # сайт до следующего утра показывал бы вчерашние темы рядом со свежими
    # движениями — два блока об одном дне с разным возрастом.
    topics = con.execute(
        "SELECT label, key, summary, publishers, items, outlier_symbol "
        "FROM news_clusters WHERE day=? AND summary_status='ok' "
        "ORDER BY publishers DESC LIMIT 3", (day,)).fetchall()
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    out = WEB_DATA / "outliers.json"
    out.write_text(json.dumps({
        "updated": datetime.now(timezone.utc).isoformat(),
        "thresholds": {"equity": cfg["equity"], "crypto": cfg["crypto"]},
        "items": [{
            "symbol": r["symbol"], "name": r["name"], "asset_class": r["asset_class"],
            "chg_pct": r["chg_pct"], "peak_chg_pct": r["peak_chg_pct"],
            "price": r["price"], "dollar_volume": r["dollar_volume"],
            "screener": r["screener"],
            "seen_utc": datetime.fromtimestamp(r["last_seen_ts"], timezone.utc).isoformat(),
            "explained": bool(r["news_cluster_id"]),
        } for r in rows],
        "off_context": [{
            "label": t[0] or t[1],
            "text": t[2],
            "publishers": t[3],
            "items": t[4],
            "symbol": t[5],
        } for t in topics],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def triage(now_ts: int, force: bool = False, verbose: bool = False) -> int:
    """§3.2. Отдельный вход, а НЕ часть 15-минутного скана: скан идёт 96 раз в
    сутки, а вопрос «что сегодня выбилось из контекста» имеет смысл задать
    один раз, перед утренним брифингом (analyze/run_daily.sh). Девяносто шесть
    вызовов модели в день ради одного блока — цена без содержания."""
    from core import news_clusters as NC
    from core import outlier_triage as T

    day = datetime.fromtimestamp(now_ts, timezone.utc).strftime("%Y-%m-%d")
    try:
        headlines = NC.recent_headlines(24, now_ts)
    except Exception as e:
        log.error("триаж: лента новостей недоступна (%s) — блока не будет", e)
        return 1

    con = _connect()
    try:
        stats = T.run(con, day, headlines, now_ts=now_ts, force=force, verbose=verbose)
    finally:
        con.close()

    print(f"триаж: предложено {stats['offered']}, сформулировано {stats['ok']}, "
          f"отклонено валидатором {stats['rejected']}, не выбрано {stats['skipped']}, "
          f"модель молчит {stats['failed']}")
    # Ненулевой код только когда модель не ответила вовсе: «предложили и
    # ничего не выбрано» — штатный тихий день, а не отказ.
    return 1 if stats["failed"] else 0


def report(cfg: dict, top: int) -> int:
    """Что близко к порогу — для калибровки. Ничего не пишет."""
    eq, market_open = O.fetch_equity({**cfg, "equity": {**cfg["equity"], "abs_chg_pct": 0,
                                                        "min_price_usd": 0,
                                                        "min_dollar_volume": 0}})
    cr = O.fetch_crypto({**cfg, "crypto": {**cfg["crypto"], "abs_chg_pct": 0,
                                           "min_dollar_volume": 0}})
    for title, rows, thr in (("АКЦИИ", eq, cfg["equity"]), ("КРИПТА", cr, cfg["crypto"])):
        rows.sort(key=lambda r: abs(r["chg_pct"]), reverse=True)
        print(f"\n=== {title} — порог {thr['abs_chg_pct']}%, "
              f"объём торгов от ${thr.get('min_dollar_volume'):,} ===")
        for r in rows[:top]:
            passes = (abs(r["chg_pct"]) >= thr["abs_chg_pct"]
                      and r["dollar_volume"] >= thr.get("min_dollar_volume", 0)
                      and r["price"] >= thr.get("min_price_usd", 0))
            mark = "ПРОЙДЁТ" if passes else "       "
            print(f"  {mark} {r['symbol']:<12} {r['chg_pct']:+7.2f}%  "
                  f"пик {str(r['peak_chg_pct']):>8}  объём ${_fmt_money(r['dollar_volume']):>9}"
                  f"  {(r['name'] or '')[:34]}")
    print(f"\nрынок США открыт: {market_open}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=int, metavar="N",
                    help="показать N ближайших к порогу и выйти, ничего не записывая")
    ap.add_argument("--config", help="другой файл порогов (для прогона на других значениях)")
    ap.add_argument("--triage", action="store_true",
                    help="§3.2: спросить модель, что из тем дня — событие, и выйти "
                         "(раз в сутки, перед брифингом; скан этого не делает)")
    ap.add_argument("--force", action="store_true",
                    help="с --triage: переспросить и по темам, о которых модель уже высказалась")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    cfg = O.load_config()
    if args.config:
        override = json.loads(Path(args.config).read_text(encoding="utf-8"))
        cfg = {**cfg, **{k: v for k, v in override.items() if not k.startswith("_")}}
        for section in ("equity", "crypto"):
            if section in override:
                cfg[section] = {**cfg[section], **override[section]}

    if args.report:
        return report(cfg, args.report)

    if args.triage:
        return triage(int(time.time()), force=args.force, verbose=args.verbose)

    now_ts = int(time.time())
    failures = []
    eq, market_open = [], False
    try:
        eq, market_open = O.fetch_equity(cfg)
    except O.SourceFailed as e:
        failures.append(str(e))
    try:
        cr = O.fetch_crypto(cfg)
    except O.SourceFailed as e:
        failures.append(str(e))
        cr = []

    if len(failures) == 2:
        # Оба источника молчат — это не «сегодня тихо», это мы не смотрели.
        log.error("outliers: ни один источник не ответил: %s", "; ".join(failures))
        return 1
    for f in failures:
        log.error("outliers: источник недоступен: %s", f)

    con = _connect()
    try:
        new, updated = O.upsert(con, eq + cr, now_ts)
        # §3.1 ступень 1 — ДО рассылки: связь «выброс ↔ заголовок» должна
        # успеть попасть в сам алерт строкой объяснения, иначе смысл ловить
        # её вообще пропадает (к утру движение уже история).
        linked, topics = _link_news(con, now_ts)
        stats = dispatch(con, cfg, now_ts)
        # После рассылки: посты, опубликованные без объяснения, могли его
        # получить за прошедшие 15 минут. Правку сделает Vorovka2 по флагу.
        enriched = refresh_published(con, now_ts)
        path = publish_json(con, cfg, now_ts)
    finally:
        con.close()

    print(f"outliers: новых {new}, обновлено {updated}, объяснено новостью {linked}, "
          f"дополнено постов {enriched}, "
          f"тем-всплесков {topics}, отправлено {stats['sent']}, "
          f"придержано {stats['suppressed']}, ждёт бота {stats['pending_for_bot']}, "
          f"тихий режим {stats['quiet']}, рынок США открыт {market_open} -> {path.name}")
    # Частичный отказ источника — ненулевой код: таймер это покажет в journalctl,
    # а не растворит в «прогон успешен, просто пусто».
    return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
