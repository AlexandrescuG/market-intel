/* ============================================================================
   SBF INTELLIGENCE — единый реестр понятных названий инструментов.
   Подключать БЕЗ defer, как можно раньше в <head> (как academy-shared.js —
   см. комментарий в serve.py про "деструктурирует сразу при выполнении"):
   <script src="/assets/sbf-symbols.js"></script>.
   Данные — /data/symbols.json (см. SPEC_symbol_names.md §3). Один источник
   истины и для фронта (этот файл), и для бэкенда (core/symbols.py).

   Загрузка СИНХРОННАЯ (XHR, не fetch) намеренно: инлайновые синхронные
   <script>-блоки (главы книги, основной скрипт index.html) выполняются ДО
   любого отложенного (defer) скрипта — с асинхронной загрузкой window.
   SBFSymbols существовал бы, но реестр внутри был бы ещё пуст, и первый
   рендер молча показывал бы сырые тикеры без единой ошибки в консоли (так
   это и проявилось на живой проверке: строка котировок отрисовывалась
   раньше, чем резолвился fetch, и никогда не перерисовывалась). Файл малый
   (~6КБ), тот же источник — задержка не заметна.

   symbolName(sym, {lang, mode}):
     mode 'name'         → «Золото»           (проза, бриф, движения, фигуры)
     mode 'name+ticker'  → «Золото · GOLD»    (шапка графика, журнал, свитчеры)
     mode 'raw'          → «GOLD»             (URL, ключи данных — не для UI)
   Инструмент без имени в реестре возвращает исходный тикер как есть —
   честный фолбэк, а не выдумка (см. §1, категория C и приёмка §6).
   ========================================================================= */
(function () {
  'use strict';

  var REGISTRY = {};         // { CANON: {ru, ro, en, aliases, class} }
  var ALIAS_TO_CANON = {};   // { 'XAUUSD': 'GOLD', ... }, ключи в верхнем регистре

  function buildIndex(reg) {
    var map = {};
    Object.keys(reg).forEach(function (canon) {
      map[canon.toUpperCase()] = canon;
      (reg[canon].aliases || []).forEach(function (a) {
        map[String(a).toUpperCase()] = canon;
      });
    });
    return map;
  }

  (function loadSync() {
    try {
      var xhr = new XMLHttpRequest();
      xhr.open('GET', '/data/symbols.json', false);
      xhr.send(null);
      if (xhr.status === 200 || xhr.status === 0) {
        REGISTRY = JSON.parse(xhr.responseText);
      }
    } catch (e) {
      REGISTRY = {};
    }
    ALIAS_TO_CANON = buildIndex(REGISTRY);
  })();

  function load() { return Promise.resolve(REGISTRY); }

  function canonOf(sym) {
    if (!sym) return null;
    return ALIAS_TO_CANON[String(sym).toUpperCase()] || null;
  }

  function currentLang() {
    return (window.sbfI18n && window.sbfI18n.lang) || 'ru';
  }

  function symbolClass(sym) {
    var canon = canonOf(sym);
    return canon ? REGISTRY[canon].class : null;
  }

  function symbolName(sym, opts) {
    opts = opts || {};
    var mode = opts.mode || 'name';
    if (mode === 'raw' || !sym) return sym;

    var canon = canonOf(sym);
    var entry = canon ? REGISTRY[canon] : null;
    var lang = opts.lang || currentLang();
    var name = entry ? (entry[lang] || entry.ru || sym) : sym;
    var ticker = canon || sym;

    if (mode === 'name+ticker') {
      return name.toUpperCase() === String(ticker).toUpperCase()
        ? name
        : name + ' · ' + ticker;
    }
    return name;
  }

  window.SBFSymbols = {
    load: load,
    ready: load(),
    symbolName: symbolName,
    canonOf: canonOf,
    symbolClass: symbolClass
  };
})();
