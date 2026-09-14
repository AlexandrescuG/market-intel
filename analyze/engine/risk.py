#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/engine/risk.py — размер позиции и все запреты движка.

Вынесено отдельным модулем с отдельными тестами по той же причине, что и
`mt5_safety.py`: это единственное, что стоит между источником сигналов и
реальным ордером, и проверить можно только то, что отделено от кода отправки.

Разделение обязанностей с `mt5_safety.py`: там предохранители СЧЁТА (демо,
AutoTrading, чужой magic), здесь — предохранители ПОРТФЕЛЯ (сколько рискуем,
сколько одновременно, когда останавливаемся). Оба применяются, ни один не
заменяет другой.
"""
from __future__ import annotations

import sqlite3

from analyze.engine.contracts import LONG, Signal, ST_HALTED

# ─── параметры риска ────────────────────────────────────────────────────────
# 🔴 Это НЕ калиброванные числа, а осознанные консервативные значения на
# старт. Калибровать их можно будет только по журналу движка, которого пока
# нет; до тех пор любое «оптимальное» значение было бы придумано.

# 🔴 0.5%, а не «поменьше для осторожности» — число упирается в минимальный
# лот брокера, замерено на живом терминале 27.08 при equity ~10 000:
#   GOLD   ATR1h=15.66, стоп 1.5 ATR при vmin=0.01 -> 23.49 USD
#   USDZAR                                          ->  1.85 USD
#   EURUSD                                          ->  0.75 USD
#   USDCNY                                          ->  0.26 USD
# То есть на золоте нижний предел риска задан брокером и равен ~23.5 USD.
# При 0.25% (25 USD) любая сделка по золоту отказывалась бы, стоило ATR
# подрасти на процент — движок молча перестал бы торговать главный
# инструмент, и это выглядело бы как «сигналов нет». 0.5% даёт двукратный
# зазор. Обратная сторона: по FX объём вырастет с привычных 0.01 до
# десятых лота — это и есть паритет риска, а не ошибка.
RISK_PER_TRADE = 0.005       # 0.5% капитала на сделку

# Два потолка вместо одного — 14.09, вместе с переходом на нетто.
#
# НЕТТО — направленный риск: по каждому инструменту лонги и шорты
# складываются со знаком и гасят друг друга. Это то, чем мы рискуем при
# одном движении рынка, и это основной потолок.
#
# ВАЛОВОЙ — сумма по модулю, без учёта знака. Нужен ровно против одного
# сценария, и его стоит назвать прямо, потому что нетто его НЕ ловит:
# лонг со стопом снизу и шорт со стопом сверху при одном движении гасят
# друг друга, но при ПИЛЕ — цена сходила вверх и выбила стоп шорта, потом
# вернулась вниз и выбила стоп лонга — теряются оба, и худший случай равен
# СУММЕ, а не разности. Нетто в этот момент показывал бы ноль.
#
# Поэтому нетто разрешает хеджу не съедать лимит, а валовой не даёт
# набрать бесконечно много встречных пар.
MAX_PORTFOLIO_RISK = 0.03    # нетто: 3% капитала -> ~6 однонаправленных позиций
MAX_GROSS_RISK = 0.05        # валовой: 5%, потолок на случай пилы
MAX_OPEN_TOTAL = 12
MAX_OPEN_PER_SYMBOL = 3      # было «10 по золоту разом» — главный урок 26-27.08
MAX_OPEN_PER_SYMBOL_SIDE = 2 # и не более двух в одну сторону по одному символу
MAX_OPEN_PER_STRATEGY = 4

# Стоп-кран: просадка ОТ ПИКА кривой стратегии, в R.
# 🔴 Именно от пика, а не «накопленная сумма ниже -15», как было в
# 2026-08-19_forward_stopping.md §3. Старая формулировка ослабевала по мере
# того, как стратегия зарабатывала: при пике +32 ATR она разрешала потерять
# ещё 23 ATR прежде чем сработать. Просадка от пика такого свойства не имеет.
#
# 🔴 07.09: ПОРОГ ПЕРЕСЧИТАН ИЗ РАСПРЕДЕЛЕНИЯ. Значение 8.0 было выбрано
# 28.08 «осознанно консервативным» — и оказалось сломанным. Бутстрап по
# 154 894 историческим исходам (ops/calibrate_drawdown.py), окно 50 сделок:
#
#     правила               медиана    p95     p99
#     без сопровождения      -11.0   -21.1   -25.9
#     безубыток+трейлинг      -7.9   -16.1   -20.4
#
# Восьмёрка лежала ВНУТРИ медианы: кран остановил бы стратегию в
# большинстве нормальных полос, ни разу не поймав поломки. Смысл крана —
# отличить «перестала работать» от «работает как всегда, сейчас полоса»,
# поэтому порог — p99 нормальной просадки: ложное срабатывание в ~1% полос.
# Берём 20 R под включённое сопровождение; окно 50 сделок — примерно
# столько проходит между ревизиями.
MAX_DRAWDOWN_R = 20.0
MIN_TRADES_BEFORE_HALT = 10  # чтобы серия из трёх стопов на старте не глушила

# Минимальное расстояние стопа в ATR — защита от «стоп в один тик», который
# гарантированно выбьет шумом и превратит риск-модель в фикцию.
MIN_STOP_ATR = 0.5
MAX_STOP_ATR = 5.0

# Допустимый снос цены от бара-основания, в единицах риска.
# 🔴 Поймано на живой сделке live_strategy 19.08 16:02: сигнальный бар
# закрылся на 4365.95, за час золото ушло до 4442, и вход по рынку оказался
# ВЫШЕ цели, посчитанной от бара. Ордер с целью ниже входа брокер отвергает.
MAX_ENTRY_DRIFT_R = 0.5


class RiskRefusal(RuntimeError):
    """Отказ риск-модуля. Как и SafetyRefusal, несёт машинный статус —
    молчаливый пропуск запрещён, причина обязана попасть в журнал."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


# ─── размер позиции ─────────────────────────────────────────────────────────

def money_per_price_unit(symbol_info) -> float:
    """Сколько денег даёт движение цены на 1.0 при объёме 1 лот.

    Транспорт может передать готовый `SymbolInfo` (см. engine/market.py) —
    тогда значение уже посчитано там, где известны особенности площадки.
    Это предпочтительный путь: у MT5 цену пункта даёт сам терминал, у
    cTrader её надо выводить из lotSize с разной формулой для прямых и
    обратных пар, и сводить обе арифметики сюда значило бы завести развилку
    ровно там, где ошибка тише всего — неверная цена пункта не падает, она
    просто делает размер позиции не тем.

    Ветка ниже оставлена для сырого MT5-объекта: движок ещё ходит обоими
    путями, пока идёт параллельная работа двух площадок."""
    ready = getattr(symbol_info, "money_per_unit", None)
    if ready:
        return float(ready)
    tv = getattr(symbol_info, "trade_tick_value", None)
    ts = getattr(symbol_info, "trade_tick_size", None)
    if not tv or not ts or ts <= 0:
        # запасной путь — размер контракта; для FX-мажоров совпадает
        cs = getattr(symbol_info, "trade_contract_size", None)
        if not cs or cs <= 0:
            raise RiskRefusal("bad_symbol",
                              "не удалось определить цену пункта: нет tick_value/contract_size")
        return float(cs)
    return float(tv) / float(ts)


def _round_volume(volume: float, symbol_info) -> float:
    step = float(getattr(symbol_info, "volume_step", 0.01) or 0.01)
    vmin = float(getattr(symbol_info, "volume_min", step) or step)
    vmax = float(getattr(symbol_info, "volume_max", 100.0) or 100.0)
    v = round(volume / step) * step
    v = round(v, 8)
    if v < vmin:
        return 0.0          # честнее отказать, чем округлить риск вверх
    return min(v, vmax)


def position_volume(signal: Signal, equity: float, symbol_info) -> tuple[float, float]:
    """Объём под фиксированную долю капитала. Возвращает (volume, risk_money).

    🔴 Заменяет фиксированный `volume_min` старого контура. Там стоп в 2 ATR
    при расширении волатильности подорожал с -31 до -45 USD за сделку — риск
    рос сам собой, никем не ограниченный. Здесь наоборот: чем шире стоп, тем
    меньше объём, и цена ошибки остаётся постоянной долей счёта.

    Отказ вместо округления вверх: если минимальный лот брокера уже дороже
    разрешённого риска, сделку не берём. Это ограничивает движок на мелком
    счёте — и правильно, что ограничивает."""
    dist = signal.stop_distance
    if dist <= 0:
        raise RiskRefusal("bad_geometry", "нулевое расстояние до стопа")
    per_unit = money_per_price_unit(symbol_info)
    risk_money = equity * RISK_PER_TRADE
    raw = risk_money / (dist * per_unit)
    vol = _round_volume(raw, symbol_info)
    if vol <= 0:
        vmin = float(getattr(symbol_info, "volume_min", 0.01) or 0.01)
        need = dist * per_unit * vmin
        raise RiskRefusal(
            "risk_too_small",
            f"минимальный лот {vmin} стоит {need:.2f} при разрешённом риске "
            f"{risk_money:.2f} — сделка не берётся")
    return vol, vol * dist * per_unit


# ─── проверки сигнала ───────────────────────────────────────────────────────

def geometry_gate(signal: Signal) -> None:
    bad = signal.validate()
    if bad:
        raise RiskRefusal("bad_geometry", bad)
    in_atr = signal.stop_distance / signal.atr
    if in_atr < MIN_STOP_ATR:
        raise RiskRefusal("stop_too_tight",
                          f"стоп {in_atr:.2f} ATR теснее предела {MIN_STOP_ATR}")
    if in_atr > MAX_STOP_ATR:
        raise RiskRefusal("stop_too_wide",
                          f"стоп {in_atr:.2f} ATR шире предела {MAX_STOP_ATR}")


def drift_gate(signal: Signal, market_price: float) -> None:
    """Не входить, если рынок ушёл от основания дальше, чем на долю риска."""
    drift = abs(market_price - signal.ref_price) / signal.stop_distance
    if drift > MAX_ENTRY_DRIFT_R:
        raise RiskRefusal(
            "drift_reject",
            f"цена ушла от бара-основания на {drift:.2f}R при пределе {MAX_ENTRY_DRIFT_R}")


# Какую долю награды разрешено отдать спреду.
# 🔴 Замерено 31.08 на живых котировках — спред как доля цели (1.5 ATR × RR 2):
#   XAUUSD  0.6%    USDJPY  3.0%    EURUSD  3.0%
#   GBPUSD  4.0%    USDZAR 11.4%    USDCNY 35.2%
# У USDCNY спред равен 105.7% ATR: он один съедает треть награды, и никакое
# улучшение сигнала этого не отыграет — инструмент не торгуем при такой
# геометрии, а не «торгуем осторожно». Порог 10% выбран так, чтобы отсечь
# USDCNY и USDZAR и оставить остальных с запасом.
MAX_SPREAD_SHARE_OF_TARGET = 0.10

# 🔴 07.09: второй порог — доля спреда от РИСКА, не от награды. Первый порог
# делил спред на цель (3 ATR) и потому пропускал USDZAR: 0.010 / 0.088 = 11%,
# на грани. Но риск там 1.5 ATR = 0.044, и спред от риска — 23%: каждая
# сделка стартует почти с четверти пути к стопу. Результат за неделю живьём:
# USDZAR 1 выигрыш из 8, -5.87 R, -326 USD — худший инструмент счёта.
# Награда — то, чего может не случиться; риск — то, что платится всегда.
# Поэтому порог от риска жёстче.
MAX_SPREAD_SHARE_OF_RISK = 0.12


def cost_gate(signal: Signal, tick) -> None:
    """Спред не должен съедать заметную долю ни награды, ни риска.

    Считается на КАЖДОМ сигнале по живому спреду, а не по списку
    инструментов: спред расширяется ночью и на новостях, и инструмент,
    торгуемый днём, может стать нерентабельным в 3 часа ночи. Статический
    чёрный список этого не поймает."""
    if tick is None:
        return
    spread = abs(float(tick.ask) - float(tick.bid))
    reward = abs(signal.target - signal.ref_price)
    risk = signal.stop_distance
    if reward <= 0 or risk <= 0:
        return
    share_reward = spread / reward
    if share_reward > MAX_SPREAD_SHARE_OF_TARGET:
        raise RiskRefusal(
            "spread_too_wide",
            f"спред {spread:.5f} съедает {share_reward * 100:.1f}% награды при пределе "
            f"{MAX_SPREAD_SHARE_OF_TARGET * 100:.0f}%")
    share_risk = spread / risk
    if share_risk > MAX_SPREAD_SHARE_OF_RISK:
        raise RiskRefusal(
            "spread_too_wide",
            f"спред {spread:.5f} — это {share_risk * 100:.1f}% риска при пределе "
            f"{MAX_SPREAD_SHARE_OF_RISK * 100:.0f}%: сделка стартует с пути к стопу")


def broker_barrier_gate(signal: Signal, symbol_info, tick) -> None:
    """Барьеры должны быть дальше минимума, который требует брокер.

    🔴 Замерено на первом же боевом прогоне 28.08: из 9 принятых сигналов 4
    отбились с `order_check retcode=10016 Invalid stops` — все по USDCNY и
    USDZAR. У брокера `trade_stops_level` в пунктах, и он очень разный:

        GOLD    50 п -> 0.5      EURUSD    1 п -> 0.00001
        USDJPY  20 п -> 0.02     USDCNY   30 п -> 0.003
        USDZAR 120 п -> 0.012    (при спреде ещё 100 п = 0.01)

    Отправлять заведомо отвергаемый ордер плохо не тем, что он не пройдёт, а
    тем, что отказ выглядит как отказ БРОКЕРА, а не как наша негодная
    геометрия. В журнале копились бы `order_rejected` без внятной причины —
    ровно то, от чего уводил комментарий в live_strategy про снос цены.

    Спред добавляется к минимуму осознанно: стоп, стоящий внутри спреда,
    выбьет мгновенно и не по движению рынка."""
    # `stops_level` у MT5 в пунктах, у нашего SymbolInfo — сразу в цене:
    # транспорт приводит к общему виду, чтобы здесь не было развилки.
    ready = getattr(symbol_info, "stops_level", None)
    if ready is not None:
        need_barrier = float(ready)
    else:
        point = float(getattr(symbol_info, "point", 0.0) or 0.0)
        if point <= 0:
            return
        need_barrier = float(getattr(symbol_info, "trade_stops_level", 0) or 0) * point
    spread = 0.0
    if tick is not None:
        spread = abs(float(tick.ask) - float(tick.bid))
    need = need_barrier + spread
    if need <= 0:
        return
    have = signal.stop_distance
    if have < need:
        raise RiskRefusal(
            "barrier_too_close",
            f"стоп {have:.5f} ближе минимума брокера {need:.5f} "
            f"(минимум брокера {need_barrier:.5f} + спред {spread:.5f})")
    tgt = abs(signal.target - signal.ref_price)
    if tgt < need:
        raise RiskRefusal(
            "barrier_too_close",
            f"цель {tgt:.5f} ближе минимума брокера {need:.5f}")


# Доля свободной маржи, которую разрешено занять одной позицией.
# 🔴 Не абстрактная осторожность: на первом боевом прогоне риск-сайзинг дал
# 1.93 лота по USDCNY (пара тихая, поэтому под тот же риск в деньгах
# получается крупный номинал), и order_check показал margin=4283 при
# свободных 9944 — одна сделка забрала бы 43% маржи. Риск в деньгах и
# нагрузка на маржу — разные вещи, ограничивать надо обе.
MAX_MARGIN_SHARE = 0.15


def margin_gate(mt5, broker_sym: str, volume: float, is_buy: bool, price: float,
                free_margin: float) -> None:
    """Занимаемая маржа не больше доли свободной. Считает сам терминал —
    формула зависит от типа инструмента и плеча, и повторять её у себя
    значит однажды разойтись с брокером."""
    try:
        need = mt5.order_calc_margin(
            mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
            broker_sym, volume, price)
    except Exception as e:                                   # noqa: BLE001
        raise RiskRefusal("margin_unknown", f"order_calc_margin упал: {e}") from e
    if need is None:
        raise RiskRefusal("margin_unknown", "order_calc_margin вернул None")
    if free_margin > 0 and float(need) > free_margin * MAX_MARGIN_SHARE:
        raise RiskRefusal(
            "margin_too_big",
            f"нужно маржи {float(need):.2f} при свободных {free_margin:.2f} — "
            f"это больше предела {MAX_MARGIN_SHARE * 100:.0f}%")


def live_risk(direction: str, entry: float | None, stop: float | None,
              risk_per_price: float | None, risk_money: float | None) -> float:
    """Сколько позиция может ещё потерять ПРЯМО СЕЙЧАС, а не сколько могла на входе.

    🔴 14.09. `risk_money` пишется при открытии и больше не меняется, а
    `manage_open` переносит стопы — в безубыток и дальше в прибыль. Позиция с
    выкупленным стопом продолжала занимать полный риск в портфельном лимите.

    Замер на живом счёте в момент находки: шесть открытых сделок занимали
    328.17 USD при потолке 3% ≈ 324 USD, то есть лимит был выбран целиком и
    движок отказывал всем. Реальный остаток риска — 187.51 USD (1.74%): у
    трёх сделок стоп стоял ЗА точкой входа, и терять им было нечего.

    Считается честно в обе стороны: если брокер налил хуже расчётного и
    фактическая дистанция до стопа шире задуманной, живой риск выйдет БОЛЬШЕ
    записанного — так и должно быть.

    За безубытком возвращается 0, а не отрицательное число: запертая прибыль
    — это не «свободный лимит», её нельзя выдать другой сделке."""
    if not risk_per_price or entry is None or stop is None:
        return float(risk_money or 0.0)          # старая строка без пересчёта
    dist = (entry - stop) if direction == "long" else (stop - entry)
    return max(0.0, dist * risk_per_price)


def open_risk_rows(con: sqlite3.Connection) -> list[tuple]:
    """Открытые живые позиции с уже посчитанным живым риском."""
    rows = con.execute(
        "SELECT symbol, direction, strategy, risk_money, entry_price, stop, "
        "risk_per_price, id FROM engine_trades "
        "WHERE status='open' AND mode='live'").fetchall()
    return [(r[0], r[1], r[2],
             live_risk(r[1], r[4], r[5], r[6], r[3]), r[7]) for r in rows]


def exposure(rows, add: tuple | None = None) -> tuple[float, float]:
    """(нетто, валовой) риск портфеля в деньгах.

    rows — из open_risk_rows(); add — сделка, которую только собираемся взять,
    в виде (символ, лонг ли, риск).

    Нетто считается ПО ИНСТРУМЕНТАМ и только потом складывается: гасить друг
    друга имеют право лонг и шорт одного EURUSD, а не лонг EURUSD против
    шорта золота. Разные инструменты здесь считаются независимыми — это
    упрощение, и его снимает отдельная работа по валютным ногам (лонг EURUSD,
    лонг GBPUSD и шорт USDJPY — это три раза шорт доллара, а не три
    независимые ставки)."""
    signed: dict[str, float] = {}
    gross = 0.0
    for sym, direction, _strategy, r, _tid in rows:
        r = r or 0.0
        signed[sym] = signed.get(sym, 0.0) + (r if direction == "long" else -r)
        gross += r
    if add:
        sym, is_long, r = add
        signed[sym] = signed.get(sym, 0.0) + (r if is_long else -r)
        gross += r
    return sum(abs(v) for v in signed.values()), gross


def crossing_trade(con: sqlite3.Connection, symbol: str, is_long: bool) -> int | None:
    """id открытой ВСТРЕЧНОЙ позиции по тому же инструменту, если она есть.

    Раньше здесь стоял запрет (`opposite_open`): встречный вход отклонялся,
    чтобы не путать измерение. 627 отклонённых сигналов за 14 дней —
    четвёртая по величине причина отказа, и единственная, которая не
    защищала счёт.

    🔴 Обоснование запрета к тому же не выдержало проверки. В докстринге
    было написано, что встречная позиция гасит часть движения и «R перестаёт
    значить то, что написано». Но R считается в ledger.close_trade по ЦЕНАМ
    самой сделки — её вход, её стоп, её выход, — и чужая позиция в эту
    арифметику не входит вовсе. Портилось не R, а подсчёт портфельного
    риска, и это чинится подсчётом, а не запретом.

    Вместо запрета — пометка: сделка запоминает, с чем она пересеклась, и
    выборку можно разделить задним числом."""
    row = con.execute(
        "SELECT id FROM engine_trades WHERE status='open' AND mode='live' "
        "AND symbol=? AND direction=? ORDER BY id DESC LIMIT 1",
        (symbol, "short" if is_long else "long")).fetchone()
    return int(row[0]) if row else None


def portfolio_gate(con: sqlite3.Connection, signal: Signal, equity: float,
                   risk_money: float) -> None:
    """Лимиты кучности и суммарного риска.

    🔴 Причина существования — 26-27.08: старый потолок «10 наших позиций»
    не различал символ и направление, набралось десять лонгов по золоту, и
    развернувшийся рынок вынес их одним движением (шесть стопов за 13 минут,
    три за одну минуту). Десять одинаковых ставок — это одна ставка размером
    в десять, и потолок обязан это понимать."""
    rows = open_risk_rows(con)
    total = len(rows)
    if total >= MAX_OPEN_TOTAL:
        raise RiskRefusal("cap_total", f"открыто {total} при потолке {MAX_OPEN_TOTAL}")

    same_symbol = [r for r in rows if r[0] == signal.symbol]
    if len(same_symbol) >= MAX_OPEN_PER_SYMBOL:
        raise RiskRefusal("cap_symbol",
                          f"по {signal.symbol} открыто {len(same_symbol)} при потолке "
                          f"{MAX_OPEN_PER_SYMBOL}")

    same_side = [r for r in same_symbol if r[1] == signal.direction]
    if len(same_side) >= MAX_OPEN_PER_SYMBOL_SIDE:
        raise RiskRefusal("cap_symbol_side",
                          f"по {signal.symbol} в сторону {signal.direction} открыто "
                          f"{len(same_side)} при потолке {MAX_OPEN_PER_SYMBOL_SIDE}")

    same_strat = [r for r in rows if r[2] == signal.strategy]
    if len(same_strat) >= MAX_OPEN_PER_STRATEGY:
        raise RiskRefusal("cap_strategy",
                          f"у стратегии {signal.strategy} открыто {len(same_strat)} "
                          f"при потолке {MAX_OPEN_PER_STRATEGY}")

    if equity <= 0:
        return
    net, gross = exposure(rows, add=(signal.symbol, signal.is_long, risk_money))
    if net / equity > MAX_PORTFOLIO_RISK:
        raise RiskRefusal(
            "cap_portfolio_risk",
            f"направленный риск {net / equity * 100:.2f}% превысит предел "
            f"{MAX_PORTFOLIO_RISK * 100:.2f}%")
    if gross / equity > MAX_GROSS_RISK:
        raise RiskRefusal(
            "cap_gross_risk",
            f"валовой риск {gross / equity * 100:.2f}% превысит предел "
            f"{MAX_GROSS_RISK * 100:.2f}% (пила выбивает встречные стопы оба)")


# ─── стоп-кран стратегии ────────────────────────────────────────────────────

def drawdown_halt(state: dict) -> str | None:
    """Причина остановки стратегии, либо None.

    Меряет просадку ОТ ПИКА кривой в R. Порог не зависит от того, сколько
    стратегия успела заработать раньше — в этом всё отличие от старого
    правила, которое после пика +32 ATR разрешало потерять 23 ATR прежде
    чем сработать."""
    if (state.get("n_closed") or 0) < MIN_TRADES_BEFORE_HALT:
        return None
    dd = (state.get("cum_r") or 0.0) - (state.get("peak_r") or 0.0)
    if dd <= -MAX_DRAWDOWN_R:
        return (f"просадка от пика {dd:.2f}R достигла предела -{MAX_DRAWDOWN_R}R "
                f"(пик {state.get('peak_r'):.2f}R, сейчас {state.get('cum_r'):.2f}R, "
                f"сделок {state.get('n_closed')})")
    return None


def strategy_gate(state: dict) -> None:
    if state.get("status") == ST_HALTED:
        raise RiskRefusal("strategy_halted",
                          f"стратегия остановлена: {state.get('halt_reason') or 'без причины'}")
