"""WP4 — Режим рынка. Детерминированная классификация текущего состояния.

Сигналы: VIX, DXY тренд, 10y-2y спред, breadth DASHBOARD-инструментов.
Без LLM — только числа.
"""
from __future__ import annotations

from datetime import datetime, timezone


def detect_regime() -> dict:
    """Вернуть текущий режим рынка.

    Returns:
        {risk, inflation, dollar, vol, yield_curve, label, updated}
    """
    import yfinance as yf
    import pandas as pd

    def _last_close(ticker: str, period: str = "5d") -> float | None:
        try:
            df = yf.download(ticker, period=period, progress=False, auto_adjust=True)
            if df.empty:
                return None
            close = df["Close"]
            if hasattr(close, "iloc"):
                return float(close.iloc[-1])
            return float(close)
        except Exception:
            return None

    def _trend(ticker: str, short: int = 5, long: int = 20) -> str:
        """up | down | flat на основе SMA."""
        try:
            df = yf.download(ticker, period="30d", progress=False, auto_adjust=True)
            close = df["Close"].dropna()
            if len(close) < long:
                return "flat"
            sma_short = float(close.iloc[-short:].mean())
            sma_long = float(close.iloc[-long:].mean())
            if sma_short > sma_long * 1.005:
                return "up"
            if sma_short < sma_long * 0.995:
                return "down"
            return "flat"
        except Exception:
            return "flat"

    # VIX
    vix = _last_close("^VIX")
    if vix is None:
        vol = "unknown"
    elif vix > 25:
        vol = "high"
    elif vix < 15:
        vol = "low"
    else:
        vol = "moderate"

    # DXY тренд
    dxy_trend = _trend("DX-Y.NYB")
    dollar = "strong" if dxy_trend == "up" else ("weak" if dxy_trend == "down" else "neutral")

    # Risk: если VIX высокий → risk-off; DXY растёт + VIX высокий → сильный risk-off
    if vix is not None and vix > 25:
        risk = "off"
    elif vix is not None and vix < 15 and dxy_trend != "up":
        risk = "on"
    else:
        risk = "mixed"

    # Кривая доходности: 10y-2y через yfinance (ближайший прокси)
    t10 = _last_close("^TNX")   # 10-летняя US treasury
    t2  = _last_close("^IRX")   # 3-мес (прокси для краткосрочных)
    if t10 is not None and t2 is not None:
        spread = t10 - t2 / 10  # IRX в процентах × 10
        if spread > 0.5:
            yield_curve = "steepening"
        elif spread < -0.1:
            yield_curve = "inverted"
        else:
            yield_curve = "flattening"
    else:
        yield_curve = "unknown"

    # Breadth: доля DASHBOARD-инструментов в плюсе сегодня
    from core.market import snapshot, DASHBOARD
    snap = snapshot(DASHBOARD)
    changes = [v.get("change_pct", 0) for v in snap.values() if v.get("change_pct") is not None]
    positive = sum(1 for c in changes if c > 0)
    breadth = round(positive / len(changes), 2) if changes else 0.5

    # Инфляционный режим — из FRED если есть, иначе неизвестно
    inflation = "unknown"
    try:
        from core.fred import series
        cpi = series("CPIAUCSL", n=3)
        if len(cpi) >= 2:
            delta = cpi[-1]["value"] - cpi[-2]["value"]
            inflation = "up" if delta > 0.1 else ("down" if delta < -0.1 else "flat")
    except Exception:
        pass

    # Human-readable label
    parts = []
    if risk == "off":
        parts.append("Risk-OFF")
    elif risk == "on":
        parts.append("Risk-ON")
    else:
        parts.append("Mixed")
    if vol == "high":
        parts.append("High Volatility")
    if yield_curve == "inverted":
        parts.append("Inverted Curve")
    if dollar == "strong":
        parts.append("Strong USD")
    label = " · ".join(parts) or "Neutral"

    return {
        "risk": risk,
        "inflation": inflation,
        "dollar": dollar,
        "vol": vol,
        "breadth": breadth,
        "yield_curve": yield_curve,
        "vix": vix,
        "label": label,
        "updated": datetime.now(timezone.utc).isoformat(),
    }
