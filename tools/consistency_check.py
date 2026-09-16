#!/usr/bin/env python3
"""
tools/consistency_check.py — АУДИТ_легаси_market_intel_2026-08-06.md / WP10.

Ловит регресс ДО того, как он расползётся, а не рефакторит сам. Пять проверок:
  1. Дубли ключей в JSON — обычный json.load молча берёт последний ключ (так
     demo_requires_verification: null затирал верное значение в partners.json).
  2. Ключи i18n: используются, но отсутствуют / объявлены, но не используются /
     расходятся между ru/ro/en.
  3. Реестр символов: тикеры вида "..=X" вне symbols.json и core/symbols*.py.
  4. Эндпоинты: вызываются из фронта, но не объявлены в serve.py.
  5. Файлы данных: читаются, но отсутствуют на диске / лежат, но никем не читаются.

Пункты 4 и 5 дают ложные срабатывания на внешних потребителях (lp.sbfconsult.com,
MT5-агент, cron) — исключения ведутся явным файлом exceptions.json рядом со
скриптом (§10 приёмки: "не молчанием").

Запуск: .venv/bin/python3 tools/consistency_check.py [--json]
Код возврата: 0 — чисто, 1 — есть находки (для CI).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCEPTIONS_PATH = Path(__file__).resolve().parent / "consistency_check_exceptions.json"

SCAN_EXT_CODE = (".py", ".js", ".html")
SKIP_DIR_NAMES = {".venv", "node_modules", "__pycache__", ".git", "browser_profile", "browser_profile.bak"}


def _iter_files(exts: tuple[str, ...], root: Path = ROOT):
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        if any(part in SKIP_DIR_NAMES for part in p.parts):
            continue
        if p.suffix in exts:
            yield p


def _load_exceptions() -> dict:
    if EXCEPTIONS_PATH.exists():
        return json.loads(EXCEPTIONS_PATH.read_text(encoding="utf-8"))
    return {"external_endpoints": [], "unreferenced_data_files_ok": [], "hardcoded_symbols_ok": []}


# ── 1. Дубли ключей в JSON ────────────────────────────────────────────────────

def check_duplicate_json_keys() -> list[str]:
    findings = []
    for p in _iter_files((".json",)):
        try:
            raw = p.read_text(encoding="utf-8")
        except Exception:
            continue

        def _reject_dupes(pairs):
            seen = {}
            for k, v in pairs:
                if k in seen:
                    raise ValueError(f"дублирующийся ключ {k!r}")
                seen[k] = v
            return seen

        try:
            json.loads(raw, object_pairs_hook=_reject_dupes)
        except ValueError as e:
            if "дублирующийся ключ" in str(e):
                findings.append(f"{p.relative_to(ROOT)}: {e}")
            # иначе — обычная синтаксическая ошибка JSON, не наша забота здесь
    return findings


# ── 2. Ключи i18n ─────────────────────────────────────────────────────────────

_I18N_DIR = ROOT / "i18n" / "site"
_I18N_LANGS = ("ru", "ro", "en")
# Реальные i18n-ключи всегда namespace.leaf (минимум одна точка). Без этого
# t('div', ...)/t('svg', ...) из JSX-скомпилированных глав курса (React.createElement
# под тем же именем t) ложно матчились бы как ключи — см. feedback_variable_shadowing_i18n.
# Серверный переводчик — core/i18n.py::t(key, lang), вызывается как i18n.t(...) —
# поэтому сканируем и .py (не только .js/.html), иначе весь server-side edu-текст
# (i18n.t("edu.chapter_n", ...) и т.п.) ложно попадёт в "объявлено, но не используется".
_T_CALL_RE = re.compile(r"""\bt\(\s*['"]([a-zA-Z0-9_]+\.[a-zA-Z0-9_.]+)['"]""")
# Часть страниц переводит статическую разметку атрибутом data-i18n="key" (admin.html,
# chart.html, journal.html, edu/*.html) вместо t()-вызова из JS — отдельный канал
# использования, без него весь admin.* и куски других страниц ложно "не используются".
_DATA_I18N_RE = re.compile(r'data-i18n="([a-zA-Z0-9_]+\.[a-zA-Z0-9_.]+)"')
# Динамически собранные ключи (t('chart.sess_' + x), t('eduindex.chapters.' + n + '.title'))
# матчатся регэкспом только своим литеральным префиксом/суффиксом — это не настоящий
# ключ целиком, а обрывок конкатенации. Настоящий ключ никогда не кончается на "." или "_".
_DYNAMIC_KEY_FRAGMENT_RE = re.compile(r"[._]$")


def _flatten(d: dict, prefix: str = "") -> set[str]:
    keys = set()
    for k, v in d.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys |= _flatten(v, full)
        else:
            keys.add(full)
    return keys


def check_i18n() -> dict:
    lang_keys = {}
    for lang in _I18N_LANGS:
        fp = _I18N_DIR / f"{lang}.json"
        if not fp.exists():
            continue
        lang_keys[lang] = _flatten(json.loads(fp.read_text(encoding="utf-8")))

    all_declared = set()
    for keys in lang_keys.values():
        all_declared |= keys

    used = set()
    for p in _iter_files((".js", ".html", ".py")):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in _T_CALL_RE.finditer(text):
            key = m.group(1)
            if _DYNAMIC_KEY_FRAGMENT_RE.search(key):
                continue  # обрывок конкатенации, не настоящий ключ
            used.add(key)
        for m in _DATA_I18N_RE.finditer(text):
            used.add(m.group(1))

    missing = sorted(used - all_declared)
    unused = sorted(all_declared - used)

    mismatches = []
    for key in sorted(all_declared):
        present_in = [lang for lang in _I18N_LANGS if lang in lang_keys and key in lang_keys[lang]]
        if 0 < len(present_in) < len(lang_keys):
            missing_in = [l for l in lang_keys if l not in present_in]
            mismatches.append(f"{key}: есть в {present_in}, нет в {missing_in}")

    return {"missing_from_i18n": missing, "declared_but_unused": unused, "lang_mismatches": mismatches}


# ── 3. Реестр символов ────────────────────────────────────────────────────────

_HARDCODED_TICKER_RE = re.compile(r'["\']([A-Z]{2,10}=X)["\']')
_SYMBOL_REGISTRY_FILES = {
    ROOT / "core" / "symbols.py",
    ROOT / "core" / "symbols_registry.py",
    ROOT / "web" / "assets" / "sbf-symbols.js",
    ROOT / "web" / "data" / "symbols.json",
}


def check_symbol_hardcoding(exceptions: list[str]) -> list[str]:
    findings = []
    for p in _iter_files((".py", ".js")):
        if p in _SYMBOL_REGISTRY_FILES:
            continue
        rel = str(p.relative_to(ROOT))
        if rel in exceptions:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for m in _HARDCODED_TICKER_RE.finditer(line):
                findings.append(f"{rel}:{i}: {m.group(1)}")
    return findings


# ── 4. Эндпоинты ──────────────────────────────────────────────────────────────

_ROUTE_EXACT_RE = re.compile(r'path_clean == "(/api/[^"]+)"')
# И path_clean.startswith(...), и self.path.startswith(...) (эндпоинт /api/quotes
# диспетчеризуется по self.path, а не path_clean — единственный такой случай).
_ROUTE_PREFIX_RE = re.compile(r'(?:path_clean|self\.path)\.startswith\("(/api/[^"]+)"\)')
# Третий диспетчер — re.match(r"^/api/copy/[^/]+$", path_clean) и подобные (в основном
# journal/admin/copy). Берём литеральный префикс до первого регекс-метасимвола —
# этого достаточно, чтобы понять "какой путь этот маршрут покрывает".
_ROUTE_REGEX_RE = re.compile(r're\.match\(r"\^(/api/[^"]*?)(?:[\[\(\\$]|$)')
_FETCH_CALL_RE = re.compile(r"""fetch\(\s*['"`](/api/[a-zA-Z0-9_\-/]+)""")


def check_endpoints(exceptions: list[str]) -> list[str]:
    serve_py = ROOT / "serve.py"
    text = serve_py.read_text(encoding="utf-8")
    exact_routes = set(_ROUTE_EXACT_RE.findall(text))
    prefix_routes = list(_ROUTE_PREFIX_RE.findall(text)) + list(_ROUTE_REGEX_RE.findall(text))

    def is_declared(path: str) -> bool:
        if path in exact_routes:
            return True
        # Вызов из фронта часто обрезан до литерального префикса конкатенации
        # (fetch('/api/event/' + id + '/history') → captured '/api/event/'), а
        # объявленный префикс тоже кончается на "/" — сравниваем в обе стороны,
        # чтобы "/api/event" (после rstrip) и "/api/event/" (из startswith) совпали.
        return any(path.startswith(prefix) or prefix.startswith(path) for prefix in prefix_routes)

    called = set()
    for p in _iter_files((".js", ".html")):
        try:
            fp_text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in _FETCH_CALL_RE.finditer(fp_text):
            called.add(m.group(1).rstrip("/"))

    findings = []
    for path in sorted(called):
        if path in exceptions:
            continue
        if any(path.startswith(exc.rstrip("*")) for exc in exceptions if exc.endswith("*")):
            continue
        if not is_declared(path):
            findings.append(path)
    return findings


# ── 5. Файлы данных ───────────────────────────────────────────────────────────

_DATA_DIR = ROOT / "web" / "data"


def _matches_glob_exception(name: str, patterns: list[str]) -> bool:
    from fnmatch import fnmatch
    return any(fnmatch(name, pat) for pat in patterns)


def check_data_files(exceptions: list[str], glob_exceptions: list[str]) -> dict:
    # "Не читается никем" — проверяем в пределах web/data/ (рекурсивно: edu_capsules/,
    # edu_stats/ и т.п. тоже сюда, это тот же вопрос "лежит, но не читается").
    on_disk = {p.name for p in _DATA_DIR.rglob("*.json")}
    # "Отсутствует на диске" — файлы данных живут не только в web/data/ (manifest.json
    # в корне web/, vapid_keys.json в data/, feed_filter_config.json рядом с модулем) —
    # для "missing" ищем существование ИМЕНИ файла где угодно в репозитории.
    anywhere_on_disk = {p.name for p in ROOT.rglob("*.json") if not any(part in SKIP_DIR_NAMES for part in p.parts)}

    referenced = set()
    # Два разных стиля путей в этом кодовом стиле: pathlib-сегменты
    # (WEB_DIR / "data" / "buzz.json" — литерал "buzz.json" сам по себе) и
    # цельные строки-пути ("/data/edu_stats/market_hours.json" — литерал внутри
    # более длинной строки). Плюс fetch()-вызовы часто добавляют cache-buster
    # ("partners.json?t=" + Date.now()) — закрывающая кавычка не сразу после
    # ".json". Ловим basename в обоих случаях, кавычка допускает "?..." после.
    ref_re = re.compile(r"""['"`][a-zA-Z0-9_\-/]*?([a-zA-Z0-9_\-]+\.json)(?:\?[^'"`]*)?['"`]""")
    # f-строки/format вида f"ohlc_{symbol}_{tf}.json" — собираются из переменных,
    # литерала целиком в источнике нет. Ловим сам паттерн отдельно, чтобы не считать
    # ohlc_GOLD_D1.json и еже с ним "никем не читаемыми".
    fstring_re = re.compile(r"""f?['"`]([a-zA-Z0-9_\-]*\{[a-zA-Z0-9_]+\}[a-zA-Z0-9_\-{}]*\.json)['"`]""")
    fstring_patterns = set()
    for p in _iter_files((".py", ".js", ".html")):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in ref_re.finditer(text):
            referenced.add(m.group(1))
        for m in fstring_re.finditer(text):
            # "ohlc_{symbol}_{tf}.json" → "ohlc_*_*.json"
            pat = re.sub(r"\{[a-zA-Z0-9_]+\}", "*", m.group(1))
            # Вырожденный случай f"{lang}.json" → "*.json" матчит вообще всё —
            # такой паттерн ничего не говорит о конкретном файле, отбрасываем
            # (нашлось на собственном core/i18n.py::f"{lang}.json" — и на этой
            # же строке скрипта, раз он сканирует .py-файлы репозитория целиком).
            stem_literal = pat[:-len(".json")].replace("*", "")
            if len(stem_literal) < 2:
                continue
            fstring_patterns.add(pat)

    def is_referenced(name: str) -> bool:
        if name in referenced:
            return True
        return _matches_glob_exception(name, list(fstring_patterns))

    unreferenced = sorted(
        n for n in on_disk
        if not is_referenced(n) and n not in exceptions and not _matches_glob_exception(n, glob_exceptions)
    )
    missing = sorted(n for n in referenced if n not in anywhere_on_disk and n not in exceptions)
    return {"unreferenced_on_disk": unreferenced, "referenced_but_missing": missing}


# ── main ───────────────────────────────────────────────────────────────────────

def check_glossary_related() -> list[str]:
    """Ссылки «по теме» между статьями глоссария, которые ведут в никуда.

    🔴 16.09.2026: шесть таких ссылок жили на /glossary незамеченными.
    Пять вели на термины, которых в словаре нет вовсе (atr, margin,
    oscillator, risk — на последний ссылались три статьи), шестая была
    опечаткой: `stoplos` вместо `stoploss`. Клик по ним прокручивал
    в никуда — навигация внутри глоссария частично не работала.

    Молча это не ловилось ничем: JSON валиден, страница рендерится,
    в консоли чисто. Ошибка видна, только если сверить related со списком
    slug'ов, — то есть ровно то, за чем существует этот скрипт.
    """
    итог = []
    for имя in ("glossary.json", "glossary.ro.json", "glossary.en.json"):
        путь = ROOT / "web" / "assets" / имя
        if not путь.exists():
            continue
        try:
            данные = json.loads(путь.read_text(encoding="utf-8"))
        except Exception as e:
            итог.append(f"{имя}: не читается — {e}")
            continue
        статьи = данные if isinstance(данные, list) else (
            данные.get("terms") or данные.get("items") or [])
        слаги = {с.get("slug") for с in статьи if isinstance(с, dict)}
        for с in статьи:
            if not isinstance(с, dict):
                continue
            for r in (с.get("related") or []):
                if r not in слаги:
                    итог.append(f"{имя}: «{с.get('slug')}» → related «{r}» — такого термина нет")
    return итог


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="машиночитаемый вывод")
    args = ap.parse_args()

    exc = _load_exceptions()

    report = {
        "duplicate_json_keys": check_duplicate_json_keys(),
        "i18n": check_i18n(),
        "hardcoded_symbol_tickers": check_symbol_hardcoding(exc.get("hardcoded_symbols_ok", [])),
        "undeclared_endpoints": check_endpoints(exc.get("external_endpoints", [])),
        "data_files": check_data_files(
            exc.get("unreferenced_data_files_ok", []),
            exc.get("unreferenced_data_files_glob_ok", []),
        ),
        "glossary_related": check_glossary_related(),
    }

    has_findings = (
        bool(report["duplicate_json_keys"])
        or bool(report["i18n"]["missing_from_i18n"])
        or bool(report["i18n"]["lang_mismatches"])
        or bool(report["hardcoded_symbol_tickers"])
        or bool(report["undeclared_endpoints"])
        or bool(report["data_files"]["referenced_but_missing"])
        or bool(report["glossary_related"])
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        sys.exit(1 if has_findings else 0)

    def section(title, items):
        print(f"\n── {title} ({len(items)}) ──")
        for it in items[:50]:
            print(f"  {it}")
        if len(items) > 50:
            print(f"  … и ещё {len(items) - 50}")

    print("=== consistency_check.py ===")
    section("1. Дубли ключей в JSON", report["duplicate_json_keys"])
    section("2a. i18n: используются, но не объявлены", report["i18n"]["missing_from_i18n"])
    section("2b. i18n: объявлены, но не используются", report["i18n"]["declared_but_unused"])
    section("2c. i18n: расхождение между языками", report["i18n"]["lang_mismatches"])
    section("3. Захардкоженные тикеры вне реестра", report["hardcoded_symbol_tickers"])
    section("4. Эндпоинты без объявления в serve.py", report["undeclared_endpoints"])
    section("5a. Данные на диске, но никем не читаются", report["data_files"]["unreferenced_on_disk"])
    section("5b. Данные читаются, но отсутствуют на диске", report["data_files"]["referenced_but_missing"])

    print(f"\n{'НАЙДЕНЫ ПРОБЛЕМЫ' if has_findings else 'ЧИСТО'}")
    print(f"Исключения: {EXCEPTIONS_PATH.relative_to(ROOT)}")
    sys.exit(1 if has_findings else 0)


if __name__ == "__main__":
    main()
