"""Технический слой — то, что делает Trading Central, своими руками.

Считает из OHLCV (yfinance/биржа) ФАКТИЧЕСКИЕ величины:
  - floor-пивоты (PP, R1-R3, S1-S3) — как «Точка разворота» у TC
  - уровни поддержки/сопротивления из swing-точек
  - ATR и ожидаемый диапазон хода (аналог «19-49 PIPS»)
  - простые свечные/прайс-экшн паттерны (inside bar, engulfing, doji, pin)
  - состояние момента (RSI, MA20 vs MA50, momentum zero-cross)

ВАЖНО про рамку: модуль выдаёт ФАКТЫ и НАБЛЮДЕНИЯ («цена выше пивота, momentum
положительный»), а НЕ сигналы «ПОКУПАЙ/ПРОДАВАЙ с TP/SL». Публиковать сигналы
клиентам — регулируемая деятельность (TC это лицензированный провайдер). Этот
слой — внутренняя аналитика для брифа и образовательного контента.

Индикаторы реализованы вручную (без pandas-ta) — это десяток формул, так
надёжнее и без конфликтов версий numpy.
"""
from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger("technical")


# ─── базовые индикаторы ──────────────────────────────────────────────────────────
def _atr(df: pd.DataFrame, n: int = 14) -> float:
    h, l, c = df["High"], df["Low"], df["Close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return float(tr.rolling(n).mean().iloc[-1])


def _rsi(close: pd.Series, n: int = 14) -> float:
    d = close.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    rs = up / dn.replace(0, 1e-9)
    return float((100 - 100 / (1 + rs)).iloc[-1])


def pivots(prev_high: float, prev_low: float, prev_close: float) -> dict:
    pp = (prev_high + prev_low + prev_close) / 3
    rng = prev_high - prev_low
    return {
        "PP": pp,
        "R1": 2 * pp - prev_low, "S1": 2 * pp - prev_high,
        "R2": pp + rng, "S2": pp - rng,
        "R3": prev_high + 2 * (pp - prev_low), "S3": prev_low - 2 * (prev_high - pp),
    }


def swing_levels(df: pd.DataFrame, left: int = 3, right: int = 3, top: int = 3) -> dict:
    """Ближайшие уровни сопротивления (сверху) и поддержки (снизу) из фракталов."""
    highs, lows = df["High"].values, df["Low"].values
    price = float(df["Close"].iloc[-1])
    res, sup = [], []
    for i in range(left, len(df) - right):
        if highs[i] == max(highs[i - left:i + right + 1]) and highs[i] > price:
            res.append(round(float(highs[i]), 4))
        if lows[i] == min(lows[i - left:i + right + 1]) and lows[i] < price:
            sup.append(round(float(lows[i]), 4))
    res = sorted(set(res))[:top]                    # ближайшие сверху
    sup = sorted(set(sup), reverse=True)[:top]      # ближайшие снизу
    return {"resistance": res, "support": sup}


# ─── паттерны (простые и детерминированные — те, что реально надёжны) ─────────────
def patterns(df: pd.DataFrame) -> list[str]:
    o, h, l, c = (df[x] for x in ("Open", "High", "Low", "Close"))
    found = []
    O, H, L, C = o.iloc[-1], h.iloc[-1], l.iloc[-1], c.iloc[-1]
    pO, pH, pL, pC = o.iloc[-2], h.iloc[-2], l.iloc[-2], c.iloc[-2]
    rng = max(H - L, 1e-9)
    body = abs(C - O)
    if H < pH and L > pL:
        found.append(f"Inside Bar ({'бычий' if C > O else 'медвежий'})")
    if L < pL and H > pH:
        found.append("Outside Bar")
    if C > O and pC < pO and C >= pO and O <= pC:
        found.append("Bullish Engulfing")
    if C < O and pC > pO and C <= pO and O >= pC:
        found.append("Bearish Engulfing")
    if body <= 0.1 * rng:
        found.append("Doji")
    lower_wick = min(O, C) - L
    upper_wick = H - max(O, C)
    if lower_wick > 2 * body and upper_wick < body:
        found.append("Hammer / Pin (бычий)")
    if upper_wick > 2 * body and lower_wick < body:
        found.append("Shooting Star (медвежий)")
    return found


# ─── pip-конвертация для FX ───────────────────────────────────────────────────────
def _pip_size(ticker: str) -> float | None:
    t = ticker.upper()
    if "=X" in t or len(t.replace("=X", "")) == 6:  # FX пара
        return 0.01 if "JPY" in t else 0.0001
    return None  # крипта/индексы/металлы — считаем в пунктах


def analyze(ticker: str, interval: str = "60m", period: str = "10d") -> dict | None:
    """Полная TC-подобная карточка по инструменту. Возвращает структуру фактов."""
    import yfinance as yf
    try:
        df = yf.Ticker(ticker).history(period=period, interval=interval)
    except Exception as e:
        log.debug("analyze %s: %s", ticker, e)
        return None
    if df is None or len(df) < 30:
        return None

    price = float(df["Close"].iloc[-1])
    # пивоты по предыдущему ДНЮ
    daily = yf.Ticker(ticker).history(period="5d", interval="1d")
    if len(daily) >= 2:
        pv = pivots(float(daily["High"].iloc[-2]), float(daily["Low"].iloc[-2]),
                    float(daily["Close"].iloc[-2]))
    else:
        pv = pivots(float(df["High"].max()), float(df["Low"].min()), price)

    atr = _atr(df)
    rsi = _rsi(df["Close"])
    ma20 = float(df["Close"].rolling(20).mean().iloc[-1])
    ma50 = float(df["Close"].rolling(50).mean().iloc[-1]) if len(df) >= 50 else ma20
    mom = price - float(df["Close"].iloc[-11]) if len(df) > 11 else 0.0
    sr = swing_levels(df)
    pats = patterns(df)

    pip = _pip_size(ticker)
    if pip:
        exp = (round(0.6 * atr / pip), round(1.2 * atr / pip))
        exp_unit = "pips"
    else:
        exp = (round(0.6 * atr, 2), round(1.2 * atr, 2))
        exp_unit = "пунктов"

    # НАБЛЮДЕНИЕ (не сигнал): сводим картину
    bull = sum([price > pv["PP"], ma20 > ma50, mom > 0, rsi > 50])
    if bull >= 3:
        bias = "техническая картина бычья"
    elif bull <= 1:
        bias = "техническая картина медвежья"
    else:
        bias = "смешанная / нейтральная"

    return {
        "ticker": ticker, "interval": interval, "price": round(price, 4),
        "pivots": {k: round(v, 4) for k, v in pv.items()},
        "support": sr["support"], "resistance": sr["resistance"],
        "atr": round(atr, 4), "expected_move": exp, "expected_unit": exp_unit,
        "rsi": round(rsi, 1), "ma20": round(ma20, 4), "ma50": round(ma50, 4),
        "momentum": round(mom, 4), "patterns": pats, "bias": bias,
    }


def card(a: dict) -> str:
    """Markdown-карточка в стиле TC (но с честной рамкой «наблюдение»)."""
    if not a:
        return "_(нет данных)_"
    p = a["pivots"]
    res = " · ".join(str(x) for x in a["resistance"]) or "—"
    sup = " · ".join(str(x) for x in a["support"]) or "—"
    pats = ", ".join(a["patterns"]) or "нет выраженных"
    return (
        f"**{a['ticker']}** ({a['interval']}) · {a['price']}\n"
        f"  Точка разворота (PP): {p['PP']}\n"
        f"  Сопротивление: R1 {p['R1']} · R2 {p['R2']} | swing: {res}\n"
        f"  Поддержка:    S1 {p['S1']} · S2 {p['S2']} | swing: {sup}\n"
        f"  Ожидаемый ход (ATR): {a['expected_move'][0]}–{a['expected_move'][1]} {a['expected_unit']}\n"
        f"  RSI {a['rsi']} · MA20 {a['ma20']} {'>' if a['ma20'] > a['ma50'] else '<'} MA50 {a['ma50']} · "
        f"momentum {'+' if a['momentum'] > 0 else ''}{a['momentum']}\n"
        f"  Паттерны: {pats}\n"
        f"  Наблюдение: {a['bias']} (не инвестрекомендация)"
    )


def scan(tickers: list[str], interval: str = "60m") -> list[dict]:
    return [a for a in (analyze(t, interval) for t in tickers) if a]


if __name__ == "__main__":
    from core.logging_setup import setup
    setup("technical")
    for t in ["BTC-USD", "EURUSD=X", "USDCAD=X", "^GSPC"]:
        a = analyze(t)
        print(card(a) if a else f"{t}: нет данных")
        print()
