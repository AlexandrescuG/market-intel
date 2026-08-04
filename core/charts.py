"""Генерация candlestick-графиков с уровнями поддержки/сопротивления.

Выдаёт PNG в web/charts/{safe_ticker}.png.
Паттерны (Double Top, H&S и т.д.) намеренно исключены — только ценовые уровни.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker

log = logging.getLogger("charts")

SBF_BG   = "#FDFCF8"
SBF_GOLD = "#C5A059"
SBF_DARK = "#1A1818"
SBF_BULL = "#4A7C59"
SBF_BEAR = "#8B3A3A"
SBF_GRID = "#EBE8E0"
SBF_PP   = "#C5A059"   # pivot — золотой
SBF_RES  = "#C0392B"   # сопротивление — красный
SBF_SUP  = "#27AE60"   # поддержка — зелёный


def _safe_name(ticker: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9]", "", ticker)


def _price_fmt(price: float) -> str:
    if price >= 1000:
        return f"{price:,.0f}"
    if price >= 10:
        return f"{price:.2f}"
    return f"{price:.4f}"


def generate_chart(
    ticker: str,
    display_name: str,
    out_dir: Path,
    days: int = 60,
) -> Path | None:
    """Строит candlestick + уровни S/R. Возвращает путь к PNG или None при ошибке."""
    try:
        import yfinance as yf
        from core.technical import pivots, swing_levels, _atr
    except ImportError as e:
        log.error("charts import: %s", e)
        return None

    try:
        df = yf.Ticker(ticker).history(period=f"{days + 10}d", interval="1d")
        if df is None or len(df) < 20:
            return None
        df = df.dropna(subset=["Close", "Open", "High", "Low"])
        df = df.tail(days)

        price = float(df["Close"].iloc[-1])

        # Pivot по предыдущей свече
        pv = None
        if len(df) >= 2:
            pv = pivots(
                float(df["High"].iloc[-2]),
                float(df["Low"].iloc[-2]),
                float(df["Close"].iloc[-2]),
            )
            pv = {k: round(v, 4) for k, v in pv.items()}

        sr = swing_levels(df, left=4, right=4, top=3)

        # ── Рисуем ─────────────────────────────────────────────────────
        fig, (ax_price, ax_vol) = plt.subplots(
            2, 1, figsize=(12, 6),
            gridspec_kw={"height_ratios": [4, 1]},
            facecolor=SBF_BG,
        )
        ax_price.set_facecolor(SBF_BG)
        ax_vol.set_facecolor(SBF_BG)

        # Свечи
        for idx, (_, row) in enumerate(df.iterrows()):
            o, h, l, c = row["Open"], row["High"], row["Low"], row["Close"]
            color = SBF_BULL if c >= o else SBF_BEAR
            ax_price.plot([idx, idx], [l, h], color=color, lw=0.8)
            rect = plt.Rectangle(
                (idx - 0.35, min(o, c)), 0.7, abs(c - o),
                color=color, zorder=2,
            )
            ax_price.add_patch(rect)

        # Горизонтальные уровни
        x_max = len(df) - 1

        def hline(ax, y, color, ls, lw, label=None):
            ax.axhline(y=y, color=color, linestyle=ls, linewidth=lw, alpha=0.85)
            if label:
                ax.text(x_max + 0.3, y, label, color=color, fontsize=7.5,
                        va="center", fontweight="bold")

        if pv:
            hline(ax_price, pv["PP"], SBF_PP, "--", 1.2, f"PP {_price_fmt(pv['PP'])}")
            hline(ax_price, pv["R1"], SBF_RES, "-.", 0.9, f"R1 {_price_fmt(pv['R1'])}")
            hline(ax_price, pv["R2"], SBF_RES, ":", 0.8, f"R2 {_price_fmt(pv['R2'])}")
            hline(ax_price, pv["S1"], SBF_SUP, "-.", 0.9, f"S1 {_price_fmt(pv['S1'])}")
            hline(ax_price, pv["S2"], SBF_SUP, ":", 0.8, f"S2 {_price_fmt(pv['S2'])}")

        for r in sr["resistance"]:
            hline(ax_price, r, SBF_RES, "--", 0.7)
        for s in sr["support"]:
            hline(ax_price, s, SBF_SUP, "--", 0.7)

        # Текущая цена (пунктир серый)
        ax_price.axhline(y=price, color="#888", linestyle=":", linewidth=0.8)

        # Объём
        for idx, (_, row) in enumerate(df.iterrows()):
            color = SBF_BULL if row["Close"] >= row["Open"] else SBF_BEAR
            ax_vol.bar(idx, row.get("Volume", 0), color=color, alpha=0.6, width=0.8)

        # Подписи X — даты каждые ~10 баров
        dates = df.index.strftime("%d.%m").tolist()
        step = max(len(dates) // 8, 1)
        xticks = list(range(0, len(dates), step))
        ax_price.set_xticks([])
        ax_vol.set_xticks(xticks)
        ax_vol.set_xticklabels([dates[i] for i in xticks], fontsize=7, color=SBF_DARK)

        # Сетка и оформление
        for ax in (ax_price, ax_vol):
            ax.grid(True, color=SBF_GRID, linewidth=0.5)
            ax.tick_params(colors=SBF_DARK, labelsize=8)
            for spine in ax.spines.values():
                spine.set_edgecolor(SBF_GRID)

        ax_price.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda v, _: _price_fmt(v))
        )
        ax_vol.set_ylabel("Объём", fontsize=7, color=SBF_DARK)

        # Легенда
        legend_handles = [
            mpatches.Patch(color=SBF_PP,  label="Точка разворота (PP)"),
            mpatches.Patch(color=SBF_RES, label="Сопротивление"),
            mpatches.Patch(color=SBF_SUP, label="Поддержка"),
        ]
        ax_price.legend(handles=legend_handles, loc="upper left",
                        fontsize=7.5, framealpha=0.85, facecolor=SBF_BG)

        fig.suptitle(f"{display_name} — Уровни поддержки и сопротивления (D1)",
                     fontsize=11, color=SBF_DARK, y=0.98, fontweight="bold")
        plt.tight_layout(rect=[0, 0, 0.93, 0.96])

        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{_safe_name(ticker)}.png"
        fig.savefig(str(out_path), dpi=130, bbox_inches="tight",
                    facecolor=SBF_BG)
        plt.close(fig)
        return out_path

    except Exception as e:
        log.error("generate_chart %s: %s", ticker, e)
        return None
