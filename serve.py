"""Static server + /api/quotes proxy + /edu book renderer.
JSX компилируется серверно при старте (Node.js + Babel). Браузер получает чистый JS."""
import glob
import http.server
import json
import math
import re
import sqlite3
import subprocess
import socketserver
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

# Journal modules (добавляем core/ в path)
sys.path.insert(0, str(Path(__file__).parent))
from core import journal_db, journal_crypto, journal_ocr, journal_csv, journal_meta, journal_discipline, journal_alerts, journal_brief, journal_setups, journal_tilt, journal_gamification, journal_goals, journal_account, journal_auth, journal_feedback, journal_import, journal_analytics, journal_review, journal_cooldown, journal_rules, journal_tradeplan, journal_gate, i18n
from core import symbols as _symbols
from core import candle_cache
from core.symbols_registry import yahoo_ticker as _registry_yahoo_ticker
from core.event_types import normalize_event_type
from core.config import DB_PATH as _SIGNALS_DB
from core.patterns import PATTERNS, detect as _detect_patterns
from day_thermo_job import _load_d1 as _thermo_load_d1, _range_series as _thermo_range_series, \
    _dvol_series as _thermo_dvol_series, CRYPTO_SYMBOLS as _THERMO_CRYPTO, \
    DVOL_CURRENCIES as _THERMO_DVOL_CCY
from core.sessions import session_bounds_utc, session_at
from core.journal_symbols import to_chart_symbol, chart_symbol_aliases
from core import focus_db
from core.focus import DEFAULT_UNIVERSE, select_focus
from core.sentiment_lexicon import detect_divergence
from sr_levels_job import _atr14, _load_d1_candles
from sentiment_job import STARTER_SYMBOLS as _SENTIMENT_SYMBOLS

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

PORT = 8085
DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
BOOK_DIR = Path(__file__).parent / "web" / "book"
EDU_DIR  = Path(__file__).parent / "web" / "edu"
WEB_DIR  = Path(__file__).parent / "web"

# SPEC_chart_fixes_and_staged_signup.md §3 / WP1.1 SPEC_alpha_engine_implementation.md:
# тикеры yfinance для live M5- и tail-эндпоинтов — раньше был свой хардкод-словарь
# _M5_YF_TICKERS (независимый от core.symbols_registry.yahoo_ticker(), с которым уже
# успел разойтись: тут USDJPY был "JPY=X", в реестре — устаревшее "USDJPY=X". Реестр
# теперь исправлен на "JPY=X" — единственный источник, дубль убран).
_m5_cache: dict = {}
_M5_CACHE_TTL = 90  # сек

# H4/W1 у Yahoo нет нативно — ресэмплим из H1/D1, как publish.py::publish_charts.
# M1 (SPEC_chart_m1_m5 §5): минутка on-demand из Yahoo, окно сутки. Отдельного
# фида/ретенции в price_bars намеренно нет — Yahoo даёт 1m за ~7 дней, а нам для
# графика нужно «последние сутки». Тот же оконный механизм, что M5, а не третья
# подсистема. Yahoo нативно даёт 1m/5m/15m/30m/60m/1d; H4 и W1 ресэмплим.
_TAIL_YF_INTERVAL = {"M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m", "H1": "60m",
                     "H4": "60m", "D1": "1d", "W1": "1d"}
_TAIL_YF_PERIOD   = {"M1": "1d", "M5": "2d", "M15": "5d", "M30": "7d", "H1": "1mo",
                     "H4": "1mo", "D1": "3mo", "W1": "1y"}
_TAIL_RESAMPLE    = {"H4": "4h", "W1": "1W"}
_TAIL_TF_SEC      = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600,
                     "H4": 14400, "D1": 86400, "W1": 604800}
_tail_cache: dict = {}
_TAIL_CACHE_TTL = 25  # чуть меньше минимальной частоты клиента (30с, §2)

# ── Real-time внутридневка из брокера MT5 (SPEC_chart_m1_m5) ─────────────────
# Yahoo отдаёт фьючерсы/индексы (GOLD/SILVER/WTI/US_500…) с задержкой ~10 мин.
# У брокера те же инструменты идут в реальном времени (~0.3 мин, проверено).
# Отдаём внутридневку (M1..H4) из моста для символов CHART_BROKER_MAP, Yahoo —
# фолбэк. Выборка 200-400 баров ~0.17с, кэш 20с, блокировка (мост последователен),
# любая ошибка -> None -> Yahoo (график не ломается, если мост лёг).
_mt5_lock = threading.Lock()
_mt5_conn = None
_mt5_tail_cache: dict = {}
_MT5_TAIL_TTL = 20
# 🔴 Символы, у которых фид брокера МЁРТВ (а не «на паузе»).
# Пустой ответ моста бывает двух разных природ, и путать их нельзя:
#   • пауза/сбой — брокер скоро продолжит, подставлять сюда Yahoo нельзя
#     (получится чужой скачок поверх брокерского ряда, семейство бага 20.08);
#   • фид умер — брокер перестал котировать символ насовсем (USDRUB стоит с
#     17 марта), и держать пустой график, когда у Yahoo есть свежие часовые
#     бары, — это не осторожность, а потеря данных.
# Заполняется в _mt5_tail, читается в _mt5_tail_supported. Час TTL: если
# брокер вернёт символ к жизни, запись протухнет сама.
_mt5_dead_feed: dict = {}
_MT5_DEAD_TTL = 3600
# Метка времени котировки каждого символа каталога — её уже собирает
# broker_catalog_loop раз в 15 с и кладёт в broker_symbols.quote_ts.
# Позволяет узнать, что фид мёртв, НЕ дёргая мост вообще.
_quote_ts_cache: tuple = (0.0, {})
_QUOTE_TS_TTL = 300
_FROZEN_SEC = 7 * 86400
_MT5_TF_ATTR = {"M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
                "M30": "TIMEFRAME_M30", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4",
                # 🔴 20.08.2026: D1/W1 сюда добавлены после того, как шип нашёлся
                # на ДЕФОЛТНОМ таймфрейме. До этого дневки/недельки уходили в
                # Yahoo-ветку ниже, и получалось так: история — из price_bars
                # (спот брокера, GOLD 4483.5), а сегодняшний бар тейл приносил
                # из GC=F (фьючерс, o=4580 c=4540.3) и клал его через
                # series.update() поверх. На экране это ровно «две цены сразу»:
                # весь ряд в одном масштабе цен и последняя свеча в другом,
                # оторванная вверх на 1.3%. Проверено живым Chrome 20.08:
                # lastCandle {open:4580, close:4542.5} против предыдущего
                # закрытия 4483.5.
                "D1": "TIMEFRAME_D1", "W1": "TIMEFRAME_W1"}
# Глубина хвоста. 🔴 20.08: было 300 на всех внутридневных ТФ, и на M1 это
# давало ПЯТЬ ЧАСОВ истории — график начинался посреди вчерашнего вечера и
# читался как «недостроенный». Замер стоимости выборки через мост:
# 300 баров — 0.07 с, 10000 баров — 0.11 с. То есть ограничение в 300
# ничего не экономило: время уходит на сам вызов, не на объём.
# Глубина по ТФ: M1 ~7 суток, M5 ~17, M15 ~31, M30 ~62, H1 ~125, H4 ~330.
_MT5_COUNT = {"M1": 10000, "M5": 5000, "M15": 3000, "M30": 3000,
              "H1": 3000, "H4": 2000, "D1": 3000, "W1": 1000}
_MT5_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"


def _mt5_bridge():
    global _mt5_conn
    if _mt5_conn is not None:
        try:
            _mt5_conn.ping()
            return _mt5_conn
        except Exception:
            _mt5_conn = None
    import rpyc
    _mt5_conn = rpyc.classic.connect("127.0.0.1", 18812)
    # 🔴 Ограничение времени ответа ОБЯЗАТЕЛЬНО. Этот вызов идёт синхронно из
    # обработчика веб-запроса (_mt5_tail <- /api/chart/tail). До 31.08 сервер
    # был однопоточным, и один запрос, ждущий мост, замораживал ВСЕ остальные —
    # туннель отдавал 502 на весь сайт. Ровно это и случилось 25.08, когда обход
    # спарклайнов насытил мост: сервис был "active", локальный curl не отвечал
    # вовсе, снаружи — bad gateway. Сервер теперь многопоточный, но таймаут
    # нужен по-прежнему: без него поток висит на мосту неограниченно, копится
    # очередь, и мы возвращаемся к тому же исчерпанию.
    # Без таймаута rpyc ждёт ответа сколько угодно.
    # 8 секунд — заметно больше обычного ответа моста (сотые доли секунды) и
    # заметно меньше терпения пользователя; не дождавшись, _mt5_tail вернёт
    # None и график честно возьмёт запасной источник, а не повесит сайт.
    _mt5_conn._config["sync_request_timeout"] = 8
    _mt5_conn.modules["MetaTrader5"].initialize(path=_MT5_PATH, timeout=60000)
    return _mt5_conn


def _mt5_tail_supported(our_key, tf):
    """Можно ли отдавать хвост этого символа/ТФ из брокера.

    Условие НЕ сводится к «инструмент есть у брокера»: для D1/W1 хвост ложится
    на статику, набранную publish_charts из price_bars, и склеивать два фида в
    одном ряду нельзя. Внутридневка у брокера есть для всех CHART_BROKER_MAP;
    дневки/недельки — только там, где статика тоже брокерская
    (mt5_config.bars_from_broker(), там же замеры расхождения).

    🔴 Для инструментов КАТАЛОГА оговорка про D1/W1 не действует, и это не
    послабление, а следствие: склеивать нечего. Ограничение существует потому,
    что у 31 символа реестра дневки/недельки уже опубликованы статикой из
    price_bars, и хвост из другого фида поверх неё давал бы «две цены сразу»
    (шип 20.08). У символа каталога статики нет вовсе — весь ряд приходит
    одним источником, из моста, и смешивать его не с чем.
    """
    from mt5_config import CHART_BROKER_MAP, bars_from_broker
    if tf not in _MT5_TF_ATTR:
        return False
    dead = _mt5_dead_feed.get((our_key, tf))
    if dead and time.time() - dead < _MT5_DEAD_TTL:
        # Фид этого символа мёртв — отвечаем «брокер его не умеет», и
        # обработчик честно уходит на Yahoo вместо пустого графика.
        return False
    if not CHART_BROKER_MAP.get(our_key):
        # Каталожный символ: спрашиваем УЖЕ СОБРАННУЮ метку котировки, а не
        # мост. Инвентарь 26.08: из 842 инструментов каталога 773 живые, 61
        # заморожен (делистинг — #TWITTER, #SVBFINANCIAL, USDRUB, VIX…), 8 без
        # котировки вовсе. По каждому из 69 мёртвых иначе уходил бы напрасный
        # вызов в мост на каждый первый запрос.
        age = _broker_quote_ages().get(our_key)
        if age is None or age > _FROZEN_SEC:
            return False
    if CHART_BROKER_MAP.get(our_key):
        if tf in ("D1", "W1"):
            return our_key in bars_from_broker()
        return True
    return our_key in _broker_catalog_symbols()


def _mt5_broker_symbol(our_key):
    """Имя инструмента у брокера. Для реестра — через карту (GOLD -> XAUUSD),
    для каталога ключ И ЕСТЬ имя брокера (#3M, _BMW.DE): каталог снят с самого
    терминала, переводить нечего."""
    from mt5_config import CHART_BROKER_MAP
    bs = CHART_BROKER_MAP.get(our_key)
    if bs:
        return bs
    return our_key if our_key in _broker_catalog_symbols() else None


_econ_ru: tuple = (0.0, {})


def _econ_ru_dict() -> dict:
    """Словарь русских названий макропоказателей. Файл, а не код.

    В календаре 683 разных индикатора и 1208 заголовков — руками все не
    перевести и не нужно: полсотни самых частых закрывают подавляющую часть
    событий, доходящих до графика. Остальное показывается по-английски, и это
    честнее выдуманного перевода: «Kansas Fed Composite Index» в вольном
    пересказе читатель не сопоставит ни с чем.
    """
    global _econ_ru
    path = Path(DIRECTORY).parent / "data" / "econ_indicator_ru.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if _econ_ru[0] == mtime:
        return _econ_ru[1]
    try:
        _econ_ru = (mtime, json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return _econ_ru[1]
    return _econ_ru[1]


def _econ_title_ru(indicator, title, country) -> str | None:
    """«Retail Sales MoM (November)» → «Розничные продажи, месяц к месяцу ·
    США · ноябрь». None — перевода нет, показываем оригинал."""
    d = _econ_ru_dict()
    if not d:
        return None
    key = (indicator or "").strip().lower()
    base = d.get(key)
    if not base:
        # Один и тот же показатель приходит в разных написаниях: «PPI MoM»,
        # «PPI m/m», «PPI MoM Prel». Держать в словаре все варианты — значит
        # обречь его на вечное отставание от источника. Приводим к общему виду:
        # разделители к «mom/yoy/qoq», предварительные и финальные пометки прочь.
        norm = re.sub(r"\bm\s*/\s*m\b", "mom", key)
        norm = re.sub(r"\by\s*/\s*y\b", "yoy", norm)
        norm = re.sub(r"\bq\s*/\s*q\b", "qoq", norm)
        norm = re.sub(r"\b(prel|preliminary|final|flash|adv|advance|revised)\b", "", norm)
        norm = re.sub(r"\s+", " ", norm).strip()
        base = d.get(norm)
    if not base:
        return None
    parts = [base]
    cn = (d.get("_countries") or {}).get((country or "").upper())
    if cn:
        parts.append(cn)
    # Период берём из скобок исходного заголовка: «PCE (November)». Своей
    # колонки под него нет, а выбрасывать жалко — без месяца непонятно, к
    # какому периоду относится цифра.
    m = re.search(r"\(([^)]+)\)\s*$", title or "")
    if m:
        raw = m.group(1).strip().lower()
        parts.append((d.get("_months") or {}).get(raw, m.group(1).strip()))
    return " · ".join(parts)


_ctrader_map: tuple = (0.0, {})


def _ctrader_symbols() -> dict:
    """Карта инструментов, переведённых на cTrader. Файл, не база.

    Собирается tools/ctrader_build_map.py и дальше только читается: соответствие
    имён — решение, принятое один раз и записанное, а не догадка в момент
    показа страницы. Тихого фолбэка «возьмём имя как есть» здесь нет намеренно —
    он однажды подставил бы фонду #XRP график монеты XRP.
    """
    global _ctrader_map
    path = Path(DIRECTORY).parent / "data" / "ctrader_map.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if _ctrader_map[0] == mtime:
        return _ctrader_map[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _ctrader_map[1]
    _ctrader_map = (mtime, data)
    return data


def _ctrader_tail(our_key, tf):
    """Свечи инструментов, переведённых на cTrader. None — не наш случай.

    🔴 В брокера отсюда НЕ ходим. Наполнением занимается отдельный процесс
    ctrader_pull.py, здесь только чтение с диска. Причина та же, по которой мы
    уходили от MT5: сетевой вызов внутри обработчика веб-запроса связывает
    живучесть сайта с живучестью чужого соединения. Пуллер упал — витрина
    продолжает отдавать последние свечи, а не гаснет.

    Возвращает ([], True), если инструмент наш, но кэш пуст: вызывающий должен
    сказать об этом словами, а не свалиться на MT5 — иначе на графике окажется
    ряд другого брокера, склеенный с нашим (семейство бага 20.08).
    """
    if our_key not in _ctrader_symbols():
        return None
    bars, _stale = candle_cache.get(our_key, tf)
    return bars or []


_geo_places_cache: tuple = (0.0, {})


def _geo_places() -> dict:
    """{код страны: {lon, lat, city}} из data/geo_places.json.

    Координаты держит платформа, а не сайт: у сайта был свой список из
    двадцати четырёх столиц, и при расхождении одна и та же страна оказалась
    бы в разных точках на карте и на глобусе.
    """
    global _geo_places_cache
    path = Path(DIRECTORY).parent / "data" / "geo_places.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return _geo_places_cache[1]
    if _geo_places_cache[0] == mtime and _geo_places_cache[1]:
        return _geo_places_cache[1]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _geo_places_cache[1]
    out = {}
    for code, meta in raw.items():
        if code.startswith("_") or not isinstance(meta, dict):
            continue
        try:
            out[code] = {"lon": float(meta["lon"]), "lat": float(meta["lat"]),
                         "city": meta.get("город", code)}
        except (KeyError, ValueError):
            continue
    if out:
        _geo_places_cache = (mtime, out)
    return out


_board_meta_cache: tuple = (0.0, {})
_BOARD_META_TTL = 60


def _board_display_name(broker_symbol: str, name: str | None) -> str:
    """Человеческое имя для доски.

    У валют и сырья в каталоге лежит нормальное название («Евро / доллар»,
    «Золото»), а у акций — биржевой тикер: `#NETFLIX` подписан как «NFLX»,
    `_COMMERZBANK.DE` как «CBK». На доске, куда человек попадает с первого
    экрана, три буквы не говорят ничего. Само имя инструмента при этом
    читаемо — берём его.
    """
    s = broker_symbol
    if s.startswith(("#", "_")):
        base = s.lstrip("#_")
        base = re.sub(r"\.(DE|UK|IT|FR|ES|NL|BE|PT|AT|FI|CH|SE|NO|DK|IE|PL)$", "", base)
        base = base.replace("_", " ").strip()
        if base:
            # JP_MORGAN -> Jp Morgan; оставляем короткие аббревиатуры как есть
            return base if len(base) <= 3 else base.capitalize()
    return name or s


def _board_symbol_meta() -> dict:
    """{имя из счётчика упоминаний: как показать его на доске}.

    Собирает три вещи в одном месте, потому что доске нужны все три сразу:
    под каким именем открывать график, как назвать по-человечески и какая
    сейчас цена. Источник — broker_symbols (там и цена, и изменение, и
    каноническое имя) плюс список доступных графиков.

    Ключ схлопывания — каноническое имя: WTI и CrudeOIL, NG и NATURAL_GAS,
    XRP и XRPUSD это один актив под двумя именами.
    """
    global _board_meta_cache
    now = time.time()
    if now - _board_meta_cache[0] < _BOARD_META_TTL and _board_meta_cache[1]:
        return _board_meta_cache[1]

    blocked = set(_blocked_symbols())
    try:
        avail = json.loads((Path(DIRECTORY) / "data" / "chart_available.json")
                           .read_text(encoding="utf-8"))["items"]
    except Exception:
        avail = {}

    out: dict = {}
    try:
        con = sqlite3.connect(f"file:{_BOT_DB}?mode=ro", uri=True, timeout=10)
        con.execute("PRAGMA busy_timeout=10000")
        try:
            rows = con.execute(
                "SELECT broker_symbol, canonical, display_name, bid, chg_pct "
                "FROM broker_symbols").fetchall()
        finally:
            con.close()
    except Exception:
        return _board_meta_cache[1]

    for bs, canon, name, bid, chg in rows:
        if bs in blocked or (canon and canon in blocked):
            continue
        if not (avail.get(bs) or {}).get("ok"):
            continue
        key = canon or bs
        rec = {"key": key, "name": _board_display_name(bs, name), "price": bid,
               "chg": round(chg, 2) if chg is not None else None,
               # Короткая форма для мелких кругов на телефоне: у акций в
               # каталоге display_name — это биржевой тикер (NFLX, HOOD), и
               # он влезает туда, где «NETFLIX» обрезается на середине.
               # У валют и сырья короткого имени нет — там и так EURUSD, GOLD.
               "ticker": (name or "").strip() if bs.startswith(("#", "_")) else None}
        out[bs] = rec
        if canon:
            out[canon] = rec
    if out:
        _board_meta_cache = (now, out)
    return out


def _board_category_fill(cat: str) -> list:
    """Инструменты направления, о которых сегодня не писали, — в порядке каталога.

    Нужны, чтобы в выбранном направлении всегда было не меньше десяти кругов.
    Счётчик упоминаний знает только тех, кого хоть раз упомянули за неделю; по
    крипте это восемь инструментов из четырнадцати доступных. Остальные шесть
    от этого не перестают отслеживаться — просто про них молчат, и честнее
    показать их нулём, чем сделать вид, что мы следим за восемью.

    Порядок каталога брокера — не случайный: там сверху мажоры. Сортировать
    нечем (упоминаний ноль у всех), а стабильный порядок важнее — доска не
    должна перетасовываться при каждом обновлении.
    """
    meta = _board_symbol_meta()
    out, seen = [], set()
    try:
        raw = json.loads((WEB_DIR / "data" / "broker_catalog.json").read_text(encoding="utf-8"))
        items = raw.get("items", raw) if isinstance(raw, dict) else raw
    except Exception:
        return out
    for it in items:
        our_cat = _BOARD_CATEGORY_OF.get(it.get("category"))
        if our_cat != cat:
            continue
        m = meta.get(it["symbol"])
        if not m or m["key"] in seen:
            continue
        seen.add(m["key"])
        out.append({"symbol": m["key"], "name": m["name"], "category": cat,
                    "mentions": 0, "burst": 0.0, "price": m["price"],
                    "chg": m["chg"], "ticker": m.get("ticker")})
    return out


# Категория каталога → направление на доске. Тот же словарь, что в pulse_job:
# держать два разных значило бы получить инструмент в одном направлении в
# счётчике и в другом на витрине.
_BOARD_CATEGORY_OF = {
    "crypto": "crypto", "stock": "stocks", "index": "indices",
    "fx": "fx", "commodity": "commodity", "etf": "stocks", "bond": "indices",
}


_blocklist_cache: tuple = (0.0, {})


def _blocked_symbols() -> dict:
    """Инструменты, скрытые с витрины сознательно (data/instrument_blocklist.json).

    Список инструментов уже не показывает их — он читает chart_available.json,
    где они помечены отказом. Но прямая ссылка `?s=SHIBUSD` открывала бы график
    как ни в чём не бывало: такие ссылки живут в закладках, в телеграме и в
    поисковой выдаче. Решение «мы это не показываем» должно соблюдаться на
    сервере, а не только в отрисовке списка.
    """
    global _blocklist_cache
    path = Path(DIRECTORY).parent / "data" / "instrument_blocklist.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if _blocklist_cache[0] == mtime:
        return _blocklist_cache[1]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        data = {k: v for k, v in raw.items()
                if not k.startswith("_") and isinstance(v, dict)}
    except Exception:
        return _blocklist_cache[1]
    _blocklist_cache = (mtime, data)
    return data


_crypto_map: tuple = (0.0, {})


def _crypto_symbols() -> dict:
    """Карта инструмент → пары на биржах (data/crypto_map.json).

    Файл, а не код, и заполняется руками: тихого фолбэка «возьмём имя как
    есть» здесь нет намеренно — он однажды подставил бы фонду #XRP график
    монеты XRP. Ровно та же причина, что у карты cTrader выше.
    """
    global _crypto_map
    path = Path(DIRECTORY).parent / "data" / "crypto_map.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if _crypto_map[0] == mtime:
        return _crypto_map[1]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        data = {k: v for k, v in raw.items()
                if not k.startswith("_") and isinstance(v, dict)}
    except Exception:
        return _crypto_map[1]
    _crypto_map = (mtime, data)
    return data


def _crypto_tail(our_key, tf):
    """Свечи с криптобиржи. None — инструмент не наш случай.

    В биржу отсюда не ходим: наполняет crypto_pull.py, здесь только чтение с
    диска. Причина та же, что у cTrader и MT5 — сетевой вызов внутри
    обработчика веб-запроса связывает живучесть сайта с чужим соединением.
    """
    if our_key not in _crypto_symbols():
        return None
    bars, _stale = candle_cache.get(our_key, tf)
    return bars or None


def _mt5_tail(our_key, tf):
    """Свечи из брокера в реальном времени. None -> Yahoo-фолбэк."""
    global _mt5_conn
    bs = _mt5_broker_symbol(our_key)
    if not bs or not _mt5_tail_supported(our_key, tf):
        return None
    now = time.time()
    ck = (our_key, tf)
    # M1 — короткий кэш (8с): бар минутный, текущую минуту надо показывать быстро,
    # иначе график «отстаёт на минуту». Выборка из моста дешёвая (~0.17с).
    ttl = 8 if tf == "M1" else _MT5_TAIL_TTL
    c = _mt5_tail_cache.get(ck)
    if c and now - c[0] < ttl:
        return c[1]

    # ── Диск: свечи, взятые у брокера раньше ────────────────────────────────
    # 🔴 Читаем ДО захвата _mt5_lock. Замок последователен (мост однопоточен), и
    # если встать в очередь за ним, второй посетитель ждёт чужой поход в
    # терминал — 1.5-3.4 с на холодном инструменте. Свежая копия на диске
    # снимает вопрос за миллисекунды, не касаясь ни замка, ни моста.
    disk, disk_stale = candle_cache.get(our_key, tf)
    if disk and not disk_stale:
        _mt5_tail_cache[ck] = (now, disk)
        return disk

    # 🔴 Замок с таймаутом, а не безусловное ожидание. Раньше запрос вставал в
    # очередь к мосту насмерть, а сервер однопоточный — один посетитель,
    # ждущий свой график, останавливал сайт для всех. Теперь: не дождались за
    # секунду — отдаём устаревшую копию (она честно помечена возрастом
    # последней свечи), а мост оставляем тому, кто его уже занял.
    if not _mt5_lock.acquire(timeout=1.0):
        return disk or None
    try:
        c = _mt5_tail_cache.get(ck)
        if c and now - c[0] < ttl:
            return c[1]
        data = None
        # Две попытки: sbf-mt5-pull в конце прогона вызывает mt5.shutdown() на ОБЩЕМ
        # серверном модуле — после каждого прогона первая выборка иначе падала и
        # отдавала Yahoo (а Yahoo M1 у FX плоский, o=h=l=c). Переинициализируем на
        # каждой выборке (initialize() идемпотентен) и при обрыве соединения
        # сбрасываем его и пробуем ещё раз.
        for _attempt in (1, 2):
            try:
                import rpyc
                conn = _mt5_bridge()
                mt5 = conn.modules["MetaTrader5"]
                mt5.initialize(path=_MT5_PATH, timeout=60000)
                if not mt5.symbol_select(bs, True):
                    return disk or None
                tfc = getattr(mt5, _MT5_TF_ATTR[tf])
                rates = mt5.copy_rates_from_pos(bs, tfc, 0, _MT5_COUNT.get(tf, 300))
                if rates is None or len(rates) == 0:
                    return disk or None
                data = rpyc.classic.obtain(rates)
                break
            except Exception:
                _mt5_conn = None  # сбросить и попробовать заново
                data = None
        if data is None:
            # 🔴 Мост не ответил — отдаём копию с диска, а не пустоту.
            # Пустой ответ фронт рисует белым полем без единого слова, и это
            # ровно то, что читается как «график сломан». Устаревший ряд честен:
            # delay_sec считается от последней свечи, страница показывает
            # «данные от …». Молчание моста — не повод терять данные.
            return disk or None
        candles = [{"time": int(x["time"]),
                    "open": round(float(x["open"]), 5), "high": round(float(x["high"]), 5),
                    "low": round(float(x["low"]), 5), "close": round(float(x["close"]), 5)}
                   for x in data]
        # 🔴 Мёртвый фид брокера НЕ выдаём: пусть лучше сработает Yahoo.
        #
        # Поймано 26.08 при открытии каталога ярусу 3. У USDRUB символ в
        # каталоге есть, copy_rates_from_pos() честно отдаёт 3000 баров — вот
        # только последний из них от 17 марта: брокер перестал его котировать
        # и с тех пор просто хранит старое. До расширения на каталог USDRUB
        # сюда не попадал и уходил на Yahoo со свежими часовыми барами;
        # молча подменить их пятимесячной заморозкой было бы ухудшением.
        #
        # Неделя — порог, который не задевает ни выходные (макс ~60 ч), ни
        # праздники, ни закрытые биржи: столько подряд не стоит ни один живой
        # рынок. Возврат None роняет запрос в Yahoo-ветку обработчика.
        if candles and (time.time() - candles[-1]["time"]) > 7 * 86400:
            _mt5_dead_feed[ck] = now
            _mt5_tail_cache[ck] = (now, None)
            candle_cache.drop(our_key, tf)
            return None
        _mt5_dead_feed.pop(ck, None)
        _mt5_tail_cache[ck] = (now, candles)
        candle_cache.put(our_key, tf, candles)
        return candles
    finally:
        _mt5_lock.release()


def _chart_symbols() -> set:
    """Инструменты, которые умеет рисовать ДЕТАЛЬНЫЙ график.

    SBF_Charts_Layer4_Spec, Фаза 1.3: валидация ватчлиста ДОЛЖНА идти против
    этого списка, не journal_brief.get_available_symbols() (тот читает
    price_bars — другой, гораздо более узкий и по-другому именованный набор:
    XAUUSD вместо GOLD, нет крипты/индексов/commodities вовсе — не тот домен).

    SPEC_chart_all_instruments §5: раньше список был глобом по
    web/data/ohlc_*_D1.json — то есть инструмент существовал ровно постольку,
    поскольку для него заранее опубликовали файлы по каждому ТФ. На каталоге
    брокера (842 символа x 6 ТФ) это пять тысяч файлов, которых не будет
    никогда. Источник — реестр; множество то же самое, проверено сверкой:
    глоб и реестр дают одни и те же 31, разницы ноль в обе стороны.

    🔴 Это НЕ каталог брокера. Здесь — ИМЕНОВАННЫЕ инструменты реестра: у них
    есть человеческое название, переводы и заранее опубликованная статика
    ohlc_*.json. Их и предлагает выпадающий список ватчлиста
    (/api/chart/symbols): вывалить туда 842 сырых тикера вроде #3M значило бы
    сломать выбор ради полноты.

    Множество «что вообще можно нарисовать» — шире, см. _chartable_symbols()."""
    from core.symbols_registry import _load as _load_symbol_registry
    return {k for k, v in _load_symbol_registry().items()
            if isinstance(v, dict) and v.get("chart")}
_BOT_DB  = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

_catalog_cache: tuple = (0.0, set())
_CATALOG_TTL = 300


def _broker_catalog_symbols() -> set:
    """Тикеры каталога брокера (broker_symbols, ~842). Кэш на 5 минут: состав
    каталога меняется раз в недели, а спрашивают его на каждый запрос графика."""
    global _catalog_cache
    now = time.time()
    if now - _catalog_cache[0] < _CATALOG_TTL and _catalog_cache[1]:
        return _catalog_cache[1]
    try:
        con = sqlite3.connect(str(_BOT_DB), timeout=10)
        con.execute("PRAGMA busy_timeout=10000")
        try:
            syms = {s for (s,) in con.execute("SELECT broker_symbol FROM broker_symbols")}
        finally:
            con.close()
    except Exception:
        # Пустой ответ = «не знаю», а не «пусто»: отдать старый кэш честнее,
        # чем молча сузить платформу до реестра из-за занятой на секунду базы.
        return _catalog_cache[1]
    if syms:
        _catalog_cache = (now, syms)
    return _catalog_cache[1]


_alias_cache: tuple = (0.0, {})


def _canonical_alias_map() -> dict:
    """{каноническое имя → тикер брокера}, например LINK → LINKUSD.

    🔴 Зачем это вообще нужно. В каталоге у 18 инструментов имя брокера и
    каноническое имя расходятся: `LINKUSD` / `LINK`, `US_500` / `SPX`,
    `CrudeOIL` / `WTI`. Список инструментов на графике строит ссылку по
    КАНОНИЧЕСКОМУ имени (`data-go = canonical || symbol`), а свечи лежат под
    именем брокера. Для десяти из восемнадцати перевод был прописан руками в
    `CHART_BROKER_MAP` — SPX, DJI, BTC, WTI открывались. Для остальных
    восьми (XLM, LTC, XRP, LINK, UNI, DOGE, SHIB, MATIC, PEPE) его не было, и
    страница честно отвечала «по этому инструменту данных нет», хотя те же
    свечи прекрасно отдавались по `?s=LINKUSD`.

    Проверка доступности этого не ловила: `chart_available.json` заполнялся по
    именам брокера, а ломались ссылки по каноническим — то есть мерили одно
    имя, а кликали по другому.

    Карта строится из самого каталога, а не пишется руками: новый инструмент с
    расходящимися именами начнёт работать сам.
    """
    global _alias_cache
    now = time.time()
    if now - _alias_cache[0] < _CATALOG_TTL and _alias_cache[1]:
        return _alias_cache[1]
    try:
        raw = json.loads((WEB_DIR / "data" / "broker_catalog.json").read_text(encoding="utf-8"))
        items = raw.get("items", raw) if isinstance(raw, dict) else raw
        m = {}
        for it in items:
            canon, sym = it.get("canonical"), it.get("symbol")
            if canon and sym and canon != sym:
                m[canon] = sym
    except Exception:
        return _alias_cache[1]
    if m:
        _alias_cache = (now, m)
    return _alias_cache[1]


_LEVELS_LIMIT = 12
# Полосы поиска вокруг текущей цены, от узкой к широкой. Берём первую, в
# которой набирается достаточно уровней.
_LEVEL_BANDS = (0.08, 0.15, 0.30, 0.60)


def _levels_near_price(items: list, price) -> list:
    """Топ-12 уровней рядом с ценой, а не топ-12 за всю историю.

    🔴 Score = touches × log(age+1) — и ни слова о том, где цена сейчас. На
    инструменте в тренде это выдаёт уровни из другой ценовой эпохи: у GOLD при
    цене 4430 все двенадцать уровней лежали в 1302–1956, у ITALY_40 при 52 215
    — в 27 880–35 030. График честно их рисовал, просто за пределами экрана, и
    слой «Уровни» выглядел пустым. Замер 07.09 — на обоих инструментах ни
    одной линии в видимой области.

    Формула не менялась: старый уровень с многими касаниями действительно
    ценнее свежего и случайного. Изменился отбор кандидатов — сначала берём те,
    до которых цене есть дело, и уже среди них ранжируем.

    Полоса расширяется, пока не наберётся достаточно уровней: у спокойного
    инструмента хватит ±8%, у волатильного — нет, и жёсткий порог оставил бы
    его вовсе без слоя. Если не набралось и в самой широкой — отдаём топ по
    старой логике: показать далёкие уровни лучше, чем не показать ничего.
    """
    if not price or price <= 0:
        return items[:_LEVELS_LIMIT]
    for band in _LEVEL_BANDS:
        lo, hi = price * (1 - band), price * (1 + band)
        near = [it for it in items if lo <= it["price"] <= hi]
        if len(near) >= _LEVELS_LIMIT:
            return near[:_LEVELS_LIMIT]
    near = [it for it in items
            if price * (1 - _LEVEL_BANDS[-1]) <= it["price"] <= price * (1 + _LEVEL_BANDS[-1])]
    return near[:_LEVELS_LIMIT] if near else items[:_LEVELS_LIMIT]


def _resolve_chart_symbol(symbol: str) -> str:
    """Имя, под которым инструмент реально лежит у брокера.

    Порядок важен: сначала пробуем имя как есть (для реестра оно рабочее и
    переведено через CHART_BROKER_MAP), и только если брокер такого не знает —
    смотрим карту канонических имён, а потом journal-домен. Иначе можно
    сломать те, что уже работали.

    🔴 Третья ветка про journal-домен добавлена 08.09 по живому вопросу «почему
    по золоту нет данных» со ссылкой `?s=XAUUSD`. У золота три имени: `GOLD` в
    каталоге и на графике, `XAUUSD` в дневнике сделок и у брокера, `GC=F` в
    ленте котировок. Ссылка с `XAUUSD` приходила из дневника и из внешних
    материалов — и отдавала пустой график, хотя те же свечи прекрасно
    открывались по `?s=GOLD`.
    """
    if not symbol:
        return symbol
    from mt5_config import CHART_BROKER_MAP
    if symbol in CHART_BROKER_MAP or symbol in _broker_catalog_symbols():
        return symbol
    alias = _canonical_alias_map().get(symbol)
    if alias:
        return alias
    try:
        from core.journal_symbols import to_chart_symbol
        chart = to_chart_symbol(symbol)
        if chart:
            return chart
    except Exception:
        pass
    return symbol


def _canonical_link_name(symbol: str) -> str:
    """Одно имя инструмента для ссылки — то, что видно в адресе страницы.

    Не то же самое, что _resolve_chart_symbol: там мы ищем имя, под которым
    лежат свечи (LINK → LINKUSD), а здесь — имя, под которым инструмент
    показывается человеку и попадает в ссылку (LINKUSD → LINK, XAUUSD → GOLD).

    Зачем вообще: у одного актива до трёх имён, и каждое открывало свою
    страницу. Один и тот же график расходился по разным адресам в закладках,
    в переписке и в поисковой выдаче — а для поисковика это ещё и две страницы
    с одинаковым содержимым.
    """
    if not symbol:
        return symbol
    s = symbol.upper().strip()
    # journal-домен → домен графика (XAUUSD → GOLD)
    try:
        from core.journal_symbols import to_chart_symbol
        chart = to_chart_symbol(s)
        if chart:
            s = chart
    except Exception:
        pass
    # имя брокера → каноническое имя каталога (LINKUSD → LINK)
    for canon, broker in _canonical_alias_map().items():
        if broker == s:
            return canon
    return s


def _broker_quote_ages() -> dict:
    """{тикер: возраст его котировки в секундах} из broker_symbols.

    Данные уже собраны — broker_catalog_loop пишет туда снимок каждые 15 с.
    Спрашивать у моста то, что лежит в базе, незачем: замер 26.08 показал,
    что обход каталога через мост (842 вызова) насыщает его настолько, что
    график перестаёт отвечать вовсе. Тот же ответ отсюда стоит один SELECT."""
    global _quote_ts_cache
    now = time.time()
    if now - _quote_ts_cache[0] < _QUOTE_TS_TTL and _quote_ts_cache[1]:
        return _quote_ts_cache[1]
    try:
        con = sqlite3.connect(str(_BOT_DB), timeout=10)
        con.execute("PRAGMA busy_timeout=10000")
        try:
            ages = {s: (now - ts if ts else None)
                    for s, ts in con.execute(
                        "SELECT broker_symbol, quote_ts FROM broker_symbols")}
        finally:
            con.close()
    except Exception:
        return _quote_ts_cache[1]
    if ages:
        _quote_ts_cache = (now, ages)
    return _quote_ts_cache[1]


def _chartable_symbols() -> set:
    """Всё, что платформа умеет нарисовать: именованный реестр ПЛЮС весь
    каталог брокера.

    Ярус 3 из SPEC_chart_all_instruments §4 — «детальный график по клику; для
    инструментов, которых нет у Yahoo, из MT5 по запросу с кэшем». До 26.08
    здесь было только 31 имя реестра, и клик по любой из остальных 811 строк
    левой панели упирался в пустой график: котировка в списке есть, свечей
    взять неоткуда.

    Замер 26.08, по одному символу каждой категории (H1, 3000 баров): акции
    1.06 с, ETF 1.35, индексы 1.23, крипта 1.18, FX 0.73, облигации 0.60,
    сырьё 0.01. Бары есть у ВСЕХ категорий каталога.

    🔴 Почему это не повторяет аварию 25.08. Тогда сайт лёг из-за фонового
    ОБХОДА каталога (спарклайны: сотни вызовов подряд насытили мост, а сервер
    однопоточный). Здесь обхода нет вовсе: один открытый график — один вызов
    с кэшем на 20 с, ровно та же стоимость, что у нынешних 31 инструмента.
    Массовой заливки каталога в price_bars тоже нет и не предполагается: 842
    символа x 6 ТФ — это ~84 минуты на проход при часовом такте и ~30 млн
    строк, то есть возврат к той же нагрузке, что мост уже не выдержал."""
    return _chart_symbols() | _broker_catalog_symbols()

_COUNTRY_SYM = {
    "US": "EURUSD", "EU": "EURUSD", "EA": "EURUSD",
    "GB": "GBPUSD", "JP": "USDJPY", "CN": "USDCNY",
    "RU": "USDRUB", "ZA": "USDZAR", "AE": "USDAED", "KZ": "USDKZT",
}

_COUNTRY_CURRENCY = {
    "US": "USD", "EU": "EUR", "EA": "EUR", "GB": "GBP", "JP": "JPY",
    "CN": "CNY", "RU": "RUB", "ZA": "ZAR", "AE": "AED", "KZ": "KZT",
    "CA": "CAD", "AU": "AUD", "NZ": "NZD", "CH": "CHF",
}

def _ensure_schema() -> None:
    """Обёртка: досоздание схемы не имеет права уронить веб-сервер.

    🔴 01.09 сайт лежал четыре минуты именно здесь. Цикл анализа держал запись
    в bot.db, sbf-web стоял на executescript, порт никто не слушал, туннель
    отдавал 502 — а юнит числился active. Ожидание чужой транзакции не должно
    решать, работает ли сайт: страницы, графики и кэш свечей от bot.db не
    зависят вовсе, а таблицы, которые тут создаются, к этому моменту почти
    всегда уже существуют.
    """
    try:
        _ensure_schema_inner()
    except Exception as e:
        print(f"схема bot.db недоступна ({e}) — поднимаюсь без неё", flush=True)


def _ensure_schema_inner() -> None:
    """Создаёт новые таблицы БД Фазы 1 если не существуют.

    🔴 busy_timeout обязателен. bot.db пишут соседние джобы (доливка баров,
    снимок каталога брокера), и без ожидания ЛЮБАЯ их запись в момент старта
    роняет весь веб-сервер: 25.08 sbf-web.service упал на этой строке с
    "database is locked", когда каталог инструментов писал свои 842 строки.
    Сервис поднялся рестартом, но падать веб-серверу из-за чужой транзакции
    незачем — тот же приём уже применён в outliers_job и доливке баров."""
    # 🔴 Ждать — но не бесконечно, и не ценой самого сайта.
    #
    # Ожидание в 60 секунд оказалось недостаточным: 01.09 цикл анализа
    # (analyze.run_cycle --profile h4) держал запись в bot.db больше четырёх
    # минут, sbf-web стоял на этой строке, порт 8085 никто не слушал, туннель
    # отдавал 502 — сайт лежал целиком. Юнит при этом числился active: снаружи
    # «работает», для посетителя пусто. Тот же класс отказа, который мы ловим
    # в этом проекте третью неделю.
    #
    # Схема здесь только ДОСОЗДАЁТСЯ (всё CREATE IF NOT EXISTS). Если её сейчас
    # не создать — почти всегда потому, что она уже есть, а база занята чужой
    # транзакцией. Это не повод не поднимать сайт: страницы, графики и кэш
    # свечей от bot.db не зависят вовсе.
    try:
        con = sqlite3.connect(str(_BOT_DB), timeout=15)
        con.execute("PRAGMA busy_timeout=15000")
    except Exception as e:
        print(f"схема bot.db недоступна ({e}) — поднимаюсь без неё", flush=True)
        return
    con.executescript("""
        CREATE TABLE IF NOT EXISTS price_bars (
            symbol TEXT NOT NULL, tf TEXT NOT NULL, ts INTEGER NOT NULL,
            o REAL, h REAL, l REAL, c REAL, v REAL,
            PRIMARY KEY(symbol, tf, ts)
        );
        CREATE TABLE IF NOT EXISTS symbol_map (
            our_key TEXT PRIMARY KEY, twelvedata TEXT, mt5 TEXT, yahoo TEXT
        );
        -- 🔴 Исправлено 06.08.2026: было actual/forecast/previous REAL.
        -- Ровно эта же таблица в этой же bot.db объявляется в calendar_pull.py:255
        -- с типом TEXT. Кто первым выполнил CREATE TABLE IF NOT EXISTS, того
        -- и типы — то есть аффинность зависела от порядка запуска процессов.
        -- Верен TEXT: значения приходят строками вида "199k", "$62.396B", "5.1%",
        -- "−0.4%" и в число не приводятся. При REAL-аффинности SQLite сохранял бы
        -- "5.1" как число, а "199k" как текст — в одной колонке вперемешку,
        -- что ломает сравнение и сортировку.
        -- ВНИМАНИЕ: если таблица уже создана с REAL, этот DDL её не изменит —
        -- нужна разовая миграция (ALTER/пересоздание). Проверить фактическую
        -- схему: PRAGMA table_info(econ_event_history).
        CREATE TABLE IF NOT EXISTS econ_event_history (
            event_key TEXT NOT NULL, ts INTEGER NOT NULL,
            actual TEXT, forecast TEXT, previous TEXT, unit TEXT,
            PRIMARY KEY(event_key, ts)
        );
        CREATE TABLE IF NOT EXISTS event_reactions (
            event_key TEXT NOT NULL, symbol TEXT NOT NULL,
            release_ts INTEGER NOT NULL, window TEXT NOT NULL,
            pips REAL, true_range REAL, dir TEXT, close_dir TEXT,
            PRIMARY KEY(event_key, symbol, release_ts, window)
        );
        CREATE TABLE IF NOT EXISTS event_instrument_map (
            country TEXT NOT NULL, symbol TEXT NOT NULL, weight INT NOT NULL,
            PRIMARY KEY(country, symbol)
        );
        CREATE TABLE IF NOT EXISTS event_reaction_stats (
            event_type TEXT NOT NULL, symbol TEXT NOT NULL, n INT NOT NULL,
            avg_move_30m REAL, avg_move_60m REAL, max_move_60m REAL,
            volatile_share REAL, computed_ts INT,
            median_move_30m REAL, median_atr_30m REAL,
            PRIMARY KEY(event_type, symbol, n)
        );
    """)
    # SPEC_morning_brief_v2.md блок 1 ("в прошлые разы") хочет медиану,
    # нормированную на дневной ATR14 -- avg_move_30m/60m остаются как были
    # (сырые пункты, среднее), эти две колонки добавлены отдельно, не заменяют.
    # SPEC_календарь_и_движения_рынка.md §3: нормировка хода на медианный ход
    # ТОГО ЖЕ ЧАСА СУТОК (без событий, hourly_profile.json), не только на ATR14 —
    # без этого 38 пипс в 15:30 UTC и 38 пипс в 03:00 UTC читаются как одно и то
    # же, хотя это обычный час против аномалии. Плюс период выборки (§4: любая
    # публикуемая метрика обязана показывать n И период) и 4-часовое окно —
    # тот же горизонт, что у контрольных цифр Recognia (§0), для сверки.
    # WP1.4 SPEC_alpha_engine_implementation.md: раньше здесь и в
    # event_reactions_job.py._migrate() было по независимой копии этого же
    # списка -- уже успели разойтись (там не было двух первых колонок).
    # core.db_migrations — общий источник, версионированный, идемпотентный.
    from core.db_migrations import apply_all as _apply_migrations
    _apply_migrations(con)
    con.executemany(
        "INSERT OR IGNORE INTO symbol_map(our_key, twelvedata, mt5, yahoo) VALUES(?,?,?,?)",
        [
            ("EURUSD", "EUR/USD", "EURUSD",  "EURUSD=X"),
            ("GBPUSD", "GBP/USD", "GBPUSD",  "GBPUSD=X"),
            ("USDJPY", "USD/JPY", "USDJPY",  "JPY=X"),
            ("XAUUSD", "XAU/USD", "XAUUSD",  "GC=F"),
            ("USDRUB", "USD/RUB", "USDRUB",  "RUB=X"),
            ("USDCNY", "USD/CNY", "USDCNY",  "CNY=X"),
            ("USDAED", "USD/AED", "USDAED",  "AED=X"),
            ("USDZAR", "USD/ZAR", "USDZAR",  "ZAR=X"),
            ("USDKZT", "USD/KZT", "USDKZT",  "KZT=X"),
        ],
    )
    # event→instrument веса: 2 = прямое влияние (валюта — плечо пары),
    # 1 = косвенное (риск-сентимент/сырьё/индексы/крипта реагируют на USD и т.п.)
    con.executemany(
        "INSERT OR IGNORE INTO event_instrument_map(country, symbol, weight) VALUES(?,?,?)",
        [
            ("US", "EURUSD", 2), ("US", "GBPUSD", 2), ("US", "USDJPY", 2), ("US", "DXY", 2),
            ("US", "GOLD", 1), ("US", "SILVER", 1), ("US", "SPX", 1), ("US", "NASDAQ", 1),
            ("US", "DJI", 1), ("US", "VIX", 1), ("US", "BTC", 1), ("US", "ETH", 1),
            ("US", "SOL", 1), ("US", "WTI", 1),
            ("EU", "EURUSD", 2), ("EU", "DXY", 1),
            ("EA", "EURUSD", 2), ("EA", "DXY", 1),
            ("GB", "GBPUSD", 2),
            ("JP", "USDJPY", 2),
            ("CN", "GOLD", 1), ("CN", "WTI", 1), ("CN", "SPX", 1),
        ],
    )
    # Досоздание схемы не должно ронять сервер: если база занята чужой
    # транзакцией, поднимаемся без неё — таблицы почти наверняка уже есть.
    try:
        con.commit()
    except Exception as e:
        print(f"схема bot.db не записана ({e}) — продолжаю", flush=True)
    finally:
        con.close()

# ── Jinja2 ──────────────────────────────────────────────────────────────────
def _url_for(endpoint, **values):
    if endpoint == "static":
        return "/assets/" + values.get("filename", "")
    return "/"

# SPEC_site_fixes_2026-07-29 §4: единая иконка сайта. Раньше пять разных
# состояний по файлам -- index.html относительный ./assets/favicon.svg
# (ломался на /ro/, /en/: разрешался в /ro/assets/favicon.svg, которого нет),
# 16 глав книги через url_for('static', filename='favicon.png') (после
# рендера -- /assets/favicon.png, другой формат), пара страниц вовсе без
# иконки. Нормализуем ЗДЕСЬ, один раз, по факту отрисованного HTML -- иначе
# следующая новая страница снова разъедется (спека прямо предлагает вынести
# в общий фрагмент). rel="apple-touch-icon" убирается перед вставкой блока,
# если уже стоял отдельно (journal.html) -- иначе дубль.
_FAVICON_BLOCK = (
    '<link rel="icon" type="image/svg+xml" href="/assets/favicon.svg">\n'
    '<link rel="alternate icon" type="image/png" href="/assets/favicon.png">\n'
    '<link rel="apple-touch-icon" href="/assets/icons/icon-192.png">'
)
_FAVICON_ICON_RE = re.compile(r'<link[^>]*\brel="icon"[^>]*>')
_FAVICON_APPLE_RE = re.compile(r'\s*<link[^>]*\brel="apple-touch-icon"[^>]*>')


def _normalize_favicon(html: str) -> str:
    if not _FAVICON_ICON_RE.search(html):
        return html  # страницы вовсе без <link rel="icon"> чинятся отдельно, не здесь
    html = _FAVICON_APPLE_RE.sub("", html, count=1)
    html = _FAVICON_ICON_RE.sub(_FAVICON_BLOCK, html, count=1)
    return html

_jinja = Environment(loader=FileSystemLoader(str(BOOK_DIR)), autoescape=False)
_jinja.globals["url_for"] = _url_for

# Отдельное окружение для обычных страниц сайта (не глав курса) -- шаблоны
# лежат прямо в web/ (это те же .html, что раньше отдавались как статика;
# конвертация в Jinja добавляет только {{ t(...) }} и {% ... %}, разметка
# не переезжает в отдельную templates/ директорию). autoescape=True здесь
# (в отличие от _jinja выше) -- это обычный HTML с пользовательским вводом
# в некоторых местах (email в формах и т.п.), книжный движок исторически
# жил без экранирования, но новый код это ни от чего не освобождает.
_site_jinja = Environment(loader=FileSystemLoader(str(WEB_DIR)), autoescape=True)
_site_jinja.globals["t"] = i18n.t
_site_jinja.globals["symbol_name"] = _symbols.symbol_name


def _tojson_filter(value) -> Markup:
    """Обычная jinja2.Environment (в отличие от Flask) не регистрирует tojson
    сама -- нужен для безопасной подстановки переведённых строк внутрь <script>
    как JS-литералов (напр. {{ t('key', lang) | tojson }}). json.dumps() как
    filter НЕЛЬЗЯ регистрировать напрямую: при autoescape=True Jinja экранирует
    его результат как обычный текст (" -> &#34;), а HTML-entities внутри
    <script> браузер не декодирует -- получился бы синтаксически битый JS.
    Оборачиваем в Markup (уже безопасно для вставки как есть) и вдобавок
    экранируем </script>-подобные последовательности и &, чтобы переведённая
    строка не могла преждевременно закрыть тег или пробить HTML."""
    raw = json.dumps(value, ensure_ascii=False)
    raw = raw.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return Markup(raw)


_site_jinja.filters["tojson"] = _tojson_filter

_EDU_RE     = re.compile(r'^/edu(?:/(?P<lang>ro|en))?/b(?:/(?P<ch>\d+))?(?:\?.*)?$')
_EDU_TOC_RE = re.compile(r'^/edu/?(?:\?.*)?$')

_EDU_LIVE = {
    1: "^GSPC", 2: "^GSPC", 3: "GC=F",      4: "^GSPC",    5: "EURUSD=X",
    6: "^VIX",  7: "^GSPC", 8: "^GSPC",     9: "GC=F",     10: "^GSPC",
    11: "^NDX", 12: "EURUSD=X",13: "GC=F",  14: "EURUSD=X",15: "^GSPC",
}
_EDU_LIVE_LABEL = {
    1: "S&P 500", 2: "S&P 500", 3: "Золото",  4: "S&P 500",  5: "EUR/USD",
    6: "VIX",     7: "S&P 500", 8: "S&P 500", 9: "Золото",  10: "S&P 500",
    11: "Nasdaq", 12: "EUR/USD",13: "Золото", 14: "EUR/USD", 15: "S&P 500",
}
# Ключи для /chart.html (наши, не Yahoo-формат)
_EDU_CHART_KEY = {
    1: "SPX",    2: "SPX",    3: "GOLD",   4: "SPX",    5: "EURUSD",
    6: "VIX",    7: "SPX",    8: "SPX",    9: "GOLD",   10: "SPX",
    11: "NASDAQ",12: "EURUSD",13: "GOLD",  14: "EURUSD",15: "SPX",
}

# ── Серверная компиляция JSX ─────────────────────────────────────────────────
_MARKET_INTEL_DIR = str(Path(__file__).parent.resolve())
_BABEL_REQUIRE = _MARKET_INTEL_DIR + "/node_modules/@babel/standalone"
_BABEL_COMPILE_JS = (
    "const Babel = require('" + _BABEL_REQUIRE + "');\n"
    "const chunks = [];\n"
    "process.stdin.on('data', d => chunks.push(d));\n"
    "process.stdin.on('end', () => {\n"
    "  const code = Buffer.concat(chunks).toString('utf8');\n"
    "  try {\n"
    "    const r = Babel.transform(code, {presets: [['react', {runtime: 'classic'}]]});\n"
    "    process.stdout.write(r.code);\n"
    "  } catch(e) {\n"
    "    process.stderr.write('JSX_ERROR: ' + e.message);\n"
    "    process.exit(1);\n"
    "  }\n"
    "});\n"
)

_COMPILED: dict[int, str] = {}  # ch → compiled JS (lang-neutral)

_BABEL_SCRIPT_RE = re.compile(
    r'<script\s+type=["\']text/babel["\'][^>]*>([\s\S]*?)</script>',
    re.IGNORECASE
)
_CDN_REACT    = re.compile(r'<script[^>]+unpkg\.com/react@[^>]+></script>')
_CDN_REACTDOM = re.compile(r'<script[^>]+unpkg\.com/react-dom@[^>]+></script>')
_CDN_BABEL    = re.compile(r'<script[^>]+unpkg\.com/@babel[^>]+></script>')

LOCAL_REACT    = '<script src="/book/vendor/react.min.js"></script>'
LOCAL_REACTDOM = '<script src="/book/vendor/react-dom.min.js"></script>'


def _compile_jsx(jsx_code: str) -> str | None:
    """Компилирует JSX в чистый JS через Node.js + @babel/standalone."""
    try:
        result = subprocess.run(
            ["node", "-e", _BABEL_COMPILE_JS],
            input=jsx_code.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout.decode("utf-8")
        print(f"Babel error: {result.stderr.decode()[:200]}")
    except Exception as e:
        print(f"JSX compile exception: {e}")
    return None


def _precompile_all() -> None:
    """Компилируем все 15 глав при старте сервера (один раз)."""
    print("Компиляция JSX глав...", flush=True)
    for ch in range(1, 16):
        tpl = f"edu_book_{ch}.html"
        try:
            raw = _jinja.get_template(tpl).render(lang="ru")
            m = _BABEL_SCRIPT_RE.search(raw)
            if not m:
                print(f"  Глава {ch}: нет babel-скрипта")
                continue
            jsx = m.group(1)
            # Нейтрализуем lang — при отдаче подставим нужный
            jsx_neutral = jsx.replace('const INITIAL_LANG = "ru";', 'const INITIAL_LANG = "__LANG__";')
            compiled = _compile_jsx(jsx_neutral)
            if compiled:
                _COMPILED[ch] = compiled
                print(f"  Глава {ch}: OK ({len(compiled)} chars)")
            else:
                print(f"  Глава {ch}: ошибка компиляции")
        except Exception as e:
            print(f"  Глава {ch}: {e}")
    print(f"Готово: {len(_COMPILED)}/15 глав скомпилированы", flush=True)


def _edu_inject(ch: int, lang: str = i18n.DEFAULT_LANG) -> str:
    """Генерирует HTML инжекции для главы: nav, прогресс-бар, дисклеймер, live."""
    # Ссылки между главами должны сохранять текущий язык, иначе "Далее"/
    # "Назад"/"Содержание" всегда уводят на русскую версию -- баг, из-за
    # которого переход на новую страницу в ro/en "сбрасывал" в ru. Главы
    # используют свою схему /edu/{lang}/b/N (см. _EDU_RE), а TOC-страница --
    # общий префикс /{lang}/edu/ (см. i18n.lang_from_path в serve.py; /edu/*
    # исключён из общего механизма, у книги своя схема, но сама TOC-страница
    # index.html не является главой и живёт по общей /{lang}/-схеме).
    _book_lang_seg = f"{lang}/" if lang in ("ro", "en") else ""
    _toc_href = f"/{lang}/edu/" if lang != i18n.DEFAULT_LANG else "/edu/"
    prev_href  = f"/edu/{_book_lang_seg}b/{ch - 1}" if ch > 1  else _toc_href
    next_href  = f"/edu/{_book_lang_seg}b/{ch + 1}" if ch < 15 else _toc_href
    prev_label = i18n.t("edu.chapter_n", lang, n=ch - 1) if ch > 1  else i18n.t("edu.toc", lang)
    next_label = i18n.t("edu.chapter_n", lang, n=ch + 1) if ch < 15 else i18n.t("edu.toc", lang)
    ticker     = _EDU_LIVE.get(ch, "^GSPC")
    live_label = _EDU_LIVE_LABEL.get(ch, "Live")
    chart_key  = _EDU_CHART_KEY.get(ch, "SPX")
    _WIDGET_MAP = {3: "risk-calc", 5: "session-clock", 10: "pattern-gallery"}
    _CTA_MAP = {
        3:  (i18n.t("edu.cta.3", lang), "/grafik#chart/dbot"),
        10: (i18n.t("edu.cta.10", lang), "/grafik#chart/hns"),
        13: (i18n.t("edu.cta.13", lang), "/grafik#chart/hns"),
        14: (i18n.t("edu.cta.14", lang), "/grafik#candle/bullEngulf"),
    }
    widget_html = (
        f'<div style="max-width:780px;margin:0 auto;padding:0 24px">'
        f'<div data-sbf-widget="{_WIDGET_MAP[ch]}"></div></div>'
    ) if ch in _WIDGET_MAP else ""
    if ch in _CTA_MAP:
        _cta_label, _cta_href = _CTA_MAP[ch]
        cta_html = (
            f'<div class="sbf-cta"><a href="{_cta_href}" target="_blank">'
            f'{_cta_label} →</a></div>'
        )
    else:
        cta_html = ""

    # ── Sbf-fig блоки (grafik-engine.js) — один источник правды для графики ──
    # ch 9 и 10 имеют отдельные JSX-правки; здесь только остальные главы
    _FIG_MAP: dict[int, list[tuple[str, str, str]]] = {
        1:  [("candle","doji",i18n.t("edu.fig.1.1", lang)),
             ("candle","hammer",i18n.t("edu.fig.1.2", lang))],
        2:  [("ind","atr",i18n.t("edu.fig.2.1", lang))],
        3:  [("chart","dbot",i18n.t("edu.fig.3.1", lang))],
        4:  [("smc","sweep",i18n.t("edu.fig.4.1", lang)),
             ("smc","ob",i18n.t("edu.fig.4.2", lang))],
        6:  [("ind","bb",i18n.t("edu.fig.6.1", lang)),
             ("ind","atr",i18n.t("edu.fig.6.2", lang))],
        7:  [("smc","fvg",i18n.t("edu.fig.7.1", lang)),
             ("smc","ob",i18n.t("edu.fig.7.2", lang)),
             ("smc","sweep",i18n.t("edu.fig.7.3", lang))],
        8:  [("smc","structure",i18n.t("edu.fig.8.1", lang)),
             ("smc","bos",i18n.t("edu.fig.8.2", lang)),
             ("ind","ma",i18n.t("edu.fig.8.3", lang))],
        11: [("ind","volume",i18n.t("edu.fig.11.1", lang))],
        12: [("ind","ichimoku",i18n.t("edu.fig.12.1", lang))],
        13: [("chart","hns",i18n.t("edu.fig.13.1", lang)),
             ("chart","dtop",i18n.t("edu.fig.13.2", lang)),
             ("chart","flag",i18n.t("edu.fig.13.3", lang)),
             ("ind","fib",i18n.t("edu.fig.13.4", lang))],
        14: [("candle","hammer",i18n.t("edu.fig.14.1", lang)),
             ("candle","bullEngulf",i18n.t("edu.fig.14.2", lang)),
             ("candle","bearEngulf",i18n.t("edu.fig.14.3", lang)),
             ("ind","ma",i18n.t("edu.fig.14.4", lang)),
             ("ind","bb",i18n.t("edu.fig.14.5", lang))],
        15: [("chart","hns",i18n.t("edu.fig.15.1", lang)),
             ("chart","dtop",i18n.t("edu.fig.15.2", lang)),
             ("ind","rsi",i18n.t("edu.fig.15.3", lang))],
    }
    # Тех-карточки (sbfTechCard) — учебные примеры уровней (не сигналы)
    _LVL = {
        "entry":       i18n.t("edu.lvl.entry", lang),
        "stop":        i18n.t("edu.lvl.stop", lang),
        "target":      i18n.t("edu.lvl.target", lang),
        "neckline":    i18n.t("edu.lvl.neckline", lang),
        "target_h":    i18n.t("edu.lvl.target_h", lang),
        "order_block": i18n.t("edu.lvl.order_block", lang),
        "fvg_target":  i18n.t("edu.lvl.fvg_target", lang),
    }
    # sym — «Название · ТИКЕР» из общего реестра (SPEC_symbol_names.md §3), не
    # разрозненные литералы по главам: раньше главы 3/7/14 писали "человеческий"
    # формат руками (EUR/USD, XAU/USD), а глава 13 — сырые US500/BTCUSD.
    _eurusd = _symbols.symbol_name("EURUSD", lang=lang, mode="name+ticker")
    _xauusd = _symbols.symbol_name("GOLD", lang=lang, mode="name+ticker")
    _gbpusd = _symbols.symbol_name("GBPUSD", lang=lang, mode="name+ticker")
    _us500 = _symbols.symbol_name("SPX", lang=lang, mode="name+ticker")
    _btcusd = _symbols.symbol_name("BTC", lang=lang, mode="name+ticker")
    _TCARD_MAP: dict[int, str] = {
        3: (
            f"sbfTechCard({{sym:'{_eurusd} · D1',bias:'bull',"
            f"levels:[['{_LVL['entry']}','1.0850'],['{_LVL['stop']}','1.0790'],['{_LVL['target']}','1.0980']],"
            f"note:'{i18n.t('edu.tcard.n1', lang)}'}}) +"
            f"sbfTechCard({{sym:'{_xauusd} · H4',bias:'bear',"
            f"levels:[['{_LVL['entry']}','2020'],['{_LVL['stop']}','2045'],['{_LVL['target']}','1970']],"
            f"note:'{i18n.t('edu.tcard.n2', lang)}'}})"
        ),
        7: (
            f"sbfTechCard({{sym:'{_gbpusd} · H1',bias:'bull',"
            f"levels:[['{_LVL['order_block']}','1.2640'],['{_LVL['entry']}','1.2660'],['{_LVL['stop']}','1.2610'],['{_LVL['fvg_target']}','1.2750']],"
            f"note:'{i18n.t('edu.tcard.n3', lang)}'}})"
        ),
        13: (
            f"sbfTechCard({{sym:'{_us500} · D1',bias:'bear',"
            f"levels:[['{_LVL['neckline']}','5180'],['{_LVL['target_h']}','5040']],"
            f"note:'{i18n.t('edu.tcard.n4', lang)}'}}) +"
            f"sbfTechCard({{sym:'{_btcusd} · H4',bias:'bear',"
            f"levels:[['{_LVL['neckline']}','61 200'],['{_LVL['target_h']}','58 400']],"
            f"note:'{i18n.t('edu.tcard.n5', lang)}'}})"
        ),
        14: (
            f"sbfTechCard({{sym:'{_eurusd} · M5',bias:'bull',"
            f"levels:[['{_LVL['entry']}','1.0902'],['{_LVL['stop']}','1.0893'],['{_LVL['target']}','1.0924']],"
            f"note:'{i18n.t('edu.tcard.n6', lang)}'}})"
        ),
    }
    if ch in _FIG_MAP:
        # SPEC_charts_and_interactivity_standard.md §2.1 (29.07 re-audit):
        # data-schema-label computed server-side, same as data-caption --
        # edu-embed.js's client-side t() dict loads async and is empty at
        # DOMContentLoaded (window.sbfI18n.ready hasn't resolved yet), so a
        # client-only translation would render the RU fallback on RO/EN
        # pages. Passing it pre-translated sidesteps that race entirely.
        _schema_label = i18n.t("eduindex.embed.schema_label", lang)
        _figs_inner = "".join(
            f'<div class="sbf-fig" data-cat="{cat}" data-key="{key}"'
            f' data-caption="{cap}" data-schema-label="{_schema_label}"></div>\n'
            for cat, key, cap in _FIG_MAP[ch]
        )
        _tcard_js = _TCARD_MAP.get(ch, "")
        _tcard_block = (
            f'<div id="sbf-tch{ch}" class="sbf-tcards"></div>\n'
            f'<script>(function(){{'
            f'var w=document.getElementById("sbf-tch{ch}");'
            f'if(w&&typeof sbfTechCard!=="undefined")w.innerHTML={_tcard_js};'
            f'}})();</script>\n'
        ) if _tcard_js else ""
        figs_html = (
            f'<div style="max-width:780px;margin:0 auto;padding:24px 24px 0">'
            f'<div class="sbf-widget-head">{i18n.t("edu.widgets_head", lang)}</div>'
            f'{_figs_inner}{_tcard_block}</div>'
        )
    else:
        figs_html = ""
    return f"""{widget_html}
{cta_html}
{figs_html}
<div class="edu-progress-bar" id="edu-pb"></div>

<div class="edu-nav">
  <a class="nav-prev" href="{prev_href}">{prev_label}</a>
  <span class="nav-counter">{i18n.t("edu.chapter_counter", lang, ch=ch)}</span>
  <a class="nav-toc" href="{_toc_href}">{i18n.t("edu.toc", lang)}</a>
  <a class="nav-next" href="{next_href}">{next_label}</a>
  <a class="nav-live" id="edu-live-btn" href="/chart.html?s={chart_key}" target="_blank">
    <span id="edu-live-price">{live_label}</span>
  </a>
</div>

<div style="max-width:780px;margin:24px auto 0;padding:0 24px">
  <div style="border:1px solid #E7DFCF;border-radius:10px;padding:16px 20px;background:rgba(201,162,39,.04)">
    <div style="font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#C9A227;margin-bottom:10px">{i18n.t("edu.live_concept_title", lang)}</div>
    <div id="edu-live-widget" style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;font-family:'JetBrains Mono',monospace;font-size:12px">
      <span style="color:#8A8275">{i18n.t("edu.loading", lang)}</span>
    </div>
    <a href="/chart.html?s={chart_key}" target="_blank"
       style="display:inline-flex;align-items:center;gap:6px;margin-top:12px;padding:7px 16px;background:#C9A227;color:#fff;font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;letter-spacing:.5px;text-decoration:none;border-radius:6px">
      {i18n.t("edu.open_in_terminal", lang, live_label=live_label)}
    </a>
  </div>
</div>

<div class="edu-disclaimer">
  <strong>{i18n.t("edu.disclaimer_title", lang)}</strong>
  {i18n.t("edu.disclaimer_body", lang)}
</div>

<script src="/edu/widgets.js"></script>
<script src="/edu/edu-live.js"></script>
<div id="sbf-pro-toast" style="position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:#2B2B33;color:#fff;font-family:'JetBrains Mono',monospace;font-size:12px;padding:10px 20px;border-radius:8px;opacity:0;transition:opacity .3s;pointer-events:none;z-index:9999">{i18n.t("edu.pro_available_later", lang)}</div>
<script>
function sbfNavigate(tool) {{
  var routes = {{grafik:'/grafik',chart:'/grafik','risk-calc':'/grafik'}};
  var href = routes[tool];
  if(href){{ window.location.href=href; return; }}
  var t=document.getElementById('sbf-pro-toast');
  if(t){{t.style.opacity='1';setTimeout(function(){{t.style.opacity='0';}},2800);}}
}}
(function(){{
  var K='sbf_edu_done', C={ch}, TICK='{ticker}';
  function get(){{ try{{return JSON.parse(localStorage.getItem(K)||'[]')}}catch{{return[]}} }}

  // Прогресс-бар + авто-отметка прочитанной главы
  window.addEventListener('scroll', function(){{
    var d=document.documentElement,
        pct=d.scrollTop/(d.scrollHeight-d.clientHeight)*100||0;
    var pb=document.getElementById('edu-pb');
    if(pb) pb.style.width=Math.min(100,pct)+'%';
    if(pct>75){{
      var done=get();
      if(done.indexOf(C)<0){{ done.push(C); localStorage.setItem(K,JSON.stringify(done)); }}
    }}
  }});

  // Live price в кнопке nav + в виджете
  fetch('/data/quotes.json').then(function(r){{return r.json();}}).then(function(d){{
    var q = d && d.quotes && d.quotes[TICK];
    if(!q) return;
    var p = q.price, chg = q.change_pct||0;
    var sign = chg > 0 ? '+' : '';
    var col  = chg > 0 ? '#1e8e5a' : chg < 0 ? '#c0392b' : '#8A8275';
    var priceStr = p.toLocaleString('ru-RU',{{maximumFractionDigits:4}});
    var chgHtml  = '<span style="color:' + col + '">' + sign + chg.toFixed(2) + '%</span>';

    var navEl = document.getElementById('edu-live-price');
    if(navEl) navEl.innerHTML = priceStr + ' ' + chgHtml;

    var widgetEl = document.getElementById('edu-live-widget');
    if(widgetEl){{
      widgetEl.innerHTML =
        '<span style="font-weight:700;color:#2B2B33">' + TICK + '</span>'
        + '<span style="color:#2B2B33">' + priceStr + '</span>'
        + chgHtml
        + '<span style="color:#E7DFCF">│</span>';
    }}
  }}).then(function(){{
    // Добавить RSI из OHLC
    var OHLC_MAP = {{'GC=F':'ohlc_GOLD_D1.json','EURUSD=X':'ohlc_EURUSD_D1.json',
      '^GSPC':'ohlc_SPX_D1.json','^NDX':'ohlc_NASDAQ_D1.json',
      'CL=F':'ohlc_WTI_D1.json','BTC-USD':'ohlc_BTC_D1.json'}};
    var ohlcFile = OHLC_MAP[TICK];
    if(!ohlcFile) return;
    fetch('/data/'+ohlcFile).then(function(r){{return r.json();}}).then(function(o){{
      var rsi = o && o.rsi;
      if(rsi == null) return;
      var zone = rsi>=70?'{i18n.t("edu.rsi_overbought", lang)}':rsi<=30?'{i18n.t("edu.rsi_oversold", lang)}':'{i18n.t("edu.rsi_neutral", lang)}';
      var zCol = rsi>=70?'#c0392b':rsi<=30?'#1e8e5a':'#8A8275';
      var wEl = document.getElementById('edu-live-widget');
      if(wEl){{
        wEl.innerHTML += '<span>RSI(14): <b style="color:'+zCol+'">'+rsi.toFixed(1)+'</b></span>'
          + '<span style="color:'+zCol+';font-size:11px">'+zone+'</span>';
      }}
    }}).catch(function(){{}});
  }}).catch(function(){{}});
}})();
</script>"""


def _build_edu_page(ch: int, lang: str) -> bytes:
    """Рендерим шаблон + вставляем скомпилированный JS + edu-nav инжекции."""
    html = _normalize_favicon(_jinja.get_template(f"edu_book_{ch}.html").render(lang=lang))

    if ch in _COMPILED:
        # Убираем CDN-скрипты и babel-блок
        html = _CDN_REACT.sub(LOCAL_REACT, html)
        html = _CDN_REACTDOM.sub(LOCAL_REACTDOM, html)
        html = _CDN_BABEL.sub("", html)

        compiled_js = _COMPILED[ch].replace('"__LANG__"', f'"{lang}"')
        # ВАЖНО: repl должен быть функцией, а не строкой. re.sub() парсит
        # строковый repl на предмет backreference-последовательностей вида
        # \n/\t/\1 -- и compiled_js (реальный JS с настоящими "\n"-эскейпами
        # внутри строковых литералов) содержит их в изобилии. Со строковым
        # repl каждый такой "\n" молча превращался в НАСТОЯЩИЙ перевод
        # строки внутри JS string-литерала -- невидимая порча компилята,
        # которая обычно не всплывала (движок иногда восстанавливался), но
        # на главе 14 ломала весь <script> целиком (SyntaxError, пустой
        # #sbf-book-root). Функция-repl вставляется как есть, без разбора.
        html = _BABEL_SCRIPT_RE.sub(
            lambda _m: f'<script>\n{compiled_js}\n</script>',
            html,
        )
    else:
        # Fallback: локальные CDN копии + Babel в браузере
        html = html.replace(
            'https://unpkg.com/react@18/umd/react.production.min.js',
            '/book/vendor/react.min.js'
        ).replace(
            'https://unpkg.com/react-dom@18/umd/react-dom.production.min.js',
            '/book/vendor/react-dom.min.js'
        ).replace(
            'https://unpkg.com/@babel/standalone/babel.min.js',
            '/book/vendor/babel.min.js'
        )

    # Инжектируем edu.css + i18n.js + sbf-header.js + движок Графика перед </head>
    # i18n.js должен идти ДО sbf-header.js: без него window.sbfI18n не определён,
    # и sbf-header.js падает на свой fallback-объект {lang:'ru', t:(k,fb)=>fb||k}
    # -- верхний нав (Сегодня/Обучение/Календарь) оставался русским на ЛЮБОЙ
    # главе независимо от lang (баг, существовавший и до английской версии --
    # главы никогда не грузили /assets/i18n.js, только сам sbf-header.js).
    css_tags = (
        '<link rel="stylesheet" href="/assets/design.css?v=20260903b">\n'
        '<link rel="stylesheet" href="/edu/edu.css?v=20260903b">\n'
        '<link rel="stylesheet" href="/assets/sbf-nav.css?v=20260903b">\n'
        '<script src="/assets/i18n.js?v=2" defer></script>\n'
        '<script src="/assets/sbf-symbols.js?v=2"></script>\n'
        '<script src="/assets/sbf-header.js?v=23" defer></script>'
    )
    if '/edu/edu.css?v=20260903b' not in html:
        html = html.replace("</head>", f"{css_tags}\n</head>", 1)
    elif '/assets/sbf-header.js?v=23' not in html:
        html = html.replace("</head>",
            '<link rel="stylesheet" href="/assets/sbf-nav.css?v=20260903b">\n'
            '<script src="/assets/i18n.js?v=2" defer></script>\n'
            '<script src="/assets/sbf-symbols.js?v=2"></script>\n'
            '<script src="/assets/sbf-header.js?v=23" defer></script>\n</head>', 1)

    grafik_tags = (
        '<script src="/edu/assets/grafik-engine.js"></script>\n'
        '<script src="/edu/assets/edu-embed.js"></script>'
    )
    if 'grafik-engine.js' not in html:
        html = html.replace("</head>", f"{grafik_tags}\n</head>", 1)

    # window.sbfAuth (SPEC_academy_level1_interactivity.md, попытки квиза
    # привязываются к реальному user_id, не к общему "default") -- те же
    # тег и версия, что на index.html/journal.html/chart.html, книжные главы
    # раньше вообще не грузили sbf-auth.js.
    # Проверка ИМЕННО на тег <script src="...">, не на голую подстроку
    # "sbf-auth.js" -- та случайно совпадает с текстом обычных code-комментариев
    # (см. markChapterRead-вызовы в главах, комментирующие сам этот механизм),
    # из-за чего инъекция тихо пропускалась на всех 15 главах разом.
    if '<script src="/assets/sbf-auth.js' not in html:
        html = html.replace(
            "</head>", '<script src="/assets/sbf-auth.js?v=1" defer></script>\n</head>', 1)

    # Анонимная личность читателя для прогресса по главам, SPEC_chart_fixes_
    # and_staged_signup.md §5, Этап 0 — БЕЗ defer (главы дёргают markChapterRead
    # синхронно при монтировании, тот же порядок аргументов, что sbf-symbols.js).
    if '<script src="/assets/sbf-anon.js' not in html:
        html = html.replace(
            "</head>", '<script src="/assets/sbf-anon.js"></script>\n</head>', 1)

    # Общий "хром" книги (C/Mono/Chip/Rule/GlossWord/AskAnalystPopup/
    # AskAnalystBtn/getChUrl/QuizBlock/ComplianceFootnote) -- SPEC_academy_
    # chapter3_integration.md §5/§7, три независимые копии уже разошлись
    # практически (не только гипотетически), см. план. НЕ defer: инлайновый
    # <script type="text/babel"> главы (обычный, синхронный, в <body>)
    # деструктурирует window.AcademyShared сразу при выполнении -- если
    # этот тег отложить, глава попытается прочитать AcademyShared раньше,
    # чем он появится.
    # Проверяем именно тег, а не голую подстроку "academy-shared.js" -- главы
    # сами упоминают это имя файла в комментариях, и подстрочная проверка
    # решила бы, что тег "уже есть", и тег так и не добавлялся бы вовсе.
    if '<script src="/assets/academy-shared.js' not in html:
        html = html.replace(
            "</head>", '<script src="/assets/academy-shared.js?v=1"></script>\n</head>', 1)

    # Якоря с возвратом (SPEC_ch2_debug_and_chart_engine.md §5) -- курс-wide,
    # не привязан к конкретной главе (источник и цель ссылки могут быть
    # любыми двумя главами), поэтому грузится так же глобально, как
    # academy-shared.js/sbf-header.js, а не через per-chapter <script>.
    if '<script src="/edu/assets/anchor-return.js' not in html:
        html = html.replace(
            "</head>", '<script src="/edu/assets/anchor-return.js?v=1" defer></script>\n</head>', 1)

    # Переключатель «Просто / Как есть» (SPEC_ch2_debug_and_chart_engine.md
    # §3) -- состояние (localStorage) грузится глобально, чтобы выбор,
    # сделанный на одной главе, был виден на любой другой, даже раньше, чем
    # в ней появятся _simple-блоки; сам переключатель в шапке пока рисует
    # только глава 2 (§3.3: раскатка по главам постепенная, не разом).
    if '<script src="/edu/assets/simple-lang.js' not in html:
        html = html.replace(
            "</head>", '<script src="/edu/assets/simple-lang.js?v=1"></script>\n</head>', 1)

    # Хедер инжектирует sbf-header.js (добавлен через css_tags выше)

    # Инжектируем nav + прогресс + дисклеймер перед </body>
    inject = _edu_inject(ch, lang)
    html = html.replace("</body>", f"{inject}\n</body>", 1)

    return html.encode("utf-8")


# ── Quotes ───────────────────────────────────────────────────────────────────
QUOTES_FILE = Path(__file__).parent / "web" / "data" / "quotes.json"


def fetch_quotes() -> tuple[list[dict], str | None]:
    """SPEC_fix_live_chart.md §3: возвращает ещё и "updated" из quotes.json —
    /api/quotes переиспользует его, чтобы фронт мог определить устаревание
    (§4) не читая напрямую статический файл вторым запросом."""
    try:
        data = json.loads(QUOTES_FILE.read_text(encoding="utf-8"))
        quotes = data.get("quotes", {})
        rows = [
            {"ticker": sym, "name": _symbols.symbol_name(sym, mode="name"),
             "price": q["price"], "change_pct": q.get("change_pct"),
             "delay_sec": q.get("delay_sec")}
            for sym, q in quotes.items() if q.get("price") is not None
        ]
        return rows, data.get("updated")
    except Exception:
        return [], None


# ── HTTP Handler ─────────────────────────────────────────────────────────────
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_PUT(self):
        path_clean = self.path.split("?")[0]
        # /api/user/* — SBF_Charts_Layer4_Spec Фаза 1: строго auth (401 без
        # токена, acceptance спеки), в отличие от /api/journal/* выше, где
        # _current_user_id() исторически подставляет "default" для анонима.
        if path_clean == "/api/user/watchlist":
            self._handle_user_watchlist_put()
            return
        if path_clean == "/api/user/watchlist/pin":
            self._handle_user_watchlist_pin_put()
            return
        if path_clean == "/api/user/chart-prefs":
            self._handle_user_chart_prefs_put()
            return
        if path_clean == "/api/auth/profile":
            self._handle_auth_profile_put()
            return
        if path_clean == "/api/user/trading-window":
            self._handle_user_trading_window_put()
            return
        user_id = self._current_user_id()
        if re.match(r"^/api/journal/setups/\d+$", path_clean):
            setup_id = int(path_clean.split("/")[-1])
            self._handle_setups_update(setup_id, user_id)
        else:
            self._send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        path_clean = self.path.split("?")[0]
        # См. do_GET/do_POST -- та же правка: раньше ни одно из этих удалений
        # не резолвило пользователя вообще, все они молча работали над общим
        # "default" (см. delete_trade и т.п. -- все они уже принимали user_id
        # и фильтровали DELETE ... WHERE id=? AND user_id=?, параметр просто
        # никогда не передавался).
        user_id = self._current_user_id()
        if re.match(r"^/api/journal/trades/\d+$", path_clean):
            trade_id = int(path_clean.split("/")[-1])
            ok = journal_db.delete_trade(trade_id, user_id)
            self._send_json({"ok": ok})
        elif re.match(r"^/api/journal/alerts/rules/\d+$", path_clean):
            rule_id = int(path_clean.split("/")[-1])
            self._send_json({"ok": journal_alerts.delete_rule(rule_id, user_id)})
        elif re.match(r"^/api/journal/alerts/subscriptions/\d+$", path_clean):
            sub_id = int(path_clean.split("/")[-1])
            self._send_json({"ok": journal_alerts.delete_subscription(sub_id, user_id)})
        elif re.match(r"^/api/journal/watchlist/[A-Z0-9]+$", path_clean):
            symbol = path_clean.split("/")[-1]
            ok = journal_brief.remove_from_watchlist(symbol, user_id)
            if ok:
                journal_brief.invalidate_cache()
            self._send_json({"ok": ok})
        elif re.match(r"^/api/journal/setups/\d+$", path_clean):
            setup_id = int(path_clean.split("/")[-1])
            self._send_json({"ok": journal_setups.delete_setup(setup_id, user_id)})
        elif path_clean == "/api/journal/course":
            self._send_json(journal_gamification.reset_course_progress(self._effective_user_id(user_id)))
        elif re.match(r"^/api/journal/checklist/items/\d+$", path_clean):
            item_id = int(path_clean.split("/")[-1])
            self._send_json({"ok": journal_tilt.delete_checklist_item(item_id, user_id)})
        elif re.match(r"^/api/journal/goals/\d+$", path_clean):
            goal_id = int(path_clean.split("/")[-1])
            self._send_json({"ok": journal_goals.delete_goal(goal_id, user_id)})
        elif re.match(r"^/api/account/broker-links/\d+$", path_clean):
            link_id = int(path_clean.split("/")[-1])
            self._send_json({"ok": journal_account.delete_broker_link(link_id, user_id)})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        path_clean = self.path.split("?")[0]
        # См. do_GET -- тот же системный пробел (почти каждая journal_*-ветка
        # ниже писала/читала под "default", а не под реально залогиненного).
        user_id = self._current_user_id()
        if path_clean == "/api/ingest/bars":
            self._handle_ingest_bars()
        elif path_clean == "/api/journal/trades":
            self._handle_journal_add_trade(user_id)
        elif path_clean == "/api/journal/import":
            self._handle_mt_import()
        elif path_clean == "/api/journal/import/csv":
            self._handle_journal_import_csv(user_id)
        elif path_clean == "/api/journal/import/ocr":
            self._handle_journal_import_ocr(user_id)
        elif path_clean == "/api/journal/accounts":
            self._handle_journal_save_account(user_id)
        elif path_clean == "/api/journal/meta":
            self._handle_journal_save_meta()
        elif path_clean == "/api/journal/rules":
            self._handle_journal_start_series(user_id)
        elif path_clean == "/api/journal/tradeplan":
            self._handle_journal_save_tradeplan(user_id)
        elif path_clean == "/api/journal/gate-flag":
            self._handle_journal_set_gate_flag(user_id)
        elif path_clean == "/api/journal/discipline/config":
            self._handle_discipline_save_config(user_id)
        elif path_clean == "/api/journal/discipline/eval":
            self._handle_discipline_save_eval(user_id)
        elif path_clean == "/api/journal/discipline/preset":
            self._handle_discipline_apply_preset(user_id)
        elif path_clean == "/api/journal/alerts/rules":
            self._handle_alerts_add_rule(user_id)
        elif path_clean == "/api/journal/alerts/subscriptions":
            self._handle_alerts_save_subscription()
        elif re.match(r"^/api/journal/alerts/rules/\d+/toggle$", path_clean):
            rule_id = int(path_clean.split("/")[-2])
            self._handle_alerts_toggle_rule(rule_id)
        elif path_clean == "/api/journal/alerts/notifications/mark-delivered":
            self._handle_alerts_mark_delivered()
        elif path_clean == "/api/journal/alerts/check":
            self._handle_alerts_behavioral_check()
        elif path_clean == "/api/journal/watchlist":
            self._handle_brief_add_watchlist(user_id)
        elif path_clean == "/api/journal/setups":
            self._handle_setups_create(user_id)
        elif re.match(r"^/api/journal/setups/\d+/link-trade$", path_clean):
            setup_id = int(path_clean.split("/")[-2])
            self._handle_setups_link_trade(setup_id)
        elif re.match(r"^/api/journal/setups/\d+/status$", path_clean):
            setup_id = int(path_clean.split("/")[-2])
            self._handle_setups_update_status(setup_id)
        elif path_clean == "/api/journal/checklist/items":
            self._handle_checklist_add_item(user_id)
        elif re.match(r"^/api/journal/checklist/items/\d+/toggle$", path_clean):
            item_id = int(path_clean.split("/")[-2])
            self._send_json({"ok": journal_tilt.toggle_checklist_item(item_id, user_id)})
        elif path_clean == "/api/journal/checklist/run":
            self._handle_checklist_run(user_id)
        elif re.match(r"^/api/journal/checklist/runs/\d+/link-trade$", path_clean):
            run_id = int(path_clean.split("/")[-2])
            self._handle_checklist_link_trade(run_id)
        elif path_clean == "/api/journal/tilt/check":
            self._send_json(journal_tilt.run_tilt_check(user_id))
        # ── Part 8: Gamification ──
        elif path_clean == "/api/journal/gamification/xp":
            self._handle_gamification_award_xp(user_id)
        elif path_clean == "/api/journal/flashcards/review":
            self._handle_flashcard_review(user_id)
        elif path_clean == "/api/journal/course/complete":
            self._handle_course_complete(self._effective_user_id(user_id))
        elif path_clean == "/api/academy/quiz-attempt":
            self._handle_academy_quiz_attempt(user_id)
        elif path_clean.startswith("/api/journal/course/") and path_clean.endswith("/complete"):
            chapter_n = int(path_clean.split("/")[-2])
            self._send_json(journal_gamification.complete_chapter(chapter_n, self._effective_user_id(user_id)))
        elif path_clean == "/api/journal/streaks/freeze":
            self._handle_streak_freeze(user_id)
        elif path_clean == "/api/journal/quests/event":
            self._handle_quest_event(user_id)
        elif path_clean == "/api/journal/achievements/check":
            newly = journal_gamification.check_achievements(user_id)
            self._send_json({"newly_unlocked": newly})
        # ── Part 9: Goals & Seasons ──
        elif path_clean == "/api/journal/goals":
            self._handle_goal_create(user_id)
        elif re.match(r"^/api/journal/goals/preset/\w+$", path_clean):
            code = path_clean.split("/")[-1]
            self._send_json(journal_goals.add_goal_from_preset(code, user_id))
        elif path_clean == "/api/journal/seasons/close":
            self._handle_season_close()
        # ── Part 10: Account Hub ──
        elif path_clean == "/api/account/referral/use":
            self._handle_referral_use(user_id)
        elif path_clean == "/api/account/broker-links":
            self._handle_broker_link_add(user_id)
        elif path_clean == "/api/account/delete-request":
            self._send_json(journal_account.request_account_deletion(user_id))
        elif path_clean == "/api/account/delete-cancel":
            self._send_json({"ok": journal_account.cancel_deletion_request(user_id)})
        # ── §0.3 Web Push ──
        elif path_clean == "/api/push/subscribe":
            self._handle_push_subscribe()
        elif path_clean == "/api/push/deliver":
            self._send_json(journal_alerts.deliver_pending_notifications())
        # ── Auth / Onboarding ──
        elif path_clean == "/api/auth/register":
            self._handle_auth_register()
        elif path_clean == "/api/auth/login":
            self._handle_auth_login()
        elif path_clean == "/api/auth/logout":
            self._handle_auth_logout()
        elif path_clean == "/api/auth/onboarding":
            self._handle_auth_onboarding()
        elif path_clean == "/api/auth/register-via-survey":
            self._handle_register_via_survey()
        elif path_clean == "/api/auth/tz":
            self._handle_auth_update_tz()
        elif path_clean == "/api/auth/broker-tz":
            self._handle_auth_broker_tz()
        elif path_clean == "/api/auth/prestige":
            self._handle_auth_prestige()
        # ── Weekly review ──
        elif path_clean == "/api/journal/review":
            self._handle_review_submit()
        # ── Cooldown/Debrief ──
        elif path_clean == "/api/alerts/cooldown":
            self._handle_cooldown_accept()
        elif path_clean == "/api/alerts/cooldown/break":
            self._handle_cooldown_break()
        elif path_clean == "/api/alerts/debrief":
            self._handle_debrief_submit()
        # ── Analytics violations ──
        elif path_clean == "/api/journal/analytics/violations":
            self._handle_log_violation()
        # ── Feedback ──
        elif path_clean == "/api/feedback":
            self._handle_feedback_submit()
        elif path_clean == "/api/feedback/vote":
            self._handle_feedback_vote()
        # ── Admin ──
        elif path_clean == "/api/admin/clusters/merge":
            self._handle_admin_merge_clusters()
        elif path_clean == "/api/admin/clusters/create":
            self._handle_admin_create_cluster()
        elif re.match(r"^/api/admin/cluster/[^/]+/status$", path_clean):
            cid = path_clean.split("/")[4]
            self._handle_admin_set_status(cid)
        elif re.match(r"^/api/admin/cluster/[^/]+/title$", path_clean):
            cid = path_clean.split("/")[4]
            self._handle_admin_set_title(cid)
        elif re.match(r"^/api/admin/feedback/[^/]+/split$", path_clean):
            fid = path_clean.split("/")[4]
            self._handle_admin_split_feedback(fid)
        elif re.match(r"^/api/admin/bootstrap$", path_clean):
            self._handle_admin_bootstrap()
        # ── site_copy ──
        elif re.match(r"^/api/copy/[^/]+/reset$", path_clean):
            cid = path_clean[len("/api/copy/"):-len("/reset")]
            self._handle_copy_reset(cid)
        elif re.match(r"^/api/copy/[^/]+$", path_clean):
            cid = path_clean[len("/api/copy/"):]
            self._handle_copy_upsert(cid)
        else:
            self._send_json({"error": "not found"}, 404)

    def _handle_ingest_bars(self) -> None:
        token_env = os.environ.get("INGEST_TOKEN", "")
        auth = self.headers.get("Authorization", "")
        # Compare token without logging it
        if not token_env or not auth.startswith("Bearer ") or auth[7:] != token_env:
            self._send_json({"error": "unauthorized"}, 401)
            return
        length = int(self.headers.get("Content-Length", 0))
        if length > 20_000_000:
            self._send_json({"error": "payload too large"}, 413)
            return
        try:
            body = json.loads(self.rfile.read(length))
            bars = body.get("bars", [])
        except Exception:
            self._send_json({"error": "invalid JSON"}, 400)
            return
        if not isinstance(bars, list):
            self._send_json({"error": "bars must be a list"}, 400)
            return
        if len(bars) > 50000:
            self._send_json({"error": "batch exceeds 50 000 bars"}, 400)
            return
        required = {"symbol", "tf", "ts", "o", "h", "l", "c"}
        for b in bars:
            if not required.issubset(b.keys()):
                self._send_json({"error": "missing required fields in bar record"}, 400)
                return
        try:
            rows = [{"symbol": b["symbol"], "tf": b["tf"], "ts": int(b["ts"]),
                     "o": float(b["o"]), "h": float(b["h"]),
                     "l": float(b["l"]), "c": float(b["c"]),
                     "v": float(b.get("v") or 0)} for b in bars]
            con = sqlite3.connect(str(_BOT_DB))
            con.executemany(
                "INSERT OR REPLACE INTO price_bars(symbol,tf,ts,o,h,l,c,v)"
                " VALUES(:symbol,:tf,:ts,:o,:h,:l,:c,:v)",
                rows,
            )
            con.commit()
            con.close()
            self._send_json({"ok": True, "inserted": len(rows)})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def do_GET(self):
        path_clean = self.path.split("?")[0]
        # /ro/... -> lang='ro', путь без префикса -- единая точка для ВСЕХ
        # страниц кроме /edu/*, у которого уже свой собственный, более старый
        # формат (/edu/ro/b/N, сегмент языка ПОСЛЕ /edu, не перед ним) — не
        # трогаем его парсинг, иначе /ro/edu/b/1 и /edu/ro/b/1 разошлись бы
        # в две разные, путающие друг друга схемы.
        req_lang = i18n.DEFAULT_LANG
        if not path_clean.startswith("/edu"):
            req_lang, path_clean = i18n.lang_from_path(path_clean)
        # Единая точка резолва пользователя для всего GET -- раньше почти каждая
        # journal_*-ветка ниже вызывала функцию без user_id вообще, из-за чего
        # ВСЕ данные (сделки/дисциплина/геймификация/цели/...) читались из общего
        # "default", независимо от того, кто реально залогинен (см. коммит,
        # добавляющий SBFAcademy-мост -- без этой правки мост не был бы виден
        # нигде в самом журнале).
        user_id = self._current_user_id()
        if self.path.startswith("/api/quotes"):
            self._handle_quotes()
        elif path_clean == "/api/journal/trades":
            self._handle_journal_list_trades(user_id)
        elif path_clean == "/api/journal/equity-curve":
            self._send_json(journal_db.equity_curve(user_id))
        elif path_clean == "/api/journal/stats":
            self._send_json(journal_db.get_stats(user_id))
        elif path_clean == "/api/journal/accounts":
            self._send_json(journal_db.list_investor_accounts(user_id))
        elif path_clean == "/api/journal/tradeplan":
            self._send_json(journal_tradeplan.list_plans(user_id))
        elif path_clean == "/api/journal/gate-status":
            self._send_json(journal_gate.get_gate_status(user_id))
        elif path_clean == "/api/journal/behavioral":
            self._send_json(journal_meta.get_behavioral_data(user_id))
        elif path_clean == "/api/journal/series-progress":
            self._send_json(journal_rules.get_series_progress(user_id))
        elif path_clean == "/api/journal/discipline":
            self._send_json(journal_discipline.get_discipline_data(user_id))
        elif path_clean == "/api/journal/discipline/config":
            self._send_json(journal_discipline.get_config(user_id))
        elif path_clean.startswith("/api/journal/discipline/eval/"):
            trade_id = int(path_clean.split("/")[-1])
            self._send_json(journal_discipline.get_trade_eval(trade_id))
        elif path_clean.startswith("/api/journal/meta/"):
            trade_id = int(path_clean.split("/")[-1])
            m = journal_meta.get_meta(trade_id)
            self._send_json(m or {})
        elif path_clean == "/api/journal/alerts/rules":
            self._send_json(journal_alerts.list_rules(user_id))
        elif path_clean == "/api/journal/alerts/subscriptions":
            self._send_json(journal_alerts.list_subscriptions(user_id))
        elif path_clean == "/api/journal/alerts/notifications":
            self._send_json(journal_alerts.get_pending_notifications(user_id))
        elif path_clean == "/api/journal/brief":
            self._send_json(journal_brief.get_brief(user_id))
        elif path_clean == "/api/journal/watchlist":
            self._send_json({
                "watchlist": journal_brief.get_watchlist(user_id),
                "available": journal_brief.get_available_symbols(),
            })
        elif path_clean == "/api/journal/setups":
            params = parse_qs(urlparse(self.path).query)
            self._send_json(journal_setups.list_setups(
                user_id=user_id,
                symbol=params.get("symbol", [None])[0],
                status=params.get("status", [None])[0],
                limit=min(int(params.get("limit", ["50"])[0]), 200),
                offset=int(params.get("offset", ["0"])[0]),
            ))
        elif path_clean == "/api/journal/setups/playbook-stats":
            self._send_json(journal_setups.get_playbook_stats(user_id))
        elif re.match(r"^/api/journal/setups/\d+$", path_clean):
            setup_id = int(path_clean.split("/")[-1])
            setup = journal_setups.get_setup(setup_id, user_id)
            self._send_json(setup or {}, 200 if setup else 404)
        elif path_clean == "/api/journal/checklist":
            recent = journal_tilt.get_recent_run(user_id)
            self._send_json({
                "items": journal_tilt.get_checklist_items(user_id),
                "recent_run": recent,
            })
        elif path_clean == "/api/journal/checklist/last-run":
            self._send_json(journal_tilt.get_recent_run(user_id) or {})
        elif path_clean == "/api/journal/tilt":
            self._send_json(journal_tilt.run_tilt_check(user_id))
        elif path_clean == "/api/journal/tilt/heatmap":
            self._send_json(journal_tilt.get_tilt_heatmap(user_id))
        elif path_clean == "/api/journal/tilt/recent":
            self._send_json(journal_tilt.get_tilt_recent_events(user_id))
        # ── Part 8: Gamification GET ──
        elif path_clean == "/api/journal/gamification":
            self._send_json(journal_gamification.get_overview(user_id))
        elif path_clean == "/api/journal/flashcards":
            params = parse_qs(urlparse(self.path).query)
            mode = params.get("mode", ["due"])[0]
            if mode == "all":
                self._send_json(journal_gamification.get_all_flashcards(user_id))
            elif mode == "quiz":
                self._send_json(journal_gamification.get_quiz_cards(user_id))
            else:
                self._send_json(journal_gamification.get_due_flashcards(user_id))
        elif path_clean == "/api/journal/quests":
            self._send_json(journal_gamification.get_active_quests(user_id))
        elif path_clean == "/api/journal/achievements":
            self._send_json(journal_gamification.get_achievements(user_id))
        elif path_clean == "/api/journal/course":
            self._send_json(journal_gamification.get_course_progress(self._effective_user_id(user_id)))
        elif path_clean == "/api/journal/streaks":
            self._send_json(journal_gamification.get_streaks(user_id))
        elif path_clean == "/api/journal/leaderboard":
            self._send_json(journal_gamification.get_leaderboard(user_id))
        elif path_clean == "/api/journal/cosmetics":
            self._send_json(journal_gamification.get_cosmetics(user_id))
        # ── Part 9: Goals & Seasons ──
        elif path_clean == "/api/journal/goals":
            self._send_json(journal_goals.get_goals_overview(user_id))
        elif path_clean == "/api/journal/seasons":
            self._send_json({
                "active": journal_goals.get_active_season(user_id),
                "past": journal_goals.list_past_seasons(user_id)
            })
        # ── Part 10: Account Hub ──
        elif path_clean == "/api/account":
            self._send_json(journal_account.get_account_overview(user_id))
        elif path_clean == "/api/account/export":
            self._handle_account_export(user_id)
        # ── i18n ──
        elif path_clean == "/api/i18n":
            params = parse_qs(urlparse(self.path).query)
            lang = params.get("lang", [i18n.DEFAULT_LANG])[0]
            self._send_json(i18n.all_dict(lang))
        # ── §0.3 Web Push ──
        elif path_clean == "/api/push/vapid-key":
            self._send_json({"applicationServerKey": journal_alerts.get_vapid_public_key()})
        elif path_clean == "/sw.js":
            self._serve_static(WEB_DIR / "sw.js", content_type="application/javascript")
        elif path_clean == "/manifest.json":
            self._serve_static(WEB_DIR / "manifest.json", content_type="application/manifest+json")
        elif re.match(r"^/assets/icons/icon-\d+\.png$", path_clean):
            fname = path_clean.split("/")[-1]
            self._serve_static(WEB_DIR / "assets" / "icons" / fname, content_type="image/png")
        elif path_clean == "/favicon.ico":
            # §4: маршрута не было вовсе -- core/journal_alerts.py:663 ставит этот
            # путь иконкой пуш-уведомлений по умолчанию, запрос был битым (404).
            # Расширение в URL для Notification API не имеет значения, важен
            # Content-Type -- отдаём тот же PNG, что и alternate icon на страницах.
            self._serve_static(WEB_DIR / "assets" / "favicon.png", content_type="image/png")
        # ── Auth / Onboarding ──
        elif path_clean == "/api/auth/me":
            self._handle_auth_me()
        elif path_clean in ("/unsubscribe", "/api/unsubscribe"):
            self._handle_unsubscribe()
        elif path_clean == "/api/user/watchlist-news":
            self._handle_user_watchlist_news()
        elif path_clean == "/api/auth/my-path":
            self._handle_auth_my_path()
        elif path_clean == "/api/auth/survey-status":
            self._handle_survey_status()
        # ── Import history ──
        elif path_clean == "/api/journal/import/history":
            self._handle_import_history()
        # ── Analytics ──
        elif path_clean == "/api/journal/analytics/discipline-cost":
            self._handle_analytics_discipline_cost()
        elif path_clean == "/api/journal/analytics/setups":
            self._handle_analytics_setups()
        # ── Weekly review ──
        elif path_clean == "/api/journal/review/current":
            self._handle_review_current()
        elif path_clean == "/api/journal/review/history":
            self._handle_review_history()
        # ── Cooldown ──
        elif path_clean == "/api/alerts/cooldown/active":
            self._handle_cooldown_active()
        elif path_clean == "/api/alerts/cooldown/stats":
            self._handle_cooldown_stats()
        elif path_clean == "/api/alerts/debriefs":
            self._handle_debriefs_list()
        elif path_clean == "/":
            self._render_site_page("index.html", req_lang)
        elif path_clean in ("/register", "/register.html"):
            self._render_site_page("register.html", req_lang)
        elif path_clean in ("/login", "/login.html"):
            self._render_site_page("login.html", req_lang)
        elif path_clean in ("/survey", "/survey.html"):
            self._render_site_page("survey.html", req_lang)
        # 27.08.2026: обязательные согласия на /register и /survey ссылались
        # на политику, которой не существовало — register.html вёл на "#",
        # survey.html на /privacy с ответом 404. Человек соглашался с
        # документом, которого нельзя открыть.
        elif path_clean in ("/privacy", "/privacy.html"):
            self._render_site_page("privacy.html", req_lang)
        elif path_clean in ("/brokers", "/brokers.html"):
            self._render_site_page("brokers.html", req_lang)
        elif path_clean in ("/brokers/xm", "/brokers/naga", "/brokers/fxpro", "/brokers/instaforex", "/brokers/avatrade"):
            # Инструкции по брокерам со скриншотами (SPEC_broker_guides_screenshots.md).
            # broker_guide.html не параметризован через Jinja -- guide.js сам
            # берёт id брокера из location.pathname и качает /data/guides/<id>.json,
            # поэтому один и тот же шаблон обслуживает все маршруты без сервер-side
            # переменных. Список литеральный (не regex): маршрут добавляется только
            # когда для брокера реально есть данные в web/data/guides/.
            self._render_site_page("broker_guide.html", req_lang)
        elif path_clean == "/journal":
            self._serve_static(WEB_DIR / "journal.html")
        # ── Legacy /m/* routes → redirect to unified index ──
        elif path_clean.startswith("/m"):
            self.send_response(301)
            self.send_header("Location", "/")
            self.end_headers()
        elif path_clean in ("/glossary", "/glossary.html"):
            self._render_site_page("glossary.html", req_lang)
        # ── /api/lp/* удалены 02.09.2026 ──
        # Четыре обработчика (signals, buzz, patterns, gold-scenarios) исправно
        # отвечали 401 и требовали авторизации, то есть работали. Звал их при
        # этом никто: поиск "api/lp/" по всему web/ (html + js) давал ноль
        # совпадений. Данные они брали из signals.json и buzz.json, которые
        # тоже никто больше не читает.
        # Работающий код без единого вызывающего — не запас, а лишняя
        # поверхность: его надо поддерживать при каждом изменении авторизации
        # и он путает того, кто читает маршруты.
        elif path_clean.startswith("/api/calendar/events"):
            self._handle_calendar_api()
        elif path_clean.startswith("/api/event/"):
            segs = path_clean[len("/api/event/"):].rstrip("/").split("/")
            if len(segs) == 2 and segs[1] == "history":
                self._handle_event_history(segs[0])
            elif len(segs) == 2 and segs[1] == "markers":
                self._handle_event_markers(segs[0])
            # Заглушка /api/event/{key}/reactions → 501 «скоро (Фаза 2)»
            # удалена 02.09.2026: Фаза 2 давно сделана в другом месте. Рабочий
            # маршрут — /api/chart/event-reaction, его зовут chart.html и
            # edu/calendar.html, таблица event_reaction_stats содержит 4092
            # строки. Обещание «скоро» в коде, где функциональность уже год как
            # есть, дезориентирует сильнее, чем честный 404.
            else:
                self._send_json({"error": "not found"}, 404)
        elif path_clean == "/api/price":
            self._handle_price_api()
        elif path_clean == "/api/chart/events":
            self._handle_chart_events()
        elif path_clean == "/api/chart/event-reaction":
            self._handle_chart_event_reaction()
        elif path_clean == "/api/chart/news-bursts":
            self._handle_chart_news_bursts()
        elif path_clean == "/api/chart/news":
            self._handle_chart_news()
        elif path_clean == "/api/geo/feed":
            self._handle_geo_feed()
        elif path_clean == "/api/pulse/board":
            self._handle_pulse_board()
        elif path_clean == "/api/pulse":
            self._handle_pulse()
        elif path_clean == "/api/pulse/feed":
            self._handle_pulse_feed()
        elif path_clean == "/api/chart/levels":
            self._handle_chart_levels()
        elif path_clean == "/api/chart/confluence":
            self._handle_chart_confluence()
        elif path_clean == "/api/chart/patterns":
            self._handle_chart_patterns()
        elif path_clean == "/api/chart/pattern-stats":
            self._handle_chart_pattern_stats()
        elif path_clean == "/api/chart/thermo":
            self._handle_chart_thermo()
        elif path_clean == "/api/chart/thermo-hist":
            self._handle_chart_thermo_hist()
        elif path_clean == "/api/chart/sessions":
            self._handle_chart_sessions()
        elif path_clean == "/api/chart/ohlc-m5":
            self._handle_chart_ohlc_m5()
        elif path_clean == "/api/chart/tail":
            self._handle_chart_tail()
        elif path_clean == "/api/chart/sentiment":
            self._handle_chart_sentiment()
        elif path_clean == "/api/chart/symbols":
            self._send_json(sorted(_chart_symbols()))
        elif path_clean == "/api/chart/smc":
            self._handle_chart_smc()
        elif path_clean == "/api/focus":
            self._handle_focus(user_id)
        elif path_clean == "/api/chart/my-trades":
            self._handle_chart_my_trades()
        elif path_clean == "/api/chart/trade-context":
            self._handle_chart_trade_context()
        elif _EDU_TOC_RE.match(self.path):
            self._handle_edu_toc()
        elif _EDU_RE.match(self.path):
            self._handle_edu()
        elif path_clean == "/grafik":
            self._serve_static(WEB_DIR / "grafik.html")
        elif path_clean == "/edu/glossary":
            self.send_response(301)
            self.send_header("Location", "/glossary")
            self.end_headers()
        elif path_clean in ("/edu/calendar", "/calendar"):
            self._serve_static(EDU_DIR / "calendar.html")
        # ── Admin panel ──
        elif path_clean in ("/admin", "/admin.html"):
            self._serve_static(WEB_DIR / "admin.html")
        elif path_clean == "/api/admin/me":
            self._handle_admin_me()
        elif path_clean == "/api/admin/clusters":
            self._handle_admin_get_clusters()
        elif re.match(r"^/api/admin/cluster/[^/]+$", path_clean):
            cid = path_clean[len("/api/admin/cluster/"):]
            self._handle_admin_get_cluster(cid)
        elif path_clean == "/api/admin/feedback/unassigned":
            self._handle_admin_unassigned()
        # ── site_copy ──
        elif path_clean == "/api/copy/all":
            self._handle_copy_all()
        elif path_clean == "/api/copy/batch":
            self._handle_copy_batch()
        elif re.match(r"^/api/copy/[^/]+$", path_clean):
            cid = path_clean[len("/api/copy/"):]
            self._handle_copy_get(cid)
        # ── Screenshots ──
        elif re.match(r"^/screenshots/[^/]+\.(jpg|png)$", path_clean):
            fname = path_clean[len("/screenshots/"):]
            self._serve_static(
                Path(__file__).parent / "data" / "screenshots" / fname,
                content_type="image/jpeg",
            )
        else:
            if req_lang != i18n.DEFAULT_LANG:
                # Страница ещё не переведена (нет явного Jinja-маршрута выше) --
                # не 404им на /ro/<file>, тихо отдаём русскую версию по
                # каноническому (без префикса) пути.
                query = self.path.split("?", 1)
                self.path = path_clean + ("?" + query[1] if len(query) > 1 else "")
            super().do_GET()

    def _handle_edu_toc(self):
        toc_path = EDU_DIR / "index.html"
        try:
            body = toc_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self._redirect("/edu/b/1")

    def _handle_edu(self):
        m = _EDU_RE.match(self.path)
        if not m:
            self._redirect("/edu/b")
            return
        lang = m.group("lang") or "ru"
        ch = int(m.group("ch") or 1)
        if not (1 <= ch <= 15):
            self._redirect("/edu/b")
            return
        # SPEC_chart_fixes_and_staged_signup.md §5: раньше _handle_edu не
        # проверял вход вообще — все 15 глав были открыты анонимно по прямой
        # ссылке, значки "PRO" на 6-15 чисто косметические. Теперь настоящий
        # серверный гейт (не клиентский, который легко обойти прямой ссылкой).
        # Главы 1-5 остаются бесплатными без проверки.
        if ch >= 6:
            user_id = self._current_user_id()
            if not journal_auth.is_pro(user_id):
                self._send_edu_paywall(ch, lang, logged_in=(user_id != "default"))
                return
        try:
            body = _build_edu_page(ch, lang)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            body = f"<h1>Ошибка</h1><pre>{e}</pre>".encode()
            self.send_response(500)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

    def _send_edu_paywall(self, ch: int, lang: str, logged_in: bool) -> None:
        """Страница-заглушка для PRO-глав (6-15) без действующего PRO.
        Тот же "хром" (шапка/нав/шрифты), что и у обычной главы, чтобы не
        выглядело как ошибка — целенаправленный экран с понятным следующим
        шагом, а не 403 в браузерном стиле."""
        # 27.08.2026: для незалогиненного кнопка вела на /register — форму,
        # которая просит почту с паролем и ничего не обещает взамен. При этом
        # /survey делает ровно то же самое (тот же journal_auth.register), но
        # одним заходом с опросом и сразу выдаёт 30 дней PRO через
        # grant_survey_pro(). Человек, упёршийся в платную главу, — самый
        # горячий посетитель на сайте; отправлять его в форму без обещания
        # было прямой потерей.
        lang_pref = "" if lang == "ru" else f"/{lang}"
        cta_href = f"/edu/{'' if lang == 'ru' else lang + '/'}b/4" if logged_in else f"{lang_pref}/survey"
        cta_label = i18n.t("eduindex.paywall.cta_survey" if logged_in else "eduindex.paywall.cta_register", lang)
        toc_href = "/edu" if lang == "ru" else f"/edu/{lang}/b"
        html = f"""<!doctype html><html lang="{lang}"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{i18n.t('eduindex.paywall.title', lang)}</title>
<link rel="stylesheet" href="/assets/design.css?v=20260903b">
<link rel="stylesheet" href="/edu/edu.css?v=20260903b">
<link rel="stylesheet" href="/assets/sbf-nav.css?v=20260903b">
<script src="/assets/i18n.js?v=2" defer></script>
<script src="/assets/sbf-symbols.js?v=2"></script>
<script src="/assets/sbf-header.js?v=23" defer></script>
<script src="/assets/sbf-auth.js?v=1" defer></script>
<style>
.paywall-wrap{{max-width:560px;margin:80px auto;padding:0 20px;text-align:center}}
.paywall-wrap h1{{font-size:24px;margin-bottom:14px}}
.paywall-wrap p{{color:var(--muted);line-height:1.6;margin-bottom:24px}}
.paywall-wrap a.btn{{display:inline-block;background:var(--gold);color:#18181a;font-weight:700;padding:12px 28px;border-radius:8px;text-decoration:none}}
.paywall-wrap a.btn:hover{{opacity:.9}}
.paywall-wrap .back{{display:block;margin-top:20px;color:var(--muted);text-decoration:underline;font-size:13px}}
</style>
</head><body>
<div class="paywall-wrap">
  <h1>{i18n.t('eduindex.paywall.title', lang)}</h1>
  <p>{i18n.t('eduindex.paywall.body', lang)}</p>
  <a class="btn" href="{cta_href}">{cta_label}</a>
  <a class="back" href="{toc_href}">{i18n.t('eduindex.paywall.back_toc', lang)}</a>
</div>
</body></html>"""
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, path: Path, content_type: str = "text/html; charset=utf-8"):
        try:
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Not found")

    def _render_site_page(self, template_name: str, lang: str = i18n.DEFAULT_LANG) -> None:
        """Рендерит web/<template_name> через _site_jinja с {{ t(key) }}
        доступным внутри. lang прокидывается в шаблон явно (а не только
        через глобальный t, у которого свой параметр по умолчанию) -- сами
        шаблоны используют `{{ t('key', lang) }}`."""
        try:
            tpl = _site_jinja.get_template(template_name)
            html = _normalize_favicon(tpl.render(lang=lang))
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"Template error: {e}".encode("utf-8"))
            return
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def _handle_calendar_api(self):
        from core.calendar_api import query_events
        params  = parse_qs(urlparse(self.path).query)
        date    = params.get("date",    [None])[0]
        from_d  = params.get("from",    [None])[0]
        to_d    = params.get("to",      [None])[0]
        impact  = params.get("impact",  [None])[0]
        country = params.get("country", [None])[0]
        symbols = params.get("symbols", [None])[0]  # Layer4 Ф1.2.2: тумблер «Мои инструменты»
        limit   = params.get("limit",   [None])[0]
        try:
            rows = query_events(
                date=date, from_d=from_d, to_d=to_d, impact=impact,
                country=country, symbols=symbols,
                limit=int(limit) if limit else 2000,
            )
            body = json.dumps(rows, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            body = json.dumps({"error": str(e)}).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    def _send_json(self, data, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _handle_event_history(self, event_key: str) -> None:
        try:
            con = sqlite3.connect(str(_BOT_DB))
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT ts, actual, forecast, previous, unit "
                "FROM econ_event_history WHERE event_key=? ORDER BY ts ASC LIMIT 60",
                (event_key,),
            ).fetchall()
            con.close()
            self._send_json([dict(r) for r in rows])
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_event_markers(self, event_key: str) -> None:
        params = parse_qs(urlparse(self.path).query)
        symbol = params.get("symbol", ["EURUSD"])[0]
        try:
            con = sqlite3.connect(str(_BOT_DB))
            con.row_factory = sqlite3.Row
            # Нормализуем ts события к началу дня UTC для JOIN с price_bars
            rows = con.execute(
                """SELECT h.ts, h.actual, h.forecast, h.unit,
                          b.o, b.h, b.l, b.c
                   FROM econ_event_history h
                   LEFT JOIN price_bars b
                     ON b.symbol = ? AND b.tf = '1d'
                        AND b.ts = (h.ts / 86400 * 86400)
                   WHERE h.event_key = ?
                   ORDER BY h.ts ASC LIMIT 60""",
                (symbol, event_key),
            ).fetchall()
            con.close()
            self._send_json([dict(r) for r in rows])
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_chart_events(self) -> None:
        """Фаза 1: события календаря для оверлея на живом графике chart.html.
        Фильтр по event_instrument_map (weight>=1) + скрываем impact='low' всегда;
        на D1/W1 отдаём только impact='high' (иначе шум, см. SBF_Charts_Layer1_Spec)."""
        params = parse_qs(urlparse(self.path).query)
        symbol = params.get("symbol", [None])[0]
        tf     = params.get("tf", ["D1"])[0]
        if not symbol:
            self._send_json({"error": "symbol required"}, 400)
            return
        try:
            from_ts = int(params.get("from", [None])[0] or (int(time.time()) - 30 * 86400))
            to_ts   = int(params.get("to",   [None])[0] or (int(time.time()) + 14 * 86400))
        except ValueError:
            self._send_json({"error": "invalid from/to"}, 400)
            return
        try:
            con = sqlite3.connect(str(_BOT_DB))
            con.row_factory = sqlite3.Row
            query = """
                SELECT e.id, e.scheduled_ts AS ts, e.title, e.indicator, e.country, e.impact,
                       e.forecast, e.previous, e.actual, m.weight
                FROM econ_events e
                JOIN event_instrument_map m ON m.country = e.country
                WHERE m.symbol = ? AND m.weight >= 1
                  AND e.impact != 'low'
                  AND e.scheduled_ts BETWEEN ? AND ?
            """
            args = [symbol, from_ts, to_ts]
            if tf in ("D1", "W1"):
                query += " AND e.impact = 'high'"
            query += " ORDER BY e.scheduled_ts ASC LIMIT 500"
            rows = [dict(r) for r in con.execute(query, args).fetchall()]
            con.close()
            for r in rows:
                r["importance"] = r.pop("impact")
                r["currency"] = _COUNTRY_CURRENCY.get(r["country"], r["country"])
                # Русское название рядом с исходным, а не вместо него: фронт
                # берёт его только на русской странице, английская остаётся как
                # была. Нет перевода — ключа нет, и фронт покажет оригинал.
                ru = _econ_title_ru(r.get("indicator"), r.get("title"), r.get("country"))
                if ru:
                    r["title_ru"] = ru
                # Для блока "Прошлые разы" (Фаза 2) — фронтенд передаёт это как
                # есть в /api/chart/event-reaction, не дублируя regex-словарь.
                r["event_type"] = normalize_event_type(r.pop("indicator") or r["title"])
            self._send_json(rows)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_chart_event_reaction(self) -> None:
        """Фаза 2: агрегаты статистики реакций из event_reaction_stats
        (считает event_reactions_job.py раз в сутки). Только залогиненным."""
        if not self._lp_require_auth():
            return
        params = parse_qs(urlparse(self.path).query)
        event_type = params.get("event_type", [None])[0]
        symbol = params.get("symbol", [None])[0]
        if not event_type or not symbol:
            self._send_json({"error": "event_type and symbol required"}, 400)
            return
        try:
            con = sqlite3.connect(str(_BOT_DB))
            con.row_factory = sqlite3.Row
            rows = con.execute(
                """SELECT n, avg_move_30m, avg_move_60m, max_move_60m, volatile_share, computed_ts,
                          baseline_ratio_30m, period_from, period_to,
                          n_beat, beat_up_share, beat_down_share, n_miss, miss_up_share, miss_down_share
                   FROM event_reaction_stats WHERE event_type=? AND symbol=? ORDER BY n ASC""",
                (event_type, symbol),
            ).fetchall()
            con.close()
            if not rows:
                self._send_json({"error": "not found"}, 404)
                return
            # n6 = наименьшее доступное n (цель 6), n12 = наибольшее (цель 12).
            # Если истории < 12 публикаций, обе тира могут указывать на одну и ту
            # же строку (n6 и n12 совпадают) — это ожидаемо, не баг.
            smallest, largest = dict(rows[0]), dict(rows[-1])
            self._send_json({"n6": smallest, "n12": largest})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_chart_news_bursts(self) -> None:
        """Фаза 3: зоны новостных всплесков (news_burst_job.py, раз в 15 мин).
        Никогда не рендерятся на D1/W1 (см. SBF_Charts_Layer1_Spec) — сервер
        сам это соблюдает, не полагаясь только на фронтенд."""
        params = parse_qs(urlparse(self.path).query)
        symbol = params.get("symbol", [None])[0]
        tf = params.get("tf", ["D1"])[0]
        if not symbol:
            self._send_json({"error": "symbol required"}, 400)
            return
        if tf in ("D1", "W1"):
            self._send_json([])
            return
        try:
            from_ts = int(params.get("from", [None])[0] or (int(time.time()) - 2 * 86400))
            to_ts   = int(params.get("to",   [None])[0] or int(time.time()))
        except ValueError:
            self._send_json({"error": "invalid from/to"}, 400)
            return
        try:
            con = sqlite3.connect(str(_SIGNALS_DB))
            con.row_factory = sqlite3.Row
            rows = con.execute(
                """SELECT symbol, start_ts, end_ts, count, avg_baseline FROM news_bursts
                   WHERE symbol = ? AND start_ts <= ? AND end_ts >= ?
                   ORDER BY start_ts ASC""",
                (symbol, to_ts, from_ts),
            ).fetchall()
            con.close()
            self._send_json([dict(r) for r in rows])
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_chart_news(self) -> None:
        """Фаза 3: заголовки новостей в окне всплеска (тап по зоне). Отдаём как
        есть из RSS (title+url+источник) — без пересказа, см. compliance спеки."""
        params = parse_qs(urlparse(self.path).query)
        symbol = params.get("symbol", [None])[0]
        if not symbol:
            self._send_json({"error": "symbol required"}, 400)
            return
        try:
            from_ts = int(params.get("from", [None])[0] or (int(time.time()) - 3600))
            to_ts   = int(params.get("to",   [None])[0] or int(time.time()))
        except ValueError:
            self._send_json({"error": "invalid from/to"}, 400)
            return
        try:
            con = sqlite3.connect(str(_SIGNALS_DB))
            con.row_factory = sqlite3.Row
            rows = con.execute(
                """SELECT s.title, s.url, s.topic_hint AS source, s.raw, s.first_seen
                   FROM news_instrument_tags t JOIN signals s ON s.uid = t.news_uid
                   WHERE t.symbol = ?""",
                (symbol,),
            ).fetchall()
            con.close()
            items = []
            for r in rows:
                try:
                    ts = float(json.loads(r["raw"] or "{}").get("published") or 0)
                except (ValueError, TypeError):
                    ts = 0
                if not ts:
                    try:
                        ts = datetime.fromisoformat(r["first_seen"]).timestamp()
                    except (ValueError, TypeError):
                        continue
                if from_ts <= ts <= to_ts:
                    items.append({"title": r["title"], "url": r["url"], "source": r["source"], "ts": int(ts)})
            items.sort(key=lambda x: x["ts"])
            # SPEC_chart_fixes_and_staged_signup.md §4: список без лимита разрастал
            # карточку всплеска новостей за пределы экрана. 20 самых свежих в окне.
            self._send_json(items[-20:])
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_pulse(self) -> None:
        """Фаза 4: топ-8 обсуждаемости по вкладке (pulse_job.py, раз в 15 мин).
        Публично (витрина). Ночью/без активности — фолбэк на топ-8 по
        абсолютным упоминаниям с флагом calm, чтобы вкладка не была пустой."""
        params = parse_qs(urlparse(self.path).query)
        category = params.get("category", [None])[0]
        if category not in ("crypto", "stocks", "indices"):
            self._send_json({"error": "category must be crypto|stocks|indices"}, 400)
            return
        try:
            con = sqlite3.connect(str(_SIGNALS_DB))
            con.row_factory = sqlite3.Row
            latest_ts = con.execute(
                "SELECT MAX(ts) FROM pulse_scores WHERE category=?", (category,)
            ).fetchone()[0]
            if latest_ts is None:
                self._send_json({"category": category, "calm": True, "items": []})
                con.close()
                return
            snapshot = con.execute(
                "SELECT symbol, mentions, baseline, score FROM pulse_scores WHERE category=? AND ts=?",
                (category, latest_ts),
            ).fetchall()
            top_by_score = sorted(snapshot, key=lambda r: r["score"], reverse=True)[:8]
            calm = not top_by_score or top_by_score[0]["score"] <= 0
            chosen = top_by_score if not calm else sorted(snapshot, key=lambda r: r["mentions"], reverse=True)[:8]

            since = latest_ts - 24 * 3600
            items = []
            for r in chosen:
                spark = con.execute(
                    "SELECT score FROM pulse_scores WHERE symbol=? AND category=? AND ts>=? ORDER BY ts ASC",
                    (r["symbol"], category, since),
                ).fetchall()
                items.append({
                    "symbol": r["symbol"], "mentions": r["mentions"],
                    "baseline": round(r["baseline"], 2), "score": round(r["score"], 2),
                    "sparkline": [round(s["score"], 2) for s in spark],
                })
            con.close()
            updated = datetime.fromtimestamp(latest_ts, timezone.utc).isoformat()
            self._send_json({"category": category, "calm": calm, "updated": updated, "items": items})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    # Сколько инструментов каждого направления берём на доску. Сумма 20 —
    # столько пузырей помещается на экран, оставаясь различимыми; при 30 мелкие
    # сливаются в кашу, при 10 доска перестаёт быть картой рынка.
    #
    # Квота одинаковая для всех пяти направлений: с 08.09 доска разбита на
    # группы, и колонка из одного круга рядом с колонкой из шести читается как
    # «здесь данных нет», хотя дело только в разной активности новостного
    # потока. Ровные четыре на каждое направление держат картинку сравнимой.
    _BOARD_QUOTA = {"crypto": 4, "stocks": 4, "indices": 4, "fx": 4, "commodity": 4}
    # Добор до двадцати, если по какому-то направлению сегодня молчат. Потолок
    # на группу не даёт одному направлению занять всю доску.
    _BOARD_GROUP_CAP = 6
    _BOARD_TOTAL = 20

    # Сколько показываем, когда выбрано одно направление. Десять — нижняя
    # граница, заданная владельцем: доска одного направления должна давать
    # картину рынка, а не тройку самых шумных.
    #
    # Верхняя граница — «сколько отслеживаем», а не «сколько поместится».
    # По валютам это 58 пар, по индексам 32, по сырью 19, по крипте 14 — все
    # они и показываются. Потолок в 60 стоит ради акций: их в каталоге 618, и
    # шестьсот кругов это не карта рынка, а серый шум. Шестьдесят —
    # эмпирический предел, за которым подпись перестаёт читаться даже на
    # десктопе (проверено замером радиусов, не на глаз).
    _BOARD_CAT_MIN = 10
    _BOARD_CAT_MAX = 60

    # Сколько отдаём на карту. Больше полусотни точек на глобусе сливаются в
    # кашу, а лента всё равно листается по одной.
    _GEO_LIMIT = 60

    def _handle_geo_feed(self) -> None:
        """Лента для карты и глобуса sbfconsult.com: что и где происходит.

        Два потока в одном формате:
          event — макро-событие календаря. Страна есть в данных, координата
                  берётся по стране, время — время публикации показателя.
          news  — новость с гео-привязкой (news_geo_job). Ставится только
                  когда для места есть основание; крипта и золото сюда не
                  попадают, у них страны нет по природе.

        🔴 Формат намеренно несёт `rule` — на каком основании поставлена точка.
        Карта — это утверждение «здесь произошло вот что», и сайт должен иметь
        возможность показывать только надёжное: до этой ручки тикеры на карте
        расставлялись по первым свободным городам, и Amazon оказывался в
        Гонконге, а Intel во Франкфурте.
        """
        params = parse_qs(urlparse(self.path).query)
        try:
            hours = max(1, min(72, int(params.get("hours", ["24"])[0])))
        except ValueError:
            hours = 24
        kinds = (params.get("kind", ["all"])[0] or "all").lower()
        try:
            limit = max(1, min(self._GEO_LIMIT, int(params.get("limit", ["40"])[0])))
        except ValueError:
            limit = 40

        places = _geo_places()
        items = []
        now = int(time.time())
        since = now - hours * 3600
        try:
            if kinds in ("all", "event"):
                con = sqlite3.connect(f"file:{_BOT_DB}?mode=ro", uri=True, timeout=10)
                con.row_factory = sqlite3.Row
                try:
                    rows = con.execute(
                        """SELECT id, country, title, indicator, impact, scheduled_ts,
                                  actual, forecast, previous
                           FROM econ_events
                           WHERE scheduled_ts BETWEEN ? AND ?
                             AND impact IN ('high','medium')
                           ORDER BY scheduled_ts DESC LIMIT ?""",
                        (since, now + 6 * 3600, limit)).fetchall()
                finally:
                    con.close()
                for r in rows:
                    p = places.get(r["country"])
                    if not p:
                        continue
                    items.append({
                        "kind": "event", "id": f"ev-{r['id']}",
                        # Перевода может не быть — тогда честно отдаём оригинал,
                        # а не выдуманный русский вариант.
                        "title": (_econ_title_ru(r["indicator"], r["title"], r["country"])
                                  or r["title"]),
                        "title_en": r["title"], "country": r["country"],
                        "place": p["city"], "lon": p["lon"], "lat": p["lat"],
                        "ts": r["scheduled_ts"], "impact": r["impact"],
                        "rule": "calendar",
                        "actual": r["actual"], "forecast": r["forecast"],
                        "previous": r["previous"],
                    })

            if kinds in ("all", "news"):
                con = sqlite3.connect(f"file:{_SIGNALS_DB}?mode=ro", uri=True, timeout=10)
                con.row_factory = sqlite3.Row
                try:
                    rows = con.execute(
                        """SELECT g.country, g.lon, g.lat, g.rule,
                                  s.title, s.url, s.topic_hint, s.last_seen
                           FROM news_geo g JOIN signals s ON s.uid = g.news_uid
                           WHERE s.last_seen >= datetime('now', ?)
                             AND s.title <> ''
                           ORDER BY s.last_seen DESC LIMIT ?""",
                        (f"-{hours} hours", limit)).fetchall()
                finally:
                    con.close()
                for r in rows:
                    try:
                        ts = int(datetime.fromisoformat(r["last_seen"]).timestamp())
                    except (ValueError, TypeError):
                        continue
                    p = places.get(r["country"], {})
                    items.append({
                        "kind": "news", "id": f"nw-{abs(hash(r['url'] or r['title'])) % 10**9}",
                        "title": r["title"], "country": r["country"],
                        "place": p.get("city", r["country"]),
                        "lon": r["lon"], "lat": r["lat"], "ts": ts,
                        "source": r["topic_hint"], "url": r["url"],
                        "rule": r["rule"],
                    })

            items.sort(key=lambda x: x["ts"], reverse=True)
            self._send_json({
                "updated": datetime.now(timezone.utc).isoformat(),
                "window_hours": hours,
                "items": items[:limit],
            })
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_pulse_board(self) -> None:
        """Доска обсуждаемости для главной.

        Без параметра — срез по всему рынку: по четыре инструмента каждого из
        пяти направлений, чтобы их можно было сравнить между собой.
        С `?cat=<направление>` — одно направление и не меньше десяти
        инструментов в нём.

        Отличие от /api/pulse (вкладки «крипта / акции / индексы»): там топ-8
        по всплеску внутри направления, здесь — по абсолютным упоминаниям за
        сутки, потому что размер пузыря должен отвечать на вопрос «о чём
        говорят больше», а не «где сильнее разогналось».
        """
        params = parse_qs(urlparse(self.path).query)
        cat = params.get("cat", [None])[0]
        if cat and cat not in self._BOARD_QUOTA:
            self._send_json({"error": "unknown cat"}, 400)
            return
        try:
            con = sqlite3.connect(str(_SIGNALS_DB))
            con.row_factory = sqlite3.Row
            ts = con.execute("SELECT MAX(ts) FROM pulse_scores").fetchone()[0]
            if ts is None:
                self._send_json({"items": [], "updated": None})
                con.close()
                return
            rows = con.execute(
                "SELECT symbol, category, mentions, mentions_24h, score "
                "FROM pulse_scores WHERE ts=?", (ts,)).fetchall()
            con.close()

            # 🔴 Схлопываем имена одного и того же актива. В счётчике WTI и
            # CrudeOIL, NG и NATURAL_GAS, XRP и XRPUSD живут отдельными
            # строками — это одно и то же, просто каноническое имя и имя
            # брокера. Без слияния доска показала бы нефть дважды и заняла бы
            # два места из двадцати.
            meta = _board_symbol_meta()
            merged: dict = {}
            for r in rows:
                m = meta.get(r["symbol"])
                if not m:
                    # Символа нет среди открывающихся инструментов — это
                    # кештег вроде LUNA или GME, который мы не показываем.
                    # Молча пропускаем: доска должна вести на график.
                    continue
                key = m["key"]
                cur = merged.setdefault(key, {
                    "symbol": key, "name": m["name"], "category": r["category"],
                    "mentions": 0, "burst": 0.0, "price": m["price"], "chg": m["chg"],
                    "ticker": m.get("ticker"),
                })
                cur["mentions"] += r["mentions_24h"] or 0
                cur["burst"] = max(cur["burst"], round(r["score"] or 0, 2))

            pool = sorted(merged.values(), key=lambda x: x["mentions"], reverse=True)

            # ── Одно направление ────────────────────────────────────────────
            if cat:
                items = [x for x in pool if x["category"] == cat][:self._BOARD_CAT_MAX]
                # 🔴 Добираем инструментами, о которых сегодня не писали. Ноль
                # упоминаний — это факт, а не пустота: инструмент
                # отслеживается, просто про него молчат. Показать по валютам
                # три круга вместо пятидесяти значило бы соврать, что мы
                # следим только за тремя.
                #
                # Добираем до потолка, а не до минимума: раздел отвечает на
                # вопрос «за чем мы следим в этом направлении», и ответ на
                # него — весь список, а не его верхушка.
                if len(items) < self._BOARD_CAT_MAX:
                    have = {x["symbol"] for x in items}
                    for extra in _board_category_fill(cat):
                        if extra["symbol"] in have:
                            continue
                        items.append(extra)
                        have.add(extra["symbol"])
                        if len(items) >= self._BOARD_CAT_MAX:
                            break
                items.sort(key=lambda x: x["mentions"], reverse=True)
                self._send_json({
                    "updated": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
                    "window_hours": 24, "category": cat, "items": items,
                })
                return

            chosen, taken = [], {k: 0 for k in self._BOARD_QUOTA}
            for it in pool:
                q = self._BOARD_QUOTA.get(it["category"])
                if q is None or taken[it["category"]] >= q:
                    continue
                taken[it["category"]] += 1
                chosen.append(it)
            # Квоты добираем общим топом: если про сырьё сегодня молчат, место
            # не должно пустовать. Но не больше потолка на группу — иначе
            # акции, которых в каталоге 618, вытеснили бы все остальные.
            if len(chosen) < self._BOARD_TOTAL:
                have = {c["symbol"] for c in chosen}
                for it in pool:
                    if it["symbol"] in have:
                        continue
                    if taken.get(it["category"], 0) >= self._BOARD_GROUP_CAP:
                        continue
                    taken[it["category"]] = taken.get(it["category"], 0) + 1
                    chosen.append(it)
                    if len(chosen) >= self._BOARD_TOTAL:
                        break
            chosen = chosen[:self._BOARD_TOTAL]
            chosen.sort(key=lambda x: x["mentions"], reverse=True)
            self._send_json({
                "updated": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
                "window_hours": 24,
                "items": chosen,
            })
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_pulse_feed(self) -> None:
        """Фаза 4: лента упоминаний по тикеру (тап на карточку) — за регистрацией,
        консистентно с /api/chart/event-reaction (см. _lp_require_auth)."""
        if not self._lp_require_auth():
            return
        params = parse_qs(urlparse(self.path).query)
        symbol = params.get("symbol", [None])[0]
        if not symbol:
            self._send_json({"error": "symbol required"}, 400)
            return
        try:
            con = sqlite3.connect(str(_SIGNALS_DB))
            con.row_factory = sqlite3.Row
            cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
            rows = con.execute(
                """SELECT source, title, text, url, topic_hint, cashtags, last_seen
                   FROM signals WHERE last_seen >= ? ORDER BY last_seen DESC LIMIT 800""",
                (cutoff_iso,),
            ).fetchall()
            items = []
            for r in rows:
                try:
                    tags = json.loads(r["cashtags"] or "[]")
                except (ValueError, TypeError):
                    tags = []
                if symbol not in tags:
                    continue
                try:
                    ts = int(datetime.fromisoformat(r["last_seen"]).timestamp())
                except (ValueError, TypeError):
                    continue
                items.append({
                    "title": r["title"] or (r["text"] or "")[:140],
                    "url": r["url"], "source": r["source"] or r["topic_hint"], "ts": ts,
                })
            # + RSS-заголовки с тегом инструмента (Фаза 3), релевантно для индексов
            try:
                news_rows = con.execute(
                    """SELECT s.title, s.url, s.topic_hint AS source, s.raw, s.first_seen
                       FROM news_instrument_tags t JOIN signals s ON s.uid = t.news_uid
                       WHERE t.symbol = ?""",
                    (symbol,),
                ).fetchall()
                for r in news_rows:
                    try:
                        ts = float(json.loads(r["raw"] or "{}").get("published") or 0) \
                             or datetime.fromisoformat(r["first_seen"]).timestamp()
                    except (ValueError, TypeError):
                        continue
                    items.append({"title": r["title"], "url": r["url"], "source": r["source"], "ts": int(ts)})
            except sqlite3.OperationalError:
                pass
            con.close()
            items.sort(key=lambda x: x["ts"], reverse=True)
            self._send_json(items[:30])
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_chart_levels(self) -> None:
        """SBF_Charts_Layer2_Spec, Фаза 1: исторические S/R-уровни (sr_levels_job.py,
        раз в сутки). Публично — расчётные факты без направленных утверждений
        (см. compliance спеки), топ-12 активных (broken=0) по score."""
        params = parse_qs(urlparse(self.path).query)
        symbol = params.get("symbol", [None])[0]
        if not symbol:
            self._send_json({"error": "symbol required"}, 400)
            return
        # Ссылка приходит с каноническим именем (LINK), а уровни и зоны
        # посчитаны под именем брокера (LINKUSD) — см. _canonical_alias_map.
        symbol = _resolve_chart_symbol(symbol)
        try:
            price = float(params.get("price", [""])[0])
        except (TypeError, ValueError):
            price = None
        try:
            con = sqlite3.connect(str(_BOT_DB))
            con.row_factory = sqlite3.Row
            rows = con.execute(
                """SELECT price, kind, touches, age_days, last_touch_ts FROM sr_levels
                   WHERE symbol=? AND broken=0""",
                (symbol,),
            ).fetchall()
            con.close()
            items = [dict(r) for r in rows]
            for it in items:
                it["score"] = round(it["touches"] * math.log(it["age_days"] + 1), 3)
            items.sort(key=lambda x: x["score"], reverse=True)
            self._send_json(_levels_near_price(items, price))
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_chart_confluence(self) -> None:
        """SBF_Charts_Layer2_Spec, Фаза 2: зоны внимания (confluence_job.py,
        раз в сутки вслед за sr_levels_job.py). Публично — расчётные факты."""
        params = parse_qs(urlparse(self.path).query)
        symbol = params.get("symbol", [None])[0]
        if not symbol:
            self._send_json({"error": "symbol required"}, 400)
            return
        # Ссылка приходит с каноническим именем (LINK), а уровни и зоны
        # посчитаны под именем брокера (LINKUSD) — см. _canonical_alias_map.
        symbol = _resolve_chart_symbol(symbol)
        try:
            con = sqlite3.connect(str(_BOT_DB))
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT price_low, price_high, score, factors FROM confluence_zones WHERE symbol=? ORDER BY score DESC",
                (symbol,),
            ).fetchall()
            con.close()
            items = []
            for r in rows:
                d = dict(r)
                try:
                    d["factors"] = json.loads(d["factors"] or "[]")
                except (ValueError, TypeError):
                    d["factors"] = []
                items.append(d)
            self._send_json(items)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_chart_thermo(self) -> None:
        """SBF_Charts_Layer3_Spec, Фаза 1: «Термометр дня» (day_thermo_job.py,
        раз в 5 мин). Публично — расчётные факты, витринная ценность выше
        гейт-ценности (см. спеку). next_event отдаём развёрнуто (не только id) —
        та же форма, что /api/chart/events, чтобы фронт мог открыть карточку
        события напрямую, не полагаясь на то, что событие уже есть в кэше
        _curEvents текущего графика (для D1/W1 там фильтр impact='high', а
        термометр берёт medium+ — событие может отсутствовать в кэше)."""
        params = parse_qs(urlparse(self.path).query)
        symbol = params.get("symbol", [None])[0]
        if not symbol:
            self._send_json({"error": "symbol required"}, 400)
            return
        # ⚠️ Здесь перевода имени НЕТ, в отличие от levels/confluence рядом.
        # day_thermo индексирован символами графика (GOLD, SPX), то есть как
        # раз каноническими — перевод в имя брокера сломал бы попадание.
        # Ниже есть свой фолбэк через to_chart_symbol для journal-домена.
        try:
            con = sqlite3.connect(str(_BOT_DB))
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM day_thermo WHERE symbol=?", (symbol,)).fetchone()
            if not row:
                # Вызывающая сторона может передать символ journal-домена
                # (watchlist из дневника хранит XAUUSD/EURUSD/..., не GOLD —
                # см. core/journal_symbols.py). day_thermo индексирован по
                # символам графика, поэтому пробуем конвертировать перед 404.
                chart_sym = to_chart_symbol(symbol)
                if chart_sym and chart_sym != symbol:
                    row = con.execute("SELECT * FROM day_thermo WHERE symbol=?", (chart_sym,)).fetchone()
            if not row:
                con.close()
                self._send_json({"error": "not found"}, 404)
                return
            out = dict(row)
            if out.get("next_event_id"):
                ev = con.execute(
                    """SELECT e.id, e.scheduled_ts AS ts, e.title, e.indicator, e.country,
                              e.impact, e.forecast, e.previous, e.actual
                       FROM econ_events e WHERE e.id = ?""",
                    (out["next_event_id"],),
                ).fetchone()
                if ev:
                    ev = dict(ev)
                    ev["importance"] = ev.pop("impact")
                    ev["currency"] = _COUNTRY_CURRENCY.get(ev["country"], ev["country"])
                    # Тот же перевод, что и в /api/chart/events: «Ближайшее
                    # событие» в шапке графика — тот же самый релиз, и видеть его
                    # по-английски там, где карточка уже по-русски, странно.
                    ru = _econ_title_ru(ev.get("indicator"), ev.get("title"), ev.get("country"))
                    if ru:
                        ev["title_ru"] = ru
                    ev["event_type"] = normalize_event_type(ev.pop("indicator") or ev["title"])
                    out["next_event"] = ev
            con.close()
            self._send_json(out)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_focus(self, user_id: str) -> None:
        """SPEC_focus_engine.md §9. Публично, как /api/chart/thermo — фокус
        для scope='default' не привязан к пользователю; scope=me резолвит
        персональный watchlist/пин через уже посчитанный user_id (нет смысла
        второй раз резолвить токен, _current_user_id() один раз на весь GET)."""
        params = parse_qs(urlparse(self.path).query)
        scope_param = params.get("scope", ["me"])[0]
        is_anon = user_id == "default"
        pin_user = None if (scope_param == "default" or is_anon) else user_id

        try:
            now_ts = int(time.time())
            pinned_raw = journal_brief.get_pinned(pin_user) if pin_user else None
            if pinned_raw:
                pinned_sym = to_chart_symbol(pinned_raw) or pinned_raw
                inst = focus_db.load_instrument(pinned_sym)
                last, change_pct = self._focus_move(pinned_sym, inst)
                self._send_json({
                    "symbol": pinned_sym, "name": inst["name"] if inst else pinned_sym,
                    "anomaly": None, "session_state": None,
                    "headline": "Фокус закреплён вручную.", "source": "pin",
                    "has_llm_analysis": False, "analysis": None, "updated_at": now_ts,
                    "last": last, "change_pct": change_pct,
                })
                return

            # Персональный scope_key имеет смысл, только пока у пользователя
            # реально есть непустой watchlist -- как только он опустел,
            # focus_live.py/focus_batch_job.py перестают трогать этот scope
            # (см. focus_db.active_user_scopes()) и его focus_state навсегда
            # замораживается на последнем пике (нашли по жалобе: карточка
            # показывала SILVER сутки спустя после того, как watchlist уже
            # опустел, с только "живой" ценой поверх мёртвого символа).
            # С пустым watchlist откатываемся на 'default' — те же символы
            # (focus_db.scope_symbols() и так фоллбэчит на DEFAULT_UNIVERSE),
            # но живое, постоянно обновляемое состояние с LLM-разбором.
            if pin_user and journal_brief.get_watchlist(pin_user):
                scope_key = f"user:{pin_user}"
            else:
                scope_key = "default"

            state = focus_db.load_focus_state(scope_key)
            if state is None:
                # Живой поллер ещё не тикнул этот scope (новый пользователь,
                # §11 edge case) — считаем на лету вместо 404.
                if scope_key == "default":
                    symbols = DEFAULT_UNIVERSE
                else:
                    raw = journal_brief.get_watchlist(pin_user)
                    symbols = [to_chart_symbol(s) or s for s in raw] or DEFAULT_UNIVERSE
                today = focus_db.today_str()
                candidates = focus_db.build_candidates(symbols, today)
                state = select_focus(scope_key, candidates, None, None, now_ts, new_source="live")
                focus_db.save_focus_state(state)

            if state.symbol is None:
                self._send_json({
                    "symbol": None, "name": None, "anomaly": None, "session_state": None,
                    "headline": "Рынок спокоен — ни один инструмент не выходит за пределы нормы.",
                    "source": "calm", "has_llm_analysis": False, "analysis": None,
                    "updated_at": state.decided_at, "last": None, "change_pct": None,
                })
                return

            inst = focus_db.load_instrument(state.symbol)
            name = inst["name"] if inst else state.symbol
            mult = round(state.anomaly, 1) if state.anomaly is not None else None
            headline = (f"{name} сегодня движется в {mult}× своей нормы"
                        if mult is not None else name)
            live_row = focus_db.load_instrument_live(state.symbol)
            session_state = live_row["session_state"] if live_row else None

            # has_llm_analysis (§9): true только когда source=batch И файл с
            # разбором реально существует. Файл ключуется СИМВОЛОМ, не только
            # датой (analysis_<date>_<symbol>.txt) -- build_brief.py/prompt.md
            # теперь пишут разбор для 'default' И для каждого персонального
            # scope с активным batch-пиком (см. focus_batch_job.py), дедуп по
            # символу; поэтому лукап тоже идёт по фактическому символу ТЕКУЩЕГО
            # scope, а не по одному файлу на весь день. Смена на source="live"
            # в течение дня естественно гасит has_llm_analysis, т.к. condition
            # ниже проверяет ИМЕННО текущий source, не то, каким он был при
            # первом коммите.
            analysis = None
            has_llm = state.source == "batch"
            if has_llm:
                f = Path(__file__).parent / "data" / "focus" / f"analysis_{focus_db.today_str()}_{state.symbol}.txt"
                if f.exists():
                    try:
                        analysis = f.read_text(encoding="utf-8").strip() or None
                    except OSError:
                        analysis = None
                has_llm = analysis is not None

            last, change_pct = self._focus_move(state.symbol, inst)
            self._send_json({
                "symbol": state.symbol, "name": name, "anomaly": state.anomaly,
                "session_state": session_state, "headline": headline, "source": state.source,
                "has_llm_analysis": has_llm, "analysis": analysis, "updated_at": state.decided_at,
                "last": last, "change_pct": change_pct,
            })
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _focus_move(self, symbol: str, inst) -> tuple[float | None, float | None]:
        """Текущая цена (округлённая по instrument.decimals) + дневное
        изменение в % от day_open -- для бейджа "тикер · движение" на
        карточке (визуальный ориентир из sbf_briefing_v1.html §03, не часть
        буквальной спеки §9, но данные уже есть в instrument_live)."""
        live = focus_db.load_instrument_live(symbol)
        if not live or live["last"] is None:
            return None, None
        decimals = inst["decimals"] if inst and inst["decimals"] is not None else 2
        last = round(live["last"], decimals)
        change_pct = None
        if live["day_open"]:
            change_pct = round((live["last"] - live["day_open"]) / live["day_open"] * 100, 2)
        return last, change_pct

    def _handle_chart_thermo_hist(self) -> None:
        """SBF_Charts_Layer3_Spec, Фаза 1: мини-гистограмма по тапу на чип
        «волатильность» (kind=range, 60 дневных диапазонов) или «DVOL»
        (kind=dvol, 90-дневная серия Deribit). Живой расчёт по запросу — НЕ
        часть 5-минутного снапшота day_thermo (сеть до Deribit не должна
        замедлять основной /api/chart/thermo, который должен отвечать быстро,
        см. спеку "за 3 секунды")."""
        params = parse_qs(urlparse(self.path).query)
        symbol = params.get("symbol", [None])[0]
        kind = params.get("kind", ["range"])[0]
        if not symbol:
            self._send_json({"error": "symbol required"}, 400)
            return
        try:
            if kind == "dvol":
                if symbol not in _THERMO_CRYPTO or symbol not in _THERMO_DVOL_CCY:
                    self._send_json({"error": "no dvol for symbol"}, 404)
                    return
                series = _thermo_dvol_series(symbol)
                if not series:
                    self._send_json({"error": "not found"}, 404)
                    return
                self._send_json([{"ts": ts, "v": v} for ts, v in series])
            else:
                d1 = _thermo_load_d1(symbol)
                if not d1 or not d1["candles"]:
                    self._send_json({"error": "not found"}, 404)
                    return
                series = _thermo_range_series(d1["candles"])
                self._send_json([{"ts": ts, "v": v} for ts, v in series])
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_chart_sessions(self) -> None:
        """SBF_Charts_Layer3_Spec, Фаза 2: границы торговых сессий (Азия/Лондон/NY,
        DST на сегодня — см. core/sessions.py) + 24-часовой профиль типичной
        волатильности. Публично — факты.
        sessions_today отдаётся для удобства (акцептанс спеки прямо просит
        «границы сессий с учётом DST на сегодня»), но рендер полос на графике
        для ПРОИЗВОЛЬНОГО видимого дня фронтенд считает сам теми же правилами
        (см. комментарий в core/sessions.py) — иначе прокрутка к историческим
        датам через переход DST показывала бы неверные границы.

        SPEC_chart_fixes_and_staged_signup.md §2: profile раньше шёл из своего,
        худшего конвейера (hourly_vol_job.py → sqlite hourly_vol_profile,
        среднее без размера выборки). Главы книги уже читают edu_stats/
        hourly_profile.json — тот же вопрос посчитан там честнее (медиана,
        n, coverage, warnings) tools/edu_build/hourly_profile.py. Теперь
        график берёт то же самое, а не второй параллельный расчёт."""
        params = parse_qs(urlparse(self.path).query)
        symbol = params.get("symbol", [None])[0]
        if not symbol:
            self._send_json({"error": "symbol required"}, 400)
            return
        try:
            bounds = session_bounds_utc(datetime.now(timezone.utc).date())
            hp_path = WEB_DIR / "data" / "edu_stats" / "hourly_profile.json"
            try:
                hp = json.loads(hp_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                hp = {}
            sym_data = hp.get(symbol) or {}
            avg_share = sym_data.get("avg_share") or {}
            n_by_hour: dict[str, int] = {}
            for hours in (sym_data.get("by_period") or {}).values():
                for hh, v in hours.items():
                    n_by_hour[hh] = n_by_hour.get(hh, 0) + (v.get("n") or 0)
            profile = [
                {"hour_utc": int(h), "share": share, "n": n_by_hour.get(h, 0)}
                for h, share in sorted(avg_share.items(), key=lambda kv: int(kv[0]))
            ]
            self._send_json({
                "sessions_today": {name: {"from_hour": fh, "to_hour": th} for name, (fh, th) in bounds.items()},
                "profile": profile,
                "coverage": sym_data.get("coverage"),
                "warnings": sym_data.get("warnings", []),
            })
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_chart_ohlc_m5(self) -> None:
        """SPEC_chart_fixes_and_staged_signup.md §3: M5 не отдаём статикой
        (60д на 5m ≈ 2,5МБ/символ — grafik-engine.js тянет файл целиком,
        неприемлемо на телефоне). Вместо этого — короткое окно (7 дней) по
        запросу, с коротким кэшем (бар M5 не меняется чаще, чем раз в 5 мин).
        rsi/bias/pivots/nearest в ответе намеренно нет — chart.html их и так
        досчитывает на клиенте, если сервер их не прислал (SBFGrafik.calcRSI14/
        calcBias/calcPivots/nearestPivot — тот же фолбэк, что уже был для
        любого ответа без этих полей)."""
        params = parse_qs(urlparse(self.path).query)
        symbol = params.get("symbol", [None])[0]
        if not symbol:
            self._send_json({"error": "symbol required"}, 400)
            return
        ticker = _registry_yahoo_ticker(symbol)
        if not ticker:
            # Честно: нет надёжного источника M5 для этого символа (MT5-only
            # валюты типа USDRUB/USDKZT никто ещё не собирал на этом ТФ) —
            # не 500, а пустой набор баров, чтобы фронт показал "нет данных".
            self._send_json({"ticker": symbol, "interval": "M5", "candles": [], "volume": []})
            return
        now = time.time()
        cached = _m5_cache.get(symbol)
        if cached and now - cached[0] < _M5_CACHE_TTL:
            self._send_json(cached[1])
            return
        try:
            import yfinance as yf
            df = yf.Ticker(ticker).history(period="7d", interval="5m")
            candles, volume = [], []
            for ts, r in df.iterrows():
                o, h, l, c = float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"])
                up = c >= o
                t = int(ts.timestamp())
                candles.append({"time": t, "open": round(o, 4), "high": round(h, 4),
                                 "low": round(l, 4), "close": round(c, 4)})
                volume.append({"time": t, "value": int(r["Volume"] or 0),
                                "color": "rgba(30,142,90,.5)" if up else "rgba(192,57,43,.5)"})
            payload = {
                "ticker": ticker, "interval": "M5", "candles": candles, "volume": volume,
                "last": candles[-1]["close"] if candles else None,
            }
            _m5_cache[symbol] = (now, payload)
            self._send_json(payload)
        except Exception as e:
            self._send_json({"ticker": ticker, "interval": "M5", "candles": [], "volume": [], "error": str(e)})

    def _handle_chart_tail(self) -> None:
        """SPEC_fix_live_chart.md §2. Живая свеча раньше синтезировалась из
        котировки (close=price, high/low растянуты по 8-секундным точкам
        опроса, open — из последней публикации publish_charts()). Тут —
        честный хвост реальных баров: те же йfinance-данные, что и статика,
        просто короткое окно и короткий кэш, модель — _handle_chart_ohlc_m5.

        market_open честно ИЗМЕРЯЕТСЯ (не декларируется по календарю сессий —
        это отдельная, более точная работа §7 на фронте): если последний
        полученный от Yahoo бар свежее ~2.5 таймфреймов, считаем рынок
        открытым, иначе закрытым. Календарным способом (session_bounds_utc)
        не дублирую — §7 сделает выключение опроса на фронте отдельно,
        market_open здесь просто честная метка для текущего снимка данных."""
        params = parse_qs(urlparse(self.path).query)
        symbol = params.get("s", [None])[0]
        tf = params.get("tf", [None])[0]
        since_raw = params.get("since", ["0"])[0]
        if not symbol or tf not in _TAIL_YF_INTERVAL:
            self._send_json({"error": "s and tf (M1/M5/M15/M30/H1/H4/D1/W1) required"}, 400)
            return
        try:
            since = int(since_raw)
        except ValueError:
            since = 0

        # Ссылка из списка инструментов приходит с каноническим именем (LINK),
        # а свечи лежат под именем брокера (LINKUSD) — см. _canonical_alias_map.
        link_name = _canonical_link_name(symbol)
        symbol = _resolve_chart_symbol(symbol)

        # Скрытые сознательно отвечают отказом с причиной, а не пустым рядом:
        # пустой график человек читает как поломку сайта, а не как решение.
        blocked = _blocked_symbols().get(symbol)
        if blocked:
            self._send_json({"candles": [], "blocked": True,
                             "reason": blocked.get("причина", "не показывается")})
            return

        # ── cTrader: 80 инструментов витрины переведены сюда (01.09.2026) ──
        # Валюты, металлы, нефть, индексы, крипта. Читается с диска, к брокеру
        # обработчик не ходит вовсе — ни к cTrader, ни к MT5.
        ct = _ctrader_tail(symbol, tf)

        # 🔴 Кэш ещё пуст (первое наполнение, пуллер лежит) — уходим на MT5, а
        # не показываем пустой график.
        #
        # Сначала здесь стоял честный feed_down, и это было неверно: первый
        # проход пуллера идёт по алфавиту около четырёх минут, и всё это время
        # EURUSD, GOLD и US_500 отдавали пустоту, хотя MT5 рядом отдавал их
        # прекрасно. Проверено на живом сервере — поймано ровно так.
        #
        # Подмена источника здесь безопасна, в отличие от случая 20.08: тогда
        # хвост ДОПИСЫВАЛСЯ к чужому ряду и рисовал ступеньку на стыке. Мы
        # отдаём весь ряд целиком из одного источника, и следующая загрузка
        # страницы просто заменит его целиком же.
        broker = ct if ct else _mt5_tail(symbol, tf)
        src = "ctrader" if ct else ("mt5" if broker else None)

        # 🔴 Биржевые свечи — последними, а не первыми. У брокера живы
        # шестнадцать монет из двадцати одной, и подменять их чужим рядом
        # незачем: цена в списке инструментов, котировка и график должны
        # приходить из одного места, иначе на стыке получается ступенька
        # (семейство бага 20.08). Биржа закрывает ровно то, чего у брокера
        # нет: SHIBUSD с котировкой 121-дневной давности, BTGUSD, ETHBTC,
        # MELANIAUSD и PAX_GOLD — по ним баров не было вовсе.
        if not broker:
            broker = _crypto_tail(symbol, tf)
            if broker:
                src = "exchange"

        if broker:
            filtered = [c for c in broker if c["time"] > since]
            last_ts = broker[-1]["time"]
            delay_sec = max(0, int(time.time() - last_ts))
            market_open = delay_sec < _TAIL_TF_SEC[tf] * 3
            # 🔴 live_price — цена ТОГО ЖЕ инструмента, что и свечи.
            # Фронт до 20.08 брал живую цену из /api/quotes по карте YF, где у
            # золота стоит GC=F, у серебра SI=F, у нефти CL=F — это ФЬЮЧЕРСЫ, а
            # ряд идёт из MT5 по СПОТУ. Фьючерс торгуется с базисом: замер
            # 20.08 — 4546.4 против спота 4492.7, разница 54 пункта. applyLive()
            # растягивал текущую свечу до фьючерсной цены, и получался одиночный
            # вертикальный шип. По валютам (EURUSD=X) базиса почти нет — поэтому
            # ломалось «на некоторых активах», а не на всех.
            # Последняя свеча MT5 — незакрытая, её close и есть текущая цена.
            self._send_json({"updated": datetime.now(timezone.utc).isoformat(),
                             "delay_sec": delay_sec, "market_open": market_open,
                             # Источник помечаем честно: по нему на странице
                             # подписано, чьи это котировки, и по нему же
                             # различаются отказы в логах.
                             "candles": filtered,
                             # exchange — свечи с криптобиржи, не от брокера.
                             # Подписывать их как «mt5» значило бы говорить
                             # неправду в том самом месте, где страница
                             # объясняет человеку, чьи это котировки.
                             "source": src or "mt5",
                             # Одно имя для ссылки: страница по нему поправит
                             # адрес, чтобы XAUUSD и GOLD не жили как две
                             # разные страницы одного графика.
                             "canonical": link_name,
                             "live_price": broker[-1]["close"]})
            return

        # 🔴 Ряд НЕ склеивается из двух источников.
        #
        # Симптом, с которым это найдено: свеча EURUSD прыгала вертикально на
        # ровном месте. Замер 20.08 02:11 — MT5 bid 1.16754, Yahoo close
        # 1.16795, разница 4.1 пункта, и она держится. Пока мост падал
        # (973 перезапуска из-за отмонтированного диска), хвост переключался
        # между двумя фидами каждые 8-20 секунд по TTL кэша, и график рисовал
        # эту разницу как движение цены. Данные при этом целы — испорчена
        # именно склейка.
        #
        # Yahoo остаётся источником для символов, которых у брокера нет. Но
        # если внутридневка символа ЖИВЁТ в MT5, а мост сейчас молчит, честный
        # ответ — пустой хвост: график замирает на последней настоящей свече.
        # Пауза — правда, скачок на 4 пункта — нет. Фронт видит feed_down и
        # может сказать об этом словами вместо того, чтобы дорисовывать.
        if _mt5_tail_supported(symbol, tf):
            self._send_json({"candles": [], "updated": datetime.now(timezone.utc).isoformat(),
                             "delay_sec": None, "market_open": None,
                             "source": "mt5", "feed_down": True})
            return

        ticker = _registry_yahoo_ticker(symbol)
        if not ticker:
            self._send_json({"candles": [], "updated": datetime.now(timezone.utc).isoformat(),
                              "delay_sec": None, "market_open": None})
            return

        now = time.time()
        cache_key = (symbol, tf)
        cached = _tail_cache.get(cache_key)
        if cached and now - cached[0] < _TAIL_CACHE_TTL:
            payload = cached[1]
        else:
            try:
                import yfinance as yf
                interval = _TAIL_YF_INTERVAL[tf]
                period = _TAIL_YF_PERIOD[tf]
                df = yf.Ticker(ticker).history(period=period, interval=interval)
                resample_to = _TAIL_RESAMPLE.get(tf)
                if resample_to and not df.empty:
                    # label='left': пандас по умолчанию метит недельный бин концом
                    # недели (воскресеньем) -- для ТЕКУЩЕЙ незавершённой недели это
                    # дата в будущем относительно "сейчас", ломает delay_sec ниже
                    # (now - last_ts стал бы отрицательным). H4 своей выравненной
                    # сеткой (00/04/08…) этой проблемы не имеет, но label='left'
                    # ей тоже не вредит -- ставим на оба ресэмпла для единообразия.
                    df = df.resample(resample_to, label="left").agg(
                        {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
                    ).dropna()
                candles = []
                for ts, r in df.iterrows():
                    candles.append({
                        "time": int(ts.timestamp()),
                        "open": round(float(r["Open"]), 4), "high": round(float(r["High"]), 4),
                        "low": round(float(r["Low"]), 4), "close": round(float(r["Close"]), 4),
                    })
                last_ts = candles[-1]["time"] if candles else None
                delay_sec = max(0, int(now - last_ts)) if last_ts else None
                tf_sec = _TAIL_TF_SEC[tf]
                market_open = (delay_sec is not None) and (delay_sec < tf_sec * 2.5)
                payload = {
                    "updated": datetime.now(timezone.utc).isoformat(),
                    "delay_sec": delay_sec, "market_open": market_open,
                    "candles": candles,
                }
                _tail_cache[cache_key] = (now, payload)
            except Exception as e:
                self._send_json({"error": str(e), "candles": [],
                                  "updated": datetime.now(timezone.utc).isoformat(),
                                  "delay_sec": None, "market_open": None})
                return

        filtered = [c for c in payload["candles"] if c["time"] > since]
        self._send_json({**payload, "candles": filtered})

    def _handle_chart_sentiment(self) -> None:
        """SBF_Charts_Layer3_Spec, Фаза 3: сентимент толпы по часам (twitter+
        telegram, словарная разметка bull/bear) + флаг дивергенции с ценой.
        За регистрацией (спека). Источники см. sentiment_job.py — StockTwits/
        Reddit/Telegram-алерты, заявленные спекой, сейчас не работают."""
        if not self._lp_require_auth():
            return
        params = parse_qs(urlparse(self.path).query)
        symbol = params.get("symbol", [None])[0]
        if not symbol:
            self._send_json({"error": "symbol required"}, 400)
            return
        try:
            now = int(time.time())
            from_ts = int(params.get("from", [None])[0] or (now - 7 * 86400))
            to_ts = int(params.get("to", [None])[0] or now)
        except ValueError:
            self._send_json({"error": "invalid from/to"}, 400)
            return
        try:
            con = sqlite3.connect(str(_BOT_DB))
            rows = con.execute(
                "SELECT ts_hour, score, total FROM sentiment_hourly WHERE symbol=? AND ts_hour BETWEEN ? AND ? ORDER BY ts_hour",
                (symbol, from_ts, to_ts),
            ).fetchall()
            con.close()
            points = [{"ts_hour": r[0], "score": r[1], "total": r[2]} for r in rows]

            # Дивергенция — всегда по последним 24ч (снапшот-флаг, не зависит
            # от запрошенного окна графика), только по часам БЕЗ пропусков.
            con2 = sqlite3.connect(str(_BOT_DB))
            recent = con2.execute(
                "SELECT score FROM sentiment_hourly WHERE symbol=? AND ts_hour >= ?",
                (symbol, now - 24 * 3600),
            ).fetchall()
            con2.close()
            scores_24h = [r[0] for r in recent]

            price_change = None
            atr = None
            h1_file = WEB_DIR / "data" / f"ohlc_{symbol}_H1.json"
            if h1_file.exists():
                try:
                    h1 = json.loads(h1_file.read_text())
                    candles = h1.get("candles") or []
                    if len(candles) >= 25:
                        price_change = float(candles[-1]["close"]) - float(candles[-25]["close"])
                except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                    pass
            d1_candles = _load_d1_candles(symbol)
            if d1_candles:
                atr = _atr14(d1_candles)

            divergence = detect_divergence(scores_24h, price_change or 0.0, atr) if price_change is not None else False
            self._send_json({"points": points, "divergence": bool(divergence)})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_chart_my_trades(self) -> None:
        """SBF_Charts_Layer4_Spec, Фаза 2: сделки пользователя на графике.
        Auth strict (own trades only — WHERE user_id=? внутри journal_db,
        см. list_trades_for_chart), private/no-store (уже дефолт _send_json).

        ВАЖНО (найдено на Фазе 1, не переоткрывать): trades.exit_price и
        close_ts — NOT NULL в схеме БД (core/journal_db.py) — это чисто
        пост-фактум журнал закрытых сделок, "открытых" сделок в текущей
        модели данных не существует. exit_ts/exit_price в ответе поэтому
        НИКОГДА не будут null на практике, хотя спека это допускает."""
        user_id = self._lp_require_auth()
        if not user_id:
            return
        params = parse_qs(urlparse(self.path).query)
        symbol = params.get("symbol", [None])[0]
        if not symbol:
            self._send_json({"error": "symbol required"}, 400)
            return
        try:
            now = int(time.time())
            from_ts = int(params.get("from", [None])[0] or (now - 180 * 86400))
            to_ts = int(params.get("to", [None])[0] or (now + 86400))
        except ValueError:
            self._send_json({"error": "invalid from/to"}, 400)
            return
        try:
            aliases = chart_symbol_aliases(symbol.upper())
            from_iso = datetime.fromtimestamp(from_ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            to_iso = datetime.fromtimestamp(to_ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            rows = journal_db.list_trades_for_chart(user_id, aliases, from_iso, to_iso)
            out = []
            for r in rows:
                try:
                    entry_ts = int(datetime.fromisoformat(r["open_ts"]).replace(tzinfo=timezone.utc).timestamp())
                    exit_ts = int(datetime.fromisoformat(r["close_ts"]).replace(tzinfo=timezone.utc).timestamp())
                except (ValueError, TypeError):
                    continue
                out.append({
                    "id": r["id"], "direction": "long" if r["dir"] == "buy" else "short",
                    "entry_ts": entry_ts, "entry_price": r["entry_price"],
                    "exit_ts": exit_ts, "exit_price": r["exit_price"],
                    "sl": r["stop_loss"], "tp": None, "r": r["pnl_r"],
                    "setup": r["setup_tag"], "note": (r["note"] or "")[:140],
                })
            self._send_json(out)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_chart_trade_context(self) -> None:
        """SBF_Charts_Layer4_Spec, Фаза 2: контекст-строка карточки сделки —
        ближайшее событие ±60 мин, попадание входа в зону внимания, сессия на
        момент входа. Все три — запросы к уже готовым таблицам/модулям
        Layer1-3, ни одного нового расчёта (буквально по спеке)."""
        user_id = self._lp_require_auth()
        if not user_id:
            return
        params = parse_qs(urlparse(self.path).query)
        trade_id = params.get("trade_id", [None])[0]
        if not trade_id:
            self._send_json({"error": "trade_id required"}, 400)
            return
        try:
            trade_id = int(trade_id)
        except ValueError:
            self._send_json({"error": "invalid trade_id"}, 400)
            return
        try:
            trade = journal_db.get_trade(trade_id, user_id)
            if not trade:
                self._send_json({"error": "not found"}, 404)
                return
            chart_symbol = to_chart_symbol(trade["symbol"])
            entry_ts = int(datetime.fromisoformat(trade["open_ts"]).replace(tzinfo=timezone.utc).timestamp())
            entry_price = trade["entry_price"]

            event = None
            zone = None
            session = None
            if chart_symbol:
                con = sqlite3.connect(str(_BOT_DB))
                con.row_factory = sqlite3.Row
                ev_row = con.execute(
                    """SELECT e.id, e.scheduled_ts AS ts, e.title, e.country, e.impact
                       FROM econ_events e JOIN event_instrument_map m ON m.country = e.country
                       WHERE m.symbol = ? AND e.scheduled_ts BETWEEN ? AND ?
                       ORDER BY ABS(e.scheduled_ts - ?) ASC,
                                CASE e.impact WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END ASC
                       LIMIT 1""",
                    (chart_symbol, entry_ts - 3600, entry_ts + 3600, entry_ts),
                ).fetchone()
                if ev_row:
                    event = {"id": ev_row["id"], "ts": ev_row["ts"], "title": ev_row["title"],
                              "country": ev_row["country"], "importance": ev_row["impact"],
                              "minutes_before": round((ev_row["ts"] - entry_ts) / 60)}
                zone_row = con.execute(
                    "SELECT price_low, price_high, score FROM confluence_zones WHERE symbol=? AND price_low<=? AND price_high>=?",
                    (chart_symbol, entry_price, entry_price),
                ).fetchone()
                if zone_row:
                    zone = {"price_low": zone_row["price_low"], "price_high": zone_row["price_high"], "score": zone_row["score"]}
                con.close()
                dt = datetime.fromtimestamp(entry_ts, timezone.utc)
                session = session_at(dt.date(), dt.hour)

            self._send_json({"event": event, "zone": zone, "session": session, "chart_symbol": chart_symbol})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_chart_patterns(self) -> None:
        """SBF_Charts_Layer2_Spec, Фаза 3: маркеры паттернов для рендера (слой
        «Паттерны» — публичный, гейт только на статистику ниже). Детект живой,
        через core.patterns.detect() — единый источник с pattern_stats_job.py."""
        params = parse_qs(urlparse(self.path).query)
        symbol = params.get("symbol", [None])[0]
        tf = params.get("tf", ["D1"])[0]
        if not symbol:
            self._send_json({"error": "symbol required"}, 400)
            return
        try:
            from_ts = int(params.get("from", [None])[0] or 0)
            to_ts = int(params.get("to", [None])[0] or int(time.time()) + 365 * 86400)
        except ValueError:
            self._send_json({"error": "invalid from/to"}, 400)
            return
        try:
            from pattern_stats_job import _load_candles as _load_ohlc
            candles = _load_ohlc(symbol, tf)
            if not candles:
                self._send_json([])
                return
            levels = []
            try:
                con = sqlite3.connect(str(_BOT_DB))
                con.row_factory = sqlite3.Row
                levels = [dict(r) for r in con.execute(
                    "SELECT price, tolerance, kind FROM sr_levels WHERE symbol=? AND broken=0", (symbol,)
                ).fetchall()]
                con.close()
            except sqlite3.OperationalError:
                pass
            events = _detect_patterns(candles, levels)
            items = [
                {"pattern_key": e["pattern_key"], "ts": e["ts"], "direction": e["direction"],
                 "display_name_ru": PATTERNS.get(e["pattern_key"], {}).get("display_name_ru", e["pattern_key"])}
                for e in events if from_ts <= e["ts"] <= to_ts
            ]
            self._send_json(items)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_chart_smc(self) -> None:
        """WP3.2 SPEC_alpha_engine_implementation.md: структура рынка
        (свинги HH/LH/HL/LL, BOS/CHoCH, FVG, OB, пулы ликвидности, sweep) —
        живой детект через core.smc.detect(), порт SBFGrafik.detectSMC
        (grafik-engine.js:528-609), сверенный с ним на 200 барах (Core-лог
        11.08). SBFGrafik.detectSMC остаётся только для образовательной
        галереи (§3 спеки) — та же развилка, что уже у detectCandles
        (chart.html:431-432)."""
        params = parse_qs(urlparse(self.path).query)
        symbol = params.get("symbol", [None])[0]
        tf = params.get("tf", ["D1"])[0]
        if not symbol:
            self._send_json({"error": "symbol required"}, 400)
            return
        try:
            from_ts = int(params.get("from", [None])[0] or 0)
            to_ts = int(params.get("to", [None])[0] or int(time.time()) + 365 * 86400)
        except ValueError:
            self._send_json({"error": "invalid from/to"}, 400)
            return
        try:
            from pattern_stats_job import _load_candles as _load_ohlc
            from core.smc import detect as _detect_smc
            candles = _load_ohlc(symbol, tf)
            if not candles:
                self._send_json([])
                return
            events = _detect_smc(candles)
            items = [e for e in events if from_ts <= e["ts"] <= to_ts]
            self._send_json(items)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_chart_pattern_stats(self) -> None:
        """SBF_Charts_Layer2_Spec, Фаза 3: статистика отработки паттерна
        (pattern_stats_job.py, еженедельно). За регистрацией — как event-reaction
        Фазы 2. n<15 — 404 (порог публикации, см. compliance спеки)."""
        if not self._lp_require_auth():
            return
        params = parse_qs(urlparse(self.path).query)
        pattern = params.get("pattern", [None])[0]
        symbol = params.get("symbol", [None])[0]
        tf = params.get("tf", [None])[0]
        if not pattern or not symbol or not tf:
            self._send_json({"error": "pattern, symbol and tf required"}, 400)
            return
        try:
            con = sqlite3.connect(str(_BOT_DB))
            con.row_factory = sqlite3.Row
            row = con.execute(
                """SELECT n, agree_share_3, agree_share_5, agree_share_10, avg_move_5,
                   max_adverse_5, history_from_ts, computed_ts FROM pattern_stats
                   WHERE pattern_key=? AND symbol=? AND tf=?""",
                (pattern, symbol, tf),
            ).fetchone()
            con.close()
            if not row or row["n"] < 15:
                self._send_json({"error": "not found"}, 404)
                return
            d = dict(row)
            d["display_name_ru"] = PATTERNS.get(pattern, {}).get("display_name_ru", pattern)
            self._send_json(d)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_price_api(self) -> None:
        params = parse_qs(urlparse(self.path).query)
        symbol = params.get("symbol", ["EURUSD"])[0]
        tf     = params.get("tf",     ["1d"])[0]
        from_ts = params.get("from",  [None])[0]
        to_ts   = params.get("to",    [None])[0]
        try:
            con = sqlite3.connect(str(_BOT_DB))
            con.row_factory = sqlite3.Row
            q = "SELECT ts, o, h, l, c, v FROM price_bars WHERE symbol=? AND tf=?"
            args: list = [symbol, tf]
            if from_ts:
                q += " AND ts >= ?"; args.append(int(from_ts))
            if to_ts:
                q += " AND ts <= ?"; args.append(int(to_ts))
            q += " ORDER BY ts ASC LIMIT 500"
            rows = con.execute(q, args).fetchall()
            con.close()
            self._send_json([dict(r) for r in rows])
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    # ── Journal API ───────────────────────────────────────────────────────────

    def _read_body_json(self, max_bytes: int = 5_000_000) -> dict | None:
        length = int(self.headers.get("Content-Length", 0))
        if length > max_bytes:
            self._send_json({"error": "payload too large"}, 413)
            return None
        try:
            return json.loads(self.rfile.read(length))
        except Exception:
            self._send_json({"error": "invalid JSON"}, 400)
            return None

    def _handle_journal_list_trades(self, user_id: str = "default") -> None:
        params = parse_qs(urlparse(self.path).query)
        limit  = min(int(params.get("limit",  ["100"])[0]), 500)
        offset = int(params.get("offset", ["0"])[0])
        trades = journal_db.list_trades(user_id=user_id, limit=limit, offset=offset)
        total  = journal_db.count_trades(user_id)
        self._send_json({"trades": trades, "total": total, "limit": limit, "offset": offset})

    def _handle_journal_add_trade(self, user_id: str = "default") -> None:
        body = self._read_body_json()
        if body is None:
            return
        required = {"symbol", "dir", "entry_price", "exit_price",
                    "size", "open_ts", "close_ts", "pnl", "source"}
        missing = required - set(body.keys())
        if missing:
            self._send_json({"error": f"missing: {', '.join(missing)}"}, 400)
            return
        try:
            result = journal_db.add_trade(body, user_id)
            if not result.get("duplicate"):
                try:
                    pnl_r = float(body.get("pnl_r") or body.get("pnl") or 0)
                    journal_gamification.on_trade_added(result.get("id", 0), pnl_r, user_id)
                except Exception:
                    pass
            self._send_json(result, 201 if not result.get("duplicate") else 200)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_journal_import_csv(self, user_id: str = "default") -> None:
        length = int(self.headers.get("Content-Length", 0))
        if length > 10_000_000:
            self._send_json({"error": "payload too large"}, 413)
            return
        content = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            trades = journal_csv.parse_auto(content)
        except Exception as e:
            self._send_json({"error": str(e)}, 400)
            return
        added, dupes, errors = 0, 0, 0
        for t in trades:
            try:
                r = journal_db.add_trade(t, user_id)
                if r.get("duplicate"):
                    dupes += 1
                else:
                    added += 1
            except Exception:
                errors += 1
        self._send_json({"ok": True, "parsed": len(trades),
                         "added": added, "duplicates": dupes, "errors": errors})

    def _handle_journal_import_ocr(self, user_id: str = "default") -> None:
        import cgi
        ctype = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", 0))
        if length > 20_000_000:
            self._send_json({"error": "payload too large"}, 413)
            return
        # Читаем raw-байты файла (простой POST без multipart)
        data = self.rfile.read(length)
        try:
            trades = journal_ocr.ocr_bytes(data)
        except Exception as e:
            self._send_json({"error": f"OCR failed: {e}"}, 500)
            return
        added, dupes = 0, 0
        for t in trades:
            try:
                r = journal_db.add_trade(t, user_id)
                if r.get("duplicate"):
                    dupes += 1
                else:
                    added += 1
            except Exception:
                pass
        self._send_json({"ok": True, "parsed": len(trades),
                         "added": added, "duplicates": dupes})

    def _handle_journal_start_series(self, user_id: str = "default") -> None:
        """Гл.12 ступень 7: новая серия правил (или ручной тик бумажной
        версии). Фронтенд обязан подтвердить у пользователя, что старт новой
        серии обнулит счётчик, ДО этого вызова, если активная серия уже
        существует и в ней есть прогресс."""
        body = self._read_body_json()
        if body is None:
            return
        if body.get("action") == "tick":
            result = journal_rules.tick_manual(user_id)
            self._send_json(result, 200 if result.get("ok") else 400)
            return
        rules_text  = body.get("rules_text", "")
        predict_pct = body.get("predict_pct")
        try:
            predict_pct = float(predict_pct) if predict_pct is not None else None
        except (TypeError, ValueError):
            predict_pct = None
        result = journal_rules.start_series(user_id, rules_text, predict_pct)
        self._send_json(result, 200 if result.get("ok") else 400)

    def _handle_journal_save_tradeplan(self, user_id: str = "default") -> None:
        """Гл.13 §3.6: план сделки, записанный ДО открытия позиции — не
        привязан к trade_id, поэтому не через /api/journal/meta."""
        body = self._read_body_json()
        if body is None:
            return
        result = journal_tradeplan.save_plan(user_id, body.get("plan_text", ""))
        self._send_json(result, 200 if result.get("ok") else 400)

    def _handle_journal_set_gate_flag(self, user_id: str = "default") -> None:
        """Гл.14 ступень 9: только risk_math_completed выставляется отсюда
        сейчас (по завершении CostArithmetic §3.2)."""
        body = self._read_body_json()
        if body is None:
            return
        flag_key = body.get("flag_key")
        if flag_key != "risk_math_completed":
            self._send_json({"error": "unknown flag_key"}, 400)
            return
        result = journal_gate.set_flag(user_id, flag_key)
        self._send_json(result)

    def _handle_discipline_save_config(self, user_id: str = "default") -> None:
        body = self._read_body_json()
        if body is None:
            return
        config_list  = body.get("config", [])
        advanced     = bool(body.get("advanced_mode", False))
        if not isinstance(config_list, list):
            self._send_json({"error": "config must be a list"}, 400)
            return
        result = journal_discipline.save_config(user_id, config_list, advanced)
        self._send_json(result, 200 if result["ok"] else 400)

    def _handle_discipline_save_eval(self, user_id: str = "default") -> None:
        body = self._read_body_json()
        if body is None:
            return
        trade_id    = body.get("trade_id")
        evaluations = body.get("evaluations", [])
        if not trade_id or not isinstance(evaluations, list):
            self._send_json({"error": "trade_id and evaluations required"}, 400)
            return
        try:
            journal_discipline.save_eval(int(trade_id), evaluations)
            # Авто-обновляем journal_completed_24h если критерий включён
            config = journal_discipline.get_config(user_id)
            j24 = next((c for c in config if c["criterion"] == "journal_completed_24h" and c["enabled"]), None)
            if j24:
                passed_24h = journal_discipline.auto_eval_journal_24h(int(trade_id))
                journal_discipline.save_eval(int(trade_id), [{"criterion": "journal_completed_24h", "passed": passed_24h}])
            self._send_json({"ok": True})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_discipline_apply_preset(self, user_id: str = "default") -> None:
        body = self._read_body_json()
        if body is None:
            return
        preset = body.get("preset", "conservative")
        if preset not in journal_discipline.PRESETS:
            self._send_json({"error": f"unknown preset: {preset}"}, 400)
            return
        journal_discipline._apply_preset(user_id, preset)
        self._send_json({"ok": True, "config": journal_discipline.get_config(user_id)})

    # ── Alerts handlers (Part 4) ──────────────────────────────────────────────

    def _handle_alerts_add_rule(self, user_id: str = "default") -> None:
        body = self._read_body_json()
        if body is None:
            return
        required = {"symbol", "kind", "param"}
        missing = required - set(body.keys())
        if missing:
            self._send_json({"error": f"missing: {', '.join(missing)}"}, 400)
            return
        if body["kind"] not in journal_alerts.ALERT_KINDS:
            self._send_json({"error": f"unknown kind: {body['kind']}"}, 400)
            return
        try:
            result = journal_alerts.add_rule(
                symbol=str(body["symbol"]),
                kind=body["kind"],
                param=body["param"] if isinstance(body["param"], dict) else {},
                user_id=user_id,
            )
            self._send_json(result, 201)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_alerts_save_subscription(self) -> None:
        body = self._read_body_json()
        if body is None:
            return
        required = {"platform", "token"}
        missing = required - set(body.keys())
        if missing:
            self._send_json({"error": f"missing: {', '.join(missing)}"}, 400)
            return
        try:
            sid = journal_alerts.save_subscription(
                platform=body["platform"],
                token=body["token"],
                quiet_hours_start=body.get("quiet_hours_start"),
                quiet_hours_end=body.get("quiet_hours_end"),
                timezone=body.get("timezone", "UTC"),
            )
            self._send_json({"ok": True, "id": sid})
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_alerts_toggle_rule(self, rule_id: int) -> None:
        body = self._read_body_json()
        if body is None:
            return
        is_active = bool(body.get("is_active", True))
        ok = journal_alerts.toggle_rule(rule_id, is_active)
        self._send_json({"ok": ok})

    def _handle_alerts_mark_delivered(self) -> None:
        body = self._read_body_json()
        if body is None:
            return
        ids = body.get("ids") or []
        if not isinstance(ids, list):
            ids = []
        n = journal_alerts.mark_delivered([int(i) for i in ids])
        self._send_json({"ok": True, "marked": n})

    def _handle_alerts_behavioral_check(self) -> None:
        try:
            fired = journal_alerts.check_behavioral_alerts()
            # После генерации уведомлений сразу пытаемся доставить через Web Push
            if fired:
                try:
                    journal_alerts.deliver_pending_notifications()
                except Exception:
                    pass
            self._send_json({"ok": True, "fired": fired})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_brief_add_watchlist(self, user_id: str = "default") -> None:
        body = self._read_body_json()
        if body is None:
            return
        symbol = str(body.get("symbol", "")).strip().upper()
        if not symbol:
            self._send_json({"error": "symbol required"}, 400)
            return
        journal_brief.add_to_watchlist(symbol, user_id)
        journal_brief.invalidate_cache()
        self._send_json({"ok": True, "symbol": symbol})

    # ── Setups handlers (Part 6) ──────────────────────────────────────────────

    def _handle_setups_create(self, user_id: str = "default") -> None:
        body = self._read_body_json()
        if body is None:
            return
        required = {"symbol", "timeframe", "pattern_key", "thesis"}
        missing = required - set(body.keys())
        if missing:
            self._send_json({"error": f"missing: {', '.join(missing)}"}, 400)
            return
        try:
            result = journal_setups.add_setup(body, user_id)
            self._send_json(result, 201)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_setups_update(self, setup_id: int, user_id: str = "default") -> None:
        body = self._read_body_json()
        if body is None:
            return
        ok = journal_setups.update_setup(setup_id, body, user_id)
        self._send_json({"ok": ok}, 200 if ok else 404)

    def _handle_setups_link_trade(self, setup_id: int) -> None:
        body = self._read_body_json()
        if body is None:
            return
        trade_id = body.get("trade_id")
        if not trade_id:
            self._send_json({"error": "trade_id required"}, 400)
            return
        ok = journal_setups.link_trade(setup_id, int(trade_id))
        self._send_json({"ok": ok}, 200 if ok else 404)

    def _handle_setups_update_status(self, setup_id: int) -> None:
        body = self._read_body_json()
        if body is None:
            return
        status = str(body.get("status", ""))
        if status not in journal_setups.VALID_STATUSES:
            self._send_json({"error": f"status must be one of {journal_setups.VALID_STATUSES}"}, 400)
            return
        ok = journal_setups.update_status(setup_id, status)
        self._send_json({"ok": ok}, 200 if ok else 404)

    # ── Part 8: Gamification ─────────────────────────────────────────────────

    def _handle_gamification_award_xp(self, user_id: str = "default") -> None:
        body = self._read_body_json()
        if body is None:
            return
        kind = str(body.get("kind", "manual"))
        amount = int(body.get("amount", 0))
        if amount <= 0:
            self._send_json({"error": "amount must be > 0"}, 400)
            return
        total = journal_gamification.award_xp(kind, amount, user_id=user_id)
        self._send_json({"ok": True, "total_xp": total, "level": journal_gamification.calc_level(total)})

    def _handle_flashcard_review(self, user_id: str = "default") -> None:
        body = self._read_body_json()
        if body is None:
            return
        card_id = body.get("card_id")
        quality = body.get("quality")
        if card_id is None or quality is None:
            self._send_json({"error": "card_id and quality required"}, 400)
            return
        result = journal_gamification.review_flashcard(int(card_id), int(quality), user_id)
        # Fire daily_login streak on any review
        journal_gamification.update_streak(user_id, "daily_login")
        self._send_json(result)

    def _handle_course_complete(self, user_id: str = "default") -> None:
        body = self._read_body_json()
        if body is None:
            return
        chapter_n = body.get("chapter_number")
        if not chapter_n:
            self._send_json({"error": "chapter_number required"}, 400)
            return
        self._send_json(journal_gamification.complete_chapter(int(chapter_n), user_id))

    def _handle_academy_quiz_attempt(self, user_id: str = "default") -> None:
        body = self._read_body_json()
        if body is None:
            return
        level_id = body.get("level_id")
        question_id = body.get("question_id")
        correct = body.get("correct")
        if not level_id or not question_id or correct is None:
            self._send_json({"error": "level_id, question_id and correct required"}, 400)
            return
        self._send_json(journal_gamification.record_quiz_attempt(
            str(level_id), str(question_id), bool(correct), user_id))

    def _handle_streak_freeze(self, user_id: str = "default") -> None:
        body = self._read_body_json()
        if body is None:
            return
        kind = str(body.get("kind", "daily_login"))
        self._send_json(journal_gamification.use_streak_freeze(user_id, kind))

    def _handle_quest_event(self, user_id: str = "default") -> None:
        body = self._read_body_json()
        if body is None:
            return
        event_type = str(body.get("type", ""))
        meta = body.get("meta") or {}
        newly = journal_gamification.process_quest_event(user_id, event_type, meta)
        journal_gamification.update_streak(user_id, "daily_login")
        self._send_json({"newly_completed": newly})

    # ── Part 7: Checklist & Tilt ──────────────────────────────────────────────

    def _handle_checklist_add_item(self, user_id: str = "default") -> None:
        body = self._read_body_json()
        if body is None:
            return
        text = str(body.get("text", "")).strip()
        if not text:
            self._send_json({"error": "text required"}, 400)
            return
        item = journal_tilt.add_checklist_item(text, user_id)
        self._send_json(item, 201)

    def _handle_checklist_run(self, user_id: str = "default") -> None:
        body = self._read_body_json()
        if body is None:
            return
        checked_ids = body.get("checked_ids") or []
        if not isinstance(checked_ids, list):
            self._send_json({"error": "checked_ids must be a list"}, 400)
            return
        result = journal_tilt.save_checklist_run([int(i) for i in checked_ids], user_id)
        # Auto-trigger tilt check after run
        tilt = journal_tilt.run_tilt_check(user_id)
        result["tilt"] = tilt
        # Award XP if checklist passed
        if result.get("passed"):
            try:
                xp_result = journal_gamification.on_checklist_passed(result.get("id", 0), user_id)
                result["xp_awarded"] = xp_result.get("xp_awarded", 0)
            except Exception:
                pass
        self._send_json(result, 201)

    def _handle_goal_create(self, user_id: str = "default") -> None:
        body = self._read_body_json()
        if body is None:
            return
        kind = body.get("kind")
        target = body.get("target") or body.get("target_value")
        if not kind or target is None:
            self._send_json({"error": "kind and target required"}, 400)
            return
        try:
            result = journal_goals.add_goal(
                kind=kind,
                target_value=float(target),
                label=body.get("label") or "",
                deadline_days=int(body.get("deadline_days", 30)),
                user_id=user_id,
            )
            self._send_json(result, 201)
        except (ValueError, TypeError) as e:
            self._send_json({"error": str(e)}, 400)

    # ── Auth / Onboarding handlers ───────────────────────────────────────────

    def _auth_token(self) -> str:
        """Извлекает токен из заголовка X-Auth-Token, Authorization: Bearer,
        или куки sbf_session (в этом порядке).
        journal.html's _authHdr() отправляет именно Bearer — раньше сервер его
        не читал вообще (TZ-детект/MT4-импорт/cooldown/review/analytics/prestige
        были из-за этого молча сломаны), плюс SBFAcademy-мост должен работать
        независимо от того, какой из двух заголовков прислал конкретный файл.
        Кука — SPEC_chart_fixes_and_staged_signup.md §5: обычная навигация
        страницы (не fetch/XHR) не может приложить кастомный заголовок, а
        серверный гейт PRO-глав (_handle_edu) должен знать, кто пришёл, именно
        на такой навигации. web/assets/sbf-auth.js дублирует тот же токен в
        куку sbf_session при каждом setTokens (логин/регистрация/тихий refresh)."""
        token = self.headers.get("X-Auth-Token", "")
        if token:
            return token
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:]
        cookie_header = self.headers.get("Cookie", "")
        for part in cookie_header.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "sbf_session" and value:
                return unquote(value)
        return ""

    def _current_user_id(self) -> str:
        """Резолвит user_id из токена запроса, или 'default' для анонимных
        визитёров (сохраняет прежнее поведение для гостей). Раньше почти
        каждый POST-обработчик ниже либо вообще не резолвил токен, либо
        передавал буквально строку "default" — из-за этого залогиненный
        пользователь читал/писал в общий анонимный набор данных, а не в свой."""
        return journal_auth.validate_session(self._auth_token()) or "default"

    def _effective_user_id(self, user_id: str) -> str:
        """user_id ('default', если сессии нет) с фолбэком на анонимный ID
        (заголовок X-Anon-Id, web/assets/sbf-anon.js) — ТОЛЬКО для прогресса
        по главам курса (SPEC_chart_fixes_and_staged_signup.md §5, Этап 0).
        Не меняет поведение _current_user_id() в остальных ручках -- вызывается
        точечно в get_course_progress/complete_chapter, не глобально: смешивать
        анонимную identity с "default"-бакетом торговых данных (сделки/
        дисциплина/цели) отдельный, гораздо более рискованный шаг, спека его
        не просит."""
        if user_id != "default":
            return user_id
        anon_id = self.headers.get("X-Anon-Id", "").strip()[:128]
        return anon_id or "default"

    def _handle_auth_register(self) -> None:
        body = self._read_body_json()
        if body is None:
            return
        result = journal_auth.register(
            email=body.get("email", ""),
            password=body.get("password", ""),
            first_name=body.get("first_name", ""),
            last_name=body.get("last_name", ""),
            phone=body.get("phone", ""),
            lang=body.get("lang", "ru"),
            age_18_confirmed=bool(body.get("age_18_confirmed")),
            consent_data=bool(body.get("consent_data")),
            consent_disclaimer=bool(body.get("consent_disclaimer")),
            consent_marketing=bool(body.get("consent_marketing", False)),
        )
        # SPEC_chart_fixes_and_staged_signup.md §5, Этап 0: анонимный прогресс
        # по главам (web/assets/sbf-anon.js) переносится на настоящего
        # пользователя ровно один раз, здесь, в момент когда он появляется.
        anon_id = str(body.get("anon_id") or "").strip()[:128]
        if anon_id and result.get("user_id"):
            journal_gamification.migrate_anon_progress(anon_id, result["user_id"])
        # Источник перехода и лид в CRM (27.08.2026). Здесь опроса ещё нет —
        # карточка создаётся «тонкой», а ответы к ней добавит
        # crm_leads.enrich_with_survey(), когда человек дойдёт до опроса.
        if result.get("user_id"):
            attrib = body.get("attrib") or {}
            if attrib:
                try:
                    journal_auth.save_attribution(result["user_id"], attrib)
                except Exception:
                    pass
            try:
                from core import crm_leads
                crm_leads.create_lead(
                    email=(body.get("email") or "").strip().lower(),
                    name=" ".join(x for x in (body.get("first_name"), body.get("last_name")) if x).strip(),
                    attrib=attrib)
            except Exception as e:
                log.error("CRM: лид не создан (обычная регистрация) — %s", e)
        status = 400 if "error" in result else 201
        self._send_json(result, status)

    def _handle_survey_status(self) -> None:
        token = self._auth_token()
        user_id = journal_auth.validate_session(token)
        if not user_id:
            self._send_json({"done": False, "pro_until": None})
            return
        self._send_json(journal_auth.get_survey_status(user_id))

    def _handle_auth_login(self) -> None:
        body = self._read_body_json()
        if body is None:
            return
        client_ip = self.client_address[0] if self.client_address else ""
        result = journal_auth.login(body.get("email", ""), body.get("password", ""), client_ip)
        if result.get("error") == "rate_limit":
            self._send_json(result, 429)
            return
        status = 401 if "error" in result else 200
        self._send_json(result, status)

    def _handle_auth_logout(self) -> None:
        token = self._auth_token()
        self._send_json({"ok": journal_auth.logout(token)})

    def _handle_auth_me(self) -> None:
        """SBF_Charts_Layer4_Spec, Фаза 1.1: единый auth-контекст на всех
        экранах. Базовая форма — уже существующий journal_auth.get_user()
        (id/email/first_name/.../prefs) — здесь только добавлен ЖИВОЙ ватчлист
        (journal_brief.watchlist — та же таблица, что уже использует
        journal_alerts.py) верхним полем `watchlist`, а НЕ user_prefs.
        watchlist_markets (тот заполняется один раз при онбординге и с тех пор
        не читается ни одной другой фичей проекта — снапшот, не источник
        истины)."""
        token = self._auth_token()
        user_id = journal_auth.validate_session(token)
        if not user_id:
            self._send_json({"error": "unauthorized"}, 401)
            return
        user = journal_auth.get_user(user_id)
        if user:
            user["watchlist"] = journal_brief.get_watchlist(user_id)
            user["pinned"] = journal_brief.get_pinned(user_id)  # Focus Engine §6
        self._send_json(user or {"error": "not found"})

    def _handle_unsubscribe(self) -> None:
        """Отписка от рассылки по ссылке из письма — без входа в аккаунт.

        🔴 Требовать вход здесь нельзя. Человек, которому надоели письма, не
        станет вспоминать пароль — он нажмёт «Спам», и пострадает домен, с
        которого уходят коды входа. Одно нажатие должно работать.
        Подпись в ссылке защищает от подстановки чужого id: без неё отписать
        любого мог бы кто угодно, подобрав идентификатор.
        """
        params = parse_qs(urlparse(self.path).query)
        user_id = (params.get("u", [""])[0] or "").strip()
        token = (params.get("t", [""])[0] or "").strip()
        ok = False
        if user_id and token:
            import hashlib
            import hmac as _hmac
            secret = (journal_auth._SBF_JWT_SECRET or "").encode()
            expected = _hmac.new(secret, f"unsub:{user_id}".encode(),
                                 hashlib.sha256).hexdigest()[:32]
            if _hmac.compare_digest(expected, token):
                try:
                    con = sqlite3.connect(str(Path(DIRECTORY).parent / "data" / "journal.db"))
                    con.execute("UPDATE users SET consent_marketing = 0 WHERE id = ?", (user_id,))
                    con.commit()
                    con.close()
                    ok = True
                except Exception as e:
                    print(f"отписка {user_id}: {e}", flush=True)
        body = ("<h2>Вы отписаны</h2><p>Больше не будем присылать утренний брифинг. "
                "Вернуть рассылку можно в профиле на платформе.</p>" if ok else
                "<h2>Ссылка не сработала</h2><p>Возможно, она устарела. "
                "Отписаться можно в профиле на платформе.</p>")
        html = ("<!doctype html><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<body style=\"font-family:-apple-system,Segoe UI,Arial,sans-serif;"
                "background:#FBF6EF;color:#2B2B33;display:flex;min-height:90vh;"
                "align-items:center;justify-content:center;text-align:center\">"
                f"<div style='max-width:420px;padding:20px'>{body}"
                "<p><a href='/' style='color:#C9A227'>На платформу →</a></p></div></body>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _handle_user_watchlist_news(self) -> None:
        """Что нового по инструментам, отмеченным звездой.

        Ленту наполняет watchlist_news_job.py; здесь только чтение. Считать её
        на лету по каждому запросу значило бы гонять соединение JOIN по 20 тыс.
        тегов на каждое открытие страницы — ровно тот путь, который уже привёл
        нас к однопоточному серверу в очереди за мостом.
        """
        user_id = self._lp_require_auth()
        if not user_id:
            return
        try:
            limit = min(int(parse_qs(urlparse(self.path).query).get("limit", ["30"])[0]), 100)
        except ValueError:
            limit = 30
        try:
            con = sqlite3.connect(str(Path(DIRECTORY).parent / "data" / "journal.db"))
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT symbol, title, url, source, ts, seen FROM watchlist_feed "
                "WHERE user_id = ? ORDER BY ts DESC LIMIT ?", (user_id, limit)).fetchall()
            unseen = con.execute(
                "SELECT COUNT(*) FROM watchlist_feed WHERE user_id = ? AND seen = 0",
                (user_id,)).fetchone()[0]
            con.close()
            self._send_json({"items": [dict(r) for r in rows], "unseen": unseen})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_user_watchlist_put(self) -> None:
        """SBF_Charts_Layer4_Spec, Фаза 1.3: PUT — полная замена ватчлиста
        (редактор — чипы+drag, не инкрементальный add/remove, отсюда PUT а не
        POST/DELETE как в старом /api/journal/watchlist). Валидация — против
        символов ГРАФИКА (_chart_symbols()), не journal_brief.
        get_available_symbols() (тот из другого домена, см. комментарий в
        _chart_symbols)."""
        user_id = self._lp_require_auth()
        if not user_id:
            return
        body = self._read_body_json()
        if body is None:
            return
        symbols = body.get("symbols")
        if not isinstance(symbols, list):
            self._send_json({"error": "symbols must be a list"}, 400)
            return
        if len(symbols) > 10:
            self._send_json({"error": "max 10 symbols"}, 400)
            return
        # Ватчлист принимает всё, что платформа умеет нарисовать, включая
        # каталог брокера (ярус 3). Выпадающий СПИСОК при этом остаётся
        # именованным реестром — см. /api/chart/symbols.
        valid = _chartable_symbols()
        cleaned = []
        for s in symbols:
            if not isinstance(s, str):
                continue
            su = s.upper().strip()
            if su in valid and su not in cleaned:
                cleaned.append(su)
        result = journal_brief.set_watchlist(cleaned, user_id)
        self._send_json({"ok": True, "watchlist": result})

    def _handle_user_watchlist_pin_put(self) -> None:
        """SPEC_focus_engine.md §6: {"symbol": "GOLD"} закрепляет (снимая
        любой прежний пин у этого пользователя — максимум один), {"symbol":
        null} снимает. Анонимам недоступно (_lp_require_auth, как и обычный
        watchlist PUT) -- пин это приватное намерение пользователя, не
        публичный факт рынка."""
        user_id = self._lp_require_auth()
        if not user_id:
            return
        body = self._read_body_json()
        if body is None:
            return
        symbol = body.get("symbol")
        if symbol is not None and not isinstance(symbol, str):
            self._send_json({"error": "symbol must be a string or null"}, 400)
            return
        ok = journal_brief.set_pinned(symbol, user_id)
        if not ok:
            self._send_json({"error": "symbol not in watchlist"}, 400)
            return
        self._send_json({"ok": True, "pinned": journal_brief.get_pinned(user_id)})

    def _handle_user_chart_prefs_put(self) -> None:
        """SBF_Charts_Layer4_Spec, Фаза 1.4 (тогглы слоёв) + 1.2.3 (последний
        просмотренный инструмент) — см. journal_auth.update_chart_prefs()."""
        user_id = self._lp_require_auth()
        if not user_id:
            return
        body = self._read_body_json()
        if body is None:
            return
        layers = body.get("layers")
        last_symbol = body.get("last_symbol")
        if layers is not None and not isinstance(layers, dict):
            self._send_json({"error": "layers must be an object"}, 400)
            return
        if last_symbol is not None:
            if not isinstance(last_symbol, str) or last_symbol.upper() not in _chartable_symbols():
                self._send_json({"error": "invalid last_symbol"}, 400)
                return
            last_symbol = last_symbol.upper()
        result = journal_auth.update_chart_prefs(user_id, layers=layers, last_symbol=last_symbol)
        self._send_json(result, 200 if result.get("ok") else 400)

    def _handle_auth_profile_put(self) -> None:
        """SPEC_chart_fixes_and_staged_signup.md §5, Этап 2 — форма внутри
        главы 4 (имя/фамилия/телефон/дата рождения), см. journal_auth.
        update_profile(). Телефон — отдельный явный флажок consent_phone,
        не общий consent_data."""
        user_id = self._lp_require_auth()
        if not user_id:
            return
        body = self._read_body_json()
        if body is None:
            return
        phone = str(body.get("phone") or "")
        if phone and not body.get("consent_phone"):
            self._send_json({"error": "consent_phone required with phone"}, 400)
            return
        result = journal_auth.update_profile(
            user_id,
            last_name=str(body.get("last_name") or ""),
            phone=phone,
            dob=str(body.get("dob") or ""),
            consent_phone=bool(body.get("consent_phone")),
        )
        self._send_json(result, 200 if result.get("ok") else 400)

    def _handle_user_trading_window_put(self) -> None:
        """SPEC_morning_brief_v2.md блок 6 — сохранить окно из MyWindowBlock
        (edu_book_5.html), см. journal_auth.update_trading_window()."""
        user_id = self._lp_require_auth()
        if not user_id:
            return
        body = self._read_body_json()
        if body is None:
            return
        start_h = body.get("start_h")
        end_h = body.get("end_h")
        archetype = body.get("archetype")
        result = journal_auth.update_trading_window(user_id, start_h, end_h, archetype)
        self._send_json(result, 200 if result.get("ok") else 400)

    def _handle_auth_my_path(self) -> None:
        token = self._auth_token()
        user_id = journal_auth.validate_session(token)
        if not user_id:
            self._send_json({"error": "unauthorized"}, 401)
            return
        self._send_json(journal_auth.get_my_path(user_id))

    def _handle_auth_onboarding(self) -> None:
        body = self._read_body_json()
        if body is None:
            return
        token = self._auth_token() or body.get("token", "")
        user_id = journal_auth.validate_session(token)
        if not user_id:
            self._send_json({"error": "unauthorized"}, 401)
            return
        answers = body.get("answers", {})
        if not isinstance(answers, dict):
            self._send_json({"error": "answers must be an object"}, 400)
            return
        result = journal_auth.save_onboarding_answers(user_id, answers)
        path = journal_auth.get_my_path(user_id)
        result["path"] = path
        # Опрос пройден уже зарегистрированным человеком (пришёл с /register
        # раньше, а до опроса дошёл позже) — ДОПОЛНЯЕМ его карточку в CRM,
        # а не заводим вторую. Поиск по почте внутри enrich_with_survey.
        try:
            from core import crm_leads
            prof = journal_auth.get_user(user_id)
            email = (prof or {}).get("email")
            if email and answers:
                crm_leads.enrich_with_survey(email=email, answers=answers,
                                             pro_until=result.get("pro_until"))
        except Exception as e:
            log.error("CRM: карточка не дополнена опросом — %s", e)
        self._send_json(result)

    # ── Feedback handlers ────────────────────────────────────────────────────

    def _handle_feedback_submit(self) -> None:
        body = self._read_body_json(max_bytes=10_000_000)
        if body is None:
            return
        token = self._auth_token() or body.get("token", "")
        user_id = journal_auth.validate_session(token) if token else None
        # Rate limit by user_id or IP
        rl_key = user_id or self.client_address[0]
        if not journal_feedback.check_rate_limit(rl_key, limit=5, window=3600):
            self._send_json({"error": "rate_limit", "msg": "Максимум 5 отзывов в час"}, 429)
            return
        result = journal_feedback.submit_feedback(
            user_id=user_id,
            kind=body.get("kind", "other"),
            comment=body.get("comment", ""),
            page_url=body.get("page_url", ""),
            screenshot_b64=body.get("screenshot_b64"),
            ua=body.get("ua", ""),
            viewport=body.get("viewport", ""),
        )
        self._send_json(result, 201 if result.get("ok") else 400)

    def _handle_feedback_vote(self) -> None:
        body = self._read_body_json()
        if body is None:
            return
        token = self._auth_token() or body.get("token", "")
        user_id = journal_auth.validate_session(token) if token else None
        if not user_id:
            self._send_json({"error": "unauthorized"}, 401)
            return
        cluster_id = body.get("cluster_id", "")
        if not cluster_id:
            self._send_json({"error": "cluster_id required"}, 400)
            return
        # Вес = уровень пользователя
        try:
            xp = journal_gamification.get_xp_total()
            lvl_info = journal_gamification.calc_level(xp)
            weight = max(1, int(lvl_info.get("level", 1)))
        except Exception:
            weight = 1
        result = journal_feedback.vote_on_cluster(cluster_id, user_id, weight)
        self._send_json(result)

    # ── Admin handlers ───────────────────────────────────────────────────────

    def _admin_auth(self):
        """Возвращает user_id если это admin, иначе отправляет 403 и None."""
        token = self._auth_token()
        user_id = journal_auth.validate_session(token) if token else None
        if not user_id or not journal_feedback.is_admin(user_id):
            self._send_json({"error": "forbidden"}, 403)
            return None
        return user_id

    def _handle_admin_me(self) -> None:
        token = self._auth_token()
        user_id = journal_auth.validate_session(token) if token else None
        if not user_id:
            self._send_json({"error": "unauthorized"}, 401)
            return
        user = journal_auth.get_user(user_id) or {}
        user["is_admin"] = journal_feedback.is_admin(user_id)
        self._send_json(user)

    def _handle_admin_get_clusters(self) -> None:
        if not self._admin_auth():
            return
        from urllib.parse import parse_qs, urlparse as _up
        params = parse_qs(_up(self.path).query)
        status = params.get("status", [None])[0]
        clusters = journal_feedback.get_clusters(status=status)
        self._send_json({"clusters": clusters})

    def _handle_admin_get_cluster(self, cluster_id: str) -> None:
        if not self._admin_auth():
            return
        feedbacks = journal_feedback.get_cluster_feedbacks(cluster_id)
        self._send_json({"cluster_id": cluster_id, "feedbacks": feedbacks})

    def _handle_admin_set_status(self, cluster_id: str) -> None:
        admin_uid = self._admin_auth()
        if not admin_uid:
            return
        body = self._read_body_json() or {}
        self._send_json(
            journal_feedback.update_cluster_status(cluster_id, body.get("status", ""), admin_uid)
        )

    def _handle_admin_set_title(self, cluster_id: str) -> None:
        admin_uid = self._admin_auth()
        if not admin_uid:
            return
        body = self._read_body_json() or {}
        self._send_json(
            journal_feedback.update_cluster_title(cluster_id, body.get("title", ""))
        )

    def _handle_admin_merge_clusters(self) -> None:
        admin_uid = self._admin_auth()
        if not admin_uid:
            return
        body = self._read_body_json() or {}
        source = body.get("source_id", "")
        target = body.get("target_id", "")
        if not source or not target:
            self._send_json({"error": "source_id and target_id required"}, 400)
            return
        self._send_json(journal_feedback.merge_clusters(source, target, admin_uid))

    def _handle_admin_create_cluster(self) -> None:
        admin_uid = self._admin_auth()
        if not admin_uid:
            return
        body = self._read_body_json() or {}
        ids = body.get("feedback_ids", [])
        title = body.get("title", "")
        if not ids:
            self._send_json({"error": "feedback_ids required"}, 400)
            return
        self._send_json(journal_feedback.create_cluster_from_feedbacks(ids, title))

    def _handle_admin_split_feedback(self, feedback_id: str) -> None:
        admin_uid = self._admin_auth()
        if not admin_uid:
            return
        self._send_json(journal_feedback.split_feedback_from_cluster(feedback_id, admin_uid))

    def _handle_admin_unassigned(self) -> None:
        if not self._admin_auth():
            return
        feedbacks = journal_feedback.get_unassigned_feedback(limit=200)
        self._send_json({"feedbacks": feedbacks})

    def _handle_admin_bootstrap(self) -> None:
        body = self._read_body_json() or {}
        token = self._auth_token() or body.get("token", "")
        user_id = journal_auth.validate_session(token) if token else None
        if not user_id:
            self._send_json({"error": "unauthorized"}, 401)
            return
        self._send_json(journal_feedback.bootstrap_admin(user_id))

    # ── site_copy handlers ───────────────────────────────────────────────────

    def _handle_copy_get(self, copy_id: str) -> None:
        text = journal_feedback.get_copy(copy_id)
        if text is None:
            self._send_json({"error": "not found"}, 404)
            return
        self._send_json({"copy_id": copy_id, "text": text})

    def _handle_copy_batch(self) -> None:
        from urllib.parse import parse_qs, urlparse as _up
        params = parse_qs(_up(self.path).query)
        ids_raw = params.get("ids", [""])[0]
        ids = [i.strip() for i in ids_raw.split(",") if i.strip()]
        if not ids:
            self._send_json({"items": []})
            return
        items = []
        for cid in ids[:50]:
            text = journal_feedback.get_copy(cid)
            if text is not None:
                items.append({"copy_id": cid, "text_current": text})
        self._send_json({"items": items})

    def _handle_copy_all(self) -> None:
        if not self._admin_auth():
            return
        items = journal_feedback.get_all_copy()
        self._send_json({"items": items})

    def _handle_copy_upsert(self, copy_id: str) -> None:
        admin_uid = self._admin_auth()
        if not admin_uid:
            return
        body = self._read_body_json() or {}
        text = body.get("text", "")
        page = body.get("page", "")
        self._send_json(journal_feedback.upsert_copy(copy_id, text, page, updated_by=admin_uid))

    def _handle_copy_reset(self, copy_id: str) -> None:
        if not self._admin_auth():
            return
        self._send_json(journal_feedback.reset_copy_to_default(copy_id))

    # ── MT4/MT5 import ──────────────────────────────────────────────────────────

    def _handle_mt_import(self) -> None:
        import base64 as _b64
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 5_000_000:
            self._send_json({"error": "file_too_large"}, 413)
            return
        raw = self.rfile.read(content_length)
        if not raw:
            self._send_json({"error": "empty body"}, 400)
            return
        token = self._auth_token()
        user_id = journal_auth.validate_session(token) if token else "default"
        filename = self.headers.get("X-Filename", "upload.html")
        tz_override = None

        # Try JSON envelope with base64 data
        body_bytes = raw
        try:
            payload = json.loads(raw.decode("utf-8"))
            if isinstance(payload, dict) and "data" in payload:
                body_bytes = _b64.b64decode(payload["data"])
                if "broker_tz_offset" in payload:
                    tz_override = int(payload["broker_tz_offset"])
        except Exception:
            pass  # treat raw as file bytes directly

        # broker_tz_offset: request payload > user_prefs
        tz_offset = tz_override if tz_override is not None else 0
        if tz_override is None and user_id and user_id != "default":
            try:
                import sqlite3 as _sq3
                _db = Path(__file__).parent / "data" / "journal.db"
                _c = _sq3.connect(str(_db))
                _row = _c.execute("SELECT broker_tz_offset FROM user_prefs WHERE user_id=?", (user_id,)).fetchone()
                _c.close()
                if _row and _row[0] is not None:
                    tz_offset = int(_row[0])
            except Exception:
                pass

        rows, errors = journal_import.parse_file(filename, body_bytes, tz_offset)
        result = journal_import.import_trades(rows, user_id=user_id, filename=filename)
        result["parse_errors"] = errors
        self._send_json(result)

    def _handle_import_history(self) -> None:
        token = self._auth_token()
        user_id = journal_auth.validate_session(token) if token else "default"
        self._send_json({"history": journal_import.get_import_history(user_id)})

    # ── Analytics ────────────────────────────────────────────────────────────────

    def _handle_analytics_discipline_cost(self) -> None:
        from urllib.parse import parse_qs, urlparse as _up
        params = parse_qs(_up(self.path).query)
        period = params.get("period", ["90d"])[0]
        token = self._auth_token()
        user_id = journal_auth.validate_session(token) if token else "default"
        self._send_json(journal_analytics.get_discipline_cost(user_id, period))

    def _handle_analytics_setups(self) -> None:
        from urllib.parse import parse_qs, urlparse as _up
        params = parse_qs(_up(self.path).query)
        period = params.get("period", ["90d"])[0]
        token = self._auth_token()
        user_id = journal_auth.validate_session(token) if token else "default"
        self._send_json(journal_analytics.get_setup_analytics(user_id, period))

    def _handle_log_violation(self) -> None:
        body = self._read_body_json() or {}
        trade_id = body.get("trade_id")
        rule_key = body.get("rule_key", "")
        if not trade_id or not rule_key:
            self._send_json({"error": "trade_id and rule_key required"}, 400)
            return
        journal_analytics.log_violation(int(trade_id), rule_key)
        self._send_json({"ok": True})

    # ── Weekly Review ────────────────────────────────────────────────────────────

    def _handle_review_current(self) -> None:
        token = self._auth_token()
        user_id = journal_auth.validate_session(token) if token else "default"
        stats = journal_review.get_auto_stats(user_id)
        existing = journal_review.get_this_week_review(user_id)
        prev_reflection = journal_review.get_prev_reflection(user_id)
        self._send_json({
            "stats": stats,
            "existing_review": existing,
            "prev_reflection": prev_reflection,
        })

    def _handle_review_submit(self) -> None:
        body = self._read_body_json()
        if body is None:
            return
        token = self._auth_token() or body.get("token", "")
        user_id = journal_auth.validate_session(token) if token else "default"
        result = journal_review.submit_review(
            user_id=user_id,
            week_iso=body.get("week_iso"),
            reflection=body.get("reflection", ""),
            best_trade_id=body.get("best_trade_id"),
            worst_trade_id=body.get("worst_trade_id"),
        )
        status = result.pop("status", 200) if "error" in result else 201
        self._send_json(result, status)

    def _handle_review_history(self) -> None:
        token = self._auth_token()
        user_id = journal_auth.validate_session(token) if token else "default"
        self._send_json({"reviews": journal_review.get_reviews(user_id)})

    # ── Cooldown / Debrief ───────────────────────────────────────────────────────

    def _handle_cooldown_break(self) -> None:
        body = self._read_body_json() or {}
        token = self._auth_token() or body.get("token", "")
        user_id = journal_auth.validate_session(token) if token else "default"
        self._send_json(journal_cooldown.mark_broken(user_id))

    def _handle_cooldown_accept(self) -> None:
        body = self._read_body_json() or {}
        token = self._auth_token() or body.get("token", "")
        user_id = journal_auth.validate_session(token) if token else "default"
        accept = body.get("accept", False)
        trigger = body.get("trigger", "loss_streak")
        if not accept:
            self._send_json(journal_cooldown.reject_cooldown(user_id))
            return
        # Получить tz_offset
        tz_offset = 120
        try:
            _db = Path(__file__).parent / "data" / "journal.db"
            import sqlite3 as _sq
            _c = _sq.connect(str(_db))
            _row = _c.execute("SELECT broker_tz_offset, tz FROM user_prefs WHERE user_id=?", (user_id,)).fetchone()
            _c.close()
            if _row and _row[0] is not None:
                tz_offset = int(_row[0])
        except Exception:
            pass
        result = journal_cooldown.accept_cooldown(user_id, trigger=trigger, tz_offset_min=tz_offset)
        self._send_json(result)

    def _handle_cooldown_active(self) -> None:
        token = self._auth_token()
        user_id = journal_auth.validate_session(token) if token else "default"
        active = journal_cooldown.get_active_cooldown(user_id)
        self._send_json({"active": active})

    def _handle_cooldown_stats(self) -> None:
        token = self._auth_token()
        user_id = journal_auth.validate_session(token) if token else "default"
        self._send_json(journal_cooldown.get_cooldown_stats(user_id))

    def _handle_debrief_submit(self) -> None:
        body = self._read_body_json()
        if body is None:
            return
        token = self._auth_token() or body.get("token", "")
        user_id = journal_auth.validate_session(token) if token else "default"
        result = journal_cooldown.submit_debrief(
            user_id=user_id,
            alert_id=body.get("alert_id"),
            q1=body.get("q1", ""),
            q2=body.get("q2", ""),
            q3=body.get("q3", ""),
        )
        status = result.pop("status", 200) if "error" in result else 201
        self._send_json(result, status)

    def _handle_debriefs_list(self) -> None:
        token = self._auth_token()
        user_id = journal_auth.validate_session(token) if token else "default"
        self._send_json({"debriefs": journal_cooldown.get_debriefs(user_id)})

    # ── Auth: TZ / broker_tz / prestige ─────────────────────────────────────────

    def _handle_auth_update_tz(self) -> None:
        body = self._read_body_json() or {}
        token = self._auth_token() or body.get("token", "")
        user_id = journal_auth.validate_session(token) if token else None
        if not user_id:
            self._send_json({"error": "unauthorized"}, 401)
            return
        self._send_json(journal_auth.update_tz(user_id, body.get("tz", "")))

    def _handle_auth_broker_tz(self) -> None:
        body = self._read_body_json() or {}
        token = self._auth_token() or body.get("token", "")
        user_id = journal_auth.validate_session(token) if token else None
        if not user_id:
            self._send_json({"error": "unauthorized"}, 401)
            return
        offset = body.get("offset_minutes")
        if offset is None:
            self._send_json({"error": "offset_minutes required"}, 400)
            return
        self._send_json(journal_auth.update_broker_tz(user_id, int(offset)))

    def _handle_auth_prestige(self) -> None:
        token = self._auth_token()
        user_id = journal_auth.validate_session(token) if token else None
        if not user_id:
            self._send_json({"error": "unauthorized"}, 401)
            return
        self._send_json(journal_auth.prestige(user_id))

    # ── LP gated endpoints ────────────────────────────────────────────────────

    def _lp_require_auth(self) -> str | None:
        """Returns user_id or sends 401 and returns None."""
        token = self._auth_token()
        user_id = journal_auth.validate_session(token) if token else None
        if not user_id:
            self._send_json({"gate": True, "error": "unauthorized"}, 401)
            return None
        return user_id





    def _handle_register_via_survey(self) -> None:
        body = self._read_body_json()
        if body is None:
            return
        client_ip = self.client_address[0]
        if not journal_auth._rate_check_register(client_ip):
            self._send_json({"error": "Слишком много регистраций с этого IP. Попробуй через час."}, 429)
            return
        email    = (body.get("email") or "").strip().lower()
        password = body.get("password") or ""
        name     = (body.get("name") or "").strip()
        age_ok   = bool(body.get("age_18_confirmed"))
        consent_data  = bool(body.get("consent_data"))
        consent_disc  = bool(body.get("consent_disclaimer"))
        consent_mkt   = bool(body.get("consent_marketing", False))
        answers  = body.get("answers") or {}

        result = journal_auth.register(
            email=email, password=password,
            first_name=name, last_name="",
            age_18_confirmed=age_ok,
            consent_data=consent_data,
            consent_disclaimer=consent_disc,
            consent_marketing=consent_mkt,
        )
        if "error" in result:
            if "зарегистрирован" in result["error"]:
                self._send_json({"error": result["error"], "email_exists": True}, 409)
            else:
                self._send_json(result, 400)
            return

        user_id = result["user_id"]
        # Save survey answers if provided
        if answers:
            try:
                journal_auth.save_onboarding_answers(user_id, answers)
            except Exception:
                pass
        # Источник перехода (27.08.2026). До этого метки кампаний не доезжали
        # до регистрации вообще: полей под них здесь не было, и ответить
        # «из какого ролика пришёл этот человек» было нечем. Ошибка не роняет
        # регистрацию — аккаунт важнее метки.
        attrib = body.get("attrib") or {}
        if attrib:
            try:
                journal_auth.save_attribution(user_id, attrib)
            except Exception:
                pass
        # Grant PRO regardless (survey completion)
        try:
            pro = journal_auth.grant_survey_pro(user_id)
            result["pro_granted"] = True
            result["pro_until"]   = pro.get("expires_ts")
        except Exception:
            result["pro_granted"] = False

        # Лид в SBFCRM (27.08.2026). Регистрация через опрос — это сразу и
        # аккаунт, и пройденный опрос, поэтому карточка создаётся уже полной:
        # источник перехода, ответы, срок PRO. Ошибка CRM не должна отменять
        # регистрацию — человек важнее записи в чужой системе.
        try:
            from core import crm_leads
            crm_leads.create_lead(email=email, name=name, attrib=attrib,
                                  answers=answers, pro_until=result.get("pro_until"))
        except Exception as e:
            log.error("CRM: лид не создан (регистрация через опрос) — %s", e)

        self._send_json(result, 201)

    def _handle_push_subscribe(self) -> None:
        body = self._read_body_json()
        if body is None:
            return
        subscription = body.get("subscription")
        if not subscription or not isinstance(subscription, dict):
            self._send_json({"error": "subscription object required"}, 400)
            return
        result = journal_alerts.register_web_push_subscription(
            subscription_json=subscription,
            quiet_hours_start=body.get("quiet_hours_start"),
            quiet_hours_end=body.get("quiet_hours_end"),
            timezone=body.get("timezone", "UTC"),
        )
        self._send_json(result)

    def _handle_season_close(self) -> None:
        body = self._read_body_json() or {}
        season_id = body.get("season_id")
        if not season_id:
            active = journal_goals.get_active_season()
            if not active:
                self._send_json({"error": "no active season"}, 404)
                return
            season_id = active["id"]
        self._send_json(journal_goals.close_season(int(season_id)))

    # ── Part 10: Account Hub handlers ────────────────────────────────────────

    def _handle_referral_use(self, user_id: str = "default") -> None:
        body = self._read_body_json()
        if body is None:
            return
        code = (body.get("code") or "").strip()
        if not code:
            self._send_json({"error": "code required"}, 400)
            return
        self._send_json(journal_account.use_referral_code(code, user_id))

    def _handle_broker_link_add(self, user_id: str = "default") -> None:
        body = self._read_body_json()
        if body is None:
            return
        broker = (body.get("broker") or "").strip().lower()
        account_number = (body.get("account_number") or "").strip()
        if not broker or not account_number:
            self._send_json({"error": "broker and account_number required"}, 400)
            return
        result = journal_account.add_broker_link(
            user_id=user_id, broker=broker, account_number=account_number
        )
        status = 400 if "error" in result else 201
        self._send_json(result, status)

    def _handle_account_export(self, user_id: str = "default") -> None:
        data = journal_account.export_user_data(user_id)
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Disposition",
                         f'attachment; filename="sbf_journal_export_{ts}.json"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_checklist_link_trade(self, run_id: int) -> None:
        body = self._read_body_json()
        if body is None:
            return
        trade_id = body.get("trade_id")
        if not trade_id:
            self._send_json({"error": "trade_id required"}, 400)
            return
        ok = journal_tilt.link_run_to_trade(run_id, int(trade_id))
        self._send_json({"ok": ok}, 200 if ok else 404)

    def _handle_journal_save_meta(self) -> None:
        body = self._read_body_json()
        if body is None:
            return
        required = {"trade_id", "setup_tag", "emo_open", "emo_close", "followed_plan"}
        missing = required - set(body.keys())
        if missing:
            self._send_json({"error": f"missing: {', '.join(missing)}"}, 400)
            return
        try:
            tid = int(body["trade_id"])
            journal_meta.save_meta(
                tid,
                body["setup_tag"],
                body["emo_open"],
                body["emo_close"],
                bool(body["followed_plan"]),
                body.get("note", ""),
            )
            # Авто-оценка sl_used
            disc_config = journal_discipline.get_config()
            sl_c = next((c for c in disc_config if c["criterion"] == "sl_used" and c["enabled"]), None)
            if sl_c:
                sl_passed = journal_discipline.auto_eval_sl_used(tid)
                if sl_passed is not None:
                    journal_discipline.save_eval(tid, [{"criterion": "sl_used", "passed": sl_passed}])
            # XP: meta filled + discipline
            try:
                followed = bool(body.get("followed_plan", False))
                journal_gamification.on_meta_saved(tid, followed_plan=followed)
            except Exception:
                pass
            self._send_json({"ok": True})
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_journal_save_account(self, user_id: str = "default") -> None:
        body = self._read_body_json()
        if body is None:
            return
        required = {"broker", "account_no", "server", "password"}
        missing = required - set(body.keys())
        if missing:
            self._send_json({"error": f"missing: {', '.join(missing)}"}, 400)
            return
        try:
            enc, iv = journal_crypto.encrypt_password(body["password"])
            acc_id = journal_db.save_investor_account(
                body["broker"], body["account_no"],
                body["server"], enc, iv, user_id,
            )
            self._send_json({"ok": True, "id": acc_id})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_quotes(self):
        try:
            quotes, updated = fetch_quotes()
            body = json.dumps({"ok": True, "quotes": quotes, "updated": updated}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            # SPEC_fix_live_chart.md §3: quotes.json пишется раз в 15с, читался
            # раз в 8с через ?t=Date.now() (убивает браузерный кэш) на статику
            # с no-store (serve.py::end_headers). Две трети опросов получали
            # одни и те же байты полным походом до сервера. /api/quotes не
            # подпадает под общий no-store (он только для не-/api/ путей) —
            # здесь max-age вместо него. У этого эндпоинта до сих пор не было
            # ни одного потребителя в проекте (только static quotes.json
            # читали sbf-header.js/index.html/chart.html) — их не трогаем,
            # только chart.html переведён на этот путь.
            self.send_header("Cache-Control", "max-age=10")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    # Статика, которую можно и нужно кэшировать. Ключ — расширение, значение —
    # срок в секундах.
    #
    # 🔴 Правило `no-store на всё, кроме /api/` било далеко за пределы своей
    # цели. Оно писалось про HTML (см. комментарий ниже), но `end_headers`
    # вызывается и для картинок, и для шрифтов, и для скриптов, поэтому
    # браузер выбрасывал их сразу и тянул заново на каждой странице.
    # Замер на мобильном вьюпорте 390px: главная — 5799 КБ и 41 запрос,
    # график — 5795 КБ, дневник — 5832 КБ, и в каждом случае 5481 КБ из них
    # это один `logo.png`, скачиваемый заново при каждом переходе.
    # (Сам логотип тоже починен: был 4000×4000 при показе в 32–44px.)
    #
    # Скрипты и стили держим на коротком сроке: у них есть `?v=N` в ссылках,
    # но соглашение не проверяется автоматически, и забытый бамп версии при
    # годовом кэше означал бы сломанный сайт у части людей без возможности
    # это заметить. Пять минут — достаточно, чтобы переход между страницами
    # не тянул одни и те же 200 КБ, и мало, чтобы правка доехала сама.
    _STATIC_TTL = {
        ".png": 604800, ".jpg": 604800, ".jpeg": 604800, ".webp": 604800,
        ".gif": 604800, ".svg": 604800, ".ico": 604800,
        ".woff": 2592000, ".woff2": 2592000, ".ttf": 2592000,
        ".js": 300, ".css": 300, ".mjs": 300,
    }

    def end_headers(self):
        # no-store (не no-cache): без ETag/Last-Modified эти страницы нечем
        # ревалидировать, и no-cache в таком виде на практике вело себя как
        # "можно отдать из кэша/bfcache без обращения к серверу" -- главы
        # курса (и вообще любая HTML-страница) обновлялись только через
        # Hard Reload. no-store запрещает сохранение целиком, обычная
        # навигация/обновление страницы всегда идёт на сервер.
        path = self.path.split("?")[0]
        if not path.startswith("/api/"):
            ttl = self._STATIC_TTL.get(os.path.splitext(path)[1].lower())
            if ttl and not path.endswith((".html", ".htm")):
                self.send_header("Cache-Control", f"public, max-age={ttl}")
            else:
                self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


def _run_calendar_pull():
    """
    Умный поллинг:
      • pull_forward каждые 3ч  — thisweek+nextweek+lastweek, обновляет расписание
      • pull_capture каждые 2мин — только thisweek, ловим факт в момент релиза
      • вне окна события — 15-мин пауза, не долбим фид
    """
    import importlib.util, time as _time
    _cal_path = str(Path(__file__).parent / "calendar_pull.py")
    spec = importlib.util.spec_from_file_location("calendar_pull", _cal_path)
    mod  = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        print(f"calendar_pull import: {e}", flush=True)
        return

    FORWARD_EVERY  = 3 * 3600   # 3 ч
    CAPTURE_SLEEP  = 2 * 60     # 2 мин (в окне события)
    IDLE_SLEEP     = 15 * 60    # 15 мин (нет близких событий)
    EVENT_WINDOW   = 35         # ±35 мин вокруг scheduled_ts

    last_forward = 0.0

    while True:
        now = _time.time()

        # Forward: каждые 3 ч
        if now - last_forward >= FORWARD_EVERY:
            try:
                mod.pull_forward(verbose=True)
            except Exception as e:
                print(f"calendar forward: {e}", flush=True)
            last_forward = _time.time()

        # Capture: только если есть событие рядом
        try:
            near = mod.has_upcoming_event(within_minutes=EVENT_WINDOW)
        except Exception:
            near = False

        if near:
            try:
                n = mod.pull_capture(verbose=False)
                if n:
                    print(f"calendar: захвачено {n} фактов", flush=True)
            except Exception as e:
                print(f"calendar capture: {e}", flush=True)
            _time.sleep(CAPTURE_SLEEP)
        else:
            _time.sleep(IDLE_SLEEP)


if __name__ == "__main__":
    import threading
    _ensure_schema()
    threading.Thread(target=_precompile_all, daemon=True).start()
    threading.Thread(target=_run_calendar_pull, daemon=True).start()
    # 🔴 Сервер многопоточный (31.08.2026). Раньше был обычный TCPServer — один
    # запрос за раз. Любой поход в мост MT5 (1.5-3.4 с на холодный инструмент)
    # останавливал сайт целиком для всех остальных: замер 6 параллельных
    # запросов давал 5.3 с, выстроенных в очередь.
    #
    # Почему это безопасно именно здесь, а не «вообще»: обработчик создаётся
    # заново на каждый запрос (своего состояния не делит), соединения к SQLite
    # везде открываются на вызов, а не хранятся на уровне модуля
    # (core/journal_*.py::_get_conn, check_same_thread=False + WAL), единственный
    # общий ресурс — соединение с мостом _mt5_conn, и оно закрыто _mt5_lock.
    # Кэш свечей держит соединение в threading.local. Файлов обработчики не
    # пишут — гонок за запись нет.
    #
    # daemon_threads: не ждать зависший запрос при остановке юнита, иначе
    # systemctl restart упирается в таймаут.
    class _ThreadedServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        daemon_threads = True
        allow_reuse_address = True

    with _ThreadedServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"Serving {DIRECTORY} on http://127.0.0.1:{PORT}")
        httpd.serve_forever()
