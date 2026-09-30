"""Golden-file тесты на analyze/bundle.py::_render_md() -- ревью 14.08, п.3:
"баги переехали на стык скриптов и модели" (Read bundle.md -> claude -p),
этот стык не был покрыт ничем. Прецедент, который эти тесты ловят задним
числом: пустой список candidates у одного символа перед непустым визуально
сливал их блоки "### SYMBOL TF" -- живой H4-прогон поймал модель (Haiku),
реально приписавшую кандидатов не тому символу (см. Core-лог 14.08).
Golden-файл фиксирует ТОЧНЫЙ текст, который видит модель -- регрессия в
рендере (не в логике вокруг него) ловится диффом, не требует живого вызова
`claude -p` за каждый прогон CI.

Golden-файлы в tests/golden/*.md записаны руками после ручной проверки
вывода глазами (не auto-record при первом запуске теста -- иначе тест
"проходит" даже если исходный вывод сам был багом)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze.bundle import _render_md, _truncate

_GOLDEN_DIR = Path(__file__).parent / "golden"


def _read_golden(name: str) -> str:
    return (_GOLDEN_DIR / name).read_text()


def test_render_empty_candidates_block_has_explicit_placeholder():
    """🔴 Регрессионный тест на реальный баг 14.08: EURUSD:H4 (пустые
    candidates) стоит ПЕРЕД USDJPY:H4 (два кандидата) -- их блоки не
    должны сливаться, у пустого должна быть явная строка-заполнитель."""
    bundle = {
        "generated_at_iso": "2026-08-14T00:00:00Z",
        "sections_included": ["calendar", "news", "watch"],
        "gaps": [],
        "focus": {
            "EURUSD:H4": {"symbol": "EURUSD", "tf": "H4",
                          "state": {"session": "asia", "trend_regime": "range"}, "candidates": []},
            "USDJPY:H4": {"symbol": "USDJPY", "tf": "H4",
                          "state": {"session": "asia", "trend_regime": "range"},
                          "candidates": [{"pattern_key": "double_top", "direction": "bearish",
                                          "config_key": "a1.5_r2.0_h30_costsv1", "tf": "H4",
                                          "base_rate": {"insufficient": False, "p": 0.1176, "n": 34}}]},
        },
        "calendar": [], "news": [], "macro": {}, "watch": [], "calibration": {},
    }
    md = _render_md(bundle)
    assert md == _read_golden("bundle_empty_candidates.md")
    # Явный якорь на сам механизм фикса -- если кто-то уберёт строку-
    # заполнитель, но случайно не тронет golden-файл, этот assert всё
    # равно поймает регрессию отдельно от полного посимвольного сравнения.
    eurusd_block = md.split("### EURUSD H4")[1].split("### USDJPY H4")[0]
    assert "кандидатов для разбора нет" in eurusd_block
    assert "double_top" not in eurusd_block


def test_render_single_symbol_minimal_profile():
    """Один символ в focus, минимальный (h1-подобный) профиль -- только
    news в sections_included, остальные явно "вне профиля"."""
    bundle = {
        "generated_at_iso": "2026-08-14T01:00:00Z",
        "sections_included": ["news"],
        "gaps": [],
        "focus": {
            "GOLD:H1": {"symbol": "GOLD", "tf": "H1", "state": {"session": "london"},
                        "candidates": [{"pattern_key": "hammer", "direction": "bullish",
                                        "config_key": "a1.5_r2.0_h30_costsv1", "tf": "H1",
                                        "base_rate": {"insufficient": True, "p": None, "n": 5}}]},
        },
        "calendar": [],
        "news": [{"symbol": "GOLD", "title": "Fed minutes released", "url": "http://example.com/1",
                  "ts": 1000, "importance": 3}],
        "macro": {}, "watch": [], "calibration": {},
    }
    md = _render_md(bundle)
    assert md == _read_golden("bundle_single_symbol.md")


def test_render_truncated_section():
    """_truncate() режет watch наполовину при переполнении char_limit --
    рендер должен показать РОВНО усечённый список + note в gaps, не
    полный список и не пустой."""
    watch_items = [{"symbol": f"SYM{i}", "tf": "D1", "move_atr": 0.1 * i, "score": 0.05 * i}
                   for i in range(30)]
    bundle = {
        "generated_at_iso": "2026-08-14T02:00:00Z",
        "sections_included": ["watch"],
        "gaps": [],
        "focus": {},
        "calendar": [], "news": [], "macro": {}, "watch": watch_items, "calibration": {},
    }
    truncated, notes = _truncate(bundle, char_limit=800)
    truncated["gaps"].extend(notes)
    md = _render_md(truncated)
    assert len(truncated["watch"]) == 15
    assert notes == ["секция watch усечена, показано 15 из 30"]
    assert md == _read_golden("bundle_truncated.md")
