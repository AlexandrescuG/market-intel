"""core/news_junk.py — поточные заметки, которые не являются новостью.

ЗАЧЕМ. Лента по Tesla на 10 карточек из 30 состояла из заголовков вида
«Rational Advisors Inc. Sells 2,473 Shares of Tesla, Inc. $TSLA». Это
автоматические заметки о движениях в отчётности фондов: их генерируют пачками
по каждой подаче формы, они не сообщают ничего о компании и вытесняют
настоящие новости с первого экрана.

ПРИЗНАК — СОЧЕТАНИЕ, А НЕ ОДНО СЛОВО. Такая заметка всегда называет
юрлицо-держателя И действие с долей. По отдельности ни то, ни другое мусором
не является:

  «Berkshire Hathaway buys stake in Alphabet»  — действие есть, юрлица нет
  «BlackRock Inc. launches new ETF»            — юрлицо есть, действия нет
  «Rational Advisors Inc. Sells 2,473 Shares»  — есть и то, и другое

🔴 ЧЕГО ЗДЕСЬ НЕТ: запрета по источнику. Замер 11.09.2026 показал, что 171
заметка из 185 пришла от MarketBeat, и соблазн отсечь издание целиком велик —
но они публикуют и нормальные материалы, а такие же заметки приходят ещё от
трёх источников. Отсекаем форму, а не того, кто её написал.

ОСТАТОЧНЫЙ РИСК, названный честно. Правило отсечёт «Berkshire Hathaway Inc.
Boosts Stake in Apple» — а это настоящая новость. На живой выборке из 7556
новостей за двое суток таких не встретилось (все 185 помеченных оказались
заметками об отчётности), но случай возможен. Цена ошибки несимметрична: одна
пропущенная новость против десяти мусорных карточек на первом экране.
"""
from __future__ import annotations

import re

# Юрлицо-держатель: организационная форма или слово из названия управляющей
# компании. Точка после Inc обязательна не всегда — «inc.» и «Inc» оба живые.
_ЮРЛИЦО = re.compile(
    r"\b(LLC|L\.L\.C|LP|LLP|Inc\.?|Ltd\.?|Corp\.?|N\.A\.|"
    r"Advisors?|Advisers?|Capital|Management|Managers?|Partners?|Holdings|"
    r"Investments?|Wealth|Trust|Bancorp|Retirement System|Pension|"
    r"Fund Management|Asset Management)\b")

# Действие с долей: глагол плюс существительное про долю, не дальше сорока
# пяти знаков друг от друга — чтобы «sells» из одного предложения не
# склеивалось со «shares» из другого.
#
# 🔴 Точка разрешена внутри числа. Первая версия писала просто [^.], и
# «M Holdings Securities Inc. Has $6.26 Million Stake in Tesla» НЕ опознавалась:
# разделителем в сумме стоит точка, шаблон на ней обрывался. Замер при этом
# отрапортовал «0 заметок об отчётности» — а в списке они были видны глазами.
# Метрика соврала ровно там, где её писали; поймано просмотром выдачи, а не
# цифрой.
_ДЕЙСТВИЕ = re.compile(
    r"\b(purchase[sd]?|sell[s]?|sold|buy[s]?|bought|acquire[sd]?|boost[sd]?|"
    r"trim[s]?|raise[sd]?|lower[sd]?|cut[s]?|increase[sd]?|decrease[sd]?|"
    r"reduce[sd]?|grow[s]?|has|takes?|makes?)\b(?:[^.]|\.(?=\d)){0,45}\b"
    r"(shares?|stake|position|holdings?|investment)\b", re.I)

# Обратный порядок: «Netflix $NFLX Position Cut by Waverly Advisors LLC».
_ДЕРЖАТЕЛЬ = re.compile(
    r"\b(shares?|stake|position|holdings?)\b(?:[^.]|\.(?=\d)){0,30}\bby\b", re.I)


def is_filing_note(title: str | None) -> bool:
    """Заголовок — поточная заметка о движении в отчётности фонда."""
    if not title:
        return False
    if not _ЮРЛИЦО.search(title):
        return False
    return bool(_ДЕЙСТВИЕ.search(title) or _ДЕРЖАТЕЛЬ.search(title))
