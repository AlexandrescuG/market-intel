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
SYMBOL_MAP = {
    "EURUSD": "EURUSD.",
    "USDJPY": "USDJPY.",
    "XAUUSD": "XAUUSD",   # без точки — у этого брокера уникально для золота
    "USDRUB": "USDRUB",   # недоступен у Daoti.io-Server — останется пустым
    "USDCNY": "USDCNH.",
    "USDZAR": "USDZAR.",
    "USDKZT": "USDKZT",   # недоступен у Daoti.io-Server — останется пустым
    "USDAED": "USDAED",   # недоступен у Daoti.io-Server — останется пустым
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
