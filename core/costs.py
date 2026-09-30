"""core/costs.py — WP2.1 SPEC_alpha_engine_implementation.md.

Модель издержек для бэктеста/разметки: спред за сделку + своп за
перенос позиции через ночь/выходные. Единая ставка `COST_PER_TRADE_ATR =
0.03` (`tools/edu_build/ema_reality.py:38`) для ВСЕХ инструментов сама
спека называет "заведомо неверной" для XAUUSD против SOLUSD.

🔴 Обновлено 12.08.2026 (REVIEW_alpha_engine_WP0-WP3.md §3): для 5
реально торгуемых у брокера инструментов (`mt5_config.SYMBOL_MAP`,
Daoti.io-Server, счёт 1012535) получены ЖИВЫЕ измерения через
`mt5.symbol_info()` по rpyc-мосту (`sbf-mt5-bridge.service`) — раньше
не удавалось из-за расхождения версий rpyc между системным python3
(5.2.3) и venv сервиса (6.0.2, "invalid message type: 18"); при вызове
из ТОГО ЖЕ venv (`market_intel/.venv`), что и у сервиса, мост отвечает
нормально. `history_deals_get()` на этом счету пуст (0 сделок за всю
историю — торгов на нём никогда не было) — поэтому КОМИССИЯ остаётся
неизвестной и НЕ моделируется (0.0, честно, не выдумка); спред и своп —
измерены напрямую:

  - `journal_trades` (журнал пользователя) — 0 строк, тот же вывод.
  - Спред (`symbol_info().spread`, в пунктах) — снят ОДНИМ живым снимком
    12.08.2026, не усреднён по сессиям/времени суток; переведён в долю
    ATR через МЕДИАННЫЙ ATR14 всей доступной истории price_bars ОТДЕЛЬНО
    для каждого signal_tf (H1/H4/D1) — единая по всем ТФ ставка была
    системной ошибкой: спред как ЦЕНОВАЯ величина не зависит от ТФ
    графика, а ATR растёт с ТФ, так что доля от ATR падает с H1 к D1 в
    ~5 раз (см. `DAOTI_SPREAD_ATR` — GOLD H1=0.22 ATR против D1=0.046).
  - Своп (`symbol_info().swap_long/short`, в валюте счёта за лот за
    ночь) — переведён в ценовые единицы через `trade_tick_value/
    trade_tick_size` (курс конвертации на момент снятия) и подключён в
    `analyze/labeler.py:label_one` через `nights_held` (см. `swap_cost_price`).

[ДОПУЩЕНИЕ] Для инструментов ВНЕ этих 5 (большинство реестра) —
измерений всё ещё нет, остаётся класс-эвристика ниже (2 грубых уровня
относительно исходной ставки ema_reality: мажоры/металлы/индексы/крипта
— 0.03 ATR; FX-экзотика/commodities — вдвое шире, 0.06 ATR; направление
обосновано, число не откалибровано) — заменить первым, как появится
реальный источник для конкретного инструмента.
"""
from __future__ import annotations

# Живые измерения 12.08.2026, Daoti.io-Server (счёт 1012535), symbol_info()
# через rpyc (см. докстринг модуля). Ключ — (canonical_symbol, signal_tf).
DAOTI_SPREAD_ATR = {
    ("EURUSD", "H1"): 0.0711, ("EURUSD", "H4"): 0.0344, ("EURUSD", "D1"): 0.0140,
    ("USDJPY", "H1"): 0.0656, ("USDJPY", "H4"): 0.0315, ("USDJPY", "D1"): 0.0123,
    ("GOLD", "H1"): 0.2204, ("GOLD", "H4"): 0.1106, ("GOLD", "D1"): 0.0457,
    ("USDCNY", "H1"): 0.1672, ("USDCNY", "H4"): 0.0805, ("USDCNY", "D1"): 0.0329,
    ("USDZAR", "H1"): 0.1597, ("USDZAR", "H4"): 0.0786, ("USDZAR", "D1"): 0.0327,
}

# (swap_long, swap_short), в ЦЕНОВЫХ единицах за ночь. Знак сохранён из
# MT5 как есть: отрицательное — списание, положительное — начисление.
DAOTI_SWAP_PRICE_PER_NIGHT = {
    "EURUSD": (-0.0000821, 0.0000057),
    "USDJPY": (0.0236641, -0.0384362),
    "GOLD": (-0.4174000, 0.3036000),
    "USDCNY": (0.0001788, -0.0004959),
    "USDZAR": (-0.0362154, 0.0118765),
}

# ─── Живые измерения 18.08.2026, Ava-Demo 1-MT5 (счёт 101746781) ────────────
#
# 🔴 Счёт сменился, и константы Daoti к нему НЕ ПРИМЕНИМЫ. Это не косметика:
# расхождение в единицах ATR от 0.10x до 8.7x.
#
#   символ   tf    Daoti     Ava    Ava/Daoti
#   EURUSD   H1   0.0711  0.1016      1.43x
#   USDJPY   H1   0.0656  0.0969      1.48x
#   GOLD     H1   0.2204  0.0254      0.12x   <- у Ava спред золота ВОСЕМЬ раз уже
#   USDCNY   H1   0.1672  1.3270      7.94x   <- и это РАЗНЫЕ инструменты:
#   USDZAR   H1   0.1597  0.3995      2.50x      у Daoti USDCNH (оффшорный юань)
#
# Спред снят по symbol_info_tick() (ask-bid), а не по symbol_info().spread:
# у только что выбранного символа spread приходит нулём до первой котировки,
# и GOLD показывал 0 — ровно та величина, которую заманчиво принять за факт.
# ATR — по 14 последним барам price_bars соответствующего ТФ.
AVA_SPREAD_ATR = {
    ("EURUSD", "H1"): 0.1016, ("EURUSD", "H4"): 0.0430, ("EURUSD", "D1"): 0.0201,
    ("USDJPY", "H1"): 0.0969, ("USDJPY", "H4"): 0.0486, ("USDJPY", "D1"): 0.0139,
    ("GOLD", "H1"): 0.0254, ("GOLD", "H4"): 0.0140, ("GOLD", "D1"): 0.0047,
    ("USDCNY", "H1"): 1.3270, ("USDCNY", "H4"): 0.6364, ("USDCNY", "D1"): 0.2863,
    ("USDZAR", "H1"): 0.3995, ("USDZAR", "H4"): 0.2009, ("USDZAR", "D1"): 0.0830,
}

# (swap_long, swap_short) в ценовых единицах за ночь, знак как в MT5.
AVA_SWAP_PRICE_PER_NIGHT = {
    "EURUSD": (-0.0000322, 0.0000110),
    "USDJPY": (0.0020921, -0.0083845),
    "GOLD": (-0.0950000, 0.0050000),
    "USDCNY": (0.0000931, -0.0002767),
    "USDZAR": (-0.0006537, -0.0000325),
}

# Ключ — server из account_info(). Обе таблицы живут рядом: price_bars,
# набранные через Daoti, остаются валидными для расчётов по Daoti, и знать,
# чьи это числа, нужно ретроспективно.
SPREAD_ATR_BY_SERVER = {
    "Daoti.io-Server": DAOTI_SPREAD_ATR,
    "Ava-Demo 1-MT5": AVA_SPREAD_ATR,
}
SWAP_PRICE_BY_SERVER = {
    "Daoti.io-Server": DAOTI_SWAP_PRICE_PER_NIGHT,
    "Ava-Demo 1-MT5": AVA_SWAP_PRICE_PER_NIGHT,
}

# 🔴 КОМИССИЯ по-прежнему НЕ измерена ни на одной площадке и остаётся 0.0.
# Демо-счёт заводится ровно ради неё: history_deals_get() отдаст фактическую
# величину после первых закрытых сделок. До того — честный ноль, не выдумка.
#
# ПРОСКАЛЬЗЫВАНИЕ демо не измерит в принципе: сервер наливает по котировке,
# нет проскока на гэпах, новостях, реквотов и отказов. Ошибается в
# оптимистичную сторону. Фиксируется как известная неизмеренная величина,
# нулём НЕ подменяется.
COMMISSION_PRICE = 0.0

CLASS_COST_ATR = {
    "fx_major": 0.03,
    "fx_exotic": 0.06,
    "metal": 0.03,
    "index": 0.03,
    "crypto": 0.03,
    "commodity": 0.06,
}
_DEFAULT_CLASS = "fx_major"  # ema_reality.py исходная ставка, самый ликвидный класс

# Канонический (реестровый) символ -> класс ликвидности.
INSTRUMENT_CLASS: dict[str, str] = {
    "EURUSD": "fx_major", "GBPUSD": "fx_major", "USDJPY": "fx_major",
    "USDCHF": "fx_major", "USDCAD": "fx_major", "AUDUSD": "fx_major", "NZDUSD": "fx_major",
    "GOLD": "metal", "SILVER": "metal",
    "EURGBP": "fx_exotic", "USDBRL": "fx_exotic", "USDMXN": "fx_exotic", "USDTRY": "fx_exotic",
    "USDPLN": "fx_exotic", "USDCZK": "fx_exotic", "USDHUF": "fx_exotic", "USDKRW": "fx_exotic",
    "USDRUB": "fx_exotic", "USDCNY": "fx_exotic", "USDZAR": "fx_exotic",
    "USDKZT": "fx_exotic", "USDAED": "fx_exotic",
    "DXY": "index", "SPX": "index", "NASDAQ": "index", "DJI": "index", "VIX": "index", "RUT": "index",
    "WTI": "commodity", "NG": "commodity", "BRENT": "commodity",
    "BTC": "crypto", "ETH": "crypto", "SOL": "crypto",
}


def cost_atr_fraction(canonical_symbol: str, signal_tf: str | None = None) -> float:
    """Издержка за одну смену позиции, в долях ATR (симметрично
    ema_reality.py — списывается один раз при входе, не за каждый бар).
    Если для (symbol, signal_tf) есть живое измерение (`DAOTI_SPREAD_ATR`)
    — используется оно; иначе — класс-эвристика (см. докстринг модуля)."""
    if signal_tf is not None:
        real = DAOTI_SPREAD_ATR.get((canonical_symbol, signal_tf))
        if real is not None:
            return real
    cls = INSTRUMENT_CLASS.get(canonical_symbol, _DEFAULT_CLASS)
    return CLASS_COST_ATR.get(cls, CLASS_COST_ATR[_DEFAULT_CLASS])


def entry_cost_price(canonical_symbol: str, atr_value: float, signal_tf: str | None = None) -> float:
    """Издержка входа в ЦЕНОВЫХ единицах (для прямого вычитания из P&L)."""
    if atr_value is None or atr_value <= 0:
        return 0.0
    return cost_atr_fraction(canonical_symbol, signal_tf) * atr_value


def swap_cost_price(canonical_symbol: str, direction: str, nights_held: int) -> float:
    """Своп за nights_held ночей переноса позиции, в ценовых единицах,
    С УЧЁТОМ ЗНАКА (может быть начислением, не только списанием).
    [ДОПУЩЕНИЕ] nights_held считается вызывающим кодом как
    floor((ts_exit-ts_entry)/86400) — без учёта тройного свопа в среду и
    без точного часа rollover у конкретного брокера (не публикуется).
    Для 5 инструментов Daoti — реальные ставки (`DAOTI_SWAP_PRICE_PER_NIGHT`,
    измерены 12.08.2026). Для остальных инструментов реестра — 0.0, как и
    раньше (нет измерений, не выдумываем)."""
    if nights_held <= 0:
        return 0.0
    rates = DAOTI_SWAP_PRICE_PER_NIGHT.get(canonical_symbol)
    if rates is None:
        return 0.0
    swap_long, swap_short = rates
    per_night = swap_long if direction == "bullish" else swap_short
    return per_night * nights_held


def config_key_suffix() -> str:
    """Строка для config_key бэктеста — фиксирует, какая версия модели
    издержек участвовала в конкретном прогоне (Acceptance WP2: "в отчёте
    явно указан config_key и модель издержек")."""
    return "costsv1"
