"""Из чего состоят главы курса: интерактив против прозы.

Компонент считается ИНТЕРАКТИВНЫМ, только если внутри его тела есть то, на
что читатель может подействовать: состояние, обработчик, поле ввода, канвас,
перетаскивание. Компонент, который просто рисует карточку с текстом, —
оформление, а не интерактив, и в этом вся разница между «поиграй» и «прочитай».
"""
import json
import re
import sys
from pathlib import Path

BOOK = Path("/mnt/sbfdata/sbf-platform/market_intel/web/book")

RE_COMPONENT = re.compile(r"^\s*function ([A-Z][A-Za-z0-9_]*)\s*\(", re.M)
OFORMLENIE = {"Chip", "Mono", "Section", "Card", "Divider", "Badge"}

ПРИЗНАКИ = {
    "состояние": re.compile(r"React\.useState|(?<![.\w])useState\("),
    "клик": re.compile(r"onClick\s*[:=]"),
    "ввод": re.compile(r"onChange\s*[:=]|onInput\s*[:=]|<input|<select|<textarea"),
    "канвас": re.compile(r"<canvas|getContext\("),
    "анимация": re.compile(r"requestAnimationFrame|setInterval\("),
    "перетаскивание": re.compile(r"onMouseDown|onPointerDown|onTouchStart"),
}

RE_LONG_STRING = re.compile(r'"((?:[^"\\]|\\.){90,})"')
RE_CYR = re.compile(r"[А-Яа-яЁё]")


def тела_компонентов(src: str) -> dict[str, str]:
    """{имя: тело} — от объявления до следующего объявления."""
    точки = [(m.start(), m.group(1)) for m in RE_COMPONENT.finditer(src)]
    out = {}
    for i, (poz, имя) in enumerate(точки):
        конец = точки[i + 1][0] if i + 1 < len(точки) else len(src)
        out[имя] = src[poz:конец]
    return out


def analyse(path: Path) -> dict:
    src = path.read_text(encoding="utf-8")
    тела = тела_компонентов(src)
    живые, мёртвые = [], []
    for имя, тело in тела.items():
        if имя in OFORMLENIE:
            continue
        сколько = sum(len(rx.findall(тело)) for rx in ПРИЗНАКИ.values())
        (живые if сколько >= 2 else мёртвые).append(имя)

    проза = [m.group(1) for m in RE_LONG_STRING.finditer(src)
             if RE_CYR.search(m.group(1))]
    длины = sorted((len(p) for p in проза), reverse=True)
    очень_длинных = sum(1 for d in длины if d >= 400)
    return {
        "интерактивных": len(живые), "оформления": len(мёртвые),
        "живые": живые,
        "прозы": sum(длины), "абзацев": len(длины),
        "медиана": длины[len(длины) // 2] if длины else 0,
        "макс": длины[0] if длины else 0,
        "абзацев_400+": очень_длинных,
        "байт": len(src.encode("utf-8")),
    }


def main() -> int:
    rows = []
    for ch in range(1, 16):
        p = BOOK / f"edu_book_{ch}.html"
        if p.exists():
            d = analyse(p)
            d["глава"] = ch
            rows.append(d)

    print(f"{'гл':>3} {'интеракт':>9} {'оформл':>7} {'прозы':>7} {'абз':>4} "
          f"{'медиана':>8} {'макс':>5} {'абз≥400':>8} {'проза/интеракт':>15}")
    for d in rows:
        на_один = d["прозы"] // max(d["интерактивных"], 1)
        print(f"{d['глава']:3d} {d['интерактивных']:9d} {d['оформления']:7d} "
              f"{d['прозы']:7d} {d['абзацев']:4d} {d['медиана']:8d} {d['макс']:5d} "
              f"{d['абзацев_400+']:8d} {на_один:15d}")

    п, в = rows[:5], rows[5:]
    ср = lambda rs, k: sum(r[k] for r in rs) / len(rs)  # noqa: E731
    print("\n                            главы 1-5   главы 6-15   отношение")
    for k, подпись in (("интерактивных", "интерактивных блоков"),
                       ("оформления", "статичных компонентов"),
                       ("прозы", "символов прозы"),
                       ("абзацев", "абзацев"),
                       ("медиана", "медиана абзаца"),
                       ("абзацев_400+", "абзацев от 400 знаков")):
        a, b = ср(п, k), ср(в, k)
        print(f"  {подпись:26s} {a:9.1f} {b:12.1f} {(f'{b/a:.2f}x' if a else '—'):>11}")

    a = ср(п, "прозы") / max(ср(п, "интерактивных"), 1)
    b = ср(в, "прозы") / max(ср(в, "интерактивных"), 1)
    print(f"  {'символов на интерактив':26s} {a:9.0f} {b:12.0f} {b/a:10.2f}x")

    print("\nчто именно интерактивного в главах:")
    for d in rows:
        print(f"  {d['глава']:2d}: {', '.join(d['живые']) or '— ничего —'}")

    (BOOK.parent.parent / "tools" / "_audit.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
