/*
 * academy-shared.js — общий "хром" книги SBF Academy (SPEC_academy_chapter3_
 * integration.md §5/§7). Раньше C/Mono/Chip/Rule/MSG_TR/AskAnalystPopup/
 * AskAnalystBtn/getChUrl/GlossWord/тест-на-воспроизведение существовали в
 * ТРЁХ независимых копиях (edu_book_1/2/3.html) — уже разошедшихся на
 * практике (в Главе 3 своя, более простая версия попапа аналитика).
 *
 * ВАЖНО: подключается обычным <script src="/assets/academy-shared.js">,
 * БЕЗ type="text/babel" — компиляция глав (_precompile_all() в serve.py)
 * обрабатывает только инлайновый <script type="text/babel"> каждой главы;
 * babel.min.js вообще вырезается из уже скомпилированных страниц. Поэтому
 * здесь пишем ТОЛЬКО React.createElement(...), никакого JSX.
 *
 * Инъекция — в <head>, ДО тегов react/react-dom/babel в <body> (см.
 * _build_edu_page() в serve.py). Значит верхний уровень этого файла НЕ
 * должен обращаться к window.React в момент выполнения — только внутри
 * тел функций, которые реально вызываются намного позже (когда React уже
 * точно загружен). INITIAL_LANG — const внутри инлайн-скрипта каждой
 * главы, из отдельного <script> тега не виден — поэтому getChUrl/
 * AskAnalystBtn принимают lang явным аргументом/пропом, а не читают
 * глобальную переменную.
 */
(function () {
  /* 🔴 КОНТРАСТ (16.09.2026). Эта палитра красит все 15 глав, и четыре её
     значения не проходили WCAG AA как цвет текста. Замер
     tools/audit_contrast.py нашёл в главах 1 и 2 больше нарушений, чем на
     всём остальном сайте вместе.

     Пороги считаны по САМОМУ ТЁМНОМУ фону, на котором цвет реально лежит
     (#f0ebe0 = surfaceMid), а не по белому: на белом почти всё проходило,
     и именно поэтому проблему не видели.

     Ярусы серого — это альфа, а не отдельные hex, поэтому правка одного
     числа чинит сразу 148 мест (inkFaint) и 75 (inkSoft). Лесенка после
     правки на #f0ebe0: ink 14.9 → inkMid 6.3 → inkSoft 5.7 → inkFaint 4.5.
     Разница между ярусами стала меньше, чем была, и иначе быть не может:
     AA требует 4.5:1 для текста мельче 24px, так что «совсем бледный»
     ярус читаемым не бывает — различать ярусы приходится размером и
     насыщенностью, а не светлотой.

     ⚠ inkFaint в 4 местах из 152 стоит не текстом (2 фона, рамка, заливка).
     Там он станет заметно темнее — это осознанная плата за 148 исправленных
     подписей; если какая-то из четырёх рамок начнёт бить в глаза, ей нужен
     свой токен, а не откат альфы.

     gold НЕ трогаем: он в 166 местах фон и рамка (графика, порог 3:1), и
     затемнение перекрасило бы бренд. Для текста заведён goldText. */
  var C = {
    gold:"#c9973a", goldDark:"#b8832a", goldLight:"#f4d49f", goldPale:"#f7f0e3",
    /* 🔴 goldText — НЕ константа, а переменная, которую решает фон.
       На светлом это #876525 (запасное значение прямо здесь), а на тёмных
       панелях его переопределяет функция `подсветитьТёмныеБлоки` ниже.
       Так пришлось сделать, потому что в главах 3 и 4 «золото на тёмном»
       встречается в 53 местах, и править их по одному я уже пробовал —
       ровно так, механической заменой по грепу, я 16.09 уронил главу 5
       (`aria-label={p...}` в компоненте без переменной `p`). Одна точка
       вместо 53 правок, и критерий тот же, что в правиле про цвет: он
       определяется ОТНОСИТЕЛЬНО фона, а не назначается заранее.
       var() работает и в инлайновом style, и у иконок: sbf-icons.js кладёт
       color в CSS-свойство, а сам SVG рисует currentColor. */
    goldText:"var(--ch-gold, #876525)",
    /* 🔴 ТЁМНЫЕ БЛОКИ — ОТДЕЛЬНЫЙ ЯРУС, И ЭТО НЕ ПЕДАНТИЗМ.
       Затемнив золото под кремовый фон, я тем же движением сделал его
       нечитаемым на тёмных панелях главы 2 (шапка, симулятор ФРС):
       #876525 на #18181a — 3.31:1, а на #212123 и вовсе 2.99:1. Замер
       поймал 20 таких элементов, которых до правки не было.
       Урок общий: цвет текста не бывает «правильным» сам по себе, он
       правильный ОТНОСИТЕЛЬНО фона. Раз фонов у нас два семейства —
       светлое и тёмное, — токенов тоже должно быть два. */
    goldOnDark:"#E6C257",   /* 10.2:1 на #18181a */
    greenOnDark:"#4FBF8B",  /* 7.5:1  — C.green на тёмном даёт 2.90:1 */
    redOnDark:"#F38277",    /* 6.1:1 на #18181a и 4.5 на тёмно-красной плашке #60272d */
    black:"#18181a", ink:"#18181a", inkMid:"#555555",
    /* 🔴 Ярусы серого — тоже относительно фона. На тёмных панелях главы 3
       «3 · ДАЙ СДЕЛАТЬ» рисовалось цветом rgba(24,24,26,0.61) по фону
       rgb(24,24,26): контраст 1.00:1, текст не видно вообще. Тёмная тушь
       на тёмном — не «бледно», а невидимо.
       На тёмном подсветитьТёмныеБлоки переводит их в белые с той же
       альфой (--ch-ink-soft / --ch-ink-faint).
       ⚠ Одно место пришлось вывести из-под переменной руками:
       edu_book_6 рисовал подпись оси через SVG-атрибут fill={C.inkFaint},
       а var() в презентационных атрибутах SVG не разворачивается — там
       оставлен литерал. */
    inkSoft:"var(--ch-ink-soft, rgba(24,24,26,0.68))",
    inkFaint:"var(--ch-ink-faint, rgba(24,24,26,0.61))",
    /* Те же два яруса в готовом «тёмном» виде — для мест, где ветка
       по фону написана руками (props.dark) и переменная не подходит.
       Числа держатся ЗДЕСЬ, а не внутри подсветитьТёмныеБлоки: пока они
       были вписаны в механизм литералами, ручная ветка жила своей жизнью
       и ставила rgba(255,255,255,0.4) — 3.82:1 на #18181a, ниже AA.
       Замер поймал это пять раз, в главах 6-10, на подписи «часть 1 из 4». */
    inkSoftOnDark:"rgba(255,255,255,0.72)",   /* 10.4:1 на #18181a */
    inkFaintOnDark:"rgba(255,255,255,0.62)",  /*  7.7:1 на #18181a */
    white:"#ffffff", surface:"#faf8f5", surfaceMid:"#f0ebe0",
    border:"rgba(24,24,26,0.1)", borderGold:"rgba(201,151,58,0.25)",
    dark:"#18181a",
    green:"#2C784E", greenPale:"#eaf5ee", red:"#c0392b", redPale:"#fdecea",
    blue:"#1F5FEA", bluePale:"#eff6ff", orange:"#A05804",
    // Яркие "биржевые" (TradingView-подобные) цвета для графиков/лент сделок
    // -- Глава 4 -- намеренно отдельные от green/red выше: те используются
    // как приглушённый индикатор "хорошо/плохо" в обычном UI, эти -- для
    // визуализации цены/свечей, семантически разные вещи с похожими именами.
    chartGreen:"#089981", chartRed:"#f23645", chartBg:"#131722",
    /* 🔴 Те же биржевые цвета, но ДЛЯ ТЕКСТА, и тоже переменные.
       chartGreen/chartRed уходят в конфиг lightweight-charts (upColor,
       wickUpColor и т.д.) — туда var() подставить нельзя, библиотека рисует
       в canvas и CSS-переменную не развернёт. Поэтому свечи красятся
       по-прежнему, а цены в стакане и ленте сделок — этими.
       На светлом: #067865 и #D50E1E. На тёмных панелях их переопределяет
       подсветитьТёмныеБлоки (#4FBF8B / #F38277) — стакан главы 4 как раз
       стоит на #212123, где исходные давали 4.49 и 4.11. */
    chartGreenText:"var(--ch-up, #067865)",
    chartRedText:"var(--ch-down, #D50E1E)",
  };

  /* ── Золото на тёмных панелях ─────────────────────────────────────────────
   *
   * Главы — светлые страницы с тёмными вставками: шапка, симулятор ФРС,
   * стакан, выводы. Цвет текста в них задаётся инлайном из палитры выше,
   * то есть про фон под собой не знает ничего. Затемнённое золото #876525,
   * правильное на кремовом, на #18181a даёт 3.31:1, на #212123 — 2.99:1.
   *
   * Здесь фон СПРАШИВАЕТСЯ у браузера, а не угадывается по коду: берём
   * вычисленный background-color и его яркость. Нашли тёмный — ставим на
   * элемент --ch-gold со светлым золотом, и все потомки наследуют его
   * автоматически, потому что CSS-переменные наследуются.
   *
   * Обходим не всё подряд, а только элементы с инлайновым background:
   * тёмные панели в главах задаются именно так, а полный обход по
   * getComputedStyle на каждую перерисовку React был бы дорогим.
   */
  var СВЕТЛОЕ_ЗОЛОТО = C.goldOnDark;          // #E6C257, 10.2:1 на #18181a
  var ПОРОГ_ТЕМНОТЫ = 0.18;                   // яркость по WCAG; #322d25 ≈ 0.03

  function _яркостьRGB(r, g, b) {
    var к = [r, g, b].map(function (v) {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * к[0] + 0.7152 * к[1] + 0.0722 * к[2];
  }

  function подсветитьТёмныеБлоки(корень) {
    var узлы;
    try {
      узлы = (корень || document).querySelectorAll('[style*="background"]');
    } catch (e) { return 0; }
    var поставлено = 0;
    for (var i = 0; i < узлы.length; i++) {
      var э = узлы[i];
      var м = /rgba?\(([^)]+)\)/.exec(getComputedStyle(э).backgroundColor);
      if (!м) continue;
      var ч = м[1].split(',').map(parseFloat);
      // Полупрозрачную подложку пропускаем: под ней может быть что угодно,
      // и «тёмная» она только на вид. Решать по ней — гадание.
      if (ч.length > 3 && ч[3] < 0.9) continue;
      if (_яркостьRGB(ч[0], ч[1], ч[2]) > ПОРОГ_ТЕМНОТЫ) continue;
      if (э.style.getPropertyValue('--ch-gold')) continue;   // уже стоит
      э.style.setProperty('--ch-gold', СВЕТЛОЕ_ЗОЛОТО);
      э.style.setProperty('--ch-up', C.greenOnDark);
      э.style.setProperty('--ch-down', C.redOnDark);
      э.style.setProperty('--ch-ink-soft', C.inkSoftOnDark);
      э.style.setProperty('--ch-ink-faint', C.inkFaintOnDark);
      поставлено++;
    }
    return поставлено;
  }

  /* 🔴 ПЕРЕХОДЫ МЕЖДУ ГЛАВАМИ — ЦЕЛИ КАСАНИЯ, А НЕ СТРОЧКИ ТЕКСТА.
     Внизу каждой главы стоят «← Глава N» (210×20) и стрелка «←» (10×19).
     Вторая — вдвое ниже минимума WCAG 2.5.8 по обеим сторонам и вчетверо
     уже; на телефоне попасть по ней можно только случайно. Разметка у
     каждой из 15 глав своя, то есть правка руками — это 30 одинаковых
     правок в 15 файлах, которые снова разойдутся.

     Помечаем классом здесь и задаём размер в edu.css, где ему и место.
     Условие «ссылка ведёт на главу или оглавление И не стоит внутри
     абзаца»: ссылки в тексте («см. главу 7») трогать нельзя — inline-flex
     и min-height разорвали бы строку. */
  function пометитьНавигационныеСсылки(корень) {
    var узлы = (корень || document).querySelectorAll(
      'a[href*="/edu/b/"], a[href$="/edu/"], a[href$="/ro/edu/"], a[href$="/en/edu/"]');
    for (var i = 0; i < узлы.length; i++) {
      var с = узлы[i];
      if (с.classList.contains('sbf-tap')) continue;
      if (с.closest('p, li, td, th')) continue;          // ссылка в тексте
      if (с.querySelector('img, svg')) continue;          // картинка сама держит размер
      с.classList.add('sbf-tap');
    }
  }

  // Главы перерисовываются (переключение «Просто/Как есть», приход данных),
  // поэтому один проход после загрузки не годится: новые тёмные панели
  // появятся уже после него. Наблюдатель с дебаунсом — и разовый проход
  // сразу, на случай если разметка уже на месте.
  if (typeof document !== "undefined") {
    var _таймер = null;
    var _перепройти = function () {
      clearTimeout(_таймер);
      _таймер = setTimeout(function () {
        подсветитьТёмныеБлоки(document);
        пометитьНавигационныеСсылки(document);
      }, 120);
    };
    var _старт = function () {
      подсветитьТёмныеБлоки(document);
      пометитьНавигационныеСсылки(document);
      try {
        new MutationObserver(_перепройти).observe(document.body,
          { childList: true, subtree: true });
      } catch (e) { /* без наблюдателя работает разовый проход */ }
    };
    if (document.readyState === "loading")
      document.addEventListener("DOMContentLoaded", _старт);
    else _старт();
  }

  // Сетка вариантов ответа QuizBlock -- SPEC_ch2_debug_and_chart_engine.md §1.5
  // ("сетка 2×2 кнопками... на мобильном 1 колонка"), применено ко всем главам,
  // не только к главе 2. Инлайновые React-стили не умеют в media query, а
  // .g2/.g3 определены не во всех edu_book_N.html (нет в 1-3) -- поэтому стиль
  // самодостаточный, инжектится этим файлом один раз, не зависит от хост-страницы.
  if (typeof document !== "undefined" && !document.getElementById("academy-quiz-optgrid-style")) {
    var _qgStyle = document.createElement("style");
    _qgStyle.id = "academy-quiz-optgrid-style";
    _qgStyle.textContent =
      ".quiz-optgrid{display:grid;grid-template-columns:1fr 1fr;gap:10px}" +
      "@media(max-width:640px){.quiz-optgrid{grid-template-columns:1fr}}";
    document.head.appendChild(_qgStyle);
  }

  function Mono(props) {
    var children = props.children, size = props.size == null ? 13 : props.size,
        color = props.color || C.inkSoft, spacing = props.spacing == null ? 3 : props.spacing,
        style = props.style || {}, className = props.className || "";
    return React.createElement('span', {className: className, style: Object.assign(
      {fontFamily:"'Courier New',monospace", fontSize:size, letterSpacing:spacing, color:color}, style
    )}, children);
  }

  function Chip(props) {
    // По умолчанию значок стоит на светлом: C.gold как текст — 2.63:1.
    // Для тёмных секций цвет передаётся явно (C.goldOnDark).
    var color = props.color || C.goldText;
    return React.createElement('span', {style:{
      fontFamily:"'Courier New',monospace", fontSize:11, letterSpacing:3, color:color,
      border:"1px solid " + color, padding:"4px 11px", display:"inline-block", textTransform:"uppercase"
    }}, props.children);
  }

  function Rule(props) {
    var w = props.w || "50%", my = props.my == null ? 32 : props.my;
    return React.createElement('div', {style:{
      height:1, background:"linear-gradient(90deg,transparent," + C.gold + ",transparent)",
      width:w, margin: my + "px auto", opacity:0.4
    }});
  }

  // ── Глоссарий-тултип. glossary передаётся пропом (словарь термина —
  // контент главы, не механизм) — GLOSSARY каждой главы остаётся локальным.
  function GlossWord(props) {
    var glossary = props.glossary, word = props.word, lang = props.lang, children = props.children;
    var open = React.useState(false), isOpen = open[0], setOpen = open[1];
    var d = glossary && glossary[lang] && glossary[lang][word];
    if (!d) {
      // Термина в словаре нет — значит и нажимать нечего: рисуем выделенным
      // словом, но без курсора-пальца. Палец на неработающем элементе — это
      // обещание, которого страница не выполняет.
      return React.createElement('span', {style:{color:C.goldText, fontWeight:600,
                                                 borderBottom:"1px dashed " + C.gold}}, children);
    }
    return React.createElement('span', {style:{position:"relative", display:"inline"}},
      // 🔴 Термин словаря — это управление, и объявлен он должен быть как
      // управление. До 10.09.2026 это был <span onClick>: мышью работает,
      // с клавиатуры недостижим, экранный диктор читает как обычное слово.
      // Замер по всем пятнадцати главам нашёл 150 таких элементов, и термины
      // словаря — самая многочисленная их часть.
      //
      // button, а не span с role: кнопка приходит с фокусом, обработкой
      // Enter/Space и правильной семантикой бесплатно. Стили сбрасываются
      // явно, чтобы слово внутри абзаца осталось словом, а не кнопкой.
      React.createElement('button', {
        type: "button",
        "aria-expanded": isOpen ? "true" : "false",
        onClick: function(e){ e.stopPropagation(); setOpen(function(o){ return !o; }); },
        style:{color:C.goldText, borderBottom:"1px dashed " + C.gold, cursor:"pointer",
               fontWeight:600, background:"none", border:"none", borderRadius:0,
               padding:0, margin:0, font:"inherit", lineHeight:"inherit",
               display:"inline", textAlign:"left"}
      }, children),
      isOpen && React.createElement(React.Fragment, {},
        React.createElement('div', {
          onClick: function(e){ e.stopPropagation(); setOpen(false); },
          style:{position:"fixed", inset:0, zIndex:199}
        }),
        React.createElement('span', {
          onClick: function(e){ e.stopPropagation(); },
          style:{position:"absolute", bottom:"130%", left:"50%", transform:"translateX(-50%)",
                 width:360, background:C.white, border:"1px solid " + C.border,
                 boxShadow:"0 10px 40px rgba(0,0,0,0.15)", padding:"20px 23px", zIndex:200, display:"block"}
        },
          React.createElement(Mono, {size:13, color:C.goldText, spacing:2, style:{display:"block", marginBottom:8}}, word.toUpperCase()),
          React.createElement('span', {style:{display:"block", fontSize:16, color:C.ink, marginBottom:10, lineHeight:1.6, fontWeight:600}}, d.s),
          React.createElement('span', {style:{display:"block", fontSize:15, color:C.inkSoft, marginBottom:10, lineHeight:1.5, fontStyle:"italic"}}, d.a),
          React.createElement('span', {style:{display:"block", fontSize:15, color:C.goldText, lineHeight:1.5}}, "→ " + d.e),
          React.createElement('span', {
            onClick: function(e){ e.stopPropagation(); setOpen(false); },
            style:{position:"absolute", top:10, right:12, cursor:"pointer", color:C.inkFaint, fontSize:20, lineHeight:1}
          }, "×")
        )
      )
    );
  }

  // Оборачивает КАЖДОЕ из pairs=[{term,word}] (term встречается в text не
  // больше 1 раза) ссылкой на глоссарий -- нужен, когда термин нужно
  // вставить в готовую строку из STRINGS (не JSX-фрагмент), напр. описание
  // центробанка или вводную строку перед интерактивом (см. Главы 2/3).
  function withGlossTerms(text, pairs, glossary, lang) {
    var esc = function(s){ return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); };
    var re = new RegExp('(' + pairs.map(function(p){ return esc(p.term); }).join('|') + ')');
    return text.split(re).map(function(part, i){
      var pair = pairs.filter(function(p){ return p.term === part; })[0];
      return pair ? React.createElement(GlossWord, {key:i, glossary:glossary, word:pair.word, lang:lang}, part) : part;
    });
  }

  // ── Попап "Спросить аналитика" — канонизировано на версию Глав 1/2
  // (имитация переписки, инлайн-SVG, rel=noreferrer, hover) -- Глава 3
  // получает апгрейд до неё же (её собственная версия была проще).
  var MSG_TR = {
    ru: { tag:"НАПИСАТЬ НАМ", title:"Предпочитаете мессенджер?",
          sub:"Напишите в Telegram или WhatsApp — сообщение уже готово, просто нажмите Отправить.",
          tgInc:"Привет 👋 Чем можем помочь? Оставьте заявку и мы пришлём материалы.",
          waInc:"Добрый день! Напишите что вас интересует <img class='mi-icon' style='vertical-align:middle' src='/assets/icons/icon-bar-chart.png' alt='' width='20' height='20' />",
          btnTg:"ОТКРЫТЬ TELEGRAM", btnWa:"ОТКРЫТЬ WHATSAPP", you:"Вы", online:"онлайн", justNow:"только что" },
    en: { tag:"CONTACT US", title:"Prefer a messenger?",
          sub:"Write us on Telegram or WhatsApp — the message is pre-filled, just click Send.",
          tgInc:"Hi 👋 How can we help? Leave a request and we'll send the materials.",
          waInc:"Good day! Tell us what you're interested in <img class='mi-icon' style='vertical-align:middle' src='/assets/icons/icon-bar-chart.png' alt='' width='20' height='20' />",
          btnTg:"OPEN TELEGRAM", btnWa:"OPEN WHATSAPP", you:"You", online:"online", justNow:"just now" },
    ro: { tag:"CONTACTAȚI-NE", title:"Preferați un messenger?",
          sub:"Scrieți pe Telegram sau WhatsApp — mesajul este pregătit, doar apăsați Trimite.",
          tgInc:"Bună 👋 Cu ce vă putem ajuta? Lăsați o cerere și vă trimitem materialele.",
          waInc:"Bună ziua! Spuneți-ne ce vă interesează <img class='mi-icon' style='vertical-align:middle' src='/assets/icons/icon-bar-chart.png' alt='' width='20' height='20' />",
          btnTg:"DESCHIDE TELEGRAM", btnWa:"DESCHIDE WHATSAPP", you:"Dvs.", online:"online", justNow:"chiar acum" },
  };

  function AskAnalystPopup(props) {
    var chapterNum = props.chapterNum, lang = props.lang, onClose = props.onClose;
    var tr = MSG_TR[lang] || MSG_TR.ru;
    var prefillRu = "Здравствуйте, есть вопрос по главе " + chapterNum;
    var prefillEn = "Hello, I have a question about chapter " + chapterNum;
    var prefillRo = "Bună ziua, am o întrebare despre capitolul " + chapterNum;
    var msgText = lang === 'ru' ? prefillRu : lang === 'en' ? prefillEn : prefillRo;
    var tgLink = "https://t.me/SBF_Support?text=" + encodeURIComponent(msgText);
    var waLink = "https://api.whatsapp.com/send/?phone=37369005200&text=" + encodeURIComponent(msgText) + "&type=phone_number&app_absent=0";
    var e = React.createElement;

    return e('div', {style:{position:"fixed", inset:0, zIndex:500, display:"flex", alignItems:"center", justifyContent:"center", padding:20, overflowY:"auto"}, onClick:onClose},
      e('div', {style:{position:"fixed", inset:0, background:"rgba(250,248,245,0.98)"}}),
      e('div', {onClick:function(ev){ ev.stopPropagation(); }, style:{position:"relative", width:"100%", maxWidth:900, zIndex:1, margin:"auto", padding:"40px 0"}},
        e('button', {onClick:onClose, style:{position:"absolute", top:0, right:10, background:"none", border:"none", fontSize:35, cursor:"pointer", color:C.inkFaint, lineHeight:1}}, "×"),
        e('div', {style:{marginBottom:40, padding:"0 10px"}},
          e(Mono, {size:13, color:C.goldText, spacing:3, style:{display:"block", marginBottom:15}}, "— " + tr.tag),
          e('h2', {style:{fontSize:"clamp(30px,5vw,42px)", fontWeight:700, color:C.black, marginBottom:15, fontFamily:"'DM Serif Display',serif"}}, tr.title),
          e('p', {style:{fontSize:18, color:C.inkMid, lineHeight:1.6}}, tr.sub)
        ),
        e('div', {className:"messenger-grid"},
          e('div', {style:{background:"#ffffff", border:"1px solid #e0e0e0", borderRadius:12, padding:"30px 25px", display:"flex", flexDirection:"column", boxShadow:"0 10px 30px rgba(0,0,0,0.03)"}},
            e('div', {style:{display:"flex", alignItems:"center", gap:15, marginBottom:30}},
              e('div', {style:{width:50, height:50, borderRadius:"50%", background:"#e1f3fb", display:"flex", alignItems:"center", justifyContent:"center"}},
                e('svg', {width:24, height:24, viewBox:"0 0 24 24", fill:"none", xmlns:"http://www.w3.org/2000/svg"},
                  e('path', {d:"M20.665 3.717l-17.73 6.837c-1.21.486-1.203 1.161-.222 1.462l4.552 1.42 10.532-6.645c.498-.303.953-.14.579.192l-8.533 7.701h-.002l.002.002-.314 4.692c.46 0 .663-.211.921-.46l2.211-2.15 4.599 3.397c.848.467 1.457.227 1.668-.785l3.019-14.228c.309-1.239-.473-1.8-1.282-1.435z", fill:"#0088cc"})
                )
              ),
              e('div', {},
                e('div', {style:{fontSize:18, fontWeight:700, color:C.black}}, "SBF Support"),
                e('div', {style:{fontSize:14, color:C.inkFaint}}, "Telegram · " + tr.online)
              )
            ),
            e('div', {style:{background:"#f7f7f7", padding:"15px 20px", borderRadius:"12px 12px 12px 0", marginBottom:20, alignSelf:"flex-start", maxWidth:"90%"}},
              e('div', {style:{fontSize:16, color:C.black, lineHeight:1.5, marginBottom:8}}, tr.tgInc),
              e('div', {style:{fontSize:11, color:C.inkFaint}}, "SBF Support · " + tr.justNow)
            ),
            e('div', {style:{background:"#0088cc", padding:"15px 20px", borderRadius:"12px 12px 0 12px", marginBottom:30, alignSelf:"flex-end", maxWidth:"90%"}},
              e('div', {style:{fontSize:16, color:"#ffffff", lineHeight:1.5, marginBottom:8}}, msgText),
              e('div', {style:{fontSize:11, color:"rgba(255,255,255,0.7)", textAlign:"right"}}, tr.you + " · ✓✓")
            ),
            e('a', {href:tgLink, target:"_blank", rel:"noreferrer",
                    style:{marginTop:"auto", display:"block", background:"#0088cc", color:"#fff", textAlign:"center", padding:"18px 20px", borderRadius:8, fontSize:15, letterSpacing:1.5, fontFamily:"monospace", fontWeight:700, textDecoration:"none", transition:"opacity 0.2s"},
                    onMouseEnter:function(ev){ ev.currentTarget.style.opacity=0.85; }, onMouseLeave:function(ev){ ev.currentTarget.style.opacity=1; }},
              e('span', {style:{display:"inline-block", width:12, height:12, borderRadius:"50%", background:"#fff", marginRight:10, verticalAlign:"middle"}}),
              tr.btnTg
            )
          ),
          e('div', {style:{background:"#ffffff", border:"1px solid #e0e0e0", borderRadius:12, padding:"30px 25px", display:"flex", flexDirection:"column", boxShadow:"0 10px 30px rgba(0,0,0,0.03)"}},
            e('div', {style:{display:"flex", alignItems:"center", gap:15, marginBottom:30}},
              e('div', {style:{width:50, height:50, borderRadius:"50%", background:"#e8f5ed", display:"flex", alignItems:"center", justifyContent:"center"}},
                e('svg', {width:24, height:24, viewBox:"0 0 24 24", fill:"none", xmlns:"http://www.w3.org/2000/svg"},
                  e('path', {d:"M20.52 3.449C18.24 1.245 15.24 0 12.042 0 5.463 0 .104 5.334.101 11.893c-.001 2.093.546 4.14 1.587 5.945L.041 24l6.335-1.652c1.745.943 3.71 1.444 5.71 1.445h.005c6.577 0 11.938-5.336 11.94-11.897.002-3.174-1.229-6.158-3.511-8.447zm-8.473 17.51h-.004c-1.774-.001-3.513-.475-5.038-1.373l-.361-.213-3.744.977.994-3.633-.235-.373c-1.01-1.603-1.543-3.453-1.542-5.36.002-5.541 4.536-10.057 10.106-10.057 2.697.001 5.234 1.048 7.137 2.943 1.905 1.897 2.955 4.418 2.954 7.108-.002 5.542-4.538 10.058-10.108 10.058zm5.552-7.532c-.304-.152-1.799-.884-2.078-.985-.279-.101-.482-.152-.685.152-.203.303-.787.985-.964 1.187-.178.203-.356.228-.66.076-1.554-.775-2.73-1.564-3.76-3.32-.102-.178-.011-.274.141-.426.136-.136.304-.354.456-.532.152-.177.203-.303.304-.506.102-.203.051-.38-.025-.532-.076-.152-.685-1.643-.938-2.251-.247-.591-.497-.512-.685-.521-.177-.008-.38-.01-.582-.01-.203 0-.532.076-.811.38-.279.304-1.065 1.036-1.065 2.527s1.09 2.932 1.242 3.134c.152.202 2.146 3.262 5.197 4.577.726.313 1.292.5 1.734.64.729.231 1.393.198 1.916.12.585-.088 1.799-.733 2.053-1.442.253-.708.253-1.314.177-1.442-.076-.126-.279-.202-.583-.354z", fill:"#25d366"})
                )
              ),
              e('div', {},
                e('div', {style:{fontSize:18, fontWeight:700, color:C.black}}, "SBF Company"),
                e('div', {style:{fontSize:14, color:C.inkFaint}}, "WhatsApp · " + tr.online)
              )
            ),
            e('div', {style:{background:"#f7f7f7", padding:"15px 20px", borderRadius:"12px 12px 12px 0", marginBottom:20, alignSelf:"flex-start", maxWidth:"90%"}},
              e('div', {style:{fontSize:16, color:C.black, lineHeight:1.5, marginBottom:8}, dangerouslySetInnerHTML:{__html: tr.waInc}}),
              e('div', {style:{fontSize:11, color:C.inkFaint}}, "SBF · " + tr.justNow)
            ),
            e('div', {style:{background:"#25d366", padding:"15px 20px", borderRadius:"12px 12px 0 12px", marginBottom:30, alignSelf:"flex-end", maxWidth:"90%"}},
              e('div', {style:{fontSize:16, color:"#ffffff", lineHeight:1.5, marginBottom:8}}, msgText),
              e('div', {style:{fontSize:11, color:"rgba(255,255,255,0.8)", textAlign:"right"}}, tr.you + " · ✓✓")
            ),
            e('a', {href:waLink, target:"_blank", rel:"noreferrer",
                    style:{marginTop:"auto", display:"block", background:"#25d366", color:"#fff", textAlign:"center", padding:"18px 20px", borderRadius:8, fontSize:15, letterSpacing:1.5, fontFamily:"monospace", fontWeight:700, textDecoration:"none", transition:"opacity 0.2s"},
                    onMouseEnter:function(ev){ ev.currentTarget.style.opacity=0.85; }, onMouseLeave:function(ev){ ev.currentTarget.style.opacity=1; }},
              e('span', {style:{display:"inline-block", marginRight:10, verticalAlign:"middle"}},
                e('img', {className:"mi-icon", style:{verticalAlign:"middle"}, src:"/assets/icons/icon-quote.png", alt:"", width:20, height:20})
              ),
              tr.btnWa
            )
          )
        )
      )
    );
  }

  function AskAnalystBtn(props) {
    var tr = props.tr, chapterNum = props.chapterNum, lang = props.lang;
    var s = React.useState(false), open = s[0], setOpen = s[1];
    return React.createElement('span', {},
      // «Остался вопрос? Напиши аналитику» — единственный способ связаться с
      // человеком прямо из главы, и он стоит в тринадцати главах из
      // пятнадцати. Как <span onClick> он был недостижим с клавиатуры и не
      // попадал в список интерактивных элементов страницы вовсе.
      React.createElement('button', {
        type: "button",
        onClick: function(){ setOpen(true); },
        // Цель касания: высота была 20 px — ниже минимума 2.5.8 (24).
        // Ширина уже во всю строку, добираем только высоту отступами,
        // подчёркивание остаётся под текстом (border-bottom ушёл на
        // внутренний span был бы лишним — хватает text-decoration).
        style:{fontSize:15, color:C.inkSoft, fontFamily:"monospace", letterSpacing:1,
               textDecoration:"underline", textUnderlineOffset:3, cursor:"pointer",
               display:"inline-block", background:"none", border:"none",
               borderRadius:0, padding:"8px 0", margin:0, minHeight:36, textAlign:"left"}
      }, tr.askAnalyst),
      open && React.createElement(AskAnalystPopup, {chapterNum:chapterNum, lang:lang, onClose:function(){ setOpen(false); }})
    );
  }

  // ── getChUrl -- lang передаётся явно (INITIAL_LANG главы не виден
  // из этого отдельно загруженного файла).
  function getChUrl(ch, lang) {
    var p = new URLSearchParams(window.location.search).get('path') || 'explorer';
    var base = lang === 'ru' ? '/edu/b' : ('/edu/' + lang + '/b');
    return ch === 'start' ? (base + '?path=' + p) : (base + '/' + ch + '?path=' + p);
  }

  // ── Тест на воспроизведение (параметризованный: questions/levelId/lang/
  // copy). Паттерн подтверждён дважды (Главы 1 и 2) -- quizIdx/quizAnswers/
  // quizSelected, БЕЗ медали (тот паттерн -- из мёртвого edu_book_cover.html,
  // в реальной книге никогда не существовал).
  function QuizBlock(props) {
    var questions = props.questions, levelId = props.levelId, lang = props.lang, copy = props.copy;
    var onProgress = props.onProgress; // необязательный (answered, total) -- напр. для sticky-прогресс-бара главы
    var s1 = React.useState(0), quizIdx = s1[0], setQuizIdx = s1[1];
    var s2 = React.useState({}), quizAnswers = s2[0], setQuizAnswers = s2[1];
    var s3 = React.useState(null), quizSelected = s3[0], setQuizSelected = s3[1];
    var e = React.createElement;

    function postQuizAttempt(question_id, correct) {
      var doFetch = (window.sbfAuth && window.sbfAuth.isLoggedIn && window.sbfAuth.isLoggedIn())
        ? window.sbfAuth.fetch : fetch;
      doFetch('/api/academy/quiz-attempt', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({level_id:levelId, question_id:question_id, correct:correct}),
      }).catch(function(){});
    }

    function answerQuiz(optIdx) {
      if (quizSelected !== null) return;
      var q = questions[quizIdx];
      var correct = !!q.options[optIdx].correct;
      setQuizSelected(optIdx);
      setQuizAnswers(function(a){ var n = Object.assign({}, a); n[q.id] = correct; return n; });
      if (onProgress) onProgress(Object.keys(quizAnswers).length + 1, questions.length);
      postQuizAttempt(q.id, correct);
    }

    function nextQuiz() {
      setQuizSelected(null);
      setQuizIdx(function(i){ return i + 1; });
    }

    var header = [
      e(Mono, {key:"k", size:11, color:C.goldText, spacing:4, style:{display:"block", textAlign:"center", marginBottom:12}}, copy.kicker),
      e('h3', {key:"t", style:{fontFamily:"'DM Serif Display',serif", fontSize:26, color:C.black, fontWeight:400, textAlign:"center", marginBottom:28}}, copy.title),
    ];

    if (quizIdx < questions.length) {
      var q = questions[quizIdx];
      return e('div', {style:{marginBottom:60}}, header,
        e('div', {style:{border:"1px solid " + C.border, padding:"30px 5vw"}},
          e('div', {style:{fontFamily:"monospace", fontSize:12, color:C.inkFaint, marginBottom:14}}, (quizIdx+1) + " / " + questions.length),
          e('p', {style:{fontSize:20, fontWeight:700, color:C.black, marginBottom:22}}, q.prompt),
          e('div', {className:"quiz-optgrid"},
            q.options.map(function(opt, i){
              var showState = quizSelected !== null;
              var isSelected = quizSelected === i;
              var bg = showState ? (opt.correct ? C.goldPale : (isSelected ? C.redPale : C.white)) : C.white;
              var bd = showState ? (opt.correct ? C.gold : (isSelected ? C.red : C.border)) : C.border;
              // 🔴 Вариант ответа — кнопка, а не <div onClick>. Это главный
              // элемент управления во всём курсе: тест есть в каждой главе, и
              // до 10.09.2026 ответить на него с клавиатуры было нельзя.
              // disabled после ответа заодно чинит вторую проблему: раньше по
              // уже отвеченному вопросу клик проходил и подсвечивал другой
              // вариант, хотя ответ был засчитан.
              return e('button', {key:i, type:"button", disabled: showState,
                       onClick:function(){ answerQuiz(i); },
                       style:{width:"100%", padding:"14px 18px", border:"1px solid " + bd,
                              background:bg, cursor:showState?"default":"pointer",
                              transition:"all 0.2s", display:"flex", alignItems:"center",
                              minHeight:24, textAlign:"left", font:"inherit"}},
                e('span', {style:{fontSize:16, color:C.inkMid, textAlign:"left"}}, opt.text)
              );
            })
          ),
          quizSelected !== null && e('div', {style:{marginTop:18, padding:"14px 18px", background:q.options[quizSelected].correct?C.goldPale:C.redPale}},
            e('p', {style:{margin:0, fontSize:15, lineHeight:1.6, color:C.inkMid}}, q.options[quizSelected].correct ? q.feedbackCorrect : q.feedbackWrong)
          ),
          quizSelected !== null && e('button', {
            onClick: nextQuiz,
            style:{background:C.black, color:C.white, border:"none", padding:"12px 28px", cursor:"pointer", fontFamily:"monospace", fontSize:13, letterSpacing:2, fontWeight:700, marginTop:18},
            onMouseEnter:function(ev){ ev.target.style.background=C.gold; },
            onMouseLeave:function(ev){ ev.target.style.background=C.black; }
          }, copy.next)
        )
      );
    }

    var missed = questions.filter(function(q){ return quizAnswers[q.id] === false; })[0];
    var correctCount = Object.keys(quizAnswers).filter(function(k){ return quizAnswers[k]; }).length;
    var allCorrect = Object.keys(quizAnswers).length > 0 && Object.keys(quizAnswers).every(function(k){ return quizAnswers[k]; });
    return e('div', {style:{marginBottom:60}}, header,
      e('div', {style:{border:"1px solid " + C.gold, background:C.goldPale, padding:"30px 5vw", textAlign:"center"}},
        e('p', {style:{fontSize:22, fontWeight:700, color:C.black, marginBottom:8}}, correctCount + " / " + questions.length),
        e('p', {style:{fontSize:15, color:C.inkMid, marginBottom: allCorrect ? 0 : 16}}, allCorrect ? copy.stuckAll : copy.stuckSome),
        missed ? e('a', {href:"#" + missed.section, style:{color:"#a8851f", fontFamily:"monospace", fontSize:13}}, copy.backToSection) : null
      )
    );
  }

  // ── Матрица влияния/силы — общий компонент глав 2 и 6 (SPEC_ch2_debug_and_
  // chart_engine.md §2.2: "тот же компонент, что «матрица силы» в спеке главы
  // 6 -- одинаковая логика, одинаковый вид, один код"). Ждёт УЖЕ ATR/дневной-
  // диапазон-нормированные значения в cell.norm (нормировку каждая глава
  // считает своим build-скриптом на своих данных, здесь только отрисовка):
  // rows=[{key,label,cells:{SYM:{norm,n,raw?,rawUnit?,tooltip?}}}],
  // columns=[{key,label}], minCases=число, copy={rowHead,naLabel,lowSampleLegend}.
  // Малая выборка и "нет данных" -- визуально (приглушение+штриховка), а не
  // повторным текстом в каждой клетке (§2.2, "восемь повторов -> одна строка").
  function ImpactMatrix(props) {
    var rows = props.rows, columns = props.columns, minCases = props.minCases, copy = props.copy;
    var e = React.createElement;
    var hatch = "repeating-linear-gradient(45deg, rgba(24,24,26,0.055), rgba(24,24,26,0.055) 4px, transparent 4px, transparent 9px)";

    /* 🔴 Матрица отвечала на один вопрос — «какое событие вообще сильнее
     * всех»: строки сортировались по максимуму по всей строке, и порядок
     * был намертво зашит. А читатель приходит с вопросом про СВОЙ
     * инструмент: «что сильнее всего двигает золото». Ответ в таблице был,
     * но искать его надо было глазами по столбцу.
     *
     * Нажатие на заголовок столбца сортирует строки по нему. Заголовок —
     * кнопка с aria-sort, как в таблицах глав 7, 8 и 9: одинаковый приём в
     * одинаковых местах, доступно с клавиатуры.
     */
    var st = React.useState({key: null, dir: 1}), порядок = st[0], setПорядок = st[1];
    var МЕТКИ = {
      ru: {byStrength: "по силе", sortBy: "сортировать по столбцу"},
      ro: {byStrength: "după forță", sortBy: "sortează după coloană"},
      en: {byStrength: "by strength", sortBy: "sort by this column"}
    };
    var м = МЕТКИ[props.lang] || МЕТКИ.ru;

    function значение(row, key) {
      if (key === null) {
        // По умолчанию — максимум по строке, как было.
        return columns.reduce(function (m, c) {
          var cell = row.cells[c.key];
          return (cell && cell.norm != null) ? Math.max(m, cell.norm) : m;
        }, -1);
      }
      var cell = row.cells[key];
      return (cell && cell.norm != null) ? cell.norm : -1;
    }

    var sorted = rows.slice().sort(function (a, b) {
      return порядок.dir * (значение(b, порядок.key) - значение(a, порядок.key));
    });

    function щёлк(key) {
      if (порядок.key === key) { setПорядок({key: key, dir: -порядок.dir}); return; }
      setПорядок({key: key, dir: 1});
    }

    function cellBody(cell) {
      if (!cell || cell.n === 0 || cell.norm == null) {
        return e('div', { title: (cell && cell.tooltip) || undefined },
          e('div', { style: { fontFamily: "monospace", fontWeight: 700, color: C.inkFaint } }, "—"),
          e('div', { style: { fontSize: 10, color: C.inkFaint, fontFamily: "monospace" } }, copy.naLabel)
        );
      }
      var small = cell.n < minCases;
      return e('div', { title: cell.tooltip || undefined },
        e('div', { style: { fontFamily: "monospace", fontWeight: 700, fontSize: 15, color: small ? C.inkMid : C.black } }, cell.norm.toFixed(1)),
        cell.raw != null ? e('div', { style: { fontSize: 10, color: C.inkFaint, fontFamily: "monospace" } }, cell.raw.toFixed(1) + (cell.rawUnit || "")) : null,
        e('div', { style: { fontSize: 10, color: small ? "#a8851f" : C.inkFaint, fontFamily: "monospace" } }, "n=" + cell.n)
      );
    }

    return e('div', {},
      e('div', { style: { overflowX: "auto", marginBottom: 10 } },
        e('table', { style: { width: "100%", borderCollapse: "collapse", fontSize: 13, minWidth: 480 } },
          e('thead', {},
            e('tr', {},
              e('th', { scope: "col",
                        'aria-sort': порядок.key === null ? (порядок.dir > 0 ? "descending" : "ascending") : "none",
                        style: { textAlign: "left", padding: 0, borderBottom: "1px solid " + C.border } },
                e('button', { type: "button", onClick: function () { щёлк(null); },
                  style: { width: "100%", textAlign: "left", padding: "8px 10px", fontSize: 10.5,
                           fontFamily: "monospace", color: порядок.key === null ? C.goldText : C.inkFaint,
                           textTransform: "uppercase", cursor: "pointer", background: "none",
                           border: "none", fontWeight: 600 } },
                  copy.rowHead + " · " + м.byStrength + (порядок.key === null ? (порядок.dir > 0 ? " ▾" : " ▴") : ""))),
              columns.map(function (c) {
                var свой = порядок.key === c.key;
                return e('th', { key: c.key, scope: "col",
                                 'aria-sort': свой ? (порядок.dir > 0 ? "descending" : "ascending") : "none",
                                 style: { textAlign: "center", padding: 0, borderBottom: "1px solid " + C.border, whiteSpace: "nowrap" } },
                  e('button', { type: "button", onClick: function () { щёлк(c.key); }, title: м.sortBy,
                    style: { width: "100%", textAlign: "center", padding: "8px 10px", fontSize: 10.5,
                             fontFamily: "monospace", color: свой ? C.goldText : C.inkFaint,
                             textTransform: "uppercase", cursor: "pointer", background: "none",
                             border: "none", fontWeight: 600 } },
                    c.label + (свой ? (порядок.dir > 0 ? " ▾" : " ▴") : "")));
              })
            )
          ),
          e('tbody', {},
            sorted.map(function (row) {
              return e('tr', { key: row.key, style: { borderBottom: "1px solid " + C.border } },
                e('td', { style: { padding: "10px", fontWeight: 700, color: C.black, whiteSpace: "nowrap" } }, row.label),
                columns.map(function (c) {
                  var cell = row.cells[c.key];
                  var muted = !cell || cell.n === 0 || cell.norm == null || cell.n < minCases;
                  return e('td', { key: c.key, style: Object.assign({ padding: "10px", textAlign: "center" }, muted ? { backgroundImage: hatch } : {}) }, cellBody(cell));
                })
              );
            })
          )
        )
      ),
      e('p', { style: { fontSize: 11, color: C.inkFaint, lineHeight: 1.6 } }, copy.lowSampleLegend)
    );
  }

  // ── Переключатель «Просто / Как есть» (SPEC_ch2_debug_and_chart_engine.md
  // §3) -- читает/пишет window.SbfSimpleLang (simple-lang.js, грузится
  // глобально ДО этого файла не гарантированно, поэтому все обращения --
  // внутри тела компонента/эффекта, не на верхнем уровне модуля). simplified/
  // total -- честный счётчик прогресса главы ("упрощены N из M", §3.2), а не
  // выдумка: считает его сам вызывающий (edu_book_N.html), этот компонент
  // только показывает то, что ему передали.
  function SimpleLangToggle(props) {
    var lang = props.lang, simplified = props.simplified, total = props.total;
    var e = React.createElement;
    var s = React.useState(function () { return (window.SbfSimpleLang && window.SbfSimpleLang.get()) || "pro"; });
    var mode = s[0], setMode = s[1];
    React.useEffect(function () {
      if (!window.SbfSimpleLang) return undefined;
      return window.SbfSimpleLang.subscribe(setMode);
    }, []);
    var L = ({
      ru: { simple: "Просто", pro: "Как есть", progress: function (n, m) { return "упрощены " + n + " из " + m; } },
      ro: { simple: "Simplu", pro: "Ca atare", progress: function (n, m) { return "simplificate " + n + " din " + m; } },
      en: { simple: "Simple", pro: "As-is", progress: function (n, m) { return "simplified " + n + " of " + m; } },
    })[lang] || { simple: "Просто", pro: "Как есть", progress: function (n, m) { return "упрощены " + n + " из " + m; } };
    function btn(key, text) {
      var active = mode === key;
      return e('button', {
        key: key,
        onClick: function () { window.SbfSimpleLang && window.SbfSimpleLang.set(key); },
        style: {
          fontFamily: "monospace", fontSize: 11.5, letterSpacing: 1, padding: "6px 14px", border: "1px solid " + (active ? C.gold : C.border),
          background: active ? C.gold : "transparent", color: active ? C.black : C.inkSoft, cursor: "pointer",
          borderRadius: key === "simple" ? "16px 0 0 16px" : "0 16px 16px 0", transition: "all .15s",
        },
      }, text);
    }
    return e('div', { style: { display: "inline-flex", flexDirection: "column", alignItems: "flex-start", gap: 4 } },
      e('div', { style: { display: "inline-flex" } }, btn("simple", L.simple), btn("pro", L.pro)),
      total ? e('span', { style: { fontSize: 10, color: C.inkFaint, fontFamily: "monospace" } }, L.progress(simplified, total)) : null
    );
  }

  // ── Комплаенс-дисклеймер (SPEC_academy_chapter3_integration.md §6,
  // решение А: оставляем RR/WinRate-математику как общую арифметику точки
  // безубыточности, добавляем один системный дисклеймер во все главы).
  var COMPLIANCE_TEXT = {
    ru: "Иллюстративные данные, используются в образовательных целях. Не является индивидуальной инвестиционной рекомендацией.",
    en: "Illustrative data, used for educational purposes. Not personalized investment advice.",
    ro: "Date ilustrative, utilizate în scopuri educaționale. Nu reprezintă o recomandare de investiții personalizată.",
  };
  function ComplianceFootnote(props) {
    var lang = props.lang;
    return React.createElement('p', {
      style:{fontFamily:"monospace", fontSize:11, color:C.inkFaint, textAlign:"center", lineHeight:1.6, margin:"32px auto 0", maxWidth:640}
    }, COMPLIANCE_TEXT[lang] || COMPLIANCE_TEXT.ru);
  }

  // Русское склонение числительных (SPEC_site_fixes_2026-07-28.md P2.1):
  // "61 дней" вместо "61 день" — числа теперь везде приходят из JSON
  // (бары/дни/периоды бэкфилла), такие места будут появляться постоянно
  // во всех главах, поэтому одна общая функция, а не разовая правка строки.
  function pluralRu(n, forms) {
    // forms = [один, немного (2-4), много (5-20, 0)] -- например
    // ["день","дня","дней"] или ["торговый день","торговых дня","торговых дней"].
    var mod10 = Math.abs(n) % 10, mod100 = Math.abs(n) % 100;
    if (mod10 === 1 && mod100 !== 11) return forms[0];
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return forms[1];
    return forms[2];
  }
  function declineRu(n, forms) {
    return n + ' ' + pluralRu(n, forms);
  }
  // Румынский: "de" перед мн.ч. существительным при числе >=20 ("61 de zile"),
  // без "de" для 2-19 ("19 zile") и ед.ч. для 1 ("1 zi"). [ДОПУЩЕНИЕ] упрощённое
  // правило -- не покрывает более редкие морфологические случаи, но верно для
  // всех числительных, встречающихся в курсе (дни/бары/периоды бэкфилла).
  function declineRo(n, singular, plural) {
    if (Math.abs(n) === 1) return n + ' ' + singular;
    return n + (Math.abs(n) >= 20 ? ' de ' : ' ') + plural;
  }
  // Английский: 1 -> singular, иначе plural (никакой другой развилки нет).
  function declineEn(n, singular, plural) {
    return n + ' ' + (Math.abs(n) === 1 ? singular : plural);
  }

  // ── ColdStart — единый интерактив "вопрос → действие → настоящий ответ"
  // (SPEC_coldstart_interactives_ch6_15.md §1). Один компонент на все главы
  // 6-15, отличаются только пропсы. Жёсткие правила спеки, которые компонент
  // соблюдает сам, а не понадеявшись на вызывающую главу:
  //  - ответ (reveal) не рендерится, пока action не зафиксирован (committed);
  //  - один жест на действие: choice -- клик по кнопке, slider -- отпускание
  //    указателя, numberInput -- Enter/blur, chartTap -- клик по свече;
  //  - bridge и reveal показываются вместе, после commit, единым блоком.
  // action.type: 'choice' | 'slider' | 'numberInput' | 'chartTap' | 'custom'.
  // reveal может быть строкой/нодой или функцией (answer) => нода -- удобно,
  // когда текст раскрытия зависит от того, что выбрал читатель.
  function ColdStart(props) {
    var tag = props.tag, ask = props.ask, action = props.action,
        reveal = props.reveal, bridge = props.bridge;
    var e = React.createElement;
    var s1 = React.useState(false), committed = s1[0], setCommitted = s1[1];
    var s2 = React.useState(null), answer = s2[0], setAnswer = s2[1];

    function commit(value) {
      if (committed) return;
      setAnswer(value);
      setCommitted(true);
    }

    var revealContent = committed ? (typeof reveal === "function" ? reveal(answer) : reveal) : null;

    return e('div', {style:{background:C.black, padding:"64px 5vw 52px", color:"#fff"}},
      tag ? e(Mono, {size:11, color:C.goldText, spacing:4, style:{display:"block", marginBottom:22, textAlign:"center"}}, tag) : null,
      e('p', {style:{fontFamily:"'DM Serif Display',serif", fontSize:"clamp(21px,3.2vw,28px)", color:"#fff",
                     textAlign:"center", maxWidth:680, margin:"0 auto 30px", lineHeight:1.42}}, ask),
      e('div', {style:{maxWidth:660, margin:"0 auto"}},
        ColdStartAction({action: action, committed: committed, answer: answer, commit: commit})
      ),
      committed && revealContent ? e('div', {style:{maxWidth:640, margin:"26px auto 0", padding:"20px 24px",
                    background:"rgba(201,151,58,0.1)", border:"1px solid rgba(201,151,58,0.3)", borderRadius:6}},
        e('div', {style:{fontSize:16, lineHeight:1.62, color:"#fff"}}, revealContent)
      ) : null,
      committed && bridge ? e('p', {style:{textAlign:"center", fontFamily:"monospace", fontSize:12,
                    color:C.goldText, letterSpacing:0.5, marginTop:22, marginBottom:0}}, bridge) : null
    );
  }

  function ColdStartAction(p) {
    var action = p.action, committed = p.committed, answer = p.answer, commit = p.commit;
    var e = React.createElement;
    if (!action) return null;
    if (action.type === "choice") return ColdStartChoice({options: action.options, committed: committed, answer: answer, commit: commit});
    if (action.type === "slider") return ColdStartSlider({cfg: action.slider, committed: committed, commit: commit});
    if (action.type === "numberInput") return ColdStartNumberInput({cfg: action.numberInput, committed: committed, commit: commit});
    if (action.type === "chartTap") return ColdStartChartTap({cfg: action.chart, committed: committed, commit: commit});
    if (action.type === "custom" && typeof action.render === "function") return action.render(commit, committed, answer);
    return null;
  }

  function ColdStartChoice(p) {
    var options = p.options, committed = p.committed, answer = p.answer, commit = p.commit;
    var e = React.createElement;
    return e('div', {style:{display:"flex", gap:10, flexWrap:"wrap", justifyContent:"center"}},
      options.map(function (opt, i) {
        var isPicked = committed && answer === opt.value;
        return e('button', {
          key: i, disabled: committed,
          onClick: function () { commit(opt.value); },
          style: {
            fontFamily:"monospace", fontSize:14, fontWeight:700, letterSpacing:0.5,
            padding:"14px 22px", borderRadius:4, cursor: committed ? "default" : "pointer",
            background: isPicked ? C.gold : "rgba(255,255,255,0.06)",
            color: isPicked ? C.black : "#fff",
            border:"1px solid " + (isPicked ? C.gold : "rgba(255,255,255,0.22)"),
            opacity: committed && !isPicked ? 0.45 : 1, transition:"all .15s", minWidth:96,
          }
        }, opt.label);
      })
    );
  }

  function ColdStartSlider(p) {
    var cfg = p.cfg, committed = p.committed, commit = p.commit;
    var e = React.createElement;
    var s = React.useState(cfg.default), val = s[0], setVal = s[1];
    var fmt = cfg.format || function (v) { return String(v); };
    function release() { if (!committed) commit(val); }
    return e('div', {style:{textAlign:"center"}},
      e('div', {style:{fontFamily:"monospace", fontSize:28, fontWeight:700, color:C.goldText, marginBottom:14}}, fmt(val)),
      e('input', {
        // Имя ползунка: диктор иначе скажет «ползунок» и не скажет, чего.
        // Вопрос блока — самая осмысленная подпись, какая тут есть:
        // он и объясняет, что именно двигают.
        "aria-label": cfg.label || cfg.question || cfg.title || "",
        type:"range", min:cfg.min, max:cfg.max, step:cfg.step || 1, value:val, disabled:committed,
        onChange: function (ev) { setVal(+ev.target.value); },
        onMouseUp: release, onTouchEnd: release, onKeyUp: function (ev) { if (ev.key === "Enter") release(); },
        style:{width:"100%", accentColor:C.gold, cursor: committed ? "default" : "pointer"}
      })
    );
  }

  function ColdStartNumberInput(p) {
    var cfg = p.cfg, committed = p.committed, commit = p.commit;
    var e = React.createElement;
    var s = React.useState(cfg.default != null ? String(cfg.default) : ""), val = s[0], setVal = s[1];
    function submit() {
      if (committed) return;
      var n = parseFloat(val);
      if (!isNaN(n)) commit(n);
    }
    return e('div', {style:{display:"flex", gap:10, justifyContent:"center", alignItems:"center"}},
      e('input', {
        type:"number", value:val, disabled:committed, placeholder:cfg.placeholder || "",
        onChange: function (ev) { setVal(ev.target.value); },
        onKeyDown: function (ev) { if (ev.key === "Enter") submit(); },
        onBlur: submit,
        style:{fontFamily:"monospace", fontSize:20, padding:"12px 16px", width:120, textAlign:"center",
               background:"rgba(255,255,255,0.06)", color:"#fff", border:"1px solid rgba(255,255,255,0.22)", borderRadius:4}
      }),
      cfg.unit ? e('span', {style:{fontFamily:"monospace", fontSize:14, color:"rgba(255,255,255,0.6)"}}, cfg.unit) : null,
      !committed ? e('button', {
        onClick: submit,
        style:{fontFamily:"monospace", fontSize:14, fontWeight:700, padding:"12px 18px", borderRadius:4,
               cursor:"pointer", background:C.gold, color:C.black, border:"none"}
      }, "→") : null
    );
  }

  // Тап по свече на реальном LightweightCharts-графике с закрытой правой
  // частью -- тот же механизм, что уже проверен в SqueezeTrainer (Глава 6,
  // SPEC_charts_and_interactivity_standard.md §2/§2.1): реальные бары,
  // ценовая/временная ось, data-source, штора вместо нарисованного будущего.
  // cfg = {candles:[{time,open,high,low,close}], visibleCount, dataSource,
  //        isCorrect:(time)=>bool, height}.
  function ColdStartChartTap(p) {
    var cfg = p.cfg, committed = p.committed, commit = p.commit;
    var e = React.createElement;
    var containerRef = React.useRef(null);
    var chartRef = React.useRef(null);
    var seriesRef = React.useRef(null);
    var tapHandlerRef = React.useRef(null);
    var s = React.useState(false), missed = s[0], setMissed = s[1];

    tapHandlerRef.current = function (time) {
      if (committed) return;
      if (cfg.isCorrect(time)) { setMissed(false); commit(time); }
      else { setMissed(true); setTimeout(function () { setMissed(false); }, 500); }
    };

    React.useEffect(function () {
      if (!containerRef.current || chartRef.current || typeof LightweightCharts === "undefined") return undefined;
      var chart = LightweightCharts.createChart(containerRef.current, {
        width: containerRef.current.clientWidth, height: cfg.height || 300,
        layout: { background: { color: C.chartBg }, textColor: "rgba(255,255,255,0.55)" },
        grid: { vertLines: { color: "rgba(255,255,255,0.05)" }, horzLines: { color: "rgba(255,255,255,0.05)" } },
        rightPriceScale: { borderColor: "rgba(255,255,255,0.15)" },
        timeScale: { borderColor: "rgba(255,255,255,0.15)", timeVisible: true, secondsVisible: false },
      });
      var series = chart.addCandlestickSeries({
        upColor: C.chartGreen, downColor: C.chartRed, borderUpColor: C.chartGreen, borderDownColor: C.chartRed,
        wickUpColor: C.chartGreen, wickDownColor: C.chartRed,
      });
      chartRef.current = chart; seriesRef.current = series;
      chart.subscribeClick(function (param) { if (param.time != null && tapHandlerRef.current) tapHandlerRef.current(param.time); });
      var ro = new ResizeObserver(function (entries) { if (entries[0]) chart.applyOptions({ width: entries[0].contentRect.width }); });
      ro.observe(containerRef.current);
      return function () { ro.disconnect(); chart.remove(); chartRef.current = null; };
    }, []);

    React.useEffect(function () {
      var series = seriesRef.current;
      if (!series || !cfg.candles || !cfg.candles.length) return;
      var visibleCount = committed ? cfg.candles.length : Math.min(cfg.visibleCount, cfg.candles.length);
      series.setData(cfg.candles.slice(0, visibleCount).map(function (c) {
        return { time: c.time, open: +c.open, high: +c.high, low: +c.low, close: +c.close };
      }));
      if (committed && cfg.markerTime != null) {
        series.setMarkers([{ time: cfg.markerTime, position:"aboveBar", color:C.goldText, shape:"arrowDown", text: cfg.markerText || "" }]);
      } else {
        series.setMarkers([]);
      }
      chartRef.current.timeScale().fitContent();
    }, [cfg.candles, cfg.visibleCount, committed, cfg.markerTime]);

    return e('div', {style:{position:"relative", borderRadius:6, overflow:"hidden",
                            border: missed ? "1px solid " + C.red : "1px solid transparent", transition:"border .2s",
                            cursor: committed ? "default" : "crosshair"}},
      e('div', {ref:containerRef, "data-source":cfg.dataSource}),
      !committed ? e('div', {style:{position:"absolute", top:0, right:0, bottom:0,
                    width: (100 - (cfg.visibleCount / cfg.candles.length * 100)) + "%",
                    background:"rgba(19,23,34,0.92)", pointerEvents:"none"}}) : null
    );
  }

  /* ── АНТИ-МИФ: слои снимаются по одному ────────────────────────────────
   *
   * ЗАЧЕМ. Замер 10.09.2026 по всем пятнадцати главам: в главах 6-15 вдвое
   * меньше интерактивных элементов при том же объёме текста, а медиана куска
   * текста между двумя действиями — 1064 знака против 401 в главах 2-5. Причём
   * рубрика «АНТИ-МИФ» стоит в начале самого длинного куска в ШЕСТИ главах из
   * десяти: 6, 7, 8, 9, 10, 12.
   *
   * В главе 5 та же рубрика — компонент с двумя кнопками. В главах 6-14 её
   * скопировали как три-четыре подряд идущих <p> на 900-1300 знаков. Один
   * шаблон испортил статистику половине курса.
   *
   * ПОЧЕМУ ИМЕННО «ПО ОДНОМУ СЛОЮ», а не вкладки и не аккордеон. Так устроен
   * сам текст рубрики: «миф здесь слоёный, и снимать надо по одному» (гл. 7),
   * «у этой главы миф двусторонний» (гл. 5). Первый абзац — ходовое
   * заблуждение, последний — что остаётся после разбора. Порядок в этой
   * рубрике несёт смысл, поэтому и раскрытие последовательное.
   *
   * 🔴 Уже раскрытое НЕ прячется обратно. Соблазн сделать «одна карточка за
   * раз» велик — так метрика была бы ещё лучше, — но читателю нужно вернуться
   * глазами к предыдущему слою, когда он читает следующий: они спорят друг с
   * другом. Прятать прочитанное ради красивого числа значит чинить замер, а
   * не главу.
   */
  /* Наборы подписей. Ключ — рубрика, а не «вариант 1/2»: подпись кнопки в
   * этих блоках несёт смысл. У «ЦЕНЫ НЕЗНАНИЯ» последний абзац во всех пяти
   * главах буквально начинается словами «Честная вторая половина» — это не
   * выдуманная подпись, а фраза автора, вынесенная на кнопку. */
  var REVEAL_COPY = {
    layers: {
      ru: {next:"Снять следующий слой →", last:"Что остаётся →", of:"слой %1 из %2",
           done:"слои сняты"},
      ro: {next:"Înlătură stratul următor →", last:"Ce rămâne →",
           of:"stratul %1 din %2", done:"straturi înlăturate"},
      en: {next:"Peel the next layer →", last:"What remains →",
           of:"layer %1 of %2", done:"layers peeled"}
    },
    cost: {
      ru: {next:"Считаем дальше →", last:"Честная вторая половина →",
           of:"часть %1 из %2", done:"разобрано"},
      ro: {next:"Continuăm calculul →", last:"Cealaltă jumătate, cinstit →",
           of:"partea %1 din %2", done:"analizat"},
      en: {next:"Keep counting →", last:"The honest other half →",
           of:"part %1 of %2", done:"done"}
    }
  };
  var ANTIMYTH_COPY = REVEAL_COPY.layers;

  function antiMythBodies(data) {
    // В главах структура разная: где-то body, где-то body1..body4.
    if (!data) return [];
    if (data.bodies && data.bodies.length) return data.bodies;
    var out = [];
    if (data.body) out.push(data.body);
    for (var i = 1; i <= 8; i++) {
      if (data["body" + i]) out.push(data["body" + i]);
    }
    return out;
  }

  /* Абзацы, открывающиеся по одному. Общий движок для «АНТИ-МИФА» и «ЦЕНЫ
   * НЕЗНАНИЯ»: обе рубрики устроены как последовательность, где порядок несёт
   * смысл, и обе были скопированы по главам как стена подряд идущих <p>.
   *
   * dark — блок на чёрной подложке («ЦЕНА НЕЗНАНИЯ» стоит на ней во всех
   * главах). Без этого флага светлый текст на светлом фоне.
   * bare — рисовать только абзацы и кнопку, без карточки, подписи и заголовка:
   * в «ЦЕНЕ НЕЗНАНИЯ» они уже нарисованы главой.
   */
  function RevealSteps(props) {
    var e = React.createElement;
    var bodies = props.bodies || [];
    var lang = props.lang || "ru";
    var набор = REVEAL_COPY[props.preset || "layers"] || REVEAL_COPY.layers;
    var copy = набор[lang] || набор.ru;
    var dark = !!props.dark;
    var st = React.useState(1), shown = st[0], setShown = st[1];
    var всего = bodies.length;
    var последний = shown >= всего;
    var цвет = dark ? "rgba(255,255,255,0.7)" : C.inkMid;
    var цветИтога = dark ? "#fff" : C.black;

    return e(React.Fragment, null,
      bodies.slice(0, shown).map(function (b, i) {
        var итог = i === всего - 1 && всего > 1;
        return e('p', {key:i, style:{fontSize:13.5, color: итог ? цветИтога : цвет,
                                     lineHeight: dark ? 1.75 : 1.7, marginBottom:12,
                                     fontWeight: итог ? 600 : 400}}, b);
      }),
      всего > 1 ? e('div', {style:{display:"flex", alignItems:"center", gap:12,
                                   marginTop:6, flexWrap:"wrap"}},
        !последний ? e('button', {
          onClick: function () { setShown(shown + 1); },
          style:{fontFamily:"monospace", fontSize:11.5, padding:"9px 16px", cursor:"pointer",
                 background:C.gold, color:"#18181a", border:"none", borderRadius:4,
                 fontWeight:700}
        }, shown === всего - 1 ? copy.last : copy.next) : null,
        e(Mono, {size:10.5, color: dark ? C.inkFaintOnDark : C.inkFaint},
          последний ? copy.done
                    : copy.of.replace("%1", String(shown)).replace("%2", String(всего)))
      ) : null
    );
  }

  function AntiMythBlock(props) {
    var e = React.createElement;
    var data = props.data || {};
    var bodies = antiMythBodies(data);

    // Внешний отступ приходит из главы: в разных главах блок стоит в разном
    // окружении (28 у одних, 48 у других), и зашитое здесь число ломало бы
    // вертикальный ритм страницы.
    return e('div', {style: props.style || {marginBottom:28}},
      data.tag ? e(Mono, {size:11, color:C.goldText, spacing:3,
                          style:{display:"block", marginBottom:10}}, data.tag) : null,
      e('div', {style:{background:C.surface, border:"1px solid " + C.border,
                       borderRadius:8, padding:"22px 26px"}},
        data.title ? e('p', {style:{fontWeight:600, fontSize:14.5, color:C.black,
                                    marginBottom:16}}, data.title) : null,
        e(RevealSteps, {bodies: bodies, lang: props.lang, preset: "layers"})
      )
    );
  }

  /* ── Чек-лист, который правда отмечается ───────────────────────────────
   *
   * ЗАЧЕМ. В главе 15 рубрика буквально называется «ЧТО ПРОВЕРИТЬ» и «КОГДА
   * НЕ НАДО ОТКРЫВАТЬ РЕАЛЬНЫЙ СЧЁТ» — и оба списка отрисованы точками. Список
   * вопросов, который нельзя отметить, читается как текст и пролистывается как
   * текст; отмеченный — это уже ответ читателя самому себе.
   *
   * 🔴 Ответы никуда не отправляются и нигде не сохраняются. Это разговор
   * человека с самим собой: «деньги заёмные», «недавно был крупный проигрыш»,
   * «есть желание отыграться». Такие галочки не наше дело — ни на сервере, ни
   * в localStorage. Состояние живёт в памяти вкладки и умирает с ней.
   *
   * mode:
   *   "any" — вывод показывается, как только отмечен ХОТЬ ОДИН пункт
   *           (стоп-лист: любой пункт означает «не сейчас»);
   *   "all" — счётчик прогресса, вывод в конце.
   */
  var CHECKLIST_COPY = {
    ru: {of:"отмечено %1 из %2", none:"ничего не отмечено"},
    ro: {of:"bifate %1 din %2", none:"nimic bifat"},
    en: {of:"%1 of %2 ticked", none:"nothing ticked"}
  };

  function CheckList(props) {
    var e = React.createElement;
    var items = props.items || [];
    var lang = props.lang || "ru";
    var copy = CHECKLIST_COPY[lang] || CHECKLIST_COPY.ru;
    var mode = props.mode || "all";
    var accent = props.accent || C.gold;
    var st = React.useState({}), отмечено = st[0], setОтмечено = st[1];
    var сколько = Object.keys(отмечено).filter(function (k) { return отмечено[k]; }).length;
    var показать = mode === "any" ? сколько > 0 : сколько === items.length && items.length > 0;

    function переключить(i) {
      var копия = {};
      for (var k in отмечено) копия[k] = отмечено[k];
      копия[i] = !копия[i];
      setОтмечено(копия);
    }

    return e('div', {style: props.style || null},
      items.map(function (it, i) {
        var on = !!отмечено[i];
        return e('label', {key:i, style:{display:"flex", gap:11, marginBottom:11,
                  alignItems:"flex-start", cursor:"pointer"}},
          e('input', {type:"checkbox", checked:on,
                      onChange: function () { переключить(i); },
                      style:{marginTop:3, width:16, height:16, accentColor:accent,
                             flex:"0 0 16px", cursor:"pointer"}}),
          e('span', {style:{fontSize:13, lineHeight:1.6,
                            color: on ? C.black : C.inkMid,
                            fontWeight: on ? 600 : 400}}, it)
        );
      }),
      e('div', {style:{display:"flex", alignItems:"center", gap:12, marginTop:14,
                       flexWrap:"wrap"}},
        e(Mono, {size:10.5, color: сколько ? accent : C.inkFaint},
          сколько ? copy.of.replace("%1", String(сколько)).replace("%2", String(items.length))
                  : copy.none)
      ),
      показать && props.verdict
        ? e('p', {style:{fontSize:13.5, color:C.black, fontWeight:600, lineHeight:1.7,
                         marginTop:14, marginBottom:0,
                         borderTop:"1px solid " + C.border, paddingTop:14}}, props.verdict)
        : null
    );
  }

  /* ── Разложить по двум корзинам ────────────────────────────────────────
   *
   * ЗАЧЕМ ИМЕННО ЭТО. Девятое правило главы 15 звучит так: «отличай правило
   * процесса от параметра метода». До правки девять правил были списком —
   * то есть навык, который глава объявляет главным, читателю предлагалось
   * получить чтением. Здесь он его применяет: восемь утверждений, две
   * корзины, разбор после ответа.
   *
   * 🔴 Ответ показывается только после того, как человек разложил ВСЁ. Иначе
   * первая же подсказка превращает упражнение в чтение с подсветкой.
   */
  /* ── Справочник из N карточек → переключатель ──────────────────────────
   *
   * ЗАЧЕМ. «КАК ЧИТАТЬ ОТЧЁТНОСТЬ» в главе 9 — пять определений подряд:
   * выручка, EPS, маржа, сегментация, guidance. Замер: 2505 знаков одним
   * куском без единого управления. Выложенные разом, пять справочных статей
   * читаются как один абзац и пролистываются как один абзац.
   *
   * 🔴 ЭТО НЕ «СПРЯТАТЬ ТЕКСТ РАДИ МЕТРИКИ». Справочником пользуются
   * выборочно: человек смотрит один термин, а не читает все пять подряд.
   * Переключатель отвечает тому, как рубрику используют на самом деле, —
   * и заодно называет все пять терминов сразу, в подписях кнопок, чего
   * стена карточек не делала.
   *
   * items = [{title, body}]
   */
  function CardTabs(props) {
    var e = React.createElement;
    var items = (props.items || []).filter(function (it) { return it && it.title; });
    var st = React.useState(0), выбран = st[0], setВыбран = st[1];
    if (!items.length) return null;
    var текущий = items[Math.min(выбран, items.length - 1)];

    return e('div', {style: props.style || {marginBottom:20}},
      e('div', {style:{display:"flex", gap:7, flexWrap:"wrap", marginBottom:14}},
        items.map(function (it, i) {
          var активна = i === выбран;
          return e('button', {key:i, onClick: function () { setВыбран(i); },
            'aria-pressed': активна ? "true" : "false",
            style:{fontFamily:"monospace", fontSize:10.5, padding:"7px 13px",
                   cursor:"pointer", fontWeight:600, borderRadius:4,
                   background: активна ? C.gold : "#fff",
                   color: активна ? "#18181a" : C.inkMid,
                   border:"1px solid " + (активна ? C.gold : C.border)}}, it.title);
        })),
      e('div', {style:{background:C.surface, border:"1px solid " + C.border,
                       borderTop:"3px solid " + C.gold, borderRadius:6,
                       padding:"18px 22px", minHeight:96}},
        e('div', {style:{fontWeight:600, fontSize:13, color:C.black,
                         marginBottom:8}}, текущий.title),
        e('p', {style:{fontSize:12.5, color:C.inkMid, lineHeight:1.7, margin:0}},
          текущий.body))
    );
  }

  var SORT_COPY = {
    ru: {check:"Проверить →", again:"Ещё раз", left:"осталось %1",
         score:"верно %1 из %2", allRight:"Все восемь на местах."},
    ro: {check:"Verifică →", again:"Din nou", left:"au mai rămas %1",
         score:"corect %1 din %2", allRight:"Toate la locul lor."},
    en: {check:"Check →", again:"Again", left:"%1 left",
         score:"%1 of %2 correct", allRight:"All in the right place."}
  };

  function SortTwoBins(props) {
    var e = React.createElement;
    var items = props.items || [];   // [{text, bin: 0|1}]
    var labels = props.labels || ["", ""];
    var lang = props.lang || "ru";
    var copy = SORT_COPY[lang] || SORT_COPY.ru;
    var st = React.useState({}), выбор = st[0], setВыбор = st[1];
    var st2 = React.useState(false), проверено = st2[0], setПроверено = st2[1];

    var разложено = items.filter(function (_, i) { return выбор[i] !== undefined; }).length;
    var верно = items.filter(function (it, i) { return выбор[i] === it.bin; }).length;

    function положить(i, bin) {
      if (проверено) return;
      var копия = {};
      for (var k in выбор) копия[k] = выбор[k];
      копия[i] = bin;
      setВыбор(копия);
    }

    return e('div', {style: props.style || {marginBottom:32}},
      items.map(function (it, i) {
        var мой = выбор[i];
        var правильно = проверено && мой === it.bin;
        var неправильно = проверено && мой !== undefined && мой !== it.bin;
        return e('div', {key:i, style:{border:"1px solid " +
                    (правильно ? C.green : неправильно ? C.red : C.border),
                    background: правильно ? C.greenPale : неправильно ? C.redPale : C.surface,
                    borderRadius:6, padding:"12px 14px", marginBottom:10}},
          e('p', {style:{fontSize:12.5, color:C.black, lineHeight:1.55, margin:"0 0 9px"}}, it.text),
          e('div', {style:{display:"flex", gap:7, flexWrap:"wrap"}},
            [0, 1].map(function (b) {
              var активна = мой === b;
              return e('button', {key:b, onClick: function () { положить(i, b); },
                style:{fontFamily:"monospace", fontSize:10.5, padding:"6px 11px",
                       cursor: проверено ? "default" : "pointer",
                       background: активна ? C.gold : "#fff",
                       color: активна ? "#18181a" : C.inkMid,
                       border:"1px solid " + (активна ? C.gold : C.border),
                       borderRadius:4, fontWeight:600}}, labels[b]);
            }),
            проверено && неправильно
              ? e(Mono, {size:10, color:C.red, style:{alignSelf:"center"}}, labels[it.bin])
              : null
          )
        );
      }),
      e('div', {style:{display:"flex", alignItems:"center", gap:12, marginTop:6,
                       flexWrap:"wrap"}},
        !проверено
          ? e('button', {
              onClick: function () { if (разложено === items.length) setПроверено(true); },
              disabled: разложено !== items.length,
              style:{fontFamily:"monospace", fontSize:11.5, padding:"9px 16px",
                     cursor: разложено === items.length ? "pointer" : "default",
                     background: разложено === items.length ? C.gold : C.surfaceMid,
                     color: разложено === items.length ? "#18181a" : C.inkFaint,
                     border:"none", borderRadius:4, fontWeight:700}}, copy.check)
          : e('button', {onClick: function () { setВыбор({}); setПроверено(false); },
              style:{fontFamily:"monospace", fontSize:11.5, padding:"9px 16px",
                     cursor:"pointer", background:"#fff", color:C.inkMid,
                     border:"1px solid " + C.border, borderRadius:4, fontWeight:600}}, copy.again),
        e(Mono, {size:10.5, color: проверено ? C.goldText : C.inkFaint},
          проверено
            ? (верно === items.length ? copy.allRight
               : copy.score.replace("%1", String(верно)).replace("%2", String(items.length)))
            : copy.left.replace("%1", String(items.length - разложено)))
      )
    );
  }


  /* ── Выбор площадки: одна ступень, три главы ──────────────────────────────
     🔴 ПОЧЕМУ ОБЩИЙ КОМПОНЕНТ. Ступени 6 (гл. 11), 9 (гл. 14) и 10 (гл. 15)
     показывают читателю один и тот же список площадок с одними и теми же
     правилами: юрлицо резолвится по стране, плечо задаёт юрисдикция, процент
     теряющих счетов берётся у брокера с датой и ссылкой. Написать это трижды
     значило бы завести три источника правды для одного экрана — и однажды
     они разойдутся, как уже разошлись подписи статусов лида в CRM.

     Данные и разметка — из brokers.js (BrokerPicker), тот же код, что и на
     странице /brokers. Здесь только React-обёртка и ожидание скрипта:
     brokers.js подключён с defer и к первому рендеру главы может быть ещё
     не выполнен. */
  function PartnerPicker({ limit, place, errorText }) {
    const { useEffect, useRef, useState } = React;
    const узел = useRef(null);
    const [сбой, setСбой] = useState(false);

    useEffect(() => {
      let живо = true;
      const пуск = () => {
        if (!живо || !узел.current || !window.BrokerPicker) return;
        window.BrokerPicker.mount(узел.current, { limit: limit || 3, place: place || 'ladder' });
      };
      if (window.BrokerPicker) { пуск(); return; }
      const т = setInterval(() => { if (window.BrokerPicker) { clearInterval(т); пуск(); } }, 120);
      // Молча пустое место читается как «здесь ничего и не было», и чинить
      // его никто не придёт. Шесть секунд — с запасом на медленную сеть.
      const с = setTimeout(() => { clearInterval(т); if (живо && !window.BrokerPicker) setСбой(true); }, 6000);
      return () => { живо = false; clearInterval(т); clearTimeout(с); };
    }, [limit, place]);

    if (сбой) {
      return React.createElement('p',
        { style: { fontSize: 12, color: 'rgba(43,43,51,0.55)', fontStyle: 'italic' } },
        errorText || 'Сравнение площадок не загрузилось — данные лежат в /brokers.');
    }
    return React.createElement('div', { ref: узел });
  }

  window.AcademyShared = {
    AntiMythBlock: AntiMythBlock,
    RevealSteps: RevealSteps,
    CheckList: CheckList,
    SortTwoBins: SortTwoBins,
    CardTabs: CardTabs,
    C: C, Mono: Mono, Chip: Chip, Rule: Rule,
    GlossWord: GlossWord, withGlossTerms: withGlossTerms,
    AskAnalystPopup: AskAnalystPopup, AskAnalystBtn: AskAnalystBtn,
    getChUrl: getChUrl,
    QuizBlock: QuizBlock,
    ImpactMatrix: ImpactMatrix,
    SimpleLangToggle: SimpleLangToggle,
    ComplianceFootnote: ComplianceFootnote,
    pluralRu: pluralRu,
    declineRu: declineRu,
    declineRo: declineRo,
    declineEn: declineEn,
    ColdStart: ColdStart,
    PartnerPicker: PartnerPicker,
  };
})();
