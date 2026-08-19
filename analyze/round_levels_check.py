# -*- coding: utf-8 -*-
"""Мешают ли круглые уровни цели в 1.0 ATR? Разведочная проверка.

Механика, а не признак: вход на закрытии каждого бара, цель +1.0 ATR,
стоп -2.0 ATR, горизонт 12 баров H1 — та же геометрия, что у форварда.
Вопрос один: хуже ли исход, когда цель стоит чуть ВЫШЕ круглого уровня.
"""
import sys
sys.path.insert(0, '.')
import core.price_bars as _pb

ATR_MULT, RR, HORIZON = 2.0, 0.5, 12
PLANKA = 0.036

c = _pb.load_candles("XAUUSD", "1h")
print(f"баров: {len(c)}  с {__import__('datetime').datetime.fromtimestamp(c[0]['ts']):%Y-%m-%d}")

def atr_series(c, period=14):
    out = [None] * len(c)
    tr = [0.0] * len(c)
    for k in range(1, len(c)):
        tr[k] = max(c[k]["h"] - c[k]["l"], abs(c[k]["h"] - c[k-1]["c"]), abs(c[k]["l"] - c[k-1]["c"]))
    s = 0.0
    for k in range(1, len(c)):
        s += tr[k]
        if k >= period:
            s -= tr[k - period]
            out[k] = s / period
    return out

A = atr_series(c)

def simulate(entry, tp, sl, i):
    """Исход одной сделки. Оба барьера в одном баре -> считаем стоп (консервативно)."""
    for k in range(i + 1, min(i + 1 + HORIZON, len(c))):
        if c[k]["l"] <= sl:
            return sl - entry, "stop"
        if c[k]["h"] >= tp:
            return tp - entry, "target"
    k = min(i + HORIZON, len(c) - 1)
    return c[k]["c"] - entry, "horizon"

STEP = float(__import__("os").environ.get("STEP","50"))
NEAR = 0.25          # «чуть выше» = в пределах 0.25 ATR над уровнем

groups = {"над уровнем": [], "прочие": []}
variant = []         # EV варианта «цель чуть НИЖЕ уровня» на тех же сделках
for i in range(20, len(c) - HORIZON - 1):
    a = A[i]
    if not a:
        continue
    e = c[i]["c"]
    tp, sl = e + RR * ATR_MULT * a, e - ATR_MULT * a
    d = tp - (int(tp / STEP) * STEP)              # насколько цель выше круглого уровня
    over = 0 < d <= NEAR * a
    r, _ = simulate(e, tp, sl, i)
    groups["над уровнем" if over else "прочие"].append(r / a)
    if over:
        tp2 = (int(tp / STEP) * STEP) - 0.05 * a  # перенос цели под уровень
        r2, _ = simulate(e, tp2, sl, i)
        variant.append((r / a, r2 / a))

def stat(v, name):
    n = len(v)
    m = sum(v) / n
    sd = (sum((x - m) ** 2 for x in v) / (n - 1)) ** 0.5
    se = sd / n ** 0.5
    print(f"{name:24s} n={n:6d}  EV={m:+.4f} ATR  CI95 [{m-1.96*se:+.4f}, {m+1.96*se:+.4f}]  "
          f"выигрышных {sum(1 for x in v if x>0)/n:.1%}")
    return m, se

print(f"\n— цель относительно круглых уровней (шаг {STEP:.0f}, «чуть выше» = до {NEAR} ATR) —")
m1, se1 = stat(groups["над уровнем"], "цель над уровнем")
m2, se2 = stat(groups["прочие"], "прочие")
diff = m1 - m2
sed = (se1**2 + se2**2) ** 0.5
print(f"{'разница':24s}     {diff:+.4f} ATR  CI95 [{diff-1.96*sed:+.4f}, {diff+1.96*sed:+.4f}]"
      f"   {'значима' if abs(diff) > 1.96*sed else 'НЕ значима'}")

print("\n— перенос цели под уровень, на тех же сделках —")
a_ = [x for x, _ in variant]; b_ = [y for _, y in variant]
stat(a_, "как есть (над уровнем)")
stat(b_, "цель перенесена вниз")
d_ = [y - x for x, y in variant]
n = len(d_); md = sum(d_) / n
sdd = (sum((x - md) ** 2 for x in d_) / (n - 1)) ** 0.5
sed2 = sdd / n ** 0.5
print(f"{'выигрыш переноса':24s} n={n:6d}  {md:+.4f} ATR  CI95 [{md-1.96*sed2:+.4f}, {md+1.96*sed2:+.4f}]"
      f"   {'значим' if abs(md) > 1.96*sed2 else 'НЕ значим'}")
print(f"\nдля справки: планка издержек XAUUSD = {PLANKA} ATR")
