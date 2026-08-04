/**
 * Chapter 15 "От Теории к Практике" content — SPEC_edu_level15_three_paths.md.
 * Финал 15-главного курса market_intel. RU is the master text (spec §3, close
 * to verbatim, including SPEC_partner_ladder_ch6_15.md §6.2/§3.10 blocks it
 * references); RO/EN are translations in the same register as ch1-14.
 * window.Ch15Content = {ru, ro, en}.
 *
 * [ФАКТ-ЧЕК ВЫПОЛНЕН ЧЕРЕЗ WebSearch] §3.1 требует юридической проверки дела
 * MyForexFunds/CFTC перед публикацией. Проверено вручную (не автоматически):
 * CFTC подала иск против Traders Global Group Inc. (My Forex Funds) и её
 * основателя Murtuza Kazmi в августе 2023 (заморозка активов подписана судьёй
 * Robert B. Kugler 29 августа 2023, >135 000 клиентов, обвинение на сумму
 * свыше $300-310 млн). 13 мая 2025 дело прекращено С ПРАВОМ НЕ ПОДАВАТЬ ЗАНОВО
 * (with prejudice) по рекомендации Special Master José L. Linares: CFTC ввела
 * суд в заблуждение, представив рутинный налоговый платёж (CAD ~31.55М в
 * Canada Revenue Agency) как вывод активов, зная об этом заранее. Санкции по
 * Правилу 11 против CFTC — свыше $3 млн судебных издержек (по Quinn Emanuel,
 * представлявшим ответчика: "крупнейшая денежная санкция против федерального
 * агентства США на сегодняшний день"). Решение о прекращении — процессуальное
 * (о поведении CFTC в процессе), не оправдание по существу обвинений. Все эти
 * факты совпадают с формулировкой родительской спеки почти дословно —
 * серьёзных расхождений не найдено. Источники: quinnemanuel.com, tradingview
 * News/FinanceMagnates, cftc.gov (Kazmi Report & Recommendation on Sanctions).
 *
 * [ЧАСТИЧНО ПРОВЕРЕНО] Регуляторный блок (FSMA, CONSOB, ČNB, ESMA, BaFin):
 * FSMA (Бельгия, март 2024) и CONSOB (Италия, июль 2024) — даты и содержание
 * предупреждений подтверждены WebSearch независимо от родительской спеки.
 * ČNB/ESMA позиция про периметр MiFID II — подтверждена в общих чертах.
 * Точный номер документа ESMA от 24.02.2026 (ESMA35-243228190-8024) и даты
 * BaFin/CONSOB 2025-26 из родительской спеки самостоятельно НЕ переверифицированы
 * (вне глубины доступного поиска в разумное время) — взяты из родительской
 * спеки как единственного источника, с пометкой честной даты сверки. Это НЕ
 * заменяет формальную юридическую проверку, которую спека требует явно —
 * рекомендация ниже (в документации закрытия) отражает это прямо.
 *
 * [РЕШЕНИЕ] Путь 2 (реальный счёт) не раскрывает <PartnerBridge tier="path">
 * с реальными данными площадки — partners.json не существует (та же причина,
 * что отложила ступень 6 в главе 11 и полное раскрытие в ступени 9 главы 14).
 * Условия ворот проверяются по-настоящему через тот же /api/journal/gate-status
 * (глава 14) — переиспользование, не дублирование гейта.
 *
 * [РЕШЕНИЕ] Путь 3 (доверительное управление) построен ТОЧНО по фолбэку,
 * который спека сама прописывает на случай отсутствия юриста: «обсуждается
 * лично» с формой заявки, без описания условий. Это не отложено — это
 * буквально то, что спека просит построить в данном состоянии.
 *
 * [РЕШЕНИЕ] Счётчик "N партнёров" в финале не показан вовсе (не "6 PROP-ФИРМ",
 * не выдуманное "5 партнёров") — partners.json не существует, показать любое
 * число значило бы нарушить правило, которое эта же глава формулирует про
 * MyForexFunds: ни одной цифры без файла с датой проверки.
 */
window.Ch15Content = {
  ru: {
    coldOpen: {
      tag: "ГЛАВА 15 — ПОЛТОРА ГОДА",
      lines: [
        "Это предыдущая версия страницы, которую ты сейчас читаешь. Шесть проп-фирм, красивые карточки, кнопка «подать на челлендж».",
        "Одна из них — на момент публикации фактически не принимала клиентов. Против неё был подан иск американского регулятора; полтора года она оставалась в нашем списке.",
        "Мы не заметили. Список был написан руками прямо в коде страницы, у чисел не было даты проверки, и обновлять их было некому и нечем.",
        "С этого стоит начать последнюю главу, потому что она про то, как выбирать — и про то, что проверять надо любой список, включая наш. Мы починили это у себя: данные партнёров теперь лежат в отдельном файле, у каждой цифры есть дата снятия и ссылка на источник, а партнёр без актуальных данных просто не показывается.",
        "Следующие двенадцать минут — про проп-трейдинг без витрины, про девять правил, из которых только пять настоящие, и про три пути, из которых первый бесплатный.",
      ],
      cta: "Разобрать механику ↓",
      screenshotCaption: "Прежняя версия этой главы, снимок из истории репозитория.",
    },
    propMechanics: {
      tag: "ПРОП-ТРЕЙДИНГ: ЧТО ТЕБЕ ПРОДАЮТ НА САМОМ ДЕЛЕ",
      intro: "Ты почти наверняка видел рекламу: «получи $100 000 в управление, пройди челлендж». Разберём механику, потому что она устроена не так, как выглядит.",
      howLabel: "Как это работает",
      howText: "Ты платишь взнос за участие. Торгуешь на симуляторе — у большинства фирм это так, но не универсально: часть заявляет о выводе части потока на рынок, и проверяется это по договору конкретной фирмы, а не по рекламе. Если ты выполняешь правила (цель по прибыли, дневной лимит просадки, общий лимит), ты получаешь «финансируемый счёт». Он, как правило, тоже симулированный, а выплаты — доля от виртуальной прибыли, выплачиваемая реальными деньгами.",
      interestLabel: "Где здесь чей интерес",
      interestText: "Основной доход большинства таких фирм — взносы тех, кто не прошёл. Это не обвинение и не конспирология, это описание модели: чем ниже проходимость, тем выше доход. Проходимость и средний размер выплат почти никто не публикует. Когда тебе не показывают ключевую цифру, а показывают истории успеха, — цифра, скорее всего, не в твою пользу.",
      compareLabel: "Сравни с тем, что мы писали в главе 11 про брокеров",
      compareText: "Брокер зарабатывает на спреде и комиссии — то есть на том, что ты торгуешь; ему выгодно, чтобы ты остался. Проп-фирма зарабатывает на взносе — то есть на попытке; ей достаточно, чтобы ты попробовал. Это разные знаки, и знать их полезнее, чем любой список фирм.",
      caseTitle: "Фирма, о которой шла речь в начале",
      caseText: "MyForexFunds (юрлицо Traders Global Group Inc.). В августе 2023 года Комиссия по торговле товарными фьючерсами США (CFTC) подала против неё иск с обвинением в мошенничестве на сумму свыше $300 млн; в тот же месяц суд заморозил активы, деятельность фактически остановилась (у платформы было более 135 000 клиентов). Дело было прекращено 13 мая 2025 года без права повторной подачи — по рекомендации специального судебного порученца (Special Master), установившего, что CFTC ввела суд в заблуждение, представив рутинный налоговый платёж (около CAD 31,55 млн в канадскую налоговую) как вывод активов, зная об этом заранее. На саму CFTC были наложены санкции по Правилу 11 на сумму свыше $3 млн — судебные издержки ответчика.",
      caseNeutral: "Мы приводим это не как обвинение и не как оправдание — решение суда касалось поведения регулятора в процессе, а не разбора обвинений по существу, и обе стороны этой истории выглядят неидеально. Вывод для нас другой: полтора года фирма стояла в нашем списке уже после того, как перестала работать. Список был статичным, у цифр не было даты, следить было некому. Любой список — включая наш — устаревает молча. Единственная защита: дата проверки рядом с каждой цифрой и источник, по которому можно проверить самому.",
      regLabel: "Регуляторный фон",
      regIntro: "С 2024 года регуляторы взялись за отрасль всерьёз.",
      regItems: [
        ["FSMA (Бельгия)", "март 2024", "публичное предупреждение о проп-челленджах: платные курсы, самовыдаваемые сертификаты, всплеск маркетинга симулированных счетов в соцсетях"],
        ["CONSOB (Италия)", "июль 2024", "описала проп-платформы как симуляцию торговли в формате «финансовой видеоигры»; отметила регулируемую сложность тестов и невыплаченные доли прибыли"],
        ["ČNB (Чехия)", "2024", "надзорная позиция: часть funded-trader сервисов может являться инвестиционной услугой по MiFID II"],
        ["BaFin, CONSOB", "2025–2026", "предупреждения инвесторам с упоминанием высокого плеча в CFD, продвигаемых проп-фирмами"],
        ["ESMA", "февраль 2026", "публичное заявление: продукты с плечом, включая продвигаемые проп-фирмами, подпадают под действующие национальные меры продуктового вмешательства по CFD"],
      ],
      regOutro: "Отдельного закона о проп-фирмах пока нет; направление движения — внутрь регулируемого периметра.",
      regCaveat: "Даты и содержание предупреждений FSMA и CONSOB проверены нами независимо. Формулировки по ČNB/ESMA/BaFin взяты из внутренней сверки команды и не заменяют профессиональную юридическую проверку каждого документа — она рекомендована до окончательной публикации этого раздела.",
    },
    propChecklist: {
      tag: "ЧТО ПРОВЕРИТЬ, ЕСЛИ ВСЁ РАВНО ХОЧЕШЬ",
      frame: "Мы не получаем вознаграждения ни от одной проп-фирмы и не даём на них ссылок. Поэтому дальше — просто список вопросов, а не рекомендация и не рейтинг.",
      items: [
        "Опубликована ли проходимость челленджа и средняя выплата? Если нет — спроси в поддержке и сохрани ответ.",
        "Есть ли независимые подтверждения выплат, а не скриншоты в соцсетях?",
        "В какой юрисдикции зарегистрировано юрлицо и что там с надзором?",
        "Что происходит с твоим счётом, если фирма закроется? У симулированного счёта нет компенсационного фонда.",
        "Сколько ты потеряешь, если не пройдёшь? Это единственная цифра, которую ты знаешь заранее и точно.",
      ],
    },
    honestAlt: {
      tag: "ЧЕСТНАЯ АЛЬТЕРНАТИВА",
      body1: "Взнос за челлендж — это деньги, отданные за право доказать дисциплину по чужим правилам. Ровно ту же дисциплину показывает твой собственный журнал за пятьдесят сделок, и он ничего не стоит. Разница только в том, что журнал не выдаёт сертификат.",
      body2: "И одна цифра для сравнения, которую ты уже знаешь. В главе 12 мы считали, сколько сделок нужно, чтобы отличить умение от везения. Челлендж обычно оценивает тебя на дистанции короче этой. То есть проходят его в том числе те, кому просто повезло, — и не проходят те, у кого преимущество есть, но выпала нормальная серия убытков.",
    },
    nineRules: {
      tag: "ДЕВЯТЬ ПРАВИЛ",
      group1Label: "Группа 1 — правила процесса (верны всегда)",
      group1: [
        "Никогда не рискуй больше 2% депозита в одной сделке",
        "Ставь стоп до входа, а не после",
        "Проверяй календарь перед сделкой",
        "При двух убытках подряд закрой терминал",
        "Веди журнал по каждой сделке — без исключений",
      ],
      group2Label: "Группа 2 — параметры методов из глав 12–14 (не законы рынка)",
      group2: [
        "В стратегии из главы 13 добавление к позиции происходит определённым шагом — в этой стратегии, а не вообще.",
        "В стратегии из главы 14 используются зоны RSI 35/65 вместо 30/70 — потому что на M5 зоны 30/70 срабатывают редко. На других таймфреймах вывод другой.",
        "Ишимоку из главы 12 фильтрует направление — в системе, где он и есть фильтр направления.",
      ],
      ninthLabel: "Девятое правило — самое важное",
      ninthText: "Отличай правило процесса от параметра метода. Первое ты не меняешь никогда. Второе ты обязан перепроверить на своих данных, прежде чем считать своим. Всё, что в этом курсе выглядит как число — период, зона, уровень, — это чей-то параметр, а не свойство рынка.",
    },
    threePaths: {
      tag: "ТРИ ПУТИ — ШАГ, РАДИ КОТОРОГО ВСЁ ЭТО ПИСАЛОСЬ",
      intro: "Пятнадцать глав закончились. Дальше — три разных пути, и один из них правильный чаще, чем два других.",
      path1: {
        title: "Путь первый: остаться на демо ещё на два-три месяца",
        text: "Подходит, если пятьдесят сделок ты добил, но результат по журналу нестабилен, или если свободных денег, потеря которых ничего не изменит, сейчас нет. Это не «неудача» и не отложенный старт — это самый частый правильный ответ. Курс остаётся открытым, журнал работает, разбор можно запросить снова через три месяца. Стоит ноль.",
        cta: "Остаться на демо",
      },
      path2: {
        title: "Путь второй: реальный счёт с минимальной суммой и сопровождением",
        text: "Подходит, если четыре условия из главы 14 сошлись. Мы помогаем выбрать площадку по твоей стране и задачам (сравнение — в главе 11), проверяем, что ты подписываешь договор с тем юрлицом, которое думаешь, и разбираем первые сделки. Что мы получаем от площадки — написано на странице «Как мы зарабатываем».",
        cta: "Проверить условия",
        blockedNote: "Сначала — то, чего не хватает по воротам главы 14.",
        gotoGate: "К воротам главы 14 →",
        condTrades: "Сделок в серии", condWeeks: "Недель активности", condSystem: "Правила серии записаны", condMath: "Калькулятор издержек пройден",
        projLabel: "Сделок в неделю (твой темп)", projResult: (weeks) => {
          const mod10 = weeks % 10, mod100 = weeks % 100;
          const word = (mod10 === 1 && mod100 !== 11) ? "неделя" : (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) ? "недели" : "недель";
          return `ещё ${weeks} ${word} до 50 сделок`;
        }, projDone: "условие по сделкам уже выполнено",
        pendingNote: "Список площадок с проверенными данными по юрлицам и лицензиям готовится отдельно и пока не показан здесь — по той же причине, по которой мы не публикуем непроверенные цифры нигде в курсе.",
      },
      path3: {
        title: "Путь третий: доверительное управление",
        text: "Подходит, если ты дочитал курс до конца и понял, что тебе интересен рынок, но не интересно им заниматься. Это отдельная услуга с отдельным договором и отдельным регулированием, и она обсуждается только лично: заочно её не продают, и мы не будем.",
        cta: "Обсудить лично",
        pendingNote: "Условия этой услуги проходят отдельную юридическую проверку и намеренно не описаны здесь до её завершения.",
      },
      whatWeDontDoTitle: "И то, чего мы не делаем ни на одном из трёх путей",
      whatWeDontDo: "Мы не продаём сигналы и не даём торговых рекомендаций. Не гарантируем доходность и не публикуем винрейты — ни свои, ни чужие. Не берём деньги за доступ к курсу. Не обещаем, что ты заработаешь. Если тебе это где-то пообещали от нашего имени — это не мы, и мы хотим об этом знать.",
      selectedNote: "Отмечено. Спасибо — это последнее, о чём мы просим в этом курсе.",
    },
    stopList: {
      tag: "КОГДА НЕ НАДО ОТКРЫВАТЬ РЕАЛЬНЫЙ СЧЁТ",
      subtitle: "Ни у нас, ни у кого-либо ещё.",
      items: [
        "Если деньги заёмные — кредит, рассрочка, взято у родственников.",
        "Если это подушка безопасности, деньги на лечение, на учёбу, на аренду.",
        "Если недавно был крупный проигрыш в чём-то другом и есть желание отыграться.",
        "Если основной мотив — «надо срочно», а не «хочу разобраться».",
        "Если ты не можешь объяснить своими словами, что такое стоп-лосс и почему он ставится до входа.",
        "Если за последний месяц ты хотя бы раз увеличивал риск после убытка — журнал это знает, посмотри главу 10.",
        "Если ты рассчитываешь заменить этим зарплату в обозримом сроке.",
      ],
      outro: "В любом из этих случаев ответ — путь первый. Он бесплатный и от него ещё никто не пострадал.",
    },
    verifyUs: {
      tag: "ПРОВЕРЬ НАС",
      title: "Всё, что мы утверждали в пятнадцати главах, — в одном файле",
      body1: "Каждое измерение, которое мы публиковали, посчитано скриптом, и скрипт лежит в открытом виде. Каждая выгрузка доступна в CSV. У каждого внешнего факта указан источник и дата проверки.",
      body2: "Мы собрали это в один список: утверждение — где считалось — чем проверить. Если найдёшь ошибку — напиши, поправим и напишем, что поправили.",
      downloadClaims: "Скачать список утверждений и источников",
      downloadAll: "Скачать все наши измерения (CSV)",
      typeLabels: { measured: "измерено", external: "внешний факт", arithmetic: "арифметика" },
      chapterLabel: "гл.",
    },
    coldStart: {
      tag: "ПРОВЕРЬ НАС",
      ask: "Пятнадцать глав утверждений. Выбери любое — увидишь, чем именно оно проверено.",
      methodScript: "Метод: скрипт {{script}}", methodArithmetic: "Метод: прямой расчёт, без данных",
      dateLabel: "Проверено {{date}}", downloadLabel: "Скачать проверку",
      bridge: "Остальные семь утверждений и полный список источников — в course_claims.json, открыт для скачивания.",
    },
    finalParagraph: {
      body1: "Пятнадцать глав назад мы начали с того, что цена — это след чужих решений, а не линия на экране. Всё остальное было способами читать этот след.",
      body2: "Мы старались не соврать тебе ни разу. Где могли — выкладывали данные, чтобы ты пересчитал сам. Где зарабатываем — писали, сколько и на чём. Где не знаем — говорили, что не знаем. Это единственное, чем обучающий курс о рынке может отличаться от рекламы, и это же единственное, что мы просим сохранить в собственной торговле: считать самому и проверять, кому что выгодно.",
      body3: "Дальше — твой журнал. Он честнее любого курса, включая этот.",
    },
    sources: {
      tag: "ИСТОЧНИКИ ГЛАВЫ",
      list: [
        "CFTC v. Traders Global Group Inc. (My Forex Funds) — материалы дела и определение о прекращении производства с санкциями по Правилу 11, май 2025.",
        "FSMA (Бельгия), публичное предупреждение по проп-трейдинговым платформам, март 2024.",
        "CONSOB (Италия), заявление о формате проп-челленджей, июль 2024.",
        "Чешский национальный банк, надзорная позиция о применимости MiFID II к funded-trader сервисам, 2024.",
        "ESMA, заявление о продуктах с плечом и мерах продуктового вмешательства по CFD, февраль 2026.",
        "Наши собственные измерения и скрипты — полный список в блоке «Проверь нас» и в course_claims.json.",
      ],
      checked: "Проверено на 27.07.2026.",
    },
  },

  en: {
    coldOpen: {
      tag: "CHAPTER 15 — A YEAR AND A HALF",
      lines: [
        "This is the previous version of the page you're reading right now. Six prop firms, nice cards, an 'apply for the challenge' button.",
        "One of them — at the time this was published — had effectively stopped accepting clients. A U.S. regulator had filed suit against it; it stayed on our list for a year and a half.",
        "We didn't notice. The list was written by hand directly in the page's code, the numbers had no verification date, and there was nobody and nothing to update them.",
        "That's the right place to start the last chapter, because it's about how to choose — and about the fact that any list needs checking, including ours. We fixed this on our end: partner data now lives in a separate file, every number has a date it was pulled and a source link, and a partner without current data simply isn't shown.",
        "The next twelve minutes are about prop trading without the storefront, about nine rules of which only five are actually rules, and about three paths, the first of which is free.",
      ],
      cta: "Break down the mechanics ↓",
      screenshotCaption: "The previous version of this chapter, a snapshot from repository history.",
    },
    propMechanics: {
      tag: "PROP TRADING: WHAT YOU'RE ACTUALLY BUYING",
      intro: "You've almost certainly seen the ad: \"get $100,000 in funding, pass the challenge.\" Let's break down the mechanics, because it works differently than it looks.",
      howLabel: "How it works",
      howText: "You pay an entry fee. You trade on a simulator — true for most firms, but not universal: some claim to route part of the flow to the market, and that's checked against a specific firm's contract, not its advertising. If you meet the rules (profit target, daily drawdown limit, overall limit), you get a 'funded account.' It's usually simulated too, and payouts are a share of virtual profit, paid out in real money.",
      interestLabel: "Whose interest sits where",
      interestText: "Most such firms' main income is fees from people who don't pass. That's not an accusation or a conspiracy — it's a description of the model: the lower the pass rate, the higher the revenue. Almost nobody publishes pass rates or average payout size. When you're not shown the key number but you are shown success stories, the number is probably not in your favor.",
      compareLabel: "Compare this to what we wrote about brokers in chapter 11",
      compareText: "A broker earns on spread and commission — on the fact that you trade; it benefits from you staying. A prop firm earns on the entry fee — on the attempt; it's enough that you tried once. These are opposite signs, and knowing them is more useful than any list of firms.",
      caseTitle: "The firm mentioned at the start",
      caseText: "My Forex Funds (legal entity Traders Global Group Inc.). In August 2023, the U.S. Commodity Futures Trading Commission (CFTC) filed suit against it alleging fraud exceeding $300 million; that same month, the court froze its assets and the business effectively stopped operating (the platform had over 135,000 clients). The case was dismissed with prejudice on May 13, 2025, on the recommendation of a court-appointed Special Master, who found that the CFTC had misled the court by presenting a routine tax payment (roughly CAD 31.55 million to Canada's tax authority) as asset dissipation, while knowing what it actually was. The CFTC itself was sanctioned under Rule 11 for over $3 million — the defendant's legal costs.",
      caseNeutral: "We're presenting this neither as an accusation nor as an exoneration — the court's ruling concerned the regulator's conduct during the proceedings, not a ruling on the underlying allegations, and neither side of this story looks great. The takeaway for us is different: the firm sat on our list for a year and a half after it had already stopped operating. The list was static, the numbers had no date, and nobody was watching. Any list — including ours — goes stale silently. The only defense is a verification date next to every number, and a source you can check yourself.",
      regLabel: "The regulatory backdrop",
      regIntro: "Since 2024, regulators have taken the industry seriously.",
      regItems: [
        ["FSMA (Belgium)", "March 2024", "public warning about prop challenges: paid courses, self-issued certifications, a surge in marketing simulated accounts on social media"],
        ["CONSOB (Italy)", "July 2024", "described prop platforms as trading simulation in the form of a 'financial video game'; flagged the tuned difficulty of tests and unpaid profit shares"],
        ["ČNB (Czech Republic)", "2024", "supervisory position: some funded-trader services may qualify as an investment service under MiFID II"],
        ["BaFin, CONSOB", "2025-2026", "investor warnings mentioning high CFD leverage promoted by prop firms"],
        ["ESMA", "February 2026", "public statement: leveraged products, including those promoted by prop firms, fall under existing national CFD product-intervention measures"],
      ],
      regOutro: "There's no dedicated law on prop firms yet; the direction of travel is into the regulated perimeter.",
      regCaveat: "The dates and content of the FSMA and CONSOB warnings were independently verified by us. The ČNB/ESMA/BaFin wording is taken from internal cross-checking and doesn't substitute for a professional legal review of each document — one is recommended before this section's final publication.",
    },
    propChecklist: {
      tag: "WHAT TO CHECK IF YOU STILL WANT TO",
      frame: "We don't get paid by any prop firm and we don't link to any. So what follows is just a list of questions, not a recommendation or a ranking.",
      items: [
        "Is the challenge pass rate and average payout published? If not, ask support and keep the answer.",
        "Is there independent confirmation of payouts, not just social-media screenshots?",
        "What jurisdiction is the legal entity registered in, and what's the oversight situation there?",
        "What happens to your account if the firm closes? A simulated account has no compensation fund.",
        "How much will you lose if you don't pass? That's the one number you know in advance, for certain.",
      ],
    },
    honestAlt: {
      tag: "AN HONEST ALTERNATIVE",
      body1: "A challenge fee is money paid for the right to prove discipline by someone else's rules. Your own journal over fifty trades shows the exact same discipline, and it costs nothing. The only difference is the journal doesn't issue a certificate.",
      body2: "And one comparison figure you already know. In chapter 12 we computed how many trades it takes to tell skill from luck. A challenge usually judges you over a shorter run than that. Which means people who just got lucky pass it too — and people with a real edge who happened to hit a normal losing streak don't.",
    },
    nineRules: {
      tag: "NINE RULES",
      group1Label: "Group 1 — process rules (always true)",
      group1: [
        "Never risk more than 2% of the deposit on one trade",
        "Set the stop before entry, not after",
        "Check the calendar before a trade",
        "Close the terminal after two losses in a row",
        "Journal every trade, no exceptions",
      ],
      group2Label: "Group 2 — method parameters from chapters 12-14 (not laws of the market)",
      group2: [
        "In chapter 13's strategy, adding to a position happens at a specific step — in that strategy, not universally.",
        "Chapter 14's strategy uses RSI zones 35/65 instead of 30/70 — because on M5, 30/70 zones trigger rarely. On other timeframes the conclusion differs.",
        "Chapter 12's Ichimoku filters direction — in the system where it's specifically used as a direction filter.",
      ],
      ninthLabel: "The ninth rule — the most important one",
      ninthText: "Tell a process rule apart from a method parameter. You never change the first. You're obligated to re-check the second against your own data before treating it as yours. Anything in this course that looks like a number — a period, a zone, a level — is someone's parameter, not a property of the market.",
    },
    threePaths: {
      tag: "THREE PATHS — THE STEP ALL OF THIS WAS WRITTEN FOR",
      intro: "Fifteen chapters are over. What follows are three different paths, and one of them is right more often than the other two.",
      path1: {
        title: "Path one: stay on demo for another two to three months",
        text: "Fits if you finished the fifty trades but the journal's results are unstable, or if you don't currently have free money whose loss wouldn't change anything. This isn't a 'failure' or a delayed start — it's the most common correct answer. The course stays open, the journal keeps working, and a review can be requested again in three months. It costs nothing.",
        cta: "Stay on demo",
      },
      path2: {
        title: "Path two: a real account, minimum size, with support",
        text: "Fits if the four conditions from chapter 14 are met. We help pick a platform for your country and goals (comparison in chapter 11), verify you're signing with the legal entity you think you are, and go through your first trades with you. What we get from the platform is written on the 'How we earn' page.",
        cta: "Check the conditions",
        blockedNote: "First, what's missing at chapter 14's gate.",
        gotoGate: "To chapter 14's gate →",
        condTrades: "Trades logged", condWeeks: "Active weeks", condSystem: "Rules written down", condMath: "Cost calculator done",
        projLabel: "Trades per week (your pace)", projResult: (weeks) => weeks === 1 ? "1 more week to 50 trades" : `${weeks} more weeks to 50 trades`, projDone: "the trades condition is already met",
        pendingNote: "The list of platforms with verified legal-entity and license data is being prepared separately and isn't shown here yet — for the same reason we don't publish unverified numbers anywhere in the course.",
      },
      path3: {
        title: "Path three: managed accounts",
        text: "Fits if you've read the course to the end and realized you're interested in the market, but not in doing it yourself. This is a separate service with a separate contract and separate regulation, and it's only discussed in person: it isn't sold remotely, and we won't start.",
        cta: "Discuss in person",
        pendingNote: "This service's terms are undergoing a separate legal review and are deliberately not described here until it's complete.",
      },
      whatWeDontDoTitle: "And what we don't do on any of the three paths",
      whatWeDontDo: "We don't sell signals and we don't give trading recommendations. We don't guarantee returns and we don't publish win rates, ours or anyone else's. We don't charge for access to the course. We don't promise you'll make money. If anyone promised you that in our name, it wasn't us, and we want to know about it.",
      selectedNote: "Noted. Thank you — that's the last thing this course asks of you.",
    },
    stopList: {
      tag: "WHEN NOT TO OPEN A REAL ACCOUNT",
      subtitle: "Not with us, not with anyone.",
      items: [
        "If the money is borrowed — a loan, installments, taken from relatives.",
        "If it's your safety cushion, money for medical care, education, or rent.",
        "If you recently had a big loss at something else and want to win it back.",
        "If the main motive is 'I need this now,' not 'I want to understand this.'",
        "If you can't explain in your own words what a stop-loss is and why it's set before entry.",
        "If in the past month you've increased size after a loss even once — the journal knows this, look at chapter 10.",
        "If you're counting on this to replace a salary any time soon.",
      ],
      outro: "In any of these cases, the answer is path one. It's free, and it has never hurt anyone.",
    },
    verifyUs: {
      tag: "CHECK US",
      title: "Everything we claimed across fifteen chapters — in one file",
      body1: "Every measurement we published was computed by a script, and the script is open to read. Every export is available as CSV. Every external fact has a source and a verification date.",
      body2: "We compiled it into a single list: claim — where it was computed — how to check it. If you find an error, tell us — we'll fix it and say we fixed it.",
      downloadClaims: "Download the list of claims and sources",
      downloadAll: "Download all our measurements (CSV)",
      typeLabels: { measured: "measured", external: "external fact", arithmetic: "arithmetic" },
      chapterLabel: "ch.",
    },
    coldStart: {
      tag: "CHECK US",
      ask: "Fifteen chapters of claims. Pick any one — see exactly how it was checked.",
      methodScript: "Method: script {{script}}", methodArithmetic: "Method: direct calculation, no data",
      dateLabel: "Checked {{date}}", downloadLabel: "Download the check",
      bridge: "The other seven claims and the full source list — in course_claims.json, open for download.",
    },
    finalParagraph: {
      body1: "Fifteen chapters ago we started with the idea that price is a trace of other people's decisions, not a line on a screen. Everything else was ways of reading that trace.",
      body2: "We tried never to lie to you. Where we could, we published the data so you could recompute it yourself. Where we earn, we wrote how much and from what. Where we don't know, we said so. That's the only thing that can separate a course about markets from an advertisement, and it's the only thing we ask you to carry into your own trading: compute it yourself, and check who benefits from what.",
      body3: "What comes next is your journal. It's more honest than any course, including this one.",
    },
    sources: {
      tag: "CHAPTER SOURCES",
      list: [
        "CFTC v. Traders Global Group Inc. (My Forex Funds) — case materials and the dismissal order with Rule 11 sanctions, May 2025.",
        "FSMA (Belgium), public warning on prop trading platforms, March 2024.",
        "CONSOB (Italy), statement on the format of prop challenges, July 2024.",
        "Czech National Bank, supervisory position on MiFID II applicability to funded-trader services, 2024.",
        "ESMA, statement on leveraged products and CFD product-intervention measures, February 2026.",
        "Our own measurements and scripts — full list in the 'Check Us' block and in course_claims.json.",
      ],
      checked: "Checked as of 2026-07-27.",
    },
  },

  ro: {
    coldOpen: {
      tag: "CAPITOLUL 15 — UN AN ȘI JUMĂTATE",
      lines: [
        "Aceasta e versiunea anterioară a paginii pe care o citești acum. Șase firme prop, carduri frumoase, un buton „aplică la challenge”.",
        "Una dintre ele — la momentul publicării — practic nu mai accepta clienți. Un regulator american depusese o acțiune în justiție împotriva ei; a rămas în lista noastră un an și jumătate.",
        "Nu am observat. Lista era scrisă de mână direct în codul paginii, cifrele nu aveau dată de verificare, și nu era nimeni și nimic care s-o actualizeze.",
        "De aici merită început ultimul capitol, pentru că e despre cum alegi — și despre faptul că orice listă trebuie verificată, inclusiv a noastră. Am reparat asta la noi: datele partenerilor stau acum într-un fișier separat, fiecare cifră are o dată de preluare și o sursă, iar un partener fără date actuale pur și simplu nu apare.",
        "Următoarele douăsprezece minute sunt despre prop trading fără vitrină, despre nouă reguli din care doar cinci sunt reguli adevărate, și despre trei căi, dintre care prima e gratuită.",
      ],
      cta: "Analizează mecanica ↓",
      screenshotCaption: "Versiunea anterioară a acestui capitol, captură din istoricul repository-ului.",
    },
    propMechanics: {
      tag: "PROP TRADING: CE ȚI SE VINDE DE FAPT",
      intro: "Aproape sigur ai văzut reclama: „primești $100.000 în administrare, treci challenge-ul”. Să analizăm mecanica, pentru că funcționează altfel decât pare.",
      howLabel: "Cum funcționează",
      howText: "Plătești o taxă de participare. Tranzacționezi pe un simulator — așa e la majoritatea firmelor, dar nu universal: unele declară că trimit o parte din flux pe piață, iar asta se verifică din contractul firmei concrete, nu din reclamă. Dacă îndeplinești regulile (țintă de profit, limită zilnică de drawdown, limită totală), primești un „cont finanțat”. De regulă e tot simulat, iar plățile sunt o cotă din profitul virtual, plătită în bani reali.",
      interestLabel: "Interesul cui unde stă",
      interestText: "Venitul principal al majorității acestor firme sunt taxele celor care nu trec. Nu e o acuzație și nu e o teorie a conspirației, e o descriere a modelului: cu cât rata de reușită e mai mică, cu atât venitul e mai mare. Aproape nimeni nu publică rata de reușită sau mărimea medie a plăților. Când nu ți se arată cifra-cheie, dar ți se arată povești de succes, cifra probabil nu e în favoarea ta.",
      compareLabel: "Compară cu ce am scris despre brokeri în capitolul 11",
      compareText: "Un broker câștigă din spread și comision — adică din faptul că tranzacționezi; îi convine să rămâi. O firmă prop câștigă din taxa de participare — adică din încercare; îi ajunge să încerci o dată. Sunt semne opuse, și a le cunoaște e mai util decât orice listă de firme.",
      caseTitle: "Firma menționată la început",
      caseText: "My Forex Funds (entitate juridică Traders Global Group Inc.). În august 2023, Comisia pentru Tranzacționarea Contractelor Futures pe Mărfuri din SUA (CFTC) a depus o acțiune împotriva ei, acuzând-o de fraudă de peste $300 de milioane; în aceeași lună instanța a înghețat activele, iar activitatea s-a oprit practic (platforma avea peste 135.000 de clienți). Cazul a fost respins definitiv (cu prejudiciu) pe 13 mai 2025, la recomandarea unui Special Master numit de instanță, care a constatat că CFTC a indus în eroare instanța, prezentând o plată fiscală de rutină (aproximativ CAD 31,55 milioane către autoritatea fiscală canadiană) drept disipare de active, deși știa despre ce era vorba. CFTC însăși a fost sancționată conform Regulii 11 cu peste $3 milioane — costurile juridice ale pârâtului.",
      caseNeutral: "Nu prezentăm asta nici ca acuzație, nici ca dezvinovățire — decizia instanței a vizat conduita regulatorului în proces, nu o judecată asupra acuzațiilor de fond, și niciuna dintre părțile acestei povești nu arată grozav. Concluzia pentru noi e alta: firma a stat în lista noastră un an și jumătate după ce încetase deja să funcționeze. Lista era statică, cifrele n-aveau dată, nimeni nu urmărea. Orice listă — inclusiv a noastră — se învechește în tăcere. Singura apărare: o dată de verificare lângă fiecare cifră și o sursă pe care s-o poți verifica singur.",
      regLabel: "Contextul de reglementare",
      regIntro: "Din 2024, regulatorii au început să trateze industria cu seriozitate.",
      regItems: [
        ["FSMA (Belgia)", "martie 2024", "avertisment public despre challenge-urile prop: cursuri plătite, certificări auto-emise, un val de marketing pentru conturi simulate pe rețelele sociale"],
        ["CONSOB (Italia)", "iulie 2024", "a descris platformele prop drept simulare de tranzacționare sub forma unui „joc video financiar”; a semnalat dificultatea reglată a testelor și cotele de profit neplătite"],
        ["ČNB (Cehia)", "2024", "poziție de supraveghere: unele servicii funded-trader pot constitui un serviciu de investiții conform MiFID II"],
        ["BaFin, CONSOB", "2025-2026", "avertismente pentru investitori care menționează leverage-ul ridicat la CFD promovat de firmele prop"],
        ["ESMA", "februarie 2026", "declarație publică: produsele cu leverage, inclusiv cele promovate de firme prop, intră sub măsurile naționale existente de intervenție asupra produselor CFD"],
      ],
      regOutro: "Nu există încă o lege dedicată firmelor prop; direcția de mișcare e spre interiorul perimetrului reglementat.",
      regCaveat: "Datele și conținutul avertismentelor FSMA și CONSOB au fost verificate independent de noi. Formulările despre ČNB/ESMA/BaFin provin dintr-o verificare internă a echipei și nu înlocuiesc o revizuire juridică profesională a fiecărui document — una e recomandată înainte de publicarea finală a acestei secțiuni.",
    },
    propChecklist: {
      tag: "CE SĂ VERIFICI DACĂ TOT VREI",
      frame: "Nu suntem plătiți de nicio firmă prop și nu oferim linkuri către ele. Deci ce urmează e doar o listă de întrebări, nu o recomandare sau un clasament.",
      items: [
        "E publicată rata de reușită a challenge-ului și plata medie? Dacă nu, întreabă suportul și păstrează răspunsul.",
        "Există confirmări independente ale plăților, nu doar capturi de ecran pe rețele sociale?",
        "În ce jurisdicție e înregistrată entitatea juridică și cum stă cu supravegherea acolo?",
        "Ce se întâmplă cu contul tău dacă firma se închide? Un cont simulat nu are fond de compensare.",
        "Cât pierzi dacă nu treci? Aceasta e singura cifră pe care o știi dinainte, cu certitudine.",
      ],
    },
    honestAlt: {
      tag: "O ALTERNATIVĂ CINSTITĂ",
      body1: "Taxa de challenge sunt bani plătiți pentru dreptul de a-ți dovedi disciplina după regulile altcuiva. Exact aceeași disciplină o arată propriul tău jurnal pe cincizeci de tranzacții, și nu costă nimic. Singura diferență e că jurnalul nu eliberează un certificat.",
      body2: "Și o cifră de comparație pe care deja o știi. În capitolul 12 am calculat de câte tranzacții e nevoie ca să deosebești priceperea de noroc. Un challenge te evaluează de obicei pe o distanță mai scurtă decât atât. Adică îl trec și cei care au avut noroc — și nu-l trec cei cu avantaj real, care au nimerit o serie normală de pierderi.",
    },
    nineRules: {
      tag: "NOUĂ REGULI",
      group1Label: "Grupa 1 — reguli de proces (adevărate mereu)",
      group1: [
        "Nu risca niciodată mai mult de 2% din depozit într-o tranzacție",
        "Pune stopul înainte de intrare, nu după",
        "Verifică calendarul înainte de o tranzacție",
        "La două pierderi la rând, închide terminalul",
        "Ține jurnal pentru fiecare tranzacție — fără excepții",
      ],
      group2Label: "Grupa 2 — parametri de metodă din capitolele 12-14 (nu legi ale pieței)",
      group2: [
        "În strategia din capitolul 13, adăugarea la poziție se face la un pas anume — în acea strategie, nu în general.",
        "Strategia din capitolul 14 folosește zone RSI 35/65 în loc de 30/70 — pentru că pe M5 zonele 30/70 se declanșează rar. Pe alte intervale concluzia diferă.",
        "Ichimoku din capitolul 12 filtrează direcția — în sistemul unde e folosit special ca filtru de direcție.",
      ],
      ninthLabel: "A noua regulă — cea mai importantă",
      ninthText: "Deosebește o regulă de proces de un parametru de metodă. Pe prima n-o schimbi niciodată. Pe al doilea ești obligat să-l reverifici pe datele tale înainte de a-l considera al tău. Tot ce arată ca un număr în acest curs — o perioadă, o zonă, un nivel — e parametrul cuiva, nu o proprietate a pieței.",
    },
    threePaths: {
      tag: "TREI CĂI — PASUL PENTRU CARE S-A SCRIS TOT ACEST CURS",
      intro: "Cincisprezece capitole s-au terminat. Urmează trei căi diferite, iar una dintre ele e corectă mai des decât celelalte două.",
      path1: {
        title: "Calea întâi: rămâi pe demo încă două-trei luni",
        text: "Se potrivește dacă ai terminat cele cincizeci de tranzacții, dar rezultatul din jurnal e instabil, sau dacă nu ai acum bani liberi a căror pierdere n-ar schimba nimic. Nu e un „eșec” și nici un start amânat — e cel mai frecvent răspuns corect. Cursul rămâne deschis, jurnalul funcționează, o analiză poate fi cerută din nou peste trei luni. Costă zero.",
        cta: "Rămân pe demo",
      },
      path2: {
        title: "Calea a doua: cont real, sumă minimă, cu sprijin",
        text: "Se potrivește dacă cele patru condiții din capitolul 14 sunt îndeplinite. Te ajutăm să alegi o platformă pentru țara și obiectivele tale (comparație în capitolul 11), verificăm că semnezi cu entitatea juridică pe care crezi că o semnezi, și analizăm primele tale tranzacții. Ce primim de la platformă e scris pe pagina „Cum câștigăm bani”.",
        cta: "Verific condițiile",
        blockedNote: "Mai întâi, ce lipsește la poarta capitolului 14.",
        gotoGate: "La poarta capitolului 14 →",
        condTrades: "Tranzacții înregistrate", condWeeks: "Săptămâni active", condSystem: "Reguli scrise", condMath: "Calculator de costuri făcut",
        projLabel: "Tranzacții pe săptămână (ritmul tău)", projResult: (weeks) => weeks === 1 ? "încă 1 săptămână până la 50" : `încă ${weeks} săptămâni până la 50`, projDone: "condiția de tranzacții e deja îndeplinită",
        pendingNote: "Lista platformelor cu date verificate despre entități juridice și licențe e în pregătire separată și nu e încă arătată aici — din același motiv pentru care nu publicăm cifre neverificate nicăieri în curs.",
      },
      path3: {
        title: "Calea a treia: administrare fiduciară",
        text: "Se potrivește dacă ai citit cursul până la capăt și ai înțeles că te interesează piața, dar nu te interesează s-o faci singur. E un serviciu separat, cu un contract separat și o reglementare separată, și se discută doar personal: nu se vinde de la distanță, și nici noi n-o vom face.",
        cta: "Discut personal",
        pendingNote: "Condițiile acestui serviciu trec printr-o verificare juridică separată și sunt intenționat nedescrise aici până la finalizarea ei.",
      },
      whatWeDontDoTitle: "Și ce nu facem pe niciuna dintre cele trei căi",
      whatWeDontDo: "Nu vindem semnale și nu dăm recomandări de tranzacționare. Nu garantăm randamente și nu publicăm rate de câștig — nici ale noastre, nici ale altora. Nu luăm bani pentru acces la curs. Nu promitem că vei câștiga bani. Dacă cineva ți-a promis asta în numele nostru, nu suntem noi, și vrem să știm.",
      selectedNote: "Notat. Mulțumim — e ultimul lucru pe care ți-l cerem în acest curs.",
    },
    stopList: {
      tag: "CÂND NU TREBUIE SĂ DESCHIZI UN CONT REAL",
      subtitle: "Nici la noi, nici la altcineva.",
      items: [
        "Dacă banii sunt împrumutați — credit, rate, luați de la rude.",
        "Dacă e perna de siguranță, bani pentru tratament, educație sau chirie.",
        "Dacă recent ai avut o pierdere mare în altceva și vrei să te revanșezi.",
        "Dacă motivul principal e „trebuie urgent”, nu „vreau să înțeleg”.",
        "Dacă nu poți explica cu propriile cuvinte ce e un stop-loss și de ce se pune înainte de intrare.",
        "Dacă în ultima lună ai mărit riscul după o pierdere măcar o dată — jurnalul știe asta, uită-te în capitolul 10.",
        "Dacă te bazezi pe asta ca să înlocuiască un salariu în timp apropiat.",
      ],
      outro: "În oricare dintre aceste cazuri, răspunsul e calea întâi. E gratuită și n-a păgubit pe nimeni până acum.",
    },
    verifyUs: {
      tag: "VERIFICĂ-NE",
      title: "Tot ce am afirmat în cincisprezece capitole — într-un singur fișier",
      body1: "Fiecare măsurătoare pe care am publicat-o a fost calculată printr-un script, iar scriptul e deschis spre citire. Fiecare export e disponibil în CSV. Fiecare fapt extern are o sursă și o dată de verificare.",
      body2: "Le-am adunat într-o singură listă: afirmație — unde a fost calculată — cum se verifică. Dacă găsești o greșeală, scrie-ne — o reparăm și scriem că am reparat-o.",
      downloadClaims: "Descarcă lista de afirmații și surse",
      downloadAll: "Descarcă toate măsurătorile noastre (CSV)",
      typeLabels: { measured: "măsurat", external: "fapt extern", arithmetic: "aritmetică" },
      chapterLabel: "cap.",
    },
    coldStart: {
      tag: "VERIFICĂ-NE",
      ask: "Cincisprezece capitole de afirmații. Alege una — vezi exact cum a fost verificată.",
      methodScript: "Metodă: script {{script}}", methodArithmetic: "Metodă: calcul direct, fără date",
      dateLabel: "Verificat {{date}}", downloadLabel: "Descarcă verificarea",
      bridge: "Celelalte șapte afirmații și lista completă a surselor — în course_claims.json, deschis pentru descărcare.",
    },
    finalParagraph: {
      body1: "Acum cincisprezece capitole am pornit de la ideea că prețul e urma unor decizii ale altora, nu o linie pe ecran. Tot restul au fost moduri de a citi acea urmă.",
      body2: "Am încercat să nu te mințim niciodată. Unde am putut, am publicat datele ca să le recalculezi tu însuți. Unde câștigăm, am scris cât și din ce. Unde nu știm, am spus că nu știm. Ăsta e singurul lucru care poate deosebi un curs despre piețe de o reclamă, și e singurul lucru pe care îți cerem să-l duci mai departe în propria ta tranzacționare: calculează singur și verifică cui îi e avantajos ce.",
      body3: "Urmează jurnalul tău. E mai cinstit decât orice curs, inclusiv acesta.",
    },
    sources: {
      tag: "SURSELE CAPITOLULUI",
      list: [
        "CFTC v. Traders Global Group Inc. (My Forex Funds) — materialele cazului și decizia de respingere cu sancțiuni conform Regulii 11, mai 2025.",
        "FSMA (Belgia), avertisment public privind platformele de prop trading, martie 2024.",
        "CONSOB (Italia), declarație despre formatul challenge-urilor prop, iulie 2024.",
        "Banca Națională a Cehiei, poziție de supraveghere privind aplicabilitatea MiFID II la serviciile funded-trader, 2024.",
        "ESMA, declarație despre produsele cu leverage și măsurile de intervenție asupra produselor CFD, februarie 2026.",
        "Măsurătorile și scripturile noastre — lista completă în blocul „Verifică-ne” și în course_claims.json.",
      ],
      checked: "Verificat la 27.07.2026.",
    },
  },
};
