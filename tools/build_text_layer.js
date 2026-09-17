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

function вHTML(блоки) {
  return блоки.map(([вид, т]) => вид === 'h'
    ? `<h2>${экран(т)}</h2>`
    : `<p>${экран(т).replace(/\n{2,}/g, '</p><p>').replace(/\n/g, ' ')}</p>`
  ).join('\n');
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
    const html = данные.map(т => [
      `<h2 id="gl-${экран(т.slug)}">${экран(т.term)}</h2>`,
      т.short ? `<p>${экран(т.short)}</p>` : '',
      т.full ? `<p>${экран(т.full)}</p>` : '',
      т.etym ? `<p>${экран(т.etym)}</p>` : '',
    ].filter(Boolean).join('\n')).join('\n');
    fs.writeFileSync(path.join(ВЫХОД, `glossary.${яз}.html`), html, 'utf8');
    итог.push([яз, `${данные.length} терминов`, html.length]);
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
