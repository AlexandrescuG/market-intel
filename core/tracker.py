#!/usr/bin/env python3
"""
SBF Signal Tracker
------------------
Превращает отправленные сигналы в проверяемый трек-рекорд.

Идея:
  1. record_signal(...)        — фиксируем сигнал со статусом OPEN и ATR-барьерами.
  2. evaluate_open_signals(...) — позже смотрим вперёд по барам и размечаем исход
                                  методом triple-barrier (де Прадо):
                                      первым коснулся верхний барьер  -> WIN
                                      первым коснулся нижний барьер   -> LOSS
                                      ни один за горизонт             -> EXPIRED
                                  + пишем MFE/MAE (макс. ход в плюс/минус).
  3. get_stats(...)            — измеренный винрейт по срезам, только при выборке >= MIN_SAMPLE.

Зависимости: стандартный sqlite3 + numpy/pandas (уже есть в monitor.py).
Никаких внешних сервисов. Постгрес подключишь позже — схема такая же.
"""

import os, sqlite3, json
from datetime import datetime, timezone
import numpy as np
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "signal_outcomes.sqlite")
MIN_SAMPLE = 20          # ниже этого статистику не показываем — "недостаточно данных"
DEFAULT_HORIZON_BARS = 30  # сколько баров ждём разрешения (триггер EXPIRED)


# ─── ATR: ширина барьеров берём из волатильности, а не из фикс. процента ────
def atr(df: pd.DataFrame, period: int = 14) -> float:
    h, l, c = df["High"], df["Low"], df["Close"]
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    val = tr.rolling(period).mean().iloc[-1]
    return float(val) if np.isfinite(val) else float((h - l).tail(period).mean())


def barriers(entry: float, direction: str, atr_val: float,
             rr: float = 2.0, atr_mult: float = 1.5):
    """
    Стоп = atr_mult * ATR (не выбивается шумом).
    Цель = rr * стоп  (по умолчанию R:R = 2:1).
    Возвращает (upper, lower) абсолютные ценовые уровни.
    """
    stop = atr_mult * atr_val
    target = rr * stop
    if direction == "BULLISH":
        return entry + target, entry - stop      # upper=цель, lower=стоп
    else:
        return entry + stop, entry - target       # upper=стоп, lower=цель


# ─── Хранилище ──────────────────────────────────────────────────────────────
def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            signal_id   TEXT PRIMARY KEY,
            asset       TEXT, tf TEXT, pattern TEXT, direction TEXT,
            entry       REAL, upper REAL, lower REAL, atr REAL,
            sent_at     TEXT, last_bar TEXT,
            status      TEXT DEFAULT 'OPEN',     -- OPEN | WIN | LOSS | EXPIRED
            resolved_at TEXT, bars_to_resolve INTEGER,
            mfe REAL, mae REAL                    -- max favorable / adverse excursion, в R
        )
    """)
    return c


def record_signal(signal_id, asset, tf, pattern, direction, df, *,
                  rr=2.0, atr_mult=1.5):
    """Вызывать в момент отправки алерта. Барьеры считаются здесь же."""
    entry = float(df["Close"].iloc[-1])
    a = atr(df)
    upper, lower = barriers(entry, direction, a, rr=rr, atr_mult=atr_mult)
    with _conn() as c:
        c.execute("""INSERT OR IGNORE INTO signals
            (signal_id, asset, tf, pattern, direction, entry, upper, lower, atr,
             sent_at, last_bar, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?, 'OPEN')""",
            (signal_id, asset, tf, pattern, direction, entry, upper, lower, a,
             datetime.now(timezone.utc).isoformat(),
             str(df.index[-1])))
    return {"entry": entry, "upper": upper, "lower": lower, "atr": a}


def evaluate_open_signals(fetch_recent, horizon_bars=DEFAULT_HORIZON_BARS):
    """
    fetch_recent(asset, tf) -> DataFrame со свежими барами (включая бар входа и позже).
    Размечает все OPEN-сигналы, по которым появились новые бары.
    """
    with _conn() as c:
        rows = c.execute(
            "SELECT signal_id, asset, tf, direction, entry, upper, lower, atr, last_bar "
            "FROM signals WHERE status='OPEN'").fetchall()

        for sid, asset, tf, direction, entry, upper, lower, a, last_bar in rows:
            try:
                df = fetch_recent(asset, tf)
            except Exception:
                continue
            if df is None or df.empty:
                continue

            future = df[df.index > pd.Timestamp(last_bar)]
            if future.empty:
                continue

            status, bars, resolved_idx = "EXPIRED", len(future), None
            for i, (_, bar) in enumerate(future.iterrows(), start=1):
                hi, lo = float(bar["High"]), float(bar["Low"])
                hit_up = hi >= upper
                hit_dn = lo <= lower
                if hit_up or hit_dn:
                    # консервативно: если бар задел оба барьера — считаем стоп (худший случай)
                    if direction == "BULLISH":
                        status = "LOSS" if hit_dn and not hit_up else ("WIN" if hit_up else "LOSS")
                        if hit_up and hit_dn: status = "LOSS"
                    else:
                        status = "LOSS" if hit_up and not hit_dn else ("WIN" if hit_dn else "LOSS")
                        if hit_up and hit_dn: status = "LOSS"
                    bars, resolved_idx = i, i
                    break
                if i >= horizon_bars:
                    bars = horizon_bars
                    break

            # MFE/MAE в единицах R (риск = |entry - стоп-барьер|)
            risk = abs(entry - (lower if direction == "BULLISH" else upper))
            seg = future.iloc[:resolved_idx] if resolved_idx else future.iloc[:horizon_bars]
            if direction == "BULLISH":
                mfe = (seg["High"].max() - entry) / risk if len(seg) else 0.0
                mae = (entry - seg["Low"].min()) / risk if len(seg) else 0.0
            else:
                mfe = (entry - seg["Low"].min()) / risk if len(seg) else 0.0
                mae = (seg["High"].max() - entry) / risk if len(seg) else 0.0

            if status != "EXPIRED" or len(future) >= horizon_bars:
                c.execute("""UPDATE signals SET status=?, resolved_at=?,
                             bars_to_resolve=?, mfe=?, mae=? WHERE signal_id=?""",
                          (status, datetime.now(timezone.utc).isoformat(),
                           bars, float(mfe), float(mae), sid))


def get_stats(group_by=("pattern", "tf"), min_sample=MIN_SAMPLE):
    """Измеренный винрейт по срезам. Возвращает только статистически осмысленные группы."""
    cols = ", ".join(group_by)
    with _conn() as c:
        rows = c.execute(f"""
            SELECT {cols},
                   COUNT(*)                                              AS n,
                   SUM(status='WIN')                                     AS wins,
                   SUM(status='LOSS')                                    AS losses,
                   AVG(CASE WHEN status IN ('WIN','LOSS') THEN mfe END)  AS avg_mfe,
                   AVG(CASE WHEN status IN ('WIN','LOSS') THEN mae END)  AS avg_mae
            FROM signals
            WHERE status IN ('WIN','LOSS','EXPIRED')
            GROUP BY {cols}
        """).fetchall()

    out = []
    for r in rows:
        *keys, n, wins, losses, avg_mfe, avg_mae = r
        decided = (wins or 0) + (losses or 0)
        if decided < min_sample:
            continue
        out.append({
            "ключ": dict(zip(group_by, keys)),
            "выборка": decided,
            "винрейт": round(100 * wins / decided, 1),
            "сред_MFE_R": round(avg_mfe or 0, 2),
            "сред_MAE_R": round(avg_mae or 0, 2),
        })
    return sorted(out, key=lambda x: -x["выборка"])


def label_for_alert(pattern, tf, direction):
    """
    Текст для карточки ВМЕСТО фабрикованной 'Вероятность: 82%'.
    Если выборки нет — никаких процентов, только нейтральная формулировка.
    """
    for s in get_stats(group_by=("pattern", "tf")):
        if s["ключ"].get("pattern") == pattern and s["ключ"].get("tf") == tf:
            return (f"Историческое наблюдение по «{pattern}» {tf}: "
                    f"{s['винрейт']}% на выборке {s['выборка']} "
                    f"(средний ход +{s['сред_MFE_R']}R / −{s['сред_MAE_R']}R).")
    return "Статистический паттерн. Не является прогнозом или гарантией результата."


if __name__ == "__main__":
    # быстрый самотест на синтетике
    idx = pd.date_range("2026-06-01", periods=60, freq="4h")
    base = 100 + np.cumsum(np.random.randn(60))
    df = pd.DataFrame({"Open": base, "High": base + 1, "Low": base - 1, "Close": base}, index=idx)
    info = record_signal("TEST-1", "BTCUSD", "H4", "Double Bottom", "BULLISH", df.iloc[:40])
    print("recorded:", info)
    evaluate_open_signals(lambda a, t: df)   # отдаём те же 60 баров как "будущее"
    print("stats:", get_stats(min_sample=1))
    print("label:", label_for_alert("Double Bottom", "H4", "BULLISH"))
