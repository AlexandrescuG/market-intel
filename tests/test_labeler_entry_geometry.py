"""Тест на analyze/labeler.py::_entry_and_barriers() -- ревью 14.08, п.4:
альтернативные конфиги входа (entry=open следующего бара, stop=экстремум
сигнального бара). Регрессионный тест на реальный класс бага, найденный на
разведочном pilot-скрипте: entry price и i0 (точка старта _walk_barriers)
считались в двух разных местах -- для geometry="next_open" entry брался из
close ВСЕГО сигнального дня, а i0 (точка старта пути) оставался на НАЧАЛЕ
дня -- систематическое искажение winrate на КАЖДОМ occurrence, где цена
внутри дня прошла путь от open к close. Явный assert "res_candles[i0]
согласован с entry_ts" ловит эту регрессию, если кто-то её случайно вернёт.

geometry="close" тест сверяет БИТ-В-БИТ то же поведение, что было в коде
до рефакторинга (см. Core-лог 14.08, live-сверка с реальными labels)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze.labeler import _entry_and_barriers, _barriers

# Синтетические 30m-свечи: 4 получасовки дня 1 (ts=0,1800,3600,5400), затем
# день 2 начинается на ts=7200 (следующие 4 получасовки).
RES_CANDLES = [
    {"ts": 0, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5},
    {"ts": 1800, "o": 100.5, "h": 102.0, "l": 100.0, "c": 101.5},
    {"ts": 3600, "o": 101.5, "h": 103.0, "l": 101.0, "c": 102.5},
    {"ts": 5400, "o": 102.5, "h": 104.0, "l": 102.0, "c": 110.0},  # день 1 закрывается высоко (110)
    {"ts": 7200, "o": 110.2, "h": 111.0, "l": 109.5, "c": 110.5},  # день 2 открывается рядом с close дня 1
    {"ts": 9000, "o": 110.5, "h": 112.0, "l": 110.0, "c": 111.0},
]
TS_TO_IDX = {c["ts"]: i for i, c in enumerate(RES_CANDLES)}

# Один "сигнальный" D1-бар (i=0, ts=0..7200) + следующий (i=1, ts=7200..).
SIGNAL_CANDLES = [
    {"ts": 0, "o": 100.0, "h": 104.0, "l": 99.0, "c": 110.0},
    {"ts": 7200, "o": 110.2, "h": 112.0, "l": 109.5, "c": 111.0},
]

ATR_VAL, ATR_MULT, RR = 5.0, 1.5, 2.0


def test_close_geometry_entry_matches_res_candle_at_signal_ts():
    """entry == res_candles[i0]["c"] где i0 -- бар С ТЕМ ЖЕ ts, что сигнал
    (НЕ close всего D1-дня, см. докстринг _entry_and_barriers)."""
    geo = _entry_and_barriers("close", "bullish", ATR_VAL, ATR_MULT, RR, 0,
                               RES_CANDLES, TS_TO_IDX, SIGNAL_CANDLES, 0)
    assert geo is not None
    assert geo["i0"] == 0
    assert geo["entry"] == RES_CANDLES[0]["c"] == 100.5
    assert geo["entry"] != SIGNAL_CANDLES[0]["c"]  # НЕ close дня (110.0) -- умышленно


def test_next_open_geometry_entry_matches_i0_bar():
    """🔴 Регрессионный тест на найденный баг: entry ДОЛЖЕН быть ценой ТОГО
    ЖЕ бара, что и i0 (иначе walk стартует не с той точки, откуда взята
    цена барьеров) -- для next_open это open следующего сигнального дня."""
    geo = _entry_and_barriers("next_open", "bullish", ATR_VAL, ATR_MULT, RR, 0,
                               RES_CANDLES, TS_TO_IDX, SIGNAL_CANDLES, 0)
    assert geo is not None
    assert geo["entry_ts"] == 7200
    assert geo["i0"] == TS_TO_IDX[7200]
    # Явный якорь на сам класс бага: entry ОБЯЗАН совпадать с ценой бара i0,
    # а не с каким-либо другим баром (напр. close предыдущего дня).
    assert geo["entry"] == RES_CANDLES[geo["i0"]]["o"] == 110.2
    assert geo["entry"] != RES_CANDLES[0]["c"]


def test_next_open_no_next_signal_bar_returns_none():
    geo = _entry_and_barriers("next_open", "bullish", ATR_VAL, ATR_MULT, RR, 7200,
                               RES_CANDLES, TS_TO_IDX, SIGNAL_CANDLES, 1)
    assert geo is None  # signal_i=1 -- последний сигнальный бар, некуда идти дальше


def test_extreme_geometry_stop_at_signal_bar_low_bullish():
    """stop = low сигнального D1-бара (99.0), НЕ atr_mult*atr."""
    geo = _entry_and_barriers("extreme", "bullish", ATR_VAL, ATR_MULT, RR, 0,
                               RES_CANDLES, TS_TO_IDX, SIGNAL_CANDLES, 0)
    assert geo is not None
    assert geo["entry"] == 100.5  # то же entry, что "close" -- меняется только stop
    assert geo["lower"] == SIGNAL_CANDLES[0]["l"] == 99.0
    stop_dist = geo["entry"] - geo["lower"]
    assert geo["upper"] == geo["entry"] + RR * stop_dist


def test_extreme_geometry_stop_at_signal_bar_high_bearish():
    geo = _entry_and_barriers("extreme", "bearish", ATR_VAL, ATR_MULT, RR, 0,
                               RES_CANDLES, TS_TO_IDX, SIGNAL_CANDLES, 0)
    assert geo is not None
    assert geo["upper"] == SIGNAL_CANDLES[0]["h"] == 104.0


def test_extreme_geometry_zero_stop_distance_returns_none():
    """entry == экстремум (edge case: сигнальный бар без хвоста) -- risk=0,
    честный None, не деление на ноль где-то выше по стеку."""
    flat_signal = [{"ts": 0, "o": 100.0, "h": 100.5, "l": 100.5, "c": 100.5}]
    geo = _entry_and_barriers("extreme", "bullish", ATR_VAL, ATR_MULT, RR, 0,
                               RES_CANDLES, TS_TO_IDX, flat_signal, 0)
    assert geo is None


def test_close_and_extreme_share_same_entry_and_i0():
    """extreme меняет ТОЛЬКО барьеры -- entry/i0 идентичны close-варианту
    (обе geometry входят "как обычно", в один и тот же момент)."""
    geo_close = _entry_and_barriers("close", "bearish", ATR_VAL, ATR_MULT, RR, 0,
                                     RES_CANDLES, TS_TO_IDX, SIGNAL_CANDLES, 0)
    geo_extreme = _entry_and_barriers("extreme", "bearish", ATR_VAL, ATR_MULT, RR, 0,
                                       RES_CANDLES, TS_TO_IDX, SIGNAL_CANDLES, 0)
    assert geo_close["entry"] == geo_extreme["entry"]
    assert geo_close["i0"] == geo_extreme["i0"]
    assert geo_close["upper"] != geo_extreme["upper"]  # барьеры разные -- это и есть суть extreme
