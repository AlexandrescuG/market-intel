/* Хроно-машина главы 2 «Крупнейшие организации» (SPEC_edu_level2_central_banks.md §3.3, 23.07.2026).
   Название переименовано 27.07.2026 по фидбэку пользователя -- «Глобальные кукловоды»
   звучало оскорбительно (см. живой edu_book_2.html, тот же рефакторинг).
   Отдельный набор данных от chrono.js (глава 1) — не трогаем рабочий, живой код главы 1.
   16 станций, после 1929 — 13 станций, плотность к настоящему как в главе 1.
   window.Chrono2Stations = {ru:[16], ro:[16], en:[16]}.
   Некоторые illustration-ключи переиспользуют ассеты главы 1 (window.ChronoStationArt/Image из chrono.js) —
   тот же исторический эпизод, та же картинка: "1929_crowd" (ст.3), "1987_blackmonday" (ст.7),
   "2008_lehman" (ст.9), "2020_covid" (ст.13). Остальные — новые SVG-плейсхолдеры ниже,
   реальные фото — следующая фаза (только для ст. 1-9, спека §7 явно требует НЕ ставить пресс-фото
   современных ЦБ на ст.10-16 — юридический риск, вместо этого свои графики). */
(function(){
  var STATIONS = {

    ru: [
      {
        id: "1907", year: "1907", place: "Нью-Йорк",
        title: "Один человек вместо центробанка",
        body: "Паника 1907 года: банки падают домино, биржа теряет половину стоимости, а центрального банка в США просто нет. Частный банкир Дж. П. Морган запирает крупнейших финансистов Нью-Йорка в своей библиотеке и не выпускает, пока те не скидываются на спасение системы. Работает. Но у всех остаётся один вопрос: а если в следующий раз Моргана не будет?",
        fact: "Заперты они были в буквальном смысле — Морган забрал ключ от двери библиотеки.",
        legend: null, source: "SPEC_edu_level2_central_banks.md", illustration: "1907_morgan"
      },
      {
        id: "1913", year: "1913", place: "Вашингтон",
        title: "Рождение ФРС",
        body: "23 декабря 1913 года президент Вильсон подписывает Federal Reserve Act. Америка — последней из великих держав — получает центральный банк: «кредитора последней инстанции», который должен гасить паники деньгами, а не харизмой одного банкира. Ирония станции: институт, созданный предотвращать крахи, через 16 лет проспит величайший из них.",
        fact: "ФРС — не министерство: это система из 12 региональных банков, формально независимая от правительства. Именно за независимость её будут атаковать президенты — от Джонсона до наших дней.",
        legend: null, source: "Federal Reserve Act, 1913", illustration: "1913_fed"
      },
      {
        id: "1929", year: "1929–1933", place: "Нью-Йорк",
        title: "Первый экзамен — провален",
        body: "Крах 1929-го ФРС встречает… ужесточением: боясь спекулянтов и защищая золотой стандарт, она даёт денежной массе сжаться на треть. Рецессия превращается в Великую депрессию: −89% по Dow, 9000 закрытых банков. Милтон Фридман позже докажет: главная вина — не крах, а реакция на него. В 2002-м член совета ФРС по имени Бен Бернанке публично скажет Фридману: «Вы правы, это сделали мы. Простите — больше не повторим». Через шесть лет ему придётся доказывать это делом.",
        fact: "Слова Бернанке — реальная цитата с 90-летия Фридмана, 2002 год.",
        legend: null, source: "Milton Friedman, \"A Monetary History of the United States\"", illustration: "1929_crowd"
      },
      {
        id: "1944", year: "1944", place: "Бреттон-Вудс",
        title: "Бреттон-Вудс: валюты по назначению",
        body: "Пока в Европе война, 44 державы в горном отеле проектируют послевоенные деньги: все валюты фиксируются к доллару, доллар — к золоту, $35 за унцию. Валютных графиков в нашем понимании не существует — курсы назначены. Тридцать лет мировые деньги живут без волатильности… и без свободы.",
        fact: "Там же созданы МВФ и Всемирный банк — «дети Бреттон-Вудса». СССР участвовал в конференции, но соглашение так и не ратифицировал.",
        legend: null, source: "Bretton Woods Conference, 1944", illustration: "1944_bretton"
      },
      {
        id: "1971", year: "1971", place: "Вашингтон",
        title: "Никсон-шок: включили графики",
        body: "Доллару перестаёт хватать золота (война во Вьетнаме, дефициты), и 15 августа 1971-го Никсон «временно закрывает золотое окно». Курсы отпускают — валюты впервые плавают свободно. Родился форекс: каждый EURUSD-бар твоего терминала — потомок того вечера. Золото, отвязанное от $35, за десятилетие делает 20x.",
        fact: "Слово «временно» из речи Никсона действует 55-й год. В том же 1971-м открывается NASDAQ — первая электронная биржа: эпоха плавающих цен потребовала скорости.",
        legend: null, source: "Nixon Presidential Library", illustration: "1971_nixon"
      },
      {
        id: "1980", year: "1980", place: "Вашингтон",
        title: "Волкер: ставка 20%",
        body: "Инфляция в США — 14% и растёт, доллару не верит никто. Пол Волкер поднимает ставку до 20% (!) и держит, пока инфляция не ломается, — ценой двойной рецессии и проклятий на лужайке перед ФРС: фермеры блокировали здание тракторами. С тех пор каждое «ястребиное» решение любого ЦБ мира сравнивают с волкеровским.",
        fact: "Ипотека в США при Волкере стоила 18% годовых.",
        legend: null, source: "Federal Reserve History", illustration: "1980_volcker"
      },
      {
        id: "1987", year: "1987", place: "Нью-Йорк",
        title: "Рождение «Greenspan put»",
        body: "Чёрный понедельник, −22.6% за день. Наутро новый глава ФРС Алан Гринспен выпускает заявление в одну строку: ФРС «готова служить источником ликвидности для экономики и финансовой системы». Рынок разворачивается. Так родилась вера, определившая следующие 35 лет: «что бы ни случилось — ФРС спасёт». Трейдеры назовут её «пут-опционом Гринспена» — бесплатной страховкой от обвала.",
        fact: "Заявление 20.10.1987 — 30 слов. Ущерб понедельника — ~$500 млрд.",
        legend: null, source: "Federal Reserve History · Wikipedia", illustration: "1987_blackmonday"
      },
      {
        id: "1998", year: "1998", place: "Нью-Йорк",
        title: "LTCM: гении с плечом 25:1",
        body: "Хедж-фонд Long-Term Capital Management — два нобелевских лауреата в совете, лучшие математики Уолл-стрит, плечо 25:1 и уверенность, что «такое отклонение случается раз в миллиард лет». Дефолт России-1998 оказывается тем самым «разом». Фонд теряет $4.6 млрд за месяцы; ФРС собирает банки на спасение — не деньгами налогоплательщиков, но своим авторитетом.",
        fact: "Доходность LTCM до краха — 40% в год; после — минус всё.",
        legend: null, source: "Roger Lowenstein, \"When Genius Failed\"", illustration: "1998_ltcm"
      },
      {
        id: "2008", year: "2008", place: "Вашингтон",
        title: "Ноль и печатный станок",
        body: "Lehman исчезает за выходные, система замерзает. Бернанке — тот самый ученик Фридмана — исполняет обещание: 16 декабря 2008-го ставка впервые в истории США — 0–0.25%, запускается QE: ФРС покупает активы напечатанными деньгами. Начинается 14-летняя эпоха бесплатных денег: всё, что растёт с 2009 по 2021 — акции, недвижимость, крипта, — растёт в этой воде.",
        fact: "Баланс ФРС за эпоху QE вырос с $0.9 трлн до $9 трлн.",
        legend: null, source: "Federal Reserve H.4.1", illustration: "2008_lehman"
      },
      {
        id: "2012", year: "2012", place: "Франкфурт",
        title: "Три слова Драги",
        body: "Еврозона трещит: доходность облигаций Италии и Испании — на уровнях дефолта. 26 июля 2012-го Марио Драги произносит: «ЕЦБ готов сделать всё, что потребуется (whatever it takes), чтобы сохранить евро. И поверьте — этого будет достаточно». Кризис заканчивается в этот момент. Без единого потраченного евро. Вербальная интервенция — самое дешёвое и самое мощное оружие ЦБ: рынки торгуют не деньги, а ожидания.",
        fact: "Программу OMT, о которой шла речь, так ни разу и не пришлось использовать.",
        legend: null, source: "European Central Bank, речь 26.07.2012", illustration: "2012_draghi"
      },
      {
        id: "2015", year: "2015", place: "Цюрих",
        title: "SNB: день, когда исчезла «гарантия»",
        body: "Три года швейцарский нацбанк держит «пол» 1.20 по EURCHF — официально, публично, «с неограниченной решимостью». 15 января 2015-го в 11:30 утра — пресс-релиз: пол отменён. За 20 минут франк дорожает на ~30%; стоп-лоссы исполняются на тысячи пунктов хуже уровней; брокер Alpari UK банкротится в тот же день. Урок, который дороже любого учебника: «гарантированный уровень» — это чьё-то обещание, а обещания отменяются пресс-релизом. Стоп-лосс защищает от движения цены, но не от исчезновения цены (гэп).",
        fact: "За день до отмены глава SNB называл пол «краеугольным камнем политики».",
        legend: null, source: "Swiss National Bank, пресс-релиз 15.01.2015", illustration: "2015_snb",
        scene: "ch2_snb_2015"
      },
      {
        id: "2016", year: "2016", place: "Токио",
        title: "Япония: деньги дешевле нуля",
        body: "BoJ вводит отрицательную ставку (январь 2016) — банки платят за право хранить деньги — и контроль кривой доходности YCC (сентябрь 2016): таргетируется уже не короткая ставка, а вся кривая. Мир перевернулся: к 2019-му на планете $17 трлн облигаций с отрицательной доходностью — кредитор доплачивает заёмщику. Дешёвая иена становится топливом мирового кэрри-трейда.",
        fact: "BoJ скупил столько ETF, что стал крупнейшим акционером японского рынка.",
        legend: null, source: "Bank of Japan", illustration: "2016_boj"
      },
      {
        id: "2020", year: "2020", place: "Вашингтон",
        title: "Два воскресенья ФРС",
        body: "COVID: 3 марта — экстренное снижение на 50 бп (впервые вне графика с 2008-го). Рынок растёт 15 минут и закрывает день −2.8%: экстренность прочитана как паника. 15 марта, в воскресенье вечером, — сразу до нуля + QE на $700 млрд; понедельник открывается −12%, дно — только 23 марта (−34% от пика). А потом безлимитное QE разворачивает всё: +100% за 18 месяцев.",
        fact: "Не новость двигает рынок, а контекст. И с ликвидностью ФРС не спорят — в обе стороны.",
        legend: null, source: "Federal Reserve, пресс-релизы 03.03/15.03.2020", illustration: "2020_covid",
        scene: "ch2_fed_2020"
      },
      {
        id: "2022", year: "2022–2023", place: "Вашингтон",
        title: "Расплата: самый быстрый цикл за 40 лет",
        body: "Счёт за бесплатные деньги приходит инфляцией 9%. ФРС отвечает по-волкеровски: 16 марта 2022 — первое повышение, дальше четыре подряд по +75 бп (такого не было с 1994-го), 0 → 5.25–5.50% за 16 месяцев. NASDAQ −33% за год, облигации — худший год за век, крипта −75%, «вечный портфель» 60/40 сломан. Кто читал календарь — знал каждый шаг заранее: цикл объявляли открытым текстом.",
        body_simple: "Деньги перестали быть бесплатными. С марта 2022 ФРС начала поднимать ставку и за 16 месяцев подняла с нуля до 5.25–5.50% — быстрее, чем когда-либо за 40 лет. Подорожало всё сразу: акции технологических компаний упали на треть, облигации показали худший год за столетие, криптовалюта — минус три четверти.",
        fact: "Четыре повышения подряд по +75 базисных пунктов — такого не было с 1994 года.",
        legend: null, source: "FOMC, официальный календарь заседаний", illustration: "2022_cycle",
        scene: "ch2_cycle_2022"
      },
      {
        id: "2024", year: "2024", place: "Токио",
        title: "Иена дёргает стоп-кран",
        body: "19 марта 2024-го BoJ выходит из отрицательных ставок — впервые за 17 лет. Топливо кэрри-трейда дорожает, и 5 августа 2024-го мир видит, что бывает, когда триллионное заимствование в иенах разворачивается: Nikkei −12.4% за день (худший день с 1987-го), волны — по всем рынкам планеты, VIX — в небо. В сентябре ФРС начинает снижение (−50 бп). Великий разворот эпох начался.",
        fact: "За три дня августовского шторма Nikkei прошёл вниз путь, на который у краха 1929-го ушло два месяца.",
        legend: null, source: "Bank of Japan · Nikkei историческая статистика", illustration: "2024_boj",
        scene: "ch2_carry_2024"
      },
      {
        id: "today", year: "Сейчас", place: "Везде",
        title: "Три центробанка тянут в разные стороны",
        body: "Июль 2026-го: ФРС — в цикле снижения (эффективная ставка ~3.6%); ЕЦБ 11 июня 2026-го впервые за три года поднял ставку (+25 бп, депозитная 2.25%) — война на Ближнем Востоке разогнала энергию и инфляцию; Банк Японии 16 июня поднял до 1.00% — максимум с 1995 года. Впервые за десятилетия три великих ЦБ движутся в трёх разных направлениях. Что делает золото, когда центробанки спорят между собой? Открой терминал — этот график живёт прямо сейчас.",
        fact: "Технологии и десятилетия менялись. Ставка как гравитация, действующая на всё сразу, — нет.",
        legend: null, source: "Federal Reserve H.15 · ECB · Bank of Japan (на 23.07.2026)", illustration: "today_ch2",
        scene: "ch2_now", bridge: true
      }
    ],

    ro: [
      {
        id: "1907", year: "1907", place: "New York",
        title: "Un singur om în locul unei bănci centrale",
        body: "Panica din 1907: băncile cad ca dominourile, bursa pierde jumătate din valoare, iar în SUA pur și simplu nu există bancă centrală. Bancherul privat J.P. Morgan îi încuie pe cei mai mari financiari din New York în biblioteca sa și nu-i lasă să plece până nu strâng bani pentru a salva sistemul. Funcționează. Dar tuturor le rămâne o singură întrebare: dacă data viitoare nu va exista un Morgan?",
        fact: "Au fost încuiați la propriu — Morgan a luat cheia ușii bibliotecii.",
        legend: null, source: "SPEC_edu_level2_central_banks.md", illustration: "1907_morgan"
      },
      {
        id: "1913", year: "1913", place: "Washington",
        title: "Nașterea Fed",
        body: "Pe 23 decembrie 1913, președintele Wilson semnează Federal Reserve Act. America — ultima dintre marile puteri — capătă o bancă centrală: un „creditor de ultimă instanță” care trebuie să stingă panicile cu bani, nu cu charisma unui singur bancher. Ironia stației: instituția creată pentru a preveni prăbușirile va dormi peste 16 ani chiar în timpul celei mai mari dintre ele.",
        fact: "Fed nu e un minister: e un sistem de 12 bănci regionale, formal independent de guvern. Tocmai pentru această independență va fi atacată de președinți — de la Johnson până azi.",
        legend: null, source: "Federal Reserve Act, 1913", illustration: "1913_fed"
      },
      {
        id: "1929", year: "1929–1933", place: "New York",
        title: "Primul examen — picat",
        body: "Prăbușirea din 1929 e întâmpinată de Fed cu… înăsprire: temându-se de speculanți și apărând standardul aur, lasă masa monetară să se contracte cu o treime. Recesiunea devine Marea Depresiune: −89% pentru Dow, 9000 de bănci închise. Milton Friedman va dovedi mai târziu: vina principală n-a fost prăbușirea, ci reacția la ea. În 2002, un membru al consiliului Fed pe nume Ben Bernanke îi va spune public lui Friedman: „Aveți dreptate, noi am făcut-o. Ne pare rău — nu se va mai repeta”. Șase ani mai târziu va trebui s-o dovedească prin fapte.",
        fact: "Cuvintele lui Bernanke sunt un citat real de la aniversarea a 90 de ani a lui Friedman, 2002.",
        legend: null, source: "Milton Friedman, \"A Monetary History of the United States\"", illustration: "1929_crowd"
      },
      {
        id: "1944", year: "1944", place: "Bretton Woods",
        title: "Bretton Woods: monede pe bază de numire",
        body: "În timp ce în Europa e război, 44 de puteri proiectează într-un hotel montan banii postbelici: toate monedele sunt fixate la dolar, dolarul — la aur, 35$ uncia. Grafice valutare în sensul nostru nu există — cursurile sunt numite. Timp de treizeci de ani, banii lumii trăiesc fără volatilitate… și fără libertate.",
        fact: "Tot atunci sunt create FMI și Banca Mondială — „copiii de la Bretton Woods”. URSS a participat la conferință, dar nu a ratificat niciodată acordul.",
        legend: null, source: "Conferința de la Bretton Woods, 1944", illustration: "1944_bretton"
      },
      {
        id: "1971", year: "1971", place: "Washington",
        title: "Șocul Nixon: s-au pornit graficele",
        body: "Dolarului nu-i mai ajunge aur (războiul din Vietnam, deficite), iar pe 15 august 1971 Nixon „închide temporar fereastra aurului”. Cursurile sunt eliberate — monedele plutesc liber pentru prima dată. S-a născut forex-ul: fiecare bară EURUSD din terminalul tău e urmașa acelei seri. Aurul, eliberat de cei 35$, face 20x într-un deceniu.",
        fact: "Cuvântul „temporar” din discursul lui Nixon e valabil de 55 de ani. Tot în 1971 se deschide NASDAQ — prima bursă electronică: era cursurilor flotante a cerut viteză.",
        legend: null, source: "Nixon Presidential Library", illustration: "1971_nixon"
      },
      {
        id: "1980", year: "1980", place: "Washington",
        title: "Volcker: dobânda 20%",
        body: "Inflația în SUA e 14% și crește, nimeni nu mai crede în dolar. Paul Volcker urcă dobânda la 20% (!) și o menține până se rupe inflația — cu prețul unei duble recesiuni și al blestemelor pe peluza din fața Fed: fermierii au blocat clădirea cu tractoare. De atunci, orice decizie „de șoim” a oricărei bănci centrale din lume e comparată cu cea a lui Volcker.",
        fact: "Ipoteca în SUA sub Volcker costa 18% pe an.",
        legend: null, source: "Federal Reserve History", illustration: "1980_volcker"
      },
      {
        id: "1987", year: "1987", place: "New York",
        title: "Nașterea „Greenspan put”",
        body: "Luni neagră, −22.6% într-o zi. A doua zi dimineață, noul șef Fed Alan Greenspan emite o declarație de o singură propoziție: Fed „este pregătită să servească drept sursă de lichiditate pentru economie și sistemul financiar”. Piața se întoarce. Așa s-a născut credința care a definit următorii 35 de ani: „orice s-ar întâmpla — Fed va salva”. Traderii o vor numi „Greenspan put” — asigurare gratuită împotriva prăbușirii.",
        fact: "Declarația din 20.10.1987 avea 30 de cuvinte. Pagubele de luni — ~500 de miliarde de dolari.",
        legend: null, source: "Federal Reserve History · Wikipedia", illustration: "1987_blackmonday"
      },
      {
        id: "1998", year: "1998", place: "New York",
        title: "LTCM: genii cu levier 25:1",
        body: "Fondul speculativ Long-Term Capital Management — doi laureați Nobel în consiliu, cei mai buni matematicieni de pe Wall Street, levier 25:1 și convingerea că „o astfel de abatere se întâmplă o dată la un miliard de ani”. Falimentul Rusiei din 1998 se dovedește a fi exact acel „o dată”. Fondul pierde 4.6 miliarde de dolari în câteva luni; Fed adună băncile pentru salvare — nu cu bani de la contribuabili, ci cu propria autoritate.",
        fact: "Randamentul LTCM înainte de prăbușire — 40% pe an; după — minus tot.",
        legend: null, source: "Roger Lowenstein, \"When Genius Failed\"", illustration: "1998_ltcm"
      },
      {
        id: "2008", year: "2008", place: "Washington",
        title: "Zero și tiparnița",
        body: "Lehman dispare într-un weekend, sistemul îngheață. Bernanke — chiar acel discipol al lui Friedman — își respectă promisiunea: pe 16 decembrie 2008, dobânda ajunge pentru prima dată în istoria SUA la 0–0.25%, se lansează QE: Fed cumpără active cu bani tipăriți. Începe o eră de 14 ani a banilor gratuiți: tot ce crește între 2009 și 2021 — acțiuni, imobiliare, cripto — crește în această apă.",
        fact: "Bilanțul Fed în era QE a crescut de la 0.9 la 9 trilioane de dolari.",
        legend: null, source: "Federal Reserve H.4.1", illustration: "2008_lehman"
      },
      {
        id: "2012", year: "2012", place: "Frankfurt",
        title: "Cele trei cuvinte ale lui Draghi",
        body: "Zona euro trosnește: randamentele obligațiunilor Italiei și Spaniei — la niveluri de faliment. Pe 26 iulie 2012, Mario Draghi rostește: „BCE este pregătită să facă orice este nevoie (whatever it takes) pentru a păstra euro. Și credeți-mă — va fi suficient”. Criza se termină chiar în acel moment. Fără a cheltui vreun euro. Intervenția verbală — cea mai ieftină și mai puternică armă a unei bănci centrale: piețele tranzacționează așteptări, nu bani.",
        fact: "Programul OMT, despre care era vorba, nu a trebuit folosit niciodată.",
        legend: null, source: "Banca Centrală Europeană, discurs 26.07.2012", illustration: "2012_draghi"
      },
      {
        id: "2015", year: "2015", place: "Zürich",
        title: "SNB: ziua în care a dispărut „garanția”",
        body: "Timp de trei ani, banca națională elvețiană menține un „prag” de 1.20 pentru EURCHF — oficial, public, „cu hotărâre nelimitată”. Pe 15 ianuarie 2015, la ora 11:30, un comunicat: pragul e anulat. În 20 de minute, francul se scumpește cu ~30%; stop-loss-urile se execută cu mii de pips mai rău decât nivelurile; brokerul Alpari UK dă faliment chiar în aceeași zi. Lecția care valorează mai mult decât orice manual: un „nivel garantat” e o promisiune a cuiva, iar promisiunile se anulează printr-un comunicat. Stop-loss-ul protejează de mișcarea prețului, dar nu de dispariția prețului (gap).",
        fact: "Cu o zi înainte de anulare, șeful SNB numea pragul „piatra de temelie a politicii”.",
        legend: null, source: "Banca Națională a Elveției, comunicat 15.01.2015", illustration: "2015_snb",
        scene: "ch2_snb_2015"
      },
      {
        id: "2016", year: "2016", place: "Tokyo",
        title: "Japonia: banii mai ieftini decât zero",
        body: "BoJ introduce dobânda negativă (ianuarie 2016) — băncile plătesc pentru dreptul de a păstra bani — și controlul curbei randamentelor YCC (septembrie 2016): nu mai e țintită doar dobânda scurtă, ci întreaga curbă. Lumea s-a răsturnat: până în 2019, pe planetă existau 17 trilioane de dolari în obligațiuni cu randament negativ — creditorul plătește debitorul. Yenul ieftin devine combustibilul carry trade-ului global.",
        fact: "BoJ a cumpărat atât de multe ETF-uri încât a devenit cel mai mare acționar al pieței japoneze.",
        legend: null, source: "Bank of Japan", illustration: "2016_boj"
      },
      {
        id: "2020", year: "2020", place: "Washington",
        title: "Cele două duminici ale Fed",
        body: "COVID: pe 3 martie, reducere de urgență cu 50 pb (prima dată în afara programului din 2008). Piața crește 15 minute și închide ziua cu −2.8%: urgența e citită drept panică. Pe 15 martie, duminică seara, direct la zero + QE de 700 de miliarde de dolari; luni se deschide cu −12%, minimul vine abia pe 23 martie (−34% de la vârf). Apoi QE nelimitat întoarce totul: +100% în 18 luni.",
        fact: "Nu știrea mișcă piața, ci contextul. Iar cu lichiditatea Fed nu te cerți — în ambele direcții.",
        legend: null, source: "Federal Reserve, comunicate 03.03/15.03.2020", illustration: "2020_covid",
        scene: "ch2_fed_2020"
      },
      {
        id: "2022", year: "2022–2023", place: "Washington",
        title: "Plata: cel mai rapid ciclu din ultimii 40 de ani",
        body: "Nota de plată pentru banii gratuiți vine sub formă de inflație de 9%. Fed răspunde în stil Volcker: 16 martie 2022 — prima majorare, apoi patru la rând de +75 pb (nu s-a mai întâmplat din 1994), 0 → 5.25–5.50% în 16 luni. NASDAQ −33% într-un an, obligațiunile — cel mai prost an din ultimul secol, cripto −75%, portofoliul „etern” 60/40 se rupe. Cine citea calendarul știa fiecare pas dinainte: ciclul a fost anunțat pe față.",
        body_simple: "Banii au încetat să mai fie gratuiți. Din martie 2022 Fed a început să majoreze dobânda și în 16 luni a dus-o de la zero la 5.25–5.50% — mai repede ca oricând în ultimii 40 de ani. S-a scumpit totul deodată: acțiunile tech au scăzut cu o treime, obligațiunile au avut cel mai prost an din ultimul secol, cripto — minus trei sferturi.",
        fact: "Patru majorări consecutive de +75 puncte de bază — nu s-a mai întâmplat din 1994.",
        legend: null, source: "FOMC, calendarul oficial al ședințelor", illustration: "2022_cycle",
        scene: "ch2_cycle_2022"
      },
      {
        id: "2024", year: "2024", place: "Tokyo",
        title: "Yenul trage frâna de urgență",
        body: "Pe 19 martie 2024, BoJ iese din dobânzile negative — prima dată în 17 ani. Combustibilul carry trade-ului se scumpește, iar pe 5 august 2024 lumea vede ce se întâmplă când un trilion de dolari împrumutat în yeni se întoarce: Nikkei −12.4% într-o zi (cea mai proastă zi din 1987), unde — pe toate piețele planetei, VIX — la cer. În septembrie, Fed începe reducerea (−50 pb). Marea răsturnare de epoci a început.",
        fact: "În cele trei zile ale furtunii din august, Nikkei a parcurs în jos un drum pentru care prăbușirea din 1929 a avut nevoie de două luni.",
        legend: null, source: "Bank of Japan · statistici istorice Nikkei", illustration: "2024_boj",
        scene: "ch2_carry_2024"
      },
      {
        id: "today", year: "Acum", place: "Peste tot",
        title: "Trei bănci centrale trag în direcții diferite",
        body: "Iulie 2026: Fed — în ciclu de reducere (dobânda efectivă ~3.6%); BCE, pe 11 iunie 2026, a majorat dobânda pentru prima dată în trei ani (+25 pb, dobânda de depozit 2.25%) — războiul din Orientul Mijlociu a accelerat energia și inflația; Banca Japoniei, pe 16 iunie, a urcat la 1.00% — maximul din 1995 încoace. Pentru prima dată în decenii, trei mari bănci centrale se mișcă în trei direcții diferite. Ce face aurul când băncile centrale se contrazic? Deschide terminalul — acest grafic trăiește chiar acum.",
        fact: "Tehnologiile și deceniile s-au schimbat. Dobânda, ca o gravitație care acționează asupra tuturor simultan — niciodată.",
        legend: null, source: "Federal Reserve H.15 · BCE · Bank of Japan (la 23.07.2026)", illustration: "today_ch2",
        scene: "ch2_now", bridge: true
      }
    ],

    en: [
      {
        id: "1907", year: "1907", place: "New York",
        title: "One man instead of a central bank",
        body: "The Panic of 1907: banks fall like dominoes, the market loses half its value, and the US simply has no central bank. Private banker J.P. Morgan locks New York's biggest financiers in his library and won't let them out until they pool money to save the system. It works. But everyone's left with one question: what if next time there's no Morgan?",
        fact: "They were locked in literally — Morgan took the key to the library door.",
        legend: null, source: "SPEC_edu_level2_central_banks.md", illustration: "1907_morgan"
      },
      {
        id: "1913", year: "1913", place: "Washington",
        title: "The birth of the Fed",
        body: "On December 23, 1913, President Wilson signs the Federal Reserve Act. America — last among the great powers — gets a central bank: a \"lender of last resort\" meant to put out panics with money, not one banker's charisma. The station's irony: an institution built to prevent crashes will sleep through the greatest one 16 years later.",
        fact: "The Fed isn't a ministry — it's a system of 12 regional banks, formally independent of the government. It's exactly that independence presidents will attack it over, from Johnson to today.",
        legend: null, source: "Federal Reserve Act, 1913", illustration: "1913_fed"
      },
      {
        id: "1929", year: "1929–1933", place: "New York",
        title: "The first exam — failed",
        body: "The Fed meets the 1929 crash with… tightening: fearing speculators and defending the gold standard, it lets the money supply shrink by a third. The recession becomes the Great Depression: Dow −89%, 9,000 banks closed. Milton Friedman will later prove the real fault wasn't the crash but the response to it. In 2002, a Fed governor named Ben Bernanke will publicly tell Friedman: \"You're right, we did it. We're sorry — we won't do it again.\" Six years later he'll have to prove it in practice.",
        fact: "Bernanke's words are a real quote, from Friedman's 90th birthday, 2002.",
        legend: null, source: "Milton Friedman, \"A Monetary History of the United States\"", illustration: "1929_crowd"
      },
      {
        id: "1944", year: "1944", place: "Bretton Woods",
        title: "Bretton Woods: currencies by decree",
        body: "While war still rages in Europe, 44 powers design the postwar monetary system at a mountain hotel: every currency is pegged to the dollar, the dollar to gold at $35 an ounce. Currency charts in our sense don't exist — rates are assigned. For thirty years, the world's money lives without volatility… and without freedom.",
        fact: "The IMF and World Bank are created at the same conference — the \"children of Bretton Woods.\" The USSR took part but never ratified the agreement.",
        legend: null, source: "Bretton Woods Conference, 1944", illustration: "1944_bretton"
      },
      {
        id: "1971", year: "1971", place: "Washington",
        title: "The Nixon Shock: the charts turn on",
        body: "The dollar runs short of gold (the Vietnam War, deficits), and on August 15, 1971, Nixon \"temporarily\" closes the gold window. Rates are set free — currencies float against each other for the first time. Forex is born: every EURUSD bar on your terminal descends from that evening. Gold, freed from $35, does 20x within a decade.",
        fact: "The word \"temporarily\" from Nixon's speech is in its 55th year. That same year NASDAQ opens — the first electronic exchange: the age of floating prices demanded speed.",
        legend: null, source: "Nixon Presidential Library", illustration: "1971_nixon"
      },
      {
        id: "1980", year: "1980", place: "Washington",
        title: "Volcker: a 20% rate",
        body: "US inflation is 14% and rising; nobody trusts the dollar. Paul Volcker takes the rate to 20% (!) and holds it until inflation breaks — at the cost of a double-dip recession and curses on the Fed's front lawn, where farmers blocked the building with tractors. Every \"hawkish\" decision by any central bank since gets compared to Volcker's.",
        fact: "US mortgages under Volcker cost 18% a year.",
        legend: null, source: "Federal Reserve History", illustration: "1980_volcker"
      },
      {
        id: "1987", year: "1987", place: "New York",
        title: "The birth of the \"Greenspan put\"",
        body: "Black Monday, −22.6% in a day. The next morning, new Fed chair Alan Greenspan issues a one-line statement: the Fed \"stands ready to serve as a source of liquidity to support the economic and financial system.\" The market turns around. So was born a belief that defined the next 35 years: \"whatever happens, the Fed will save it.\" Traders will call it the \"Greenspan put\" — free crash insurance.",
        fact: "The 10/20/1987 statement was 30 words. Monday's damage: roughly $500 billion.",
        legend: null, source: "Federal Reserve History · Wikipedia", illustration: "1987_blackmonday"
      },
      {
        id: "1998", year: "1998", place: "New York",
        title: "LTCM: geniuses with 25:1 leverage",
        body: "Hedge fund Long-Term Capital Management: two Nobel laureates on the board, Wall Street's best mathematicians, 25:1 leverage, and confidence that \"a deviation like this happens once in a billion years.\" Russia's 1998 default turns out to be that very \"once.\" The fund loses $4.6 billion within months; the Fed gathers the banks to bail it out — not with taxpayer money, but with its own authority.",
        fact: "LTCM's return before the collapse: 40% a year; after: minus everything.",
        legend: null, source: "Roger Lowenstein, \"When Genius Failed\"", illustration: "1998_ltcm"
      },
      {
        id: "2008", year: "2008", place: "Washington",
        title: "Zero, and the printing press",
        body: "Lehman disappears over a weekend, the system freezes. Bernanke — that same student of Friedman's — keeps his promise: on December 16, 2008, the rate hits 0–0.25% for the first time in US history, and QE launches: the Fed buys assets with printed money. A 14-year era of free money begins — everything that rises from 2009 to 2021, stocks, real estate, crypto, rises in this water.",
        fact: "The Fed's balance sheet grew from $0.9 trillion to $9 trillion over the QE era.",
        legend: null, source: "Federal Reserve H.4.1", illustration: "2008_lehman"
      },
      {
        id: "2012", year: "2012", place: "Frankfurt",
        title: "Draghi's three words",
        body: "The eurozone is cracking: Italian and Spanish bond yields sit at default levels. On July 26, 2012, Mario Draghi says: \"The ECB is ready to do whatever it takes to preserve the euro. And believe me, it will be enough.\" The crisis ends at that exact moment. Without spending a single euro. Verbal intervention is a central bank's cheapest, most powerful weapon: markets trade expectations, not money.",
        fact: "The OMT program he referenced was never actually used, not once.",
        legend: null, source: "European Central Bank, speech, 07/26/2012", illustration: "2012_draghi"
      },
      {
        id: "2015", year: "2015", place: "Zurich",
        title: "SNB: the day the \"guarantee\" vanished",
        body: "For three years the Swiss National Bank holds a 1.20 \"floor\" on EURCHF — officially, publicly, \"with utmost determination.\" On January 15, 2015, at 11:30 a.m., a press release: the floor is scrapped. In 20 minutes the franc surges roughly 30%; stop-losses fill thousands of pips worse than their levels; broker Alpari UK goes bankrupt the same day. A lesson worth more than any textbook: a \"guaranteed level\" is somebody's promise, and promises get cancelled by press release. A stop-loss protects against price movement, not against price vanishing (a gap).",
        fact: "The day before scrapping it, the SNB's chairman called the floor \"a cornerstone of policy.\"",
        legend: null, source: "Swiss National Bank, press release 01/15/2015", illustration: "2015_snb",
        scene: "ch2_snb_2015"
      },
      {
        id: "2016", year: "2016", place: "Tokyo",
        title: "Japan: money cheaper than free",
        body: "The BoJ introduces a negative rate (January 2016) — banks pay for the privilege of holding money — and yield curve control, YCC (September 2016): now the whole curve is targeted, not just the short rate. The world turns upside down: by 2019 the planet holds $17 trillion in negative-yielding bonds — the lender pays the borrower. Cheap yen becomes the fuel of the global carry trade.",
        fact: "The BoJ bought so many ETFs it became the largest shareholder in the Japanese market.",
        legend: null, source: "Bank of Japan", illustration: "2016_boj"
      },
      {
        id: "2020", year: "2020", place: "Washington",
        title: "The Fed's two Sundays",
        body: "COVID: on March 3, an emergency 50bp cut (the first off-schedule move since 2008). The market rises for 15 minutes and closes the day −2.8%: the emergency is read as panic. On March 15, a Sunday evening, straight to zero plus $700 billion in QE; Monday opens −12%, the bottom doesn't come until March 23 (−34% from the peak). Then unlimited QE turns everything around: +100% in 18 months.",
        fact: "It isn't the headline that moves the market — it's the context. And you don't argue with Fed liquidity, in either direction.",
        legend: null, source: "Federal Reserve, press releases 03/03 and 03/15/2020", illustration: "2020_covid",
        scene: "ch2_fed_2020"
      },
      {
        id: "2022", year: "2022–2023", place: "Washington",
        title: "The reckoning: the fastest cycle in 40 years",
        body: "The bill for free money arrives as 9% inflation. The Fed answers Volcker-style: March 16, 2022 — the first hike, then four straight +75bp moves (unheard of since 1994), 0 to 5.25–5.50% in 16 months. NASDAQ −33% for the year, bonds have their worst year in a century, crypto −75%, the \"forever\" 60/40 portfolio breaks. Anyone reading the calendar knew every step in advance — the cycle was announced out loud.",
        body_simple: "Money stopped being free. Starting March 2022 the Fed began raising rates and over 16 months took them from zero to 5.25–5.50% — faster than at any point in 40 years. Everything got pricier at once: tech stocks fell by a third, bonds had their worst year in a century, crypto — down three-quarters.",
        fact: "Four consecutive +75 basis-point hikes — hadn't happened since 1994.",
        legend: null, source: "FOMC, official meeting calendar", illustration: "2022_cycle",
        scene: "ch2_cycle_2022"
      },
      {
        id: "2024", year: "2024", place: "Tokyo",
        title: "The yen pulls the emergency brake",
        body: "On March 19, 2024, the BoJ exits negative rates — for the first time in 17 years. Carry-trade fuel gets pricier, and on August 5, 2024, the world sees what happens when a trillion dollars borrowed in yen unwinds: the Nikkei falls −12.4% in a day (its worst day since 1987), with waves across every market on the planet and the VIX shooting skyward. In September the Fed starts cutting (−50bp). The great turn of eras has begun.",
        fact: "In the three days of the August storm, the Nikkei traveled downward the same distance that took the 1929 crash two months.",
        legend: null, source: "Bank of Japan · Nikkei historical data", illustration: "2024_boj",
        scene: "ch2_carry_2024"
      },
      {
        id: "today", year: "Right now", place: "Everywhere",
        title: "Three central banks pulling in different directions",
        body: "July 2026: the Fed is in a cutting cycle (effective rate ~3.6%); the ECB, on June 11, 2026, raised its rate for the first time in three years (+25bp, deposit rate 2.25%) as Middle East conflict drove up energy and inflation; the Bank of Japan, on June 16, hiked to 1.00% — the highest since 1995. For the first time in decades, the three great central banks are moving in three different directions. What does gold do when the central banks disagree with each other? Open the terminal — this chart is live right now.",
        fact: "The technology changed, the decades changed. Interest rates, as a gravity acting on everything at once — never.",
        legend: null, source: "Federal Reserve H.15 · ECB · Bank of Japan (as of 07/23/2026)", illustration: "today_ch2",
        scene: "ch2_now", bridge: true
      }
    ]

  };

  window.Chrono2Stations = STATIONS;
})();

/* Плейсхолдер-иллюстрации станций главы 2 — новые. 4 illustration-ключа (1929_crowd, 1987_blackmonday,
   2008_lehman, 2020_covid) переиспользуют window.ChronoStationArt/StationImage из chrono.js (тот же эпизод,
   та же картинка) — chrono.js должен грузиться на странице ДО этого файла. Станции 10-16 (2012→сегодня)
   по спеке §7 намеренно без фото (пресс-фото Драги/SNB/Уэды не PD) — остаются авторскими графиками/SVG. */
(function(){
  /* 🔴 ПАТТЕРНОВ #hatch И #hatch2 НЕ СУЩЕСТВОВАЛО НИГДЕ.
     Каждая рисованная станция начиналась с <rect fill="url(#hatch)"> на всю
     площадь и ещё одного — «пол» внизу кадра. Ни один из двух паттернов не
     объявлен ни в этом файле, ни в chrono.js, ни в разметке главы: поиск по
     всему web/ не находит ни одного `pattern id="hatch"`. По спецификации SVG
     недостижимая ссылка в fill означает, что элемент не рисуется вовсе, —
     то есть фон и пол отсутствовали на всех станциях с самого начала, молча
     и без ошибки в консоли. Задуманная фактура «архивной бумаги» не
     показывалась ни разу.
     Объявляем оба здесь же, внутри каждого кадра: так SVG остаётся
     самодостаточным и не зависит от того, что ещё есть на странице, — а
     зависимость от «где-то определено» и была причиной поломки. */
  // Паттерны объявлены в общем модуле — одно объявление на обе главы.
  function defs(){
    return window.SbfChronoFrames ? window.SbfChronoFrames.defs() : '';
  }
  function hatchBg(h){ h = h || 400; return defs() + '<rect width="720" height="'+h+'" fill="url(#hatch)"/>'; }
  function person(cx, cy, s){ s = s || 1; return '<ellipse cx="'+cx+'" cy="'+(cy+26*s)+'" rx="'+(12*s)+'" ry="'+(26*s)+'"/><circle cx="'+cx+'" cy="'+cy+'" r="'+(9*s)+'"/>'; }

  var ART = {
    "1907_morgan": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Библиотека Моргана, 1907">'
      + hatchBg() + '<rect y="300" width="720" height="100" fill="url(#hatch2)"/>'
      + '<g stroke="#6d6350" stroke-width="3" fill="#efe8d8"><rect x="200" y="90" width="320" height="220"/>'
      + '<path d="M240 310 V150 M290 310 V150 M340 310 V150 M390 310 V150 M440 310 V150 M480 310 V150"/></g>'
      + '<g stroke="#6d6350" stroke-width="3" fill="#5c5342"><rect x="330" y="220" width="60" height="90" fill="#3a3630"/></g>'
      + '<circle cx="360" cy="180" r="22" fill="none" stroke="#C9A227" stroke-width="3"/>'
      + '<circle cx="360" cy="180" r="6" fill="#C9A227"/><rect x="356" y="180" width="8" height="20" fill="#C9A227"/>'
      + '<g fill="#5c5342">' + person(590,300,0.9) + person(630,306,0.85) + '</g>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">библиотека Моргана, Нью-Йорк 1907</text></svg>';
    },
    "1913_fed": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Федеральный резервный акт, 1913">'
      + hatchBg() + '<rect y="300" width="720" height="100" fill="url(#hatch2)"/>'
      + '<g stroke="#6d6350" stroke-width="3" fill="#efe8d8"><rect x="150" y="140" width="420" height="160"/>'
      + '<path d="M190 300 v-120 a20 24 0 0 1 40 0 v120 Z M270 300 v-120 a20 24 0 0 1 40 0 v120 Z M350 300 v-120 a20 24 0 0 1 40 0 v120 Z M430 300 v-120 a20 24 0 0 1 40 0 v120 Z M490 300 v-120 a20 24 0 0 1 40 0 v120 Z"/>'
      + '<path d="M130 140 L360 80 L590 140 Z"/></g>'
      + '<circle cx="360" cy="110" r="16" fill="none" stroke="#C9A227" stroke-width="2.5"/>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">Federal Reserve Act, 23.12.1913</text></svg>';
    },
    "1944_bretton": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Бреттон-Вудская конференция, 1944">'
      + hatchBg() + '<rect y="290" width="720" height="110" fill="url(#hatch2)"/>'
      + '<path d="M0 220 L100 100 L180 220 Z M140 220 L260 60 L380 220 Z M330 220 L430 120 L520 220 Z M470 220 L600 90 L720 220 Z" fill="#cdd8b8" stroke="#6d6350" stroke-width="2.5"/>'
      + '<g stroke="#6d6350" stroke-width="3" fill="#efe8d8"><rect x="270" y="220" width="180" height="90"/><path d="M260 220 L360 170 L460 220 Z"/></g>'
      + '<circle cx="600" cy="150" r="34" fill="none" stroke="#6d6350" stroke-width="2.5"/>'
      + '<path d="M566 150 h68 M600 116 v68 M578 128 q22 22 44 0 M578 172 q22 -22 44 0" fill="none" stroke="#6d6350" stroke-width="1.6"/>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">Бреттон-Вудская конференция, 1944</text></svg>';
    },
    "1971_nixon": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Никсон-шок, 1971">'
      + hatchBg() + '<rect y="300" width="720" height="100" fill="url(#hatch2)"/>'
      + '<g stroke="#6d6350" stroke-width="3" fill="#efe8d8"><rect x="240" y="120" width="240" height="160" rx="6"/></g>'
      + '<line x1="300" y1="120" x2="270" y2="80" stroke="#6d6350" stroke-width="2.5"/>'
      + '<line x1="420" y1="120" x2="450" y2="80" stroke="#6d6350" stroke-width="2.5"/>'
      + '<rect x="270" y="150" width="180" height="100" fill="#efe6d6" stroke="#6d6350" stroke-width="1.6"/>'
      + '<g fill="none" stroke="#8a2f2f" stroke-width="3"><rect x="120" y="230" width="70" height="34" rx="4"/><line x1="130" y1="247" x2="180" y2="247"/></g>'
      + '<g fill="none" stroke="#6d6350" stroke-width="2"><path d="M520 220 h90"/><path d="M600 220 l-14 -10 M600 220 l-14 10"/></g>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">телеобращение Никсона, 15.08.1971</text></svg>';
    },
    "1980_volcker": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Волкер и ставка 20%, 1980">'
      + hatchBg() + '<rect y="300" width="720" height="100" fill="url(#hatch2)"/>'
      + '<g stroke="#6d6350" stroke-width="3" fill="#efe8d8"><rect x="380" y="120" width="280" height="160"/><path d="M420 280 v-100 a20 22 0 0 1 40 0 v100 Z M480 280 v-100 a20 22 0 0 1 40 0 v100 Z M540 280 v-100 a20 22 0 0 1 40 0 v100 Z M600 280 v-100 a20 22 0 0 1 40 0 v100 Z"/></g>'
      + '<g stroke="#5c5342" stroke-width="3" fill="none"><rect x="80" y="240" width="120" height="36" rx="4"/><circle cx="105" cy="284" r="16"/><circle cx="175" cy="284" r="16"/></g>'
      // 🔴 Рисунок остаётся ЗАПАСНЫМ вариантом, а не основным: у станции
      // теперь есть кадр по данным — доходность десятилетних US Treasuries
      // за 1979–83 (см. build_chrono2_frames.py). Самой ставки ФРС у нас
      // по-прежнему нет, и подпись кадра это прямо оговаривает: показана
      // рыночная ставка, а не ставка ФРС. Сюда попадём, только если файл с
      // рядами не загрузится.
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">Волкер, ставка 20%, фермеры-тракторы у ФРС</text></svg>';
    },
    "1998_ltcm": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="LTCM, 1998">'
      + hatchBg() + '<rect y="300" width="720" height="100" fill="url(#hatch2)"/>'
      + '<polyline points="60,260 120,240 180,250 240,220 300,235 360,200 420,215" fill="none" stroke="#2E7D5B" stroke-width="4"/>'
      + '<polyline points="420,215 460,260 500,230 540,310 580,290 630,340 660,320" fill="none" stroke="#8a2f2f" stroke-width="4"/>'
      + '<text x="150" y="140" font-family="Georgia,serif" font-size="46" fill="#6d6350" font-style="italic">Σ</text>'
      + '<text x="260" y="150" font-family="Georgia,serif" font-size="46" fill="#6d6350" font-style="italic">σ</text>'
      + '<text x="540" y="150" font-family="monospace" font-size="26" fill="#8a2f2f">25:1</text>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">крах LTCM, 1998</text></svg>';
    },
    "2012_draghi": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Три слова Драги, 2012">'
      + hatchBg() + '<rect y="300" width="720" height="100" fill="url(#hatch2)"/>'
      + '<g stroke="#6d6350" stroke-width="3" fill="#efe8d8"><rect x="470" y="120" width="200" height="160"/><path d="M500 280 v-100 a16 18 0 0 1 32 0 v100 Z M550 280 v-100 a16 18 0 0 1 32 0 v100 Z M600 280 v-100 a16 18 0 0 1 32 0 v100 Z"/></g>'
      + '<path d="M60 140 q0 -30 30 -30 h220 q30 0 30 30 v60 q0 30 -30 30 h-120 l-40 40 v-40 h-60 q-30 0 -30 -30 Z" fill="#efe8d8" stroke="#6d6350" stroke-width="2.5"/>'
      + '<text x="200" y="180" text-anchor="middle" font-family="Georgia,serif" font-style="italic" font-size="20" fill="#2B2B33">whatever it takes</text>'
      + '<g fill="none" stroke="#C9A227" stroke-width="1.6">'
      + '<circle cx="600" cy="200" r="3"/><circle cx="618" cy="192" r="3"/><circle cx="632" cy="204" r="3"/><circle cx="628" cy="222" r="3"/><circle cx="610" cy="228" r="3"/></g>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">Марио Драги, ЕЦБ, 26.07.2012</text></svg>';
    },
    "2015_snb": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="SNB, 2015">'
      + hatchBg() + '<rect y="300" width="720" height="100" fill="url(#hatch2)"/>'
      + '<rect x="120" y="130" width="70" height="70" fill="#8a2f2f"/><rect x="142" y="108" width="26" height="114" fill="#efe8d8"/><rect x="98" y="152" width="114" height="26" fill="#efe8d8"/>'
      + '<line x1="240" y1="160" x2="640" y2="160" stroke="#6d6350" stroke-width="1.6" stroke-dasharray="6 5"/>'
      + '<polyline points="240,160 320,158 340,160 360,300 420,120 480,150 560,145 640,140" fill="none" stroke="#8a2f2f" stroke-width="4"/>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">SNB отменяет пол EURCHF, 15.01.2015</text></svg>';
    },
    "2016_boj": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Отрицательные ставки Японии, 2016">'
      + hatchBg() + '<rect y="300" width="720" height="100" fill="url(#hatch2)"/>'
      + '<g stroke="#8a2f2f" stroke-width="8" fill="none"><path d="M480 90 h140 M550 90 v190 M500 150 h100 M510 150 l-30 130 M590 150 l30 130"/></g>'
      + '<line x1="60" y1="200" x2="420" y2="200" stroke="#6d6350" stroke-width="1.6"/>'
      + '<text x="40" y="205" font-family="monospace" font-size="12" fill="#8A8275">0</text>'
      + '<polyline points="60,190 120,195 180,210 240,230 300,225 360,250 420,245" fill="none" stroke="#8a2f2f" stroke-width="4"/>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">BoJ вводит отрицательную ставку, 2016</text></svg>';
    },
    "2022_cycle": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Цикл повышения ставки, 2022">'
      + hatchBg() + '<rect y="300" width="720" height="100" fill="url(#hatch2)"/>'
      + '<g fill="none" stroke="#8a2f2f" stroke-width="4">'
      + '<path d="M60 270 h60 v-30 h60 v-40 h60 v-40 h60 v-40 h60 v-30 h60 v-20 h60 v-10 h60"/></g>'
      + '<g fill="#5c5342">' + person(640,250,0.85) + '</g>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">цикл ФРС 2022-23, 0 → 5.25-5.50%</text></svg>';
    },
    "2024_boj": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Иена и разворот кэрри-трейда, 2024">'
      + hatchBg() + '<rect y="300" width="720" height="100" fill="url(#hatch2)"/>'
      + '<text x="120" y="200" font-family="Georgia,serif" font-size="70" fill="#6d6350">¥</text>'
      + '<polyline points="220,140 300,150 340,145 380,160 420,290 460,260 500,270 560,255 640,150" fill="none" stroke="#8a2f2f" stroke-width="4.5"/>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">Nikkei −12.4% за день, 05.08.2024</text></svg>';
    },
    "today_ch2": function(){
      // Реальные значения из web/data/edu_capsules/cb_rates_now.json (обновлено 23.07.2026):
      // Fed 3.63% (as_of 21.07.2026, снижение с пика 5.25-5.50% цикла 2022-23 -- ст.11 этой же хроники);
      // ECB 2.25% (as_of 11.06.2026, "first hike in 3 years"); BoJ 1.00% (as_of 16.06.2026, "highest since 1995").
      // Направления стрелок выведены из этих же реальных данных, не нарисованы на глаз.
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Три центробанка, сегодня: ФРС 3.63% вниз, ЕЦБ 2.25% вверх, BoJ 1.00% вверх">'
      + hatchBg() + '<rect y="300" width="720" height="100" fill="url(#hatch2)"/>'
      + '<circle cx="360" cy="190" r="14" fill="#C9A227" stroke="#2B2B33" stroke-width="2"/>'
      + '<g stroke="#2E7D5B" stroke-width="4" fill="none"><path d="M360 190 L200 110"/><path d="M200 110 l24 6 M200 110 l-2 -26"/></g>'
      + '<g stroke="#8a2f2f" stroke-width="4" fill="none"><path d="M360 190 L490 250"/><path d="M490 250 l-26 -2 M490 250 l2 -26"/></g>'
      + '<g stroke="#6d6350" stroke-width="4" fill="none"><path d="M360 190 L560 130"/><path d="M560 130 l-24 8 M560 130 l-10 -24"/></g>'
      + '<text x="200" y="94" text-anchor="middle" font-family="monospace" font-size="13" font-weight="700" fill="#2E7D5B">BoJ 1.00% ↑</text>'
      + '<text x="200" y="110" text-anchor="middle" font-family="monospace" font-size="9" fill="#8A8275">макс. с 1995 · 16.06.2026</text>'
      + '<text x="560" y="112" text-anchor="middle" font-family="monospace" font-size="13" font-weight="700" fill="#6d6350">ЕЦБ 2.25% ↑</text>'
      + '<text x="560" y="128" text-anchor="middle" font-family="monospace" font-size="9" fill="#8A8275">первое повышение за 3 года · 11.06.2026</text>'
      + '<text x="490" y="268" text-anchor="middle" font-family="monospace" font-size="13" font-weight="700" fill="#8a2f2f">ФРС 3.63% ↓</text>'
      + '<text x="490" y="284" text-anchor="middle" font-family="monospace" font-size="9" fill="#8A8275">пик цикла 5.25-5.50% (2023) · 21.07.2026</text>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">три ЦБ, три направления, июль 2026</text></svg>';
    }
  };

  function art2HTML(key){
    // Данные важнее рисунка: если под станцию есть настоящий ряд, показываем
    // его, а не иллюстрацию. Рисовальщик общий с главой 1 — chrono-frames.js.
    if (window.SbfChronoFrames) {
      var svg = window.SbfChronoFrames.кадр(key);
      if (svg) return svg;
    }
    if (window.ChronoStationArtHTML && window.ChronoStationArt && window.ChronoStationArt[key]) {
      return window.ChronoStationArtHTML(key); // переиспользуем ассет главы 1 (фото или SVG)
    }
    if (ART[key]) return ART[key]();
    // 🔴 Отсутствие ассета обязано быть слышно. Раньше здесь стоял молчаливый
    // return '': когда chrono.js не подключили на странице, четыре станции из
    // шестнадцати показывали пустую рамку, и узнать об этом можно было только
    // глазами, пролистав хронику до конца. Пустой экран сам о себе не
    // сообщает — сообщать должен код.
    if (window.console && console.warn) {
      console.warn('[chrono2] нет иллюстрации для станции "' + key +
        '". Ключи 1929_crowd/1987_blackmonday/2008_lehman/2020_covid живут в ' +
        'chrono.js — он должен грузиться на странице ДО chrono2.js.');
    }
    return '';
  }

  window.Chrono2StationArt = ART;
  window.Chrono2StationArtHTML = art2HTML;

})();

/* Четыре крупнейших ЦБ — карточки (SPEC §3.2). window.Chrono2Organizations = {ru:[4],ro:[4],en:[4]}. */
(function(){
  window.Chrono2Organizations = {
    ru: [
      { id:"fed", flag:"🇺🇸", name:"ФРС", founded:"США, 1913",
        body:"Управляет долларом — валютой, в которой прячется мир, когда страшно. Уникальность — двойной мандат: стабильность цен И максимальная занятость, поэтому ФРС смотрит на CPI и NFP одновременно (вот почему эти два релиза — самые взрывные в календаре). Решения принимает комитет FOMC — 8 плановых заседаний в год, но самые важные решения случались вне расписания. Одно движение ставки ФРС переоценивает активы на всех континентах за минуты." },
      { id:"ecb", flag:"🇪🇺", name:"ЕЦБ", founded:"Еврозона, 1998",
        body:"Один банк на 20 стран с одним мандатом — цены, около 2% инфляции. В этом сила и слабость: когда немецкая экономика требует одного, а итальянский долг — другого, ЕЦБ вынужден выбирать. Отсюда великие кризисы евро и великие слова: три слова Марио Драги в 2012-м сделали то, что не могли триллионы (станция 10). EUR/USD — самая торгуемая пара планеты — это по сути ежедневный референдум «ФРС против ЕЦБ»." },
      { id:"boj", flag:"🇯🇵", name:"Банк Японии", founded:"1882",
        body:"Тридцать лет борьбы с дефляцией сделали BoJ самым изобретательным и самым странным ЦБ мира: отрицательные ставки, контроль кривой доходности, скупка акций собственного рынка. Дешёвая иена десятилетиями была «топливом» мирового кэрри-трейда: занять под 0% в иенах — вложить где доходнее. Станция 15 покажет, что случилось с рынками всей планеты, когда это топливо начало дорожать. Сейчас — впервые с 1995 года — ставка BoJ выше нуля всерьёз." },
      { id:"boe", flag:"🇬🇧", name:"Банк Англии", founded:"1694",
        body:"Старейший из великих — образец, по которому строились остальные. Фунт — третья резервная валюта; но главный урок BoE современному трейдеру — история 1992 года: даже великий ЦБ может проиграть рынку, если защищает нереалистичный курс (Сорос и «среда, когда сломали банк Англии»). ЦБ силён, пока его слову верят — запомни это до станции 11, где слово другого ЦБ обесценилось за 20 минут." }
    ],
    footnote_ru: "А где Народный банк Китая? Управляет второй экономикой мира, но юань не свободно конвертируем — его решения бьют по сырью и азиатским рынкам косвенно. Для старта хватит «большой четвёрки».",
    ro: [
      { id:"fed", flag:"🇺🇸", name:"Fed", founded:"SUA, 1913",
        body:"Gestionează dolarul — moneda în care se ascunde lumea când îi e frică. Unicitatea sa: un mandat dublu — stabilitatea prețurilor ȘI ocuparea maximă a forței de muncă, de aceea Fed urmărește simultan CPI și NFP (de aceea aceste două publicații sunt cele mai explozive din calendar). Deciziile sunt luate de comitetul FOMC — 8 ședințe programate pe an, dar cele mai importante decizii s-au întâmplat în afara programului. O singură mișcare a dobânzii Fed reevaluează activele de pe toate continentele în câteva minute." },
      { id:"ecb", flag:"🇪🇺", name:"BCE", founded:"Zona euro, 1998",
        body:"O singură bancă pentru 20 de țări cu un singur mandat — prețurile, aproximativ 2% inflație. Aici stă și forța, și slăbiciunea: când economia germană cere una, iar datoria italiană alta, BCE e nevoită să aleagă. De aici marile crize ale euro și marile cuvinte: cele trei cuvinte ale lui Mario Draghi din 2012 au făcut ceea ce trilioanele nu au putut (stația 10). EUR/USD — cea mai tranzacționată pereche de pe planetă — e practic un referendum zilnic „Fed contra BCE”." },
      { id:"boj", flag:"🇯🇵", name:"Banca Japoniei", founded:"1882",
        body:"Treizeci de ani de luptă cu deflația au făcut din BoJ cea mai inventivă și mai ciudată bancă centrală din lume: dobânzi negative, controlul curbei randamentelor, cumpărarea de acțiuni de pe propria piață. Yenul ieftin a fost decenii la rând „combustibilul” carry trade-ului global: împrumuți la 0% în yeni — investești unde randamentul e mai mare. Stația 15 va arăta ce s-a întâmplat cu piețele întregii planete când acest combustibil a început să se scumpească. Acum — pentru prima dată din 1995 — dobânda BoJ e serios peste zero." },
      { id:"boe", flag:"🇬🇧", name:"Banca Angliei", founded:"1694",
        body:"Cea mai veche dintre marile bănci centrale — modelul după care s-au construit celelalte. Lira e a treia monedă de rezervă; dar lecția principală a BoE pentru traderul de azi e povestea din 1992: chiar și o mare bancă centrală poate pierde în fața pieței dacă apără un curs nerealist (Soros și „miercurea în care s-a spart Banca Angliei”). O bancă centrală e puternică atât timp cât i se crede cuvântul — ține minte asta până la stația 11, unde cuvântul altei bănci centrale și-a pierdut valoarea în 20 de minute." }
    ],
    footnote_ro: "Dar unde e Banca Populară a Chinei? Gestionează a doua economie a lumii, dar yuanul nu e liber convertibil — deciziile sale lovesc indirect materiile prime și piețele asiatice. Pentru început, „marii patru” sunt suficienți.",
    en: [
      { id:"fed", flag:"🇺🇸", name:"The Fed", founded:"USA, 1913",
        body:"Manages the dollar — the currency the world hides in when it's scared. Its uniqueness: a dual mandate — price stability AND maximum employment — which is why the Fed watches CPI and NFP at once (that's why these two releases are the most explosive on the calendar). Decisions are made by the FOMC committee — 8 scheduled meetings a year, but the most important decisions happened off schedule. A single Fed rate move reprices assets on every continent within minutes." },
      { id:"ecb", flag:"🇪🇺", name:"The ECB", founded:"Eurozone, 1998",
        body:"One bank for 20 countries with one mandate — prices, around 2% inflation. That's both its strength and its weakness: when the German economy wants one thing and Italian debt wants another, the ECB has to choose. Hence the great euro crises, and the great words: Mario Draghi's three words in 2012 did what trillions couldn't (station 10). EUR/USD — the planet's most traded pair — is essentially a daily referendum, \"the Fed vs. the ECB.\"" },
      { id:"boj", flag:"🇯🇵", name:"The Bank of Japan", founded:"1882",
        body:"Thirty years fighting deflation made the BoJ the world's most inventive and strangest central bank: negative rates, yield curve control, buying up shares of its own market. Cheap yen was, for decades, the \"fuel\" of the global carry trade: borrow at 0% in yen, invest wherever returns more. Station 15 will show what happened to markets across the planet when that fuel got more expensive. Right now — for the first time since 1995 — the BoJ rate is seriously above zero." },
      { id:"boe", flag:"🇬🇧", name:"The Bank of England", founded:"1694",
        body:"The oldest of the greats — the model the others were built after. The pound is the world's third reserve currency; but BoE's main lesson for today's trader is the story of 1992: even a great central bank can lose to the market if it defends an unrealistic rate (Soros and \"the day Britain broke the Bank of England\"). A central bank is strong only as long as its word is believed — remember that until station 11, where another central bank's word lost its value in 20 minutes." }
    ],
    footnote_en: "So where's the People's Bank of China? It runs the world's second-largest economy, but the yuan isn't freely convertible — its decisions hit commodities and Asian markets indirectly. The \"big four\" are enough to start with."
  };
})();

/* Квиз (4), предикт, клиффхэнгер главы 2 (SPEC §5). window.Chrono2Quiz/Predict/Cliffhanger = {ru,ro,en}. */
(function(){
  window.Chrono2Quiz = {
    ru: [
      { id:"q1", section:"chrono2", prompt:"ФРС экстренно снижает ставку вне графика заседаний. Чаще всего в первые дни рынок…",
        options:[{text:"Растёт (стимул!)",correct:false},{text:"Падает — экстренность читается как признание масштаба беды",correct:true},{text:"Не реагирует",correct:false}],
        feedbackCorrect:"Верно. Обе экстренки марта-2020 закрылись падением; дно пришло позже, когда безлимитная ликвидность перевесила страх.",
        feedbackWrong:"Неверно. Обе экстренки марта-2020 (станция 13) закрылись падением — экстренность читается как признание масштаба беды. Дно пришло позже." },
      { id:"q2", section:"chrono2", prompt:"Что остановило долговой кризис еврозоны в 2012-м?",
        options:[{text:"Триллионная программа выкупа",correct:false},{text:"Три слова Драги — программу даже не пришлось включать",correct:true},{text:"Помощь МВФ",correct:false}],
        feedbackCorrect:"Верно. Рынки торгуют ожидания; вербальная интервенция — оружие ЦБ.",
        feedbackWrong:"Неверно. Кризис остановили три слова Марио Драги «whatever it takes» — программу OMT даже не пришлось включать (станция 10)." },
      { id:"q3", section:"chrono2", prompt:"Почему в 2022-м упали одновременно и акции, и облигации?",
        options:[{text:"Рост ставки уценивает будущие прибыли акций и делает старые облигации невыгодными — бьёт по обоим",correct:true},{text:"Совпадение",correct:false},{text:"Из-за крипты",correct:false}],
        feedbackCorrect:"Верно. Что тогда защищает капитал в кризис — разберём в главе 3.",
        feedbackWrong:"Неверно. Рост ставки одновременно уценивает будущие прибыли акций и делает старые облигации невыгодными — бьёт по обоим сразу." },
      { id:"q4", section:"chrono", prompt:"Первый в истории запрет шорт-продаж — это…",
        options:[{text:"Амстердам, 1610",correct:true},{text:"Нью-Йорк, 1929",correct:false},{text:"Вашингтон, 2008",correct:false}],
        feedbackCorrect:"Верно. Спор «запрещать ли шорты» старше США (глава 1, станция 1).",
        feedbackWrong:"Неверно. Первый в истории запрет — Амстердам, 1610-й, после шорт-атаки Исаака Ле Мэра (глава 1, станция 1)." }
    ],
    ro: [
      { id:"q1", section:"chrono2", prompt:"Fed reduce dobânda de urgență, în afara programului de ședințe. De cele mai multe ori, în primele zile piața…",
        options:[{text:"Crește (stimulent!)",correct:false},{text:"Scade — urgența e citită drept recunoașterea amplorii problemei",correct:true},{text:"Nu reacționează",correct:false}],
        feedbackCorrect:"Corect. Ambele reduceri de urgență din martie 2020 s-au încheiat cu scădere; minimul a venit mai târziu, când lichiditatea nelimitată a depășit frica.",
        feedbackWrong:"Incorect. Ambele reduceri de urgență din martie 2020 (stația 13) s-au încheiat cu scădere — urgența e citită drept recunoașterea amplorii problemei." },
      { id:"q2", section:"chrono2", prompt:"Ce a oprit criza datoriilor din zona euro în 2012?",
        options:[{text:"Un program de răscumpărare de trilioane",correct:false},{text:"Cele trei cuvinte ale lui Draghi — programul nici n-a trebuit activat",correct:true},{text:"Ajutorul FMI",correct:false}],
        feedbackCorrect:"Corect. Piețele tranzacționează așteptări; intervenția verbală e arma unei bănci centrale.",
        feedbackWrong:"Incorect. Criza s-a oprit datorită celor trei cuvinte ale lui Draghi „whatever it takes” — programul OMT nici n-a trebuit activat (stația 10)." },
      { id:"q3", section:"chrono2", prompt:"De ce au scăzut simultan acțiunile și obligațiunile în 2022?",
        options:[{text:"Creșterea dobânzii reduce valoarea profiturilor viitoare ale acțiunilor și face obligațiunile vechi neatractive — lovește ambele",correct:true},{text:"Coincidență",correct:false},{text:"Din cauza cripto",correct:false}],
        feedbackCorrect:"Corect. Ce protejează capitalul într-o criză — vom vedea în capitolul 3.",
        feedbackWrong:"Incorect. Creșterea dobânzii reduce simultan valoarea profiturilor viitoare ale acțiunilor și face obligațiunile vechi neatractive — lovește ambele deodată." },
      { id:"q4", section:"chrono", prompt:"Prima interdicție din istorie a vânzărilor short este…",
        options:[{text:"Amsterdam, 1610",correct:true},{text:"New York, 1929",correct:false},{text:"Washington, 2008",correct:false}],
        feedbackCorrect:"Corect. Disputa „interzicem sau nu short-urile” e mai veche decât SUA (capitolul 1, stația 1).",
        feedbackWrong:"Incorect. Prima interdicție din istorie — Amsterdam, 1610, după atacul short al lui Isaac Le Maire (capitolul 1, stația 1)." }
    ],
    en: [
      { id:"q1", section:"chrono2", prompt:"The Fed makes an emergency rate cut outside its scheduled meetings. In the first few days, the market usually…",
        options:[{text:"Rallies (stimulus!)",correct:false},{text:"Falls — the emergency reads as an admission of how bad things are",correct:true},{text:"Doesn't react",correct:false}],
        feedbackCorrect:"Correct. Both March 2020 emergency cuts closed lower; the bottom came later, once unlimited liquidity outweighed fear.",
        feedbackWrong:"Incorrect. Both March 2020 emergency cuts (station 13) closed lower — the emergency reads as an admission of how bad things are." },
      { id:"q2", section:"chrono2", prompt:"What stopped the eurozone debt crisis in 2012?",
        options:[{text:"A trillion-dollar bond-buying program",correct:false},{text:"Draghi's three words — the program never even had to be used",correct:true},{text:"IMF assistance",correct:false}],
        feedbackCorrect:"Correct. Markets trade expectations; verbal intervention is a central bank's weapon.",
        feedbackWrong:"Incorrect. The crisis stopped because of Draghi's three words, \"whatever it takes\" — the OMT program was never actually used (station 10)." },
      { id:"q3", section:"chrono2", prompt:"Why did stocks and bonds fall together in 2022?",
        options:[{text:"A higher rate discounts future stock earnings and makes old bonds unattractive — it hits both",correct:true},{text:"Coincidence",correct:false},{text:"Because of crypto",correct:false}],
        feedbackCorrect:"Correct. What actually protects capital in a crisis — we'll cover that in chapter 3.",
        feedbackWrong:"Incorrect. A higher rate simultaneously discounts future stock earnings and makes old bonds unattractive — it hits both at once." },
      { id:"q4", section:"chrono", prompt:"The first short-selling ban in history was…",
        options:[{text:"Amsterdam, 1610",correct:true},{text:"New York, 1929",correct:false},{text:"Washington, 2008",correct:false}],
        feedbackCorrect:"Correct. The dispute over banning short selling predates the US (chapter 1, station 1).",
        feedbackWrong:"Incorrect. The first-ever ban was Amsterdam, 1610, after Isaac Le Maire's short attack (chapter 1, station 1)." }
    ]
  };

  window.Chrono2Predict = {
    ru: { fallbackQ:"Закроет ли золото неделю выше открытия понедельника?", yes:"Да", no:"Нет", tag:"ПРЕДИКТ НЕДЕЛИ" },
    ro: { fallbackQ:"Va închide aurul săptămâna peste deschiderea de luni?", yes:"Da", no:"Nu", tag:"PREDICȚIA SĂPTĂMÂNII" },
    en: { fallbackQ:"Will gold close the week above Monday's open?", yes:"Yes", no:"No", tag:"PREDICTION OF THE WEEK" }
  };

  window.Chrono2Cliffhanger = {
    ru: { tag:"ДАЛЬШЕ", body:"Теперь ты знаешь, кто двигает все графики сразу. Но вот загадка, которую 2022-й задал каждому инвестору планеты: классическая защита — 60/40, акции плюс облигации — сломалась именно тогда, когда была нужнее всего. Оба актива упали вместе, впервые за почти сто лет. Значит, «диверсификация» — миф? Нет. Просто она работает не так, как тебе продавали. Что на самом деле защищало капитал в 2022-м — и что защищает в любой кризис — покажу на первом графике следующего эпизода. Подсказка: это не золото. Точнее — не только оно." },
    ro: { tag:"URMEAZĂ", body:"Acum știi cine mișcă toate graficele deodată. Dar iată enigma pe care 2022 a pus-o fiecărui investitor de pe planetă: protecția clasică — 60/40, acțiuni plus obligațiuni — s-a rupt exact atunci când era mai necesară. Ambele active au scăzut împreună, pentru prima dată în aproape un secol. Deci „diversificarea” e un mit? Nu. Doar că funcționează altfel decât ți s-a vândut. Ce a protejat cu adevărat capitalul în 2022 — și ce protejează în orice criză — îți arăt pe primul grafic al episodului următor. Indiciu: nu e aurul. Mai exact — nu doar el." },
    en: { tag:"NEXT", body:"Now you know who moves every chart at once. But here's the puzzle 2022 posed to every investor on the planet: the classic defense — 60/40, stocks plus bonds — broke exactly when it was needed most. Both assets fell together, for the first time in almost a century. So is \"diversification\" a myth? No. It just doesn't work the way it was sold to you. What actually protected capital in 2022 — and what protects it in any crisis — I'll show you on the first chart of the next episode. Hint: it isn't gold. Or rather, not only gold." }
  };
})();

/* Копия для сцен машины времени (window.SceneEngine), по одной на каждую
   станцию с полем scene: (кроме "ch2_now" -- та станция сознательно ведёт
   на живой терминал/график, не на скриптованную сцену: её собственный текст
   уже говорит "Открой терминал"). window.Chrono2SceneCopy = {sceneId: {ru,ro,en}}. */
(function(){
  window.Chrono2SceneCopy = {
    ch2_fed_2020: {
      ru: {
        question: "3 марта 2020: ФРС только что экстренно снизила ставку на 50 бп вне графика. Твоё решение на закрытии дня?",
        options: ["Покупаю — это стимул", "Продаю — экстренность пугает", "Жду"],
        revealText: "Рынок вырос на 15 минут и закрыл день −2.8%: экстренность прочитана как признание масштаба беды. 15 марта — уже до нуля + QE на $700 млрд.",
        nextMarker: "Следующее решение (15 марта) →",
      },
      ro: {
        question: "3 martie 2020: Fed tocmai a redus dobânda de urgență cu 50 pb, în afara programului. Decizia ta la închiderea zilei?",
        options: ["Cumpăr — e stimulent", "Vând — urgența sperie", "Aștept"],
        revealText: "Piața a crescut 15 minute și a închis ziua −2.8%: urgența a fost citită drept recunoașterea amplorii problemei. Pe 15 martie — deja la zero + QE de $700 mld.",
        nextMarker: "Următoarea decizie (15 martie) →",
      },
      en: {
        question: "March 3, 2020: the Fed just made an emergency 50bp rate cut, outside its schedule. Your call at the close?",
        options: ["I buy — it's stimulus", "I sell — the emergency is scary", "I wait"],
        revealText: "The market rallied for 15 minutes and closed the day −2.8%: the emergency was read as an admission of how bad things were. By March 15 — already at zero plus $700bn of QE.",
        nextMarker: "Next decision (March 15) →",
      },
    },
    ch2_snb_2015: {
      ru: {
        steps: [
          { markerTime: "2015-01-14T00:00:00Z", text: "14 января 2015. Швейцарский нацбанк уже три года держит «пол» 1.20 по EURCHF — «с неограниченной решимостью». Рынок спокоен: график — почти прямая линия." },
          { markerTime: "2015-01-15T09:30:00Z", text: "15 января, 11:30 по Цюриху (09:30 UTC). Пресс-релиз SNB: пол отменён. Никакого предупреждения." },
          { markerTime: "2015-01-15T09:45:00Z", text: "09:45 UTC — интрадей-минимум 0.8508. Франк дорожает почти на 30% за 15 минут. Стоп-лоссы исполняются в разы хуже уровней; брокер Alpari UK банкротится в тот же день." },
          { markerTime: "2015-01-16T00:00:00Z", text: "К 16 января рынок частично успокаивается — но пара уже никогда не вернётся к 1.20. Урок: «гарантированный уровень» — это чьё-то обещание, а обещания отменяются пресс-релизом." },
        ],
        prev: "← Назад", next: "Дальше →",
      },
      ro: {
        steps: [
          { markerTime: "2015-01-14T00:00:00Z", text: "14 ianuarie 2015. Banca Națională a Elveției menține de trei ani „pragul” de 1.20 pentru EURCHF — „cu hotărâre nelimitată”. Piața e calmă: graficul e aproape o linie dreaptă." },
          { markerTime: "2015-01-15T09:30:00Z", text: "15 ianuarie, ora 11:30 la Zürich (09:30 UTC). Comunicat SNB: pragul e eliminat. Fără niciun avertisment." },
          { markerTime: "2015-01-15T09:45:00Z", text: "09:45 UTC — minim intraday de 0.8508. Francul se scumpește cu aproape 30% în 15 minute. Stop-loss-urile se execută de multe ori mai rău decât nivelurile lor; brokerul Alpari UK falimentează chiar în acea zi." },
          { markerTime: "2015-01-16T00:00:00Z", text: "Pe 16 ianuarie piața se liniștește parțial — dar perechea nu se va mai întoarce niciodată la 1.20. Lecția: un „nivel garantat” e promisiunea cuiva, iar promisiunile se anulează printr-un comunicat de presă." },
        ],
        prev: "← Înapoi", next: "Continuă →",
      },
      en: {
        steps: [
          { markerTime: "2015-01-14T00:00:00Z", text: "January 14, 2015. The Swiss National Bank has held a 1.20 \"floor\" on EURCHF for three years — \"with utmost determination.\" The market is calm: the chart is nearly a straight line." },
          { markerTime: "2015-01-15T09:30:00Z", text: "January 15, 11:30am Zurich time (09:30 UTC). SNB press release: the floor is removed. No warning at all." },
          { markerTime: "2015-01-15T09:45:00Z", text: "09:45 UTC — intraday low of 0.8508. The franc gains nearly 30% in 15 minutes. Stop-losses fill many times worse than their levels; broker Alpari UK goes bankrupt that same day." },
          { markerTime: "2015-01-16T00:00:00Z", text: "By January 16 the market partly calms down — but the pair will never return to 1.20 again. The lesson: a \"guaranteed level\" is somebody's promise, and promises get cancelled by press release." },
        ],
        prev: "← Back", next: "Next →",
      },
    },
    ch2_cycle_2022: {
      ru: {
        title: "Цикл повышений ФРС", periodLabel: "март 2022 — июль 2023 · дневные свечи",
        meetingLabel: "Заседание FOMC", ofLabel: "из", bpUnit: "бп", noChange: "0", noChangeFull: "без изменений",
        prev: "← Предыдущее заседание", next: "Следующее заседание →",
        resetView: "⤢ Весь период", backToEvent: "↩ К событию",
        compareToggle: "⇄ Сравнить", compareToggleOff: "✕ Сравнение", comparePickHint: "Выбери ещё один инструмент, чтобы сравнить (до 3)",
        compareNote: "В режиме сравнения показаны линии закрытия, приведённые к моменту события",
        doneText: "Цикл завершён: 0 → 5.25–5.50% за 16 месяцев. Кто читал календарь — знал каждый шаг заранее.",
      },
      ro: {
        title: "Ciclul de majorări al Fed", periodLabel: "martie 2022 — iulie 2023 · lumânări zilnice",
        meetingLabel: "Ședința FOMC", ofLabel: "din", bpUnit: "pb", noChange: "0", noChangeFull: "fără schimbări",
        prev: "← Ședința anterioară", next: "Următoarea ședință →",
        resetView: "⤢ Toată perioada", backToEvent: "↩ La eveniment",
        compareToggle: "⇄ Compară", compareToggleOff: "✕ Comparație", comparePickHint: "Alege încă un instrument pentru comparație (max. 3)",
        compareNote: "În modul comparație sunt afișate liniile de închidere, raportate la momentul evenimentului",
        doneText: "Ciclul s-a încheiat: 0 → 5.25–5.50% în 16 luni. Cine citea calendarul știa fiecare pas dinainte.",
      },
      en: {
        title: "The Fed hiking cycle", periodLabel: "March 2022 — July 2023 · daily candles",
        meetingLabel: "FOMC Meeting", ofLabel: "of", bpUnit: "bp", noChange: "0", noChangeFull: "no change",
        prev: "← Previous meeting", next: "Next meeting →",
        resetView: "⤢ Full range", backToEvent: "↩ Back to the event",
        compareToggle: "⇄ Compare", compareToggleOff: "✕ Comparison", comparePickHint: "Pick one more instrument to compare (up to 3)",
        compareNote: "Comparison mode shows closing lines, rebased to the moment of the event",
        doneText: "The cycle is complete: 0 → 5.25–5.50% in 16 months. Whoever read the calendar knew every step in advance.",
      },
    },
    ch2_carry_2024: {
      ru: {
        steps: [
          { markerTime: "2024-07-16", text: "16 июля 2024. Йена возле многолетнего минимума — 158 за доллар. Керри-трейд в разгаре: занимают в йенах почти под 0%, вкладывают в доллары под 5%+. Прибыль почти гарантирована, пока курс не двигается резко." },
          { markerTime: "2024-07-31", text: "31 июля. Банк Японии поднимает ставку до 0.25% — самое резкое повышение с 2007-го. Занимать в йенах больше не бесплатно." },
          { markerTime: "2024-08-02", text: "2 августа. Слабый отчёт по рынку труда США оживляет страхи рецессии — доллар слабеет одновременно с ростом ставки в Японии. Керри-трейд атакован с двух сторон разом." },
          { markerTime: "2024-08-05", text: "5 августа. Nikkei падает на 12.4% внутри дня — худший день с 1987-го. Керри-трейд разворачивается лавинообразно: чем больше падает USDJPY, тем больше маржин-коллов у тех, кто занимал в йенах — а маржин-коллы заставляют продавать доллары, роняя курс ещё сильнее." },
        ],
        prev: "← Назад", next: "Дальше →",
      },
      ro: {
        steps: [
          { markerTime: "2024-07-16", text: "16 iulie 2024. Yenul e aproape de minimul din ultimii ani — 158 pentru un dolar. Carry trade-ul e în toi: te împrumuți în yeni la aproape 0%, investești în dolari la 5%+. Profitul e aproape garantat, cât timp cursul nu se mișcă brusc." },
          { markerTime: "2024-07-31", text: "31 iulie. Banca Japoniei urcă dobânda la 0.25% — cea mai abruptă majorare din 2007. Împrumutul în yeni nu mai e gratuit." },
          { markerTime: "2024-08-02", text: "2 august. Un raport slab al pieței muncii din SUA reînvie temerile de recesiune — dolarul slăbește exact când dobânda din Japonia crește. Carry trade-ul e atacat din ambele direcții deodată." },
          { markerTime: "2024-08-05", text: "5 august. Nikkei scade cu 12.4% intraday — cea mai proastă zi din 1987 încoace. Carry trade-ul se destramă în avalanșă: cu cât scade mai mult USDJPY, cu atât mai multe margin call-uri pentru cei împrumutați în yeni — iar margin call-urile îi forțează să vândă dolari, prăbușind cursul și mai mult." },
        ],
        prev: "← Înapoi", next: "Continuă →",
      },
      en: {
        steps: [
          { markerTime: "2024-07-16", text: "July 16, 2024. The yen is near a multi-year low — 158 to the dollar. The carry trade is in full swing: borrow in yen at near-0%, invest in dollars at 5%+. Profit is nearly guaranteed as long as the rate doesn't move sharply." },
          { markerTime: "2024-07-31", text: "July 31. The Bank of Japan raises its rate to 0.25% — the sharpest hike since 2007. Borrowing in yen is no longer free." },
          { markerTime: "2024-08-02", text: "August 2. A weak US jobs report revives recession fears — the dollar weakens just as Japan's rate rises. The carry trade gets attacked from both sides at once." },
          { markerTime: "2024-08-05", text: "August 5. The Nikkei falls 12.4% intraday — its worst day since 1987. The carry trade unwinds in an avalanche: the further USDJPY falls, the more margin calls hit yen borrowers — and margin calls force them to sell dollars, driving the rate down even further." },
        ],
        prev: "← Back", next: "Next →",
      },
    },
  };
})();

/* Cold open / анти-миф / голос SBF / цена незнания (SPEC §3.1) -- портировано
   из history_preview_ch2.html (было готово RU/RO/EN только там, не в
   переиспользуемом виде) для живой интеграции. window.Chrono2Content = {ru,ro,en}. */
(function(){
  window.Chrono2Content = {
    ru: {
      coldOpen: { headline: "2 марта 2020 года. Рынок падает восьмой день.", body: "Завтра Федеральная резервная система сделает то, чего не делала со времён кризиса 2008-го — и рынок отреагирует не так, как ждёт почти каждый, кто сейчас смотрит этот график. У тебя одно решение и одна попытка. Как в тот день — у всех." },
      antiMyth: { tag: "АНТИ-МИФ", no: "✗ «Ставки, инфляция, центробанки — это макроэкономика для аналитиков, к трейдингу не относится»", body: "Критическая ошибка. Ставка — это цена самих денег, а всё, что ты видишь в терминале, стоит денег. Когда цена денег меняется, переоценивается всё: акции, облигации, золото, крипта, валюты — одновременно, но с разной силой и знаком. Трейдер, не знающий календарь ЦБ, — как серфер, не знающий расписание приливов." },
      voice: { tag: "ГОЛОС SBF", body: "«Коллега, за двадцать лет на рынке я выучил простую вещь: против тренда можно выстоять, против сессии — можно, против ставки — нельзя. В этой главе мы разберём не \"что такое ставка\" из учебника, а как читать крупнейшие организации по их собственному расписанию — и что делает золото, когда они начинают спорить друг с другом. А спорят они прямо сейчас.»" },
      cost: { tag: "2022", body: "Инвестор «пересиживает» просадку в классическом портфеле 60/40 — «диверсификация же защищает». Итог года: S&P 500 −18%, облигации −13% — худший результат совместного падения почти за столетие. Понимание одного факта — «ФРС начала самый быстрый цикл повышения за 40 лет» — было публичным, бесплатным и стояло в календаре за месяцы." },
      calendarMatrix: {
        tag: "КАЛЕНДАРЬ — РАСПИСАНИЕ ВОЛАТИЛЬНОСТИ",
        title: "Матрица влияния",
        preamble: "Четыре релиза двигают рынки сильнее остальных. Ниже — не оценка на глаз, а измеренное движение цены за час после публикации, приведённое к обычному дневному размаху инструмента, чтобы колонки можно было сравнивать напрямую.",
        methodologyTitle: "Как это посчитано",
        methodologyBody: "Крупное число в клетке — среднее движение цены за 60 минут после релиза, делённое на медианный дневной диапазон (H-L) инструмента за последний год: 0.4 значит «типичным движением было 40% обычного дневного размаха», и это уже сравнимо между XAU/USD, DXY, S&P 500 и BTC/USD напрямую. Мелкая цифра под ней — то же движение в пунктах цены инструмента, для справки. XAU/USD — из живого движка Layer 1 (история с июля 2024, до 12 случаев на клетку), пересчитывается раз в сутки. DXY/S&P 500/BTC посчитаны этим же методом на нашем более коротком бэкфилле MT5 (~2.5–3 месяца) — честно меньше случаев, поэтому и приглушены чаще. Клетки S&P 500 для NFP/CPI/GDP пустые не по ошибке: эти релизы выходят в 12:30–13:30 UTC, до открытия дневной сессии биржи — в бэкфилле в этот момент просто нет котировок S&P.",
        colEvent: "Релиз", colGold: "XAU/USD", colDxy: "DXY", colSpx: "S&P 500", colBtc: "BTC/USD",
        move30Label: "30 мин", move60Label: "60 мин", casesLabel: "случаев", casesLabelOne: "случай", casesLabelFew: "случая",
        noDataCell: "нет данных в нашей истории",
        naLabel: "нет данных",
        rawUnit: " пт",
        lowSampleLegend: "Приглушённые клетки со штриховкой — меньше 4 наблюдений: иллюстрация метода, а не закономерность.",
        smallSampleTag: "мало случаев — не закономерность, а иллюстрация метода",
        spxGapNote: "Клетки S&P 500 для NFP/CPI/GDP пустые не по ошибке: эти релизы выходят в 12:30–13:30 UTC, до открытия дневной сессии биржи (13:30 UTC) — в нашем бэкфилле в этот момент попросту нет котировок S&P, торги ещё не начались.",
        goldSourceNote: "XAU/USD — живой движок Layer 1, пересчитывается раз в сутки, история с июля 2024.",
        freshSourceNote: "DXY/S&P 500/BTC — этот же расчёт, наш собственный бэкфилл MT5 (~2.5–3 месяца), обновляется вручную вместе с главой.",
        nextReleaseTag: "БЛИЖАЙШИЙ КРАСНЫЙ РЕЛИЗ",
        nextReleaseLoading: "Смотрю в календарь…",
        nextReleaseNone: "В ближайшие 30 дней релизов с высокой значимостью не найдено.",
        nextReleaseError: "Календарь недоступен прямо сейчас.",
        countdownDay: "д", countdownHour: "ч", countdownMin: "м",
        safetyTag: "ПРАВИЛО БЕЗОПАСНОСТИ НОВИЧКА",
        safetyBody: "За 15 минут до красного релиза закрой терминал, если у тебя нет плана. Спред расширяется в разы, стопы проскальзывают — станция 11 (франк, 2015) показала предел того, чем этот риск может обернуться.",
        jumpToSnbStation: "↑ Перейти к станции 11",
        cpiSceneTag: "СЦЕНА — ОДНА ЦИФРА РАЗВОРАЧИВАЕТ ТРЕНД",
        cpiSceneLegend: "10 ноября 2022 года, 13:30 UTC: выходит октябрьский CPI США — прохладнее прогноза. Золото восемь месяцев падало на цикле повышения ставок ФРС. Смотри, что случилось в следующий час на реальных минутных котировках.",
        cpiSceneQuestion: "У тебя длинная позиция по золоту, открытая до релиза. Что делаешь за минуту до выхода CPI?",
        cpiSceneOptions: ["Закрою позицию до цифры", "Оставлю как есть, стоп не трону", "Расширю стоп заранее", "Удвою позицию перед цифрой"],
        cpiSceneReveal: "Оптимального ответа для ЛЮБОЙ будущей цифры не существует — иначе рынок был бы предсказуем. «Закрою до цифры» гарантированно избегает риска гэпа, но и гарантированно не участвует, если цифра в твою пользу. «Удвою перед цифрой» — противоположность управлению риском: удваивает и потенциальный выигрыш, и потенциальный необратимый убыток в ту же секунду. Здесь эта конкретная цифра оказалась попутной — но сцена именно про то, что ДО раскрытия это было неизвестно никому в этой комнате.",
      },
    },
    ro: {
      coldOpen: { headline: "2 martie 2020. Piața scade a opta zi la rând.", body: "Mâine Rezerva Federală va face ceva ce n-a mai făcut din criza lui 2008 — iar piața va reacționa altfel decât se așteaptă aproape oricine urmărește acum acest grafic. Ai o decizie și o singură șansă. Ca toată lumea, în ziua aceea." },
      antiMyth: { tag: "ANTI-MIT", no: "✗ „Dobânzile, inflația, băncile centrale — sunt macroeconomie pentru analiști, nu au legătură cu trading-ul”", body: "Greșeală critică. Dobânda e prețul banilor înșiși, iar tot ce vezi în terminal costă bani. Când prețul banilor se schimbă, se reevaluează totul: acțiuni, obligațiuni, aur, cripto, valute — simultan, dar cu forță și semn diferite. Un trader care nu cunoaște calendarul băncilor centrale e ca un surfer care nu știe orarul mareelor." },
      voice: { tag: "VOCEA SBF", body: "„Coleg, în douăzeci de ani pe piață am învățat un lucru simplu: poți rezista unui trend, poți rezista unei sesiuni, dar nu poți rezista unei dobânzi. În acest capitol nu vom analiza «ce e dobânda» din manual, ci cum să citești cele mai mari organizații după propriul lor program — și ce face aurul când acestea încep să se contrazică. Iar acum chiar se contrazic.”" },
      cost: { tag: "2022", body: "Un investitor „rezistă” unei scăderi în portofoliul clasic 60/40 — „diversificarea protejează, totuși”. Rezultatul anului: S&P 500 −18%, obligațiuni −13% — cel mai prost rezultat al unei scăderi comune din aproape un secol. Un singur fapt — „Fed a început cel mai rapid ciclu de majorări din ultimii 40 de ani” — era public, gratuit și stătea în calendar cu luni înainte." },
      calendarMatrix: {
        tag: "CALENDARUL — ORARUL VOLATILITĂȚII",
        title: "Matricea de impact",
        preamble: "Patru publicații mișcă piețele cel mai puternic. Mai jos nu e o estimare din ochi, ci mișcarea măsurată a prețului într-o oră după publicare, raportată la amplitudinea zilnică obișnuită a instrumentului, ca să poți compara coloanele direct.",
        methodologyTitle: "Cum s-a calculat",
        methodologyBody: "Numărul mare din celulă e mișcarea medie a prețului în 60 de minute după publicare, împărțită la amplitudinea zilnică mediană (H-L) a instrumentului din ultimul an: 0.4 înseamnă „mișcarea tipică a fost 40% din amplitudinea zilnică obișnuită”, comparabil direct între XAU/USD, DXY, S&P 500 și BTC/USD. Cifra mică de dedesubt e aceeași mișcare în puncte de preț, ca referință. XAU/USD vine din motorul viu Layer 1 (istoric din iulie 2024, până la 12 cazuri per celulă), recalculat zilnic. DXY/S&P 500/BTC sunt calculate prin aceeași metodă pe bekfill-ul nostru mai scurt MT5 (~2.5–3 luni) — cinstit mai puține cazuri, de aceea și mai des atenuate. Celulele S&P 500 pentru NFP/CPI/GDP sunt goale nu din greșeală: aceste publicații apar la 12:30–13:30 UTC, înainte de deschiderea sesiunii de zi a bursei — în bekfill în acel moment pur și simplu nu există cotații S&P.",
        colEvent: "Publicație", colGold: "XAU/USD", colDxy: "DXY", colSpx: "S&P 500", colBtc: "BTC/USD",
        move30Label: "30 min", move60Label: "60 min", casesLabel: "cazuri", casesLabelOne: "caz",
        noDataCell: "fără date în istoricul nostru",
        naLabel: "fără date",
        rawUnit: " pct",
        lowSampleLegend: "Celulele atenuate cu hașură — sub 4 observații: ilustrare a metodei, nu un tipar.",
        smallSampleTag: "puține cazuri — nu e un tipar, e o ilustrare a metodei",
        spxGapNote: "Celulele S&P 500 pentru NFP/CPI/GDP sunt goale nu din greșeală: aceste publicații apar la 12:30–13:30 UTC, înainte de deschiderea sesiunii de zi a bursei (13:30 UTC) — în bekfill-ul nostru pur și simplu nu există cotații S&P în acel moment, tranzacționarea încă n-a început.",
        goldSourceNote: "XAU/USD — motorul viu Layer 1, recalculat zilnic, istoric din iulie 2024.",
        freshSourceNote: "DXY/S&P 500/BTC — același calcul, pe bekfill-ul nostru propriu MT5 (~2.5–3 luni), actualizat manual odată cu capitolul.",
        nextReleaseTag: "URMĂTOAREA PUBLICAȚIE IMPORTANTĂ",
        nextReleaseLoading: "Verific calendarul…",
        nextReleaseNone: "Nu s-au găsit publicații de impact mare în următoarele 30 de zile.",
        nextReleaseError: "Calendarul nu e disponibil chiar acum.",
        countdownDay: "z", countdownHour: "o", countdownMin: "m",
        safetyTag: "REGULA DE SIGURANȚĂ PENTRU ÎNCEPĂTORI",
        safetyBody: "Cu 15 minute înainte de o publicație importantă, închide terminalul dacă nu ai un plan. Spread-ul se lărgește de mai multe ori, stop-urile alunecă — stația 11 (francul, 2015) a arătat limita până unde poate merge acest risc.",
        jumpToSnbStation: "↑ Mergi la stația 11",
        cpiSceneTag: "SCENĂ — O SINGURĂ CIFRĂ RĂSTOARNĂ UN TREND",
        cpiSceneLegend: "10 noiembrie 2022, ora 13:30 UTC: apare CPI-ul SUA pe octombrie — mai răcoros decât prognoza. Aurul scădea de opt luni în ciclul de majorare a dobânzii Fed. Vezi ce s-a întâmplat în ora următoare, pe cotații reale de minut.",
        cpiSceneQuestion: "Ai o poziție long pe aur, deschisă înainte de publicare. Ce faci cu un minut înainte de apariția CPI?",
        cpiSceneOptions: ["Închid poziția înainte de cifră", "Las totul așa cum e, nu ating stop-ul", "Lărgesc stop-ul din timp", "Dublez poziția înainte de cifră"],
        cpiSceneReveal: "Nu există un răspuns optim pentru ORICE cifră viitoare — altfel piața ar fi previzibilă. „Închid înainte de cifră” evită garantat riscul de gap, dar garantat nici nu participă dacă cifra e favorabilă. „Dublez înainte de cifră” e opusul managementului de risc: dublează atât câștigul potențial, cât și pierderea potențial ireversibilă, în aceeași secundă. Aici cifra concretă a ieșit favorabilă — dar scena e tocmai despre faptul că, ÎNAINTE de dezvăluire, asta nu știa nimeni în această cameră.",
      },
    },
    en: {
      coldOpen: { headline: "March 2, 2020. The market is falling for the eighth day.", body: "Tomorrow the Federal Reserve will do something it hasn't done since the 2008 crisis — and the market will react differently than almost everyone watching this chart right now expects. You get one decision and one shot. Same as everyone, that day." },
      antiMyth: { tag: "ANTI-MYTH", no: "✗ \"Rates, inflation, central banks — that's macroeconomics for analysts, has nothing to do with trading\"", body: "A critical mistake. The interest rate is the price of money itself, and everything you see in the terminal costs money. When the price of money changes, everything gets repriced: stocks, bonds, gold, crypto, currencies — all at once, just with different force and sign. A trader who doesn't know the central bank calendar is a surfer who doesn't know the tide schedule." },
      voice: { tag: "SBF'S VOICE", body: "\"Colleague, in twenty years on the market I learned one simple thing: you can hold out against a trend, you can hold out against a session, you cannot hold out against a rate. In this chapter we won't cover 'what is a rate' from a textbook — we'll cover how to read the largest organizations by their own schedule, and what gold does when they start disagreeing with each other. And they're disagreeing right now.\"" },
      cost: { tag: "2022", body: "An investor \"rides out\" a drawdown in the classic 60/40 portfolio — \"diversification protects, after all.\" The year's result: S&P 500 −18%, bonds −13% — the worst joint decline in almost a century. One fact — \"the Fed started the fastest hiking cycle in 40 years\" — was public, free, and had been sitting on the calendar for months." },
      calendarMatrix: {
        tag: "THE CALENDAR — A SCHEDULE OF VOLATILITY",
        title: "Impact matrix",
        preamble: "Four releases move markets the hardest. What's below isn't an eyeballed guess — it's the measured price move in the hour after publication, scaled to the instrument's normal daily range, so the columns can be compared directly.",
        methodologyTitle: "How this is computed",
        methodologyBody: "The large number in each cell is the average price move in the 60 minutes after the release, divided by the instrument's median daily range (H-L) over the last year: 0.4 means \"the typical move was 40% of a normal day's range\" — directly comparable across XAU/USD, DXY, S&P 500 and BTC/USD. The small figure underneath is the same move in the instrument's own price points, for reference. XAU/USD comes from the live Layer 1 engine (history since July 2024, up to 12 cases per cell), recomputed daily. DXY/S&P 500/BTC are computed the same way on our shorter MT5 backfill (~2.5-3 months) — honestly fewer cases, so muted more often. The S&P 500 cells for NFP/CPI/GDP are empty, not broken: these releases land at 12:30–13:30 UTC, before the day session opens — the backfill simply has no S&P quotes at that moment.",
        colEvent: "Release", colGold: "XAU/USD", colDxy: "DXY", colSpx: "S&P 500", colBtc: "BTC/USD",
        move30Label: "30 min", move60Label: "60 min", casesLabel: "cases", casesLabelOne: "case",
        noDataCell: "no data in our history",
        naLabel: "no data",
        rawUnit: " pt",
        lowSampleLegend: "Muted, hatched cells — fewer than 4 observations: an illustration of the method, not a pattern.",
        smallSampleTag: "few cases — an illustration of the method, not a pattern",
        spxGapNote: "The S&P 500 cells for NFP/CPI/GDP are empty, not broken: these releases land at 12:30–13:30 UTC, before the day session opens (13:30 UTC) — our backfill simply has no S&P quotes at that moment, trading hasn't started yet.",
        goldSourceNote: "XAU/USD — Layer 1's live engine, recomputed daily, history since July 2024.",
        freshSourceNote: "DXY/S&P 500/BTC — the same calculation, on our own MT5 backfill (~2.5-3 months), updated manually alongside the chapter.",
        nextReleaseTag: "NEXT HIGH-IMPACT RELEASE",
        nextReleaseLoading: "Checking the calendar…",
        nextReleaseNone: "No high-impact releases found in the next 30 days.",
        nextReleaseError: "The calendar isn't reachable right now.",
        countdownDay: "d", countdownHour: "h", countdownMin: "m",
        safetyTag: "BEGINNER SAFETY RULE",
        safetyBody: "15 minutes before a high-impact release, close the terminal if you don't have a plan. The spread widens several times over, stops slip — station 11 (the franc, 2015) showed how far that risk can go.",
        jumpToSnbStation: "↑ Jump to station 11",
        cpiSceneTag: "SCENE — ONE NUMBER REVERSES A TREND",
        cpiSceneLegend: "November 10, 2022, 13:30 UTC: October US CPI comes in cooler than forecast. Gold had been falling for eight months into the Fed's hiking cycle. Watch what happened over the next hour on real minute-level quotes.",
        cpiSceneQuestion: "You're holding a long gold position opened before the release. What do you do a minute before CPI hits the wire?",
        cpiSceneOptions: ["Close the position before the number", "Leave it as is, don't touch the stop", "Widen the stop in advance", "Double the position before the number"],
        cpiSceneReveal: "There's no optimal answer for ANY future number — otherwise markets would be predictable. \"Close before the number\" guarantees you dodge gap risk, but also guarantees you miss out if the number goes your way. \"Double before the number\" is the opposite of risk management: it doubles both the potential gain and the potential irreversible loss, in the same second. Here this particular number happened to be favorable — but the scene is precisely about the fact that, before the reveal, nobody in this room knew that.",
      },
    },
  };
})();
