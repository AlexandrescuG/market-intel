#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chapter_numbers_report.py — инвентаризация круглых долей и заглушек в главах курса.

Задача 1 из SPEC_REMOTE_CLAUDE_2026-09-30.md. Ищет «круглые» проценты
(…0% и …5%) в тексте глав — web/book/edu_book_*.html (каркас глав и тексты
глав 1–2) и web/edu/assets/chN.js (тексты глав 3–15, window.ChNContent),
отбрасывает CSS, комментарии кода и стили, группирует копии ru/ro/en одного
утверждения и размечает каждое по правилам ниже (разметка ручная, правила
лишь её фиксируют — чтобы отчёт пересобирался одинаково).

Запуск:  python3 tools/chapter_numbers_report.py   → docs/CHAPTER_PLACEHOLDERS_2026-09.md
Правки в главы скрипт НЕ вносит.
"""
from __future__ import annotations
import collections, glob, json, re, sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
ВЫХОД = КОРЕНЬ / "docs" / "CHAPTER_PLACEHOLDERS_2026-09.md"

ROUND=re.compile(r"(?<![\d.,#])(\d*[05])\s?%")
CSSPROP=re.compile(r"""([A-Za-z-]+)\s*:\s*[^,;}]*$""")
CSSKEYS=set("""top left right bottom width height maxWidth minWidth maxHeight minHeight borderRadius transform background backgroundPosition backgroundSize transformOrigin margin padding flexBasis offset stopColor clipPath inset gridTemplateColumns lineHeight fontSize opacity x y cx cy r x1 x2 y1 y2 d points letterSpacing objectPosition backgroundImage mask maskImage filter""".split())
CYR=re.compile(r"[А-Яа-яЁё]"); RO=re.compile(r"[ăâîșțşţĂÂÎȘȚ]|\b(și|în|pentru|care|este|sau|din|cu|la|nu)\b")
def scan(files):
    out=[]
    for f in files:
        ch=int(re.search(r'(\d+)\.(?:html|js)$',f).group(1))
        raw=open(f).read()
        s=re.sub(r"<style.*?</style>",lambda m:"\n"*m.group(0).count("\n"),raw,flags=re.S)
        s=re.sub(r"/\*.*?\*/",lambda m:"\n"*m.group(0).count("\n"),s,flags=re.S)
        lines=s.split("\n")
        for i,l in enumerate(lines,1):
            code=re.sub(r"(^|[^:\"'`])//.*$",r"\1",l)   # drop // comments (not URLs)
            for m in ROUND.finditer(code):
                pre=code[:m.start()]
                # css: property: value context, or gradient/translate/rgba nearby, or pure "N%" literal
                win=code[max(0,m.start()-40):m.end()+15]
                mp=re.search(r"([A-Za-z-]+)\s*[:=]\s*[\"'`{]?[^\"'`,;}]*$",pre)
                if mp and not re.search(r"(?<![A-Za-z-])"+re.escape(mp.group(1))+r"\s*[:=]",pre): mp=None
                if mp and (mp.group(1) in CSSKEYS or mp.group(1).lower() in {k.lower() for k in CSSKEYS} or re.fullmatch(r"(border|margin|padding|background|transform|flex|grid|font|mask|transition)\w*|text(Align|Shadow|Indent|Decoration|Transform)\w*",mp.group(1))):
                    continue
                if re.search(r"gradient|translate|rgba?\(|calc\(|scale\(|ellipse|@keyframes|\d%\s*\{|^\s*\d+%\s*\{",win,re.I): continue
                if re.search(r"""["'`]\s*-?\d+(\.\d+)?%\s*["'`]""",win) and not re.search(r"[A-Za-zА-Яа-я]{3,}",re.sub(r"\w+\s*:","",win)): continue
                lang="ru" if CYR.search(code) else ("ro" if RO.search(code) else ("en" if re.search(r"[A-Za-z]{3,}",code) else "?"))
                ctx=re.sub(r"\s+"," ",code[max(0,m.start()-55):m.end()+30]).strip()
                out.append(dict(ch=ch,line=i,num=m.group(0).replace(" ",""),lang=lang,ctx=ctx))
    
    return out


def groups(d,src):
    g=collections.OrderedDict()
    for o in d:
        m=list(re.finditer(r"(\w+)\s*:\s*(?:\([^)]*\)\s*=>\s*)?[\"'`\[{]",o["ctx"]))
        key=m[-1].group(1) if m else "?"
        g.setdefault((o["ch"],key,o["num"],o["ctx"] if key=="?" and o["lang"]=="ru" else ""),[]).append(o)
    # merge "?" groups that are same ch/num across langs by order
    out=[]
    for (ch,key,num,_),v in g.items():
        ru=[x for x in v if x["lang"]=="ru"]
        out.append(dict(src=src,ch=ch,key=key,num=num,occ=v,ctx=(ru or v)[0]["ctx"],hasru=bool(ru)))
    return out


CHIPS=re.compile(r"^(faTag|taTag|stickyFA|stickyTA|heroChipFA|heroChipTA|chipFA|chipTA|fundamentalChip|technicalChip|interactiveChip)$")
BOOK="web/book/edu_book_{}.html"; JS="web/edu/assets/ch{}.js"
R=[]  # (pattern on ctx, ch or None, kind, replace, prio)
def rule(pat,kind,repl,prio,ch=None): R.append((re.compile(pat),ch,kind,repl,prio))
NA="не утверждение (CSS/интерфейс)"
# --- не утверждения
rule(r"linear-gradient|position:\"relative\"",NA,"—","—")
rule(r"\{total\}% / 100%|Распределите 100%|Allocate 100%|Distribuiți 100%|Сумма всегда 100%|sum is always 100%|Suma e mereu 100%|întotdeauna 100%",NA,"— (сумма слайдеров)","—")
rule(r'top:"50%"',NA,"—","—")
rule(r"random baseline\"\}: 50%|опорная линия случа",NA,"—","—")
# --- гл.2
rule(r"платит 5%\+|pays 5%\+|plătește 5%\+|платят 5%\+|pay 5%\+|plătesc acum 5%\+","факт о рынке без источника","Дать дату и источник: доходность 3-мес. T-bill 2023–2024 (FRED DTB3 — в core/fred.py пока не подключена) или ставка ФРС (FRED DFF — есть в core/fred.py:KEY_SERIES)","P1",2)
rule(r"fedRange|QE \(|— Нейтральн|— Neutr|— Жёстк|— Tight|— Restrictiv","иллюстрация (не оговорено)","Подписать как шкалу симулятора, а не как факт: «5% — нейтральная» не совпадает с оценками нейтральной ставки ФРС. Либо взять долгосрочную медиану FOMC с датой и ссылкой — в репозитории её нет","P1",2)
rule(r"70% ВВП|70% of US GDP|70% din PIB","факт о рынке без источника","Уточнить по BEA (NIPA Table 1.1.5, доля PCE в ВВП) с годом; в репозитории источника нет","P1",2)
rule(r"рухнут на 50%|crash 50%|prăbușesc garantat cu 50%","иллюстрация","Не менять: заведомо неверный вариант ответа в тесте","P2",2)
# --- гл.3 book
rule(r"\+7–15%/|\+7–15%","факт о рынке без источника","Посчитать долгосрочную доходность S&P 500 по истории ^GSPC (tools/edu_build/_yahoo.py умеет тянуть) и указать период","P1",3)
rule(r"-50% за кризис|drop -50%|scădea cu -50%","можно посчитать","web/data/edu_capsules/crisis_2008.json → stats.SPX.peak_to_trough_pct = −56.3","P1",3)
rule(r"-70% до \+200%|-70% to \+200%|-70% la \+200%","факт о рынке без источника","Посчитать по BTC: web/data/edu_capsules/crash_lab_presets.json (btc) / ohlc_BTC_D1.json; дать период","P1",3)
rule(r"риск 10% на сделку|10% risk per trade|risc de 10% per","можно посчитать","Симуляция в web/book/edu_book_3.html (стр. ~1025–1029, фиксированный seed) — сослаться на неё в тексте","P2",3)
rule(r"менее чем 50% верных|less than 50% correct|mai puțin de 50% intrări","иллюстрация","Верно при R/R ≥ 1:2 (порог 33%); можно добавить формулу","P2",3)
rule(r"просел на -56%|dropped -56%|scăzut -56%","можно посчитать","−56%: crisis_2008.json → stats.SPX.peak_to_trough_pct (−56.3). −25% для смешанного портфеля: посчитать по crash_lab_presets.json (пресет 2008) при долях из текста","P1",3)
# --- гл.3 js
rule(r"упали на 20%, облигации — на 14%|Акции −20%, облигации −14%, крипта −64%|stocks fell 20%|Stocks −20%|scăzut cu 20%|Acțiuni −20%","можно посчитать","SPX −20.0 — edu_scenes/ch3_2022_multi.json → meta.year_change_pct.SPX. Облигации −14% и BTC −64% — crash_lab_presets.json (пресет inflation_2022: bonds, btc)","P1",3)
rule(r"\+7\.6%|\+20% от январского|\+20% from the January|\+20% față de minimul","можно посчитать","DXY 2022: ch3_2022_multi.json → meta.year_change_pct.DXY = 7.6, meta.dxy_peak_gain_pct = 20.4 (совпадает)","P1",3)
rule(r"2400%","можно посчитать","edu_scenes/ch3_sol_no_stop.json → meta.drawdown_from_entry_pct = −96.3 (от цены входа $220.24). Из −96.3% следует +2600% (1/0.037−1); +2400% соответствует ровно −96.0%. Текст говорит «от пика», данные — «от входа»: выровнять базу и пересчитать","P0",3)
rule(r"Просадки до −50% и глубже|Drawdowns of −50%|Scăderi de −50%","можно посчитать","crisis_2008.json (SPX −56.3%) — привязать к конкретному кризису","P1",3)
rule(r"закрыть год в \+25%|close the year \+25%|închide anul la \+25%","факт о рынке без источника","Назвать актив и год; посчитать по ohlc_*_D1.json","P1",3)
rule(r"от −70% до сотен|from −70% to hundreds|de la −70% la sute","факт о рынке без источника","Посчитать по BTC (crash_lab_presets.json / ohlc_BTC_D1.json) с периодом","P1",3)
rule(r"5%\+ к 2023|5%\+ by 2023|5%\+ până în 2023","факт о рынке без источника","FRED DFF (есть в core/fred.py) — ставка ФРС 5.25–5.50% с июля 2023; сослаться","P1",3)
rule(r"60/40|60% акций|60% stocks|60% acțiuni","иллюстрация","Не менять: определение классического портфеля","P2",3)
rule(r"Золото \+25% за окно|Gold \+25%|Aur \+25%|33% \(в моменте\)|33% \(at the|облигации \+3\.5%","можно посчитать","crash_lab_presets.json — соответствующий пресет (gold, bonds, oil); сверить значения и окно","P1",3)
rule(r"−10% лечится|−10% is cured|−10% se recuperează|−10% needs|−50% требует|−90% — \+900%","иллюстрация","Не менять: арифметика асимметрии (1/(1−x)−1), верна","P2",3)
rule(r"Профи держат просадку|Pros keep|Profesioniștii","выдумка","Нет источника. Убрать «профи держат» или переписать как правило риска без ссылки на «профи»","P1",3)
rule(r"при винрейте 50% серия из 5|at a 50% win rate|la o rată de câștig de 50%","можно посчитать","Вероятность серии из 5 убытков за N сделок — формула или симуляция; указать N","P2",3)
rule(r"После просадки −50%|After a −50%|După o scădere de −50%|вернуться после −50%|back after −50%|reveni după −50%","иллюстрация","Не менять: вопрос теста, арифметика верна","P2",3)
rule(r"\(\$198\)|\(\$154\)|\(\$110\)","иллюстрация","Не менять: варианты ответа сценария","P2",3)
# --- 5..14 js
rule(r"±15%","можно посчитать","Совпадает с кодом: web/book/edu_book_5.html:914 (trueRange*0.15). Не менять","P2",5)
rule(r"95% ДИ|95% CI|95% IÎ|IÎ 95%|ДИ 95","можно посчитать","tools/edu_build/surprise_reaction.py (wilson, z=1.96) → edu_stats/surprise_reaction.json — уровень 95% совпадает с кодом","P2",6)
rule(r"95% времени|95% of the time|95% din timp","иллюстрация","Верно для нормального распределения (±2σ ≈ 95%); не менять","P2",6)
rule(r"Опорная линия случайности — 50%|baseline is 50%|опорной линии 50%|опорная линия — 50%|базовой линии 50%|против базовой линии 50%|baseline of 50%|against a 50% baseline|linia de bază 50%|linie de referință 50%|referință — 50%|de referință 50%|50% baseline","можно посчитать","tools/edu_build/pattern_reality.py → edu_stats/pattern_reality.json (46.8–51.3% против 50%). ⚠ Гл. 9 требует сравнивать с базовой долей инструмента, «а не с 50%» — методики гл. 7/10 и гл. 9 расходятся; решить, какая верна, и выровнять текст","P0",None)
rule(r"а не 50%: если инструмент|not 50%: if the instrument|nu cu 50%: dacă|не с 50%|not with 50%|nu cu 50%|not against 50%|а не с 50%","иллюстрация","Методическое правило, не число; 40%/42% — пример с «если». См. расхождение с гл. 7/10","P2",None)
rule(r"просадку в 20%, нужно заработать 25%|drawdown of 20%|scădere de 20%|Чтобы отыграть просадку 50%|recover a 50%|recupera o scădere de 50%|вырасти на 100%|grow by 100%|crească cu 100%","иллюстрация","Не менять: арифметика верна","P2",10)
rule(r"«35–40%»|\"35–40%\"|35–40%","факт о рынке без источника","Назвать, кто «часто цитирует» 35–40%, и дать источник ESMA/брокера; иначе убрать","P1",11)
rule(r"около 50% на середину 2020|around 50% in the mid-2020|≈50% на середину|≈50% in the mid|aproximativ 50%|≈50%","факт о рынке без источника","Доля HFT в объёме рынка акций США — дать 1–2 источника с годом; в репозитории нет","P1",11)
rule(r"по удаче окажется 60%|by luck alone|din noroc","можно посчитать","Биномиальная вероятность P(X≥6|10, 0.5)=37.7% — калькулятор главы 12 уже считает; сослаться","P2",12)
rule(r"работает, 60%|works, 60%|funcționează, 60%|6 из 10|6 out of 10|6 din 10|p=50%","иллюстрация","Не менять: учебный пример","P2",12)
rule(r"Готовый пример: система|Ready-made example|Exemplu gata","иллюстрация","Не менять: явно обозначен как пример","P2",12)
rule(r"уверенностью 95%|95% confidence|95% увер|încredere 95%|Мощность теста принята за 80%|power is taken as 80%|Puterea testului","иллюстрация","Статистические конвенции (α=5%, мощность 80%), оговорены; не менять","P2",12)
rule(r"Меньше 30%|Less than 30%|Mai puțin de 30%|30–60%|60–85%|Больше 85%|More than 85%|Peste 85%","иллюстрация","Не менять: варианты ответа","P2",13)
rule(r"75% прибыльных — достижимая|75% winners is achievable|75% profitabile","выдумка","Нет измерения, что 75% «достижимо» для скальпинга. Либо убрать, либо сослаться на измерение (tools/edu_build/breakeven_cost.py считает порог, а не достижимость)","P0",14)
rule(r"снизить издержку на 30%|cut the cost by 30%|reduce costul cu 30%","иллюстрация","Не менять: сценарий калькулятора","P2",14)
rule(r"15/20 = 75%|порог безубыточности выше 75%|breakeven threshold above 75%|peste 75%|text: \"50%\"|text: \"75%\"|>75%</div>","можно посчитать","Арифметика: стоп/(цель+стоп)=15/20=75% (edu_book_14.html L228 — число вшито в вёрстку, лучше считать из цели/стопа)","P2",14)
rule(r"80%\. Что это доказывает|80%\. What does|80%\. Ce dovedește","иллюстрация","Не менять: вопрос теста","P2",14)

rule(r'text: "\d+%"',"иллюстрация","Не менять: варианты ответа теста","P2",3)
rule(r'text: "\d+%"',"иллюстрация","Не менять: варианты ответа теста","P2",10)
rule(r"close the year at \+25%","факт о рынке без источника","Назвать актив и год; посчитать по ohlc_*_D1.json","P1",3)
rule(r"adds up to 100%",NA,"—","—")
rule(r"requires \+900%|requires \+100%|you need \+100%|need a 100% gain|De la un capital scăzut cu 50%|заработать 100%|recuperezi|câștigi 100%|câștigi 25%","иллюстрация","Не менять: арифметика асимметрии, верна","P2")
rule(r"Linia de referință a întâmplării — 50%","можно посчитать","tools/edu_build/pattern_reality.py → edu_stats/pattern_reality.json. ⚠ расхождение методики с гл. 9 (см. строку RU)","P0")
rule(r"nu 50%: dacă|în 40% din cazuri","иллюстрация","Методическое правило, не число; см. расхождение с гл. 7/10","P2")
rule(r"converg în jurul a 50%","факт о рынке без источника","Доля HFT — дать источник с годом","P1")
rule(r"by pure luck","можно посчитать","Биномиальная вероятность — калькулятор главы 12","P2")
rule(r"A worked example","иллюстрация","Не менять: явно обозначен как пример","P2")
rule(r"încredere|încr\.\)","иллюстрация","Статистическая конвенция (95%), не менять","P2")
rule(r"breakeven threshold is above 75%","можно посчитать","Арифметика 15/20 = 75%","P2")

def classify(g):
    if CHIPS.match(g["key"]):
        return ("иллюстрация (не оговорено)","Редакционная доля «фундаментал/техника» в главе — не измерение. Подписать «состав главы» или убрать проценты","P2")
    for pat,ch,kind,repl,prio in R:
        if (ch is None or ch==g["ch"]) and pat.search(g["ctx"]): return (kind,repl,prio)
    for pat,ch,kind,repl,prio in R:
        if ch is None and pat.search(g["ctx"]): return (kind,repl,prio)
    return None


# ── Заглушки и «условно»: поиск по слову, вердикт — по контексту ──────────
ЗАГЛУШКИ = re.compile(r"TODO|placeholder|заглушк|условно|примерные данные", re.I)
ВЕРДИКТ_ЗАГЛУШКИ = [
    (r"ЗАГЛУШКА СНЯТА|ЗДЕСЬ БЫЛА ЗАГЛУШКА", "комментарий в коде: заглушка уже снята", "—"),
    (r"pending заглушка", "Ступень 8 помечена в коде как «pending заглушка», но рендерит тексты ladderStep8 (limitParagraph1/2, factualityBody, disclosureLine) из web/edu/assets/ch13.js — проверить, что эти тексты финальные, и снять пометку", "P1"),
    (r"placeholder: cs\.placeholder", "атрибут placeholder поля ввода, не заглушка", "—"),
    (r"рендерятся УСЛОВНО", "комментарий в коде: «условно» = условный рендер", "—"),
    (r"условное имя", "обычное слово в тексте («условное имя для часов»)", "—"),
    (r"metodologia", "ложное срабатывание: «todo» внутри румынского «metodologia»", "—"),
]
ОБЕЩАНИЕ = re.compile(r"опубликуем вместе с инструментом сравнения|will publish .{0,40}comparison tool|vom publica", re.I)


def заглушки(files):
    строки = []
    for f in files:
        s = Path(f).read_text(encoding="utf-8")
        for m in ЗАГЛУШКИ.finditer(s):
            ln = s.count("\n", 0, m.start()) + 1
            ctx = re.sub(r"\s+", " ", s[max(0, m.start() - 60):m.end() + 50])
            вердикт, приоритет = "проверить вручную", "P1"
            for pat, v, p in ВЕРДИКТ_ЗАГЛУШКИ:
                if re.search(pat, ctx, re.I):
                    вердикт, приоритет = v, p
                    break
            строки.append((Path(f).name, ln, m.group(0), ctx, вердикт, приоритет))
    return строки


def md_escape(t: str) -> str:
    return t.replace("|", "\\|").replace("\n", " ")


def main() -> int:
    book = sorted(glob.glob(str(КОРЕНЬ / "web/book/edu_book_*.html")), key=lambda f: int(re.search(r"(\d+)\.html$", f).group(1)))
    js = sorted(glob.glob(str(КОРЕНЬ / "web/edu/assets/ch[0-9]*.js")), key=lambda f: int(re.search(r"(\d+)\.js$", f).group(1)))
    G = groups(scan(book), "book") + groups(scan(js), "js")
    rows, unk = [], []
    for g in G:
        c = classify(g)
        if not c:
            unk.append(g)
            continue
        locs = collections.defaultdict(list)
        for o in g["occ"]:
            locs[o["lang"]].append(o["line"])
        f = (BOOK if g["src"] == "book" else JS).format(g["ch"])
        rows.append(dict(g, kind=c[0], repl=c[1], prio=c[2], file=f, locs=dict(locs), n=len(g["occ"])))

    всего = sum(r["n"] for r in rows) + sum(len(u["occ"]) for u in unk)
    по_виду = collections.Counter((r["kind"], r["prio"]) for r in rows)
    по_вхожд = collections.Counter()
    for r in rows:
        по_вхожд[(r["kind"], r["prio"])] += r["n"]
    порядок = {"P0": 0, "P1": 1, "P2": 2, "—": 3}
    rows.sort(key=lambda r: (порядок.get(r["prio"], 9), r["ch"], r["src"], min(min(v) for v in r["locs"].values())))
    zag = заглушки(book)

    L = []
    L.append("# Инвентаризация чисел в главах курса — 30.09.2026\n")
    L.append("Задача 1 из `SPEC_REMOTE_CLAUDE_2026-09-30.md`. Отчёт собран скриптом "
             "`tools/chapter_numbers_report.py` по коду репозитория (ветка main на 30.09). "
             "На живом сайте не смотрел; что показывает браузер — надо смотреть на машине. "
             "Правки в главы НЕ вносились.\n")
    L.append("## Методика и расхождение с замером спеки (242)\n")
    L.append("- Ищу «круглые» доли: число, оканчивающееся на 0 или 5, со знаком `%` "
             "(`(?<![\\d.,#])\\d*[05]\\s?%`).")
    L.append("- Отбрасываю `<style>`, комментарии кода (`/* */`, `//`) и CSS-значения в JSX "
             "(`top:\"50%\"`, `translate(-50%)`, градиенты). Отброшенное проверено выборочно: "
             "это вёрстка и комментарии разработчиков, а не текст для читателя.")
    L.append("- **Главное отличие от замера спеки:** в `edu_book_*.html` лежат каркас глав и тексты "
             "только глав 1–2 (плюс подписи-чипы). Основной текст глав 3–15 — в "
             "`web/edu/assets/chN.js` (`window.ChNContent`), замер спеки его не охватывал. "
             "Я включил оба источника.")
    L.append("- Каждая глава хранит текст на трёх языках подряд, поэтому одно утверждение даёт "
             "до трёх вхождений. В таблице — **одна строка на утверждение**, в колонке «где» — "
             "номера строк всех его копий (ru/ro/en). Так каждое вхождение покрыто строкой. "
             "Язык копии определяется эвристикой (кириллица → ru, румынские диакритики и частые слова → ro, "
             "иначе en), поэтому румынский текст без диакритик иногда помечен как en, а копии одного "
             "утверждения изредка попадают в две строки — по смыслу это одна позиция.")
    n_book = sum(r["n"] for r in rows if r["src"] == "book")
    n_js = sum(r["n"] for r in rows if r["src"] == "js")
    L.append(f"- Итого вхождений в тексте: **{всего}** (`edu_book_*.html` — {n_book}, `chN.js` — {n_js}); "
             f"утверждений (строк таблицы): **{len(rows)}**; заглушек/«условно» по словам — {len(zag)}. "
             "Число 234 из спеки я воспроизвести не смог: грубый счёт по html без отсева CSS "
             "даёт 392, с отсевом стилей и комментариев — 209. Вероятно, локальный замер "
             "отсекал CSS иначе. На машине стоит прогнать скрипт и сверить.\n")
    L.append("## Сводка\n")
    L.append("| вид | приоритет | утверждений | вхождений |")
    L.append("|---|---|---|---|")
    for (k, p), n in sorted(по_виду.items(), key=lambda x: (порядок.get(x[0][1], 9), -x[1])):
        L.append(f"| {k} | {p} | {n} | {по_вхожд[(k, p)]} |")
    L.append("")
    L.append("**Виды:** `выдумка` — число ничем не подтверждено и выглядит как утверждение; "
             "`факт о рынке без источника` — похоже на правду, но в репозитории источника нет "
             "(в терминах спеки это тоже «выдумка», выделено отдельно, потому что лечится ссылкой, "
             "а не удалением); `факт партнёра` — есть в `web/data/partners.json` (таких круглых "
             "долей в главах не нашлось); `можно посчитать` — источник в репозитории назван; "
             "`иллюстрация` — условное число, честное по смыслу (варианты теста, арифметика, "
             "явно помеченный пример); `иллюстрация (не оговорено)` — условное число без пометки; "
             "`не утверждение` — интерфейс/CSS, прошедший фильтр.\n")
    L.append("## Главное — P0\n")
    for r in rows:
        if r["prio"] == "P0" and "ru" in r["locs"]:
            L.append(f"- **Гл. {r['ch']}** «{md_escape(r['ctx'][-80:].strip())}» — {md_escape(r['repl'])}")
    L.append("")
    L.append("## Таблица\n")
    L.append("| глава | цитата (≤80 знаков) | вид | чем заменить | приоритет | где (файл: строки ru / ro / en) |")
    L.append("|---|---|---|---|---|---|")
    for r in rows:
        q = r["ctx"]
        num = r["num"]
        i = q.find(num)
        if i >= 0:
            q = q[max(0, i - 45):i + len(num) + 30]
        q = md_escape(q.strip())[:80]
        где = "; ".join(f"{яз} {', '.join(map(str, sorted(v)))}" for яз, v in sorted(r["locs"].items()))
        L.append(f"| {r['ch']} | {q} | {r['kind']} | {md_escape(r['repl'])} | {r['prio']} | `{r['file']}`: {где} |")
    L.append("")
    L.append("## Заглушки, TODO, «условно» (поиск по словам в `edu_book_*.html`)\n")
    L.append("| файл | строка | слово | контекст | вывод | приоритет |")
    L.append("|---|---|---|---|---|---|")
    for f, ln, w, ctx, v, p in zag:
        L.append(f"| {f} | {ln} | {w} | {md_escape(ctx)[:110]} | {v} | {p} |")
    L.append("")
    L.append("Дополнительно, не по слову «заглушка»: `edu_book_11.html` (~стр. 559) обещает "
             "«точную таблицу по нашим партнёрам опубликуем вместе с инструментом сравнения». "
             "Это обещание будущих данных внутри главы — P1: либо опубликовать таблицу, либо убрать обещание.\n")
    if unk:
        L.append(f"## Не размечено ({len(unk)})\n")
        for u in unk:
            L.append(f"- гл. {u['ch']} {u['num']}: {md_escape(u['ctx'][-90:])}")
    L.append("## Как проверить локально\n")
    L.append("```bash\npython3 tools/chapter_numbers_report.py      # пересобирает этот файл\n"
             "git diff --stat docs/CHAPTER_PLACEHOLDERS_2026-09.md   # пусто = отчёт воспроизводится\n```\n"
             "Выборочная сверка: открыть файл и строку из колонки «где» и убедиться, что цитата там.")
    ВЫХОД.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"вхождений {всего}, утверждений {len(rows)}, не размечено {len(unk)}, заглушек {len(zag)} → {ВЫХОД.relative_to(КОРЕНЬ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
