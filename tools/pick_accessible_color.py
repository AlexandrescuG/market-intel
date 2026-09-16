#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pick_accessible_color.py — подобрать ближайший цвет, проходящий AA.

Не «затемнить на глаз», а найти минимальное изменение, при котором текст
проходит порог на ЗАДАННОМ фоне. Тон (hue) и насыщенность сохраняются —
двигается только светлота в OKLab-подобном приближении через HLS, поэтому
золото остаётся золотом, а не becomes коричневым.

Запуск:
    python3 tools/pick_accessible_color.py '#7C7563' --fon '#FBF6EF'
    python3 tools/pick_accessible_color.py '#C9A227' --fon '#FBF6EF' --porog 4.5
"""
from __future__ import annotations

import argparse
import colorsys
import sys


def в_rgb(s: str) -> tuple[int, int, int]:
    s = s.strip().lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def в_hex(t: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(v))):02X}" for v in t)


def яркость(rgb: tuple[int, int, int]) -> float:
    к = []
    for v in rgb:
        v /= 255
        к.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * к[0] + 0.7152 * к[1] + 0.0722 * к[2]


def отношение(a, b) -> float:
    la, lb = яркость(a), яркость(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def подобрать(цвет: str, фон: str, порог: float) -> tuple[str, float, float]:
    исх = в_rgb(цвет)
    ф = в_rgb(фон)
    r, g, b = (v / 255 for v in исх)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    # Двигаем светлоту в ту сторону, где контраст растёт: от светлого фона —
    # вниз, от тёмного — вверх. Направление считается, а не предполагается:
    # на тёмных страницах (/admin, /journal в тёмной теме) правило обратное.
    вниз = яркость(ф) > яркость(исх)
    шаг = -0.002 if вниз else 0.002
    текущ = l
    for _ in range(600):
        проб = tuple(round(v * 255) for v in colorsys.hls_to_rgb(h, текущ, s))
        к = отношение(проб, ф)
        if к >= порог:
            return в_hex(проб), к, отношение(исх, ф)
        текущ += шаг
        if not 0 <= текущ <= 1:
            break
    return "—", 0.0, отношение(исх, ф)


def main() -> int:
    р = argparse.ArgumentParser()
    р.add_argument("cvet", help="исходный цвет, #RRGGBB")
    р.add_argument("--fon", default="#FBF6EF")
    р.add_argument("--porog", type=float, default=4.5)
    а = р.parse_args()

    новый, стало, было = подобрать(а.cvet, а.fon, а.porog)
    print(f"{а.cvet} на {а.fon}: {было:.2f}:1  (порог {а.porog})")
    if было >= а.porog:
        print("   уже проходит, менять нечего")
    else:
        print(f"   → {новый}: {стало:.2f}:1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
