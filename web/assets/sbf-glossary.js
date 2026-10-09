/* ── SBF Glossary — auto-highlight + popup + /m/glossary page ─────────────── */
(function () {
  'use strict';

  // Detect language directly (do NOT rely on window.sbfI18n — this script
  // runs without `defer` and can execute before i18n.js's deferred code,
  // so the shared client-side dictionary is not guaranteed to be ready yet).
  // 🔴 Языки перечисляются группой, а не «ro против всего остального».
  // Регулярка знала ровно про ro, поэтому /en/glossary считался русским:
  // английский заголовок, английская обвязка — и 35 русских терминов под
  // ними. Пока язык определяется списком, забыть добавить его сюда при
  // появлении четвёртой локали будет так же легко, как это вышло с en.
  var LANG = (location.pathname.match(/^\/(ro|en)(\/|$)/) || [])[1] || 'ru';

  // Small self-contained dictionary for the handful of UI strings this file
  // owns directly (search placeholder, popup chrome) — no need to pull in
  // the server-side i18n dictionary for just 4 strings.
  // 🔴 Подписи разделов живут здесь, а НЕ в i18n/site/*.json, и это тот же
  // довод, что для четырёх строк выше: файл подключён без `defer` и
  // исполняется раньше i18n.js, поэтому общий словарь на момент отрисовки
  // не гарантирован. Держать их в i18n и читать отсюда значит иногда
  // рисовать фильтр с пустыми подписями. Ключи разделов — в данных
  // (поле section), список допустимых — в tools/glossary_merge.py.
  var STR = {
    ru: {
      etymology:      'Этимология',
      more_in_glossary: 'Подробнее в глоссарии →',
      search_placeholder: 'Поиск термина…',
      search_label:   'Поиск по глоссарию',
      related_prefix: 'По теме:',
      all_sections:   'Все',
      nothing_found:  'Ничего не найдено. Попробуйте другое слово или снимите фильтр.',
      counter:        'Статей: ',
      jump_label:     'Перейти к букве',
      sec: { technical:'Графика и индикаторы', macro:'Макро и центробанки',
             options:'Опционы', bonds:'Облигации и ставки',
             futures:'Фьючерсы и сырьё', fx:'Валютный рынок',
             equity:'Акции', crypto:'Крипта', risk:'Риск и портфель',
             micro:'Стакан и исполнение', brokers:'Брокеры и регуляторы',
             slang:'Сленг' }
    },
    ro: {
      etymology:      'Etimologie',
      more_in_glossary: 'Mai multe în glosar →',
      search_placeholder: 'Caută un termen…',
      search_label:   'Căutare în glosar',
      related_prefix: 'Vezi și:',
      all_sections:   'Toate',
      nothing_found:  'Nu s-a găsit nimic. Încercați alt cuvânt sau scoateți filtrul.',
      counter:        'Articole: ',
      jump_label:     'Salt la litera',
      sec: { technical:'Grafic și indicatori', macro:'Macro și bănci centrale',
             options:'Opțiuni', bonds:'Obligațiuni și dobânzi',
             futures:'Futures și materii prime', fx:'Piața valutară',
             equity:'Acțiuni', crypto:'Cripto', risk:'Risc și portofoliu',
             micro:'Carnet de ordine și execuție', brokers:'Brokeri și reglementatori',
             slang:'Argou' }
    },
    // Английской ветки тут не было вовсе — отсюда «Поиск термина…»
    // в поле над английским глоссарием.
    en: {
      etymology:      'Etymology',
      more_in_glossary: 'More in the glossary →',
      search_placeholder: 'Search a term…',
      search_label:   'Search the glossary',
      related_prefix: 'See also:',
      all_sections:   'All',
      nothing_found:  'Nothing found. Try another word or clear the filter.',
      counter:        'Entries: ',
      jump_label:     'Jump to letter',
      sec: { technical:'Charts and indicators', macro:'Macro and central banks',
             options:'Options', bonds:'Bonds and rates',
             futures:'Futures and commodities', fx:'Currency market',
             equity:'Equities', crypto:'Crypto', risk:'Risk and portfolio',
             micro:'Order book and execution', brokers:'Brokers and regulators',
             slang:'Slang' }
    }
  };
  function секция(ключ) {
    var таб = (STR[LANG] && STR[LANG].sec) || STR.ru.sec;
    return таб[ключ] || STR.ru.sec[ключ] || ключ;
  }
  function t(key) {
    return (STR[LANG] && STR[LANG][key]) || STR.ru[key];
  }

  var GLOSSARY = null;         // loaded lazily
  var _popup   = null;
  var _overlay = null;

  // 🔴 Словарь выбирается ПО ЯЗЫКУ, а не «ro или всё остальное». Прежний
  // тернарник отдавал английской локали русский файл: /en/glossary
  // показывал «Бычий рынок», «Волатильность», «Хомяк» под английским
  // заголовком Glossary — 35 из 46 терминов на русском (Л-1 языкового
  // аудита 17.09). Теперь запись одна на язык, и добавить четвёртый
  // язык — это добавить файл, а не переписать условие.
  var СЛОВАРИ = { ru: '/assets/glossary.json',
                  ro: '/assets/glossary.ro.json',
                  en: '/assets/glossary.en.json' };
  var GLOSSARY_URL = СЛОВАРИ[LANG] || СЛОВАРИ.ru;

  // ── Load glossary data ────────────────────────────────────────────────────
  function loadGlossary(cb) {
    if (GLOSSARY) { cb(GLOSSARY); return; }
    fetch(GLOSSARY_URL)
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (data) { GLOSSARY = data; cb(GLOSSARY); })
      .catch(function () { cb([]); });
  }

  // ── Build term → entry index ──────────────────────────────────────────────
  function buildIndex(data) {
    var idx = {}; // lowercase string → entry
    data.forEach(function (entry) {
      idx[entry.term.toLowerCase()] = entry;
      (entry.aliases || []).forEach(function (a) {
        idx[a.toLowerCase()] = entry;
      });
    });
    return idx;
  }

  // Build longest-first sorted list of all terms/aliases for matching
  function buildTermList(idx) {
    return Object.keys(idx).sort(function (a, b) { return b.length - a.length; });
  }

  // ── Highlight a single content block ─────────────────────────────────────
  // Rules:
  // - max 12 highlights per block
  // - only first occurrence of each slug per block
  // - skip inside <a>, <h1..h6>, already-highlighted <span.gl-term>
  function highlightBlock(el, idx, termList) {
    var highlighted = 0;
    var seenSlugs = {};

    function walkNode(node) {
      if (highlighted >= 12) return;
      if (node.nodeType === 1) {
        var tag = node.tagName.toLowerCase();
        if (tag === 'a' || /^h[1-6]$/.test(tag)) return;
        if (node.classList && node.classList.contains('gl-term')) return;
        var children = Array.prototype.slice.call(node.childNodes);
        children.forEach(function (child) { walkNode(child); });
        return;
      }
      if (node.nodeType !== 3) return; // only text nodes
      var text = node.nodeValue;
      if (!text || text.trim().length < 2) return;

      // Find first matching term in this text node
      var match = null;
      var matchStart = -1;
      var matchEntry = null;

      for (var i = 0; i < termList.length; i++) {
        var term = termList[i];
        var entry = idx[term];
        if (seenSlugs[entry.slug]) continue;
        // Word-boundary regex (case-insensitive)
        var re = new RegExp('(?<![а-яёa-z])' + regEscape(term) + '(?![а-яёa-z])', 'i');
        var m = re.exec(text);
        if (m && (matchStart === -1 || m.index < matchStart)) {
          matchStart = m.index;
          match = term;
          matchEntry = entry;
        }
      }

      if (!match || !matchEntry) return;
      seenSlugs[matchEntry.slug] = true;
      highlighted++;

      var before  = text.substring(0, matchStart);
      var matched = text.substring(matchStart, matchStart + match.length);
      var after   = text.substring(matchStart + match.length);

      var frag = document.createDocumentFragment();
      if (before) frag.appendChild(document.createTextNode(before));

      var span = document.createElement('span');
      span.className = 'gl-term';
      span.textContent = matched;
      span.setAttribute('data-slug', matchEntry.slug);
      span.addEventListener('click', function (e) {
        e.stopPropagation();
        showPopup(matchEntry, span);
      });
      frag.appendChild(span);

      // Replace node with fragment + rest as text
      var parent = node.parentNode;
      if (!parent) return;
      parent.insertBefore(frag, node);

      // Process remaining text recursively (after current span)
      if (after) {
        var rest = document.createTextNode(after);
        parent.insertBefore(rest, node);
        walkNode(rest);
      }
      parent.removeChild(node);
    }

    walkNode(el);
  }

  function regEscape(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  // ── Popup ─────────────────────────────────────────────────────────────────
  function ensurePopup() {
    if (_popup) return;

    _overlay = document.createElement('div');
    _overlay.id = 'glOverlay';
    _overlay.style.cssText =
      'display:none;position:fixed;inset:0;z-index:1000;' +
      'background:rgba(43,43,51,.35);touch-action:none;';
    _overlay.addEventListener('click', closePopup);
    document.body.appendChild(_overlay);

    _popup = document.createElement('div');
    _popup.id = 'glPopup';
    _popup.innerHTML =
      '<button id="glClose" style="position:absolute;top:10px;right:12px;' +
        'border:none;background:none;font-size:20px;cursor:pointer;color:var(--muted,#716A5A);' +
        'line-height:1;padding:0">✕</button>' +
      '<div id="glTerm" style="font-weight:700;font-size:15px;margin-bottom:6px"></div>' +
      '<div id="glShort" style="font-size:13px;line-height:1.6;color:var(--ink,#2B2B33)"></div>' +
      '<div id="glEtymWrap" style="margin-top:10px">' +
        '<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;' +
          'color:var(--gold-text,#866A19);margin-bottom:3px">' + t('etymology') + '</div>' +
        '<div id="glEtym" style="font-size:12px;line-height:1.5;color:var(--muted,#716A5A);font-style:italic"></div>' +
      '</div>' +
      '<a id="glMore" href="#" style="display:inline-block;margin-top:10px;font-size:12px;' +
        'color:var(--gold-text,#866A19);font-weight:600;text-decoration:none">' + t('more_in_glossary') + '</a>';
    _popup.style.cssText =
      'display:none;position:fixed;z-index:1001;' +
      'background:var(--paper,#fff);border:1px solid var(--line,#E7DFCF);' +
      'border-radius:14px;padding:20px 18px 16px;box-shadow:0 8px 32px rgba(43,43,51,.18);' +
      'max-width:340px;width:calc(100% - 32px);';
    document.body.appendChild(_popup);

    document.getElementById('glClose').addEventListener('click', closePopup);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closePopup();
    });
  }

  function showPopup(entry, anchor) {
    ensurePopup();
    document.getElementById('glTerm').textContent  = entry.term;
    document.getElementById('glShort').textContent = entry.short;
    var etymWrap = document.getElementById('glEtymWrap');
    if (entry.etym) {
      document.getElementById('glEtym').textContent = entry.etym;
      etymWrap.style.display = 'block';
    } else {
      etymWrap.style.display = 'none';
    }
    // 🔴 БЫЛО '/m/glossary#' + slug, И ЭТО ВЕЛО НА ГЛАВНУЮ.
    // Маршрут /m/* давно отдаёт 301 на '/', поэтому ссылка «Подробнее в
    // глоссарии» из любой карточки в тексте главы уводила читателя на
    // главную страницу — без якоря и без термина. Проверено запросом:
    // /m/glossary → 301 → https://lp.sbfconsult.com/. Плюс адрес был
    // всегда русский: на /en и /ro попап вёл в чужую локаль (это та же
    // утечка локали, что Л-6 языкового аудита).
    var moreLink = document.getElementById('glMore');
    moreLink.href = (LANG === 'ru' ? '' : '/' + LANG) + '/glossary#gl-' + entry.slug;

    _overlay.style.display = 'block';
    _popup.style.display = 'block';

    // Position: under anchor on desktop, bottom sheet on mobile
    if (window.innerWidth <= 640) {
      // bottom sheet
      _popup.style.bottom = '80px';
      _popup.style.left   = '50%';
      _popup.style.transform = 'translateX(-50%)';
      _popup.style.top = '';
    } else {
      var rect = anchor.getBoundingClientRect();
      var top = rect.bottom + window.scrollY + 6;
      var left = Math.min(rect.left + window.scrollX, window.innerWidth - 360);
      _popup.style.top  = top + 'px';
      _popup.style.left = Math.max(8, left) + 'px';
      _popup.style.bottom = '';
      _popup.style.transform = '';
    }
  }

  function closePopup() {
    if (_popup)   _popup.style.display   = 'none';
    if (_overlay) _overlay.style.display = 'none';
  }

  // ── Inject CSS ─────────────────────────────────────────────────────────────
  function injectCSS() {
    var st = document.createElement('style');
    st.textContent =
      '.gl-term{border-bottom:1.5px dotted var(--gold,#C9A227);cursor:pointer;color:inherit;' +
      'transition:background .12s;border-radius:2px;}' +
      '.gl-term:hover{background:rgba(201,162,39,.12);}';
    document.head.appendChild(st);
  }

  // ── Public: highlight a DOM element (called after content renders) ─────────
  function highlight(el) {
    loadGlossary(function (data) {
      var idx = buildIndex(data);
      var termList = buildTermList(idx);
      var blocks = el ? [el] : document.querySelectorAll('.report, .edu-content, [data-gl]');
      blocks.forEach(function (block) { highlightBlock(block, idx, termList); });
    });
  }

  // ── Glossary page ─────────────────────────────────────────────────────────
  // 🔴 ПЕРЕПИСАНО ПОД 219 СТАТЕЙ (было 46).
  // На сорока шести хватало одного поля поиска и заголовков-букв. На двух
  // сотнях это нечитаемо: страница стала длиннее экрана в десятки раз, а
  // «посмотреть, что вообще есть по опционам» было нельзя вовсе. Добавлены
  // три вещи и исправлены две.
  //   • Перемычка по буквам — чтобы до нужной статьи доходить прыжком.
  //   • Фильтр по разделам из поля section данных.
  //   • Поиск теперь ищет по НАЗВАНИЮ, СИНОНИМАМ и короткому определению.
  //     Прежний искал по textContent готовой карточки: синонимы в разметку
  //     не попадают, поэтому «фандинг» не находил funding-rate, а «ястреб» —
  //     hawkish. Это и есть главная поломка поиска, а не длина списка.
  //   • Ссылки «по теме» показывают ИМЯ статьи, а не slug: читать строку
  //     «negative-balance-protection» человеку не предлагают.
  //   • У поля поиска появился label (без него оно было безымянным для
  //     экранного чтения — та же находка С-4 аудита, что и 90 select'ов).
  function renderGlossaryPage(container, openSlug) {
    loadGlossary(function (data) {
      var sorted = data.slice().sort(function (a, b) {
        return a.term.localeCompare(b.term, LANG === 'ru' ? 'ru' : LANG);
      });
      var имена = {};
      sorted.forEach(function (т) { имена[т.slug] = т.term; });

      // Буква статьи. Цифры и знаки сводим в одну группу «#», иначе
      // перемычка обрастает одиночными буквами-сиротами.
      function буква(т) {
        var c = (т.term[0] || '').toUpperCase();
        return /[0-9#$€£¥₽₴₸]/.test(c) ? '#' : c;
      }

      var groups = {};
      sorted.forEach(function (entry) {
        var l = буква(entry);
        (groups[l] = groups[l] || []).push(entry);
      });
      var letters = Object.keys(groups).sort(function (a, b) {
        if (a === '#') return 1;
        if (b === '#') return -1;
        return a.localeCompare(b, LANG === 'ru' ? 'ru' : LANG);
      });

      // Разделы — только те, что реально есть в данных, в порядке убывания
      // числа статей: пустых кнопок на странице не бывает по построению.
      var счёт = {};
      sorted.forEach(function (т) { счёт[т.section] = (счёт[т.section] || 0) + 1; });
      var разделы = Object.keys(счёт).sort(function (a, b) { return счёт[b] - счёт[a]; });

      var ЧИП = 'display:inline-flex;align-items:center;min-height:44px;padding:0 13px;' +
        'margin:0 6px 6px 0;border:1.5px solid var(--line,#E7DFCF);border-radius:999px;' +
        'background:var(--paper,#fff);color:var(--ink,#2B2B33);font:600 12px Montserrat,sans-serif;' +
        'cursor:pointer;white-space:nowrap';

      var поиск =
        '<div style="position:sticky;top:64px;z-index:30;background:var(--cream,#FBF6EF);padding:10px 0 6px">' +
          '<label for="glSearch" style="position:absolute;width:1px;height:1px;overflow:hidden;' +
            'clip:rect(0 0 0 0);white-space:nowrap">' + esc(t('search_label')) + '</label>' +
          '<input id="glSearch" type="search" autocomplete="off" placeholder="' + esc(t('search_placeholder')) + '"' +
            ' style="width:100%;min-height:44px;padding:10px 14px;border:1.5px solid var(--line,#E7DFCF);' +
            'border-radius:10px;font-size:14px;font-family:Montserrat,sans-serif;background:var(--paper,#fff);' +
            'color:var(--ink,#2B2B33);box-sizing:border-box">' +
        '</div>';

      var чипы =
        '<div id="glSecs" role="group" aria-label="' + esc(t('jump_label')) + '" style="padding:4px 0 2px">' +
          '<button type="button" class="gl-sec" data-sec="" aria-pressed="true" style="' + ЧИП +
            ';border-color:var(--gold,#C9A227)">' + esc(t('all_sections')) + ' · ' + sorted.length + '</button>' +
          разделы.map(function (с) {
            return '<button type="button" class="gl-sec" data-sec="' + esc(с) + '" aria-pressed="false" style="' +
              ЧИП + '">' + esc(секция(с)) + ' · ' + счёт[с] + '</button>';
          }).join('') +
        '</div>';

      var перемычка =
        '<nav aria-label="' + esc(t('jump_label')) + '" style="padding:2px 0 8px;line-height:1">' +
          letters.map(function (l) {
            return '<a href="#gl-letter-' + encodeURIComponent(l) + '" class="gl-jump" style="' +
              'display:inline-flex;align-items:center;justify-content:center;min-width:30px;min-height:44px;' +
              'color:var(--gold-text,#866A19);font:700 12px JetBrains Mono,monospace;text-decoration:none">' +
              esc(l) + '</a>';
          }).join('') +
        '</nav>';

      var секции = letters.map(function (letter) {
        var карточки = groups[letter].map(function (entry) {
          var open = entry.slug === openSlug;
          // Стог для поиска: имя + синонимы + короткое определение.
          var стог = [entry.term, (entry.aliases || []).join(' '), entry.short || '']
            .join(' ').toLowerCase();
          return (
            '<div class="gl-card" id="gl-' + entry.slug + '" data-open="' + (open ? '1' : '0') + '" ' +
              'data-sec="' + esc(entry.section || '') + '" data-hay="' + esc(стог) + '" ' +
              'style="border:1px solid var(--line,#E7DFCF);border-radius:10px;' +
              'background:var(--paper,#fff);margin-bottom:6px;overflow:hidden">' +
            '<button type="button" class="gl-card-hd" aria-expanded="' + (open ? 'true' : 'false') + '" ' +
              'style="width:100%;min-height:44px;text-align:left;border:none;background:none;' +
              'padding:13px 14px;cursor:pointer;display:flex;align-items:center;justify-content:space-between;' +
              'gap:10px;font-family:Montserrat,sans-serif;font-size:13px;font-weight:600;color:var(--ink,#2B2B33)">' +
              '<span>' + esc(entry.term) + '</span>' +
              '<span class="gl-card-arrow" aria-hidden="true" style="font-size:10px;color:var(--muted,#716A5A);' +
                'transform:rotate(' + (open ? '180' : '0') + 'deg);transition:transform .2s">▼</span>' +
            '</button>' +
            '<div class="gl-card-body" style="display:' + (open ? 'block' : 'none') + ';' +
              'padding:0 14px 14px;font-size:13px;line-height:1.65;color:var(--ink,#2B2B33)">' +
              '<p style="color:var(--muted,#716A5A);font-size:12px;margin:0 0 8px">' + esc(entry.short) + '</p>' +
              '<p style="margin:0 0 10px">' + esc(entry.full) + '</p>' +
              (entry.etym
                ? '<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;' +
                    'color:var(--gold-text,#866A19);margin-bottom:3px">' + t('etymology') + '</div>' +
                  '<p style="margin:0 0 10px;font-size:12px;font-style:italic;color:var(--muted,#716A5A)">' +
                    esc(entry.etym) + '</p>'
                : '') +
              (entry.related && entry.related.length
                ? '<div style="font-size:11px;color:var(--muted,#716A5A)">' + esc(t('related_prefix')) + ' ' +
                  entry.related.filter(function (s) { return имена[s]; }).map(function (slug) {
                    return '<a href="#gl-' + slug + '" class="gl-rel" style="color:var(--gold-text,#866A19);' +
                      'text-decoration:none;margin-right:8px;white-space:nowrap">' + esc(имена[slug]) + '</a>';
                  }).join('') + '</div>'
                : '') +
            '</div>' +
            '</div>'
          );
        }).join('');
        return (
          '<div class="gl-section" data-letter="' + esc(letter) + '">' +
          '<h2 id="gl-letter-' + encodeURIComponent(letter) + '" style="font-size:11px;font-weight:700;' +
            'color:var(--muted,#716A5A);letter-spacing:.05em;text-transform:uppercase;' +
            'padding:10px 2px 6px;margin:0;scroll-margin-top:120px">' + esc(letter) + '</h2>' +
          карточки +
          '</div>'
        );
      }).join('');

      container.innerHTML = поиск + чипы + перемычка +
        '<p id="glCount" style="font-size:11px;color:var(--muted,#716A5A);margin:0 0 8px">' +
          esc(t('counter')) + sorted.length + '</p>' +
        '<p id="glEmpty" hidden style="font-size:13px;color:var(--muted,#716A5A);' +
          'padding:16px 2px">' + esc(t('nothing_found')) + '</p>' +
        '<div id="glSections">' + секции + '</div>';

      var входПоиска = container.querySelector('#glSearch');
      var счётчик    = container.querySelector('#glCount');
      var пусто      = container.querySelector('#glEmpty');
      var текРаздел  = '';

      // Один проход фильтрации на оба условия: раздел и строка поиска.
      // Раздельные обработчики раньше затирали работу друг друга.
      function применить() {
        var q = (входПоиска.value || '').toLowerCase().trim();
        var видно = 0;
        container.querySelectorAll('.gl-section').forEach(function (sec) {
          var есть = false;
          sec.querySelectorAll('.gl-card').forEach(function (card) {
            var ок = (!текРаздел || card.dataset.sec === текРаздел) &&
                     (!q || (card.dataset.hay || '').indexOf(q) !== -1);
            card.style.display = ок ? 'block' : 'none';
            if (ок) { есть = true; видно++; }
          });
          sec.style.display = есть ? 'block' : 'none';
        });
        счётчик.textContent = t('counter') + видно;
        пусто.hidden = видно > 0;
      }

      входПоиска.addEventListener('input', применить);

      container.querySelectorAll('.gl-sec').forEach(function (кн) {
        кн.addEventListener('click', function () {
          текРаздел = кн.dataset.sec || '';
          container.querySelectorAll('.gl-sec').forEach(function (д) {
            var выбран = d_eq(д, кн);
            д.setAttribute('aria-pressed', выбран ? 'true' : 'false');
            д.style.borderColor = выбран ? 'var(--gold,#C9A227)' : 'var(--line,#E7DFCF)';
          });
          применить();
        });
      });
      function d_eq(a, b) { return a === b; }

      // Раскрытие карточки
      container.addEventListener('click', function (e) {
        var hd = e.target.closest ? e.target.closest('.gl-card-hd') : null;
        if (!hd) return;
        var card = hd.closest('.gl-card');
        var body = card.querySelector('.gl-card-body');
        var arrow = hd.querySelector('.gl-card-arrow');
        var открыт = card.dataset.open === '1';
        body.style.display = открыт ? 'none' : 'block';
        arrow.style.transform = открыт ? 'rotate(0deg)' : 'rotate(180deg)';
        card.dataset.open = открыт ? '0' : '1';
        hd.setAttribute('aria-expanded', открыт ? 'false' : 'true');
        if (!открыт) setTimeout(function () {
          card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }, 80);
      });

      // Ссылка «по теме» раскрывает целевую статью.
      // 🔴 Снимает фильтр и поиск: иначе целевая карточка скрыта фильтром,
      // переход «срабатывает» и визуально не происходит ничего.
      container.addEventListener('click', function (e) {
        var rel = e.target.closest ? e.target.closest('.gl-rel') : null;
        if (!rel) return;
        e.preventDefault();
        var slug = rel.getAttribute('href').replace('#gl-', '');
        var target = container.querySelector('#gl-' + slug);
        if (!target) return;
        if (текРаздел || входПоиска.value) {
          текРаздел = ''; входПоиска.value = '';
          container.querySelectorAll('.gl-sec').forEach(function (д) {
            var всё = !д.dataset.sec;
            д.setAttribute('aria-pressed', всё ? 'true' : 'false');
            д.style.borderColor = всё ? 'var(--gold,#C9A227)' : 'var(--line,#E7DFCF)';
          });
          применить();
        }
        target.querySelector('.gl-card-body').style.display = 'block';
        target.querySelector('.gl-card-arrow').style.transform = 'rotate(180deg)';
        target.querySelector('.gl-card-hd').setAttribute('aria-expanded', 'true');
        target.dataset.open = '1';
        setTimeout(function () {
          target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 80);
      });

      if (openSlug) setTimeout(function () {
        var card = container.querySelector('#gl-' + openSlug);
        if (card) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }, 200);
    });
  }

  function esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // ── Init ─────────────────────────────────────────────────────────────────
  injectCSS();

  // Expose public API
  window.SBFGlossary = {
    highlight: highlight,
    renderPage: renderGlossaryPage,
    showPopup: showPopup,
    close: closePopup,
  };

  // Auto-highlight on DOM ready if we're on a content page
  function autoHighlight() {
    var el = document.querySelector('.report, [data-gl="1"]');
    if (el) highlight(el);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoHighlight);
  } else {
    autoHighlight();
  }

}());
