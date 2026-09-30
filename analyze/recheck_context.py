#!/usr/bin/env python3
"""Проверка context_<date>.json тем же валидатором, что и Telegram-пуш, с
возвратом текста нарушений модели на переделку.

Зачем. Аналитику пишет Claude (claude -p по analyze/prompt.md), а публикует её
бот из соседнего проекта, и правила текста живут у бота
(SBFAcademy_bot/sbfacademy/briefing/validate.py). До 31.08.2026 обратной связи
между ними не было вообще: модель писала пункт на 26 слов при лимите 25, бот
молча выкидывал ВСЮ аналитическую часть, подписчик получал голую таблицу
котировок. Правки промпта снижают вероятность, но не закрывают вопрос —
единственный надёжный способ выдать проходящий текст — проверить его и, если
не прошёл, сказать модели что именно не так и попросить переписать.

Валидатор НЕ копируется сюда. Он загружается из файла бота напрямую
(_load_validator): вторая копия правил разошлась бы с первой — ровно эта
рассинхронизация и была исходной поломкой. Модуль бота на импорт ничего, кроме
re, не тянет, поэтому грузится по пути без установки пакета.

Использование:
  python3 -m analyze.recheck_context [--date YYYY-MM-DD] [--attempts 2]
  python3 -m analyze.recheck_context --check-only    # только код возврата

Код возврата: 0 — файл валиден (сразу или после переделки), 1 — остались
нарушения, 2 — файла нет / он битый. Ни один из кодов не должен ронять
пайплайн: даже невалидный текст бот теперь отбраковывает поштучно, а не
целиком, — поэтому в run_daily.sh вызов идёт с `|| true`.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import REPORTS_DIR  # noqa: E402

# Бот лежит рядом в том же портфеле (зона «Платформа и Боты»).
_BOT_VALIDATE_PY = Path(
    "/mnt/sbfdata/sbf-platform/SBFAcademy_bot/sbfacademy/briefing/validate.py"
)

DEFAULT_ATTEMPTS = 2
CLAUDE_TIMEOUT = 600


def _load_validator():
    """Модуль validate.py бота как объект. None, если файла нет -- тогда
    проверять нечем, и это не повод ронять утренний пайплайн."""
    if not _BOT_VALIDATE_PY.exists():
        print(f"recheck_context: {_BOT_VALIDATE_PY} не найден -- проверка пропущена",
              file=sys.stderr)
        return None
    spec = importlib.util.spec_from_file_location("_bot_validate", _BOT_VALIDATE_PY)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _as_tg_payload(raw: dict) -> dict:
    """context_<date>.json → та же форма, которую собирает бот (tg_adapt.py).
    Пункты с confidence "social_unverified" уходят в rumors: у них свой,
    более мягкий набор правил, и судить их как detail было бы неверно."""
    context = raw.get("context") or []
    return {
        "lead": raw.get("headline") or "",
        "detail": [c.get("text") or "" for c in context
                   if isinstance(c, dict) and c.get("confidence") in ("quotes", "media")],
        "rumors": [c.get("text") or "" for c in context
                   if isinstance(c, dict) and c.get("confidence") == "social_unverified"],
        "unknown": raw.get("unknown"),
    }


def check(path: Path) -> tuple[dict | None, list[str]]:
    """(payload, нарушения). payload=None, если файла нет или он не парсится."""
    if not path.exists():
        return None, [f"{path} не существует"]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return None, [f"{path} не читается: {e}"]

    validator = _load_validator()
    if validator is None:
        return raw, []
    return raw, validator.validate_tg_payload(_as_tg_payload(raw))


def _fix_prompt(path: Path, violations: list[str], rules_text: str) -> str:
    """Текст, который уходит модели на переделку. Нарушения перечисляются
    дословно, вместе с процитированной фразой -- модель должна видеть не
    «текст не прошёл проверку», а какое правило и на какой именно фразе."""
    numbered = "\n".join(f"{i}. {v}" for i, v in enumerate(violations, 1))
    return f"""Ты писал файл {path} — headline и context для утреннего брифинга SBF.

Публикующий бот прогнал этот текст через свой валидатор, и текст НЕ ПРОШЁЛ.
Пока он не пройдёт, подписчики не увидят аналитическую часть поста вообще —
останется только таблица котировок.

ЧТО ИМЕННО НАРУШЕНО (правило: процитированная фраза):
{numbered}

ПРАВИЛА, по которым идёт проверка:
{rules_text}

Задача: прочитай {path} (Read), перепиши ТОЛЬКО те поля, которые нарушают
правила, и запиши файл обратно по тому же пути (Write), в той же схеме
{{"headline": "...", "context": [{{"text": "...", "confidence": "..."}}, ...],
"unknown": "..."}} — ровно 3 элемента в context, те же confidence, что были.

Смысл и числа сохраняй: это не переписывание содержания, а приведение
формулировок к правилам. Длинное предложение — разбей на два коротких, не
выбрасывай факты. Слово из стоп-списка — замени описанием факта («ожидается
повышение ставки» → «рынок закладывает повышение ставки»), не удаляй пункт.

Верни в stdout только слово OK."""


_RULES_TEXT = """- каждое предложение — не длиннее 25 слов (считаются слова, разделённые
  пробелами; точка с запятой предложение НЕ разделяет);
- headline — ровно одно предложение, не длиннее 110 знаков;
- запрещённые слова прогноза: «ожидается», «продолжит», «вырастет», «упадёт»,
  «цель», «прогноз»;
- запрещённые слова рекомендации: «покупать», «продавать», «стоит»,
  «рекомендуем», «лонг», «шорт»;
- запрещённые симметричные оговорки: «в любую сторону», «в ту или иную
  сторону», «двустороннее движение», «либо … либо», «или голубиным», «или
  ястребиным»;
- «исторически» / «как правило» / «обычно» — только вместе с явным «n=…»;
- «по неподтверждённым», «по данным трейдеров», «по утверждениям в соцсетях»,
  «непроверяем» — допустимы ТОЛЬКО в пункте с confidence "social_unverified".
Проверка идёт по подстроке, поэтому словоформы тоже нарушают: «продолжится»,
«целью», «прогнозный», «не стоит»."""


def _ask_claude_to_fix(path: Path, violations: list[str]) -> bool:
    """True, если claude -p отработал без ошибки. Успех переделки этим не
    доказывается -- он проверяется следующим прогоном check()."""
    try:
        proc = subprocess.run(
            ["claude", "-p", _fix_prompt(path, violations, _RULES_TEXT),
             "--allowedTools", "Read", "Write",
             "--output-format", "text"],
            capture_output=True, text=True, timeout=CLAUDE_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"recheck_context: claude -p не отработал: {e}", file=sys.stderr)
        return False
    if proc.returncode != 0:
        print(f"recheck_context: claude -p вернул {proc.returncode}: "
              f"{(proc.stderr or '').strip()[:500]}", file=sys.stderr)
        return False
    return True


def run(date: str | None = None, attempts: int = DEFAULT_ATTEMPTS,
        check_only: bool = False) -> int:
    from datetime import datetime, timezone
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = REPORTS_DIR / f"context_{date}.json"

    raw, violations = check(path)
    if raw is None:
        print(f"recheck_context: {violations[0]}", file=sys.stderr)
        return 2
    if not violations:
        print(f"recheck_context: {path.name} проходит валидатор пуша", file=sys.stderr)
        return 0

    print(f"recheck_context: нарушений {len(violations)}:", file=sys.stderr)
    for v in violations:
        print(f"  - {v}", file=sys.stderr)

    if check_only:
        return 1

    for attempt in range(1, attempts + 1):
        print(f"recheck_context: попытка переделки {attempt}/{attempts}…", file=sys.stderr)
        if not _ask_claude_to_fix(path, violations):
            return 1
        raw, violations = check(path)
        if raw is None:
            # Модель испортила файл вместо того, чтобы починить -- дальше
            # llm_context.py просто не смержит headline/context, а не упадёт.
            print(f"recheck_context: после переделки {violations[0]}", file=sys.stderr)
            return 2
        if not violations:
            print(f"recheck_context: исправлено с {attempt}-й попытки", file=sys.stderr)
            return 0
        print(f"recheck_context: осталось нарушений {len(violations)}", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)

    print("recheck_context: попытки исчерпаны, текст публикуется как есть "
          "(бот отбракует нарушающие пункты поштучно)", file=sys.stderr)
    return 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None)
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    parser.add_argument("--check-only", action="store_true",
                        help="только проверить и напечатать нарушения, не звать claude")
    args = parser.parse_args()
    sys.exit(run(args.date, args.attempts, args.check_only))


if __name__ == "__main__":
    main()
