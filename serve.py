"""Static server + /api/quotes proxy + /edu book renderer.
JSX компилируется серверно при старте (Node.js + Babel). Браузер получает чистый JS."""
import http.server
import json
import re
import sqlite3
import subprocess
import socketserver
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Journal modules (добавляем core/ в path)
sys.path.insert(0, str(Path(__file__).parent))
from core import journal_db, journal_crypto, journal_ocr, journal_csv, journal_meta, journal_discipline, journal_alerts, journal_brief, journal_setups, journal_tilt, journal_gamification, journal_goals, journal_account, journal_auth, journal_feedback, journal_import, journal_analytics, journal_review, journal_cooldown, i18n

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

PORT = 8085
DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
BOOK_DIR = Path(__file__).parent / "web" / "book"
EDU_DIR  = Path(__file__).parent / "web" / "edu"
WEB_DIR  = Path(__file__).parent / "web"
_BOT_DB  = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

_COUNTRY_SYM = {
    "US": "EURUSD", "EU": "EURUSD", "EA": "EURUSD",
    "GB": "GBPUSD", "JP": "USDJPY", "CN": "USDCNY",
    "RU": "USDRUB", "ZA": "USDZAR", "AE": "USDAED", "KZ": "USDKZT",
}

def _ensure_schema() -> None:
    """Создаёт новые таблицы БД Фазы 1 если не существуют."""
    con = sqlite3.connect(str(_BOT_DB))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS price_bars (
            symbol TEXT NOT NULL, tf TEXT NOT NULL, ts INTEGER NOT NULL,
            o REAL, h REAL, l REAL, c REAL, v REAL,
            PRIMARY KEY(symbol, tf, ts)
        );
        CREATE TABLE IF NOT EXISTS symbol_map (
            our_key TEXT PRIMARY KEY, twelvedata TEXT, mt5 TEXT, yahoo TEXT
        );
        CREATE TABLE IF NOT EXISTS econ_event_history (
            event_key TEXT NOT NULL, ts INTEGER NOT NULL,
            actual REAL, forecast REAL, previous REAL, unit TEXT,
            PRIMARY KEY(event_key, ts)
        );
        CREATE TABLE IF NOT EXISTS event_reactions (
            event_key TEXT NOT NULL, symbol TEXT NOT NULL,
            release_ts INTEGER NOT NULL, window TEXT NOT NULL,
            pips REAL, true_range REAL, dir TEXT, close_dir TEXT,
            PRIMARY KEY(event_key, symbol, release_ts, window)
        );
    """)
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
    con.commit()
    con.close()

# ── Jinja2 ──────────────────────────────────────────────────────────────────
def _url_for(endpoint, **values):
    if endpoint == "static":
        return "/assets/" + values.get("filename", "")
    return "/"

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
    11: "^IXIC",12: "EURUSD=X",13: "GC=F",  14: "EURUSD=X",15: "^GSPC",
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
    _TCARD_MAP: dict[int, str] = {
        3: (
            f"sbfTechCard({{sym:'EUR/USD · D1',bias:'bull',"
            f"levels:[['{_LVL['entry']}','1.0850'],['{_LVL['stop']}','1.0790'],['{_LVL['target']}','1.0980']],"
            f"note:'{i18n.t('edu.tcard.n1', lang)}'}}) +"
            f"sbfTechCard({{sym:'XAU/USD · H4',bias:'bear',"
            f"levels:[['{_LVL['entry']}','2020'],['{_LVL['stop']}','2045'],['{_LVL['target']}','1970']],"
            f"note:'{i18n.t('edu.tcard.n2', lang)}'}})"
        ),
        7: (
            f"sbfTechCard({{sym:'GBP/USD · H1',bias:'bull',"
            f"levels:[['{_LVL['order_block']}','1.2640'],['{_LVL['entry']}','1.2660'],['{_LVL['stop']}','1.2610'],['{_LVL['fvg_target']}','1.2750']],"
            f"note:'{i18n.t('edu.tcard.n3', lang)}'}})"
        ),
        13: (
            f"sbfTechCard({{sym:'US500 · D1',bias:'bear',"
            f"levels:[['{_LVL['neckline']}','5180'],['{_LVL['target_h']}','5040']],"
            f"note:'{i18n.t('edu.tcard.n4', lang)}'}}) +"
            f"sbfTechCard({{sym:'BTCUSD · H4',bias:'bear',"
            f"levels:[['{_LVL['neckline']}','61 200'],['{_LVL['target_h']}','58 400']],"
            f"note:'{i18n.t('edu.tcard.n5', lang)}'}})"
        ),
        14: (
            f"sbfTechCard({{sym:'EUR/USD · M5',bias:'bull',"
            f"levels:[['{_LVL['entry']}','1.0902'],['{_LVL['stop']}','1.0893'],['{_LVL['target']}','1.0924']],"
            f"note:'{i18n.t('edu.tcard.n6', lang)}'}})"
        ),
    }
    if ch in _FIG_MAP:
        _figs_inner = "".join(
            f'<div class="sbf-fig" data-cat="{cat}" data-key="{key}"'
            f' data-caption="{cap}"></div>\n'
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

<script src="/edu/concept_map.js"></script>
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
      '^GSPC':'ohlc_SPX_D1.json','^IXIC':'ohlc_NASDAQ_D1.json',
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
    html = _jinja.get_template(f"edu_book_{ch}.html").render(lang=lang)

    if ch in _COMPILED:
        # Убираем CDN-скрипты и babel-блок
        html = _CDN_REACT.sub(LOCAL_REACT, html)
        html = _CDN_REACTDOM.sub(LOCAL_REACTDOM, html)
        html = _CDN_BABEL.sub("", html)

        compiled_js = _COMPILED[ch].replace('"__LANG__"', f'"{lang}"')
        html = _BABEL_SCRIPT_RE.sub(
            f'<script>\n{compiled_js}\n</script>',
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
        '<link rel="stylesheet" href="/assets/design.css">\n'
        '<link rel="stylesheet" href="/edu/edu.css">\n'
        '<link rel="stylesheet" href="/assets/sbf-nav.css">\n'
        '<script src="/assets/i18n.js?v=2" defer></script>\n'
        '<script src="/assets/sbf-header.js?v=15" defer></script>'
    )
    if '/edu/edu.css' not in html:
        html = html.replace("</head>", f"{css_tags}\n</head>", 1)
    elif '/assets/sbf-header.js?v=15' not in html:
        html = html.replace("</head>",
            '<link rel="stylesheet" href="/assets/sbf-nav.css">\n'
            '<script src="/assets/i18n.js?v=2" defer></script>\n'
            '<script src="/assets/sbf-header.js?v=15" defer></script>\n</head>', 1)

    grafik_tags = (
        '<script src="/edu/assets/grafik-engine.js"></script>\n'
        '<script src="/edu/assets/edu-embed.js"></script>'
    )
    if 'grafik-engine.js' not in html:
        html = html.replace("</head>", f"{grafik_tags}\n</head>", 1)

    # Хедер инжектирует sbf-header.js (добавлен через css_tags выше)

    # Инжектируем nav + прогресс + дисклеймер перед </body>
    inject = _edu_inject(ch, lang)
    html = html.replace("</body>", f"{inject}\n</body>", 1)

    return html.encode("utf-8")


# ── Quotes ───────────────────────────────────────────────────────────────────
NAMES = {
    "^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^DJI": "Dow Jones", "^VIX": "VIX",
    "GC=F": "GOLD", "SI=F": "SILVER", "CL=F": "Нефть WTI", "NG=F": "Природный газ",
    "BTC-USD": "BTCUSD", "ETH-USD": "ETHUSD", "SOL-USD": "SOLUSD",
    "EURUSD=X": "EURUSD", "GBPUSD=X": "GBPUSD", "DX-Y.NYB": "DXY",
}
QUOTES_FILE = Path(__file__).parent / "web" / "data" / "quotes.json"


def fetch_quotes() -> list[dict]:
    try:
        data = json.loads(QUOTES_FILE.read_text(encoding="utf-8"))
        quotes = data.get("quotes", {})
        return [
            {"ticker": sym, "name": NAMES.get(sym, sym),
             "price": q["price"], "change_pct": q.get("change_pct")}
            for sym, q in quotes.items() if q.get("price") is not None
        ]
    except Exception:
        return []


# ── HTTP Handler ─────────────────────────────────────────────────────────────
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def end_headers(self):
        # Prevent browser caching for all JS/CSS assets so updates apply immediately
        if self.path.split("?")[0].startswith("/assets/") or self.path.split("?")[0].startswith("/edu/assets/"):
            self.send_header("Cache-Control", "no-cache, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_PUT(self):
        path_clean = self.path.split("?")[0]
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
            self._handle_course_complete(user_id)
        elif path_clean.startswith("/api/journal/course/") and path_clean.endswith("/complete"):
            chapter_n = int(path_clean.split("/")[-2])
            self._send_json(journal_gamification.complete_chapter(chapter_n, user_id))
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
        elif path_clean == "/api/journal/behavioral":
            self._send_json(journal_meta.get_behavioral_data(user_id))
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
            self._send_json(journal_gamification.get_course_progress(user_id))
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
        # ── Auth / Onboarding ──
        elif path_clean == "/api/auth/me":
            self._handle_auth_me()
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
        elif path_clean == "/journal":
            self._serve_static(WEB_DIR / "journal.html")
        # ── Legacy /m/* routes → redirect to unified index ──
        elif path_clean.startswith("/m"):
            self.send_response(301)
            self.send_header("Location", "/")
            self.end_headers()
        elif path_clean in ("/glossary", "/glossary.html", "/m/glossary"):
            self._render_site_page("glossary.html", req_lang)
        # ── Gated LP API endpoints ──
        elif path_clean == "/api/lp/signals":
            self._handle_lp_signals()
        elif path_clean == "/api/lp/buzz":
            self._handle_lp_buzz()
        elif path_clean == "/api/lp/patterns":
            self._handle_lp_patterns()
        elif path_clean == "/api/lp/gold-scenarios":
            self._handle_lp_gold_scenarios()
        elif path_clean.startswith("/api/calendar/events"):
            self._handle_calendar_api()
        elif path_clean.startswith("/api/event/"):
            segs = path_clean[len("/api/event/"):].rstrip("/").split("/")
            if len(segs) == 2 and segs[1] == "history":
                self._handle_event_history(segs[0])
            elif len(segs) == 2 and segs[1] == "markers":
                self._handle_event_markers(segs[0])
            elif len(segs) == 2 and segs[1] == "reactions":
                self._send_json({"error": "скоро (Фаза 2)", "status": 501}, 501)
            else:
                self._send_json({"error": "not found"}, 404)
        elif path_clean == "/api/price":
            self._handle_price_api()
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
            self.send_header("Cache-Control", "no-cache")
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
        try:
            body = _build_edu_page(ch, lang)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            body = f"<h1>Ошибка</h1><pre>{e}</pre>".encode()
            self.send_response(500)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

    def _serve_static(self, path: Path, content_type: str = "text/html; charset=utf-8"):
        try:
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache")
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
            html = tpl.render(lang=lang)
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"Template error: {e}".encode("utf-8"))
            return
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _handle_calendar_api(self):
        from datetime import datetime as _dt, timezone as _tz
        params  = parse_qs(urlparse(self.path).query)
        date    = params.get("date",    [None])[0]
        from_d  = params.get("from",    [None])[0]
        to_d    = params.get("to",      [None])[0]
        impact  = params.get("impact",  [None])[0]
        country = params.get("country", [None])[0]
        try:
            con = sqlite3.connect(str(_BOT_DB))
            con.row_factory = sqlite3.Row
            # Фильтр по scheduled_ts (INTEGER, индексирован) с fallback на ts_utc
            query = "SELECT * FROM econ_events WHERE 1=1"
            args: list = []
            if date:
                try:
                    day_start = int(_dt.strptime(date, "%Y-%m-%d").replace(tzinfo=_tz.utc).timestamp())
                    query += " AND (scheduled_ts >= ? AND scheduled_ts < ?" \
                             " OR scheduled_ts IS NULL AND ts_utc LIKE ?)"
                    args.extend([day_start, day_start + 86400, f"{date}%"])
                except ValueError:
                    query += " AND ts_utc LIKE ?"
                    args.append(f"{date}%")
            elif from_d or to_d:
                if from_d:
                    try:
                        ts = int(_dt.strptime(from_d, "%Y-%m-%d").replace(tzinfo=_tz.utc).timestamp())
                        query += " AND (scheduled_ts >= ? OR scheduled_ts IS NULL AND ts_utc >= ?)"
                        args.extend([ts, f"{from_d}T00:00:00"])
                    except ValueError:
                        query += " AND ts_utc >= ?"
                        args.append(f"{from_d}T00:00:00")
                if to_d:
                    try:
                        ts = int(_dt.strptime(to_d, "%Y-%m-%d").replace(tzinfo=_tz.utc).timestamp()) + 86400
                        query += " AND (scheduled_ts < ? OR scheduled_ts IS NULL AND ts_utc <= ?)"
                        args.extend([ts, f"{to_d}T23:59:59"])
                    except ValueError:
                        query += " AND ts_utc <= ?"
                        args.append(f"{to_d}T23:59:59")
            if impact:
                query += " AND impact = ?"
                args.append(impact)
            if country:
                query += " AND country = ?"
                args.append(country)
            query += " ORDER BY COALESCE(scheduled_ts, 0) ASC LIMIT 2000"
            rows = [dict(r) for r in con.execute(query, args).fetchall()]
            con.close()
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
        """Извлекает токен из заголовка X-Auth-Token или Authorization: Bearer.
        journal.html's _authHdr() отправляет именно Bearer — раньше сервер его
        не читал вообще (TZ-детект/MT4-импорт/cooldown/review/analytics/prestige
        были из-за этого молча сломаны), плюс SBFAcademy-мост должен работать
        независимо от того, какой из двух заголовков прислал конкретный файл."""
        token = self.headers.get("X-Auth-Token", "")
        if token:
            return token
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:]
        return ""

    def _current_user_id(self) -> str:
        """Резолвит user_id из токена запроса, или 'default' для анонимных
        визитёров (сохраняет прежнее поведение для гостей). Раньше почти
        каждый POST-обработчик ниже либо вообще не резолвил токен, либо
        передавал буквально строку "default" — из-за этого залогиненный
        пользователь читал/писал в общий анонимный набор данных, а не в свой."""
        return journal_auth.validate_session(self._auth_token()) or "default"

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
        token = self._auth_token()
        user_id = journal_auth.validate_session(token)
        if not user_id:
            self._send_json({"error": "unauthorized"}, 401)
            return
        user = journal_auth.get_user(user_id)
        self._send_json(user or {"error": "not found"})

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

    def _handle_lp_signals(self) -> None:
        if not self._lp_require_auth():
            return
        try:
            data = json.loads((WEB_DIR / "data" / "signals.json").read_text())
            self._send_json(data)
        except Exception:
            self._send_json({})

    def _handle_lp_buzz(self) -> None:
        if not self._lp_require_auth():
            return
        try:
            data = json.loads((WEB_DIR / "data" / "buzz.json").read_text())
            self._send_json(data)
        except Exception:
            self._send_json({"tickers": []})

    def _handle_lp_patterns(self) -> None:
        if not self._lp_require_auth():
            return
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        sym = (qs.get("sym") or ["GOLD"])[0]
        tf  = (qs.get("tf")  or ["D1"])[0]
        sym = "".join(c for c in sym if c.isalnum() or c in "-.")[:10]
        tf  = "".join(c for c in tf if c.isalnum())[:4]
        try:
            data = json.loads((WEB_DIR / "data" / f"ohlc_{sym}_{tf}.json").read_text())
            result = {
                "candles":  data.get("candles", []),
                "volume":   data.get("volume", []),
                "patterns": data.get("patterns", []),
                "zones":    [{"price": L["price"], "color": L.get("color","#C9A227"), "name": L["name"]}
                             for L in data.get("levels", [])],
            }
            self._send_json(result)
        except Exception:
            self._send_json({"candles": [], "patterns": [], "zones": []})

    def _handle_lp_gold_scenarios(self) -> None:
        if not self._lp_require_auth():
            return
        try:
            data = json.loads((WEB_DIR / "data" / "ohlc_GOLD_D1.json").read_text())
            # Build scenarios dict: level_name → short scenario description
            scenarios: dict[str, str] = {}
            for L in data.get("levels", []):
                side = "покупка" if L["name"].startswith("S") else "продажа"
                scenarios[L["name"]] = f"Реакция {side} при тесте {L['price']}"
            self._send_json(scenarios)
        except Exception:
            self._send_json({})

    # ── Survey fast-track registration ─────────────────────────────────────────

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
        # Grant PRO regardless (survey completion)
        try:
            pro = journal_auth.grant_survey_pro(user_id)
            result["pro_granted"] = True
            result["pro_until"]   = pro.get("expires_ts")
        except Exception:
            result["pro_granted"] = False

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
            quotes = fetch_quotes()
            body = json.dumps({"ok": True, "quotes": quotes}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    def end_headers(self):
        path = self.path.split("?")[0]
        if path.startswith("/data/"):
            self.send_header("Cache-Control", "no-store")
        elif not path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
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
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"Serving {DIRECTORY} on http://127.0.0.1:{PORT}")
        httpd.serve_forever()
