#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/agent_run.py — WP4.3 SPEC_alpha_engine_wp4_continuous_cycle.md.

Вызов агента на ВЕСЬ бандл разом (не один сигнал за раз, как
`tools/agent/run_analyst.py` — тот остаётся ручным dev-инструментом для
разбора одного сигнала в изоляции). Модель читает `bundle.md` САМА (Read,
живьём проверенный синтаксис `Read(<abs_dir>/*)` 13.08 — permission не
отклонён), не получает содержимое инлайн в промпте: дешевле по токенам и
честнее по аудиту (виден реальный tool-call `Read` в логе).

Механика вызова claude -p перенесена из `run_analyst.py` почти 1:1
(`--model claude-haiku-4-5-20251001` — без явного `--model` дефолт Opus
стоил $0.27 за тривиальный вызов, найдено 12.08; `structured_output`
надёжнее парсинга `result`; `cwd` явный, обе формы allowlist-путей —
модель может вызвать инструмент и абсолютным, и относительным путём).

НЕ пишет в БД — возвращает распарсенный ответ + метаданные вызова
(`duration_ms`/`cost_usd`/`exit_code`/сырой stdout). Запись — целиком
`analyze/validate.py`.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

CLAUDE_BIN = str(Path.home() / ".local" / "bin" / "claude")
CLAUDE_TIMEOUT_SEC = 150  # бандл + разбор 0-3 кандидатов -- дольше одного сигнала (run_analyst.py: 90с)
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_BUDGET_USD = 0.20

_MARKET_INTEL_ROOT = Path(__file__).parent.parent
_TOOLS_DIR = _MARKET_INTEL_ROOT / "tools" / "agent"
_CYCLE_DIR = _MARKET_INTEL_ROOT / "data" / "cycle"

_ALLOWED_TOOLS = [
    f"Read({_CYCLE_DIR}/*)",
    "Read(data/cycle/*)",
    f"Bash(python3 {_TOOLS_DIR}/q_snapshot.py *)",
    f"Bash(python3 {_TOOLS_DIR}/q_base_rate.py *)",
    f"Bash(python3 {_TOOLS_DIR}/q_news.py *)",
    "Bash(python3 tools/agent/q_snapshot.py *)",
    "Bash(python3 tools/agent/q_base_rate.py *)",
    "Bash(python3 tools/agent/q_news.py *)",
]
_DISALLOWED_TOOLS = ["Bash(sqlite3 *)", "Bash(rm *)", "Write", "Edit"]

_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "forecasts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"}, "pattern_key": {"type": "string"},
                    "direction": {"type": "string"}, "config_key": {"type": "string"},
                    "base_rate": {"type": ["number", "null"]},
                    "base_n": {"type": ["integer", "null"]},
                    "base_backoff_level": {"type": ["integer", "null"]},
                    "adjustment": {"type": "number"}, "adjustment_reason": {"type": "string"},
                    "cited_factors": {"type": "array", "items": {"type": "string"}},
                    "novel_risk": {"type": ["string", "null"]},
                    "final_p": {"type": ["number", "null"]},
                    "thesis": {"type": "string"}, "invalidation": {"type": "string"},
                },
                "required": ["symbol", "pattern_key", "direction", "config_key", "adjustment",
                             "adjustment_reason", "cited_factors", "thesis", "invalidation"],
            },
        }
    },
    "required": ["forecasts"],
}


def build_prompt(bundle_md_path: Path) -> str:
    return f"""Ты — analyst-роль непрерывного цикла WP4 (SPEC_alpha_engine_wp4_continuous_cycle.md).
ТЫ НЕ ПРОИЗВОДИШЬ ВЕРОЯТНОСТЬ С НУЛЯ, только ограниченную поправку к уже
посчитанной эмпирической базовой ставке.

Прочитай (Read) файл: {bundle_md_path}

Секция "focus" — инструменты, прошедшие гейт внимания в этом цикле. Для
КАЖДОГО кандидата из "focus" верни один объект в массиве forecasts, со
ВСЕМИ полями схемы. Секции "calendar"/"news"/"macro"/"watch"/"calibration"
— контекст для твоего решения, не требуют отдельного вывода.

ЖЁСТКИЕ ПРАВИЛА КОНТРАКТА (нарушение -> твой ответ будет отклонён целиком):
  - base_rate/base_n/base_backoff_level -- ПЕРЕПИШИ буквально из bundle
    (candidates[i].base_rate в секции focus) -- НЕ уточняй, не пересчитывай;
  - |adjustment| > 0.15 (15 п.п.) -- ТОЛЬКО если cited_factors называет
    конкретный фактор из вектора состояния ЭТОГО кандидата;
  - если base_rate кандидата -- "недостаточно данных" (insufficient=true),
    final_p ДОЛЖЕН быть null, можешь писать только novel_risk и thesis;
  - final_p (если не null) = base_rate.p + adjustment (с точностью округления);
  - novel_risk -- то, чего вектор состояния не покрывает вообще (геополитика,
    внеплановое решение ЦБ), НЕ конвертируется в число;
  - если секция "focus" пуста или в ней нет кандидатов -- верни {{"forecasts": []}}.

Тебе доступны read-only инструменты для самопроверки любого числа выше
(не обязательно):
  python3 tools/agent/q_snapshot.py --symbol <symbol> --tf <tf>
  python3 tools/agent/q_base_rate.py --symbol <symbol> --tf <tf> --pattern <p> --direction <d> --atr-mult <a> --rr <r> --horizon-bars <h>
  python3 tools/agent/q_news.py --symbol <symbol> --hours 6

Верни СТРОГО JSON по схеме."""


def call_agent(bundle_md_path: Path, max_budget_usd: float = DEFAULT_MAX_BUDGET_USD,
               model: str = DEFAULT_MODEL) -> dict:
    """Никогда не raise -- любой сбой возвращается как {"ok": False, "error": ...}.
    Возвращает {"ok","forecasts","duration_ms","cost_usd","exit_code","raw_stdout","error","model"}."""
    prompt = build_prompt(bundle_md_path)
    cmd = [CLAUDE_BIN, "-p", prompt,
           "--allowedTools", *_ALLOWED_TOOLS,
           "--disallowedTools", *_DISALLOWED_TOOLS,
           "--output-format", "json",
           "--json-schema", json.dumps(_JSON_SCHEMA),
           "--max-budget-usd", str(max_budget_usd),
           "--model", model]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, timeout=CLAUDE_TIMEOUT_SEC, capture_output=True, text=True,
                               check=False, cwd=str(_MARKET_INTEL_ROOT))
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"ok": False, "forecasts": [], "duration_ms": int((time.time() - t0) * 1000),
                "cost_usd": None, "exit_code": -1, "raw_stdout": "",
                "error": f"{type(e).__name__}: {e}", "model": model}

    duration_ms = int((time.time() - t0) * 1000)
    if proc.returncode != 0:
        return {"ok": False, "forecasts": [], "duration_ms": duration_ms, "cost_usd": None,
                "exit_code": proc.returncode, "raw_stdout": proc.stdout,
                "error": proc.stderr[:2000], "model": model}

    try:
        envelope = json.loads(proc.stdout)
        if isinstance(envelope, dict) and envelope.get("structured_output") is not None:
            resp = envelope["structured_output"]
        else:
            resp = envelope.get("result") if isinstance(envelope, dict) else envelope
            if isinstance(resp, str):
                resp = json.loads(resp)
        forecasts = resp.get("forecasts", []) if isinstance(resp, dict) else []
        cost_usd = envelope.get("total_cost_usd") if isinstance(envelope, dict) else None
        usage = envelope.get("usage", {}) if isinstance(envelope, dict) else {}
        return {"ok": True, "forecasts": forecasts, "duration_ms": duration_ms, "cost_usd": cost_usd,
                "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                "exit_code": proc.returncode, "raw_stdout": proc.stdout, "error": None, "model": model}
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as e:
        return {"ok": False, "forecasts": [], "duration_ms": duration_ms, "cost_usd": None,
                "exit_code": proc.returncode, "raw_stdout": proc.stdout,
                "error": f"невалидный JSON: {e}", "model": model}


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle-md", required=True)
    ap.add_argument("--max-budget-usd", type=float, default=DEFAULT_MAX_BUDGET_USD)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.dry_run:
        print(build_prompt(Path(args.bundle_md)))
        print("\n=== JSON SCHEMA ===")
        print(json.dumps(_JSON_SCHEMA, ensure_ascii=False, indent=2))
        return

    result = call_agent(Path(args.bundle_md), args.max_budget_usd, args.model)
    print(json.dumps({k: v for k, v in result.items() if k != "raw_stdout"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
