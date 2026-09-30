"""SBF_Charts_Layer4_Spec, Фаза 2: маппинг символов журнала → символы графика.

Спека предполагала, что такой маппинг уже есть «в импорте MT4/5» —
неверно: core/journal_import.py._normalize_symbol() только чистит суффиксы
брокера (.m/.ecn/...), не переименовывает в номенклатуру графика. Сделки в
`trades` хранятся под именами journal/price_bars-домена (XAUUSD, не GOLD —
тот же домен, что journal_brief.get_available_symbols(), см. память Фазы 1).
Этот модуль — единственное место, где эти два словаря символов встречаются.
"""

_JOURNAL_TO_CHART = {
    "XAUUSD": "GOLD", "XAU": "GOLD",
    "XAGUSD": "SILVER", "XAG": "SILVER",
    "USOIL": "WTI", "WTIUSD": "WTI", "UKOIL": "WTI",
    "NATGAS": "NG", "XNGUSD": "NG",
    "BTCUSD": "BTC", "ETHUSD": "ETH", "SOLUSD": "SOL",
    "US500": "SPX", "SPX500": "SPX",
    "NAS100": "NASDAQ", "USTEC": "NASDAQ",
    "US30": "DJI", "DJ30": "DJI",
}


def to_chart_symbol(journal_symbol: str) -> str | None:
    """journal_symbol уже нормализован (_normalize_symbol — суффиксы срезаны,
    upper). Если сам по себе уже совпадает с символом графика (EURUSD,
    GBPUSD, USDJPY, USDRUB, USDKZT — совпадают дословно в обоих доменах, или
    пользователь руками ввёл 'GOLD'/'BTC' и т.п. при ручном добавлении
    сделки) — используем как есть. USDCNY/USDAED/USDZAR графика не имеют
    вовсе (не входят в 15 инструментов ohlc_*.json) — вернётся None, сделка
    в них честно не покажется ни на одном графике."""
    from serve import _chartable_symbols  # локальный импорт — избегаем цикла на старте
    s = (journal_symbol or "").upper().strip()
    if not s:
        return None
    if s in _chartable_symbols():
        return s
    return _JOURNAL_TO_CHART.get(s)


def chart_symbol_aliases(chart_symbol: str) -> list[str]:
    """Обратное отображение: все journal-имена, которые матчатся на данный
    символ графика (для SQL WHERE symbol IN (...)) — включая сам символ
    графика (на случай ручного ввода 1:1)."""
    aliases = [chart_symbol]
    for journal_sym, chart_sym in _JOURNAL_TO_CHART.items():
        if chart_sym == chart_symbol:
            aliases.append(journal_sym)
    return aliases
