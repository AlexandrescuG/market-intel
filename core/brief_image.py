"""core/brief_image.py — картинка утреннего брифинга (SPEC_brief_outliers §4.2/§5).

ОДИН РЕНДЕРЕР НА ОБА ТРЕБОВАНИЯ. Владелец просил и картинку с котировками
(§4.2), и четыре графика (§5). Спека прямо требует делать их вместе: две
картиночные подсистемы разошлись бы по типографике. Поэтому здесь один холст:
сверху колонки котировок, ниже 2x2 свечных панели, внизу подпись.

ПОЧЕМУ НЕ СКРИНШОТ САЙТА. Playwright по chart.html дал бы максимальную
согласованность с сайтом, но у графика есть открытый дефект: при устаревшем
ряде applyLive() дорисовывает несуществующую свечу поверх мёртвых данных
(SPEC_chart_m1_m5_2026-08-18.md §1a). Скриншотить это — увековечивать
выдуманный бар в утренней рассылке. Плюс браузер в утреннем джобе — новая
поверхность отказа на машине, где Wine-стек и так хрупкий. Рисуем из
price_bars, теми же данными, что кормят сигналы.

ШТАМП СВЕЖЕСТИ — НЕ УКРАШЕНИЕ. Если последний бар старше двух периодов ТФ,
на панели пишется «данные от <дата>». Без этого картинка повторит то, что уже
случилось на сайте: 26 инструментов двенадцать дней рисовали август как
настоящее, и заметил это человек, а не система. В рассылке такое дороже — её
читают, не проверяя. Живой пример на 25.08: у USDRUB последний часовой бар от
14 июля, шесть недель назад.

Кириллица: DejaVu Sans (дефолт matplotlib) её покрывает, отдельный шрифт не
ставится.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")           # без дисплея: джоб идёт из systemd/cron
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

from core.price_bars import load_candles

log = logging.getLogger("brief_image")

BG = "#0f1218"
PANEL_BG = "#161b26"
UP = "#22c55e"
DOWN = "#ef4444"
TEXT = "#e6e9ef"
MUTED = "#8b93a7"
GRID = "#242b3a"

TF = "1h"
TF_SECONDS = 3600
BARS = 24                        # сутки по часам, §5.1
STALE_PERIODS = 2                # §5.3: старше двух периодов ТФ — штамп
PANELS = 4
QUOTES_ROWS = 5

_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня",
           "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def _fmt_date_ru(d: datetime) -> str:
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


def _fmt_pct(v) -> str:
    if v is None:
        return "—"
    s = f"{v:+.2f}%".replace(".", ",")
    return s.replace("-", "−", 1) if s.startswith("-") else s


def _fmt_price(v) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return f"{v:,.0f}".replace(",", " ")
    if abs(v) >= 100:
        return f"{v:.2f}".replace(".", ",")
    return f"{v:.4f}".rstrip("0").rstrip(".").replace(".", ",")


def day_window(candles: list[dict], now_ts: int) -> list[dict]:
    """Последние сутки по часам. Берём по времени, а не последние 24 строки:
    у мёртвого ряда «последние 24 бара» — это сутки шестинедельной давности,
    нарисованные как сегодня. Если в окне пусто — отдаём хвост ряда, но
    вызывающий код обязан поставить штамп (см. is_stale)."""
    cutoff = now_ts - BARS * TF_SECONDS
    window = [c for c in candles if c["ts"] >= cutoff]
    return window if window else candles[-BARS:]


def is_stale(candles: list[dict], now_ts: int) -> bool:
    return bool(candles) and (now_ts - candles[-1]["ts"]) > STALE_PERIODS * TF_SECONDS


def _draw_candles(ax, candles: list[dict], title: str, subtitle: str,
                  stale_note: str | None) -> None:
    ax.set_facecolor(PANEL_BG)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.6)
    ax.set_axisbelow(True)

    width = 0.62
    for i, c in enumerate(candles):
        colour = UP if c["c"] >= c["o"] else DOWN
        ax.vlines(i, c["l"], c["h"], color=colour, linewidth=1.0)
        low, high = min(c["o"], c["c"]), max(c["o"], c["c"])
        if high == low:                       # доджи: полоской, а не пустотой
            high = low + (max(x["h"] for x in candles) - min(x["l"] for x in candles)) * 0.002
        ax.add_patch(plt.Rectangle((i - width / 2, low), width, high - low,
                                   facecolor=colour, edgecolor=colour, linewidth=0.5))

    ax.set_xlim(-1, len(candles))
    ticks = [i for i in range(0, len(candles), max(1, len(candles) // 4))]
    ax.set_xticks(ticks)
    # 🔴 Формат подписи зависит от РЕАЛЬНОГО охвата окна, а не от замысла.
    # У мёртвого ряда (USDRUB, последний бар от 14 июля) фоллбэк отдаёт
    # последние 24 бара, растянутые на недели, и голые часы рисовали
    # «13:00, 12:00, 11:00, 11:00» — ось, врущая о времени, хуже отсутствующей.
    span = candles[-1]["ts"] - candles[0]["ts"]
    fmt = "%H:%M" if span <= (BARS + 2) * TF_SECONDS else "%d.%m %H:%M"
    ax.set_xticklabels(
        [datetime.fromtimestamp(candles[i]["ts"], timezone.utc).strftime(fmt) for i in ticks],
        fontsize=7 if fmt != "%H:%M" else 8)

    ax.set_title(title, color=TEXT, fontsize=11, loc="left", pad=14, fontweight="bold")
    ax.text(0, 1.015, subtitle, transform=ax.transAxes, color=MUTED, fontsize=9,
            va="bottom", ha="left")

    if stale_note:
        # Поверх поля, а не в подписи внизу: читающий рассылку не проверяет,
        # он смотрит. Штамп должен попасть в тот же взгляд, что и свечи.
        ax.text(0.5, 0.5, stale_note, transform=ax.transAxes, color="#f59e0b",
                fontsize=12, ha="center", va="center", alpha=0.92,
                bbox=dict(facecolor="#1c1408", edgecolor="#f59e0b", boxstyle="round,pad=0.5"))


def _draw_quotes(ax, numbers: list[dict]) -> None:
    """Колонки котировок (§4.2). В картинке выравнивание не зависит от ширины
    экрана — ровно та проблема, из-за которой <pre> разъезжался на телефоне."""
    ax.set_facecolor(BG)
    ax.axis("off")
    rows = numbers[:QUOTES_ROWS]
    if not rows:
        return
    # 🔴 Подпись обязательна. Здесь ДНЕВНОЕ закрытие вчера (блок «вчера вне
    # своей нормы»), а на панелях ниже — последний ЧАСОВОЙ бар за сутки. Это
    # разные числа по построению: у BTC на первом прогоне вышло 78 963 сверху
    # и 79 270 снизу. Без подписи читающий видит противоречие в одной
    # картинке и справедливо перестаёт верить обоим.
    ax.text(0.00, 1.06, "закрытие вчера", color=MUTED, fontsize=9,
            va="center", ha="left")
    y = 1.0
    step = 1.0 / max(len(rows), 1)
    for n in rows:
        chg = n.get("chg_pct")
        colour = UP if isinstance(chg, (int, float)) and chg >= 0 else DOWN
        ax.text(0.00, y - step * 0.62, n.get("name") or n.get("symbol") or "",
                color=TEXT, fontsize=13, va="center", ha="left")
        ax.text(0.52, y - step * 0.62, _fmt_pct(chg),
                color=colour, fontsize=13, va="center", ha="right", fontweight="bold")
        ax.text(0.80, y - step * 0.62, _fmt_price(n.get("close")),
                color=TEXT, fontsize=13, va="center", ha="right")
        note = (n.get("note") or "").strip()
        if note:
            ax.text(0.84, y - step * 0.62, note, color=MUTED, fontsize=10,
                    va="center", ha="left")
        y -= step


def pick_symbols(movers: dict, limit: int = PANELS) -> list[dict]:
    """§5.1: четыре инструмента из блока котировок — сперва те, что попали
    туда как аномалия, потом добор по модулю отклонения. Сортировка по ratio
    делает и то, и другое одним правилом."""
    rows = list(movers.get("up") or []) + list(movers.get("down") or [])
    rows = [r for r in rows if r.get("symbol")]
    rows.sort(key=lambda r: (r.get("ratio") or 0), reverse=True)
    seen, out = set(), []
    for r in rows:
        if r["symbol"] in seen:
            continue
        seen.add(r["symbol"])
        out.append(r)
        if len(out) >= limit:
            break
    return out


def render(numbers: list[dict], panels: list[dict], out_path: Path, *,
           date: str, now_ts: int | None = None, disclaimer: str = "") -> Path | None:
    """Возвращает путь или None, если рисовать оказалось нечего.

    Исключения НЕ гасит: вызывающий джоб оборачивает сам и решает, что делать
    (§5.4 — провал картинки не должен ронять текстовый брифинг, но и молча
    подсовывать пустой холст вместо графиков нельзя)."""
    now = int(now_ts or datetime.now(timezone.utc).timestamp())
    drawn = []
    for p in panels:
        candles = load_candles(p["symbol"], TF)
        if not candles:
            log.warning("картинка: у %s нет баров %s — панель пропущена", p["symbol"], TF)
            continue
        window = day_window(candles, now)
        if len(window) < 2:
            log.warning("картинка: у %s меньше двух баров в окне — панель пропущена", p["symbol"])
            continue
        drawn.append((p, window, is_stale(candles, now)))
    if not drawn and not numbers:
        return None

    # Сетка по факту, а не всегда 2x2: при двух панелях половина холста
    # уходила в пустоту, и картинка выглядела как недогрузившаяся.
    rows = (min(len(drawn), PANELS) + 1) // 2
    # Шапка занимает столько, сколько в ней строк: на тонком дне с одной
    # котировкой фиксированная высота оставляла полхолста пустыми.
    quotes_rows = min(len(numbers), QUOTES_ROWS)
    head_h = 0.30 + 0.17 * quotes_rows
    fig = plt.figure(figsize=(10.0, 1.4 + 2.5 * head_h + 3.4 * rows), dpi=110, facecolor=BG)
    gs = GridSpec(1 + rows, 2, figure=fig,
                  height_ratios=[head_h] + [1.6] * rows,
                  hspace=0.55, wspace=0.22,
                  left=0.07, right=0.965, top=0.90, bottom=0.075)

    d = datetime.strptime(date, "%Y-%m-%d")
    fig.text(0.07, 0.955, "SBF · утренние котировки", color=TEXT, fontsize=17,
             fontweight="bold", ha="left", va="center")
    fig.text(0.965, 0.955, _fmt_date_ru(d), color=MUTED, fontsize=12,
             ha="right", va="center")

    head = fig.add_subplot(gs[0, :])
    _draw_quotes(head, numbers)

    for i, (p, window, stale) in enumerate(drawn[:PANELS]):
        ax = fig.add_subplot(gs[1 + i // 2, i % 2])
        last = window[-1]["c"]
        # Изменение считаем ПО ПОКАЗАННОМУ ОКНУ (первое открытие -> последнее
        # закрытие), а не берём дневное из брифа: рядом с ним стоит цена
        # последнего часового бара, и пара «цена от одного окна, процент от
        # другого» — это число без источника, чего §7 не допускает.
        first_open = window[0]["o"]
        chg = ((last - first_open) / first_open * 100) if first_open else None
        title = f"{p.get('name') or p['symbol']} · {p['symbol']}"
        subtitle = f"{_fmt_price(last)}   {_fmt_pct(chg)} за сутки   ·   H1, 24 бара"
        note = None
        if stale:
            bar_date = datetime.fromtimestamp(window[-1]["ts"], timezone.utc)
            note = f"данные от {bar_date:%d.%m.%Y %H:%M} UTC"
        _draw_candles(ax, window, title, subtitle, note)

    stamp = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    foot = f"источник: брокерский фид (price_bars), снято {stamp}"
    if disclaimer:
        foot += f"   ·   {disclaimer}"
    fig.text(0.07, 0.022, foot, color=MUTED, fontsize=9, ha="left", va="center")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=BG, bbox_inches=None)
    plt.close(fig)
    return out_path
