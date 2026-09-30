"""Не съезжает ли соответствие «заголовок → перевод»."""
import sys

sys.path.insert(0, "/mnt/sbfdata/sbf-platform/market_intel")
from core import news_i18n

ТЕКСТЫ = [
    "Apple unveils foldable iPhone at September event",
    "Tesla Cybercab makes its debut in Japan",
    "Coinbase CEO calls the bottom in Bitcoin",
    "Gold slips as dollar strengthens ahead of Fed",
]
print("проверяю порядок ответа MyMemory на четырёх разных строках:\n")
переводы = news_i18n._mymemory(ТЕКСТЫ, "ru")
ошибок = 0
for ор, пер in zip(ТЕКСТЫ, переводы):
    # Грубая, но рабочая сверка: ключевое слово оригинала должно остаться.
    ключ = next((w for w in ("Apple", "Tesla", "Coinbase", "Gold") if w in ор), "")
    ожидаемо = {"Apple": ("Apple", "яблок"), "Tesla": ("Tesla", "Тесла"),
                "Coinbase": ("Coinbase",), "Gold": ("Gold", "золот", "Золот")}[ключ]
    ок = any(x.lower() in (пер or "").lower() for x in ожидаемо)
    ошибок += 0 if ок else 1
    print(f"  {'ок ' if ок else 'СЪЕХАЛ'} {ор[:46]}")
    print(f"        → {(пер or '—')[:62]}")
print(f"\nнесоответствий: {ошибок}")
