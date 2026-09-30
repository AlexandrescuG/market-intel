#!/usr/bin/env python3
"""analyze/notify_degraded.py — сказать владельцу, что брифинг идёт без аналитики.

29.09.2026. С 17 по 29 сентября утренний брифинг не собирался вовсе: у
организации отключили доступ к Claude Code, run_daily.sh делал `exit 1` на
втором шаге и дальше не шёл. Двенадцать дней — и ни одного сообщения: юнит
числился failed, а failed у oneshot-сервиса никого не будит.

ПОЧЕМУ НЕ «ОДИН АЛЕРТ В ДЕНЬ». Первая версия слала одинаковый текст раз в
сутки. При отключении на две недели это четырнадцать одинаковых сообщений —
владелец сразу сказал, что так нельзя. Повторяющееся сообщение перестают
читать, и вместе с ним перестают замечать настоящие.

Поэтому состояние аварии ведётся в файле, а голос подаётся по расписанию:
  день 1  — подробно, с причиной и что проверить;
  дни 2-3 — молчание (владелец уже знает);
  далее   — короткое напоминание раз в три дня, с номером дня;
  возврат — отдельное сообщение «аналитика вернулась».
Смена причины (был отказ подписки, стал таймаут) считается новой аварией и
докладывается сразу: это другая поломка, а не та же самая.

Использование:
  python3 -m analyze.notify_degraded --reason "claude -p недоступен"
  python3 -m analyze.notify_degraded --recovered
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_STATE = Path(__file__).parent.parent / "data" / "degraded_state.json"

# Через сколько дней аварии повторять напоминание. Три — компромисс: не
# каждый день, но и не раз в неделю, когда можно забыть совсем.
REMIND_EVERY_DAYS = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load() -> dict:
    try:
        return json.loads(_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(state: dict) -> None:
    try:
        _STATE.parent.mkdir(parents=True, exist_ok=True)
        _STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    except OSError as e:
        print(f"notify_degraded: состояние не записано: {e}", file=sys.stderr)


def _send(text: str) -> bool:
    try:
        from analyze.outbox import enqueue_ops
        enqueue_ops(text)
        return True
    except Exception as e:
        print(f"notify_degraded: алерт не поставлен в очередь: {e}", file=sys.stderr)
        return False


def _показать(text: str) -> bool:
    """Замена отправки для сухого прогона: печатает то, что ушло бы."""
    print("--- было бы отправлено ---")
    print(text)
    print("--- конец ---")
    return True


def _first_message(reason: str) -> str:
    return (
        "⚠️ <b>Брифинг собран без аналитической части</b>\n\n"
        f"Причина: {reason}\n\n"
        "Числа, календарь, выбросы и картинка на месте — их считает Python. "
        "Нет только текста от модели: подписчики получают сокращённый вид "
        "и ссылку на календарь недели.\n\n"
        "Проверить: <code>claude -p \"ок\"</code>. Если доступ к подписке "
        "закрыт — нужен ANTHROPIC_API_KEY в market_intel/.env.\n\n"
        "Дальше напомню на 4-й день: одинаковые сообщения каждое утро "
        "читать невозможно."
    )


def _reminder(day: int, reason: str) -> str:
    return (f"⚠️ Аналитики в брифинге нет {day}-й день подряд. "
            f"Причина прежняя: {reason}. Остальное уходит как обычно.")


def _recovered_message(days: int) -> str:
    return (f"✅ Аналитическая часть брифинга вернулась "
            f"(была недоступна {days} "
            f"{'день' if days == 1 else 'дня' if 2 <= days <= 4 else 'дней'}).")


def notify(reason: str, force: bool = False, сухой: bool = False) -> bool:
    """Сообщить об аварии по расписанию. True — сообщение отправлено.

    🔴 `сухой` — не роскошь. Этот модуль срабатывает ровно в тот момент,
    когда всё остальное уже сломано, и до 29.09 проверить его можно было
    только настоящей отправкой в операционный канал. Значит его либо не
    проверяли вовсе, либо проверяли, засоряя тот самый канал, тишина в
    котором и есть его продукт. Сухой прогон печатает решение и текст,
    ничего не отправляя и не трогая состояние.
    """
    state = _load()
    today = _now().date().isoformat()

    отправить = _показать if сухой else _send
    сохранить = (lambda *_: None) if сухой else _save

    # Новая авария: либо её не было, либо изменилась причина.
    if not state.get("since") or state.get("reason") != reason:
        if отправить(_first_message(reason)):
            сохранить({"since": today, "reason": reason, "last_notified": today})
            print("notify_degraded: первое сообщение об аварии", file=sys.stderr)
            return True
        return False

    since = datetime.fromisoformat(state["since"]).date()
    day = (_now().date() - since).days + 1
    last = state.get("last_notified")

    if force or (day >= 4 and (day - 1) % REMIND_EVERY_DAYS == 0 and last != today):
        if отправить(_reminder(day, reason)):
            state["last_notified"] = today
            сохранить(state)
            print(f"notify_degraded: напоминание, день {day}", file=sys.stderr)
            return True
        return False

    print(f"notify_degraded: день {day} — молчу, чтобы не повторяться",
          file=sys.stderr)
    return False


def recovered(сухой: bool = False) -> bool:
    """Сообщить, что аналитика вернулась. Молчит, если аварии не было."""
    state = _load()
    if not state.get("since"):
        print("notify_degraded: аварии не было — молчу", file=sys.stderr)
        return False
    since = datetime.fromisoformat(state["since"]).date()
    days = max(1, (_now().date() - since).days)
    sent = (_показать if сухой else _send)(_recovered_message(days))
    # Состояние снимаем в любом случае: авария кончилась, и следующая должна
    # доложиться как первая, даже если это сообщение не ушло. При сухом
    # прогоне не снимаем: проверка не должна менять картину мира.
    if not сухой:
        _save({})
    return sent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reason")
    ap.add_argument("--recovered", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="показать решение и текст, ничего не отправляя "
                         "и не меняя состояние")
    args = ap.parse_args()

    if args.recovered:
        recovered(сухой=args.dry_run)
        return 0
    if not args.reason:
        ap.error("нужен --reason или --recovered")
    notify(args.reason, args.force, сухой=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
