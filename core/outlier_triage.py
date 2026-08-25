"""core/outlier_triage.py — триаж моделью поверх посчитанного охвата (SPEC §3.2).

ЧТО ЗДЕСЬ НЕ ПРОИСХОДИТ. Модель не оценивает важность. Важность уже посчитана
кодом — числом разных публикаторов за сутки (core/news_clusters.py). Вопрос к
модели узкий: «выбери из этих тем 1-2, которые действительно событие, и
напиши по одной фразе, что произошло». Числа считает код, модель пишет только
текст — тот же принцип, что в news_digest_job.py и analyze/llm_context.py.

ВАЛИДАТОР НЕ СВОЙ. Спека прямо запрещает заводить второй: берём
news_digest_job.validate (лексикон прогнозов/рекомендаций/будущего времени
рядом с процентом). Здесь сверх него только бюджет длины — фраза, а не
абзац; это ограничение формы, а не второй набор правил содержания.

ПРОВАЛ ВИДЕН, А НЕ ТИХ. Модель не ответила или ответ отклонён — блока в
брифинге нет, а у каждой предложенной темы в базе стоит причина
(summary_status). «Тема была, но почему-то без фразы» не должно быть
представимо — тот же принцип, что alert_suppressed у выбросов.

Статусы summary_status:
    ok        — фраза написана и прошла валидатор;
    rejected  — модель выбрала тему, но текст отклонён валидатором;
    skipped   — тема предлагалась, модель её не выбрала (штатный исход);
    failed    — модель не ответила вовсе (упала/таймаут/невалидный JSON);
    NULL      — тема модели не предлагалась: не вошла в CANDIDATES_CAP по
                охвату. Не «нет ответа», а «вопрос не задавали».
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from core.config import BASE_DIR, DATA_DIR

log = logging.getLogger("outlier_triage")

CLAUDE_BIN = str(Path.home() / ".local" / "bin" / "claude")
CLAUDE_TIMEOUT_SEC = 90        # раз в сутки, не в час — можно дать больше, чем дайджесту
DRAFT_PATH = DATA_DIR / "reports" / "outlier_triage_draft.json"
REJECTED_LOG = DATA_DIR / "reports" / "outlier_triage_rejected.log"

CANDIDATES_CAP = 10            # столько тем показываем модели
HEADLINES_PER_CLUSTER = 4      # столько заголовков на тему — чтобы было из чего формулировать
MAX_PHRASE_LEN = 180           # «одна фраза», а не абзац
MAX_PICKS = 2                  # §3.2: выбрать 1-2


def _validate_phrase(text) -> str | None:
    """Валидатор новостного дайджеста + бюджет длины. Второго набора правил
    содержания здесь нет и быть не должно (см. докстринг модуля)."""
    if not isinstance(text, str):
        return None
    t = " ".join(text.split())
    if not t or len(t) > MAX_PHRASE_LEN:
        return None
    sys.path.insert(0, str(BASE_DIR))
    from news_digest_job import validate as digest_validate
    return digest_validate(t)


def candidates(con: sqlite3.Connection, day: str, *, force: bool = False,
               limit: int = CANDIDATES_CAP) -> list[dict]:
    """Темы дня, по которым модель ещё не высказывалась. Порядок — по охвату:
    первым идёт то, о чём написало больше разных изданий."""
    sql = ("SELECT id, kind, key, label, publishers, items, sample_title, outlier_symbol "
           "FROM news_clusters WHERE day=?")
    if not force:
        sql += " AND summary_status IS NULL"
    sql += " ORDER BY publishers DESC, items DESC LIMIT ?"
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(sql, (day, limit)).fetchall()]


def _pick_headlines(cluster: dict, headlines: list[dict]) -> list[dict]:
    """До HEADLINES_PER_CLUSTER заголовков темы, по одному от издания: пять
    перепечаток одного текста не помогают сформулировать, а место занимают.

    Возвращает сами заголовки, а не строки промпта: те же объекты потом
    сохраняются в summary_sources — это и есть материал, из которого модель
    писала фразу, и единственное, что честно показывать рядом с ней."""
    from core import news_clusters as NC
    hits = NC.headlines_for_cluster(cluster["kind"], cluster["key"],
                                    cluster.get("label") or "", headlines)
    hits.sort(key=lambda h: -h["published_ts"])
    seen_pub, out = set(), []
    for h in hits:
        if h["publisher"] in seen_pub:
            continue
        seen_pub.add(h["publisher"])
        out.append({"title": h["title"], "url": h["url"], "publisher": h["publisher"]})
        if len(out) >= HEADLINES_PER_CLUSTER:
            break
    if not out and cluster.get("sample_title"):
        out.append({"title": cluster["sample_title"], "url": None, "publisher": None})
    return out


def _build_prompt(blocks: list[str]) -> str:
    return f"""Ты формулируешь короткие фразы о событиях дня для утреннего брифинга
финансового образовательного сайта. Правило Voice SBF: коротко, лаконично,
исчерпывающе.

ВХОД — темы, о которых за последние сутки написало много РАЗНЫХ изданий, и
заголовки по каждой:

{chr(10).join(blocks)}

ЗАДАЧА: выбрать не больше {MAX_PICKS} тем, которые действительно являются
событием, и написать по каждой ОДНУ фразу — что произошло.

Важность оценивать НЕ надо: она уже посчитана числом изданий, оно указано.
Твоя работа — сформулировать, а не ранжировать.

ПРАВИЛА (обязательны, без исключений):
- одна фраза на тему, не длиннее {MAX_PHRASE_LEN} знаков;
- только то, что произошло, и кого/чего это касается — факт, не интерпретация;
- только из заголовков выше, ничего от себя и ничего по памяти;
- БЕЗ оценочных прилагательных ("резкий", "мощный", "тревожный", "исторический");
- БЕЗ прогнозов и будущего времени ("ожидается", "продолжит", "вырастет", "может");
- БЕЗ рекомендаций, уровней входа, "стоит", "рекомендуем";
- если тема — не событие, а общий фон (разрозненные заголовки, попавшие под
  одно слово), НЕ выбирай её. Пустой список — нормальный и ожидаемый ответ,
  выдавливать из себя фразу ради заполнения блока запрещено.

Запиши результат СТРОГО в виде JSON-файла {DRAFT_PATH} (Write):
{{"picks": [{{"id": <id темы из списка выше>, "text": "<одна фраза>"}}]}}
Верни в stdout только путь к файлу."""


def prepare(cands: list[dict], headlines: list[dict]) -> tuple[list[str], dict[int, list[dict]]]:
    """(блоки промпта, что показали по каждой теме). Второе — не для промпта,
    а для записи в summary_sources после успеха."""
    blocks, shown = [], {}
    for c in cands:
        titles = _pick_headlines(c, headlines)
        if not titles:
            continue
        shown[c["id"]] = titles
        head = f"id {c['id']} · «{c['label'] or c['key']}» · изданий: {c['publishers']}"
        if c.get("outlier_symbol"):
            head += f" · движение цены: {c['outlier_symbol']}"
        blocks.append(head + "\n" + "\n".join(
            f"  - [{t['publisher'] or '?'}] {t['title']}" for t in titles))
    return blocks, shown


def _call_claude(blocks: list[str], verbose: bool = False) -> list[dict] | None:
    """None — модель не ответила (упала/таймаут/нет файла/не тот JSON).
    Пустой список — ответила и не выбрала ничего, это штатный исход."""
    if not blocks:
        return []

    env = {**os.environ, "PATH": f"{Path.home()}/.local/bin:{os.environ.get('PATH', '')}"}
    try:
        DRAFT_PATH.parent.mkdir(parents=True, exist_ok=True)
        if DRAFT_PATH.exists():
            DRAFT_PATH.unlink()  # не читать вчерашний черновик, если claude упадёт до Write
        subprocess.run(
            [CLAUDE_BIN, "-p", _build_prompt(blocks), "--allowedTools", "Write",
             "--output-format", "text"],
            timeout=CLAUDE_TIMEOUT_SEC, capture_output=True, text=True, check=False, env=env,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        log.error("триаж: claude -p упал/не уложился в таймаут: %s", e)
        return None

    try:
        draft = json.loads(DRAFT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.error("триаж: черновик модели не прочитан (%s)", e)
        return None
    picks = draft.get("picks")
    if not isinstance(picks, list):
        log.error("триаж: в черновике нет списка picks: %r", draft)
        return None
    return picks


def run(con: sqlite3.Connection, day: str, headlines: list[dict], *,
        now_ts: int | None = None, force: bool = False, verbose: bool = False) -> dict:
    """Возвращает счётчики. Ничего не бросает: провал триажа — это отсутствие
    блока в брифинге, а не падение утреннего пайплайна."""
    # 🔴 Любой исход, кроме 'ok', ЗАЧИЩАЕТ summary. Найдено на повторном
    # прогоне 25.08: тема «reserve» была выбрана в первом заходе, во втором
    # (--force) модель её не выбрала -- статус стал 'skipped', а фраза от
    # первого захода осталась висеть в строке. Пара «статус говорит одно,
    # текст лежит другой» -- это то же самое непредставимое состояние, ради
    # запрета которого заведены alert_suppressed и order_status.
    now = int(now_ts or time.time())
    cands = candidates(con, day, force=force)
    stats = {"offered": len(cands), "ok": 0, "rejected": 0, "skipped": 0, "failed": 0}
    if not cands:
        return stats

    blocks, shown = prepare(cands, headlines)
    picks = _call_claude(blocks, verbose=verbose)

    if picks is None:
        # Модель молчит. Причина у КАЖДОЙ предложенной темы, иначе завтра
        # непонятно, было ли пусто или сломано.
        con.executemany(
            "UPDATE news_clusters SET summary_status='failed', summary=NULL, "
            "summary_sources=NULL WHERE id=?", [(c["id"],) for c in cands])
        con.commit()
        stats["failed"] = len(cands)
        return stats

    offered_ids = {c["id"] for c in cands}
    by_id = {c["id"]: c for c in cands}
    decided: set[int] = set()

    for p in picks[:MAX_PICKS]:
        if not isinstance(p, dict):
            continue
        try:
            cid = int(p.get("id"))
        except (TypeError, ValueError):
            log.warning("триаж: у выбора нет разбираемого id: %r", p)
            continue
        if cid not in offered_ids:
            # Модель назвала тему, которой ей не показывали — не подставляем
            # её в брифинг молча.
            log.warning("триаж: модель вернула id=%s, которого не было в списке", cid)
            continue
        text = _validate_phrase(p.get("text"))
        if text is None:
            REJECTED_LOG.parent.mkdir(parents=True, exist_ok=True)
            with REJECTED_LOG.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.fromtimestamp(now, timezone.utc):%Y-%m-%dT%H:%M:%SZ}\t"
                        f"{by_id[cid]['key']}\t{p.get('text')!r}\n")
            con.execute("UPDATE news_clusters SET summary_status='rejected', summary=NULL, "
                        "summary_sources=NULL WHERE id=?", (cid,))
            stats["rejected"] += 1
            decided.add(cid)
            continue
        con.execute(
            "UPDATE news_clusters SET summary=?, summary_status='ok', summary_sources=? "
            "WHERE id=?",
            (text, json.dumps(shown.get(cid, []), ensure_ascii=False), cid))
        stats["ok"] += 1
        decided.add(cid)

    rest = [(c["id"],) for c in cands if c["id"] not in decided]
    if rest:
        con.executemany("UPDATE news_clusters SET summary_status='skipped', summary=NULL, "
                        "summary_sources=NULL WHERE id=?", rest)
        stats["skipped"] = len(rest)
    con.commit()
    return stats
