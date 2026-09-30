#!/usr/bin/env python3
"""
Yahoo Finance загрузчик OHLCV баров → price_bars.

Закрывает ТОЛЬКО дыры брокера. С 20.08 единый источник цены на графиках —
MT5/AvaTrade (SPEC_chart_price_source_unification): если Yahoo перезапишет
символ, который тянет и MT5, на графике снова появится шип на стыке двух
источников. Поэтому здесь стоит замок — см. _blocked_by_broker().

Использование:
  python3 yfinance_pull.py --gaps               # то, чего у брокера нет (режим таймера)
  python3 yfinance_pull.py --symbol USDRUB
  python3 yfinance_pull.py --symbol EURUSD --force   # осознанно поверх брокера
  python3 yfinance_pull.py --days 365

Ключ не требуется.

Код выхода: 0 — все запрошенные символы загружены; 1 — хотя бы один не
загрузился или загружать было нечего. Молчаливого «ничего не сделал, но всё
хорошо» здесь быть не должно (SPEC_supervision_2026-08-26 §5).
"""
import sqlite3, sys, time, argparse, logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

try:
    import yfinance as yf
except ImportError:
    print("Установите: pip install yfinance", file=sys.stderr)
    sys.exit(1)

_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

# Символ считается «живым у брокера», если его бар _PROBE_TF не старше этого.
# Выходные влезают с запасом: пятница вечер → понедельник утро ≈ 60 ч.
_BROKER_FRESH_SEC = 72 * 3600

# Таймфрейм-свидетель: его пишет только mt5_bridge_pull. Сам yfinance_pull
# умеет ровно '1d', поэтому по '1d' отличить бар брокера от собственного
# нельзя — см. подробности в _blocked_by_broker().
_PROBE_TF = "1h"

log = logging.getLogger("yfinance_pull")


def _broker_symbols() -> set[str]:
    """Наши ключи, которые тянет mt5_bridge_pull. Импорт мягкий: недоступный
    mt5_config не должен ронять загрузчик — но и молчать об этом нельзя,
    иначе замок исчезнет незаметно."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from mt5_config import bars_pull_map
        return set(bars_pull_map().keys())
    except Exception as e:                                   # pragma: no cover
        log.warning("не смог прочитать карту MT5 (%s) — защита от перезаписи "
                    "брокерских баров ОТКЛЮЧЕНА", e)
        return set()


def _blocked_by_broker(cur, our_key: str, broker_keys: set[str]) -> bool:
    """🔴 Замок против возврата бага 20.08.

    Раньше ниже стоял безусловный `DELETE FROM price_bars WHERE symbol=? AND
    tf='1d'` и следом заливка 90 дней. На EURUSD это стирало 8,6 лет суточной
    истории и подменяло цену брокера ценой Yahoo: один запуск «догрузчика»
    ронял и глубину, и единство источника. Теперь символ, который брокер
    реально котирует, не трогается вовсе. Снять — только --force.

    🔴 Свежесть меряется по _PROBE_TF, а НЕ по '1d'. Первая версия замка
    смотрела на суточный бар — и запирала сама себя: стоило yfinance закрыть
    дыру, как свежий суточный бар делал символ «брокерским», и следующий
    прогон эту же дыру уже не обновлял. Дыра тихо протухала — ровно тот класс
    отказа, ради которого всё это и затевалось (поймано на первом же
    автоматическом прогоне таймера 26.08).

    _PROBE_TF пишет ТОЛЬКО mt5_bridge_pull; yfinance_pull не умеет ничего,
    кроме суточных. Поэтому свежий бар этого ТФ — доказательство, что символ
    ведёт брокер, а не мы сами."""
    if our_key not in broker_keys:
        return False
    row = cur.execute("SELECT MAX(ts) FROM price_bars WHERE symbol=? AND tf=?",
                      (our_key, _PROBE_TF)).fetchone()
    if not row or not row[0]:
        return False
    age = datetime.now(timezone.utc).timestamp() - row[0]
    return age < _BROKER_FRESH_SEC


def load(days: int, symbols: list[str] | None = None, gaps: bool = False,
         force: bool = False) -> int:
    """Возвращает код выхода: 0 — всё запрошенное загружено, иначе 1."""
    con = sqlite3.connect(str(_DB), timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    cur = con.cursor()

    q = "SELECT our_key, yahoo FROM symbol_map WHERE yahoo IS NOT NULL"
    if symbols:
        placeholders = ",".join("?" * len(symbols))
        q += f" AND our_key IN ({placeholders})"
        rows = cur.execute(q, symbols).fetchall()
    else:
        rows = cur.execute(q).fetchall()

    if not rows:
        print("Нет символов в symbol_map с yahoo-ключом.", file=sys.stderr)
        con.close()
        return 1

    if not force:
        broker_keys = _broker_symbols()
        kept, skipped = [], []
        for our_key, yf_sym in rows:
            if _blocked_by_broker(cur, our_key, broker_keys):
                skipped.append(our_key)
            else:
                kept.append((our_key, yf_sym))
        if skipped:
            print("Пропущено (свежие бары брокера, перезапись смешала бы "
                  f"источники): {', '.join(sorted(skipped))}")
        rows = kept

    if not rows:
        # Для --gaps это ШТАТНО: брокер закрыл всё, дыр нет. Ругаться нечем.
        if gaps:
            print("Дыр нет — все символы закрыты брокером.")
            con.close()
            return 0
        print("Все запрошенные символы закрыты брокером — загружать нечего.",
              file=sys.stderr)
        con.close()
        return 1

    period = f"{days}d"
    ok = 0
    failed: list[str] = []
    for our_key, yf_sym in rows:
        print(f"  {our_key} ({yf_sym}) ...", end=" ", flush=True)
        try:
            ticker = yf.Ticker(yf_sym)
            hist = ticker.history(period=period, interval="1d", auto_adjust=True)
            if hist.empty:
                print("нет данных")
                failed.append(our_key)
                continue

            bars = []
            for dt, row in hist.iterrows():
                # нормализуем к 00:00:00 UTC того же дня (по дате DatetimeIndex)
                # это нужно для JOIN с econ_event_history по формуле ts/86400*86400
                try:
                    d = dt.date()
                    ts = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())
                except Exception:
                    ts = (int(dt.timestamp()) // 86400) * 86400
                o, h, l, c, v = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"]), float(row.get("Volume", 0) or 0)
                bars.append((our_key, "1d", ts, o, h, l, c, v))

            # 🔴 Чистим ТОЛЬКО перезагружаемое окно, а не всю историю символа.
            # INSERT OR REPLACE сам обновит совпадающие ts; DELETE нужен лишь
            # чтобы убрать бары внутри окна, которых в новом снимке Yahoo уже
            # нет (пересмотренная история). За пределами окна лежит глубина,
            # которой у Yahoo за period нет, — её не трогаем.
            cur.execute("DELETE FROM price_bars WHERE symbol=? AND tf='1d' AND ts>=?",
                        (our_key, min(b[2] for b in bars)))
            cur.executemany(
                "INSERT OR REPLACE INTO price_bars(symbol,tf,ts,o,h,l,c,v) VALUES(?,?,?,?,?,?,?,?)",
                bars
            )
            con.commit()
            print(f"{len(bars)} баров OK")
            ok += 1
        except Exception as e:
            print(f"ошибка: {e}")
            failed.append(our_key)
        time.sleep(0.5)  # вежливая пауза

    con.close()
    print(f"\nГотово: {ok}/{len(rows)} символов загружены.")
    if failed:
        # Громко и в stderr: под systemd именно эта строка попадёт в journal,
        # а ненулевой код не даст таймеру выглядеть успешным впустую.
        print("НЕ загружены: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Yahoo Finance → price_bars (дыры брокера)")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--symbol", nargs="+", help="Символы из symbol_map (наш ключ, напр. USDRUB USDKZT)")
    ap.add_argument("--gaps", action="store_true",
                    help="только то, чего брокер не даёт (режим таймера)")
    ap.add_argument("--force", action="store_true",
                    help="снять замок и писать поверх свежих баров брокера — "
                         "вернёт смешение источников на графике, только осознанно")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(f"Загрузка за {args.days} дней...")
    sys.exit(load(args.days, args.symbol, gaps=args.gaps, force=args.force))
