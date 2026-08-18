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
        "USDRUB": "USDRUB",
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
# 🔴 СОЗНАТЕЛЬНО ОСТАВЛЕН Daoti, хотя терминал уже на Ava. Переключение
# сюда Ava выглядит как очевидное исправление, но испортило бы price_bars:
#   * запись идёт INSERT OR REPLACE под НАШИМ ключом, то есть Ava-бары
#     легли бы поверх истории Daoti в одном ряду;
#   * под ключом USDCNY лежит история Daoti, а там это был USDCNH —
#     ОФФШОРНЫЙ юань; у Ava "USDCNY" оншорный. Разные инструменты,
#     склеивать их в один ряд нельзя;
#   * бары двух площадок в одном ряду — тот же класс, что 45% трек-рекорда
#     Signals, размеченные по чужому инструменту (17.08).
#
# Следствие, которое НАДО знать: после смены счёта mt5-pull молча
# перестал качать пять инструментов — в логе "USDCNH. (USDCNY) недоступен
# у брокера — пропуск", уровень INFO, exit 0. Реально тянется только
# USDRUB (единственное совпадение имён). Чинится либо переключением сюда
# Ava с раздельным хранением по площадкам, либо возвратом на Daoti —
# это решение владельца, не побочный эффект калибровки издержек.
BARS_SERVER = "Daoti.io-Server"

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
