"""channel_agent/compose.py — факт-пакет → готовый пост.

Модель вызывается тем же способом, что и утренний синтез: `claude -p`,
headless, без инструментов. Инструменты ей здесь не нужны — все факты уже
собраны Python'ом и переданы в промпте; дать ей доступ к файлам значило бы
разрешить дописать в пост что-то, чего мы не измеряли.

Проверка текста — ТЕМ ЖЕ валидатором, что стоит на утреннем брифинге. Он
загружается из файла бота, а не копируется сюда: две копии правил уже
расходились однажды (31.08, пост терял всю аналитическую часть).
"""
from __future__ import annotations

import importlib.util
import json
import logging
import re
import subprocess
from pathlib import Path

from channel_agent import prompts

log = logging.getLogger("channel_agent.compose")

_BOT_VALIDATE_PY = Path(
    "/mnt/sbfdata/sbf-platform/SBFAcademy_bot/sbfacademy/briefing/validate.py"
)
CLAUDE_TIMEOUT = 300
MAX_ATTEMPTS = 2          # черновик + одна переделка по замечаниям валидатора


def _load_validator():
    if not _BOT_VALIDATE_PY.exists():
        log.warning("валидатор %s не найден — пост уйдёт без проверки", _BOT_VALIDATE_PY)
        return None
    spec = importlib.util.spec_from_file_location("_bot_validate", _BOT_VALIDATE_PY)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_TAG_RE = re.compile(r"<[^>]+>")


def check(text: str) -> list[str]:
    """Нарушения правил в готовом посте. Пустой список — можно публиковать.

    Валидатор написан под поля брифинга, поэтому текст подаётся ему как
    единый блок «detail»: правила там про формулировки, а не про структуру.
    Разметку снимаем — <b> и <a href> не должны считаться словами.
    """
    validator = _load_validator()
    if validator is None:
        return []
    plain = _TAG_RE.sub("", text)
    # Шапка с хештегами — не предложение, к ней правила про длину и стоп-слова
    # неприменимы: «#прогноз» там был бы ложным срабатыванием.
    body = "\n".join(plain.split("\n")[1:]) if "\n" in plain else plain
    return validator.validate_text("пост", body)


def _run_claude(prompt: str) -> str | None:
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True, text=True, timeout=CLAUDE_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        log.error("claude -p не отработал: %s", e)
        return None
    if proc.returncode != 0:
        log.error("claude -p вернул %s: %s", proc.returncode, (proc.stderr or "")[:300])
        return None
    return proc.stdout.strip()


def _parse(raw: str) -> dict | None:
    """JSON из ответа модели. Терпим ```-обрамление и болтовню вокруг —
    падать из-за форматирования ответа незачем, когда сам JSON виден."""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    log.error("ответ модели не разобран: %r", raw[:300])
    return None


def write_post(rubric: str, facts: dict) -> dict | None:
    """{"text":..., "image_hint":...} или None (отказ модели либо неудача).

    Отказ — штатный исход, а не сбой: промпт прямо разрешает не писать пост,
    если повод не годится. Пустой канал лучше поста, вводящего в заблуждение.
    """
    prompt = prompts.build(rubric, json.dumps(facts, ensure_ascii=False, indent=1))

    for attempt in range(1, MAX_ATTEMPTS + 1):
        out = _parse(_run_claude(prompt) or "")
        if out is None:
            return None
        if out.get("skip"):
            log.info("рубрика %s: модель отказалась — %s", rubric, out.get("why"))
            return None
        text = (out.get("text") or "").strip()
        if not text:
            return None

        problems = check(text)
        if not problems:
            return {"text": text, "image_hint": (out.get("image_hint") or "").strip()}

        log.warning("рубрика %s, попытка %d: %s", rubric, attempt, problems)
        if attempt == MAX_ATTEMPTS:
            # Не публикуем «почти прошедший» текст: правила писались под
            # юридические риски, а не под красоту.
            return None
        numbered = "\n".join(f"{i}. {p}" for i, p in enumerate(problems, 1))
        prompt = (f"{prompts.build(rubric, json.dumps(facts, ensure_ascii=False, indent=1))}\n\n"
                  f"ПРЕДЫДУЩИЙ ВАРИАНТ НЕ ПРОШЁЛ ПРОВЕРКУ:\n{text}\n\n"
                  f"НАРУШЕНИЯ:\n{numbered}\n\n"
                  f"Перепиши, устранив ровно эти нарушения. Факты и числа сохрани.")
    return None
