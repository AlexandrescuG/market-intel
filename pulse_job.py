#!/usr/bin/env python3
"""
pulse_job.py — сколько раз актив упомянули в сети. Питает блок «Эпицентр».

🔴 ПОЧЕМУ ПЕРЕПИСАН (08.09.2026). Считалось по одному полю `signals.cashtags` —
это тикеры вида $BTC, которые ставят в твитах. Замер: за сутки такие теги
нашлись в **36 сигналах из 2391**, полтора процента потока. Остальные 98,5% —
RSS-заголовки, телеграм-посты и обычные твиты без доллара — механизм не видел
вовсе. Результат на витрине: у всех активов ноль упоминаний, подпись
«спокойный фон» и пустой блок на главной странице. Формально работало,
фактически показывало пустоту.

ЧТО СЧИТАЕМ ТЕПЕРЬ. `news_instrument_tags` — таблицу, которую наполняет
news_burst_job по словарю из 768 инструментов, по всем трём источникам сразу
(RSS + X + Telegram). Кештеги оттуда никуда не делись: они тоже учитываются,
просто больше не являются единственным источником.

ДВА ЧИСЛА, И ОНИ ОТВЕЧАЮТ НА РАЗНЫЕ ВОПРОСЫ:
  • mentions_24h — сколько всего упоминаний за сутки. Это «о чём вообще
    говорят», и именно оно определяет размер пузыря на главной.
  • score = упоминания за час / средний час недели. Это «где сейчас
    всплеск» — актив может быть тихим по объёму, но резко разогреться.
Раньше существовало только второе, и на спокойном рынке блок был пуст.

Использование:
  python3 pulse_job.py [--verbose]
"""
import argparse
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.config import DB_PATH  # noqa: E402

CATALOG = ROOT / "web" / "data" / "broker_catalog.json"
BLOCKLIST = ROOT / "data" / "instrument_blocklist.json"

MIN_BASELINE = 0.5
BURST_LOOKBACK_HOURS = 1
BOARD_WINDOW_HOURS = 24
BASELINE_DAYS = 7
HISTORY_KEEP_DAYS = 2      # для 24-часового спарклайна с запасом

# Направления, которые показываем как «разные». Ключ — категория каталога
# брокера, значение — как это называется у нас на витрине.
CATEGORY_MAP = {
    "crypto": "crypto", "stock": "stocks", "index": "indices",
    "fx": "fx", "commodity": "commodity", "etf": "stocks", "bond": "indices",
}

# Реестровые имена, которых нет в каталоге брокера как отдельных строк
# (GOLD/WTI/SPX и т.п. лежат там под именами брокера) — задаём направление явно.
REGISTRY_CATEGORY = {
    "GOLD": "commodity", "SILVER": "commodity", "WTI": "commodity", "NG": "commodity",
    "BTC": "crypto", "ETH": "crypto", "SOL": "crypto", "XRP": "crypto",
    "LTC": "crypto", "LINK": "crypto", "XLM": "crypto", "UNI": "crypto",
    "SPX": "indices", "NASDAQ": "indices", "DJI": "indices", "VIX": "indices",
    "DXY": "fx",
}

_FX_RE = re.compile(r"^[A-Z]{3}[A-Z]{3}$")


def _catalog_categories() -> dict:
    """{символ: направление} из каталога брокера, плюс канонические имена."""
    out = dict(REGISTRY_CATEGORY)
    try:
        raw = json.loads(CATALOG.read_text(encoding="utf-8"))
        items = raw.get("items", raw) if isinstance(raw, dict) else raw
    except Exception:
        return out
    for it in items:
        cat = CATEGORY_MAP.get(it.get("category"))
        if not cat:
            continue
        out.setdefault(it["symbol"], cat)
        if it.get("canonical"):
            out.setdefault(it["canonical"], cat)
    return out


def _blocked() -> set:
    try:
        raw = json.loads(BLOCKLIST.read_text(encoding="utf-8"))
        return {k for k in raw if not k.startswith("_")}
    except Exception:
        return set()


def _classify(symbol: str, cats: dict) -> str:
    """Направление инструмента. Валютную пару узнаём по форме имени.

    🔴 Раньше здесь стояло «всё, что не крипта и не индекс — акция», и на
    витрине в разделе «Акции» висел GBP. Категория берётся из каталога, а
    догадка по форме имени — только для того, чего в каталоге нет.
    """
    if symbol in cats:
        return cats[symbol]
    if _FX_RE.match(symbol):
        return "fx"
    if symbol.startswith(("#", "_")):
        return "stocks"
    return "stocks"


def _tag_counts(con, since_iso: str) -> dict:
    """{символ: сколько упоминаний} по news_instrument_tags за окно.

    Считаем по first_seen — по моменту, когда материал ВПЕРВЫЕ попал в поток,
    а не по дате публикации и не по last_seen.

    🔴 Здесь стоял last_seen, и это ломало метрику скрытно.

    last_seen обновляется каждый раз, когда коллектор снова видит ту же
    статью в ленте, — а ленты он перечитывает раз в 20 минут, и статья висит
    в них сутками. Замер 10.09.2026: за час 1119 новостей появились впервые
    и 3177 старых были перечитаны, и все 4296 считались упоминаниями «за
    последний час».

    Хуже всего то, что числитель и знаменатель мерились разными линейками. За
    час одна и та же статья попадала в счёт при каждом перечитывании; за 7
    дней она же попадала один раз, потому что в окно влезает почти всё. По
    #NVIDIA это давало 84 упоминания за час против 26 реальных — отсюда
    «×66 к своей норме» у инструмента, о котором пишут пару десятков раз в
    день.

    Перечитывание статьи — это не новое упоминание. Один материал — один раз,
    в тот час, когда он пришёл.
    """
    counts = {}
    try:
        rows = con.execute(
            """SELECT t.symbol, COUNT(*) FROM news_instrument_tags t
               JOIN signals s ON s.uid = t.news_uid
               WHERE s.first_seen >= ? GROUP BY t.symbol""",
            (since_iso,),
        ).fetchall()
    except sqlite3.OperationalError:
        return counts
    for sym, n in rows:
        counts[sym] = n
    return counts


def _cashtag_counts(con, since_iso: str) -> dict:
    """Кештеги ($BTC) — как дополнение, а не как единственный источник.

    Окно по first_seen, по той же причине, что и в _tag_counts: считаем
    материалы, а не то, сколько раз коллектор их перечитал.
    """
    counts = {}
    for (raw,) in con.execute("SELECT cashtags FROM signals WHERE first_seen >= ?", (since_iso,)):
        try:
            for t in json.loads(raw or "[]"):
                counts[t] = counts.get(t, 0) + 1
        except (ValueError, TypeError):
            continue
    return counts


def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, 0) + v
    return out


def run(verbose: bool = False) -> int:
    # 🔴 Ожидание 10 секунд не хватало: юнит падал с «database is locked» через
    # раз. Причина — signals.db в это же время пишут коллекторы. WAL важнее
    # самого таймаута: без него любой писатель блокирует всех читателей.
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    con.execute("PRAGMA journal_mode=WAL")
    # Окна упоминаний считаются по first_seen (см. _tag_counts). Индекс был
    # только по last_seen — по полю, которое мы перестали использовать, — и без
    # этого каждый прогон уходил бы в полный перебор signals.
    con.execute("CREATE INDEX IF NOT EXISTS idx_signals_first_seen "
                "ON signals(first_seen)")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS pulse_scores(
            symbol TEXT NOT NULL, category TEXT NOT NULL, ts INT NOT NULL,
            mentions INT, baseline REAL, score REAL,
            PRIMARY KEY(symbol, category, ts)
        );
    """)
    # Колонка добавлена 08.09 вместе с переходом на news_instrument_tags.
    # ALTER без IF NOT EXISTS — ловим ошибку, иначе второй прогон падал бы.
    try:
        con.execute("ALTER TABLE pulse_scores ADD COLUMN mentions_24h INT")
    except sqlite3.OperationalError:
        pass
    con.commit()

    now = time.time()
    iso = lambda sec: datetime.fromtimestamp(now - sec, timezone.utc).isoformat()
    h1  = iso(BURST_LOOKBACK_HOURS * 3600)
    d1  = iso(BOARD_WINDOW_HOURS * 3600)
    d7  = iso(BASELINE_DAYS * 86400)

    m_1h  = _merge(_tag_counts(con, h1), _cashtag_counts(con, h1))
    m_24h = _merge(_tag_counts(con, d1), _cashtag_counts(con, d1))
    m_7d  = _merge(_tag_counts(con, d7), _cashtag_counts(con, d7))

    cats = _catalog_categories()
    blocked = _blocked()
    written = 0
    ts_now = int(now)
    for symbol in set(m_7d) | set(m_24h):
        if symbol in blocked:
            continue
        category = _classify(symbol, cats)
        m1 = m_1h.get(symbol, 0)
        m24 = m_24h.get(symbol, 0)
        m7 = m_7d.get(symbol, 0)
        # 🔴 Текущий час из нормы вычитается.
        #
        # Норма считалась как «всё за 7 дней ÷ 168», а «всё за 7 дней»
        # включает и тот самый час, который мы с ней сравниваем. Пока приток
        # ровный, разница незаметна. 09.09.2026 расширенный сбор новостей за
        # два часа принёс 2244 материала при обычных 30–130 в час — и этот
        # пакет задал сам себе норму, а потом отчитался о рекорде
        # относительно неё. Сравнивать час нужно с тем, что было ДО него.
        prev = max(m7 - m1, 0)
        hours = BASELINE_DAYS * 24 - BURST_LOOKBACK_HOURS
        baseline = max(prev / hours, MIN_BASELINE)
        score = m1 / baseline
        con.execute(
            "INSERT OR REPLACE INTO pulse_scores"
            "(symbol, category, ts, mentions, baseline, score, mentions_24h) "
            "VALUES(?,?,?,?,?,?,?)",
            (symbol, category, ts_now, m1, baseline, score, m24),
        )
        written += 1
        if verbose and m24:
            print(f"  {category:9s}/{symbol:12s} за сутки={m24:4d} за час={m1:3d} "
                  f"фон={baseline:.2f} всплеск={score:.2f}")

    con.execute("DELETE FROM pulse_scores WHERE ts < ?",
                (int(now - HISTORY_KEEP_DAYS * 86400),))
    con.commit()
    con.close()
    if verbose:
        print(f"готово: {written} инструментов записано")
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    run(verbose=args.verbose)
