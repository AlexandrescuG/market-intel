"""
mt5_config.py — общие таблицы для mt5_pull.py (нативный Windows) и
mt5_bridge_pull.py (rpyc-мост внутри Wine-бутылки Trading).

Вынесено в отдельный файл, чтобы обе стороны не расходились в имени
символа у брокера — до этого файла таблица жила только в mt5_pull.py и
дублировать её ещё раз для rpyc-моста значило бы завести второй источник
истины.
"""

# наш ключ  ->  имя символа у брокера (проверь в MarketWatch! у брокеров разнится).
# Текущий брокер (Daoti.io-Server, счёт 1012535) суффиксует майоры точкой —
# проверено mt5.symbols_get() 2026-07-16: EURUSD./USDJPY./GBPUSD./USDCNH./
# USDZAR. существуют, USDRUB/USDKZT/USDAED у этого брокера нет вообще (не 404
# скрипта — просто не торгуются здесь).
# 🔴 18.08.2026: счёт сменился на 101746781, сервер "Ava-Demo 1-MT5",
# брокер "Ava Trade Ltd." — ДРУГАЯ площадка, не Daoti. Карты стали
# по-серверными, старая НЕ затёрта: price_bars, набранные через Daoti,
# остаются валидными, и знать, чьи это имена, нужно ретроспективно.
#
# Проверено symbols_get() 18.08 (842 символа у Ava):
#   * суффикс-точки нет ни у одного майора — "EURUSD.", "USDJPY.",
#     "USDCNH.", "USDZAR." у Ava НЕ существуют;
#   * золота под именем "XAUUSD" нет вообще, оно называется "GOLD"
#     (есть ещё GOLD_FUTURE и PAX_GOLD — не они);
#   * "USDCNH" нет, есть "USDCNY" — то есть у Ava это не оффшорный юань;
#   * "USDRUB" ЕСТЬ (у Daoti не было);
#   * "USDKZT" и "USDAED" нет так же, как и у Daoti.
SYMBOL_MAP_BY_SERVER = {
    "Daoti.io-Server": {
        "EURUSD": "EURUSD.",
        "USDJPY": "USDJPY.",
        "XAUUSD": "XAUUSD",   # без точки — у этого брокера уникально для золота
        "USDRUB": "USDRUB",   # недоступен у Daoti.io-Server — останется пустым
        "USDCNY": "USDCNH.",
        "USDZAR": "USDZAR.",
        "USDKZT": "USDKZT",   # недоступен у Daoti.io-Server — останется пустым
        "USDAED": "USDAED",   # недоступен у Daoti.io-Server — останется пустым
    },
    "Ava-Demo 1-MT5": {
        "EURUSD": "EURUSD",
        "USDJPY": "USDJPY",
        "XAUUSD": "GOLD",
        "USDRUB": "USDRUB",   # есть, но котировки мёртвые — последний бар 14.07
        # 🔴 РЯД USDCNY СОСТАВНОЙ, это решение владельца 18.08.2026.
        # До 18.08 под этим ключом лежат бары Daoti, а там символ назывался
        # USDCNH — ОФФШОРНЫЙ юань. С 18.08 доливается оншорный USDCNY от Ava.
        # Это два разных рынка; расхождение котировок обычно доли процента,
        # но стык в ряду существует и он реален.
        #
        # Где это увидят: любой расчёт по длинной истории USDCNY (base_rate,
        # labels, волатильность) пересекает точку стыка. Если однажды
        # обнаружится необъяснимый сдвиг статистик USDCNY около 18.08.2026 —
        # причина здесь, а не в рынке. Точка стыка записана в Core-лог и в
        # docs/price_bars_usdcny_splice.md.
        "USDCNY": "USDCNY",
        "USDZAR": "USDZAR",
        "USDKZT": "USDKZT",   # недоступен у Ava — останется пустым
        "USDAED": "USDAED",   # недоступен у Ava — останется пустым
    },
}

# Сервер, к которому подключён калибровочный контур издержек
# (SPEC_mt5_cost_calibration_2026-08-18.md). НЕ источник баров — см. ниже.
CALIBRATION_SERVER = "Ava-Demo 1-MT5"

# Сервер, чьи имена использует доливка price_bars.
#
# 🔴 18.08: переключён на Ava, потому что доливка ВСТАЛА.
#
# Проверено по журналу: в 00:06 EEST mt5-pull ещё качал EURUSD/XAUUSD
# нормально (Daoti-имена работали), в 08:11 — уже "USDCNH. (USDCNY)
# недоступен у брокера — пропуск" по всем пяти, а тянется только USDRUB,
# у которого котировки мёртвые с 14.07. Смена счёта случилась между этими
# прогонами. Другого источника price_bars нет — то есть без переключения
# бары просто перестают поступать, тихо, с exit 0.
#
# Цена переключения, которую надо знать: Ava-бары лягут в один ряд с
# историей Daoti (INSERT OR REPLACE под нашим ключом). Для майоров и
# золота расхождение котировок между площадками мало и приемлемо. Для
# USDCNY это стык двух разных рынков (CNH -> CNY) — принято владельцем
# 18.08, см. комментарий в карте выше.
BARS_SERVER = "Ava-Demo 1-MT5"

DEFAULT_SERVER = BARS_SERVER


def symbol_map_for(server: str | None) -> dict:
    """Карта имён для конкретного сервера. Неизвестный сервер -> KeyError,
    а не тихий фолбэк на чужие имена: молча качать бары под именами другого
    брокера — ровно тот класс ошибки, из-за которого 45% трек-рекорда
    Signals оказались размечены по чужому инструменту (17.08)."""
    key = server or DEFAULT_SERVER
    if key not in SYMBOL_MAP_BY_SERVER:
        raise KeyError(
            f"нет карты символов для сервера {key!r}; известны: "
            f"{sorted(SYMBOL_MAP_BY_SERVER)}. Снять symbols_get() и добавить явно.")
    return SYMBOL_MAP_BY_SERVER[key]


# Обратная совместимость: mt5_pull.py / mt5_bridge_pull.py /
# mt5_deep_backfill_30m.py импортируют SYMBOL_MAP напрямую. Указывает на
# BARS_SERVER — поведение доливки баров этой правкой НЕ меняется.
SYMBOL_MAP = SYMBOL_MAP_BY_SERVER[BARS_SERVER]

# Имена инструментов у Ava для РЕАЛ-ТАЙМ отдачи графиков (serve.py::_handle_chart_tail).
# Отдельно от SYMBOL_MAP (та — только для доливки price_bars по 5-6 символам): сюда
# входят ВСЕ инструменты, что есть у брокера, чтобы внутридневка (M1..H4) шла из MT5
# в реальном времени (~0.3 мин), а не из Yahoo, у которого фьючерсы/индексы отстают
# ~10 мин. Проверено symbols_get()/copy_rates M1 19.08.2026. Индексы/энергия у Ava
# названы по-своему: S&P500=US_500, Nasdaq100=US_TECH100, Dow=US_30, DXY=DOLLAR_INDX,
# нефть WTI=CrudeOIL (WTICrude — мёртвый символ), газ=NATURAL_GAS. Отсутствуют у Ava:
# USDAED/USDBRL/USDCZK/USDKZT/USDRUB — для них остаётся Yahoo (FX, задержка мала).
CHART_BROKER_MAP = {
    "EURUSD": "EURUSD", "GBPUSD": "GBPUSD", "AUDUSD": "AUDUSD", "NZDUSD": "NZDUSD",
    "EURGBP": "EURGBP", "USDJPY": "USDJPY", "USDCAD": "USDCAD", "USDCHF": "USDCHF",
    "USDCNY": "USDCNY", "USDHUF": "USDHUF", "USDMXN": "USDMXN",
    # USDKRW у Ava ЕСТЬ как символ, но котировки мёртвые с 10.02.2026 (проверено
    # 20.08: последний M15 — 10.02 11:30, тик той же давности). Символ в карте
    # заставлял график отдавать февральские данные как настоящие; убран, чтобы
    # вон уходил на Yahoo. Мёртвый фид хуже отсутствующего: отсутствующий видно.
    "USDPLN": "USDPLN", "USDTRY": "USDTRY", "USDZAR": "USDZAR",
    "GOLD": "GOLD", "SILVER": "SILVER", "WTI": "CrudeOIL", "NG": "NATURAL_GAS",
    "DXY": "DOLLAR_INDX", "SPX": "US_500", "NASDAQ": "US_TECH100", "DJI": "US_30",
    "BTC": "BTCUSD", "ETH": "ETHUSD", "SOL": "SOLUSD",
}

# наш tf-код -> имя константы TIMEFRAME_* в пакете MetaTrader5.
# Хранится строкой (не самой константой), потому что mt5_bridge_pull.py
# резолвит её через getattr() на УДАЛЁННОМ модуле (нет локального MetaTrader5
# на Linux-стороне) — см. SPEC_alpha_engine_implementation.md WP0.3.
TIMEFRAME_ATTR = {
    "15m": "TIMEFRAME_M15",
    "30m": "TIMEFRAME_M30",
    "1h":  "TIMEFRAME_H1",
    "4h":  "TIMEFRAME_H4",
    "1d":  "TIMEFRAME_D1",
    "1w":  "TIMEFRAME_W1",
}

# сколько последних баров тянуть в штатном режиме (без бэкфилла)
RECENT_BARS = {"15m": 3000, "30m": 3000, "1h": 3000, "4h": 2000, "1d": 2000, "1w": 1000}
