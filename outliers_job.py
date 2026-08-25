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

sys.path.insert(0, str(Path(__file__).parent))

from core import outliers as O
from core.db_migrations import apply_all

BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
WEB_DATA = Path(__file__).parent / "web" / "data"

log = logging.getLogger("outliers_job")

DISCLAIMER = "Статистическое наблюдение, не рекомендация."


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


def alert_text(row: dict) -> str:
    """§2.5. Без объяснения тоже отправляем: факт движения самоценен, а
    придумывать причину нельзя."""
    cls = "крипта" if row["asset_class"] == "crypto" else "акция"
    name = row.get("name") or row["symbol"]
    lines = [f"📈 <b>{row['symbol']}</b> · {name}", f"{cls} · {_fmt_pct(row['chg_pct'])} за день"]
    peak = row.get("peak_chg_pct")
    if peak is not None and abs(peak) > abs(row["chg_pct"]) + 0.5:
        lines.append(f"в моменте {_fmt_pct(peak)}")
    lines.append(f"цена {row['price']} · оборот ${_fmt_money(row.get('dollar_volume'))}")
    seen = datetime.fromtimestamp(row["last_seen_ts"], timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"снято {seen} · источник {row.get('screener')}")
    if row.get("_news"):
        lines.append("")
        lines.append(row["_news"])
    lines.append("")
    lines.append(f"<i>{DISCLAIMER}</i>")
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


def _attach_news(con, rows: list[dict]) -> None:
    """Одна строка объяснения, если §3 связала выброс с темой."""
    for r in rows:
        if not r.get("news_cluster_id"):
            continue
        got = con.execute(
            "SELECT label, sample_title, sample_url, publishers FROM news_clusters WHERE id=?",
            (r["news_cluster_id"],),
        ).fetchone()
        if not got:
            continue
        label, title, url, publishers = got
        text = title or label or ""
        if url:
            text = f'<a href="{url}">{text}</a>'
        r["_news"] = (f"📰 {text} — пишут {publishers} "
                      f"{_plural(publishers, 'издание', 'издания', 'изданий')}")


def dispatch(con, cfg: dict, now_ts: int) -> dict:
    """Разослать то, что созрело. Возвращает счётчики для лога."""
    today = datetime.fromtimestamp(now_ts, timezone.utc).date()
    quiet = _quiet_mode(cfg, today)
    step = float(cfg.get("repeat_step_fraction") or 0.5)

    rows = O.today_rows(con, now_ts)
    _attach_news(con, rows)

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
            # Адресат — подписчики. Отправляет бот: у него аудитория,
            # часовые пояса и «тихие часы». Строку не трогаем, он её найдёт
            # по alerted_ts IS NULL AND alert_suppressed IS NULL.
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
            f"смотри блок в брифинге.\n\n"
            f"<i>{DISCLAIMER}</i>")
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
        } for r in rows],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


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
              f"оборот от ${thr.get('min_dollar_volume'):,} ===")
        for r in rows[:top]:
            passes = (abs(r["chg_pct"]) >= thr["abs_chg_pct"]
                      and r["dollar_volume"] >= thr.get("min_dollar_volume", 0)
                      and r["price"] >= thr.get("min_price_usd", 0))
            mark = "ПРОЙДЁТ" if passes else "       "
            print(f"  {mark} {r['symbol']:<12} {r['chg_pct']:+7.2f}%  "
                  f"пик {str(r['peak_chg_pct']):>8}  оборот ${_fmt_money(r['dollar_volume']):>9}"
                  f"  {(r['name'] or '')[:34]}")
    print(f"\nрынок США открыт: {market_open}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=int, metavar="N",
                    help="показать N ближайших к порогу и выйти, ничего не записывая")
    ap.add_argument("--config", help="другой файл порогов (для прогона на других значениях)")
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
        path = publish_json(con, cfg, now_ts)
    finally:
        con.close()

    print(f"outliers: новых {new}, обновлено {updated}, объяснено новостью {linked}, "
          f"тем-всплесков {topics}, отправлено {stats['sent']}, "
          f"придержано {stats['suppressed']}, ждёт бота {stats['pending_for_bot']}, "
          f"тихий режим {stats['quiet']}, рынок США открыт {market_open} -> {path.name}")
    # Частичный отказ источника — ненулевой код: таймер это покажет в journalctl,
    # а не растворит в «прогон успешен, просто пусто».
    return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
