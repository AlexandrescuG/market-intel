/**
 * build_text_layer.js — текстовый слой страниц для тех, кто не исполняет JS.
 *
 * 🔴 ЗАЧЕМ. Главы курса, глоссарий и брокеры собираются в браузере: React +
 * Babel. Замер 17.09.2026 с выключенным JS: /edu/b/3 отдаёт 514 знаков из
 * 13 949, /glossary — 63 из 1497. ИИ-краулеры (GPTBot, ClaudeBot,
 * PerplexityBot) JavaScript не исполняют вовсе — анализ Vercel и MERJ на
 * 500 млн запросов GPTBot не нашёл ни одного случая. То есть для них
 * сорока шести статей глоссария и пятнадцати глав курса просто нет: на
 * платформу нечем ссылаться, потому что нечего прочитать.
 *
 * Текст берётся ИЗ ТЕХ ЖЕ источников, что и живая страница
 * (web/edu/assets/chN.js, web/assets/glossary*.json), а не пишется второй
 * копией: копия разошлась бы с оригиналом на первой же правке — это уже
 * случалось с подписями статусов в CRM (шесть копий, разъехались).
 *
 * Запуск:  node tools/build_text_layer.js
 * Выход:   web/data/text/edu_b<N>.<lang>.html и glossary.<lang>.html
 */
'use strict';

const fs = require('fs');
const path = require('path');

const КОРЕНЬ = path.resolve(__dirname, '..');
const ВЫХОД = path.join(КОРЕНЬ, 'web', 'data', 'text');
const ЯЗЫКИ = ['ru', 'ro', 'en'];

/* Поля, которые в тексте не нужны: это оформление, а не содержание.
   Без отсева в текстовый слой уезжают цвета, иконки и ключи — и
   получается страница, на которой ИИ прочитает «#c9973a». */
const ПРОПУСК = /(color|colour|icon|img|image|url|href|src|key|cls|class|^id$|btn|placeholder|aria|accent|bg|style)/i;
/* Поля-заголовки. Короткая строка в таком поле — подзаголовок раздела. */
const ЗАГОЛОВОК = /(title|heading|^h[1-6]$|^tag$|^name$|^term$)/i;
/* Ниже этой длины строка — почти всегда подпись кнопки или колонки. */
const МИН_АБЗАЦ = 40;

function экран(с) {
  return String(с).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                  .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/** Обходит дерево контента и возвращает [['h'|'p', текст], ...]. */
function собратьБлоки(узел) {
  const вышло = [];
  const виделиТекст = new Set();      // один и тот же текст в двух местах — один раз

  (function обход(о) {
    if (!о || typeof о !== 'object') return;
    if (Array.isArray(о)) { о.forEach(обход); return; }
    for (const [ключ, знач] of Object.entries(о)) {
      if (ПРОПУСК.test(ключ)) continue;
      if (typeof знач === 'string') {
        const т = знач.trim();
        if (!т || виделиТекст.has(т)) continue;
        if (ЗАГОЛОВОК.test(ключ) && т.length <= 120) {
          виделиТекст.add(т);
          вышло.push(['h', т]);
        } else if (т.length >= МИН_АБЗАЦ) {
          виделиТекст.add(т);
          вышло.push(['p', т]);
        }
      } else if (typeof знач === 'object') {
        обход(знач);
      }
    }
  })(узел);

  return вышло;
}

/* 🔴 ПЕРВЫЙ ЗАГОЛОВОК СЛОЯ — h1, ОСТАЛЬНЫЕ h2.
   Bing 30.09.2026: «H1 tag missing» на главной, и прогон по всей карте сайта
   показал 39 страниц из 51 вообще без h1. Причина системная: слой всегда
   начинался с h2, то есть страница открывалась сразу вторым уровнем.
   Для главы курса и инструкции брокера первый заголовок — это и есть предмет
   страницы («ЦЕНА СПЕШКИ», «XM»), поэтому повышение уровня не выдумывает
   новый текст, а называет уже имеющийся тем, чем он является. Для читателя с
   экранной читалкой это чинит навигацию по заголовкам, для краулера — SEO;
   видимого изменения нет, слой и так скрыт при работающем JS. */
function вHTML(блоки) {
  let первыйЗаголовокБыл = false;
  return блоки.map(([вид, т]) => {
    if (вид !== 'h')
      return `<p>${экран(т).replace(/\n{2,}/g, '</p><p>').replace(/\n/g, ' ')}</p>`;
    const уровень = первыйЗаголовокБыл ? 'h2' : 'h1';
    первыйЗаголовокБыл = true;
    return `<${уровень}>${экран(т)}</${уровень}>`;
  }).join('\n');
}

/* 🔴 У глав 1 и 2 текста в chN.js нет — он живёт в хронике под своими
   именами (ChronoStations, Chrono2Content и соседи). Если бы карта ниже
   молчала об этом, сборщик честно написал бы «нет файла», а две главы
   остались бы невидимыми — и это выглядело бы как решённая задача.
   Ключ карты — номер главы, значение: файлы и имена объектов в window. */
const ОСОБЫЕ = {
  1: { файлы: ['chrono.js'],
       объекты: ['ChronoStations', 'ChronoEraLegends', 'ChronoEraFinalNote'] },
  2: { файлы: ['chrono2.js'],
       объекты: ['Chrono2Stations', 'Chrono2Content', 'Chrono2Organizations',
                 'Chrono2Quiz', 'Chrono2Predict', 'Chrono2Cliffhanger',
                 'Chrono2SceneCopy'] },
};

/** Содержимое главы: обычное (ChNContent) или собранное из хроники. */
function содержимоеГлавы(n) {
  global.window = global.window || {};
  if (ОСОБЫЕ[n]) {
    for (const имя of ОСОБЫЕ[n].файлы) {
      const п = path.join(КОРЕНЬ, 'web', 'edu', 'assets', имя);
      if (!fs.existsSync(п)) continue;
      delete require.cache[require.resolve(п)];
      require(п);
    }
    // Склеиваем несколько объектов в один «язык → содержимое».
    const свод = {};
    for (const яз of ЯЗЫКИ) {
      const части = ОСОБЫЕ[n].объекты
        .map(имя => (global.window[имя] || {})[яз])
        .filter(Boolean);
      if (части.length) свод[яз] = части;
    }
    return Object.keys(свод).length ? свод : null;
  }
  const файл = path.join(КОРЕНЬ, 'web', 'edu', 'assets', `ch${n}.js`);
  if (!fs.existsSync(файл)) return null;
  delete require.cache[require.resolve(файл)];
  require(файл);
  return global.window[`Ch${n}Content`] || null;
}

function главы() {
  const итог = [];
  for (let n = 1; n <= 15; n++) {
    const содержимое = содержимоеГлавы(n);
    if (!содержимое) { итог.push([n, 'ИСТОЧНИК НЕ НАЙДЕН', 0]); continue; }
    for (const яз of ЯЗЫКИ) {
      const ветка = содержимое[яз];
      if (!ветка) continue;
      const блоки = собратьБлоки(ветка);
      const html = вHTML(блоки);
      fs.writeFileSync(path.join(ВЫХОД, `edu_b${n}.${яз}.html`), html, 'utf8');
      if (яз === 'ru') итог.push([n, `${блоки.length} блоков`, html.length]);
    }
  }
  return итог;
}

function глоссарий() {
  const итог = [];
  const файлы = { ru: 'glossary.json', ro: 'glossary.ro.json', en: 'glossary.en.json' };
  for (const [яз, имя] of Object.entries(файлы)) {
    const п = path.join(КОРЕНЬ, 'web', 'assets', имя);
    if (!fs.existsSync(п)) continue;
    const данные = JSON.parse(fs.readFileSync(п, 'utf8'));
    /* 🔴 Связи между терминами уже лежат в поле related, но существовали
       только для JS-версии страницы. Без них словарь для обходчика —
       46 абзацев подряд; с ними это связанный справочник, по которому
       можно ходить, и каждая статья имеет свой адрес с якорем. */
    const имена = Object.fromEntries(данные.map(т => [т.slug, т.term]));
    const html = данные.map(т => {
      const связи = (т.related || []).filter(с => имена[с]);
      return [
        `<h2 id="gl-${экран(т.slug)}">${экран(т.term)}</h2>`,
        т.short ? `<p>${экран(т.short)}</p>` : '',
        т.full ? `<p>${экран(т.full)}</p>` : '',
        т.etym ? `<p>${экран(т.etym)}</p>` : '',
        связи.length ? '<p>' + связи.map(с =>
          `<a href="#gl-${экран(с)}">${экран(имена[с])}</a>`).join(', ') + '</p>' : '',
      ].filter(Boolean).join('\n');
    }).join('\n');
    fs.writeFileSync(path.join(ВЫХОД, `glossary.${яз}.html`), html, 'utf8');
    итог.push([яз, `${данные.length} терминов`, html.length]);
  }
  return итог;
}

/* ── Брокеры ────────────────────────────────────────────────────────────────
   🔴 ЗДЕСЬ НЕЛЬЗЯ ОБХОДИТЬ ДЕРЕВО, как у глав. web/data/partners.json —
   рабочий файл со служебными пометками: «ВЫВОД, А НЕ ОПУБЛИКОВАННЫЙ ФАКТ»,
   «НЕ СНЯТЫ», blocker'ы, заметки о непроверенных партнёрских ссылках. У
   главы весь объект — её содержимое, поэтому обход годится; здесь обход
   вынес бы наши внутренние сомнения на страницу и в цитату ИИ-агента.
   Поэтому ниже — БЕЛЫЙ СПИСОК полей: ровно то, что видит человек. */

const ПОДПИСИ = {
  ru: { брокеры:'Брокеры: сравнение', юрлицо:'Юридическое лицо', лицензия:'лицензия',
        депозит:'Минимальный депозит', комиссия:'Комиссия', неактивность:'Плата за неактивность',
        платформы:'Платформы', спреды:'Спреды, публикуемые брокером', средний:'средний',
        мин:'минимальный', проверено:'проверено', нужно:'Что понадобится',
        платформа:'Где', снято:'Кадры сняты', регулятор:'Регулятор', юрисдикция:'Юрисдикция' },
  ro: { брокеры:'Brokeri: comparație', юрлицо:'Entitate juridică', лицензия:'licență',
        депозит:'Depozit minim', комиссия:'Comision', неактивность:'Taxă de inactivitate',
        платформы:'Platforme', спреды:'Spread-uri publicate de broker', средний:'mediu',
        мин:'minim', проверено:'verificat', нужно:'De ce aveți nevoie',
        платформа:'Unde', снято:'Capturi făcute', регулятор:'Autoritate', юрисдикция:'Jurisdicție' },
  en: { брокеры:'Brokers: comparison', юрлицо:'Legal entity', лицензия:'licence',
        депозит:'Minimum deposit', комиссия:'Commission', неактивность:'Inactivity fee',
        платформы:'Platforms', спреды:'Spreads published by the broker', средний:'average',
        мин:'minimum', проверено:'checked', нужно:'What you will need',
        платформа:'Where', снято:'Screenshots taken', регулятор:'Regulator', юрисдикция:'Jurisdiction' },
};

/** Поле с языковым вариантом: commission_short → commission_short_en. */
function поЯзыку(о, поле, яз) {
  if (!о) return '';
  return (яз !== 'ru' && о[`${поле}_${яз}`]) || о[поле] || '';
}

function брокеры() {
  const итог = [];
  const п = path.join(КОРЕНЬ, 'web', 'data', 'partners.json');
  if (!fs.existsSync(п)) return итог;
  const данные = JSON.parse(fs.readFileSync(п, 'utf8'));
  const живые = (данные.partners || []).filter(б => б.enabled);

  for (const яз of ЯЗЫКИ) {
    const С = ПОДПИСИ[яз];
    // Своего заголовка слою не нужно: h1 страницы уже говорит то же
    // самое, а дубль заголовка для краулера — шум.
    const части = [];
    for (const б of живые) {
      // Ссылка с карточки на инструкцию: страница сравнения — вход в
      // пять подробных материалов, и без ссылок обходчик о них не узнает.
      const адрес = (яз === 'ru' ? '' : '/' + яз) + '/brokers/' + б.id;
      части.push(`<h3><a href="${экран(адрес)}">${экран(б.name)}</a></h3>`);
      const стр = [];
      for (const e of б.entities || []) {
        // Юрлицо, юрисдикция, регулятор и номер лицензии — самое
        // цитируемое, что у нас есть: это проверяемые факты с номером.
        const хвост = e.licence_no ? `, ${С.лицензия} ${e.licence_no}` : '';
        стр.push(`${С.юрлицо}: ${e.legal_name} — ${С.юрисдикция} ${e.jurisdiction}`
                 + (e.regulator ? `, ${С.регулятор}: ${e.regulator}` : '') + хвост);
      }
      const д = б.min_deposit;
      if (д && д.value != null)
        стр.push(`${С.депозит}: ${д.value} ${д.currency || ''}`.trim()
                 + (д.checked ? ` (${С.проверено} ${д.checked})` : ''));
      const ком = поЯзыку(б, 'commission_short', яз);
      if (ком) стр.push(`${С.комиссия}: ${ком}`);
      const неакт = поЯзыку(б, 'inactivity_short', яз);
      if (неакт) стр.push(`${С.неактивность}: ${неакт}`);
      if ((б.platforms || []).length)
        стр.push(`${С.платформы}: ${б.platforms.join(', ')}`);
      части.push(стр.map(с => `<p>${экран(с)}</p>`).join('\n'));

      const сп = б.spreads_published;
      if (сп && (сп.items || []).length) {
        части.push(`<p>${экран(С.спреды)}`
          + (сп.account_type ? ` (${экран(сп.account_type)})` : '')
          + (сп.checked ? `, ${экран(С.проверено)} ${экран(сп.checked)}` : '') + ':</p>');
        части.push('<ul>' + сп.items.map(и =>
          `<li>${экран(и.symbol)}: ${С.средний} ${и.avg}`
          + (и.min != null ? `, ${С.мин} ${и.min}` : '')
          + (и.unit ? ` ${экран(и.unit)}` : '') + '</li>').join('') + '</ul>');
      }
    }
    fs.writeFileSync(path.join(ВЫХОД, `brokers.${яз}.html`), части.join('\n'), 'utf8');
    итог.push([яз, `${живые.length} площадок`, части.join('\n').length]);
  }
  return итог;
}

/** Инструкции: по файлу на брокера и язык, из тех же guides/*.json. */
function инструкции() {
  const итог = [];
  const каталог = path.join(КОРЕНЬ, 'web', 'data', 'guides');
  const список = ['xm', 'naga', 'fxpro', 'instaforex', 'avatrade'];
  for (const ид of список) {
    for (const яз of ЯЗЫКИ) {
      const С = ПОДПИСИ[яз];
      const файл = path.join(каталог, яз === 'ru' ? `${ид}.json` : `${ид}.${яз}.json`);
      if (!fs.existsSync(файл)) continue;
      const д = JSON.parse(fs.readFileSync(файл, 'utf8'));
      const пре = яз === 'ru' ? '' : '/' + яз;
      // h1, а не h2: имя брокера — предмет этой страницы. См. вHTML() выше.
      const части = [`<h1>${экран(д.name || ид)}</h1>`];
      if (д.lead) части.push(`<p>${экран(д.lead)}</p>`);
      // Назад к сравнению и вбок — к остальным четырём инструкциям.
      части.push('<p>' + [`<a href="${пре}/brokers">${экран(С.брокеры)}</a>`]
        .concat(список.filter(и => и !== ид)
          .map(и => `<a href="${пре}/brokers/${и}">${и.toUpperCase()}</a>`))
        .join(', ') + '</p>');

      for (const пр of д.processes || []) {
        части.push(`<h3>${экран(пр.label || пр.key || '')}</h3>`);
        if (пр.intro) части.push(`<p>${экран(пр.intro)}</p>`);
        const шапка = [];
        if (пр.platform) шапка.push(`${С.платформа}: ${пр.platform}`);
        if (пр.captured) шапка.push(`${С.снято}: ${пр.captured}`);
        if (шапка.length) части.push(`<p>${экран(шапка.join(' · '))}</p>`);
        if ((пр.needed || []).length)
          части.push(`<p>${экран(С.нужно)}: ${экран(пр.needed.join('; '))}</p>`);

        for (const б of пр.blocks || []) {
          if (б.type === 'steps') {
            // Подпись под кадром — это и есть шаг инструкции.
            части.push('<ol>' + (б.items || []).filter(и => и.caption)
              .map(и => `<li>${экран(и.caption)}</li>`).join('') + '</ol>');
          } else if (б.type === 'callout' || б.type === 'text') {
            if (б.title) части.push(`<h4>${экран(б.title)}</h4>`);
            const тело = Array.isArray(б.body) ? б.body : (б.body ? [б.body] : []);
            части.push(тело.map(т => `<p>${экран(т)}</p>`).join('\n'));
          } else if (б.type === 'table' && (б.rows || []).length) {
            части.push('<table>'
              + (б.columns ? '<tr>' + б.columns.map(к => `<th>${экран(к)}</th>`).join('') + '</tr>' : '')
              + б.rows.map(р => '<tr>' + р.map(я => `<td>${экран(я)}</td>`).join('') + '</tr>').join('')
              + '</table>');
          } else if (б.type === 'entity') {
            const стр = [];
            if (б.legal_name) стр.push(`${С.юрлицо}: ${б.legal_name}`);
            if (б.jurisdiction) стр.push(`${С.юрисдикция}: ${б.jurisdiction}`);
            if (б.regulator) стр.push(`${С.регулятор}: ${б.regulator}`);
            if (б.licence_no) стр.push(`${С.лицензия}: ${б.licence_no}`);
            if (стр.length) части.push(`<p>${экран(стр.join(' · '))}</p>`);
            if (б.quote) части.push(`<blockquote>${экран(б.quote)}</blockquote>`);
            // register_note и confirm_note рисует guide.js — это видимая
            // часть страницы, а не служебная пометка.
            for (const поле of ['register_note', 'confirm_note', 'missing'])
              if (б[поле]) части.push(`<p>${экран(б[поле])}</p>`);
          }
        }
      }
      const html = части.filter(Boolean).join('\n');
      fs.writeFileSync(path.join(ВЫХОД, `guide_${ид}.${яз}.html`), html, 'utf8');
      if (яз === 'ru') итог.push([ид, `${(д.processes || []).length} процессов`, html.length]);
    }
  }
  return итог;
}

fs.mkdirSync(ВЫХОД, { recursive: true });
console.log('главы:');
for (const [n, что, размер] of главы())
  console.log(`  ${String(n).padStart(2)} ${что.padEnd(16)} ${размер} знаков (ru)`);
console.log('глоссарий:');
for (const [яз, что, размер] of глоссарий())
  console.log(`  ${яз} ${что.padEnd(16)} ${размер} знаков`);
console.log('брокеры (страница сравнения):');
for (const [яз, что, размер] of брокеры())
  console.log(`  ${яз} ${что.padEnd(16)} ${размер} знаков`);
console.log('инструкции:');
for (const [ид, что, размер] of инструкции())
  console.log(`  ${ид.padEnd(11)} ${что.padEnd(16)} ${размер} знаков (ru)`);
