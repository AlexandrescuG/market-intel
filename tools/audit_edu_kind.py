"""Какого РОДА интерактив в главе: тренажёр, калькулятор или переключатель.

Разница принципиальная. Тренажёр даёт попытку, ошибку и обратную связь —
читатель делает и узнаёт результат. Калькулятор считает по введённым числам.
Переключатель просто показывает другую часть того же текста.
"""
import re
from pathlib import Path

BOOK = Path("/mnt/sbfdata/sbf-platform/market_intel/web/book")
RE_COMPONENT = re.compile(r"^\s*function ([A-Z][A-Za-z0-9_]*)\s*\(", re.M)

ТРЕНАЖЁР = re.compile(
    r"попыт|attempt|score|очк|streak|раунд|round|правильн|верн[оы]|"
    r"угада|ошиб|проигр|выигр|результат теста|correct|wrong|lives|таймер|timer",
    re.I)
КАЛЬКУЛЯТОР = re.compile(r"<input|type=\"range\"|parseFloat|Number\(|onChange", re.I)
ПЕРЕКЛЮЧАТЕЛЬ = re.compile(r"onClick", re.I)


def тела(src):
    точки = [(m.start(), m.group(1)) for m in RE_COMPONENT.finditer(src)]
    return {имя: src[p:(точки[i + 1][0] if i + 1 < len(точки) else len(src))]
            for i, (p, имя) in enumerate(точки)}


итог = {}
for ch in range(1, 16):
    p = BOOK / f"edu_book_{ch}.html"
    if not p.exists():
        continue
    т = {"тренажёр": [], "калькулятор": [], "переключатель": []}
    for имя, тело in тела(p.read_text(encoding="utf-8")).items():
        if имя in ("Chip", "Mono", "Section"):
            continue
        интер = len(ПЕРЕКЛЮЧАТЕЛЬ.findall(тело)) + len(КАЛЬКУЛЯТОР.findall(тело))
        if интер < 2:
            continue
        if len(ТРЕНАЖЁР.findall(тело)) >= 3:
            т["тренажёр"].append(имя)
        elif КАЛЬКУЛЯТОР.search(тело):
            т["калькулятор"].append(имя)
        else:
            т["переключатель"].append(имя)
    итог[ch] = т

print(f"{'гл':>3} {'тренажёров':>11} {'калькуляторов':>14} {'переключателей':>15}")
for ch, т in итог.items():
    print(f"{ch:3d} {len(т['тренажёр']):11d} {len(т['калькулятор']):14d} "
          f"{len(т['переключатель']):15d}   {', '.join(т['тренажёр'])}")

п = [итог[c] for c in range(1, 6)]
в = [итог[c] for c in range(6, 16)]
for k in ("тренажёр", "калькулятор", "переключатель"):
    a = sum(len(x[k]) for x in п) / len(п)
    b = sum(len(x[k]) for x in в) / len(в)
    print(f"\n{k:14s} главы 1-5: {a:.1f}   главы 6-15: {b:.1f}   "
          f"{(f'{b/a:.2f}x' if a else '—')}")
