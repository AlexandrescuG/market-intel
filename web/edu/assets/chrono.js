/* Хроно-машина: контент станций истории рынка (SPEC_edu_level1_history.md §3 + расширение по фидбэку 23.07.2026:
   1602→1929 обогащены, 1971→2021 разбиты на отдельные станции вместо одной "1971→сегодня" — чем ближе к
   настоящему, тем плотнее остановки. window.ChronoStations = {ru:[...], ro:[...], en:[...]} — 13 объектов на язык. */
(function(){
  var STATIONS = {

    ru: [
      {
        id: "1602", year: "1602–1610", place: "Амстердам",
        title: "Рождение акции — и сразу же шорта",
        body: "Голландской Ост-Индской компании (VOC) нужны деньги на дорогие и рискованные экспедиции в Азию. Раньше такие плавания финансировали разовыми паями на один рейс: корабль вернулся — пайщики поделили прибыль и разошлись. VOC делает то, чего не было ни у кого: капитал становится постоянным, а доли — акциями, которые можно продать другому инвестору, не дожидаясь конца компании. Это и есть рождение акции в современном смысле. Старейшая сохранившаяся акция датирована 1606 годом. Уже через два года акционер-бунтарь Исаак Ле Мэр собирает тайный синдикат и играет на понижение — первая в истории скоординированная шорт-атака. В 1610-м власти отвечают первым в истории официальным запретом коротких продаж.",
        fact: "Первый регулятор появился не против жадности покупателей — против продавцов пустоты. Спор «запрещать ли шорты» старше США на полтора века.",
        hook: "Шорт-атаки живы: GameStop, 2021 — станция 12.",
        legend: null,
        source: "beursgeschiedenis.nl · worldsfirststockexchange.com",
        illustration: "1602_beurs"
      },
      {
        id: "1720", year: "1720", place: "Лондон / Париж / Амстердам",
        title: "Год, когда лопнуло всё",
        body: "South Sea Company в Лондоне получает от короны монополию на торговлю с Южной Америкой и, по сути, конвертирует государственный долг в свои акции — сама схема разгоняет спрос. Параллельно в Париже шотландец Джон Ло по похожей логике выпускает акции Компании Миссисипи, обеспеченные бумажными деньгами его же банка. Обе истории поднимают цену акций в 8 раз за несколько месяцев — и обрушивают в ноль, утянув за собой банк Ло и репутацию бумажных денег во Франции на десятилетия вперёд. В тот же 1720-й в Голландии издают альбом сатирических гравюр «Het Groote Tafereel der Dwaasheid» («Великое зерцало безумия») — свыше 70 карикатур на спекулянтов.",
        fact: "Среди проигравших — Исаак Ньютон (~£20 000). Его знаменитая фраза «могу рассчитать движение небесных тел, но не безумие толпы» — скорее всего, поздняя легенда.",
        hook: "Пузырь не требует интернета. Достаточно толпы и истории про «новую эру».",
        legend: "Ньютон-цитата — вероятно, поздняя легенда",
        source: "Wikimedia Commons · Harvard CURIOSity",
        illustration: "1720_tafereel"
      },
      {
        id: "1730", year: "1730", place: "Осака",
        title: "Рис, самураи и прото-свечи",
        body: "В Японии эпохи Токугава рис — не просто еда, а фактическая валюта: жалование самураев измеряется в коку риса, и колебания урожая швыряют экономику страны из стороны в сторону. Рисовая биржа Додзима в Осаке получает официальный статус — первый в мире организованный рынок фьючерсов: торгуют не рисом, а расписками, обещаниями поставить рис в будущем. Легендарный трейдер Мунэхиса Хомма зарабатывает состояние, изучая не только урожаи, но и психологию торговцев — говорят, у него была сеть наблюдателей, передававших новости флажками между городами быстрее обычных гонцов.",
        fact: "«Хомма изобрёл свечной график» — красивая легенда: в современном виде свечи оформились в Японии лишь к концу XIX века, а Запад узнал о них в 1991-м от Стива Нисона.",
        hook: "Тап — «прото-запись цен риса» превращается в современную свечу.",
        legend: "Хомма-свечи — легенда об изобретении в XVIII веке не подтверждается",
        source: "Wikipedia (Honma Munehisa) · FTMO",
        illustration: "1730_dojima"
      },
      {
        id: "1792", year: "1792", place: "Нью-Йорк",
        title: "Платан на Уолл-стрит",
        body: "24 маклера договариваются торговать друг с другом под платаном на Уолл-стрит — фиксированная комиссия 0.25%, никаких сделок со сторонними аукционистами. Соглашение уместилось в один абзац — «Buttonwood Agreement» — и не требовало ни здания, ни лицензии, ни государственного разрешения: биржа не строилась государством, это картель уличных брокеров, решивших торговать друг с другом на своих условиях. Первое время маклеры буквально встречаются под тем же деревом или в кофейне Tontine Coffee House неподалёку — настоящее здание появится только десятилетия спустя.",
        fact: "0.25% комиссии тогда — 0.00% у брокеров сегодня. Кто теперь платит за твою сделку? Ответ — в главе 11 (PFOF/HFT).",
        hook: "Биржа НЕ строилась государством — это картель уличных брокеров, договорившихся торговать друг с другом.",
        legend: null,
        source: "Wikimedia Commons · NYPL Digital Collections",
        illustration: "1792_buttonwood"
      },
      {
        id: "1867", year: "1867", place: "Нью-Йорк",
        title: "Скорость становится деньгами",
        body: "Эдвард Калахан запускает биржевой тикер 15 ноября 1867-го — котировки впервые покидают операционный зал биржи и бегут по проводам в брокерские конторы города. Молодой изобретатель Томас Эдисон улучшает устройство настолько, что в 1869-м продаёт патент на «Универсальный биржевой тикер» за $40 000 — огромные деньги, на которые он открывает свою первую настоящую лабораторию в Нью-Джерси. Отработанная бумажная лента становится конфетти — так рождаются ticker-tape парады, традиция, которая переживёт сам тикер на век с лишним.",
        fact: "В крах 29 октября 1929-го объём так велик, что лента отстаёт на часы — люди продавали, не зная текущих цен. Сегодня та же гонка идёт на микросекундах.",
        hook: "Ползунок: путь котировки Нью-Йорк → Лондон: 1830 — недели, 1866 — минуты, сегодня — 60 мс.",
        legend: null,
        source: "history.com · Scientific American",
        illustration: "1867_ticker"
      },
      {
        id: "1929", year: "1929", place: "Нью-Йорк",
        title: "Чёрный октябрь",
        body: "−89% индекса Доу-Джонса за три года — начало Великой депрессии. Обвал случается не за один день: 24 октября, «Чёрный четверг», паника настолько сильна, что группа крупнейших банкиров Уолл-стрит демонстративно скупает акции блue chips на бирже, чтобы остановить обвал, — и несколько дней это работает. Но 28 и 29 октября («Чёрный понедельник» и «Чёрный вторник») распродажа возвращается уже без спасителей. REPLAY: ты в Нью-Йорке, 3 сентября 1929-го, индекс на историческом пике. Дальше — сам.",
        fact: "Байка о чистильщике обуви, который давал советы по акциям самому Джозефу Кеннеди, — символ пика толпы: когда рынок обсуждают все, покупать поздно.",
        hook: "−12.8% 28 октября, −11.7% 29 октября, дно −198.69 13 ноября.",
        legend: "чистильщик обуви — байка эпохи, но индикатор реальный",
        source: "Library of Congress (PD)",
        illustration: "1929_crowd"
      },
      {
        id: "1971", year: "1971", place: "Нью-Йорк",
        title: "NASDAQ: биржа без зала",
        body: "8 февраля 1971 года начинает работу NASDAQ — National Association of Securities Dealers Automated Quotations, первая в мире полностью электронная биржа. У неё нет ни зала, ни маклеров в пиджаках, выкрикивающих цены: свыше 2500 бумаг котируются через компьютерную сеть дилеров, которые обновляют цены покупки и продажи со своих терминалов. Систему строит компания Bunker Ramo. Задача была прагматичной — избавить внебиржевой рынок от разрозненных телефонных котировок и дать единую электронную ленту. Но по факту это первый шаг к миру, где цена рождается не в зале, а в сети.",
        fact: "NASDAQ на старте — не биржа исполнения сделок, а система котировок: сами сделки ещё долго заключались по телефону между дилерами. Полностью электронное исполнение придёт лишь спустя десятилетия — но принцип «цена живёт в сети, а не в зале» уже необратим.",
        hook: "Полвека спустя на этой самой электронной архитектуре вырастет HFT — торговля на микросекундах (глава 11).",
        legend: null,
        source: "Nasdaq.com · Encyclopedia.com",
        illustration: "1971_nasdaq"
      },
      {
        id: "1987", year: "1987", place: "Нью-Йорк",
        title: "Чёрный понедельник",
        body: "19 октября 1987 года индекс Доу-Джонса падает на 508.32 пункта — 22.61% за один день. Это по-прежнему крупнейшее однодневное процентное падение в истории индекса, хуже даже дня паники 1929-го. Триггеров несколько — переоценённый рынок, рост ставок, паника вслед за утренними обвалами азиатских и европейских площадок, — но масштаб катастрофы объясняет технология: программы «страхования портфеля» автоматически продают акции при падении цены, чтобы ограничить убыток. Чем больше падает рынок, тем больше автоматических продаж это запускает — замкнутый контур из кода, который сам себя раскручивает.",
        fact: "Разбираться в причинах паники будет специальная президентская комиссия (Brady Commission) — один из первых официальных документов, прямо указавших на программную торговлю как усилитель обвала.",
        hook: "Тот же принцип — алгоритм, реагирующий на алгоритм, — вернётся в 2010-м на станции Flash Crash.",
        legend: null,
        source: "Federal Reserve History · Wikipedia",
        illustration: "1987_blackmonday"
      },
      {
        id: "2000", year: "2000", place: "Кремниевая долина",
        title: "Пузырь доткомов",
        body: "К концу 1990-х достаточно добавить «.com» к названию компании, чтобы её акции взлетели — даже без прибыли, иногда почти без выручки. 10 марта 2000 года индекс NASDAQ Composite достигает пика 5132.52 пункта. Дальше — обвал: к 9 октября 2002-го индекс падает до 1114.11 — минус 78% за полтора года, около $5 трлн рыночной стоимости испаряется. Компании вроде Pets.com и Webvan, ещё вчера казавшиеся будущим розницы, закрываются одна за другой.",
        fact: "Некоторые из «мертвецов» пузыря были правы по сути идеи — просто на 10–15 лет раньше срока: доставка продуктов на дом и товаров для животных онлайн станут гигантскими бизнесами (Amazon, Chewy) — но уже после того, как рынок перестанет прощать компаниям убытки без плана их прекращения.",
        hook: "Тот же вопрос — «прибыль когда-нибудь будет?» — рынок будет задавать каждому новому технологическому циклу, включая ИИ-компании 2020-х.",
        legend: null,
        source: "internationalbanker.com · Nasdaq.com",
        illustration: "2000_dotcom"
      },
      {
        id: "2008", year: "2008", place: "Нью-Йорк",
        title: "Lehman Brothers: крупнейшее банкротство",
        body: "15 сентября 2008 года банк Lehman Brothers подаёт на банкротство — $639 млрд активов и $613 млрд долгов, крупнейшее банкротство в истории США. Это кульминация ипотечного кризиса: банки годами продавали и перепродавали друг другу облигации, обеспеченные некачественными ипотечными кредитами, пока не выяснилось, что риск никуда не делся — он просто спрятался внутри сложных финансовых инструментов. В день объявления Доу-Джонс падает на 4.4%. Пика в 14 164.53 пункта (9 октября 2007-го) индекс достигнет снова только через годы: дно в 6469.95 пункта придёт 6 марта 2009-го — минус 54% от пика.",
        fact: "Lehman не спасли сознательно — власти дали банку упасть, чтобы не создавать прецедент бесконечных господдержек. Спустя несколько дней AIG всё же спасают на $180+ млрд — непоследовательность решений сама стала темой расследований на годы вперёд.",
        hook: "Урок 2008-го звучит совсем как урок 1929-го: технологии финансов усложнились до неузнаваемости, а причина обвала осталась той же — долг, который считали безопасным, оказался не таким.",
        legend: null,
        source: "history.com · Wikipedia (Bankruptcy of Lehman Brothers)",
        illustration: "2008_lehman"
      },
      {
        id: "2010", year: "2010", place: "Нью-Йорк",
        title: "Flash Crash: 36 минут",
        body: "6 мая 2010 года, 14:32 по нью-йоркскому времени: индекс Доу-Джонса начинает стремительно падать. К 14:47 — минус около 600 пунктов всего за 5 минут, суммарно около 998.5 пункта (~9%) внутри дня. Котировки некоторых крупных компаний на несколько секунд улетают к $0.01 или взлетают до $100 000 — алгоритмы теряют якорь реальности. К 15:07, всего через 36 минут после начала, рынок отыгрывает большую часть падения. Расследование позже укажет на крупный автоматический ордер на продажу фьючерсов, который взаимодействовал с высокочастотными алгоритмами и запустил каскад.",
        fact: "Одним из обвиняемых по итогам расследования стал лондонский трейдер-одиночка, торговавший из спальни родительского дома, — что показало: рынком, который двигает триллионы, можно дестабилизировать и не будучи гигантским банком.",
        hook: "36 минут — и это уже не метафора «скорость становится деньгами» со станции 1867-го, а буквальный секундомер.",
        legend: null,
        source: "2010 Flash Crash, Wikipedia · CityAM",
        illustration: "2010_flashcrash"
      },
      {
        id: "2020", year: "2020", place: "Нью-Йорк / весь мир",
        title: "COVID-крах: −34% за 33 дня",
        body: "19 февраля 2020-го индекс S&P 500 на историческом пике. Дальше — самый быстрый обвал в истории: к 23 марта индекс теряет 34% всего за 33 дня, обгоняя по скорости даже 1929-й и 2008-й. В течение марта биржевые автоматические предохранители (circuit breakers) останавливают торги на 15 минут четыре раза — 9, 12, 16 и 18 марта, — такого не случалось со времён их введения после 1987-го. Ответ ФРС беспрецедентен: ставки обнулены за считаные дни, в экономику вливают около $3 трлн, населению рассылают прямые чеки.",
        fact: "Рынок не просто восстановился — он вырос вдвое к концу 2021-го. Инвесторы, которые в панике продали в марте 2020-го у самого дна, зафиксировали убыток за несколько дней до начала одного из сильнейших ралли в истории.",
        hook: "Урок звучит как эхо 1929-го и 2008-го: паника — худший советник, а скорость обвала больше не измеряется годами.",
        legend: null,
        source: "S&P Dow Jones Indices · Federal Reserve",
        illustration: "2020_covid"
      },
      {
        id: "2021", year: "2021", place: "Reddit / Уолл-стрит",
        title: "GameStop: сквиз толпы",
        body: "Хедж-фонды вроде Melvin Capital годами держат крупную короткую позицию по акциям GameStop, сети магазинов видеоигр, которую с приходом цифровых загрузок многие считают бизнесом на грани исчезновения. В январе 2021-го пользователи форума r/WallStreetBets на Reddit замечают: шортов у фондов больше, чем акций в свободном обращении — скоординированная скупка заставит их закрывать позиции покупкой, толкая цену ещё выше. План срабатывает: 27 января акция достигает внутридневного пика $483 против $20 в начале месяца. Melvin Capital, начавший год с $12.5 млрд под управлением, теряет около половины и получает экстренные $2.75 млрд от Citadel и Point72, лишь бы не закрыться немедленно, — фонд всё равно ликвидируют в 2022-м.",
        fact: "Механика этой атаки — толпа розничных инвесторов ставит против концентрированной короткой позиции — зеркально повторяет то, что делал Исаак Ле Мэр в 1608-м, только наоборот: тогда синдикат инсайдеров играл против компании, теперь толпа с брокерскими приложениями играет против фонда.",
        hook: "Кольцо истории замкнулось: первая станция хроники и эта решают одну и ту же задачу — кто контролирует цену, когда все смотрят в одну сторону.",
        legend: null,
        source: "TradingSim · TheStreet · MarketsWiki",
        illustration: "2021_gamestop"
      },
      {
        id: "2022", year: "2022", place: "Москва / Лондон / весь мир",
        title: "Война в Украине: рынок как барометр",
        body: "24 февраля 2022-го Россия начинает полномасштабное вторжение в Украину. В тот же день Московская биржа останавливает торги по всем инструментам — и не открывается почти месяц, до 24 марта, частично и только по 33 крупнейшим бумагам. Индекс MOEX в день вторжения падает рекордные −45% за одну сессию. Нефть Brent взлетает выше $100 впервые с 2014-го, а 7 марта достигает $139 — максимума с 2008 года. Европейские цены на газ бьют рекорды на фоне угрозы обрыва поставок. Индекс страха VIX подскакивает на 20%.",
        fact: "Западные страны замораживают около $300 млрд резервов российского центробанка — беспрецедентный шаг, которого раньше не применяли против экономики такого масштаба. Рубль обваливается почти до 118 за доллар, но позже частично отыгрывает падение благодаря жёстким валютным ограничениям Центробанка.",
        hook: "Рынок реагирует не на войну саму по себе, а на то, что она перекраивает — потоки нефти, газа и капитала — иногда быстрее, чем успевают отреагировать регуляторы.",
        legend: null,
        source: "Reuters · Forbes · EIA",
        illustration: "2022_ukraine"
      },
      {
        id: "today", year: "Сегодня", place: "Везде",
        title: "Экраны, алгоритмы, ты",
        body: "От Амстердама-1602 до смартфона в твоём кармане — 400 с лишним лет, и каждая станция хроники доказывала одно и то же: технологии менялись каждый раз, жадность и страх — ни разу. Хроника догнала настоящее. Дальше в курсе — не история, а инструменты: как читать график, где рынок прав, а где им управляют эмоции толпы, и что со всем этим знанием делать тебе.",
        fact: "Технологии менялись каждый раз. Жадность и страх — ни разу.",
        hook: "Хроника догнала настоящее. Вот живой график — таким его видит аналитик SBF сегодня.",
        legend: null,
        source: "Commons · U.S. National Archives",
        illustration: "today_terminal",
        bridge: true
      }
    ],

    ro: [
      {
        id: "1602", year: "1602–1610", place: "Amsterdam",
        title: "Nașterea acțiunii — și imediat a short-ului",
        body: "Compania Olandeză a Indiilor de Est (VOC) are nevoie de bani pentru expediții scumpe și riscante în Asia. Înainte, astfel de călătorii erau finanțate prin participații pe o singură cursă: corabia se întorcea, participanții împărțeau profitul și se despărțeau. VOC face ceva ce nimeni nu mai făcuse: capitalul devine permanent, iar participațiile — acțiuni care pot fi vândute altui investitor fără a aștepta sfârșitul companiei. Aceasta este, în sens modern, nașterea acțiunii. Cea mai veche acțiune păstrată datează din 1606. Doi ani mai târziu, acționarul-rebel Isaac Le Maire formează un sindicat secret și pariază pe scădere — primul atac short coordonat din istorie. În 1610, autoritățile răspund cu prima interdicție oficială a vânzărilor short din istorie.",
        fact: "Primul regulator nu a apărut împotriva lăcomiei cumpărătorilor — ci împotriva celor care vindeau ceva ce nu aveau. Disputa „interzicem sau nu short-urile” e mai veche decât SUA cu un secol și jumătate.",
        hook: "Atacurile short trăiesc și azi: GameStop, 2021 — stația 12.",
        legend: null,
        source: "beursgeschiedenis.nl · worldsfirststockexchange.com",
        illustration: "1602_beurs"
      },
      {
        id: "1720", year: "1720", place: "Londra / Paris / Amsterdam",
        title: "Anul în care a explodat totul",
        body: "South Sea Company din Londra primește de la coroană monopolul comerțului cu America de Sud și, practic, convertește datoria de stat în propriile acțiuni — schema în sine alimentează cererea. În paralel, la Paris, scoțianul John Law emite, după o logică similară, acțiuni ale Compania Mississippi, garantate cu bani de hârtie ai propriei sale bănci. Ambele povești fac acțiunile să crească de 8 ori în câteva luni — și se prăbușesc la zero, trăgând după ele banca lui Law și reputația banilor de hârtie în Franța pentru decenii înainte. În același 1720, în Olanda apare un album de gravuri satirice „Het Groote Tafereel der Dwaasheid” („Marea oglindă a nebuniei”) — peste 70 de caricaturi ale speculanților.",
        fact: "Printre cei care au pierdut — Isaac Newton (~20.000 de lire). Celebra sa frază despre „nebunia mulțimii” este, cel mai probabil, o legendă ulterioară.",
        hook: "O bulă speculativă nu are nevoie de internet. E suficientă o mulțime și o poveste despre o „eră nouă”.",
        legend: "citatul lui Newton — probabil o legendă ulterioară",
        source: "Wikimedia Commons · Harvard CURIOSity",
        illustration: "1720_tafereel"
      },
      {
        id: "1730", year: "1730", place: "Osaka",
        title: "Orez, samurai și proto-lumânări",
        body: "În Japonia erei Tokugawa, orezul nu e doar hrană, ci monedă de facto: solda samurailor se măsoară în koku de orez, iar variațiile recoltei zguduie întreaga economie a țării. Bursa de orez Dōjima din Osaka primește statut oficial — prima piață de futures organizată din lume: nu se tranzacționează orezul, ci bonuri, promisiuni de livrare viitoare. Legendarul trader Munehisa Homma face avere studiind nu doar recoltele, ci și psihologia negustorilor — se spune că avea o rețea de observatori care transmiteau vești prin steaguri între orașe mai repede decât curierii obișnuiți.",
        fact: "„Homma a inventat graficul cu lumânări” e o legendă frumoasă: forma modernă a lumânărilor s-a conturat în Japonia abia spre sfârșitul secolului XIX, iar Occidentul le-a aflat în 1991, de la Steve Nison.",
        hook: "Atinge ecranul — „înregistrarea proto” a prețului orezului se transformă într-o lumânare modernă.",
        legend: "lumânările lui Homma — legenda inventării în secolul XVIII nu e confirmată",
        source: "Wikipedia (Honma Munehisa) · FTMO",
        illustration: "1730_dojima"
      },
      {
        id: "1792", year: "1792", place: "New York",
        title: "Platanul de pe Wall Street",
        body: "24 de brokeri se înțeleg să tranzacționeze doar între ei sub un platan pe Wall Street — comision fix de 0.25%, fără tranzacții cu licitatori din afară. Acordul a încăput într-un singur paragraf — „Buttonwood Agreement” — și nu a necesitat nici clădire, nici licență, nici aprobare de stat: bursa nu a fost construită de stat, e un cartel de brokeri stradali care au decis să tranzacționeze după regulile lor. La început, brokerii se întâlneau chiar sub acel copac sau la cafeneaua Tontine Coffee House din apropiere — o clădire adevărată va apărea abia decenii mai târziu.",
        fact: "0.25% comision atunci — 0.00% la brokerii de azi. Cine plătește acum pentru tranzacția ta? Răspunsul — în capitolul 11 (PFOF/HFT).",
        hook: "Bursa NU a fost construită de stat — e un cartel de brokeri stradali care au decis să tranzacționeze între ei.",
        legend: null,
        source: "Wikimedia Commons · NYPL Digital Collections",
        illustration: "1792_buttonwood"
      },
      {
        id: "1867", year: "1867", place: "New York",
        title: "Viteza devine bani",
        body: "Edward Calahan lansează telegraful bursier (ticker) pe 15 noiembrie 1867 — cotațiile părăsesc pentru prima dată sala de tranzacționare și circulă pe fire până la birourile brokerilor din oraș. Tânărul inventator Thomas Edison îmbunătățește dispozitivul atât de mult încât în 1869 vinde brevetul „Ticker-ului Universal” pentru 40.000 de dolari — bani uriași cu care își deschide primul laborator adevărat, în New Jersey. Banda de hârtie uzată devine confetti — așa se nasc paradele „ticker-tape”, o tradiție care va supraviețui tickerului însuși cu peste un secol.",
        fact: "În prăbușirea din 29 octombrie 1929, volumul e atât de mare încât banda rămâne în urmă cu ore întregi — oamenii vindeau fără să cunoască prețurile curente. Astăzi aceeași cursă se dă la nivel de microsecundă.",
        hook: "Cursor: drumul unei cotații New York → Londra: 1830 — săptămâni, 1866 — minute, azi — 60 ms.",
        legend: null,
        source: "history.com · Scientific American",
        illustration: "1867_ticker"
      },
      {
        id: "1929", year: "1929", place: "New York",
        title: "Octombrie negru",
        body: "−89% indicele Dow Jones în trei ani — începutul Marii Depresiuni. Prăbușirea nu se întâmplă într-o singură zi: pe 24 octombrie, „Joia neagră”, panica e atât de puternică încât un grup de mari bancheri de pe Wall Street cumpără demonstrativ acțiuni blue chip la bursă pentru a opri căderea — și câteva zile funcționează. Dar pe 28 și 29 octombrie („Lunea neagră” și „Marțea neagră”) vânzările revin, deja fără salvatori. REPLAY: ești în New York, 3 septembrie 1929, indicele la vârf istoric. Restul depinde de tine.",
        fact: "Povestea despre lustragiul care i-ar fi dat sfaturi bursiere lui Joseph Kennedy este simbolul vârfului mulțimii: când toți vorbesc despre piață, e prea târziu să cumperi.",
        hook: "−12.8% pe 28 octombrie, −11.7% pe 29 octombrie, minim −198.69 pe 13 noiembrie.",
        legend: "lustragiul — o poveste de epocă, dar indicatorul e real",
        source: "Library of Congress (domeniu public)",
        illustration: "1929_crowd"
      },
      {
        id: "1971", year: "1971", place: "New York",
        title: "NASDAQ: bursă fără sală",
        body: "Pe 8 februarie 1971 începe să funcționeze NASDAQ — National Association of Securities Dealers Automated Quotations, prima bursă complet electronică din lume. Nu are nici sală, nici brokeri în costume strigând prețuri: peste 2500 de titluri sunt cotate printr-o rețea informatică de dealeri care își actualizează prețurile de cumpărare și vânzare de la terminale proprii. Sistemul e construit de compania Bunker Ramo. Scopul era pragmatic — să elimine cotațiile telefonice fragmentate de pe piața extrabursieră și să ofere o bandă electronică unică. Dar, de fapt, e primul pas către o lume în care prețul nu se naște în sală, ci în rețea.",
        fact: "NASDAQ, la început, nu e o bursă de execuție, ci un sistem de cotații: tranzacțiile în sine se încheiau încă multă vreme prin telefon, între dealeri. Execuția complet electronică va veni abia peste decenii — dar principiul „prețul trăiește în rețea, nu în sală” e deja ireversibil.",
        hook: "O jumătate de secol mai târziu, pe exact această arhitectură electronică va crește HFT-ul — tranzacționarea la nivel de microsecundă (capitolul 11).",
        legend: null,
        source: "Nasdaq.com · Encyclopedia.com",
        illustration: "1971_nasdaq"
      },
      {
        id: "1987", year: "1987", place: "New York",
        title: "Luni neagră",
        body: "Pe 19 octombrie 1987, indicele Dow Jones scade cu 508.32 de puncte — 22.61% într-o singură zi. Este și acum cea mai mare scădere procentuală într-o singură zi din istoria indicelui, mai gravă chiar decât ziua de panică din 1929. Sunt mai mulți factori declanșatori — o piață supraevaluată, creșterea dobânzilor, panica după prăbușirile burselor asiatice și europene de dimineață —, dar amploarea dezastrului se explică prin tehnologie: programele de „asigurare de portofoliu” vând automat acțiuni când prețul scade, pentru a limita pierderea. Cu cât piața scade mai mult, cu atât mai multe vânzări automate declanșează — un circuit închis de cod care se auto-alimentează.",
        fact: "Cauzele panicii vor fi analizate de o comisie prezidențială specială (Comisia Brady) — unul dintre primele documente oficiale care indică direct tranzacționarea programată drept amplificator al prăbușirii.",
        hook: "Același principiu — un algoritm care reacționează la alt algoritm — va reveni în 2010, la stația Flash Crash.",
        legend: null,
        source: "Federal Reserve History · Wikipedia",
        illustration: "1987_blackmonday"
      },
      {
        id: "2000", year: "2000", place: "Silicon Valley",
        title: "Bula dot-com",
        body: "Spre finalul anilor 1990, e suficient să adaugi „.com” la numele unei companii ca acțiunile ei să explodeze — chiar fără profit, uneori aproape fără venituri. Pe 10 martie 2000, indicele NASDAQ Composite atinge vârful de 5132.52 puncte. Urmează prăbușirea: până pe 9 octombrie 2002, indicele scade la 1114.11 — minus 78% în un an și jumătate, iar aproximativ 5 trilioane de dolari din valoarea de piață se evaporă. Companii precum Pets.com și Webvan, care ieri păreau viitorul comerțului, se închid una după alta.",
        fact: "Unii dintre „morții” bulei aveau, de fapt, dreptate în privința ideii — doar cu 10-15 ani prea devreme: livrarea alimentelor la domiciliu și a produselor pentru animale online vor deveni afaceri uriașe (Amazon, Chewy) — dar abia după ce piața a încetat să ierte companiile cu pierderi fără un plan de a le opri.",
        hook: "Aceeași întrebare — „va exista vreodată profit?” — piața o va pune fiecărui nou ciclu tehnologic, inclusiv companiilor de inteligență artificială din anii 2020.",
        legend: null,
        source: "internationalbanker.com · Nasdaq.com",
        illustration: "2000_dotcom"
      },
      {
        id: "2008", year: "2008", place: "New York",
        title: "Lehman Brothers: cel mai mare faliment",
        body: "Pe 15 septembrie 2008, banca Lehman Brothers intră în faliment — 639 de miliarde de dolari active și 613 miliarde datorii, cel mai mare faliment din istoria SUA. E punctul culminant al crizei creditelor ipotecare: băncile au vândut și revândut ani la rând obligațiuni garantate cu credite ipotecare de proastă calitate, până s-a dovedit că riscul nu dispăruse nicăieri — doar se ascunsese în instrumente financiare complexe. În ziua anunțului, Dow Jones scade cu 4.4%. Vârful de 14 164.53 puncte (9 octombrie 2007) va fi atins din nou abia peste ani: minimul de 6469.95 puncte vine pe 6 martie 2009 — minus 54% față de vârf.",
        fact: "Lehman nu a fost salvată în mod deliberat — autoritățile au lăsat banca să cadă, ca să nu creeze un precedent de salvări nesfârșite. La câteva zile după, AIG e totuși salvată cu peste 180 de miliarde de dolari — inconsecvența deciziilor a devenit ea însăși subiect de anchete pentru ani de zile.",
        hook: "Lecția din 2008 sună exact ca lecția din 1929: tehnologiile financiare s-au complicat până la a deveni de nerecunoscut, dar cauza prăbușirii a rămas aceeași — o datorie considerată sigură, care nu era.",
        legend: null,
        source: "history.com · Wikipedia (Bankruptcy of Lehman Brothers)",
        illustration: "2008_lehman"
      },
      {
        id: "2010", year: "2010", place: "New York",
        title: "Flash Crash: 36 de minute",
        body: "6 mai 2010, ora 14:32, ora New York-ului: indicele Dow Jones începe să scadă brusc. Până la 14:47 — minus circa 600 de puncte în doar 5 minute, în total aproximativ 998.5 puncte (~9%) în cursul zilei. Cotațiile unor companii mari zboară pentru câteva secunde spre 0.01 dolari sau urcă la 100.000 de dolari — algoritmii pierd orice ancoră în realitate. Până la 15:07, la doar 36 de minute de la început, piața recuperează cea mai mare parte a căderii. Ancheta ulterioară va indica un ordin automat mare de vânzare de futures, care a interacționat cu algoritmi de mare frecvență și a declanșat o cascadă.",
        fact: "Unul dintre acuzații în urma anchetei a fost un trader solitar din Londra, care tranzacționa din dormitorul casei părintești — ceea ce a arătat că o piață care mișcă trilioane poate fi destabilizată și fără a fi o bancă uriașă.",
        hook: "36 de minute — nu mai e metaforă „viteza devine bani” de la stația din 1867, ci un cronometru literal.",
        legend: null,
        source: "2010 Flash Crash, Wikipedia · CityAM",
        illustration: "2010_flashcrash"
      },
      {
        id: "2020", year: "2020", place: "New York / întreaga lume",
        title: "Prăbușirea COVID: −34% în 33 de zile",
        body: "Pe 19 februarie 2020, indicele S&P 500 se află la un maxim istoric. Urmează cea mai rapidă prăbușire din istorie: până pe 23 martie, indicele pierde 34% în doar 33 de zile, depășind ca viteză chiar și 1929 și 2008. În martie, întrerupătoarele automate de tranzacționare opresc bursa timp de 15 minute de patru ori — 9, 12, 16 și 18 martie —, ceva ce nu se mai întâmplase de la introducerea mecanismului după 1987. Răspunsul Fed este fără precedent: dobânzile sunt reduse la zero în câteva zile, aproximativ 3 trilioane de dolari sunt injectați în economie, iar populația primește cecuri de stimulare directă.",
        fact: "Piața nu doar și-a revenit — s-a dublat până la finalul lui 2021. Investitorii care au vândut în panică în martie 2020, aproape de minimul exact, și-au înregistrat pierderea cu doar câteva zile înainte de începutul uneia dintre cele mai puternice creșteri din istorie.",
        hook: "Lecția e un ecou al lui 1929 și 2008: panica e cel mai rău sfătuitor, iar viteza unei prăbușiri nu se mai măsoară în ani.",
        legend: null,
        source: "S&P Dow Jones Indices · Federal Reserve",
        illustration: "2020_covid"
      },
      {
        id: "2021", year: "2021", place: "Reddit / Wall Street",
        title: "GameStop: squeeze-ul mulțimii",
        body: "Fonduri speculative precum Melvin Capital dețin ani la rând o poziție short mare pe acțiunile GameStop, un lanț de magazine de jocuri video pe care mulți îl consideră o afacere pe cale de dispariție odată cu descărcările digitale. În ianuarie 2021, utilizatorii forumului r/WallStreetBets de pe Reddit observă: fondurile au mai multe poziții short decât acțiuni aflate în circulație liberă — o cumpărare coordonată le va forța să-și închidă pozițiile tot prin cumpărare, împingând prețul și mai sus. Planul funcționează: pe 27 ianuarie, acțiunea atinge un vârf intraday de 483 de dolari, față de 20 de dolari la începutul lunii. Melvin Capital, care a început anul cu 12.5 miliarde de dolari sub administrare, pierde aproape jumătate și primește o infuzie de urgență de 2.75 miliarde de la Citadel și Point72 doar ca să nu se închidă imediat — fondul e totuși lichidat în 2022.",
        fact: "Mecanica acestui atac — o mulțime de investitori de retail pariază împotriva unei poziții short concentrate — reproduce în oglindă ce făcea Isaac Le Maire în 1608, doar invers: atunci, un sindicat de inițiați juca împotriva companiei, acum mulțimea cu aplicații de brokeraj joacă împotriva fondului.",
        hook: "Cercul istoriei s-a închis: prima stație a cronicii și aceasta rezolvă aceeași problemă — cine controlează prețul când toată lumea privește în aceeași direcție.",
        legend: null,
        source: "TradingSim · TheStreet · MarketsWiki",
        illustration: "2021_gamestop"
      },
      {
        id: "2022", year: "2022", place: "Moscova / Londra / întreaga lume",
        title: "Războiul din Ucraina: piața ca barometru",
        body: "Pe 24 februarie 2022, Rusia lansează o invazie la scară largă a Ucrainei. În aceeași zi, Bursa din Moscova oprește tranzacționarea pe toate instrumentele — și nu se redeschide timp de aproape o lună, până pe 24 martie, și atunci doar parțial, pentru 33 dintre cele mai mari acțiuni. Indicele MOEX scade cu un record de −45% într-o singură sesiune, chiar în ziua invaziei. Petrolul Brent depășește 100 de dolari pentru prima dată din 2014, atingând 139 de dolari pe 7 martie — cel mai ridicat nivel din 2008. Prețurile gazelor în Europa ating recorduri pe fondul temerilor privind întreruperea aprovizionării. Indicele fricii VIX crește cu 20%.",
        fact: "Țările occidentale îngheață aproximativ 300 de miliarde de dolari din rezervele băncii centrale ruse — o măsură fără precedent, niciodată aplicată până atunci unei economii de această dimensiune. Rubla se prăbușește la aproape 118 pentru un dolar, înainte de a-și reveni parțial datorită controalelor valutare stricte impuse de banca centrală rusă.",
        hook: "Piața nu reacționează la război în sine, ci la ceea ce acesta reconfigurează — fluxurile de petrol, gaz și capital — uneori mai repede decât pot reacționa reglementatorii.",
        legend: null,
        source: "Reuters · Forbes · EIA",
        illustration: "2022_ukraine"
      },
      {
        id: "today", year: "Azi", place: "Peste tot",
        title: "Ecrane, algoritmi, tu",
        body: "De la Amsterdam-1602 până la smartphone-ul din buzunarul tău — peste 400 de ani, și fiecare stație a cronicii a demonstrat același lucru: tehnologiile s-au schimbat de fiecare dată, lăcomia și frica — niciodată. Cronica a ajuns din urmă prezentul. Mai departe în curs — nu istorie, ci instrumente: cum citești un grafic, unde piața are dreptate și unde e condusă de emoțiile mulțimii, și ce faci tu cu toată această cunoaștere.",
        fact: "Tehnologiile s-au schimbat de fiecare dată. Lăcomia și frica — niciodată.",
        hook: "Cronica a ajuns din urmă prezentul. Iată un grafic live — așa îl vede azi un analist SBF.",
        legend: null,
        source: "Commons · U.S. National Archives",
        illustration: "today_terminal",
        bridge: true
      }
    ],

    en: [
      {
        id: "1602", year: "1602–1610", place: "Amsterdam",
        title: "The birth of the share — and of the short sale",
        body: "The Dutch East India Company (VOC) needs money for expensive, risky expeditions to Asia. Such voyages used to be financed with one-trip stakes: the ship came back, the backers split the profit and went their separate ways. VOC does something nobody had done before: capital becomes permanent, and stakes become shares that can be sold to another investor without waiting for the company to end. That's the birth of the share in the modern sense. The oldest surviving share is dated 1606. Two years later, rebel shareholder Isaac Le Maire forms a secret syndicate and bets against the price — the first coordinated short attack in history. In 1610 the authorities respond with the first ever official ban on short selling.",
        fact: "The first regulator didn't target buyers' greed — it targeted sellers of nothing. The fight over banning short selling is a century and a half older than the United States.",
        hook: "Short attacks are alive today: GameStop, 2021 — station 12.",
        legend: null,
        source: "beursgeschiedenis.nl · worldsfirststockexchange.com",
        illustration: "1602_beurs"
      },
      {
        id: "1720", year: "1720", place: "London / Paris / Amsterdam",
        title: "The year everything popped",
        body: "The South Sea Company in London gets a crown monopoly on trade with South America and essentially converts government debt into its own shares — the scheme itself fuels demand. In parallel, in Paris, the Scotsman John Law issues shares in the Mississippi Company on similar logic, backed by paper money from his own bank. Both stories send share prices up 8x in a few months — and crash them to zero, dragging down Law's bank and the reputation of paper money in France for decades. That same year, 1720, the Dutch publish an album of satirical prints, \"Het Groote Tafereel der Dwaasheid\" (\"The Great Mirror of Folly\") — over 70 caricatures of speculators.",
        fact: "Among those wiped out was Isaac Newton (~£20,000). His famous line about calculating the motion of the heavens but not the madness of crowds is most likely a later legend.",
        hook: "A bubble doesn't need the internet. A crowd and a story about a \"new era\" are enough.",
        legend: "the Newton quote — likely a later legend",
        source: "Wikimedia Commons · Harvard CURIOSity",
        illustration: "1720_tafereel"
      },
      {
        id: "1730", year: "1730", place: "Osaka",
        title: "Rice, samurai, and proto-candles",
        body: "In Tokugawa-era Japan, rice isn't just food — it's the de facto currency: samurai stipends are measured in koku of rice, and harvest swings throw the whole economy around. The Dōjima Rice Exchange in Osaka gets official status — the world's first organized futures market: traders deal not in rice, but in vouchers, promises to deliver rice in the future. Legendary trader Munehisa Homma builds his fortune studying not just harvests but the psychology of merchants — he's said to have run a network of flag-signal observers relaying news between cities faster than ordinary couriers.",
        fact: "\"Homma invented the candlestick chart\" is a beautiful legend: candlesticks took their modern form in Japan only by the late 19th century, and the West only learned of them in 1991, from Steve Nison.",
        hook: "Tap — the \"proto-record\" of rice prices morphs into a modern candlestick.",
        legend: "Homma's candlesticks — the 18th-century invention story isn't confirmed",
        source: "Wikipedia (Honma Munehisa) · FTMO",
        illustration: "1730_dojima"
      },
      {
        id: "1792", year: "1792", place: "New York",
        title: "The buttonwood tree on Wall Street",
        body: "24 brokers agree to trade only with each other under a buttonwood tree on Wall Street — a fixed 0.25% commission, no dealing with outside auctioneers. The agreement fit in a single paragraph — the \"Buttonwood Agreement\" — and needed neither a building, nor a license, nor state approval: the exchange wasn't built by the state, it's a cartel of street brokers who decided to trade on their own terms. At first the brokers literally meet under that same tree, or at the nearby Tontine Coffee House — an actual building wouldn't appear for decades.",
        fact: "The agreement fit in a single paragraph and needed neither a building nor a license.",
        hook: "0.25% commission then — 0.00% at today's brokers. Who pays for your trade now? The answer is in chapter 11 (PFOF/HFT).",
        legend: null,
        source: "Wikimedia Commons · NYPL Digital Collections",
        illustration: "1792_buttonwood"
      },
      {
        id: "1867", year: "1867", place: "New York",
        title: "Speed becomes money",
        body: "Edward Calahan launches the stock ticker on November 15, 1867 — quotes leave the exchange floor for the first time and run over wires to brokers' offices across the city. Young inventor Thomas Edison improves the device so much that in 1869 he sells the patent for the \"Universal Stock Ticker\" for $40,000 — huge money that lets him open his first real lab, in New Jersey. Spent paper tape becomes confetti — that's how ticker-tape parades are born, a tradition that will outlive the ticker itself by over a century.",
        fact: "In the crash of October 29, 1929, volume is so heavy the tape runs hours behind — people sold without knowing current prices. Today the same race plays out in microseconds.",
        hook: "Slider: how long a quote took from New York to London — 1830: weeks, 1866: minutes, today: 60 ms.",
        legend: null,
        source: "history.com · Scientific American",
        illustration: "1867_ticker"
      },
      {
        id: "1929", year: "1929", place: "New York",
        title: "Black October",
        body: "Dow Jones −89% over three years — the start of the Great Depression. The crash doesn't happen in a single day: on October 24, \"Black Thursday,\" the panic is so severe that a group of top Wall Street bankers publicly buys up blue-chip shares on the floor to stop the slide — and for a few days it works. But on October 28 and 29 (\"Black Monday\" and \"Black Tuesday\") the selling returns, this time with no rescuers. REPLAY: you're in New York, September 3, 1929, the index at an all-time high. What happens next is up to you.",
        fact: "The tale of the shoeshine boy giving Joseph Kennedy stock tips is the symbol of a crowd at its peak: when everyone's talking about the market, it's too late to buy.",
        hook: "−12.8% on October 28, −11.7% on October 29, bottom at −198.69 on November 13.",
        legend: "the shoeshine boy — a period tale, but the indicator is real",
        source: "Library of Congress (public domain)",
        illustration: "1929_crowd"
      },
      {
        id: "1971", year: "1971", place: "New York",
        title: "NASDAQ: an exchange with no floor",
        body: "On February 8, 1971, NASDAQ — the National Association of Securities Dealers Automated Quotations — starts trading as the world's first fully electronic stock market. It has no floor, no brokers in suits shouting prices: over 2,500 securities are quoted through a computer network of dealers updating bid and ask prices from their own terminals. The system is built by the Bunker Ramo company. The goal was practical — to replace the over-the-counter market's scattered phone quotes with a single electronic feed. But in effect it's the first step toward a world where the price is born not on a floor, but on a network.",
        fact: "At launch NASDAQ isn't a trade-execution exchange but a quotation system — the trades themselves were still made by phone between dealers for a long time. Fully electronic execution wouldn't arrive for decades, but the principle that price lives on the network, not the floor, was already set.",
        hook: "Half a century later, HFT — trading at the microsecond level — will grow on this exact electronic architecture (chapter 11).",
        legend: null,
        source: "Nasdaq.com · Encyclopedia.com",
        illustration: "1971_nasdaq"
      },
      {
        id: "1987", year: "1987", place: "New York",
        title: "Black Monday",
        body: "On October 19, 1987, the Dow Jones falls 508.32 points — 22.61% in a single day. It's still the largest one-day percentage drop in the index's history, worse even than the 1929 panic day. There are several triggers — an overvalued market, rising rates, panic following that morning's crashes in Asian and European markets — but the scale of the disaster comes down to technology: \"portfolio insurance\" programs automatically sell shares as prices fall, to cap losses. The more the market drops, the more automatic selling that triggers — a closed loop of code feeding on itself.",
        fact: "A special presidential commission (the Brady Commission) will later investigate the causes — one of the first official documents to directly name program trading as an amplifier of the crash.",
        hook: "That same principle — an algorithm reacting to another algorithm — will return in 2010, at the Flash Crash station.",
        legend: null,
        source: "Federal Reserve History · Wikipedia",
        illustration: "1987_blackmonday"
      },
      {
        id: "2000", year: "2000", place: "Silicon Valley",
        title: "The dot-com bubble",
        body: "By the late 1990s, adding \".com\" to a company's name is enough to send its stock soaring — even with no profit, sometimes almost no revenue. On March 10, 2000, the NASDAQ Composite peaks at 5,132.52. Then comes the crash: by October 9, 2002, the index falls to 1,114.11 — down 78% in a year and a half, wiping out roughly $5 trillion in market value. Companies like Pets.com and Webvan, seen just yesterday as the future of retail, shut down one after another.",
        fact: "Some of the bubble's \"casualties\" were actually right about the underlying idea — just 10-15 years too early: home grocery delivery and online pet supplies would become giant businesses (Amazon, Chewy) — but only after the market stopped forgiving companies for losses with no plan to stop them.",
        hook: "The same question — \"will there ever be profit?\" — is one the market will keep asking every new tech cycle, including the AI companies of the 2020s.",
        legend: null,
        source: "internationalbanker.com · Nasdaq.com",
        illustration: "2000_dotcom"
      },
      {
        id: "2008", year: "2008", place: "New York",
        title: "Lehman Brothers: the biggest bankruptcy",
        body: "On September 15, 2008, Lehman Brothers files for bankruptcy — $639 billion in assets and $613 billion in debts, the largest bankruptcy in U.S. history. It's the culmination of the mortgage crisis: banks had spent years selling and reselling each other bonds backed by low-quality mortgage loans, until it turned out the risk hadn't gone anywhere — it had just hidden inside complex financial instruments. On the day of the announcement, the Dow falls 4.4%. The 14,164.53 peak from October 9, 2007 won't be reached again for years: the bottom, 6,469.95, comes on March 6, 2009 — down 54% from the peak.",
        fact: "Lehman wasn't deliberately saved — regulators let the bank fail so as not to set a precedent of endless bailouts. Days later AIG is bailed out anyway, for over $180 billion — the inconsistency itself became a subject of inquiries for years.",
        hook: "The lesson of 2008 sounds just like the lesson of 1929: financial technology had become unrecognizably complex, but the cause of the crash was the same — debt believed safe that wasn't.",
        legend: null,
        source: "history.com · Wikipedia (Bankruptcy of Lehman Brothers)",
        illustration: "2008_lehman"
      },
      {
        id: "2010", year: "2010", place: "New York",
        title: "The Flash Crash: 36 minutes",
        body: "May 6, 2010, 2:32 p.m. New York time: the Dow Jones starts falling fast. By 2:47 p.m. — down about 600 points in just 5 minutes, roughly 998.5 points (~9%) on the day in total. Quotes for some large companies flash down to $0.01 or up to $100,000 for a few seconds — the algorithms lose any anchor to reality. By 3:07 p.m., just 36 minutes after it began, the market claws back most of the drop. The later investigation points to a large automated futures sell order that interacted with high-frequency algorithms and set off a cascade.",
        fact: "One of those charged as a result of the investigation was a lone trader in London, trading from his parents' spare bedroom — showing that a market moving trillions can be destabilized without a giant bank being involved.",
        hook: "36 minutes — this time \"speed becomes money,\" the metaphor from the 1867 station, is a literal stopwatch.",
        legend: null,
        source: "2010 Flash Crash, Wikipedia · CityAM",
        illustration: "2010_flashcrash"
      },
      {
        id: "2020", year: "2020", place: "New York / worldwide",
        title: "The COVID crash: −34% in 33 days",
        body: "On February 19, 2020, the S&P 500 sits at an all-time high. What follows is the fastest crash in history: by March 23 the index has lost 34% in just 33 days, outpacing even 1929 and 2008 for speed. Through March, automatic circuit breakers halt trading for 15 minutes four separate times — March 9, 12, 16, and 18 — something that hadn't happened since the mechanism was introduced after 1987. The Fed's response is unprecedented: rates cut to zero within days, roughly $3 trillion pumped into the economy, direct stimulus checks mailed to households.",
        fact: "The market didn't just recover — it doubled by the end of 2021. Investors who panic-sold in March 2020 near the exact bottom locked in a loss just days before one of the strongest rallies in history began.",
        hook: "The lesson echoes 1929 and 2008: panic is the worst advisor, and crash speed is no longer measured in years.",
        legend: null,
        source: "S&P Dow Jones Indices · Federal Reserve",
        illustration: "2020_covid"
      },
      {
        id: "2021", year: "2021", place: "Reddit / Wall Street",
        title: "GameStop: the crowd's squeeze",
        body: "Hedge funds like Melvin Capital hold a large short position in GameStop, a video-game retail chain many consider a dying business in the age of digital downloads. In January 2021, users of the r/WallStreetBets forum on Reddit notice that funds are short more shares than exist in free float — a coordinated buying push will force them to close positions by buying too, pushing the price higher still. The plan works: on January 27 the stock hits an intraday peak of $483, up from $20 at the start of the month. Melvin Capital, which started the year managing $12.5 billion, loses roughly half and takes an emergency $2.75 billion injection from Citadel and Point72 just to avoid closing immediately — the fund is liquidated anyway in 2022.",
        fact: "The mechanics of this attack — a crowd of retail investors betting against a concentrated short position — mirror what Isaac Le Maire did in 1608, only in reverse: back then a syndicate of insiders played against the company; now a crowd with brokerage apps plays against the fund.",
        hook: "The circle of history closes: the chronicle's first station and this one solve the same problem — who controls the price when everyone's looking the same direction.",
        legend: null,
        source: "TradingSim · TheStreet · MarketsWiki",
        illustration: "2021_gamestop"
      },
      {
        id: "2022", year: "2022", place: "Moscow / London / worldwide",
        title: "The war in Ukraine: the market as a barometer",
        body: "On February 24, 2022, Russia launches a full-scale invasion of Ukraine. The same day, the Moscow Exchange halts trading across all instruments — and doesn't reopen for nearly a month, until March 24, and even then only partially, for 33 of the largest stocks. The MOEX index falls a record −45% in a single session on the day of the invasion. Brent crude jumps above $100 for the first time since 2014, hitting $139 on March 7 — the highest since 2008. European gas prices hit records on fears of supply disruption. The VIX fear index jumps 20%.",
        fact: "Western countries freeze roughly $300 billion of Russian central bank reserves — an unprecedented move never before applied to an economy this size. The ruble collapses to nearly 118 per dollar before partially recovering thanks to strict capital controls from Russia's central bank.",
        hook: "The market doesn't react to the war itself, but to what it reshapes — flows of oil, gas, and capital — sometimes faster than regulators can respond.",
        legend: null,
        source: "Reuters · Forbes · EIA",
        illustration: "2022_ukraine"
      },
      {
        id: "today", year: "Today", place: "Everywhere",
        title: "Screens, algorithms, you",
        body: "From Amsterdam in 1602 to the phone in your pocket — over 400 years, and every station of the chronicle proved the same thing: the technology changed every time, greed and fear never did. The chronicle has caught up with the present. What's next in the course isn't history — it's tools: how to read a chart, where the market is right and where it's driven by crowd emotion, and what you do with all of it.",
        fact: "The technology changed every time. Greed and fear never did.",
        hook: "The chronicle has caught up with the present. Here's a live chart — the way an SBF analyst sees it today.",
        legend: null,
        source: "Commons · U.S. National Archives",
        illustration: "today_terminal",
        bridge: true
      }
    ]

  };

  window.ChronoStations = STATIONS;
})();

/* Легенды 5 эпох интерактива B (FIX_chart_eras_explained.md, 23.07.2026) — правило трёх шагов
   ОБЪЯСНИ → ПОКАЖИ → ДАЙ СДЕЛАТЬ. Каждая эпоха: {tab (короткая подпись таба), what/how/why/notice
   (поля легенды), why может отсутствовать у последней эпохи}. window.ChronoEraLegends = {ru:[5],ro:[5],en:[5]}. */
(function(){
  window.ChronoEraLegends = {
    ru: [
      { tab: "1900 · Таблица",
        what: "Так рынок видели сто лет назад — утренняя газета, столбцы чисел: максимум, минимум, закрытие за вчера. Никакой картинки — только цифры.",
        how: "Строка = день; сравнивай закрытия соседних строк, чтобы понять, рос день или падал.",
        why: "Другого способа не существовало — печатный станок умел только текст.",
        notice: "Попробуй увидеть в столбце разворот тренда. Не получается? Именно поэтому появилось всё остальное." },
      { tab: "1930 · Линия от руки",
        what: "Те же закрытия, но нанесённые на миллиметровку рукой чартиста — каждая точка соединена линией.",
        how: "Ось слева — цена, ось снизу — дни; наклон линии = тренд.",
        why: "Человеческий глаз мгновенно видит форму там, где в числах слепнет. Чартисты 1930-х вели сотни таких листов карандашом — по листу на акцию.",
        notice: "Разворот, который ты не нашёл в таблице, здесь виден за секунду. Но график молчит о том, что творилось ВНУТРИ дня." },
      { tab: "P&F · Крестики-нолики",
        what: "Самый радикальный график в истории — из него выбросили время.",
        how: "X — цена выросла на шаг (например, $5), O — упала на шаг; пока рост продолжается — крестики ставят в ту же колонку вверх; разворот на 3 шага — начинается новая колонка (нолики вниз). День, неделя, месяц — неважно: если цена стоит на месте, график не двигается вообще.",
        why: "Телеграфисты и «читатели ленты» конца XIX века отмечали только значимые движения — бумага маленькая, движений много.",
        notice: "Длинная колонка = сильный тренд без передышки; частая смена колонок = рынок мечется. Твой «день разворота» здесь — момент, где кончилась длинная колонка O и начались X (◆-маркер подсветит)." },
      { tab: "1991 · Свечи",
        what: "Японские торговцы рисом научились записывать четыре цены дня одним знаком: открытие, максимум, минимум, закрытие. Тело свечи — от открытия до закрытия (зелёное — закрылись выше, красное — ниже), тени — до максимума и минимума.",
        how: "Одна свеча = один день целиком, включая борьбу внутри дня: длинная нижняя тень — продавцов продавили обратно; крошечное тело при огромных тенях — война без победителя.",
        why: "Свеча несёт всё, что несли таблица, линия и P&F, плюс психологию дня. Запад узнал этот способ только в 1991-м (Стив Нисон) — и за десятилетие свечи вытеснили всё.",
        notice: "◆-день — посмотри, какой драмой он был внутри, пока линия показывала просто «точку чуть ниже»." },
      { tab: "Сегодня · Терминал",
        what: "Те же свечи, но живые: уровни, на которые рынок опирался месяцами, события календаря, паттерны с историей отработки — слоями поверх цены.",
        how: "Это уже не запись прошлого, а рабочее место — всё, чему учит курс, отображается здесь.",
        why: "",
        notice: "◆-день на живом графике — с уровнем, который он пробил, и событием, которое его вызвало. История рисования графиков закончилась. Твоя — начинается." },
    ],
    ro: [
      { tab: "1900 · Tabel",
        what: "Așa arăta piața acum o sută de ani — ziarul de dimineață, coloane de cifre: maximul, minimul, închiderea de ieri. Nicio imagine — doar cifre.",
        how: "O linie = o zi; compară închiderile liniilor vecine ca să vezi dacă ziua a crescut sau a scăzut.",
        why: "Nu exista altă metodă — tiparul știa doar text.",
        notice: "Încearcă să vezi în coloană o întoarcere de trend. Nu reușești? Exact de asta a apărut tot restul." },
      { tab: "1930 · Grafic de mână",
        what: "Aceleași închideri, dar desenate de mână pe hârtie milimetrică de un chartist — fiecare punct unit printr-o linie.",
        how: "Axa din stânga e prețul, axa de jos sunt zilele; panta liniei e trendul.",
        why: "Ochiul uman vede instant o formă acolo unde cifrele orbesc. Chartiștii anilor 1930 țineau sute de astfel de foi în creion — o foaie per acțiune.",
        notice: "Întoarcerea pe care n-ai găsit-o în tabel se vede aici într-o secundă. Dar graficul tace despre ce s-a întâmplat ÎN interiorul zilei." },
      { tab: "P&F · X și O",
        what: "Cel mai radical grafic din istorie — a eliminat timpul din el.",
        how: "X — prețul a urcat un pas (de exemplu, 5$), O — a coborât un pas; cât timp creșterea continuă, X-urile se pun în aceeași coloană în sus; o întoarcere de 3 pași începe o coloană nouă (O-uri în jos). O zi, o săptămână, o lună — nu contează: dacă prețul stă pe loc, graficul nu se mișcă deloc.",
        why: "Telegrafiștii și „cititorii de bandă” de la finalul secolului XIX marcau doar mișcările semnificative — hârtia era mică, mișcările multe.",
        notice: "O coloană lungă înseamnă trend puternic fără pauză; schimbarea frecventă a coloanelor înseamnă o piață agitată. „Ziua de întoarcere” de aici e momentul în care s-a terminat coloana lungă de O și au început X-urile (marcajul ◆ o va evidenția)." },
      { tab: "1991 · Lumânări",
        what: "Comercianții japonezi de orez au învățat să înregistreze cele patru prețuri ale unei zile într-un singur semn: deschidere, maxim, minim, închidere. Corpul lumânării merge de la deschidere la închidere (verde — a închis mai sus, roșu — mai jos), umbrele ajung până la maxim și minim.",
        how: "O lumânare înseamnă o zi întreagă, inclusiv lupta din interiorul ei: o umbră inferioară lungă înseamnă că vânzătorii au fost respinși; un corp minuscul între umbre uriașe înseamnă un război fără învingător.",
        why: "Lumânarea duce tot ce duceau tabelul, linia și Point & Figure, plus psihologia zilei. Occidentul a aflat această metodă abia în 1991 (Steve Nison) — și într-un deceniu, lumânările au înlăturat tot restul.",
        notice: "Ziua ◆ — uită-te ce dramă a fost în interior, în timp ce linia arăta doar „un punct puțin mai jos”." },
      { tab: "Azi · Terminal",
        what: "Aceleași lumânări, dar vii: niveluri pe care piața s-a sprijinit luni de zile, evenimente din calendar, tipare cu istoric — în straturi peste preț.",
        how: "Nu mai e o înregistrare a trecutului — e un loc de muncă. Tot ce învață cursul apare aici.",
        why: "",
        notice: "Ziua ◆ pe graficul live — cu nivelul pe care l-a spart și evenimentul care a declanșat-o. Istoria desenării graficelor se termină aici. A ta începe." },
    ],
    en: [
      { tab: "1900 · Newspaper table",
        what: "This is how the market looked a hundred years ago — the morning paper, columns of numbers: yesterday's high, low, close. No picture — just digits.",
        how: "A row = a day; compare neighboring rows' closes to see whether the day rose or fell.",
        why: "There was no other way — the printing press could only do text.",
        notice: "Try to spot a trend reversal in the column. Can't? That's exactly why everything else was invented." },
      { tab: "1930 · Hand-drawn line",
        what: "The same closes, but plotted by hand on graph paper by a chartist — each point connected by a line.",
        how: "The left axis is price, the bottom axis is days; the line's slope is the trend.",
        why: "The human eye instantly sees shape where numbers go blind. 1930s chartists kept hundreds of these sheets in pencil — one sheet per stock.",
        notice: "The reversal you couldn't find in the table is visible here in a second. But the chart stays silent about what happened INSIDE each day." },
      { tab: "P&F · X's and O's",
        what: "The most radical chart in history — it threw out time itself.",
        how: "X = price rose one box (say, $5), O = it fell one box; while the rise continues, X's stack in the same column upward; a 3-box reversal starts a new column (O's downward). A day, a week, a month — doesn't matter: if the price sits still, the chart doesn't move at all.",
        why: "Late-19th-century telegraph operators and \"tape readers\" only marked significant moves — the paper was small, the moves were many.",
        notice: "A long column means a strong trend with no pause; frequent column switches mean the market's thrashing. Your \"reversal day\" here is the moment the long O column ended and the X's began (the ◆ marker will highlight it)." },
      { tab: "1991 · Candlesticks",
        what: "Japanese rice traders learned to record a day's four prices in a single mark: open, high, low, close. The candle's body runs from open to close (green if it closed higher, red if lower), the wicks reach to the high and low.",
        how: "One candle equals one whole day, including the fight inside it: a long lower wick means sellers got pushed back; a tiny body inside huge wicks means a war with no winner.",
        why: "The candle carries everything the table, the line, and Point & Figure carried, plus the day's psychology. The West only learned this method in 1991 (Steve Nison) — and within a decade, candles pushed everything else aside.",
        notice: "The ◆ day — look at how dramatic it was inside, while the line was just showing \"a point a bit lower.\"" },
      { tab: "Today · SBF terminal",
        what: "The same candles, but alive: levels the market has leaned on for months, calendar events, patterns with a track record — layered over the price.",
        how: "This isn't a record of the past anymore — it's a workstation. Everything the course teaches shows up here.",
        why: "",
        notice: "The ◆ day on the live chart — with the level it broke and the event that triggered it. The history of drawing charts ends here. Yours begins." },
    ]
  };

  window.ChronoEraFinalNote = {
    ru: "Каждая эпоха изобретала способ видеть больше, быстрее и раньше остальных: таблица → форма → сила движения → психология дня → контекст целиком. Свеча победила не красотой, а плотностью информации. А терминал — это свеча, которой вернули контекст.",
    ro: "Fiecare epocă a inventat un mod de a vedea mai mult, mai rapid și înaintea celorlalți: tabel → formă → forța mișcării → psihologia zilei → contextul întreg. Lumânarea a câștigat nu prin frumusețe, ci prin densitatea informației. Iar terminalul e o lumânare căreia i s-a redat contextul.",
    en: "Every era invented a way to see more, faster, ahead of everyone else: table → shape → force of the move → the day's psychology → full context. The candle won not through beauty but through information density. And the terminal is a candle with its context given back."
  };
})();

/* Плейсхолдер-иллюстрации станций (архивная гравюра, схема) — SPEC §8.3 обработка (дуотон/паспарту/печать)
   применяется CSS-классом .h-artwork/.h-art в history.css, здесь только сама разметка SVG.
   window.ChronoStationArt = {illustrationKey: () => svgString}, window.ChronoArchiveStamp = svgString.
   Заменить на реальные сканы Wikimedia Commons/LOC — см. манифест §8.2 (станции 1-6 только;
   1971-2021 остаются иллюстрацией по причине авторских прав на современные пресс-фото). */
(function(){
  function hatchBg(h){ h = h || 400; return '<rect width="720" height="'+h+'" fill="url(#hatch)"/>'; }
  function person(cx, cy, s){ s = s || 1; return '<ellipse cx="'+cx+'" cy="'+(cy+26*s)+'" rx="'+(12*s)+'" ry="'+(26*s)+'"/><circle cx="'+cx+'" cy="'+cy+'" r="'+(9*s)+'"/>'; }

  var STATION_ART = {
    "1602_beurs": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Двор Амстердамской биржи">'
      + hatchBg() + '<rect y="258" width="720" height="142" fill="url(#hatch2)"/>'
      + '<g stroke="#6d6350" stroke-width="3" fill="#efe8d8">'
      + '<rect x="40" y="120" width="640" height="150"/>'
      + '<path d="M70 270 v-100 a30 34 0 0 1 60 0 v100 Z M150 270 v-100 a30 34 0 0 1 60 0 v100 Z M230 270 v-100 a30 34 0 0 1 60 0 v100 Z M310 270 v-100 a30 34 0 0 1 60 0 v100 Z M390 270 v-100 a30 34 0 0 1 60 0 v100 Z M470 270 v-100 a30 34 0 0 1 60 0 v100 Z M550 270 v-100 a30 34 0 0 1 60 0 v100 Z"/>'
      + '<rect x="40" y="96" width="640" height="26"/></g>'
      + '<g stroke="#6d6350" stroke-width="3" fill="#efe8d8"><rect x="330" y="34" width="60" height="64"/><path d="M325 34 L360 6 L395 34 Z"/></g>'
      + '<g fill="#5c5342">' + person(150,296) + person(196,304) + person(420,296) + person(462,302) + person(560,299) + '</g>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">скан 1653 г., Wikimedia Commons</text></svg>';
    },
    "1720_tafereel": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Крах 1720 года">'
      + hatchBg() + '<rect y="300" width="720" height="100" fill="url(#hatch2)"/>'
      + '<g stroke="#6d6350" stroke-width="3" fill="none"><path d="M60 90 L60 140 M60 90 L30 130 M60 90 L90 130"/><path d="M140 70 L140 130 M140 70 L108 118 M140 70 L172 118"/><path d="M220 100 L220 145 M220 100 L192 138 M220 100 L248 138"/></g>'
      + '<polyline points="60,150 150,130 240,150 320,120 400,110 470,180 520,230 580,290 630,320" fill="none" stroke="#8a2f2f" stroke-width="4"/>'
      + '<g fill="#5c5342">' + person(560,300,0.9) + person(610,306,0.85) + person(500,304,0.9) + '</g>'
      + '<circle cx="330" cy="250" r="34" fill="none" stroke="#6d6350" stroke-width="3"/>'
      + '<path d="M316 262 q14 12 28 0" fill="none" stroke="#6d6350" stroke-width="3"/>'
      + '<circle cx="320" cy="242" r="3" fill="#6d6350"/><circle cx="342" cy="242" r="3" fill="#6d6350"/>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">«Het Groote Tafereel der Dwaasheid», 1720</text></svg>';
    },
    "1730_dojima": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Рисовая биржа Додзима">'
      + hatchBg() + '<rect y="290" width="720" height="110" fill="url(#hatch2)"/>'
      + '<g stroke="#6d6350" stroke-width="3" fill="none"><path d="M120 60 L120 200 M280 60 L280 200 M110 90 L290 90 M105 110 L295 110"/></g>'
      + '<g fill="#c9a876" stroke="#6d6350" stroke-width="2"><rect x="420" y="220" width="70" height="34"/><rect x="420" y="182" width="70" height="34"/><rect x="500" y="220" width="70" height="34"/><rect x="500" y="182" width="70" height="34"/><rect x="460" y="150" width="70" height="34"/></g>'
      + '<g stroke="#5c5342" stroke-width="4">'
      + '<line x1="580" y1="330" x2="580" y2="300"/><line x1="600" y1="330" x2="600" y2="270"/><line x1="620" y1="330" x2="620" y2="310"/><line x1="640" y1="330" x2="640" y2="255"/><line x1="660" y1="330" x2="660" y2="290"/>'
      + '</g>'
      + '<g fill="#5c5342">' + person(180,300) + person(226,306) + '</g>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">рынок риса Додзима, Осака</text></svg>';
    },
    "1792_buttonwood": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Платановое соглашение">'
      + hatchBg() + '<rect y="300" width="720" height="100" fill="url(#hatch2)"/>'
      + '<g stroke="#6d6350" stroke-width="3" fill="#efe8d8"><rect x="60" y="150" width="90" height="150"/><rect x="170" y="130" width="90" height="170"/><rect x="560" y="140" width="90" height="160"/><rect x="470" y="160" width="80" height="140"/></g>'
      + '<rect x="345" y="230" width="26" height="80" fill="#6d6350"/>'
      + '<circle cx="358" cy="150" r="95" fill="#cdd8b8" stroke="#6d6350" stroke-width="3"/>'
      + '<g fill="#5c5342">' + person(300,290,0.9) + person(340,296,0.9) + person(380,296,0.9) + person(420,290,0.9) + '</g>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">Buttonwood Agreement, Уолл-стрит 1792</text></svg>';
    },
    "1867_ticker": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Биржевой тикер">'
      + hatchBg() + '<rect y="300" width="720" height="100" fill="url(#hatch2)"/>'
      + '<line x1="180" y1="60" x2="180" y2="300" stroke="#6d6350" stroke-width="6"/><line x1="120" y1="100" x2="240" y2="100" stroke="#6d6350" stroke-width="4"/>'
      + '<circle cx="130" cy="100" r="4" fill="#6d6350"/><circle cx="160" cy="100" r="4" fill="#6d6350"/><circle cx="200" cy="100" r="4" fill="#6d6350"/><circle cx="230" cy="100" r="4" fill="#6d6350"/>'
      + '<path d="M180 100 Q 340 40 480 120 Q 600 180 660 90" stroke="#6d6350" stroke-width="2" fill="none"/>'
      + '<circle cx="470" cy="230" r="46" fill="#efe8d8" stroke="#6d6350" stroke-width="3"/>'
      + '<path d="M470 230 q60 10 90 60 q20 34 -6 60 q-30 24 -70 4 q-30 -16 -20 -50" fill="none" stroke="#8a2f2f" stroke-width="3"/>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">тикерная лента, 1867</text></svg>';
    },
    "1929_crowd": function(){
      var ppl = '';
      var xs = [80,120,160,200,240,290,340,390,440,490,540,590,630];
      for (var i=0;i<xs.length;i++){ ppl += person(xs[i], 300 + (i%3)*4, 0.85 + (i%2)*0.1); }
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Толпа у биржи, октябрь 1929">'
      + hatchBg() + '<rect y="330" width="720" height="70" fill="url(#hatch2)"/>'
      + '<g stroke="#6d6350" stroke-width="3" fill="#efe8d8"><rect x="30" y="60" width="660" height="180"/>'
      + '<path d="M70 240 V90 M150 240 V90 M230 240 V90 M310 240 V90 M390 240 V90 M470 240 V90 M550 240 V90 M630 240 V90"/></g>'
      + '<g fill="#5c5342">' + ppl + '</g>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">толпа у NYSE, Library of Congress</text></svg>';
    },
    "1971_nasdaq": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="NASDAQ, биржа без зала">'
      + hatchBg() + '<rect y="320" width="720" height="80" fill="url(#hatch2)"/>'
      + '<g stroke="#6d6350" stroke-width="1.4" fill="none">'
      + '<line x1="140" y1="120" x2="300" y2="90"/><line x1="140" y1="120" x2="260" y2="220"/><line x1="300" y1="90" x2="460" y2="140"/>'
      + '<line x1="260" y1="220" x2="460" y2="140"/><line x1="460" y1="140" x2="600" y2="100"/><line x1="460" y1="140" x2="580" y2="230"/>'
      + '<line x1="300" y1="90" x2="580" y2="230"/><line x1="140" y1="120" x2="600" y2="100"/></g>'
      + '<g fill="#efe8d8" stroke="#6d6350" stroke-width="3">'
      + '<circle cx="140" cy="120" r="14"/><circle cx="300" cy="90" r="14"/><circle cx="460" cy="140" r="14"/><circle cx="260" cy="220" r="14"/><circle cx="600" cy="100" r="14"/><circle cx="580" cy="230" r="14"/></g>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">NASDAQ, сеть дилеров без торгового зала</text></svg>';
    },
    "1987_blackmonday": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Чёрный понедельник 1987">'
      + hatchBg() + '<rect y="300" width="720" height="100" fill="url(#hatch2)"/>'
      + '<polyline points="60,110 160,120 260,100 340,130 400,140 440,170 470,230 500,290 540,320" fill="none" stroke="#8a2f2f" stroke-width="4.5"/>'
      + '<g fill="#5c5342">' + person(120,270,0.85) + person(170,278,0.9) + person(220,272,0.8) + person(600,270,0.85) + person(650,276,0.9) + '</g>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">−22.6% за день, 19 октября 1987</text></svg>';
    },
    "2000_dotcom": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Пузырь доткомов">'
      + hatchBg() + '<rect y="300" width="720" height="100" fill="url(#hatch2)"/>'
      + '<polyline points="60,270 140,240 220,190 300,120 360,90 420,160 470,220 520,260 580,285 640,300" fill="none" stroke="#6d6350" stroke-width="4"/>'
      + '<g fill="none" stroke="#8a2f2f" stroke-width="2.4"><circle cx="360" cy="90" r="26"/><line x1="340" y1="70" x2="380" y2="110"/><line x1="380" y1="70" x2="340" y2="110"/></g>'
      + '<g fill="none" stroke="#6d6350" stroke-width="1.6"><circle cx="180" cy="150" r="16"/><circle cx="500" cy="120" r="12"/><circle cx="560" cy="200" r="10"/></g>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">NASDAQ, пик 5132 → дно 1114</text></svg>';
    },
    "2008_lehman": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Lehman Brothers 2008">'
      + hatchBg() + '<rect y="300" width="720" height="100" fill="url(#hatch2)"/>'
      + '<g stroke="#6d6350" stroke-width="3" fill="#efe8d8"><rect x="260" y="90" width="200" height="210"/>'
      + '<path d="M260 130 h200 M260 170 h200 M260 210 h200 M260 250 h200 M300 90 v210 M360 90 v210 M420 90 v210"/></g>'
      + '<path d="M270 95 L 400 200 L 340 300" fill="none" stroke="#8a2f2f" stroke-width="4"/>'
      + '<polyline points="500,320 540,290 570,310 600,260 630,300 660,240" fill="none" stroke="#8a2f2f" stroke-width="3"/>'
      + '<g fill="#5c5342">' + person(150,280,0.9) + person(195,286,0.85) + '</g>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">крупнейшее банкротство в истории США</text></svg>';
    },
    "2010_flashcrash": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Flash Crash 2010">'
      + hatchBg() + '<rect y="300" width="720" height="100" fill="url(#hatch2)"/>'
      + '<circle cx="180" cy="180" r="90" fill="none" stroke="#6d6350" stroke-width="3"/>'
      + '<line x1="180" y1="180" x2="180" y2="115" stroke="#6d6350" stroke-width="3"/>'
      + '<line x1="180" y1="180" x2="228" y2="195" stroke="#6d6350" stroke-width="4"/>'
      + '<circle cx="180" cy="180" r="4" fill="#6d6350"/>'
      + '<polyline points="330,150 380,155 420,160 450,290 490,300 530,170 570,160 640,158" fill="none" stroke="#8a2f2f" stroke-width="4"/>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">−998 пунктов и обратно за 36 минут</text></svg>';
    },
    "2021_gamestop": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="GameStop 2021">'
      + hatchBg() + '<rect y="300" width="720" height="100" fill="url(#hatch2)"/>'
      + '<polyline points="60,290 140,285 220,270 300,260 360,150 420,80 460,40" fill="none" stroke="#2E7D5B" stroke-width="4.5"/>'
      + '<g fill="#efe8d8" stroke="#6d6350" stroke-width="2.4">'
      + '<rect x="520" y="150" width="46" height="80" rx="6"/><rect x="580" y="190" width="46" height="80" rx="6"/><rect x="460" y="210" width="46" height="80" rx="6"/></g>'
      + '<g fill="none" stroke="#6d6350" stroke-width="1.6"><path d="M500 140 q14 -18 30 -6"/><path d="M630 180 q14 -18 30 -6"/></g>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">$20 → $483, толпа против фонда</text></svg>';
    },
    "2020_covid": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="COVID-крах 2020">'
      + hatchBg() + '<rect y="300" width="720" height="100" fill="url(#hatch2)"/>'
      + '<polyline points="60,120 140,110 220,130 280,150 320,280 360,300 400,270 460,180 520,140 580,120 640,110" fill="none" stroke="#8a2f2f" stroke-width="4.5"/>'
      + '<circle cx="340" cy="290" r="90" fill="none" stroke="#6d6350" stroke-width="2" stroke-dasharray="4 5"/>'
      + '<line x1="340" y1="290" x2="340" y2="230" stroke="#6d6350" stroke-width="2.5"/>'
      + '<line x1="340" y1="290" x2="380" y2="300" stroke="#6d6350" stroke-width="2.5"/>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">−34% индекса S&amp;P 500 за 33 дня</text></svg>';
    },
    "2022_ukraine": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Рынок и война в Украине 2022">'
      + hatchBg() + '<rect y="300" width="720" height="100" fill="url(#hatch2)"/>'
      + '<g fill="#efe8d8" stroke="#6d6350" stroke-width="3"><rect x="90" y="200" width="40" height="100"/><path d="M90 200 q20 -30 40 0"/></g>'
      + '<g fill="none" stroke="#6d6350" stroke-width="2"><line x1="180" y1="120" x2="180" y2="300"/><line x1="220" y1="150" x2="220" y2="300"/><line x1="260" y1="100" x2="260" y2="300"/></g>'
      + '<polyline points="360,260 420,230 460,150 500,90 540,110 600,80 650,60" fill="none" stroke="#8a2f2f" stroke-width="4.5"/>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">нефть Brent выше $100, MOEX −45% за сессию</text></svg>';
    },
    "today_terminal": function(){
      return '<svg class="h-art" viewBox="0 0 720 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Экраны и алгоритмы сегодня">'
      + hatchBg() + '<rect y="320" width="720" height="80" fill="url(#hatch2)"/>'
      + '<g stroke="#6d6350" stroke-width="3" fill="#efe8d8"><rect x="60" y="70" width="180" height="120"/><rect x="270" y="70" width="180" height="120"/><rect x="480" y="70" width="180" height="120"/></g>'
      + '<polyline points="80,170 120,140 150,155 180,110 210,130 235,95" fill="none" stroke="#2E7D5B" stroke-width="3"/>'
      + '<polyline points="290,150 320,165 350,120 380,140 410,100 440,125" fill="none" stroke="#8a2f2f" stroke-width="3"/>'
      + '<polyline points="500,160 530,130 560,150 590,105 620,135 645,90" fill="none" stroke="#6d6350" stroke-width="3"/>'
      + '<g fill="#5c5342">' + person(150,240) + person(360,246) + person(570,240) + '</g>'
      + '<text x="360" y="386" text-anchor="middle" font-family="monospace" font-size="12" fill="#8A8275">торговый зал 1980-х</text></svg>';
    }
  };

  var STAMP = '<svg class="h-stamp" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    + '<circle cx="50" cy="50" r="46" fill="none" stroke="#2B2B33" stroke-width="2.4"/>'
    + '<circle cx="50" cy="50" r="34" fill="none" stroke="#2B2B33" stroke-width="1.2"/>'
    + '<path id="stArc" d="M50,50 m-40,0 a40,40 0 1,1 80,0 a40,40 0 1,1 -80,0" fill="none"/>'
    + '<text font-family="monospace" font-size="10.5" letter-spacing="2" fill="#2B2B33"><textPath href="#stArc">SBF · ARCHIVA · 1602→ · SBF · ARCHIVA ·</textPath></text>'
    + '<text x="50" y="46" text-anchor="middle" font-family="Georgia,serif" font-size="15" fill="#2B2B33">SBF</text>'
    + '<text x="50" y="62" text-anchor="middle" font-family="monospace" font-size="8" letter-spacing="1" fill="#2B2B33">1602→</text></svg>';

  // Реальные сканы Wikimedia Commons/LOC для станций 1-6 (SPEC §8.2 манифест, скачаны и сжаты 23.07.2026,
  // лицензии — web/edu/assets/history/manifest.json). Станции 1971-2021 сознательно остаются SVG-иллюстрацией:
  // фото этих событий обычно под авторским правом (не PD), в отличие от гравюр/картин 1602-1929.
  var STATION_IMAGE = {
    "1602_beurs":     { webp:"/edu/assets/history/1602_beurs.webp",     jpg:"/edu/assets/history/1602_beurs_web.jpg",     w:900, h:925,
      alt:"Эмануэль де Витте, «Двор Амстердамской биржи», 1653" },
    "1720_tafereel":  { webp:"/edu/assets/history/1720_tafereel.webp",  jpg:"/edu/assets/history/1720_tafereel_web.jpg",  w:900, h:780,
      alt:"«Het Groote Tafereel der Dwaasheid», гравюра 1720 года" },
    "1730_dojima":    { webp:"/edu/assets/history/1730_dojima.webp",    jpg:"/edu/assets/history/1730_dojima_web.jpg",    w:900, h:390,
      alt:"Рисовая биржа Додзима, Осака, ок. 1880" },
    "1792_buttonwood":{ webp:"/edu/assets/history/1792_buttonwood.webp",jpg:"/edu/assets/history/1792_buttonwood_web.jpg",w:900, h:693,
      alt:"Tontine Coffee House, Уолл-стрит, ок. 1797" },
    "1867_ticker":    { webp:"/edu/assets/history/1867_ticker.webp",    jpg:"/edu/assets/history/1867_ticker_web.jpg",    w:900, h:1113,
      alt:"Биржевой тикер Эдисона, Smithsonian NMAH" },
    "1929_crowd":     { webp:"/edu/assets/history/1929_crowd.webp",     jpg:"/edu/assets/history/1929_crowd_web.jpg",     w:900, h:667,
      alt:"Толпа у NYSE, «Чёрный четверг», 24 октября 1929" },
    // Станции 1971-2021 + новые 2020/2022 — реальные CC-лицензированные фото, добавлены 23.07.2026
    // фоновым агентом (лицензии/источники — history/manifest.json). 1987_blackmonday сознательно
    // остаётся SVG: перепроверено — свободно лицензированных фото торгового зала 1987 года не нашлось,
    // все известные снимки того дня под авторским правом (AP/Getty).
    "1971_nasdaq":    { webp:"/edu/assets/history/1971_nasdaq.webp",    jpg:"/edu/assets/history/1971_nasdaq_web.jpg",    w:900, h:900,
      alt:"Башня NASDAQ MarketSite, Таймс-сквер" },
    "2000_dotcom":    { webp:"/edu/assets/history/2000_dotcom.webp",    jpg:"/edu/assets/history/2000_dotcom_web.jpg",    w:900, h:600,
      alt:"Штаб-квартира Webvan, символ краха доткомов" },
    "2008_lehman":    { webp:"/edu/assets/history/2008_lehman.webp",    jpg:"/edu/assets/history/2008_lehman_web.jpg",    w:900, h:675,
      alt:"Штаб-квартира Lehman Brothers, 745 Seventh Avenue" },
    "2010_flashcrash":{ webp:"/edu/assets/history/2010_flashcrash.webp",jpg:"/edu/assets/history/2010_flashcrash_web.jpg",w:900, h:598,
      alt:"Серверная — символ алгоритмической торговли" },
    "2020_covid":     { webp:"/edu/assets/history/2020_covid.webp",     jpg:"/edu/assets/history/2020_covid_web.jpg",     w:900, h:600,
      alt:"Опустевший Уолл-стрит во время локдауна, апрель 2020" },
    "2021_gamestop":  { webp:"/edu/assets/history/2021_gamestop.webp",  jpg:"/edu/assets/history/2021_gamestop_web.jpg",  w:900, h:600,
      alt:"Магазин GameStop" },
    "2022_ukraine":   { webp:"/edu/assets/history/2022_ukraine.webp",   jpg:"/edu/assets/history/2022_ukraine_web.jpg",   w:600, h:900,
      alt:"Здание Московской биржи (MOEX)" },
    "today_terminal": { webp:"/edu/assets/history/today_terminal.webp", jpg:"/edu/assets/history/today_terminal_web.jpg", w:900, h:675,
      alt:"Терминал Bloomberg, рабочее место аналитика" }
  };

  function stationArtHTML(key){
    var img = STATION_IMAGE[key];
    if (img){
      return '<picture>'
        + '<source type="image/webp" srcset="'+img.webp+'">'
        + '<img src="'+img.jpg+'" alt="'+img.alt+'" loading="lazy" width="'+img.w+'" height="'+img.h+'">'
        + '</picture>';
    }
    return STATION_ART[key] ? STATION_ART[key]() : '';
  }

  window.ChronoStationArt = STATION_ART;
  window.ChronoStationArtHTML = stationArtHTML;
  window.ChronoArchiveStamp = STAMP;
})();
