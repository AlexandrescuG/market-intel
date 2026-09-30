#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_fed_history.py — что РЕАЛЬНО было при каждом уровне ставки ФРС.

🔴 ЗАЧЕМ. В симуляторе ФРС главы 2 значения активов считались пятью
формулами, набранными руками:

    dxy   = 96    + rate * 1.55
    sp500 = 5800  - rate * 160
    gold  = 2450  - rate * 28
    btc   = 68000 - rate * 4200
    bonds = 3.5   + rate * 0.45

а подпись под ними сообщала: «Упрощённая модель корреляций на основе
исторических данных 1990–2024». Никакой регрессии за этими числами не
стояло: ни файла, ни расчёта, ни даже комментария о том, откуда взяты
коэффициенты. Читателю показывали прямую линию и называли её выводом из
тридцатилетней истории.

Вдвойне заметно это было потому, что рядом, в пресетах «2020» и «2023»,
стоят настоящие котировки на дату — и они честно помечены: «Это не
модель — реальные котировки на указанную дату».

🔴 ЧТО ВМЕСТО. Не «модель предсказывает», а «так БЫВАЛО». Берём месячную
историю, раскладываем месяцы по корзинам ставки и считаем медиану каждого
актива внутри корзины. Читатель двигает ползунок и видит: при такой
ставке рынок в среднем стоял вот здесь, и это наблюдалось столько-то
месяцев, с такого по такой. Ни одного числа, которого не было бы в
данных.

Медиана, а не среднее: корзины маленькие, один выброс (ковидный март)
уводит среднее и не трогает медиану.

Честные ограничения, которые обязаны попасть в файл и на экран:
  · история — с 2016 года (FRED отдаёт SP500 только за 10 лет). Никаких
    «1990–2024»: этих данных у нас нет;
  · связь «ставка → актив» здесь не причинная. Это совпадение во времени,
    и в подписи так и сказано. Инструмент показывает обстановку, а не
    предсказание;
  · корзины, где меньше ПОРОГ месяцев, в файл не попадают: три месяца —
    не наблюдение, а анекдот.

ИСТОЧНИКИ: FRED (DFF, SP500, DTWEXBGS, DGS10) и yfinance (GC=F, BTC-USD).

Запуск: python3 tools/build_fed_history.py
Частота: раз в месяц достаточно — ряд месячный.
"""
from __future__ import annotations

import json
import logging
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(КОРЕНЬ))
from core.fred import series  # noqa: E402

log = logging.getLogger("fed_history")
ВЫХОД = КОРЕНЬ / "web" / "data" / "edu_capsules" / "fed_history.json"

ШАГ = 0.5          # ширина корзины по ставке, %
ПОРОГ = 4          # меньше четырёх месяцев — корзину не показываем
ЛЕТ = 11


def помесячно(ряд: list[dict]) -> dict[str, float]:
    """Дневной ряд FRED → медиана по каждому месяцу («2026-09» → 3.63)."""
    по_месяцам = defaultdict(list)
    for о in ряд:
        по_месяцам[о["date"][:7]].append(о["value"])
    return {м: statistics.median(з) for м, з in по_месяцам.items()}


def из_yfinance(тикер: str) -> dict[str, float]:
    import yfinance as yf
    таблица = yf.Ticker(тикер).history(period=f"{ЛЕТ}y", interval="1mo")
    if таблица.empty:
        log.error("yfinance %s: пусто", тикер)
        return {}
    # 🔴 Известная беда yfinance в этом проекте: при конкурентных вызовах
    # кэш мутирует и всем активам достаётся один и тот же ряд. Здесь вызовы
    # строго последовательные, и на выходе стоит проверка правдоподобия.
    return {д.strftime("%Y-%m"): float(ц)
            for д, ц in zip(таблица.index, таблица["Close"])}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    дней = ЛЕТ * 366
    ставка = помесячно(series("DFF", дней))
    активы = {
        "spx": помесячно(series("SP500", дней)),
        "dxy": помесячно(series("DTWEXBGS", дней)),
        "bonds": помесячно(series("DGS10", дней)),
        "gold": из_yfinance("GC=F"),
        "btc": из_yfinance("BTC-USD"),
    }

    # Проверка правдоподобия: золото и биткойн обязаны отличаться на порядок.
    # Если yfinance подсунул один ряд обоим, это видно сразу.
    зол = list(активы["gold"].values())
    бтк = list(активы["btc"].values())
    if зол and бтк and abs(statistics.median(зол) - statistics.median(бтк)) < 1000:
        log.error("золото и биткойн подозрительно похожи — вероятна мутация "
                  "кэша yfinance. Файл не тронут.")
        return 1

    корзины: dict[float, dict] = defaultdict(lambda: defaultdict(list))
    месяцы: dict[float, list[str]] = defaultdict(list)
    for м, с in ставка.items():
        корзина = round(round(с / ШАГ) * ШАГ, 2)
        есть_всё = all(м in ряд for ряд in активы.values())
        if not есть_всё:
            continue
        месяцы[корзина].append(м)
        for имя, ряд in активы.items():
            корзины[корзина][имя].append(ряд[м])

    вышло = []
    for корзина in sorted(корзины):
        сколько = len(месяцы[корзина])
        if сколько < ПОРОГ:
            log.info("корзина %.2f%%: всего %d месяцев — пропускаем", корзина, сколько)
            continue
        запись = {"ставка": корзина, "месяцев": сколько,
                  "от": min(месяцы[корзина]), "до": max(месяцы[корзина])}
        for имя, значения in корзины[корзина].items():
            запись[имя] = round(statistics.median(значения),
                                2 if имя in ("bonds", "dxy") else 0)
        вышло.append(запись)

    if not вышло:
        log.error("ни одной корзины не набралось — файл не тронут")
        return 1

    ВЫХОД.parent.mkdir(parents=True, exist_ok=True)
    ВЫХОД.write_text(json.dumps({
        "собрано": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "источники": "FRED (DFF, SP500, DTWEXBGS, DGS10) · Yahoo Finance (GC=F, BTC-USD)",
        "шаг": ШАГ,
        "порог_месяцев": ПОРОГ,
        "оговорка": "Медианы месячных значений в месяцы с такой ставкой. "
                    "Это совпадение во времени, а не причинная связь.",
        "корзины": вышло,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    log.info("корзин: %d → %s", len(вышло), ВЫХОД.relative_to(КОРЕНЬ))
    for з in вышло:
        log.info("  %4.2f%%  n=%-3d %s..%s  S&P %-6s DXY %-6s золото %-6s BTC %-7s 10y %s",
                 з["ставка"], з["месяцев"], з["от"], з["до"],
                 з["spx"], з["dxy"], з["gold"], з["btc"], з["bonds"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
