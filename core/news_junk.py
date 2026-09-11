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
    r"Investments|Wealth|Trust|Bancorp|Retirement System|Pension|"
    r"Fund Management|Asset Management)\b")
# 🔴 «Investments» только во множественном. В единственном это обычное слово, и
# «This ETF Would Have Increased Your Investment by 6x» уходило в мусор —
# поймано просмотром выдачи, а не процентом отсева.

# Выкуп своих акций — настоящая корпоративная новость той же формы: «Coca-Cola
# Europacific Partners buys back 258,500 shares». Юрлицо есть, действие с
# долей есть, и правило срабатывало. Разница в том, КТО покупает: компания
# свои, а не фонд чужие.
_ВЫКУП = re.compile(r"\b(buy(s|ing)?[- ]back|buyback|repurchas(e|es|ed|ing))\b", re.I)

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

# «Romano Brothers AND Company Has $11.52 Million Stock Position in NVIDIA».
# Названия управляющих компаний бесконечны, и гнаться за ними списком — путь в
# никуда: «AND Company» мимо _ЮРЛИЦО прошло. Но сама форма «имеет позицию на
# столько-то миллионов» встречается ТОЛЬКО в заметках об отчётности — обычная
# новость так не пишется. Поэтому здесь юрлицо не требуется.
_СУММА_ПОЗИЦИИ = re.compile(
    r"\b(has|holds|takes|makes)\b(?:[^.]|\.(?=\d)){0,40}\$[\d.,]+\s*"
    r"(million|billion|thousand)\b(?:[^.]|\.(?=\d)){0,40}"
    r"\b(stock\s+)?(position|holdings?|stake|investment)\b", re.I)

# Форма 4: продажа инсайдером. «NIKE (NYSE:NKE) COO Venkatesh Alagirisamy
# Sells 3,671 Shares of Stock» — тот же поток от того же генератора.
#
# 🔴 ОДНОГО «продал N акций» НЕДОСТАТОЧНО, и это не придирка. «Musk Sells
# 5,000,000 Shares of Tesla» — настоящая новость ровно той же формы. Поэтому
# рядом требуется должность: у заметки о форме 4 она есть всегда (director,
# COO, EVP), а у новости про известного человека её обычно нет. Случай
# «Mark Stevens Sells 622,239 Shares of NVIDIA» остаётся в ленте — при
# сомнении пропускаем, а не режем.
_ЧИСЛО_АКЦИЙ = re.compile(
    r"\b(sells?|sold|buys?|bought|purchase[sd]?|acquire[sd]?|boost[sd]?|"
    r"trim[s]?|cut[s]?|raise[sd]?|lower[sd]?|grow[s]?|reduce[sd]?)\b\s+"
    r"[\d,]{3,}\s+shares\s+of\b", re.I)
_ДОЛЖНОСТЬ = re.compile(
    r"\b(CEO|CFO|COO|CTO|CMO|EVP|SVP|VP|President|Chairman|Director|Officer|"
    r"Insider|Founder|Treasurer|Secretary)\b", re.I)


# «NVIDIA Corporation $NVDA is Hidden Cove Wealth Management LLC's 9th Largest
# Position». Ни действия с долей, ни суммы: глагол тут «is», а доля названа
# порядковым номером. Три такие карточки висели в ленте NVIDIA уже после того,
# как я отчитался о вычищенном мусоре — правило проверялось на выборке
# прошлых суток, а на экране была свежая.
_ПО_ВЕЛИЧИНЕ = re.compile(
    r"\b\d+(st|nd|rd|th)\s+(largest|biggest)\s+(position|holding|stake)\b", re.I)


def is_filing_note(title: str | None) -> bool:
    """Заголовок — поточная заметка о движении в отчётности фонда."""
    if not title:
        return False
    if _ВЫКУП.search(title):
        return False
    if _ПО_ВЕЛИЧИНЕ.search(title):
        return True
    if _СУММА_ПОЗИЦИИ.search(title):
        return True
    if _ЧИСЛО_АКЦИЙ.search(title) and _ДОЛЖНОСТЬ.search(title):
        return True
    if not _ЮРЛИЦО.search(title):
        return False
    return bool(_ДЕЙСТВИЕ.search(title) or _ДЕРЖАТЕЛЬ.search(title))
