"""
focus_live.py — SPEC_focus_engine.md, live-контекст (§3, §9).

tick() — вызывается раз в ~60с (см. focus_live_loop.py): читает
web/data/quotes.json (уже свежий каждые 15с от sbf-quotes.service — НЕ
дёргаем Yahoo второй раз, см. план), обновляет instrument_live.day_high/
day_low для live_capable-инструментов, затем пересчитывает фокус для
scope='default' и КАЖДОГО отдельного пользователя с ватчлистом (кроме
запиненных — им select_focus() и не нужен, пин читается прямо в API).

Вынесено в отдельный модуль (не только *_loop.py с while True), чтобы
`python3 -c "import focus_live; focus_live.tick()"` можно было гонять
вручную по одному циклу для проверки (см. план, шаг 6 verification).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from core import focus_db, journal_brief
from core.focus import DEFAULT_UNIVERSE, NO_LIVE_FEED, select_focus
from core.journal_symbols import to_chart_symbol

_WEB_DATA = Path(__file__).parent / "web" / "data"

# Тот же label->ticker, что publish.py's WATCH (+ DXY) -- quotes.json ключуется
# тикером Yahoo, не site-меткой (см. план: "Preface #1" находки Plan-агента).
LABEL_TO_TICKER = {
    "GOLD": "GC=F", "SILVER": "SI=F",
    "BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD",
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X",
    "SPX": "^GSPC", "NASDAQ": "^IXIC", "DJI": "^DJI",
    "WTI": "CL=F", "NG": "NG=F", "DXY": "DX-Y.NYB",
}


def _read_quotes() -> dict:
    try:
        data = json.loads((_WEB_DATA / "quotes.json").read_text())
        return data.get("quotes") or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _update_instrument_live(quotes: dict, now_ts: int, now_dt: datetime, today: str, verbose: bool) -> None:
    for row in focus_db.all_instruments(live_capable_only=True):
        symbol = row["symbol"]
        ticker = LABEL_TO_TICKER.get(symbol)
        q = quotes.get(ticker) if ticker else None
        if not q or q.get("price") is None:
            continue
        price = float(q["price"])
        session_state = focus_db.compute_session_state(row["asset_class"], now_dt)

        prev = focus_db.load_instrument_live(symbol)
        # Новый торговый день (по UTC-дате последнего апдейта) -- сбрасываем
        # high/low на текущую цену, а не тянем вчерашний диапазон дальше.
        # instrument_live не хранит отдельную day_start_ts-колонку (нет в
        # буквальной схеме спеки) -- дата уже сохранённого ts достаточна.
        is_new_day = (
            prev is None
            or datetime.fromtimestamp(prev["ts"], tz=timezone.utc).strftime("%Y-%m-%d") != today
        )
        if is_new_day:
            day_open = day_high = day_low = price
        else:
            day_open = prev["day_open"]
            day_high = max(prev["day_high"], price)
            day_low = min(prev["day_low"], price)

        focus_db.save_instrument_live(symbol, now_ts, day_open, day_high, day_low, price, session_state)
        if verbose:
            print(f"  {symbol}: last={price} high={day_high} low={day_low} session={session_state}"
                  + (" (новый день)" if is_new_day else ""))


def _active_user_scopes() -> list[str]:
    """Пользователи (не 'default' -- тот уже покрыт scope_key='default'/
    DEFAULT_UNIVERSE) с непустым ватчлистом и БЕЗ пина (запиненным
    select_focus() не нужен -- пин читается напрямую в API)."""
    return [uid for uid in journal_brief.list_watchlist_user_ids(exclude_default=True)
            if not journal_brief.get_pinned(uid)]


def _scope_symbols(user_id: str | None) -> list[str]:
    if user_id is None:
        return DEFAULT_UNIVERSE
    raw = journal_brief.get_watchlist(user_id)
    if not raw:
        return DEFAULT_UNIVERSE
    mapped = []
    for s in raw:
        chart_sym = to_chart_symbol(s) or (s if s in DEFAULT_UNIVERSE else None)
        if chart_sym:
            mapped.append(chart_sym)
    return mapped or DEFAULT_UNIVERSE


def _reassign_scope(scope_key: str, symbols: list[str], today: str, now_ts: int, verbose: bool) -> None:
    candidates = focus_db.build_candidates(symbols, today)
    current = focus_db.load_focus_state(scope_key)
    state = select_focus(scope_key, candidates, None, current, now_ts, new_source="live")
    focus_db.save_focus_state(state)
    if verbose:
        print(f"  scope={scope_key}: symbol={state.symbol} anomaly={state.anomaly} source={state.source}")


def tick(verbose: bool = False) -> None:
    focus_db.ensure_schema()
    now_ts = int(time.time())
    now_dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
    today = focus_db.today_str(now_dt)

    quotes = _read_quotes()
    _update_instrument_live(quotes, now_ts, now_dt, today, verbose)

    _reassign_scope("default", DEFAULT_UNIVERSE, today, now_ts, verbose)
    for user_id in _active_user_scopes():
        _reassign_scope(f"user:{user_id}", _scope_symbols(user_id), today, now_ts, verbose)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    tick(verbose=args.verbose)
