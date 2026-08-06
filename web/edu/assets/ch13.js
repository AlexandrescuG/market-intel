/**
 * Chapter 13 "Анатомия Свинга и Пирамидинг" content — SPEC_edu_level13_swing_pyramiding.md.
 * RU is the master text (spec §3, close to verbatim); RO/EN are translations
 * in the same register as ch1-12.
 * window.Ch13Content = {ru, ro, en}.
 *
 * [РЕШЕНИЕ ПО §0.2] Спека прямо требует решения: публиковать ли реальный
 * стейтмент счёта и цифры результата (вариант A, полное раскрытие с
 * просадкой и убыточными периодами) или снять их полностью (вариант B).
 * Спека сама рекомендует B и объясняет, почему это не потеря — принято
 * вариант B: ни одной цифры результата (денег, %, винрейта) нигде в главе.
 * Причина, помимо рекомендации спеки: у нас физически нет реального
 * стейтмента счёта для публикации (это внешний артефакт, не то, что можно
 * сгенерировать в автономном проходе), а частичная публикация прямо
 * запрещена самой спекой ("либо всё, либо ничего").
 *
 * [ДОПУЩЕНИЕ] TradeAnatomy — разбор одной сделки написан как качественная
 * история (контекст, вопросы до входа, рассуждение о стопе, ошибка) БЕЗ
 * единого точного уровня цены/пункта — строже, чем формальное требование
 * спеки "где стоял стоп и почему именно там — рассуждение, а не число"
 * (спека прямо запрещает публиковать число для стопа; для входа/цели тоже
 * не даём чисел, той же цепью рассуждений: глава явно названа спекой самой
 * тяжёлой по комплаенсу во всём курсе, и любое точное число рядом с
 * разбором реальной сделки риском повторяет удалённую "систему" §0.1).
 *
 * [ПРОВЕРЕНО ВЫЧИСЛЕНИЕМ, СПЕКА НЕ УТОЧНЯЛА] §3.4 раскрытие просило два
 * РАЗНЫХ процента "доли пройденного пути" после 1 и 3 доборов (drawdown_1,
 * drawdown_3). Прямой расчёт показывает: при РАВНОМ шаге и равном размере
 * добора точка невозврата всегда откатывается РОВНО на половину пройденного
 * пути — это тождество, а не совпадение (среднее арифметической прогрессии
 * всегда на полпути между первым и последним членом), и НЕ меняется с
 * числом доборов. Меняется абсолютное количество пунктов и денег под
 * риском (20 -> 60 пунктов в примере на 4 лота с шагом 40). Текст ниже
 * использует проверенную формулировку (в пунктах, не в %) вместо
 * недостоверной. Это тот же класс находки, что ema_reality.py в главе 8:
 * посчитали заранее заявленную величину и получили честный, а не
 * подогнанный под ожидание спеки результат. Второй режим калькулятора
 * (уменьшающийся добор) — там доля ДЕЙСТВИТЕЛЬНО меняется, и это показано
 * живым расчётом, а не текстом.
 *
 * [ДОПУЩЕНИЕ] §3.5 breakeven_cost.json: highlight-ячейка X=0.5 ATR
 * ("перевод после прохождения половины пути к цели Y=2.0 ATR") даёт
 * zero_pct=91.0% при n=117541 (пул по всем инструментам H4+D1, реальный
 * расчёт tools/edu_build/breakeven_cost.py). Монотонность подтверждена
 * численно по всем 4 значениям Y — чем раньше переводишь (меньше X), тем
 * выше доля закрытых в ноль, без единого исключения.
 *
 * [ДОПУЩЕНИЕ] Ступень 8 (разбор журнала живым аналитиком) НЕ построена как
 * рабочий интерактив — качественно другая причина, чем отложенная
 * партнёрская инфраструктура глав 6-11: спека сама предупреждает (§8 Этап6),
 * что "форма без работающего процесса за ней хуже отсутствия формы", а
 * реальный процесс (аналитики, читающие 50 сделок, реальный SLA) — это
 * операционная мощность, которую нельзя ни построить, ни симулировать в
 * автономном проходе. Текст ступени (разворот §3.7 "тебе рано" ->
 * констатация условий) включён как контент, интерактивная заявка — нет.
 */
window.Ch13Content = {
  ru: {
    coldStart: {
      tag: "ОТЫГРАТЬ",
      ask: "Задай величину просадки. Сколько нужно заработать, чтобы вернуться к исходной сумме?",
      drawdownLabel: "Просадка",
      revealTemplate: "−{{dd}}% → нужно +{{need}}%, чтобы вернуться к исходной сумме. Асимметрия растёт быстрее, чем кажется: не линейно, а по формуле dd/(1−dd).",
      bridge: "Отсюда и весь смысл этой главы: не в том, как далеко зайти в прибыли, а в том, чего стоит вернуться из убытка.",
    },
    antiMyth: {
      tag: "АНТИ-МИФ",
      title: "Два мифа, и они противоположны",
      body1: "Первый, уже знакомый: «чем чаще торгуешь, тем больше зарабатываешь». Опровергается арифметикой издержек из главы 11: каждая сделка стоит фиксированных денег, независимо от исхода.",
      body2: "Второй, и он предмет этой главы: «добор к прибыльной позиции — это безопасно, ведь я рискую уже заработанным». Это самая дорогая ошибка мышления в трейдинге. Пока позиция в плюсе, деньги ощущаются как «не совсем мои» — но на счёте нет разницы между заработанным и внесённым: и то и другое одинаково исчезает. А объём после трёх доборов может быть вчетверо больше исходного — то есть именно тогда, когда кажется, что риск снизился, он вырос кратно.",
      body3: "Правда: добор — это открытие новой позиции по худшей цене, а не бесплатное продолжение старой. Считать его надо по правилам главы 3, как любую другую позицию, а не по ощущению.",
    },
    voiceSbf: {
      tag: "ГОЛОС SBF",
      body: "Риск перестаёт считаться ровно в тот момент, когда сделка выходит в плюс: вопрос «сколько потеряю при развороте» задаётся при входе и почему-то не задаётся при доборе. Работает одно — после каждого добора считать среднюю цену позиции и следить за одним числом: где она станет убыточной. Если это число подобралось близко к текущей цене, доборов больше нет, каким бы красивым ни был тренд.",
    },
    priceOfNotKnowing: {
      tag: "ЦЕНА НЕЗНАНИЯ",
      title: "Считаем при читателе, без выдуманных процентов",
      intro: "Вход одним лотом. Цена прошла в нужную сторону 40 пунктов, добор ещё одним лотом. Ещё 40 — третий лот. Ещё 40 — четвёртый.",
      body2: "Средняя цена входа теперь на 60 пунктов выше первого входа. Позиция вчетверо больше исходной.",
      keyLabel: "Ключевое число",
      keyBody: "При откате на 60 пунктов от максимума позиция становится убыточной, хотя цена всё ещё на 60 пунктов выше первого входа. Ты в плюсе по направлению и в минусе по деньгам одновременно.",
      body3: "Без доборов та же ситуация выглядела бы так: цена на 60 пунктов выше входа, позиция в плюсе на 60 пунктов одним лотом. Тот же рынок, то же движение, противоположный результат.",
      body4: "Честная вторая половина: из этого не следует, что добирать нельзя. Следует, что у добора есть цена, она считается заранее и её надо знать до нажатия кнопки, а не после. Именно это считает калькулятор ниже.",
    },
    whySwing: {
      tag: "ПОЧЕМУ СВИНГ — АРИФМЕТИКА, А НЕ ВКУС",
      body1: "Издержка на сделку фиксирована и известна: спред плюс комиссия, ты их замерял в главе 11. Значит, суммарная издержка пропорциональна числу сделок, а не их качеству.",
      body2: (scalp, swing) => `Отсюда следствие, которое не про предпочтения: чем меньше средний ход, на который ты рассчитываешь, тем большую его долю съедает издержка. Цель в 15 пунктов при издержке в 1 пункт отдаёт ${scalp}% результата; цель в 150 пунктов при той же издержке — ${swing}%.`,
      body3: "Это единственный честный аргумент в пользу более длинных горизонтов, и он не про то, что свинг «лучше». Он про то, что при коротком горизонте требования к точности выше — ту же издержку надо отбить меньшим движением.",
      body4: "Обратная сторона называется сразу: длинная позиция живёт через события календаря (глава 6), через ролловеры и свопы (глава 5), и её риск за ночь не контролируется. Выбор горизонта — это выбор набора проблем, а не избавление от них.",
      openOnChart: "Открыть Золото на графике →",
    },
    tradeAnatomy: {
      tag: "АНАТОМИЯ ОДНОЙ СДЕЛКИ",
      title: "Разбор одной реальной сделки как последовательности решений",
      disclaimer: "Это разбор одной сделки одного человека на одном инструменте в конкретной обстановке. Не шаблон, не стратегия и не рекомендация. Ценность здесь не в уровнях — они не повторятся, — а в порядке вопросов, которые задавались до нажатия кнопки. Порядок повторяем, уровни нет.",
      contextLabel: "Контекст на момент входа",
      contextText: "Золото, дневной график. Календарь дня — тихий, крупных публикаций не было ни в азиатскую, ни в европейскую сессию. Обе средние (глава 8) указывали в одну сторону, цена выше обеих. Ничего необычного — обычный день с ясной, но не редкой картиной.",
      questionsLabel: "Вопросы, заданные до входа",
      questions: [
        "Что именно опровергнет эту идею? — Не «если пойдёт против», а конкретное условие, при котором картина считается неверной.",
        "Где это условие физически находится на графике? — Не круглое число и не «подальше на всякий случай», а структурная точка: место, ниже которого предыдущая логика движения перестаёт работать.",
        "Сколько лотов при этом стопе укладывается в правило риска главы 3? — Считается от точки опровержения, а не наоборот.",
        "Что в календаре на весь ожидаемый срок жизни сделки, а не только на сегодня? — Проверено на несколько дней вперёд, не только на момент нажатия кнопки.",
      ],
      stopLabel: "Где стоял стоп и почему",
      stopText: "Стоп стоял не на «сколько не жалко потерять», а на структурной точке — там, где сама идея входа перестаёт быть верной. Если бы цена дошла туда, это означало бы не «не повезло», а «гипотеза о движении неверна» — и сделку правильно закрыть именно по этой причине, а не потому что стоп сработал сам.",
      timelineLabel: "Что происходило дальше",
      timeline: [
        "Первые часы — движение в ожидаемую сторону, без сюрпризов. Решение: ничего не менять, план не пересматривается по одному хорошему часу.",
        "Ближе к вечеру — ускорение, цена уверенно прошла контрольные отметки, обозначенные ещё до входа как условия для рассмотрения добора. Решение о доборе принято по заранее описанному условию, а не по ощущению «хочется ещё».",
        "Ночью — движение продолжилось, азиатская сессия тонкая (глава 5), и здесь начинается ошибка.",
      ],
      mistakeLabel: "Что оказалось ошибкой",
      mistakeText: "Ошибка — не сама сделка и не сам добор. Ошибка в том, что решение о последнем доборе было принято без повторной проверки календаря на оставшийся срок жизни позиции. Календарь по итогу оказался пуст в моменте входа, но не через двенадцать часов — а этого никто не перепроверил, потому что позиция уже была в крупном плюсе и «зачем, и так всё хорошо». Именно этот пропуск стал условием, при котором обычное ночное движение против позиции превратилось в проблему: объём к тому моменту был кратно больше исходного, а свежих данных о рисках на оставшееся время никто не смотрел.",
      lessonLabel: "Что из этого следует",
      lessonText: "Не «не добирай». Следует: список вопросов, который проверяется перед первым входом, должен проверяться перед КАЖДЫМ добором заново, а не считаться закрытым один раз. Позиция за время жизни меняет размер, а список проверок — если его не повторять — не меняется вместе с ней.",
    },
    pyramid: {
      tag: "АРИФМЕТИКА ДОБОРА — ЯДРО ГЛАВЫ",
      step1Label: "ОБЪЯСНИ",
      step1Body: "Добор — это новая позиция по новой цене. Значит, у совокупной позиции появляется средняя цена входа, и она хуже первоначальной. Сейчас посчитаем, насколько именно и что из этого следует.",
      step2Label: "ПОКАЖИ",
      step2Intro: "Готовый пример: один лот на входе, затем три добора по одному лоту каждый шаг 40 пунктов.",
      avgLabel: "Средняя цена входа (пунктов выше первого входа)",
      pnrLabel: "Точка невозврата (откат от пика, пунктов)",
      step2Note: "Точка невозврата откатывается ровно на половину пройденного пути — это не совпадение, а прямое следствие арифметики среднего для равных шагов. Абсолютное число пунктов под риском при этом растёт с каждым добором.",
      step3Label: "ДАЙ СДЕЛАТЬ",
      step3Intro: "Задай свои параметры добора.",
      firstSizeLabel: "Размер первого входа (лотов)",
      stepPtsLabel: "Шаг добора, пунктов",
      addSizeLabel: "Размер каждого добора (лотов, режим «равные»)",
      nAddsLabel: "Число доборов",
      modeLabel: "Режим",
      modeEqual: "Равные доборы",
      modeDecreasing: "Уменьшающиеся доборы",
      resultAvgLabel: "Средняя цена входа",
      resultPnrPtsLabel: "Точка невозврата, пунктов от пика",
      resultPnrPctLabel: "Это % пройденного пути",
      resultRiskLabel: "Суммарный риск, во сколько раз больше первой позиции",
      reveal: {
        title: "Три вещи, которые видно на этих числах",
        p1: "Первое: абсолютное расстояние в пунктах до точки невозврата растёт с каждым добором — 20 пунктов после одного добора, 60 после трёх в примере выше. Ты не «рискуешь заработанным» — ты сокращаешь запас прочности в реальных пунктах и деньгах.",
        p2: "Второе: суммарный риск растёт быстрее, чем кажется на глаз. При равных доборах объём растёт линейно — но каждая единица объёма несёт свою долю риска, и они складываются.",
        p3: "Третье, и оно решает: все добавления были сделаны в состоянии выигрыша. Это единственные решения в трейдинге, которые принимаются, когда всё хорошо, — и потому единственные, где не срабатывает естественная осторожность.",
        conclusion: "Вывод не «не добирай». Вывод: посчитай точку невозврата до первого добора и решай по ней, а не по тому, как выглядит тренд.",
      },
      compliance: "Это калькулятор последствий, а не торговая методика. Мы не рекомендуем ни добирать, ни воздерживаться — мы показываем арифметику решения.",
      openOnChart: "Открыть Золото на графике →",
    },
    breakeven: {
      tag: "ЧЕГО СТОИТ СТОП В БЕЗУБЫТОК — НАШЕ ИЗМЕРЕНИЕ",
      preamble: "Правило «перевёл стоп в точку входа — риск ноль» звучит безупречно и потому почти никогда не проверяется. Мы проверили две вещи.",
      firstLabel: "Первое — «риск ноль» неверно буквально",
      firstText: "Остаётся проскальзывание, разрыв на открытии недели, разрыв на публикации данных, расширение спреда. Плановый убыток нулевой; фактический может быть любым. Это не измерение, это механика, разобранная в главах 4 и 6.",
      secondLabel: "Второе — измеримое и более интересное",
      secondText: "Как часто перевод в безубыток закрывает сделку, которая бы сработала. Метод, зафиксированный до подсчёта: берём все случаи, когда цена прошла от условной точки входа X пунктов (в долях ATR) в нужную сторону; смотрим, как часто она возвращается к точке входа раньше, чем проходит цель Y. Перебор по сетке X и Y, по инструментам и таймфреймам H4/D1 — свинг живёт не в часах.",
      verdictLabel: (x, cost, n) => `При переводе после прохождения ${x} пройденного пути к цели, доля сделок, закрытых в ноль вместо достижения цели, составила ${cost}% при n = ${n.toLocaleString("ru-RU")}.`,
      point2: "Чем раньше переводишь, тем дороже. Зависимость монотонна на всех проверенных дистанциях цели — без единого исключения.",
      point3: "Компромисс, а не улучшение. Перевод в безубыток снижает средний убыток и снижает долю дошедших до цели одновременно. Что из этого важнее — зависит от соотношения цели к стопу в конкретной системе; универсального ответа нет, и мы его не даём.",
      honestPlate: "Измерено: движение цены по нашей истории, без учёта спреда и проскальзывания — то есть реальная доля закрытых в ноль ВЫШЕ нашей оценки. Не измерено: контекст входа. Мы считали механическое правило, потому что именно так его и применяют.",
      csvBtn: "Скачать наши числа (CSV)",
      tableXLabel: "X (доля ATR)", tableYLabel: "Y (доля ATR)", tableZeroLabel: "Закрыто в ноль", tableNLabel: "n",
      openOnChart: "Открыть Золото на графике →",
    },
    tradePlan: {
      tag: "ПЛАН СДЕЛКИ — ЧТО ЗАПИСЫВАЕТСЯ ДО",
      intro: "Пять строк. Всё, что не записано до, будет придумано после — и совпадёт с тем, что произошло. Механизм разбирала глава 9.",
      entryLabel: "Условие входа — проверяемое, а не «выглядит хорошо»",
      stopLabel: "Где стоп и почему именно там — уровень, при котором исходная идея опровергнута",
      exitLabel: "Где выход — и что делать, если цена дошла до половины пути и остановилась",
      addLabel: "Добираешь ли, и если да — точка невозврата после каждого добора, посчитанная заранее",
      calendarLabel: "Что в календаре на срок жизни позиции",
      saveBtn: "Сохранить план",
      savedNote: "План сохранён в журнал.",
    },
    ladderStep8: {
      tag: "СТУПЕНЬ 8 — РАЗБОР ЖУРНАЛА АНАЛИТИКОМ",
      limitParagraph1: "Ты только что читал разбор чужой сделки — с вопросами, которые задавались до входа, и с ошибкой, которая обнаружилась после. Логично захотеть такой же по своим.",
      limitParagraph2: "Автоматически этого не сделать. Журнал считает твои числа и показывает их (глава 10), но числа не отвечают на вопрос «почему ты так решил» — на него отвечает человек, который прочитает подряд пятьдесят твоих сделок и увидит то, чего не видно изнутри.",
      factualityTitle: "Как звучит вывод разбора",
      factualityBody: "Не «тебе рано торговать на реальные деньги» — это персональная рекомендация о финансовом решении, которую образовательный проект делать не вправе. Вместо этого — констатация фактов: «По твоим записям четыре условия, которые глава 14 ставит перед реальным счётом, выполнены так: сделок — 34 из 50; недель журнала — 3 из 4; система записана — да; арифметика риска посчитана — нет. Два условия из четырёх пока не выполнены.» Прямой ответ без уговоров и без совета.",
      disclosureLine: "Разбор бесплатный и ни к чему не обязывает. Зачем он нам: человек, прошедший разбор до первого реального счёта, доходит до конца курса заметно чаще. Нам это выгодно, и мы предпочитаем сказать это сами.",
      pendingNote: "Форма заявки на разбор ещё не открыта. Показать её раньше, чем за ней стоит реальная очередь и реальный срок ответа, было бы хуже, чем не показывать вовсе — обещание, которое некому исполнить, стоит дороже, чем честное «пока рано».",
    },
    quiz: [
      { id: "q1", section: "secPyramid", prompt: "Ты добрал трижды по мере роста. Что произошло с точкой, в которой позиция станет убыточной?",
        options: [{ text: "Осталась на месте", correct: false }, { text: "Приблизилась к текущей цене", correct: true }, { text: "Ушла дальше", correct: false }],
        feedbackCorrect: "Верно. Каждый добор двигает точку невозврата ближе к текущей цене в абсолютных пунктах.",
        feedbackWrong: "Не совсем. Средняя цена входа растёт с каждым добором, а значит и порог, при котором позиция становится убыточной, приближается." },
      { id: "q2", section: "secBreakeven", prompt: "Стоп переведён в точку входа. Риск равен нулю?",
        options: [{ text: "Да", correct: false }, { text: "Нет — остаются проскальзывание, разрывы и расширение спреда; нулевым стал плановый убыток", correct: true }, { text: "Только на демо", correct: false }],
        feedbackCorrect: "Верно. Плановый убыток нулевой, фактический может быть любым.",
        feedbackWrong: "Не совсем. «Риск ноль» описывает план, а не гарантию исполнения по этой цене." },
      { id: "q3", section: "secWhySwing", prompt: "Почему при короткой цели требования к точности выше?",
        options: [{ text: "Фиксированная издержка съедает большую долю малого движения", correct: true }, { text: "Рынок ночью тише", correct: false }, { text: "Комиссия выше на коротких сделках", correct: false }],
        feedbackCorrect: "Верно. Та же издержка в пунктах — большая доля маленькой цели.",
        feedbackWrong: "Не совсем. Дело в том, какую долю цели съедает одна и та же фиксированная издержка." },
      { id: "q4", section: "secTradeAnatomy", prompt: "Правила сделки, восстановленные после её закрытия, …",
        options: [{ text: "Не хуже записанных до", correct: false }, { text: "Всегда совпадут с тем, что было сделано — память подстраивается", correct: true }, { text: "Точнее, потому что известен результат", correct: false }],
        feedbackCorrect: "Верно. Именно поэтому план сделки записывается до, а не восстанавливается после.",
        feedbackWrong: "Не совсем. Память задним числом подстраивает объяснение под то, что уже произошло (глава 9)." },
    ],
    predict: {
      tag: "ПРЕДИКТ НЕДЕЛИ",
      question: "Как думаешь, при переводе стопа в безубыток после прохождения половины пути к цели — какая доля сделок закроется в ноль вместо достижения цели?",
      options: ["Меньше 30%", "30–60%", "60–85%", "Больше 85%"],
      answerNote: (cost, correct) => `${correct ? "Точно." : "Мимо."} По нашим измерениям (H4/D1, все инструменты): ${cost}%.`,
      xpNote: "Про измеримую величину — правильного варианта в моральном смысле нет, есть посчитанный.",
    },
    cliffhanger: {
      tag: "ДАЛЬШЕ → ГЛАВА 14",
      body: "Осталась одна тема и один разговор.\n\nТема — скальпинг: сделки, живущие минуты. Мы разберём его честно, и главный вывод будет не про технику. Скальпинг — это глава про издержки: при цели в десять пунктов спред и комиссия из накладного расхода превращаются в основную статью, и всё решает арифметика, которую ты уже умеешь считать с главы 11.\n\nА разговор — про реальный счёт. Мы дошли до места, где его логично обсудить, и обсудим прямо: что меняется, когда деньги настоящие, чего это стоит и почему у нас перед этой дверью стоят четыре условия, а не кнопка. Три из четырёх ты, скорее всего, уже выполнил.",
    },
    sources: {
      tag: "ИСТОЧНИКИ ГЛАВЫ",
      list: [
        "Арифметика средней цены позиции и точки безубытка — прямой расчёт, приводится в главе полностью.",
        "Kahneman D., Tversky A. — эффект «денег казино» (house money effect): склонность рисковать сильнее выигранными средствами.",
        "Thaler R., Johnson E. (1990) — эмпирика того же эффекта.",
        "Механика проскальзывания и разрывов — главы 4 и 6 курса, с источниками там же.",
      ],
      ownTemplate: "SBF Company SRL. Доля сделок, закрывшихся в ноль вместо цели при переводе стопа в безубыток. Данные: 16 инструментов, таймфреймы H4/D1, сетка {{x_n}}×{{y_n}} значений в долях ATR (период {{atr_period}}), горизонт {{lookahead}} баров. Метод: перевод в безубыток при прохождении доли X пути до цели Y; без учёта спреда и проскальзывания — реальная доля выше расчётной. Пересчёт от {{built}}.",
      csvLabel: "Скачать данные (CSV)",
      checked: "Проверено на 27.07.2026.",
    },
  },

  en: {
    coldStart: {
      tag: "CLAW BACK",
      ask: "Set the size of a drawdown. How much do you need to earn back to return to the starting amount?",
      drawdownLabel: "Drawdown",
      revealTemplate: "−{{dd}}% → you need +{{need}}% to get back to even. The asymmetry grows faster than it looks: not linearly, but by dd/(1−dd).",
      bridge: "That asymmetry is what this whole chapter is about: not how far you ride a gain, but what it costs to come back from a loss.",
    },
    antiMyth: {
      tag: "ANTI-MYTH",
      title: "Two myths, and they're opposites",
      body1: "The first, already familiar: \"trade more often, earn more.\" Disproved by the cost arithmetic from chapter 11: every trade costs fixed money, regardless of outcome.",
      body2: "The second is this chapter's subject: \"adding to a winning position is safe — I'm risking money I already made.\" This is the most expensive thinking error in trading. While a position is green, that money feels like \"not quite mine\" — but an account doesn't distinguish between money earned and money deposited: both disappear the same way. And size after three adds can be four times the original — meaning right when risk feels lower, it multiplied.",
      body3: "The truth: adding is opening a new position at a worse price, not a free continuation of the old one. It should be sized by chapter 3's rules, like any other position, not by feel.",
    },
    voiceSbf: {
      tag: "SBF VOICE",
      body: "Risk stops being counted the exact moment a trade turns green: the question \"how much do I lose if this reverses\" gets asked on entry and somehow doesn't get asked on the add. What works is one thing — after every add, compute the position's average price and watch a single number: where it turns unprofitable. If that number has crept close to the current price, there are no more adds, no matter how good the trend looks.",
    },
    priceOfNotKnowing: {
      tag: "THE PRICE OF NOT KNOWING",
      title: "Computed in front of you, no invented percentages",
      intro: "One lot on entry. Price moves 40 points the right way, add a second lot. Another 40 — a third lot. Another 40 — a fourth.",
      body2: "The average entry price is now 60 points above the first entry. The position is four times the original size.",
      keyLabel: "The key number",
      keyBody: "A 60-point pullback from the peak turns the position unprofitable — even though price is still 60 points above the first entry. You're up on direction and down on money at the same time.",
      body3: "Without the adds, the same situation would look like this: price 60 points above entry, position up 60 points on one lot. Same market, same move, opposite result.",
      body4: "The honest other half: this doesn't mean you can't add. It means adding has a price, computed in advance, and you need to know it before pressing the button, not after. That's exactly what the calculator below computes.",
    },
    whySwing: {
      tag: "WHY SWING — ARITHMETIC, NOT TASTE",
      body1: "The cost per trade is fixed and known: spread plus commission, which you measured in chapter 11. So total cost is proportional to the number of trades, not their quality.",
      body2: (scalp, swing) => `The consequence isn't about preference: the smaller the average move you're targeting, the larger the share cost eats out of it. A 15-point target at a 1-point cost gives up ${scalp}% of the result; a 150-point target at the same cost — ${swing}%.`,
      body3: "This is the only honest argument for longer horizons, and it isn't that swing is \"better.\" It's that a short horizon demands higher precision — the same cost has to be recovered by a smaller move.",
      body4: "The flip side gets named right away: a long position lives through calendar events (chapter 6), through rollovers and swaps (chapter 5), and its overnight risk isn't under your control. Choosing a horizon is choosing a set of problems, not escaping them.",
      openOnChart: "Open Gold on the chart →",
    },
    tradeAnatomy: {
      tag: "ANATOMY OF ONE TRADE",
      title: "One real trade broken down as a sequence of decisions",
      disclaimer: "This is a breakdown of one trade by one person on one instrument in a specific setting. Not a template, not a strategy, not a recommendation. The value here isn't the levels — they won't repeat — it's the order of questions asked before pressing the button. The order repeats; the levels don't.",
      contextLabel: "Context at the moment of entry",
      contextText: "Gold, daily chart. The day's calendar was quiet — no major releases in either the Asian or European session. Both moving averages (chapter 8) pointed the same way, price above both. Nothing unusual — an ordinary day with a clear, but not rare, picture.",
      questionsLabel: "Questions asked before entry",
      questions: [
        "What exactly would disprove this idea? — Not \"if it goes against me,\" but a specific condition under which the thesis is considered wrong.",
        "Where does that condition physically sit on the chart? — Not a round number, not \"a bit further just in case,\" but a structural point: the place below which the prior move's logic stops holding.",
        "How many lots at that stop fit chapter 3's risk rule? — Sized from the invalidation point, not the other way around.",
        "What's on the calendar for the whole expected life of the trade, not just today? — Checked several days ahead, not only at the moment of pressing the button.",
      ],
      stopLabel: "Where the stop sat and why",
      stopText: "The stop wasn't placed at \"how much I don't mind losing\" — it sat at a structural point, where the entry thesis itself stops being true. If price had reached it, that wouldn't mean \"bad luck,\" it would mean \"the move hypothesis is wrong\" — and the correct reason to close is exactly that, not that a stop mechanically triggered.",
      timelineLabel: "What happened next",
      timeline: [
        "The first hours — movement in the expected direction, no surprises. Decision: change nothing; a plan doesn't get revised on one good hour.",
        "Toward evening — acceleration, price confidently cleared checkpoints marked out before entry as conditions worth considering an add on. The add decision was made against a pre-written condition, not a feeling of \"want more.\"",
        "Overnight — the move continued, the Asian session is thin (chapter 5), and this is where the mistake begins.",
      ],
      mistakeLabel: "What turned out to be the mistake",
      mistakeText: "The mistake wasn't the trade or the add itself. The mistake was making the decision on the last add without re-checking the calendar for the position's remaining expected life. The calendar had indeed been empty at the moment of entry, but not twelve hours later — and nobody re-checked, because the position was already deeply green and \"why bother, it's all going fine.\" That one skipped check is exactly what turned an ordinary overnight move against the position into a real problem: by then size was several times the original, and nobody had looked at fresh risk data for the time still remaining.",
      lessonLabel: "What follows from this",
      lessonText: "Not \"don't add.\" What follows: the checklist run before the first entry has to be re-run before EVERY add, not treated as settled once. A position changes size over its life, and a checklist — if it isn't repeated — doesn't change along with it.",
    },
    pyramid: {
      tag: "THE ARITHMETIC OF ADDING — THE CHAPTER'S CORE",
      step1Label: "EXPLAIN",
      step1Body: "Adding is a new position at a new price. So the combined position gets an average entry price, and it's worse than the original. Let's compute exactly how much worse, and what follows from it.",
      step2Label: "SHOW",
      step2Intro: "A worked example: one lot on entry, then three adds of one lot each, 40 points apart.",
      avgLabel: "Average entry price (points above first entry)",
      pnrLabel: "Point of no return (pullback from peak, points)",
      step2Note: "The point of no return pulls back exactly half of the distance traveled — not a coincidence, a direct consequence of averaging arithmetic for equal steps. The absolute number of points at risk still grows with every add.",
      step3Label: "LET YOU TRY",
      step3Intro: "Set your own add parameters.",
      firstSizeLabel: "First entry size (lots)",
      stepPtsLabel: "Add step, points",
      addSizeLabel: "Each add's size (lots, \"equal\" mode)",
      nAddsLabel: "Number of adds",
      modeLabel: "Mode",
      modeEqual: "Equal adds",
      modeDecreasing: "Decreasing adds",
      resultAvgLabel: "Average entry price",
      resultPnrPtsLabel: "Point of no return, points from peak",
      resultPnrPctLabel: "% of distance traveled",
      resultRiskLabel: "Total risk, × times the first position",
      reveal: {
        title: "Three things visible in these numbers",
        p1: "First: the absolute distance in points to the point of no return grows with every add — 20 points after one add, 60 after three in the example above. You're not \"risking money already made\" — you're shrinking your margin of safety in real points and money.",
        p2: "Second: total risk grows faster than it looks. With equal adds, size grows linearly — but every unit of size carries its own share of risk, and they add up.",
        p3: "Third, and this settles it: every add was made while winning. These are the only decisions in trading made when everything is going well — and so the only ones where natural caution doesn't kick in.",
        conclusion: "The conclusion isn't \"don't add.\" It's: compute the point of no return before the first add, and decide by that, not by how good the trend looks.",
      },
      compliance: "This is a consequences calculator, not a trading method. We don't recommend adding or holding off — we show the arithmetic of the decision.",
      openOnChart: "Open Gold on the chart →",
    },
    breakeven: {
      tag: "WHAT A BREAKEVEN STOP ACTUALLY COSTS — OUR MEASUREMENT",
      preamble: "The rule \"moved the stop to entry — risk is zero\" sounds flawless, and that's exactly why it almost never gets checked. We checked two things.",
      firstLabel: "First — \"risk zero\" is literally wrong",
      firstText: "Slippage remains, weekend gaps remain, data-release gaps remain (chapter 6), spread widening remains. The planned loss is zero; the actual one can be anything. This isn't a measurement, it's mechanics already covered in chapters 4 and 6.",
      secondLabel: "Second — measurable, and more interesting",
      secondText: "How often moving to breakeven closes a trade that would have worked. Method fixed before counting: take every case where price moved X points (in ATR fractions) from a hypothetical entry in the favorable direction; check how often it returns to entry before reaching target Y. Swept over a grid of X and Y, across instruments and H4/D1 timeframes — swing lives in days, not hours.",
      verdictLabel: (x, cost, n) => `Moving to breakeven after covering ${x} of the distance to target, the share of trades closed at zero instead of reaching target was ${cost}%, at n = ${n.toLocaleString("en-US")}.`,
      point2: "The earlier you move it, the more it costs. The relationship is monotonic across every target distance checked — without a single exception.",
      point3: "A trade-off, not an improvement. Moving to breakeven lowers the average loss and lowers the share of trades reaching target at the same time. Which matters more depends on the target-to-stop ratio in a specific system; there's no universal answer, and we don't give one.",
      honestPlate: "Measured: price movement in our history, without spread or slippage — meaning the real share closed at zero is HIGHER than our estimate. Not measured: entry context. We tested the mechanical rule because that's exactly how it's applied.",
      csvBtn: "Download our numbers (CSV)",
      tableXLabel: "X (ATR fraction)", tableYLabel: "Y (ATR fraction)", tableZeroLabel: "Closed at zero", tableNLabel: "n",
      openOnChart: "Open Gold on the chart →",
    },
    tradePlan: {
      tag: "THE TRADE PLAN — WHAT GETS WRITTEN DOWN BEFORE",
      intro: "Five lines. Anything not written down before will be invented after — and it'll match what happened. The mechanism was covered in chapter 9.",
      entryLabel: "Entry condition — checkable, not \"looks good\"",
      stopLabel: "Where the stop is and why — the level at which the original idea is disproven",
      exitLabel: "Where the exit is — and what to do if price gets halfway and stalls",
      addLabel: "Whether you'll add, and if so — the point of no return after each add, computed in advance",
      calendarLabel: "What's on the calendar for the position's expected life",
      saveBtn: "Save the plan",
      savedNote: "Plan saved to the journal.",
    },
    ladderStep8: {
      tag: "STEP 8 — A LIVE ANALYST'S JOURNAL REVIEW",
      limitParagraph1: "You just read a breakdown of someone else's trade — with questions asked before entry, and a mistake found after. It's natural to want the same for your own.",
      limitParagraph2: "That can't happen automatically. The journal computes your numbers and shows them (chapter 10), but numbers don't answer \"why did you decide that\" — a person answers that, someone who reads fifty of your trades in a row and sees what isn't visible from the inside.",
      factualityTitle: "How the review's conclusion is worded",
      factualityBody: "Not \"you're not ready to trade real money\" — that's a personal recommendation about a financial decision, which an educational project has no business making. Instead — a statement of fact: \"By your records, the four conditions chapter 14 sets before a real account stand as: trades — 34 of 50; journal weeks — 3 of 4; system written down — yes; risk arithmetic computed — no. Two of four conditions aren't met yet.\" A direct answer, no persuasion, no advice.",
      disclosureLine: "The review is free and commits you to nothing. Why we offer it: someone who goes through a review before their first real account finishes the course noticeably more often. That benefits us, and we'd rather say so ourselves.",
      pendingNote: "The review request form isn't open yet. Showing it before a real queue and a real response time stand behind it would be worse than not showing it at all — a promise nobody can keep costs more than an honest \"not yet.\"",
    },
    quiz: [
      { id: "q1", section: "secPyramid", prompt: "You added three times as price rose. What happened to the point where the position turns unprofitable?",
        options: [{ text: "Stayed put", correct: false }, { text: "Moved closer to the current price", correct: true }, { text: "Moved further away", correct: false }],
        feedbackCorrect: "Correct. Every add moves the point of no return closer to the current price, in absolute points.",
        feedbackWrong: "Not quite. Average entry price rises with every add, so the threshold where the position turns unprofitable moves closer too." },
      { id: "q2", section: "secBreakeven", prompt: "The stop is moved to entry. Is risk zero?",
        options: [{ text: "Yes", correct: false }, { text: "No — slippage, gaps, and spread widening remain; the planned loss became zero", correct: true }, { text: "Only on demo", correct: false }],
        feedbackCorrect: "Correct. The planned loss is zero; the actual one can be anything.",
        feedbackWrong: "Not quite. \"Risk zero\" describes the plan, not a guarantee of execution at that price." },
      { id: "q3", section: "secWhySwing", prompt: "Why does a short target demand higher precision?",
        options: [{ text: "A fixed cost eats a larger share of a small move", correct: true }, { text: "The market is quieter at night", correct: false }, { text: "Commission is higher on short trades", correct: false }],
        feedbackCorrect: "Correct. The same cost in points is a bigger bite out of a small target.",
        feedbackWrong: "Not quite. It's about what share of the target the same fixed cost eats." },
      { id: "q4", section: "secTradeAnatomy", prompt: "Trade rules reconstructed after a trade closes …",
        options: [{ text: "Are no worse than rules written before", correct: false }, { text: "Will always match what was actually done — memory adapts", correct: true }, { text: "Are more accurate, since the outcome is known", correct: false }],
        feedbackCorrect: "Correct. That's exactly why a trade plan is written before, not reconstructed after.",
        feedbackWrong: "Not quite. Hindsight memory adapts the explanation to fit what already happened (chapter 9)." },
    ],
    predict: {
      tag: "PREDICTION OF THE WEEK",
      question: "What share of trades do you think close at zero instead of reaching target, when the stop moves to breakeven after covering half the distance to target?",
      options: ["Under 30%", "30–60%", "60–85%", "Over 85%"],
      answerNote: (cost, correct) => `${correct ? "Correct." : "Missed."} By our measurements (H4/D1, all instruments): ${cost}%.`,
      xpNote: "About a measurable quantity — there's no morally correct answer, only a computed one.",
    },
    cliffhanger: {
      tag: "NEXT → CHAPTER 14",
      body: "One topic and one conversation remain.\n\nThe topic is scalping: trades that live for minutes. We'll cover it honestly, and the main takeaway won't be about technique. Scalping is a chapter about costs: at a ten-point target, spread and commission stop being overhead and become the main line item, and everything comes down to arithmetic you already know how to do from chapter 11.\n\nThe conversation is about a real account. We've reached the point where it makes sense to discuss it, and we will, directly: what changes when the money is real, what it costs, and why there are four conditions in front of that door instead of a button. You've probably already met three of the four.",
    },
    sources: {
      tag: "CHAPTER SOURCES",
      list: [
        "The arithmetic of average entry price and the breakeven point — direct calculation, shown in full in the chapter.",
        "Kahneman D., Tversky A. — the 'house money effect': the tendency to take bigger risks with money already won.",
        "Thaler R., Johnson E. (1990) — empirical evidence for the same effect.",
        "The mechanics of slippage and gaps — chapters 4 and 6 of the course, sourced there.",
      ],
      ownTemplate: "SBF Company SRL. Share of trades that closed at zero instead of the target after moving the stop to breakeven. Data: 16 instruments, H4/D1 timeframes, a {{x_n}}×{{y_n}} grid of values in ATR fractions (period {{atr_period}}), a {{lookahead}}-bar horizon. Method: stop moved to breakeven once price crosses fraction X of the distance to a target Y; excludes spread and slippage — the real share is higher than this. Recomputed as of {{built}}.",
      csvLabel: "Download the data (CSV)",
      checked: "Checked as of 2026-07-27.",
    },
  },

  ro: {
    coldStart: {
      tag: "SĂ RECUPEREZI",
      ask: "Alege mărimea unei pierderi. Cât trebuie să câștigi ca să revii la suma inițială?",
      drawdownLabel: "Pierdere",
      revealTemplate: "−{{dd}}% → ai nevoie de +{{need}}% ca să revii la zero. Asimetria crește mai repede decât pare: nu liniar, ci după formula dd/(1−dd).",
      bridge: "În asta stă tot sensul acestui capitol: nu cât de departe mergi pe profit, ci cât costă să revii dintr-o pierdere.",
    },
    antiMyth: {
      tag: "ANTI-MIT",
      title: "Două mituri, și sunt opuse",
      body1: "Primul, deja cunoscut: „cu cât tranzacționezi mai des, cu atât câștigi mai mult”. Infirmat de aritmetica costurilor din capitolul 11: fiecare tranzacție costă bani ficși, indiferent de rezultat.",
      body2: "Al doilea e subiectul acestui capitol: „a adăuga la o poziție profitabilă e sigur, doar risc bani deja câștigați”. Aceasta e cea mai costisitoare eroare de gândire din trading. Cât timp poziția e pe plus, banii se simt „nu chiar ai mei” — dar contul nu face diferența între bani câștigați și bani depuși: amândoi dispar la fel. Iar volumul după trei adăugări poate fi de patru ori mai mare decât cel inițial — adică exact atunci când pare că riscul a scăzut, el a crescut de mai multe ori.",
      body3: "Adevărul: adăugarea înseamnă deschiderea unei poziții noi la un preț mai prost, nu continuarea gratuită a celei vechi. Trebuie dimensionată după regulile capitolului 3, ca orice altă poziție, nu după senzație.",
    },
    voiceSbf: {
      tag: "VOCEA SBF",
      body: "Riscul încetează să fie calculat exact în momentul în care o tranzacție intră pe plus: întrebarea „cât pierd dacă se întoarce” se pune la intrare și cumva nu se mai pune la adăugare. Funcționează un singur lucru — după fiecare adăugare, calculează prețul mediu al poziției și urmărește un singur număr: unde devine ea neprofitabilă. Dacă numărul ăsta s-a apropiat de prețul curent, nu mai sunt adăugări, oricât de frumos ar arăta trendul.",
    },
    priceOfNotKnowing: {
      tag: "PREȚUL NEȘTIINȚEI",
      title: "Calculăm sub ochii tăi, fără procente inventate",
      intro: "Intrare cu un lot. Prețul a parcurs 40 de puncte în direcția dorită, adăugare cu încă un lot. Încă 40 — al treilea lot. Încă 40 — al patrulea.",
      body2: "Prețul mediu de intrare e acum cu 60 de puncte peste prima intrare. Poziția e de patru ori mai mare decât cea inițială.",
      keyLabel: "Numărul cheie",
      keyBody: "La o retragere de 60 de puncte de la maxim, poziția devine neprofitabilă — deși prețul e încă cu 60 de puncte peste prima intrare. Ești pe plus din punct de vedere al direcției și pe minus din punct de vedere al banilor, simultan.",
      body3: "Fără adăugări, aceeași situație ar arăta așa: preț cu 60 de puncte peste intrare, poziție pe plus 60 de puncte cu un singur lot. Aceeași piață, aceeași mișcare, rezultat opus.",
      body4: "Partea cinstită: de aici nu rezultă că nu se poate adăuga. Rezultă că adăugarea are un preț, se calculează dinainte și trebuie știut înainte de a apăsa butonul, nu după. Exact asta calculează calculatorul de mai jos.",
    },
    whySwing: {
      tag: "DE CE SWING — ARITMETICĂ, NU GUST",
      body1: "Costul pe tranzacție e fix și cunoscut: spread plus comision, l-ai măsurat în capitolul 11. Deci costul total e proporțional cu numărul de tranzacții, nu cu calitatea lor.",
      body2: (scalp, swing) => `De aici o consecință care nu ține de preferințe: cu cât mișcarea medie vizată e mai mică, cu atât o pondere mai mare din ea e mâncată de cost. O țintă de 15 puncte la un cost de 1 punct cedează ${scalp}% din rezultat; o țintă de 150 de puncte la același cost — ${swing}%.`,
      body3: "Acesta e singurul argument cinstit în favoarea orizonturilor mai lungi, și nu ține de faptul că swing-ul e „mai bun”. Ține de faptul că la un orizont scurt cerințele de precizie sunt mai mari — același cost trebuie recuperat printr-o mișcare mai mică.",
      body4: "Reversul se numește imediat: o poziție lungă trăiește prin evenimente de calendar (capitolul 6), prin rollover-uri și swap-uri (capitolul 5), iar riscul ei peste noapte nu e sub control. Alegerea orizontului e alegerea unui set de probleme, nu scăparea de ele.",
      openOnChart: "Deschide Aur pe grafic →",
    },
    tradeAnatomy: {
      tag: "ANATOMIA UNEI TRANZACȚII",
      title: "Analiza unei tranzacții reale ca succesiune de decizii",
      disclaimer: "Aceasta e o analiză a unei tranzacții a unei persoane, pe un instrument, într-un context concret. Nu e șablon, nu e strategie, nu e recomandare. Valoarea nu stă în niveluri — nu se vor repeta — ci în ordinea întrebărilor puse înainte de a apăsa butonul. Ordinea se repetă, nivelurile nu.",
      contextLabel: "Contextul la momentul intrării",
      contextText: "Aur, grafic zilnic. Calendarul zilei — liniștit, fără publicații mari nici în sesiunea asiatică, nici în cea europeană. Ambele medii (capitolul 8) indicau aceeași direcție, prețul deasupra ambelor. Nimic neobișnuit — o zi obișnuită cu o imagine clară, dar nu rară.",
      questionsLabel: "Întrebări puse înainte de intrare",
      questions: [
        "Ce anume ar infirma ideea? — Nu „dacă merge împotrivă”, ci o condiție concretă la care imaginea e considerată greșită.",
        "Unde se află fizic acea condiție pe grafic? — Nu un număr rotund și nu „un pic mai departe ca să fiu sigur”, ci un punct structural: locul sub care logica mișcării anterioare încetează să funcționeze.",
        "Câte loturi la acest stop se încadrează în regula de risc a capitolului 3? — Calculat de la punctul de infirmare, nu invers.",
        "Ce e în calendar pe toată durata de viață așteptată a tranzacției, nu doar azi? — Verificat cu câteva zile înainte, nu doar în momentul apăsării butonului.",
      ],
      stopLabel: "Unde a stat stopul și de ce",
      stopText: "Stopul n-a stat la „cât nu-mi pare rău să pierd”, ci la un punct structural — acolo unde ideea de intrare însăși încetează să fie adevărată. Dacă prețul ar fi ajuns acolo, nu ar fi însemnat „ghinion”, ci „ipoteza de mișcare e greșită” — și motivul corect de a închide e exact acesta, nu că stopul s-a declanșat mecanic.",
      timelineLabel: "Ce a urmat",
      timeline: [
        "Primele ore — mișcare în direcția așteptată, fără surprize. Decizie: nu se schimbă nimic, planul nu se revizuiește după o oră bună.",
        "Spre seară — accelerare, prețul a depășit clar reperele marcate încă dinainte de intrare drept condiții pentru a lua în calcul o adăugare. Decizia de adăugare a fost luată după o condiție scrisă dinainte, nu după senzația „vreau mai mult”.",
        "Noaptea — mișcarea a continuat, sesiunea asiatică e subțire (capitolul 5), și aici începe greșeala.",
      ],
      mistakeLabel: "Ce s-a dovedit a fi greșeala",
      mistakeText: "Greșeala nu e tranzacția în sine, nici adăugarea în sine. Greșeala e că decizia ultimei adăugări a fost luată fără a reverifica calendarul pentru durata de viață rămasă a poziției. Calendarul chiar fusese gol la momentul intrării, dar nu și douăsprezece ore mai târziu — și nimeni n-a reverificat, pentru că poziția era deja mult pe plus și „de ce, oricum merge bine”. Exact această verificare omisă a fost condiția în care o mișcare obișnuită peste noapte împotriva poziției s-a transformat într-o problemă reală: până atunci volumul era de câteva ori mai mare decât cel inițial, și nimeni nu se uitase la date proaspete de risc pentru timpul rămas.",
      lessonLabel: "Ce rezultă de aici",
      lessonText: "Nu „nu adăuga”. Rezultă: lista de întrebări verificată înainte de prima intrare trebuie reverificată înainte de FIECARE adăugare, nu considerată închisă o singură dată. Poziția își schimbă mărimea pe parcursul vieții ei, iar lista de verificări — dacă nu se repetă — nu se schimbă odată cu ea.",
    },
    pyramid: {
      tag: "ARITMETICA ADĂUGĂRII — NUCLEUL CAPITOLULUI",
      step1Label: "EXPLICĂ",
      step1Body: "Adăugarea e o poziție nouă la un preț nou. Deci poziția combinată capătă un preț mediu de intrare, și e mai prost decât cel inițial. Acum calculăm exact cât de mult și ce rezultă din asta.",
      step2Label: "ARATĂ",
      step2Intro: "Exemplu gata făcut: un lot la intrare, apoi trei adăugări de câte un lot, la pas de 40 de puncte.",
      avgLabel: "Preț mediu de intrare (puncte peste prima intrare)",
      pnrLabel: "Punctul fără întoarcere (retragere de la vârf, puncte)",
      step2Note: "Punctul fără întoarcere se retrage exact la jumătatea distanței parcurse — nu e o coincidență, e o consecință directă a aritmeticii mediei pentru pași egali. Numărul absolut de puncte sub risc crește totuși cu fiecare adăugare.",
      step3Label: "LASĂ SĂ ÎNCERCE",
      step3Intro: "Setează-ți propriii parametri de adăugare.",
      firstSizeLabel: "Mărimea primei intrări (loturi)",
      stepPtsLabel: "Pas de adăugare, puncte",
      addSizeLabel: "Mărimea fiecărei adăugări (loturi, mod „egale”)",
      nAddsLabel: "Număr de adăugări",
      modeLabel: "Mod",
      modeEqual: "Adăugări egale",
      modeDecreasing: "Adăugări descrescătoare",
      resultAvgLabel: "Preț mediu de intrare",
      resultPnrPtsLabel: "Punct fără întoarcere, puncte de la vârf",
      resultPnrPctLabel: "% din distanța parcursă",
      resultRiskLabel: "Risc total, de câte ori mai mare decât prima poziție",
      reveal: {
        title: "Trei lucruri vizibile în aceste cifre",
        p1: "Primul: distanța absolută în puncte până la punctul fără întoarcere crește cu fiecare adăugare — 20 de puncte după o adăugare, 60 după trei în exemplul de mai sus. Nu „riști bani deja câștigați” — îți reduci marja de siguranță în puncte și bani reali.",
        p2: "Al doilea: riscul total crește mai repede decât pare la prima vedere. La adăugări egale volumul crește liniar — dar fiecare unitate de volum poartă propria pondere de risc, și se adună.",
        p3: "Al treilea, și el decide: toate adăugările au fost făcute în stare de câștig. Acestea sunt singurele decizii din trading luate atunci când totul merge bine — și de aceea singurele unde prudența naturală nu se activează.",
        conclusion: "Concluzia nu e „nu adăuga”. Concluzia e: calculează punctul fără întoarcere înainte de prima adăugare și decide după el, nu după cum arată trendul.",
      },
      compliance: "Acesta e un calculator de consecințe, nu o metodă de tranzacționare. Nu recomandăm nici să adaugi, nici să te abții — arătăm aritmetica deciziei.",
      openOnChart: "Deschide Aur pe grafic →",
    },
    breakeven: {
      tag: "CÂT COSTĂ UN STOP LA BREAKEVEN — MĂSURĂTOAREA NOASTRĂ",
      preamble: "Regula „am mutat stopul la intrare — riscul e zero” sună impecabil, și tocmai de aceea aproape că nu se verifică niciodată. Am verificat două lucruri.",
      firstLabel: "Primul — „risc zero” e greșit literalmente",
      firstText: "Rămân slippage-ul, gap-ul de la deschiderea săptămânii, gap-ul de la publicarea datelor (capitolul 6), lărgirea spread-ului. Pierderea planificată e zero; cea reală poate fi oricât. Nu e o măsurătoare, e mecanică deja analizată în capitolele 4 și 6.",
      secondLabel: "Al doilea — măsurabil și mai interesant",
      secondText: "Cât de des mutarea la breakeven închide o tranzacție care ar fi funcționat. Metodă fixată înainte de calcul: luăm toate cazurile în care prețul a parcurs de la un punct ipotetic de intrare X puncte (în fracții de ATR) în direcția dorită; verificăm cât de des revine la intrare înainte de a atinge ținta Y. Parcurgere pe o grilă de X și Y, pe instrumente și intervale H4/D1 — swing-ul trăiește în zile, nu în ore.",
      verdictLabel: (x, cost, n) => `La mutarea după parcurgerea a ${x} din distanța până la țintă, ponderea tranzacțiilor închise la zero în loc să atingă ținta a fost de ${cost}%, la n = ${n.toLocaleString("ro-RO")}.`,
      point2: "Cu cât muți mai devreme, cu atât costă mai mult. Relația e monotonă pe toate distanțele de țintă verificate — fără nicio excepție.",
      point3: "Un compromis, nu o îmbunătățire. Mutarea la breakeven reduce pierderea medie și reduce ponderea tranzacțiilor care ating ținta, simultan. Ce contează mai mult depinde de raportul țintă/stop din sistemul concret; nu există un răspuns universal, și nu dăm unul.",
      honestPlate: "Măsurat: mișcarea prețului din istoricul nostru, fără spread și slippage — deci ponderea reală închisă la zero e MAI MARE decât estimarea noastră. Nemăsurat: contextul intrării. Am testat regula mecanică, pentru că exact așa e aplicată.",
      csvBtn: "Descarcă cifrele noastre (CSV)",
      tableXLabel: "X (fracție ATR)", tableYLabel: "Y (fracție ATR)", tableZeroLabel: "Închise la zero", tableNLabel: "n",
      openOnChart: "Deschide Aur pe grafic →",
    },
    tradePlan: {
      tag: "PLANUL TRANZACȚIEI — CE SE SCRIE ÎNAINTE",
      intro: "Cinci rânduri. Tot ce nu e scris înainte va fi inventat după — și va coincide cu ce s-a întâmplat. Mecanismul a fost analizat în capitolul 9.",
      entryLabel: "Condiția de intrare — verificabilă, nu „arată bine”",
      stopLabel: "Unde e stopul și de ce exact acolo — nivelul la care ideea inițială e infirmată",
      exitLabel: "Unde e ieșirea — și ce faci dacă prețul a ajuns la jumătatea drumului și s-a oprit",
      addLabel: "Dacă adaugi, și dacă da — punctul fără întoarcere după fiecare adăugare, calculat dinainte",
      calendarLabel: "Ce e în calendar pe durata de viață a poziției",
      saveBtn: "Salvează planul",
      savedNote: "Planul a fost salvat în jurnal.",
    },
    ladderStep8: {
      tag: "TREAPTA 8 — ANALIZA JURNALULUI DE UN ANALIST REAL",
      limitParagraph1: "Tocmai ai citit analiza tranzacției altcuiva — cu întrebări puse înainte de intrare și o greșeală descoperită după. E firesc să-ți dorești aceeași analiză pentru ale tale.",
      limitParagraph2: "Automat nu se poate face asta. Jurnalul îți calculează cifrele și le arată (capitolul 10), dar cifrele nu răspund la întrebarea „de ce ai decis așa” — la ea răspunde un om care citește la rând cincizeci dintre tranzacțiile tale și vede ce nu se vede din interior.",
      factualityTitle: "Cum sună concluzia analizei",
      factualityBody: "Nu „ești prea devreme pentru bani reali” — aceasta e o recomandare personală despre o decizie financiară, pe care un proiect educațional n-are dreptul s-o facă. În loc de asta — o constatare de fapte: „Din înregistrările tale, cele patru condiții pe care capitolul 14 le pune înaintea unui cont real stau așa: tranzacții — 34 din 50; săptămâni de jurnal — 3 din 4; sistem scris — da; aritmetica riscului calculată — nu. Două din patru condiții nu sunt încă îndeplinite.” Un răspuns direct, fără convingere, fără sfat.",
      disclosureLine: "Analiza e gratuită și nu obligă la nimic. De ce o oferim: cineva care trece printr-o analiză înainte de primul cont real termină cursul vizibil mai des. Ne e avantajos, și preferăm să spunem asta noi înșine.",
      pendingNote: "Formularul de cerere pentru analiză nu e încă deschis. Să-l arătăm înainte să existe o coadă reală și un termen real de răspuns ar fi mai rău decât să nu-l arătăm deloc — o promisiune pe care n-o poate onora nimeni costă mai mult decât un „încă nu” cinstit.",
    },
    quiz: [
      { id: "q1", section: "secPyramid", prompt: "Ai adăugat de trei ori pe măsură ce prețul creștea. Ce s-a întâmplat cu punctul în care poziția devine neprofitabilă?",
        options: [{ text: "A rămas pe loc", correct: false }, { text: "S-a apropiat de prețul curent", correct: true }, { text: "S-a îndepărtat", correct: false }],
        feedbackCorrect: "Corect. Fiecare adăugare mută punctul fără întoarcere mai aproape de prețul curent, în puncte absolute.",
        feedbackWrong: "Nu chiar. Prețul mediu de intrare crește cu fiecare adăugare, deci și pragul la care poziția devine neprofitabilă se apropie." },
      { id: "q2", section: "secBreakeven", prompt: "Stopul e mutat la intrare. Riscul e zero?",
        options: [{ text: "Da", correct: false }, { text: "Nu — rămân slippage, gap-uri și lărgirea spread-ului; zero a devenit pierderea planificată", correct: true }, { text: "Doar pe demo", correct: false }],
        feedbackCorrect: "Corect. Pierderea planificată e zero, cea reală poate fi oricât.",
        feedbackWrong: "Nu chiar. „Risc zero” descrie planul, nu o garanție de execuție la acel preț." },
      { id: "q3", section: "secWhySwing", prompt: "De ce la o țintă scurtă cerințele de precizie sunt mai mari?",
        options: [{ text: "Un cost fix mănâncă o pondere mai mare dintr-o mișcare mică", correct: true }, { text: "Piața e mai liniștită noaptea", correct: false }, { text: "Comisionul e mai mare la tranzacții scurte", correct: false }],
        feedbackCorrect: "Corect. Același cost în puncte e o mușcătură mai mare dintr-o țintă mică.",
        feedbackWrong: "Nu chiar. Contează ce pondere din țintă mănâncă același cost fix." },
      { id: "q4", section: "secTradeAnatomy", prompt: "Regulile unei tranzacții, reconstituite după ce s-a închis, …",
        options: [{ text: "Nu sunt mai proaste decât cele scrise înainte", correct: false }, { text: "Vor coincide mereu cu ce s-a făcut de fapt — memoria se adaptează", correct: true }, { text: "Sunt mai precise, pentru că rezultatul e cunoscut", correct: false }],
        feedbackCorrect: "Corect. Exact de aceea planul tranzacției se scrie înainte, nu se reconstituie după.",
        feedbackWrong: "Nu chiar. Memoria retrospectivă adaptează explicația la ce s-a întâmplat deja (capitolul 9)." },
    ],
    predict: {
      tag: "PROGNOZA SĂPTĂMÂNII",
      question: "Ce pondere din tranzacții crezi că se închid la zero în loc să atingă ținta, când stopul e mutat la breakeven după jumătatea drumului spre țintă?",
      options: ["Sub 30%", "30–60%", "60–85%", "Peste 85%"],
      answerNote: (cost, correct) => `${correct ? "Corect." : "Ratat."} După măsurătorile noastre (H4/D1, toate instrumentele): ${cost}%.`,
      xpNote: "Despre o mărime măsurabilă — nu există răspuns corect moral, există unul calculat.",
    },
    cliffhanger: {
      tag: "URMEAZĂ → CAPITOLUL 14",
      body: "A mai rămas o temă și o discuție.\n\nTema e scalping: tranzacții care trăiesc minute. O vom analiza cinstit, și concluzia principală nu va fi despre tehnică. Scalping-ul e un capitol despre costuri: la o țintă de zece puncte, spread-ul și comisionul se transformă din cheltuială secundară în cheltuiala principală, și totul se decide prin aritmetica pe care deja știi s-o faci din capitolul 11.\n\nIar discuția e despre contul real. Am ajuns în locul unde e logic s-o discutăm, și o discutăm direct: ce se schimbă când banii sunt reali, cât costă asta și de ce avem patru condiții în fața acestei uși, nu un buton. Probabil ai îndeplinit deja trei din patru.",
    },
    sources: {
      tag: "SURSELE CAPITOLULUI",
      list: [
        "Aritmetica prețului mediu al poziției și a punctului de breakeven — calcul direct, prezentat integral în capitol.",
        "Kahneman D., Tversky A. — efectul „banilor de cazino” (house money effect): tendința de a risca mai mult banii deja câștigați.",
        "Thaler R., Johnson E. (1990) — dovezi empirice pentru același efect.",
        "Mecanica slippage-ului și a gap-urilor — capitolele 4 și 6 ale cursului, cu surse acolo.",
      ],
      ownTemplate: "SBF Company SRL. Ponderea tranzacțiilor închise la zero în loc de țintă după mutarea stopului la breakeven. Date: 16 instrumente, timeframe-uri H4/D1, o grilă de {{x_n}}×{{y_n}} valori în fracțiuni de ATR (perioadă {{atr_period}}), orizont de {{lookahead}} bare. Metodă: stopul mutat la breakeven după ce prețul trece fracțiunea X din distanța până la ținta Y; fără spread și slippage — ponderea reală e mai mare decât aceasta. Recalculat la {{built}}.",
      csvLabel: "Descarcă datele (CSV)",
      checked: "Verificat la 27.07.2026.",
    },
  },
};
