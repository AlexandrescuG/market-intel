#!/usr/bin/env python3
"""brief_email_job.py — утренний брифинг на почту.

Берёт готовый синтез (web/data/brief_today.json, его делает sbf-morning в 06:00)
и рассылает тем, кто согласился получать рассылку.

🔴 КОМУ ШЛЁМ — ТОЛЬКО ПО ЯВНОМУ СОГЛАСИЮ.
Условие одно: users.consent_marketing = 1. Не «зарегистрирован», не «активен»,
не «оставил почту» — именно галочка про рассылку, поставленная человеком.
Разослать по всей базе технически проще и ровно поэтому опасно: письмо не
отзывается, а жалоба на спам бьёт по домену, с которого мы шлём коды входа.

Повторов нет: отправленное за дату записывается в brief_email_log, и второй
запуск в тот же день никому ничего не пришлёт.

Запуск:
  python3 brief_email_job.py            # предпросмотр, писем НЕ шлёт
  python3 brief_email_job.py --send     # отправка
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core import mailer  # noqa: E402

JOURNAL_DB = ROOT / "data" / "journal.db"
BRIEF = ROOT / "web" / "data" / "brief_today.json"
SITE = "https://lp.sbfconsult.com"


def ensure_log(con: sqlite3.Connection) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS brief_email_log(
        day TEXT NOT NULL, user_id TEXT NOT NULL, sent_ts INTEGER NOT NULL,
        PRIMARY KEY (day, user_id))""")
    con.commit()


def _esc(x) -> str:
    return html_mod.escape(str(x or ""))


# Тот же словарь, что на графиках. Письмо на русском с английскими названиями
# показателей выглядит недоделкой, а заводить второй словарь — верный способ
# получить два расходящихся перевода одного и того же.
_RU: dict | None = None


def _ru_title(ev: dict) -> str:
    global _RU
    if _RU is None:
        try:
            _RU = json.loads((ROOT / "data" / "econ_indicator_ru.json")
                             .read_text(encoding="utf-8"))
        except Exception:
            _RU = {}
    title = ev.get("title_ru") or ev.get("title") or ev.get("indicator") or ""
    if ev.get("title_ru") or not _RU:
        return title
    key = (ev.get("indicator") or title).strip().lower()
    base = _RU.get(key)
    if not base:
        return title
    country = (_RU.get("_countries") or {}).get((ev.get("country") or "").upper())
    return f"{base} · {country}" if country else base


def build_html(brief: dict) -> tuple[str, str]:
    """(html, текстовая версия). Обе — из одних и тех же данных."""
    day = brief.get("date") or str(date.today())
    blocks: list[str] = []
    plain: list[str] = [f"Утренний брифинг SBF · {day}", ""]

    cal = brief.get("calendar") or []
    if cal:
        items = []
        for e in cal[:6]:
            title = _ru_title(e)
            when = e.get("time") or e.get("when") or ""
            items.append(f"<li>{_esc(title)}"
                         + (f" <span style='color:#8a8a94'>· {_esc(when)}</span>" if when else "")
                         + "</li>")
            plain.append(f"— {title} {when}".rstrip())
        blocks.append("<h3 style='margin:18px 0 6px;font-size:15px'>Календарь на сегодня</h3>"
                      f"<ul style='margin:0;padding-left:18px;line-height:1.7'>{''.join(items)}</ul>")

    # 🔴 movers — это не список, а словарь {up: [...], down: [...]}. Первая
    # версия резала его срезом и падала на KeyError. Формат брифинга сложился
    # раньше этой рассылки, и подгонять надо рассылку под него, а не наоборот.
    _mv = brief.get("movers") or {}
    if isinstance(_mv, dict):
        movers = (_mv.get("up") or []) + (_mv.get("down") or [])
    else:
        movers = list(_mv)
    if movers:
        items = []
        for m in movers[:6]:
            sym = m.get("symbol") or m.get("name") or ""
            chg = m.get("chg_pct")
            chg_s = f"{chg:+.2f}%" if isinstance(chg, (int, float)) else ""
            color = "#1e8e5a" if isinstance(chg, (int, float)) and chg >= 0 else "#c0392b"
            items.append(f"<li>{_esc(sym)} <b style='color:{color}'>{_esc(chg_s)}</b></li>")
            plain.append(f"— {sym} {chg_s}".rstrip())
        blocks.append("<h3 style='margin:18px 0 6px;font-size:15px'>Заметные движения</h3>"
                      f"<ul style='margin:0;padding-left:18px;line-height:1.7'>{''.join(items)}</ul>")

    off = brief.get("off_context") or []
    if off:
        items = "".join(f"<li>{_esc((o.get('title') or o.get('text') or ''))[:180]}</li>"
                        for o in off[:4])
        blocks.append("<h3 style='margin:18px 0 6px;font-size:15px'>Вне контекста рынка</h3>"
                      f"<ul style='margin:0;padding-left:18px;line-height:1.7'>{items}</ul>")

    if not blocks:
        # Пустой брифинг не рассылаем — см. main(). Здесь просто честный ответ.
        return "", ""

    html = f"""<!doctype html><html><body style="margin:0;background:#FBF6EF;
 font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;color:#2B2B33">
<div style="max-width:600px;margin:0 auto;padding:24px 20px">
  <div style="font-size:13px;letter-spacing:2px;color:#C9A227">SBF INTELLIGENCE</div>
  <h1 style="font-size:20px;margin:8px 0 2px">Утренний брифинг</h1>
  <div style="color:#8a8a94;font-size:13px">{_esc(day)}</div>
  {''.join(blocks)}
  <p style="margin:24px 0 0"><a href="{SITE}" style="color:#C9A227">Открыть платформу →</a></p>
  <hr style="border:0;border-top:1px solid #e5ded3;margin:22px 0 10px">
  <p style="font-size:11px;color:#8a8a94;line-height:1.6">
    Вы получили это письмо, потому что согласились на рассылку при регистрации на
    lp.sbfconsult.com. Отписаться можно в профиле.<br>
    Материал носит информационный характер и не является инвестиционной рекомендацией.
    Торговля CFD сопряжена с высоким риском потери капитала.
  </p>
</div></body></html>"""
    return html, "\n".join(plain)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="реально отправить (без флага — предпросмотр)")
    ap.add_argument("--only", help="отправить только на этот адрес (проверка)")
    args = ap.parse_args()

    if not BRIEF.exists():
        print(f"нет {BRIEF} — утренний синтез ещё не отработал", file=sys.stderr)
        return 1
    brief = json.loads(BRIEF.read_text(encoding="utf-8"))
    html, text = build_html(brief)
    if not html:
        print("брифинг пуст — рассылать нечего")
        return 0

    day = brief.get("date") or str(date.today())
    con = sqlite3.connect(str(JOURNAL_DB))
    ensure_log(con)

    rows = con.execute(
        "SELECT id, email FROM users WHERE consent_marketing = 1 "
        "AND email IS NOT NULL AND email <> '' "
        "AND (deleted_at IS NULL OR deleted_at = '')").fetchall()
    if args.only:
        # 🔴 Проверочная отправка на один явно названный адрес идёт В ОБХОД
        # фильтра согласия — но только если такой пользователь у нас есть.
        #
        # Обоснование: галочка про рассылку защищает человека от писем, которых
        # он не просил. Здесь адрес называет владелец системы, чтобы посмотреть
        # на вёрстку письма, и отказать ему в этом — формализм. Но обход
        # ограничен одним адресом из базы: разослать «в обход» всем этим
        # способом нельзя, и случайно превратить проверку в рассылку тоже.
        #
        # В brief_email_log проверка НЕ записывается: иначе настоящая утренняя
        # рассылка сочла бы, что этому человеку уже отправляла.
        found = con.execute(
            "SELECT id, email FROM users WHERE email = ? "
            "AND (deleted_at IS NULL OR deleted_at = '')", (args.only,)).fetchall()
        if not found:
            print(f"пользователя с адресом {args.only} в базе нет — не отправляю",
                  file=sys.stderr)
            return 1
        rows = found

    sent = skipped = failed = 0
    for user_id, email in rows:
        already = con.execute(
            "SELECT 1 FROM brief_email_log WHERE day=? AND user_id=?", (day, user_id)).fetchone()
        if already:
            skipped += 1
            continue
        ok = mailer.send(email, f"Утренний брифинг SBF · {day}", html, text, send=args.send)
        if ok and args.send and args.only:
            sent += 1     # проверка: в журнал не пишем, см. комментарий выше
        elif ok and args.send:
            con.execute("INSERT OR IGNORE INTO brief_email_log(day, user_id, sent_ts) "
                        "VALUES(?,?,strftime('%s','now'))", (day, user_id))
            sent += 1
        elif ok:
            sent += 1     # предпросмотр
        else:
            failed += 1
    con.commit()
    con.close()

    mode = "ОТПРАВЛЕНО" if args.send else "предпросмотр (ничего не ушло)"
    print(f"{mode}: получателей с согласием {len(rows)}, писем {sent}, "
          f"уже отправляли сегодня {skipped}, ошибок {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
