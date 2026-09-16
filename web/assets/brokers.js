/* ============================================================================
   brokers.js — /brokers (SPEC_brokers_page_build.md) + BrokerPicker
   встраиваемый в главу 11 (§1: "один источник данных, две поверхности").

   Два источника данных, оба на диске, ни одно число не написано руками:
   - /data/partners.json          — резолв юрлица по стране, коммерческие поля;
   - /data/partners_licences.json — key_finding (офшорный факт), лицензии/реестры
     с уровнем проверки (register/broker_site/unverified).

   Правило показа (жёсткое, из partners.json._meta.rules): партнёр без
   актуального loss_pct у РЕЗОЛВЛЕННОГО для страны пользователя юрлица не
   отображается. Исключение — юрлицо, у которого НЕ ПУБЛИКУЕТСЯ процент
   подтверждено (entity.loss_pct_confirmed_not_published), и у бренда есть
   юрлицо-сосед с реальным числом для раскрытия (кейс XM/NAGA).
   ============================================================================ */
(function (global) {
  'use strict';

  var _i18n = global.sbfI18n || { lang: 'ru', t: function (k, fb) { return fb || k; }, ready: Promise.resolve() };
  function t(key, fb, vars) {
    var s = _i18n.t(key, fb);
    if (vars) {
      Object.keys(vars).forEach(function (k) {
        s = s.split('{{' + k + '}}').join(String(vars[k]));
      });
    }
    return s;
  }

  // ── Страны: минимальный список, EEA/MENA определяют резолв юрлица ─────────
  var EEA = ['AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR', 'DE', 'GR', 'HU', 'IE',
    'IT', 'LV', 'LT', 'LU', 'MT', 'NL', 'PL', 'PT', 'RO', 'SK', 'SI', 'ES', 'SE', 'IS', 'LI', 'NO'];
  var MENA = ['AE', 'SA', 'QA', 'KW', 'BH', 'OM', 'EG', 'JO', 'LB'];
  var EEA_SET = {}; EEA.forEach(function (c) { EEA_SET[c] = true; });
  var MENA_SET = {}; MENA.forEach(function (c) { MENA_SET[c] = true; });

  var COUNTRIES = [
    { code: '', ru: 'Не выбрано', ro: 'Nespecificat', en: 'Not selected' },
    { code: 'MD', ru: 'Молдова', ro: 'Moldova', en: 'Moldova' },
    { code: 'RO', ru: 'Румыния', ro: 'România', en: 'Romania' },
    { code: 'DE', ru: 'Германия', ro: 'Germania', en: 'Germany' },
    { code: 'FR', ru: 'Франция', ro: 'Franța', en: 'France' },
    { code: 'RU', ru: 'Россия', ro: 'Rusia', en: 'Russia' },
    { code: 'UA', ru: 'Украина', ro: 'Ucraina', en: 'Ukraine' },
    { code: 'KZ', ru: 'Казахстан', ro: 'Kazahstan', en: 'Kazakhstan' },
    { code: 'AE', ru: 'ОАЭ', ro: 'EAU', en: 'UAE' },
    { code: 'GB', ru: 'Великобритания', ro: 'Marea Britanie', en: 'United Kingdom' },
    { code: 'ZZ', ru: 'Другая страна', ro: 'Altă țară', en: 'Other country' },
  ];
  // Страна не выбрана -- дефолт зависит от языка страницы, не от одной
  // зашитой страны: EN/RO читатель ориентирован на Европу (юрлицо из
  // entity_resolution.eea), RU -- на СНГ (entity_resolution.md, тот же факт,
  // что раньше был жёстко привязан к литеральной Молдове). См. resolveEntity().
  var DEFAULT_COUNTRY = '';

  // Юрисдикции офшорных юрлиц (key_finding) — короткий фиксированный список,
  // тот же паттерн, что COUNTRIES выше.
  var JURISDICTIONS = {
    BZ: { ru: 'Белиз', ro: 'Belize', en: 'Belize' },
    VG: { ru: 'БВО', ro: 'Insulele Virgine Britanice', en: 'British Virgin Islands' },
    BS: { ru: 'Багамы', ro: 'Bahamas', en: 'Bahamas' },
    SC: { ru: 'Сейшелы', ro: 'Seychelles', en: 'Seychelles' },
  };
  function jurisdictionLabel(code) {
    var j = JURISDICTIONS[code];
    return j ? (j[_i18n.lang] || j.ru) : code;
  }

  function countryLabel(code, lang) {
    var c = COUNTRIES.filter(function (x) { return x.code === code; })[0];
    return c ? (c[lang] || c.ru) : code;
  }

  // Единицы спреда — маленький фиксированный набор слов, зашитых в данных
  // (partners.json) на русском. Переводить целиком partners.json ради трёх
  // слов избыточно, поэтому здесь -- локальная таблица, тот же приём, что
  // JURISDICTIONS выше.
  var UNITS = {
    'пипс': { ru: 'пипс', ro: 'pips', en: 'pips' },
    'пункт': { ru: 'пункт', ro: 'punct', en: 'point' },
    'пункт индекса': { ru: 'пункт индекса', ro: 'punct index', en: 'index point' },
  };
  function unitLabel(u) {
    var m = u && UNITS[u];
    return m ? (m[_i18n.lang] || m.ru) : u;
  }

  // Код модели комиссии (p.commission.model) — техническое слово из данных,
  // не через t()/партнёрский JSON. Единственное встречающееся значение сейчас
  // -- 'per_side' (XM), но таблица на случай появления других моделей.
  var COMMISSION_MODELS = {
    'per_side': { ru: 'за сторону', ro: 'per parte', en: 'per side' },
  };
  function commissionModelLabel(m) {
    var x = m && COMMISSION_MODELS[m];
    return x ? (x[_i18n.lang] || x.ru) : (m || '');
  }

  // ── Партнёрская ссылка с учётом языка ──────────────────────────────────────
  //
  // 🔴 У трёх партнёров из пяти язык ЗАШИТ прямо в партнёрской ссылке:
  //   XM         …/c?c=1258918&l=ru&p=1     — параметр l
  //   FxPro      …/en/register/md/cri/…     — сегмент пути
  //   InstaForex …/en/fast_open_live_account — сегмент пути
  // То есть румын с /ro/brokers и англичанин с /en/brokers уходили на русскую
  // (соответственно английскую) страницу партнёра. Это не косметика: человек
  // дошёл до конца воронки и упёрся в форму на чужом языке.
  //
  // Подставлять язык В КОД я не стал, и это осознанно: коды локалей у каждого
  // партнёра свои, и `l=ro` у XM или `/ro/` у FxPro могут просто не
  // существовать — тогда вместо чужого языка человек получит 404, что хуже.
  // Проверить можно только живым переходом по ссылке, а каждый такой переход
  // засчитывается партнёрке как клик, поэтому это шаг владельца, не мой.
  //
  // Здесь готов МЕХАНИЗМ: если в partners.json у ссылки появится вариант
  // `affiliate_ro` / `affiliate_en`, он будет использован автоматически.
  // До тех пор работает единственная `affiliate` — ровно как раньше.
  function affiliateFor(p) {
    var l = (p && p.links) || {};
    return l['affiliate_' + _i18n.lang] || l.affiliate || '#';
  }

  // Свободный текст в самих данных (leverage_retail, published_specs.commission
  // и т.п.) -- в отличие от единиц, это не закрытый список из пары слов,
  // поэтому перевод живёт РЯДОМ с фактом в самом JSON, как <field>_en/<field>_ro,
  // а не в отдельной таблице здесь. Факт остаётся один (RU), перевод -- его
  // представление, не второй источник правды.
  function loc(obj, key) {
    if (!obj) return undefined;
    if (_i18n.lang === 'en' || _i18n.lang === 'ro') {
      var v = obj[key + '_' + _i18n.lang];
      if (v != null) return v;
    }
    return obj[key];
  }

  // ── Резолв юрлица по стране ────────────────────────────────────────────────
  function resolveEntity(partner, countryCode) {
    var entities = partner.entities || [];
    if (!entities.length) return null;
    if (!countryCode) {
      // Страна не выбрана -- показываем юрлицо, релевантное языку страницы,
      // а не подставляем первое попавшееся по массиву. EN/RO: юрисдикция
      // ЕЭЗ (entity_resolution.eea). RU и остальные: СНГ-профиль
      // (entity_resolution.md — тот же снятый факт, что раньше был
      // единственным дефолтом). Если у брокера нет юрлица в этом бакете
      // (например, у FxPro сейчас нет действующего европейского юрлица) --
      // честно null, а не ближайшее по массиву: это самостоятельная находка,
      // не пробел.
      var bucketKey = (_i18n.lang === 'en' || _i18n.lang === 'ro') ? 'eea' : 'md';
      var wantId = partner.entity_resolution && partner.entity_resolution[bucketKey];
      if (!wantId) return null;
      return entities.filter(function (e) { return e.id === wantId; })[0] || null;
    }
    var key = String(countryCode || '').toLowerCase();
    if (partner.entity_resolution && partner.entity_resolution[key]) {
      var wantId = partner.entity_resolution[key];
      var hit = entities.filter(function (e) { return e.id === wantId; })[0];
      if (hit) return hit;
    }
    var inEEA = !!EEA_SET[countryCode], inMENA = !!MENA_SET[countryCode];
    for (var i = 0; i < entities.length; i++) {
      var e = entities[i];
      if (e.excludes && e.excludes.indexOf(countryCode) !== -1) continue;
      if (e.serves === 'EEA' && !inEEA) continue;
      if (e.serves === 'MENA' && !inMENA) continue;
      if (e.show_in_eu_locales === false && inEEA) continue;
      return e;
    }
    return null; // ни одно юрлицо не обслуживает эту страну -- честно не резолвится
  }

  // ── Достоверность процента теряющих для отображения ────────────────────────
  function lossInfo(partner, entity) {
    if (entity && typeof entity.loss_pct === 'number') {
      return { kind: 'value', value: entity.loss_pct, checked: entity.loss_pct_checked, source: entity.loss_pct_source };
    }
    if (entity && entity.loss_pct_confirmed_not_published) {
      var sibling = (partner.entities || []).filter(function (e) { return typeof e.loss_pct === 'number'; })[0];
      return { kind: 'not_published', disclose: sibling || null };
    }
    if (typeof partner.loss_pct === 'number') {
      return { kind: 'value', value: partner.loss_pct, checked: partner.loss_pct_checked, source: partner.loss_pct_source };
    }
    // Подтверждение "не публикуется" на уровне БРЕНДА. Раньше проверялся только
    // уровень entity — из-за этого FxPro (partners.json: eea:null + бренд с
    // loss_pct_confirmed_not_published) молча выпадал из таблицы на /en/ и /ro/,
    // хотя partners.json._meta.rules требует показывать при подтверждении на
    // ЛЮБОМ уровне. Найдено аудитом 14.08.2026 (RU 5 строк / EN 4 строки).
    if (partner.loss_pct_confirmed_not_published) {
      var sib = (partner.entities || []).filter(function (e) { return typeof e.loss_pct === 'number'; })[0];
      return { kind: 'not_published', disclose: sib || null };
    }
    return null;
  }

  // ── Трекинг конверсий ──────────────────────────────────────────────────────
  // На сайте нет ни GA4, ни Метрики, ни пикселя (аудит 14.08.2026) — клики по
  // партнёрским ссылкам не считались нигде. Хук ниже безопасен при полном
  // отсутствии аналитики и начнёт отдавать события в тот момент, когда любой
  // из счётчиков будет подключён. Ничего не изобретает и никуда не ходит сам.
  function track(event, params) {
    params = params || {};
    try { if (global.sbfTrack) global.sbfTrack(event, params); } catch (e) { console.warn('[brokers] sbfTrack', e); }
    try { if (global.dataLayer && global.dataLayer.push) global.dataLayer.push(Object.assign({ event: event }, params)); } catch (e) { console.warn('[brokers] dataLayer', e); }
    try { if (typeof global.gtag === 'function') global.gtag('event', event, params); } catch (e) { console.warn('[brokers] gtag', e); }
    try { if (typeof global.ym === 'function' && global.sbfYmId) global.ym(global.sbfYmId, 'reachGoal', event, params); } catch (e) { console.warn('[brokers] ym', e); }
    try { if (typeof global.fbq === 'function') global.fbq('trackCustom', event, params); } catch (e) { console.warn('[brokers] fbq', e); }
  }

  function isStale(dateStr) {
    if (!dateStr) return false;
    var d = new Date(dateStr + 'T00:00:00Z');
    if (isNaN(d)) return false;
    return (Date.now() - d.getTime()) > 90 * 86400000;
  }

  // ── Загрузка данных ────────────────────────────────────────────────────────
  var _dataPromise = null;
  function loadData() {
    if (!_dataPromise) {
      _dataPromise = fetch('/data/partners.json?t=' + Date.now()).then(function (r) {
        if (!r.ok) throw new Error('partners.json HTTP ' + r.status);
        return r.json();
      });
    }
    return _dataPromise;
  }

  var _licencesPromise = null;
  function loadLicences() {
    if (!_licencesPromise) {
      _licencesPromise = fetch('/data/partners_licences.json?t=' + Date.now()).then(function (r) {
        if (!r.ok) throw new Error('partners_licences.json HTTP ' + r.status);
        return r.json();
      }).catch(function (err) {
        console.error('[brokers] licences load failed', err);
        return { partners: {}, key_finding: null };
      });
    }
    return _licencesPromise;
  }
  var _licencesData = null; // module-level, установлен при монтировании

  function groupOf(data, partnerId) {
    return (data.groups || []).filter(function (g) { return (g.members || []).indexOf(partnerId) !== -1; })[0] || null;
  }

  // ── Лицензия конкретного юрлица из partners_licences.json ──────────────────
  // Поля проверки в источнике названы непоследовательно (verification,
  // verification_licence_no, verification_licence, verification_entity) —
  // берём самое специфичное для НОМЕРА лицензии, иначе общее, иначе unverified.
  function licenceEntityFor(partnerId, entityId) {
    if (!_licencesData || !entityId) return null;
    var lp = _licencesData.partners && _licencesData.partners[partnerId];
    if (!lp || !lp.entities) return null;
    var raw = lp.entities.filter(function (x) { return x.id === entityId; })[0];
    if (!raw) return null;
    return {
      licence_no: raw.licence_no || null,
      licence_verification: raw.verification_licence_no || raw.verification_licence || raw.verification || 'unverified',
      register_url: raw.register_url || raw.register_url_company || null,
    };
  }

  // ── Построение отображаемых строк для страны ───────────────────────────────
  function buildRows(data, countryCode) {
    var rows = [];
    (data.partners || []).forEach(function (p) {
      if (p.enabled === false) return;
      var entity = resolveEntity(p, countryCode);
      var loss = lossInfo(p, entity);
      if (!loss) return; // жёсткое правило: без числа -- не показываем
      rows.push({ partner: p, entity: entity, loss: loss, group: groupOf(data, p.id) });
    });
    rows.sort(function (a, b) {
      var av = a.loss.kind === 'value' ? a.loss.value : Infinity;
      var bv = b.loss.kind === 'value' ? b.loss.value : Infinity;
      return av - bv;
    });
    return rows;
  }

  // ── Форматирование ──────────────────────────────────────────────────────────
  function fmtPct(n) { return (Math.round(n * 100) / 100).toString().replace('.', _i18n.lang === 'en' ? '.' : ','); }

  function sourceLink(url, label) {
    if (!url) return '';
    return '<a href="' + url + '" target="_blank" rel="noopener" class="src-link">' + (label || t('brokers.source_link', 'источник')) + '</a>';
  }

  function dateBadge(dateStr) {
    if (!dateStr) return '';
    var stale = isStale(dateStr);
    return '<span class="date-badge' + (stale ? ' stale' : '') + '" title="' +
      (stale ? t('brokers.stale_note', 'Данные старше 90 дней') : t('brokers.checked_note', 'Дата проверки')) +
      '">' + (stale ? '⚠ ' : '') + dateStr + '</span>';
  }

  // ── Ранг регулятора ────────────────────────────────────────────────────────
  // Порядок вывода лицензий: сильнейшая первой (решение владельца 14.08.2026).
  // «Сильнее» здесь означает объём защиты розничного клиента, а не престиж:
  // потолок плеча, обязательная защита от отрицательного баланса,
  // компенсационный фонд, читаемый публичный реестр. Отсюда tier 3 — режимы
  // ESMA-типа и равные им, tier 2 — числовой потолок есть, фонда нет,
  // tier 1 — потолка нет вовсе, tier 0 — регулятора нет.
  var REGULATOR_TIER = [
    { re: /FCA|Financial Conduct/i, tier: 3 },
    { re: /Central Bank of Ireland/i, tier: 3 },
    { re: /CySEC/i, tier: 3 },
    { re: /DFSA/i, tier: 3 },
    { re: /FSRA/i, tier: 3 },
    { re: /ASIC/i, tier: 3 },
    { re: /Securities Commission of The Bahamas/i, tier: 2 },
    { re: /Capital Markets Authority/i, tier: 2 },
    { re: /FSA \/ FFAJ|FFAJ/i, tier: 2 },
    { re: /Seychelles/i, tier: 1 },
    { re: /BVI|British Virgin/i, tier: 1 },
    { re: /Belize/i, tier: 1 },
  ];
  function regulatorTier(regulator) {
    if (!regulator) return 0;
    for (var i = 0; i < REGULATOR_TIER.length; i++) {
      if (REGULATOR_TIER[i].re.test(regulator)) return REGULATOR_TIER[i].tier;
    }
    return 1;
  }
  function licenceRank(ent) {
    var v = ent.verification_licence_no || ent.verification_licence || ent.verification;
    return v === 'register' ? 2 : v === 'broker_site' ? 1 : 0;
  }
  // MiFID II — только юрлица под надзором регулятора государства-члена ЕС.
  // Великобритания сюда НЕ входит: после выхода из ЕС FCA применяет свой
  // эквивалентный режим, называть его MiFID II неверно.
  var MIFID_JURISDICTIONS = { CY: 1, IE: 1, DE: 1, FR: 1, MT: 1, NL: 1, LU: 1, BG: 1, EE: 1, LV: 1, LT: 1, PL: 1, CZ: 1, SK: 1, SI: 1, HR: 1, RO: 1, GR: 1, IT: 1, ES: 1, PT: 1, AT: 1, BE: 1, DK: 1, FI: 1, SE: 1, HU: 1 };
  function isMifid(ent) {
    return !!(ent && ent.jurisdiction && MIFID_JURISDICTIONS[ent.jurisdiction]);
  }

  // excludes в данных заполнено непоследовательно: у xm_global это массив
  // ["US","CA","IL","IR"], у naga_markets_europe — строка «третьи страны —
  // услуг не оказывает». Прямой .join() на строке роняет обработчик: именно
  // из-за этого 14.08.2026 не открывалась модалка CySEC 204/13, при том что
  // соседние в том же списке работали. Нормализуем оба вида, а не чиним
  // данные под код — строка здесь осмысленна и переписывать её в массив
  // значило бы потерять формулировку.
  function excludesText(ent) {
    if (!ent) return '';
    // Готовый человеческий список названий, если он есть в данных: строка
    // «не обслуживает: US, CA, IL, IR» читателю мало что говорит, коды стран
    // на витрине выглядят как служебное поле (замечание владельца 14.08.2026).
    var named = loc(ent, 'excludes_names');
    if (named) return String(named);
    var ex = ent.excludes;
    if (!ex) return '';
    if (Array.isArray(ex)) return ex.length ? ex.join(', ') : '';
    return String(ex);
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // "Компенсация"/comp, "% теряющих"/loss, "Демо без верификации"/demo и
  // "Защита от отриц. баланса"/nbp убраны из основной таблицы и карточки по
  // прямому запросу -- поля по-прежнему считаются в buildFieldHtml() (нужны
  // COMPACT_COLS/BrokerPicker в главе 11, который loss использует как жёсткий
  // фильтр), просто не попадают в порядок рендера главной страницы.
  // 'loss' убран из рендера повторно 14.08.2026 по решению владельца.
  // ВАЖНО: вместе с колонкой переписан и текст brokers.risk_warning_full —
  // прежняя редакция обещала, что процент теряющих счетов "указан в таблице
  // для каждого провайдера отдельно". Без колонки это было письменным
  // обещанием раскрытия, которого на странице нет. Если колонку когда-нибудь
  // вернут — вернуть и прежнюю формулировку предупреждения, они парные.
  // Колонка 'entity' убрана 14.08.2026: после того как в 'licence' стали
  // выводиться ВСЕ юрлица с регулятором, номером, реестром и названием,
  // две колонки печатали один и тот же список — у FxPro это выглядело как
  // «FxPro UK Limited указан дважды», что владелец и заметил. Юрлицо,
  // подписывающее договор с читателем, осталось в шапке карточки.
  var FULL_COLS = ['name', 'licence', 'leverage', 'spread', 'commission', 'mindep', 'platforms'];
  var COMPACT_COLS = ['name', 'entity', 'loss', 'leverage'];
  var SORTABLE_COLS = ['name', 'leverage', 'commission', 'mindep', 'platforms']; // спред -- НИКОГДА (§5: разные размеры лота, сравнение в пунктах даёт 10-кратную ошибку)

  // Логотипы партнёров (файлы взяты из проекта sbf-nexus, assets/partners/)
  // 2026-08-06. Имя брокера остаётся в alt/title для скринридеров и на случай
  // если картинка не загрузится.
  var LOGOS = {
    xm: '/assets/logos/xm.svg',
    avatrade: '/assets/logos/avatrade.svg',
    fxpro: '/assets/logos/fxpro.svg',
    naga: '/assets/logos/naga.png',
    instaforex: '/assets/logos/instaforex.svg'
  };
  // Инлайн-размер, а не только CSS-класс: этот же nameHtml() используется
  // и в BrokerPicker (main.js -> ch11.js/ch14.js), у которых нет собственной
  // стилизации .broker-logo -- без явного размера часть логотипов (InstaForex,
  // NAGA) раздулась бы до исходных сотен пикселей и сломала бы вёрстку главы.
  function nameHtml(p) {
    var logo = LOGOS[p.id];
    return logo
      ? '<img class="broker-logo" src="' + escapeHtml(logo) + '" alt="' + escapeHtml(p.name) + '" title="' + escapeHtml(p.name) + '" style="display:block;height:22px;width:auto;max-width:100px;object-fit:contain">'
      : escapeHtml(p.name);
  }

  // Ссылки на другие страницы сайта должны сохранять текущий язык (/en/,
  // /ro/) -- иначе переход с англ./рум. страницы всегда сбрасывает в RU.
  // См. тот же приём в serve.py::_edu_inject (_book_lang_seg).
  function langPrefix() {
    return (_i18n.lang === 'en' || _i18n.lang === 'ro') ? '/' + _i18n.lang : '';
  }

  // Инструкции по регистрации со скриншотами (SPEC_broker_guides_screenshots.md,
  // 2026-08-06). Список литеральный: пополнение/верификация и AvaTrade ещё
  // не сняты, ссылка появляется только там, где инструкция реально существует.
  var GUIDES = { xm: 1, naga: 1, fxpro: 1, instaforex: 1, avatrade: 1 };
  function guideLinkHtml(p) {
    return GUIDES[p.id]
      ? '<a class="guide-link" href="' + langPrefix() + '/brokers/' + p.id + '">' + t('brokers.guide_link', 'инструкция →') + '</a>'
      : '';
  }

  function colLabel(col) {
    var map = {
      name: t('brokers.col_name', 'Брокер'),
      entity: t('brokers.col_entity', 'Юрлицо и регулятор'),
      licence: t('brokers.col_licence', 'Лицензия'),
      // Ключ намеренно НОВЫЙ, а не старый col_leverage: словарь i18n кэшируется
      // в процессе сервера (core/i18n.py:26), и до рестарта старый ключ будет
      // отдавать «Плечо для тебя», сколько его в JSON ни правь. Нового ключа
      // в кэше нет — сработает fallback ниже, то есть правильная подпись
      // появится сразу, а после рестарта подтянется перевод для ro/en.
      leverage: t('brokers.col_leverage_short', 'Плечо'),
      spread: t('brokers.col_spread', 'Спред'),
      commission: t('brokers.col_commission', 'Комиссия'),
      loss: t('brokers.col_loss', '% теряющих'),
      comp: t('brokers.col_comp', 'Защита при банкротстве'),
      nbp: t('brokers.col_nbp', 'Защита от отриц. баланса'),
      mindep: t('brokers.col_mindep', 'Мин. депозит'),
      platforms: t('brokers.col_platforms', 'Платформы'),
      restrictions: t('brokers.col_restrictions', 'Кого обслуживает'),
      inactivity: t('brokers.col_inactivity', 'Плата за неактивность'),
      demo: t('brokers.col_demo', 'Демо без верификации'),
    };
    return map[col] || col;
  }

  // ── Значения полей одной строки (общие и для <td>, и для мобильной карточки) ─
  function buildFieldHtml(row) {
    var p = row.partner, e = row.entity, loss = row.loss;
    var lic = licenceEntityFor(p.id, e ? e.id : null);
    var dash = '<span class="no-data">' + t('brokers.no_data', '—') + '</span>';

    var f = {};

    // Юрлицо и регулятор + ссылка на реестр (partners_licences.json.register_url
    // ведёт ТОЛЬКО на реестр регулятора, никогда на сайт брокера -- см. _meta.rules).
    // По договорённости с владельцем: показываем ВСЕ юрлица бренда всегда, не
    // только резолвленное для страны/языка -- прятать остальные значило бы
    // повторить ошибку партнёрских сайтов и WikiFX (§1 СПЕКА_таблица_сравнения),
    // просто в другую сторону. resolveEntity() по-прежнему решает, какое из них
    // твоё (страна выбрана явно, или язык страницы как дефолт-бакет) -- но это
    // теперь подсветка одной строки списка, а не фильтр, скрывающий остальные.
    if (p.entities && p.entities.length) {
      f.entity = p.entities.map(function (ent) {
        var entLic = licenceEntityFor(p.id, ent.id);
        var active = e && ent.id === e.id;
        return '<div class="entity-item' + (active ? ' entity-active' : '') + '">' +
          (active ? '<span class="entity-badge">' + t('brokers.entity_yours', 'ваш контрагент') + '</span>' : '') +
          escapeHtml(ent.legal_name || '—') +
          (ent.regulator ? '<div class="entity-sub">' + escapeHtml(ent.regulator) + '</div>' : '') +
          (entLic && entLic.register_url ? sourceLink(entLic.register_url, t('brokers.register_link', 'реестр')) : '') +
          '</div>';
      }).join('');
    } else {
      f.entity = dash;
    }

    // Лицензии: ВСЕ лицензии бренда, не только у резолвленного юрлица
    // (решение владельца 14.08.2026). Раньше показывалась одна, и уровень
    // unverified не показывался вовсе — из-за этого у AvaTrade и NAGA колонка
    // была прочерком при непустых данных в partners_licences.json.
    // Уровень проверки теперь не фильтр, а подпись: скрывать номер и скрывать
    // то, что он не подтверждён, — разные вещи, и вторая честнее.
    // Источник списка — partners_licences.json (полный набор юрлиц бренда: у
    // AvaTrade их 7, у XM 3), а не partners.json (там только те, что участвуют
    // в резолве по стране, — у AvaTrade 2). Если файла лицензий нет вовсе,
    // откатываемся на partners.json, чтобы колонка не опустела.
    // Сильнейшая лицензия первой (решение владельца 14.08.2026): у FxPro это
    // FCA, у AvaTrade — Центральный банк Ирландии. Раньше порядок был как в
    // файле, и наверху могло оказаться офшорное юрлицо.
    var licList = licencesOf(p);
    if (licList.length) {
      f.licence = licList.map(function (ent) {
        var no = ent.licence_no || null;
        var ver = ent.verification_licence_no || ent.verification_licence || ent.verification || (no ? 'broker_site' : null);
        // Реестр КОМПАНИЙ и реестр ЛИЦЕНЗИЙ — разные вещи, и смешивать их
        // нельзя: у FxPro UK Companies House подтверждает компанию 06925128,
        // но номер FRN 509956 там не проверяется вовсе (реестр FCA — приложение
        // на Salesforce, машинно не читается). До 14.08.2026 ссылка на
        // Companies House стояла с подписью «реестр» рядом с пометкой
        // «не подтверждена ни реестром, ни сайтом брокера» — прямое
        // противоречие на одной строке, замечено владельцем.
        var licUrl = ent.register_url || null;
        var coUrl = ent.register_url_company || null;
        var isActive = e && ent.id === e.id;
        var body = no
          ? '<span class="lic-no">' + escapeHtml(no) + '</span>'
          : '<span class="no-data">' + t('brokers.licence_no_number', 'номер не публикуется') + '</span>';
        var note = '';
        if (no && ver === 'broker_site') {
          // Две разные причины, и они не взаимозаменяемы: «реестр номер не
          // печатает» — проверенный факт (БВО, Сейшелы, Багамы так и делают),
          // а «мы реестр не читали» — наше незнание. До 14.08.2026 обе
          // подписывались первой формулировкой, то есть мы утверждали за
          // регулятора то, чего не проверяли (кейс Invemonde, SD120).
          var known = /не публикует|не печата/i.test(String(ent.register_note || ''));
          note = '<div class="licence-note">' + (known
            ? t('brokers.licence_broker_site_note', 'по данным брокера — в реестре номер не публикуется')
            : t('brokers.licence_broker_site_unchecked', 'номер — по данным брокера, по реестру регулятора не сверялся')) + '</div>';
        } else if (no && ver === 'unverified' && coUrl) {
          note = '<div class="licence-note">' + t('brokers.licence_company_only_note', 'компания подтверждена в реестре компаний; номер лицензии — по данным брокера, реестр регулятора машинно не читается') + '</div>';
        } else if (no && ver === 'unverified') {
          note = '<div class="licence-note licence-unverified">' + t('brokers.licence_unverified_note', 'не подтверждена ни реестром, ни сайтом брокера') + '</div>';
        }
        var url = licUrl || coUrl;
        var urlLabel = licUrl
          ? t('brokers.register_link', 'реестр')
          : t('brokers.register_company_link', 'реестр компаний');
        // public_note — предупреждение ЧИТАТЕЛЮ, что лицензия покрывает не то,
        // ради чего он сюда пришёл (кейс DT Direct у AvaTrade: разрешены приём
        // поручений и консультирование, но не сделки за свой счёт). Показывать
        // номер и молчать про это хуже, чем не показывать номер.
        // Поле ent.caution СОЗНАТЕЛЬНО не рендерится: это внутренняя
        // редакционная инструкция («НЕ ВЫДАВАТЬ ЗА...»), написанная нам, а не
        // читателю — 14.08.2026 она успела уйти на живую страницу, исправлено.
        var pn = loc(ent, 'public_note');
        if (pn) note += '<div class="licence-note licence-unverified">' + escapeHtml(pn) + '</div>';
        return '<div class="lic-item' + (isActive ? ' lic-active' : '') + '">' +
          (isActive ? '<span class="entity-badge">' + t('brokers.entity_yours', 'ваш контрагент') + '</span>' : '') +
          '<span class="lic-reg">' + escapeHtml(ent.regulator || t('brokers.no_regulator', 'регулятор не назван')) + '</span> ' + body +
          (url ? ' ' + sourceLink(url, urlLabel) : '') +
          '<div class="entity-sub">' + escapeHtml(ent.legal_name || '') +
            (isMifid(ent) ? ' · <span class="mifid-tag">' + t('brokers.mifid_tag', 'по правилам MiFID II') + '</span>' : '') +
          '</div>' +
          note + '</div>';
      }).join('');
    } else {
      f.licence = dash;
    }

    // % теряющих
    if (loss.kind === 'value') {
      f.loss = '<b class="loss-val">' + fmtPct(loss.value) + '%</b> ' + dateBadge(loss.checked) + ' ' + sourceLink(loss.source);
    } else {
      var d = loss.disclose;
      f.loss = '<span class="loss-np">' + t('brokers.loss_pct_not_published', 'не публикуется') + '</span>';
      if (d) {
        f.loss += '<div class="loss-disclose">' + t('brokers.loss_pct_disclosure_tpl',
          'У юрлица {{entity}} — {{pct}}%, но другое плечо ({{lev}}) и {{fund}}', {
            entity: d.legal_name, pct: fmtPct(d.loss_pct),
            lev: d.leverage_retail || '—',
            fund: d.compensation_scheme ? (d.compensation_scheme.amount + ' ' + d.compensation_scheme.currency) : t('brokers.no_fund', 'нет компенсационного фонда'),
          }) + '</div>';
      }
    }

    // Плечо. Сначала — значение ЮРЛИЦА, которое достаётся именно этой стране:
    // это единственная честная цифра, потому что потолок задаётся юрисдикцией.
    // Если у юрлица не заполнено — берём то, что брокер заявляет о себе на
    // сайте (partner.leverage_retail), с подписью "по данным брокера".
    // Значения стали длинными (разбивка по классам активов, снято 14.08.2026):
    // первый сегмент до "·" — крупно, остальные ступени — строкой помельче,
    // иначе плитка в карточке превращается в абзац.
    function leverageHtml(raw, note) {
      var parts = String(raw).split(' · ');
      var head = escapeHtml(parts.shift());
      return head +
        (parts.length ? '<div class="leverage-hint">' + escapeHtml(parts.join(' · ')) + '</div>' : '') +
        (note ? '<div class="spread-src">' + note + '</div>' : '');
    }
    if (e && e.leverage_retail) {
      f.leverage = leverageHtml(loc(e, 'leverage_retail'), t('brokers.spread_by_broker', 'по данным брокера'));
    } else if (p.leverage_retail && p.leverage_retail.value) {
      f.leverage = leverageHtml(loc(p.leverage_retail, 'value'), t('brokers.spread_by_broker', 'по данным брокера'));
    } else {
      f.leverage = dash;
    }

    f.comp = e && e.compensation_scheme && e.compensation_scheme.amount
      ? escapeHtml(e.compensation_scheme.name || '') + ' — ' + e.compensation_scheme.amount + ' ' + (e.compensation_scheme.currency || '')
      : (e && e.compensation_scheme === null ? '<span class="loss-np">' + t('brokers.no_fund', 'нет компенсационного фонда') + '</span>' : dash);

    // Защита от отрицательного баланса: сначала юрлицо, потом заявление
    // брокера о себе. Красный флаг ставим только на явное "нет".
    var nbpVal = (e && e.negative_balance_protection != null)
      ? e.negative_balance_protection
      : (p.negative_balance_protection != null ? p.negative_balance_protection : null);
    if (nbpVal === true) f.nbp = t('brokers.yes', 'да');
    else if (nbpVal === false) f.nbp = '<span class="nbp-warn">🔴 ' + t('brokers.no', 'нет') + '</span>';
    else f.nbp = dash;

    // Спред. Правило пересмотрено 2026-08-06 (partners.json → _meta.source_priority):
    // основой стали цифры, опубликованные самим брокером. Показываем ИМЕННО их,
    // с явной подписью "по данным брокера" -- читатель должен видеть, что это
    // заявление площадки, а не наше измерение.
    // spread_probe (контрольный снимок вне окон методички) НЕ показываем никогда.
    // Колонка по-прежнему НЕ сортируется (SORTABLE_COLS): размеры лота у партнёров
    // разные, сравнение в пунктах даёт десятикратную ошибку -- см. §5 методички.
    (function () {
      var sp = p.spreads_published;
      if (!sp) {
        f.spread = '<span class="no-data">' + t('brokers.spread_not_published', 'брокер не публикует') + '</span>';
        return;
      }
      // Источники в порядке приоритета: per_instrument (снято постранично,
      // не завязано на живой тикер) -> items (живая лента, но только если
      // render !== false -- у части брокеров она расходится с реальным счётом,
      // см. FxPro) -> sample_rows (алфавитная выгрузка таблицы условий, ещё
      // не покрывает EURUSD у части брокеров, но данные настоящие).
      var items = null;
      if (sp.per_instrument && sp.per_instrument.items && sp.per_instrument.items.length) {
        items = sp.per_instrument.items.map(function (i) {
          return { symbol: i.symbol, val: (i.spread_observed != null) ? i.spread_observed : i.spread, unit: i.unit };
        });
      } else if (sp.render !== false && sp.items && sp.items.length) {
        items = sp.items.map(function (i) {
          return { symbol: i.symbol, val: (i.avg != null) ? i.avg : i.spread, unit: i.unit || sp.unit, checked: i.checked };
        });
      } else if (sp.sample_rows && sp.sample_rows.length) {
        items = sp.sample_rows.map(function (i) {
          return { symbol: i.symbol, val: (i.avg != null) ? i.avg : i.spread, unit: i.unit || 'пипс', checked: i.checked };
        });
      }
      if (!items || !items.length) {
        f.spread = '<span class="no-data">' + t('brokers.spread_not_published', 'брокер не публикует') + '</span>';
        return;
      }
      var base = items.filter(function (i) { return i.symbol === 'EURUSD'; })[0] || items[0];
      var val = base.val;
      if (val == null) {
        f.spread = '<span class="no-data">' + t('brokers.spread_not_published', 'брокер не публикует') + '</span>';
        return;
      }
      var unit = unitLabel(base.unit || sp.unit || '');
      // Если EURUSD у брокера ещё не снят, в ячейку попадает первый доступный
      // инструмент — у NAGA это AUDUSD. Молча ставить его рядом с EURUSD
      // остальных нельзя: колонка читается как сравнение одного и того же.
      // Замечено владельцем 14.08.2026.
      var isBase = base.symbol === 'EURUSD';
      f.spread = escapeHtml(base.symbol) + ' ' + escapeHtml(String(val)) + (unit ? ' ' + escapeHtml(unit) : '') +
        (isBase ? '' : '<div class="spread-src spread-other">' +
          t('brokers.spread_other_symbol', 'EURUSD у этого брокера ещё не снят — показан другой инструмент, с остальными в этой колонке не сравнивать') + '</div>') +
        // Дата — конкретной строки, если она у неё своя (у NAGA EURUSD снят
        // 14.08, а блок целиком помечен 06.08), иначе блока.
        '<div class="spread-src">' + t('brokers.spread_by_broker', 'по данным брокера') +
        ((base.checked || sp.checked) ? ', ' + escapeHtml(base.checked || sp.checked) : '') + '</div>';
    })();

    // Комиссия. Сначала наше подтверждённое числовое поле, затем — то, что
    // брокер публикует сам (published_specs.commission), с той же подписью
    // "по данным брокера", что и спред. Пусто остаётся пустым: ноль не
    // додумываем, отсутствие комиссии по спецификации ещё не факт (§4).
    if (p.commission && p.commission.value != null) {
      f.commission = escapeHtml(commissionModelLabel(p.commission.model)) + ' ' + p.commission.value + ' ' + (p.commission.currency || '') +
        (p.commission.per_volume ? ' / ' + p.commission.per_volume : '');
    } else if (p.published_specs && p.published_specs.commission && p.published_specs.commission.value != null) {
      var pc = String(loc(p.published_specs.commission, 'value'));
      f.commission = escapeHtml(pc.length > 90 ? pc.slice(0, 88) + '…' : pc) +
        '<div class="spread-src">' + t('brokers.spread_by_broker', 'по данным брокера') + '</div>';
    } else {
      f.commission = dash;
    }

    f.mindep = p.min_deposit && p.min_deposit.value != null
      ? p.min_deposit.value + ' ' + (p.min_deposit.currency || '')
      : dash;

    f.platforms = (p.platforms || []).length ? escapeHtml(p.platforms.join(' / ')) : dash;

    // Плата за неактивность. Лежала в данных с самого начала, но на страницу
    // не выводилась вовсе — а это ровно тот расход, который настигает лида,
    // открывшего счёт и не начавшего торговать. У AvaTrade за год простоя
    // набегает 200 USD сборов плюс 100 USD административных. Добавлено
    // 14.08.2026 по замечанию владельца.
    var inact = loc(p, 'inactivity_short');
    f.inactivity = inact ? escapeHtml(String(inact)).split(' · ').join('<br>') : dash;

    // Кого юрлицо обслуживает и кого нет. Раньше поля serves/excludes лежали
    // в данных, но на страницу не выводились вовсе — при том что это первое,
    // что читателю нужно знать перед регистрацией (владелец 14.08.2026:
    // «не работают с США и рядом других юрисдикций с ограничениями»).
    (function () {
      var bits = [];
      if (e && e.serves) bits.push(escapeHtml(String(loc(e, 'serves'))));
      var ex = excludesText(e);
      if (ex) bits.push(t('brokers.excludes_prefix', 'не обслуживает') + ': ' + escapeHtml(ex));
      if (isMifid(e)) bits.push(t('brokers.mifid_full', 'услуги в ЕЭЗ — по правилам MiFID II'));
      f.restrictions = bits.length ? bits.join('<br>') : dash;
    })();

    f.demo = p.demo_requires_verification === true ? t('brokers.no', 'нет')
      : p.demo_requires_verification === false ? t('brokers.yes', 'да')
      : dash;

    return f;
  }

  // ── Рендер одной строки таблицы (используется и полной, и BrokerPicker) ────
  function renderRow(row, opts) {
    opts = opts || {};
    var p = row.partner;
    var f = buildFieldHtml(row);
    var order = (opts.compact ? COMPACT_COLS : FULL_COLS).filter(function (c) { return c !== 'name'; });

    var groupBadge = '';
    if (row.group) {
      var others = row.group.members.filter(function (m) { return m !== p.id; });
      groupBadge = '<div class="group-badge">' + (row.group['label_' + _i18n.lang] || row.group.label_ru) +
        (others.length ? ' · ' + t('brokers.group_same_as', 'та же группа: {{other}}', { other: others.join(', ') }) : '') + '</div>';
    }
    if (groupBadge) f.entity += groupBadge;

    var affLink = escapeHtml(affiliateFor(p));
    var tds = order.map(function (c) { return '<td class="col-' + c + '">' + f[c] + '</td>'; });

    return '<tr data-partner="' + escapeHtml(p.id) + '">' +
      '<td class="col-name"><a href="' + affLink + '" target="_blank" rel="noopener sponsored"' +
      ' data-aff="' + escapeHtml(p.id) + '" data-place="table">' + nameHtml(p) + '</a>' +
      guideLinkHtml(p) + '</td>' +
      tds.join('') + '</tr>';
  }

  // ── Карточка брокера — основная поверхность страницы (desktop + mobile) ────
  // Редизайн 14.08.2026. До этого карточки рисовались только на <=760px и были
  // копией строки таблицы: 7 пар "лейбл ↔ значение" подряд, 440-520px высотой,
  // без единой кнопки — единственным CTA был логотип 22px. Теперь: ключевые
  // цифры вынесены наверх, справочная часть (все юрлица, лицензия, комиссия,
  // платформы) свёрнута в <details>, внизу явная кнопка "Открыть счёт".
  function cardLogoHtml(p) {
    var logo = LOGOS[p.id];
    return logo
      ? '<img class="bcard-logo" src="' + escapeHtml(logo) + '" alt="' + escapeHtml(p.name) + '" width="140" height="30" loading="lazy">'
      : '<span class="bcard-name">' + escapeHtml(p.name) + '</span>';
  }

  // ── Реестр юрлиц для модалок ───────────────────────────────────────────────
  // Модальное окно открывается по ключу "partnerId::entityId" — так в разметку
  // не приходится вклеивать JSON, и данные остаются в одном месте.
  var _entityIndex = {};
  function indexEntities(data) {
    _entityIndex = {};
    (data.partners || []).forEach(function (p) {
      var fromLic = (_licencesData && _licencesData.partners && _licencesData.partners[p.id] && _licencesData.partners[p.id].entities) || [];
      var merged = {};
      (p.entities || []).forEach(function (e) { merged[e.id] = Object.assign({}, e); });
      fromLic.forEach(function (e) { merged[e.id] = Object.assign({}, merged[e.id] || {}, e); });
      Object.keys(merged).forEach(function (id) {
        _entityIndex[p.id + '::' + id] = { partner: p, entity: merged[id] };
      });
    });
  }

  // Список лицензий бренда, сильнейшая первой.
  // ОБЪЕДИНЕНИЕ обоих файлов, а не выбор одного: partners_licences.json полнее
  // по количеству юрлиц (у AvaTrade 7 против 2), но в нём НЕТ юрлиц, заведённых
  // только в partners.json — например fxpro_costa_rica, а это ровно тот
  // контрагент, с которым молдавский читатель и подписывает договор. Пока
  // источником был один файл, он из списка выпадал.
  function licencesOf(p) {
    var fromLic = (_licencesData && _licencesData.partners && _licencesData.partners[p.id] && _licencesData.partners[p.id].entities) || [];
    var merged = [];
    var seen = {};
    fromLic.forEach(function (e) { seen[e.id] = 1; merged.push(e); });
    (p.entities || []).forEach(function (e) { if (!seen[e.id]) merged.push(e); });
    return merged.sort(function (a, b) {
      var d = regulatorTier(b.regulator) - regulatorTier(a.regulator);
      return d ? d : licenceRank(b) - licenceRank(a);
    });
  }

  // Кликабельная плашка лицензии. Номер и юрлицо остаются на виду, всё
  // остальное (юрисдикция, дата выдачи, уровень проверки, ссылка на реестр,
  // ограничения) уезжает в модалку — чтобы карточка не превращалась в справку.
  function licenceChip(p, ent, opts) {
    opts = opts || {};
    var no = ent.licence_no ? escapeHtml(ent.licence_no) : '';
    return '<button type="button" class="lic-chip' + (opts.lead ? ' lic-chip-lead' : '') + '"' +
      ' data-entity="' + escapeHtml(p.id + '::' + ent.id) + '">' +
      '<span class="lic-chip-reg">' + escapeHtml(ent.regulator || t('brokers.no_regulator', 'регулятор не назван')) + '</span>' +
      (no ? '<span class="lic-chip-no">' + no + '</span>' : '') +
      '<span class="lic-chip-more" aria-hidden="true">i</span>' +
      '</button>' +
      '<div class="lic-chip-entity">' + escapeHtml(ent.legal_name || '') +
        (isMifid(ent) ? ' · <span class="mifid-tag">' + t('brokers.mifid_tag', 'по правилам MiFID II') + '</span>' : '') +
      '</div>';
  }

  function statHtml(key, valueHtml, extraClass) {
    return '<div class="bstat ' + (extraClass || '') + '">' +
      '<div class="bstat-k">' + colLabel(key) + '</div>' +
      '<div class="bstat-v' + (key === 'loss' || key === 'mindep' ? '' : ' text') + '">' + valueHtml + '</div>' +
      '</div>';
  }

  // Плитка со ссылкой «подробнее» — значение короткое, остальное в модалке.
  // Владелец 14.08.2026: «у Инстафорекс слишком много инфы в этой графе... если
  // есть необходимость добавить больше инфы, её мы запихиваем в модальное окно,
  // чтобы не перегружать интерфейс».
  function statWithModal(key, headHtml, modalKey, extraClass) {
    return '<div class="bstat ' + (extraClass || '') + '">' +
      '<div class="bstat-k">' + colLabel(key) + '</div>' +
      '<div class="bstat-v text">' + headHtml + '</div>' +
      '<button type="button" class="bstat-more" data-modal="' + escapeHtml(modalKey) + '">' +
      t('brokers.details_link', 'подробнее') + '</button>' +
      '</div>';
  }

  function renderCard(row) {
    var p = row.partner;
    var f = buildFieldHtml(row);
    var affLink = escapeHtml(affiliateFor(p));
    var lics = licencesOf(p);
    var lead = lics[0];

    // Плечо: в плитке короткий диапазон «от 1:X до 1:Y» (поле leverage_short
    // в данных — написано вручную, а не выведено регуляркой из свободного
    // текста), вся разбивка по классам активов — в модалке.
    var levRaw = (row.entity && row.entity.leverage_retail)
      ? String(loc(row.entity, 'leverage_retail'))
      : ((p.leverage_retail && p.leverage_retail.value) ? String(loc(p.leverage_retail, 'value')) : null);
    var levShort = row.entity ? loc(row.entity, 'leverage_short') : null;
    var levHead = levShort ? escapeHtml(String(levShort))
      : (levRaw ? escapeHtml(levRaw.split(' · ')[0]) : f.leverage);
    var levStat = (levRaw && row.entity)
      ? statWithModal('leverage', levHead, 'lev::' + p.id + '::' + row.entity.id)
      : statHtml('leverage', levHead);

    // Комиссия у FxPro и InstaForex — абзац на несколько строк. В плитке
    // оставляем первую фразу, полный текст в модалке (та же логика, что
    // с плечом; владелец: «не перегружать интерфейс»).
    // Комиссия: короткий диапазон «от X до Y» из commission_short, полный
    // текст брокера — в модалке. Обрезки по количеству символов больше нет:
    // «Standard — нет. Raw+ и Elite — $3,5 за ло…» ничего не сообщала, кроме
    // того, что текст не поместился.
    var commShort = loc(p, 'commission_short');
    var commStat = commShort
      ? statWithModal('commission', escapeHtml(String(commShort)), 'comm::' + p.id)
      : statHtml('commission', f.commission);

    var stats =
      statHtml('mindep', f.mindep) +
      levStat +
      statHtml('spread', f.spread) +
      commStat;

    return '<article class="bcard" data-partner="' + escapeHtml(p.id) + '">' +
      '<div class="bcard-top">' + cardLogoHtml(p) +
        (row.group ? '<span class="bcard-group">' + escapeHtml(row.group['label_' + _i18n.lang] || row.group.label_ru) + '</span>' : '') +
      '</div>' +
      // Под логотипом — сильнейшая лицензия бренда, кликабельная (решение
      // владельца 14.08.2026). Кто именно подписывает договор с читателем —
      // внутри модалки, отдельной строкой.
      (lead ? '<div class="bcard-lead">' + licenceChip(p, lead, { lead: true }) + '</div>' : '') +
      '<div class="bcard-stats">' + stats + '</div>' +
      // Раньше <details> разворачивался внутри карточки — список лицензий
      // разной длины у разных брокеров разъезжал высоту карточек в сетке
      // между собой. Теперь кнопка открывает модалку (та же allLicencesModalHtml,
      // что бы использовалась под <details>, просто в bindModalTriggers).
      '<button type="button" class="bcard-more-btn" data-modal="' + escapeHtml('all::' + p.id) + '">' +
      t('brokers.card_details', 'Все юрлица, лицензии и платформы') + '</button>' +
      '<div class="bcard-cta">' +
        '<a class="btn-open" href="' + affLink + '" target="_blank" rel="noopener sponsored"' +
        ' data-aff="' + escapeHtml(p.id) + '" data-place="card">' +
        t('brokers.cta_open', 'Открыть счёт') + ' ' + escapeHtml(p.name) + ' →</a>' +
        (GUIDES[p.id] ? '<a class="guide-link" href="' + langPrefix() + '/brokers/' + escapeHtml(p.id) + '"' +
          ' data-cta="guide" data-partner="' + escapeHtml(p.id) + '">' +
          t('brokers.cta_guide', 'Как зарегистрироваться — по шагам') + '</a>' : '') +
        '<p class="aff-note">' + t('brokers.aff_note', 'партнёрская ссылка') + '</p>' +
      '</div>' +
      '</article>';
  }

  // Блок key_finding (офшорный факт над таблицей) удалён 2026-08-06 по решению
  // владельца вместе с блоком предикта и опросником. Ключи переводов и данные
  // key_finding из partners_licences.json вычищены в том же заходе.

  // renderLossFootnote() ("где на самом деле есть проценты теряющих счетов")
  // удалена 2026-08-06 вместе с колонкой "% теряющих" -- раскрытие было целиком
  // о ней, без колонки в таблице выше стало сиротой без контекста.

  // Калькулятор годовых издержек (renderCalculator + symName) удалён
  // 2026-08-06 по прямому запросу.

  // Опросник «что для тебя важнее» (renderQuiz + QUIZ) удалён 2026-08-06 вместе
  // с блоком предикта и key_finding. Поля _state.quizFilter / quizExplain
  // оставлены со значениями null и '' — на них опирается renderTable, теперь
  // они просто никогда не заполняются, и таблица всегда показывается целиком.

  // ── Сетка карточек (страница /brokers) ──────────────────────────────────────
  // Раздел «Таблица» (плотное сравнение по запросу, переключатель Карточки/
  // Таблица) убран 14.08.2026 по решению владельца — карточки остаются
  // единственной поверхностью, сравнение двух брокеров теперь только через
  // модалку «Сравнить брокеров» (openCompare). Сортировка всегда по названию,
  // А→Я: без кликабельных заголовков колонок менять её было бы нечем.
  var _state = { country: DEFAULT_COUNTRY, quizFilter: null, quizExplain: '' };

  // Выбор страны раньше жил только в памяти: F5 сбрасывал его на "не выбрано".
  var LS_COUNTRY = 'sbf_brokers_country';
  function restoreCountry() {
    try {
      var fromUrl = new URLSearchParams(location.search).get('c');
      var codes = COUNTRIES.map(function (c) { return c.code; });
      if (fromUrl && codes.indexOf(fromUrl) !== -1) return fromUrl;
      var saved = localStorage.getItem(LS_COUNTRY);
      if (saved && codes.indexOf(saved) !== -1) return saved;
    } catch (e) { console.warn('[brokers] restoreCountry', e); }
    return DEFAULT_COUNTRY;
  }
  function persistCountry(code) {
    try {
      localStorage.setItem(LS_COUNTRY, code);
      var u = new URL(location.href);
      if (code) u.searchParams.set('c', code); else u.searchParams.delete('c');
      history.replaceState(null, '', u.toString());
    } catch (e) { console.warn('[brokers] persistCountry', e); }
  }

  function sortRows(rows, col, dir) {
    var key = {
      name: function (r) { return r.partner.name; },
      entity: function (r) { return (r.entity && r.entity.legal_name) || ''; },
      leverage: function (r) { return r.entity && r.entity.leverage_retail ? String(r.entity.leverage_retail) : ''; },
      loss: function (r) { return r.loss.kind === 'value' ? r.loss.value : Infinity; },
      comp: function (r) { return (r.entity && r.entity.compensation_scheme && r.entity.compensation_scheme.amount) || -1; },
      nbp: function (r) { return r.entity && r.entity.negative_balance_protection === true ? 1 : (r.entity && r.entity.negative_balance_protection === false ? 0 : -1); },
      commission: function (r) { return (r.partner.commission && r.partner.commission.value != null) ? r.partner.commission.value : Infinity; },
      mindep: function (r) { return (r.partner.min_deposit && r.partner.min_deposit.value) || Infinity; },
      platforms: function (r) { return (r.partner.platforms || []).length; },
      demo: function (r) { return r.partner.demo_requires_verification === false ? 1 : (r.partner.demo_requires_verification === true ? 0 : -1); },
    }[col];
    if (!key) return rows;
    var sorted = rows.slice().sort(function (a, b) {
      var av = key(a), bv = key(b);
      if (av < bv) return dir === 'asc' ? -1 : 1;
      if (av > bv) return dir === 'asc' ? 1 : -1;
      return 0;
    });
    return sorted;
  }

  function renderTable(root, data) {
    var rows = buildRows(data, _state.country);
    if (_state.quizFilter) rows = rows.filter(_state.quizFilter);
    var sorted = sortRows(rows, 'name', 'asc');

    var emptyMsg = _state.quizFilter
      ? t('brokers.empty_state_filtered', 'Ни один партнёр не подошёл под условия ответа выше — это тоже честный результат, не ошибка.')
      : t('brokers.empty_state', 'Для этой страны нет ни одного партнёра с достаточно проверенными данными — таблица пуста, потому что мы не показываем непроверенное.');

    var quizNote = _state.quizFilter
      ? '<div class="sort-note quiz-filter-note">' + t('brokers.quiz_filter_active', '⚠ Таблица отфильтрована по твоим ответам ниже') +
        ' <button class="clear-quiz-filter">' + t('brokers.sort_reset', 'сбросить') + '</button></div>'
      : '';

    var surface = '<div class="brokers-grid">' + (sorted.length ? sorted.map(renderCard).join('') : '<div class="empty-row">' + emptyMsg + '</div>') + '</div>';

    root.innerHTML =
      '<div class="brokers-toolbar">' +
      '  <label class="country-picker" for="brokersCountry">' + t('brokers.country_label', 'Страна') +
      '    <select id="brokersCountry">' + COUNTRIES.map(function (c) {
            return '<option value="' + escapeHtml(c.code) + '"' + (c.code === _state.country ? ' selected' : '') + '>' + escapeHtml(c[_i18n.lang] || c.ru) + '</option>';
          }).join('') + '</select>' +
      '  </label>' +
      '  <button type="button" class="btn-compare" id="brokersCompare"' + (sorted.length < 2 ? ' disabled' : '') + '>' +
      t('brokers.cmp_button', 'Сравнить брокеров') + '</button>' +
      '  <p class="country-hint">' + t('brokers.country_hint', 'Юрлицо и плечо зависят от страны: потолок задаётся юрисдикцией, а не брокером.') +
      '    <br>' + t('brokers.restrictions_note', 'Ни один из партнёров не обслуживает резидентов США; у отдельных юрлиц есть и другие страновые ограничения — они указаны в карточке брокера.') + '</p>' +
      '  ' + quizNote +
      '</div>' + surface;

    root.querySelector('#brokersCountry').addEventListener('change', function (e) {
      _state.country = e.target.value;
      persistCountry(_state.country);
      track('brokers_country_change', { country: _state.country });
      renderTable(root, data);
    });
    // Клики по партнёрским ссылкам и по инструкциям — единственные конверсии
    // страницы, до 14.08.2026 не считались нигде.
    root.querySelectorAll('a[data-aff]').forEach(function (a) {
      a.addEventListener('click', function () {
        track('broker_affiliate_click', {
          partner: a.getAttribute('data-aff'),
          place: a.getAttribute('data-place'),
          country: _state.country,
          lang: _i18n.lang,
        });
      });
    });
    root.querySelectorAll('a[data-cta="guide"]').forEach(function (a) {
      a.addEventListener('click', function () {
        track('broker_guide_click', { partner: a.getAttribute('data-partner'), lang: _i18n.lang });
      });
    });
    var resolvedByPartner = {};
    sorted.forEach(function (r) { if (r.entity) resolvedByPartner[r.partner.id] = r.entity.id; });
    bindModal();
    bindModalTriggers(root, resolvedByPartner);
    var cmpBtn = root.querySelector('#brokersCompare');
    if (cmpBtn) cmpBtn.addEventListener('click', function () { openCompare(sorted, cmpBtn); });
    var clearQuizBtn = root.querySelector('.clear-quiz-filter');
    if (clearQuizBtn) clearQuizBtn.addEventListener('click', function () {
      _state.quizFilter = null; _state.quizExplain = '';
      renderTable(root, data);
    });

    return rows;
  }

  // ── Модальное окно ─────────────────────────────────────────────────────────
  // Одно окно на страницу, содержимое подставляется при открытии. Esc,
  // клик по подложке, возврат фокуса на кнопку-источник и ловушка фокуса —
  // обязательны: до этого на /brokers не было ни одной модалки, и делать
  // первую недоступной с клавиатуры смысла нет.
  var _modalReturnFocus = null;

  function modalEl() { return document.getElementById('brokerModal'); }

  function openModal(title, bodyHtml, trigger) {
    var m = modalEl();
    if (!m) return;
    m.querySelector('.bm-title').textContent = title;
    m.querySelector('.bm-body').innerHTML = bodyHtml;
    // Широкая панель нужна только сравнению — сбрасываем на каждом открытии,
    // иначе после сравнения обычная модалка лицензии осталась бы растянутой.
    m.querySelector('.bm-panel').classList.remove('bm-wide');
    m.hidden = false;
    document.body.style.overflow = 'hidden';
    _modalReturnFocus = trigger || null;
    var close = m.querySelector('.bm-close');
    if (close) close.focus();
  }

  function closeModal() {
    var m = modalEl();
    if (!m || m.hidden) return;
    m.hidden = true;
    document.body.style.overflow = '';
    if (_modalReturnFocus && document.contains(_modalReturnFocus)) _modalReturnFocus.focus();
    _modalReturnFocus = null;
  }

  function bindModal() {
    var m = modalEl();
    if (!m || m.dataset.bound) return;
    m.dataset.bound = '1';
    m.addEventListener('click', function (ev) {
      if (ev.target === m || ev.target.classList.contains('bm-backdrop') || ev.target.closest('.bm-close')) closeModal();
    });
    document.addEventListener('keydown', function (ev) {
      if (m.hidden) return;
      if (ev.key === 'Escape') { closeModal(); return; }
      if (ev.key !== 'Tab') return;
      var focusable = m.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
      if (!focusable.length) return;
      var first = focusable[0], last = focusable[focusable.length - 1];
      if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
      else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
    });
  }

  function defRow(label, valueHtml) {
    if (!valueHtml) return '';
    return '<div class="bm-row"><div class="bm-k">' + escapeHtml(label) + '</div><div class="bm-v">' + valueHtml + '</div></div>';
  }

  var VERIFICATION_LABEL = {
    register: ['Подтверждено публичным реестром регулятора', 'Confirmed by the regulator’s public register', 'Confirmat de registrul public al autorității'],
    broker_site: ['Со слов брокера — на его сайте или в его документах', 'Stated by the broker on its own site or documents', 'Declarat de broker pe site-ul sau în documentele proprii'],
    unverified: ['Не подтверждено ни реестром, ни сайтом брокера', 'Confirmed neither by a register nor by the broker’s site', 'Neconfirmat nici de registru, nici de site-ul brokerului'],
  };
  function verificationLabel(v) {
    var arr = VERIFICATION_LABEL[v];
    if (!arr) return '';
    return _i18n.lang === 'en' ? arr[1] : _i18n.lang === 'ro' ? arr[2] : arr[0];
  }

  // Модалка лицензии. Ничего внутреннего: поля caution / *_note, написанные
  // нам, а не читателю, сюда не попадают — только public_note и факты.
  function licenceModalHtml(p, ent, isContracting) {
    var ver = ent.verification_licence_no || ent.verification_licence || ent.verification || null;
    var url = ent.register_url || ent.register_url_company || null;
    var isCompanyReg = !ent.register_url && !!ent.register_url_company;
    var body = '';
    body += defRow(t('brokers.m_regulator', 'Регулятор'), escapeHtml(ent.regulator || t('brokers.no_regulator', 'регулятор не назван')));
    body += defRow(t('brokers.m_licence_no', 'Номер лицензии'),
      ent.licence_no ? '<b>' + escapeHtml(ent.licence_no) + '</b>' : '<span class="no-data">' + t('brokers.licence_no_number', 'номер не публикуется') + '</span>');
    body += defRow(t('brokers.m_entity', 'Юридическое лицо'), escapeHtml(ent.legal_name || '—'));
    body += defRow(t('brokers.m_reg_no', 'Регистрационный номер'), ent.reg_no ? escapeHtml(ent.reg_no) : '');
    body += defRow(t('brokers.m_jurisdiction', 'Юрисдикция'), ent.jurisdiction ? escapeHtml(ent.jurisdiction) : '');
    body += defRow(t('brokers.m_since', 'Лицензия с'), ent.licenced_since ? escapeHtml(ent.licenced_since) : '');
    body += defRow(t('brokers.m_verification', 'Уровень проверки'), ver ? escapeHtml(verificationLabel(ver)) : '');
    if (url) {
      body += defRow(isCompanyReg ? t('brokers.register_company_link', 'реестр компаний') : t('brokers.m_register', 'Реестр'),
        '<a href="' + escapeHtml(url) + '" target="_blank" rel="noopener">' + escapeHtml(url.replace(/^https?:\/\//, '').slice(0, 60)) + '…</a>');
    }
    var serves = [];
    if (ent.serves) serves.push(escapeHtml(String(loc(ent, 'serves'))));
    var exM = excludesText(ent);
    if (exM) serves.push(t('brokers.excludes_prefix', 'не обслуживает') + ': ' + escapeHtml(exM));
    if (isMifid(ent)) serves.push(t('brokers.mifid_full', 'услуги в ЕЭЗ — по правилам MiFID II'));
    body += defRow(t('brokers.col_restrictions', 'Кого обслуживает'), serves.join('<br>'));
    if (ent.leverage_retail) body += defRow(colLabel('leverage'), escapeHtml(String(loc(ent, 'leverage_retail'))).split(' · ').join('<br>'));
    var cs = ent.compensation_scheme;
    if (cs && cs.amount) body += defRow(t('brokers.col_comp', 'Защита при банкротстве'), escapeHtml(cs.name || '') + ' — ' + escapeHtml(String(cs.amount)) + ' ' + escapeHtml(cs.currency || ''));
    else if (cs === null) body += defRow(t('brokers.col_comp', 'Защита при банкротстве'), '<span class="no-data">' + t('brokers.no_fund', 'нет компенсационного фонда') + '</span>');
    var pn = loc(ent, 'public_note');
    if (pn) body += '<div class="bm-warn">' + escapeHtml(pn) + '</div>';
    if (isContracting) body += '<div class="bm-contract">' + t('brokers.m_contracting', 'С этим юрлицом заключается договор при регистрации из выбранной вами страны.') + '</div>';
    return body;
  }

  // Полный текст комиссии в том виде, в каком его публикует брокер.
  function commissionText(p) {
    if (p.commission && p.commission.value != null) return null; // короткое числовое — модалка не нужна
    var pc = p.published_specs && p.published_specs.commission;
    return pc && pc.value != null ? String(loc(pc, 'value')) : null;
  }

  function commissionModalHtml(p) {
    var body = '';
    var short = loc(p, 'commission_short');
    if (short) body += defRow(t('brokers.cmp_commission_short', 'Коротко'), escapeHtml(String(short)));
    var txt = commissionText(p);
    if (txt) body += defRow(t('brokers.m_commission_full', 'Как публикует брокер'), escapeHtml(txt));
    else if (p.commission && p.commission.value != null) {
      body += defRow(t('brokers.m_commission_full', 'Как публикует брокер'),
        escapeHtml(commissionModelLabel(p.commission.model)) + ' ' + escapeHtml(String(p.commission.value)) + ' ' +
        escapeHtml(p.commission.currency || '') + (p.commission.per_volume ? ' / ' + escapeHtml(String(p.commission.per_volume)) : ''));
    }
    var note = loc(p, 'commission_short_note');
    if (note) body += defRow(t('brokers.m_commission_note', 'Из чего складывается'), escapeHtml(String(note)));
    if (p.commission && p.commission.account_type) {
      body += defRow(t('brokers.m_account_type', 'Тип счёта'), escapeHtml(p.commission.account_type));
    }
    var sp = p.spreads_published;
    if (sp && sp.account_type) {
      body += defRow(t('brokers.m_spread_account', 'Спред в таблице снят со счёта'), escapeHtml(sp.account_type));
    }
    var pc = p.published_specs && p.published_specs.commission;
    if (pc && pc.source) {
      body += defRow(t('brokers.m_source', 'Источник'),
        '<a href="' + escapeHtml(pc.source) + '" target="_blank" rel="noopener">' + escapeHtml(pc.source.replace(/^https?:\/\//, '').slice(0, 60)) + '…</a>');
    }
    var chk = (p.published_specs && p.published_specs.checked) || null;
    if (chk) body += defRow(t('brokers.m_checked', 'Дата снятия'), escapeHtml(chk));
    body += '<div class="bm-contract">' + t('brokers.spread_by_broker', 'по данным брокера') + '</div>';
    return body;
  }

  function leverageModalHtml(p, ent) {
    var body = '';
    var raw = loc(ent, 'leverage_retail');
    if (raw) body += defRow(colLabel('leverage'), escapeHtml(String(raw)).split(' · ').join('<br>'));
    body += defRow(t('brokers.m_entity', 'Юридическое лицо'), escapeHtml(ent.legal_name || '') + (ent.regulator ? ' · ' + escapeHtml(ent.regulator) : ''));
    var extra = loc(ent, 'leverage_public_extra');
    if (extra) body += defRow(t('brokers.m_leverage_extra', 'Как меняется на практике'), escapeHtml(String(extra)));
    var shortNote = loc(ent, 'leverage_short_note');
    if (shortNote) body += defRow(t('brokers.m_leverage_note', 'Откуда диапазон'), escapeHtml(String(shortNote)));
    if (ent.leverage_jurisdiction_note) body += defRow(t('brokers.m_leverage_rule', 'Чем задан потолок'), escapeHtml(String(loc(ent, 'leverage_jurisdiction_note'))));
    if (ent.leverage_verification) body += defRow(t('brokers.m_verification', 'Уровень проверки'), escapeHtml(verificationLabel(ent.leverage_verification)));
    if (ent.leverage_checked) body += defRow(t('brokers.m_checked', 'Дата снятия'), escapeHtml(ent.leverage_checked));
    if (ent.leverage_source) {
      body += defRow(t('brokers.m_source', 'Источник'),
        '<a href="' + escapeHtml(ent.leverage_source) + '" target="_blank" rel="noopener">' + escapeHtml(ent.leverage_source.replace(/^https?:\/\//, '').slice(0, 60)) + '…</a>');
    }
    return body;
  }

  // Модалка «Все юрлица, лицензии и платформы» — раньше это был <details>,
  // разворачивающийся прямо в карточке; при разной длине списка лицензий
  // (у AvaTrade 7 юрлиц, у XM 3) карточки в сетке разъезжались по высоте.
  // Содержимое то же самое (список лицензий кликабелен и здесь — каждая
  // плашка открывает свою licenceModalHtml поверх этой же модалки), просто
  // строится по требованию при клике, а не на каждый рендер карточки.
  function allLicencesModalHtml(p, contractingEntityId) {
    var lics = licencesOf(p);
    var moreLic = lics.map(function (ent) {
      return '<div class="lic-row">' + licenceChip(p, ent) + '</div>';
    }).join('');
    var entRec = contractingEntityId ? _entityIndex[p.id + '::' + contractingEntityId] : null;
    // loss-заглушка: buildFieldHtml() требует row.loss, но здесь нужны только
    // inactivity/restrictions/platforms — эти поля от loss не зависят.
    var f = buildFieldHtml({ partner: p, entity: entRec ? entRec.entity : null, loss: { kind: 'not_published', disclose: null } });
    return '<div class="more-row"><span class="mr-k">' + colLabel('licence') + '</span><div class="lic-list">' + moreLic + '</div></div>' +
      '<div class="more-row"><span class="mr-k">' + colLabel('inactivity') + '</span><div>' + f.inactivity + '</div></div>' +
      '<div class="more-row"><span class="mr-k">' + colLabel('restrictions') + '</span><div>' + f.restrictions + '</div></div>' +
      '<div class="more-row"><span class="mr-k">' + colLabel('platforms') + '</span><div>' + f.platforms + '</div></div>';
  }

  // ── Сравнение двух брокеров ────────────────────────────────────────────────
  // Открывается из тулбара, показывает двух рядом с возможностью подменить
  // любого из двух. Данные берутся из тех же row, что и карточки, поэтому
  // выбор страны и все оговорки («по данным брокера», даты снятия) сохраняются
  // — отдельного «упрощённого» набора цифр для сравнения не заводится, иначе
  // он неизбежно разъедется с основным.
  var _compare = { left: null, right: null };

  var COMPARE_ROWS = ['contracting', 'licences', 'leverage', 'mindep', 'spread', 'commission', 'inactivity', 'nbp', 'comp', 'platforms', 'restrictions'];

  function compareLabel(key) {
    if (key === 'contracting') return t('brokers.cmp_contracting', 'Договор подписывает');
    if (key === 'licences') return colLabel('licence');
    return colLabel(key);
  }

  function compareCell(row, key) {
    if (!row) return '<span class="no-data">—</span>';
    var p = row.partner, e = row.entity;
    if (key === 'contracting') {
      return e
        ? '<b>' + escapeHtml(e.legal_name || '—') + '</b>' +
          (e.regulator ? '<div class="entity-sub">' + escapeHtml(e.regulator) + '</div>' : '') +
          (e.jurisdiction ? '<div class="entity-sub">' + escapeHtml(e.jurisdiction) + '</div>' : '')
        : '<span class="no-data">' + t('brokers.entity_not_served', 'не обслуживает эту страну') + '</span>';
    }
    if (key === 'licences') {
      return licencesOf(p).map(function (ent) {
        return '<div class="cmp-lic">' + escapeHtml(ent.regulator || t('brokers.no_regulator', 'регулятор не назван')) +
          (ent.licence_no ? ' <b>' + escapeHtml(ent.licence_no) + '</b>' : '') + '</div>';
      }).join('');
    }
    var f = buildFieldHtml(row);
    if (key === 'leverage') {
      var raw = e && e.leverage_retail ? String(loc(e, 'leverage_retail'))
        : (p.leverage_retail && p.leverage_retail.value ? String(loc(p.leverage_retail, 'value')) : null);
      return raw ? escapeHtml(raw).split(' · ').join('<br>') : f.leverage;
    }
    return f[key] != null ? f[key] : '<span class="no-data">—</span>';
  }

  function compareSelect(side, rows, selectedId) {
    return '<select class="cmp-pick" data-side="' + side + '" aria-label="' + t('brokers.cmp_pick', 'Выбрать брокера') + '">' +
      rows.map(function (r) {
        return '<option value="' + escapeHtml(r.partner.id) + '"' + (r.partner.id === selectedId ? ' selected' : '') + '>' +
          escapeHtml(r.partner.name) + '</option>';
      }).join('') + '</select>';
  }

  function compareCta(row) {
    if (!row) return '';
    var p = row.partner;
    return '<a class="btn-open cmp-cta" href="' + escapeHtml(affiliateFor(p)) + '"' +
      ' target="_blank" rel="noopener sponsored" data-aff="' + escapeHtml(p.id) + '" data-place="compare">' +
      t('brokers.cta_open', 'Открыть счёт') + ' ' + escapeHtml(p.name) + ' →</a>';
  }

  function compareHtml(rows) {
    var byId = {};
    rows.forEach(function (r) { byId[r.partner.id] = r; });
    var L = byId[_compare.left] || rows[0] || null;
    var R = byId[_compare.right] || rows[1] || null;
    if (L) _compare.left = L.partner.id;
    if (R) _compare.right = R.partner.id;

    var head =
      '<div class="cmp-head">' +
      '  <div class="cmp-col">' + (L ? cardLogoHtml(L.partner) : '') + compareSelect('left', rows, _compare.left) + '</div>' +
      '  <div class="cmp-col">' + (R ? cardLogoHtml(R.partner) : '') + compareSelect('right', rows, _compare.right) + '</div>' +
      '</div>';

    var body = COMPARE_ROWS.map(function (key) {
      return '<div class="cmp-block">' +
        '<div class="cmp-k">' + escapeHtml(compareLabel(key)) + '</div>' +
        '<div class="cmp-pair">' +
          '<div class="cmp-v">' + compareCell(L, key) + '</div>' +
          '<div class="cmp-v">' + compareCell(R, key) + '</div>' +
        '</div></div>';
    }).join('');

    return head + '<div class="cmp-body">' + body + '</div>' +
      '<div class="cmp-foot"><div>' + compareCta(L) + '</div><div>' + compareCta(R) + '</div></div>';
  }

  function openCompare(rows, trigger) {
    openModal(t('brokers.cmp_title', 'Сравнение брокеров'), compareHtml(rows), trigger);
    var m = modalEl();
    if (m) m.querySelector('.bm-panel').classList.add('bm-wide');
    bindCompare(rows);
    track('brokers_compare_open', { left: _compare.left, right: _compare.right });
  }

  function bindCompare(rows) {
    var m = modalEl();
    if (!m) return;
    m.querySelectorAll('.cmp-pick').forEach(function (sel) {
      sel.addEventListener('change', function () {
        _compare[sel.getAttribute('data-side')] = sel.value;
        m.querySelector('.bm-body').innerHTML = compareHtml(rows);
        bindCompare(rows);
        track('brokers_compare_change', { side: sel.getAttribute('data-side'), partner: sel.value });
      });
    });
    m.querySelectorAll('a[data-aff]').forEach(function (a) {
      a.addEventListener('click', function () {
        track('broker_affiliate_click', { partner: a.getAttribute('data-aff'), place: 'compare', country: _state.country, lang: _i18n.lang });
      });
    });
  }

  // Плашки лицензий (data-entity) встречаются в двух местах: одна лид-плашка
  // прямо на карточке (root) и полный список внутри модалки «Все юрлица»
  // (allLicencesModalHtml, вставляется в .bm-body ПОСЛЕ открытия модалки —
  // поэтому её нужно биндить отдельным вызовом, не один раз через root).
  function bindEntityChips(container, resolvedEntityIdByPartner) {
    container.querySelectorAll('button[data-entity]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var rec = _entityIndex[btn.getAttribute('data-entity')];
        if (!rec) return;
        var isContracting = resolvedEntityIdByPartner[rec.partner.id] === rec.entity.id;
        openModal(rec.entity.legal_name || rec.partner.name,
          licenceModalHtml(rec.partner, rec.entity, isContracting), btn);
        track('broker_licence_modal', { partner: rec.partner.id, entity: rec.entity.id });
      });
    });
  }

  function bindModalTriggers(root, resolvedEntityIdByPartner) {
    bindEntityChips(root, resolvedEntityIdByPartner);
    root.querySelectorAll('button[data-modal^="all::"]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var pid = btn.getAttribute('data-modal').slice(5);
        var rec = Object.keys(_entityIndex).map(function (k) { return _entityIndex[k]; })
          .filter(function (x) { return x.partner.id === pid; })[0];
        if (!rec) return;
        var p = rec.partner;
        openModal(t('brokers.card_details', 'Все юрлица, лицензии и платформы') + ' · ' + (p.name || ''),
          allLicencesModalHtml(p, resolvedEntityIdByPartner[pid]), btn);
        var m = modalEl();
        if (m) bindEntityChips(m.querySelector('.bm-body'), resolvedEntityIdByPartner);
        track('broker_licences_modal', { partner: pid });
      });
    });
    root.querySelectorAll('button[data-modal^="lev::"]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var key = btn.getAttribute('data-modal').slice(5);
        var rec = _entityIndex[key];
        if (!rec) return;
        openModal(colLabel('leverage') + ' · ' + (rec.partner.name || ''), leverageModalHtml(rec.partner, rec.entity), btn);
        track('broker_leverage_modal', { partner: rec.partner.id, entity: rec.entity.id });
      });
    });
    root.querySelectorAll('button[data-modal^="comm::"]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var pid = btn.getAttribute('data-modal').slice(6);
        var rec = Object.keys(_entityIndex).map(function (k) { return _entityIndex[k]; })
          .filter(function (x) { return x.partner.id === pid; })[0];
        if (!rec) return;
        openModal(colLabel('commission') + ' · ' + (rec.partner.name || ''), commissionModalHtml(rec.partner), btn);
        track('broker_commission_modal', { partner: pid });
      });
    });
  }

  // ── Статические блоки страницы (доверие + блок помощи) ─────────────────────
  // Рендерятся из JS, а не Jinja: core/i18n.py держит словарь в процессе
  // (_cache), поэтому новые ключи не появятся у server-side t() до рестарта
  // сервиса и вывелись бы именами ключей. У клиентского t() есть fallback.
  function renderStatics(root) {
    // Блок «чипов доверия» удалён 14.08.2026 по решению владельца вместе с
    // подзаголовком: три плашки повторяли своими словами то, что и так видно
    // по самой таблице (нет колонки «рекомендация», у чисел стоят даты,
    // ссылки ведут на реестры). Контейнер #brokersTrust убран из brokers.html.

    var help = root.querySelector('#brokersHelp');
    if (help) {
      var pref = langPrefix();
      help.innerHTML =
        '<div class="help-text">' +
          '<h2>' + escapeHtml(t('brokers.help_title', 'Не уверены, что выбрать?')) + '</h2>' +
          '<p>' + escapeHtml(t('brokers.help_text',
            'Разница между этими брокерами — не в бонусах, а в том, какое юрлицо подписывает договор и какой у него регулятор. В курсе разбираем, как это читать, и что спрашивать у площадки до первого депозита.')) + '</p>' +
        '</div>' +
        '<div class="help-actions">' +
          '<a class="help-primary" href="' + pref + '/edu/b" data-cta="help_course">' +
            escapeHtml(t('brokers.help_cta_course', 'Бесплатный курс →')) + '</a>' +
          '<a class="help-secondary" href="' + pref + '/register.html" data-cta="help_register">' +
            escapeHtml(t('brokers.help_cta_register', 'Завести журнал сделок')) + '</a>' +
        '</div>';
      help.hidden = false;
      help.querySelectorAll('a[data-cta]').forEach(function (a) {
        a.addEventListener('click', function () {
          track('brokers_help_click', { target: a.getAttribute('data-cta'), lang: _i18n.lang });
        });
      });
    }
  }

  // ── Публичный API: страница /brokers ────────────────────────────────────────
  function mountPage(rootId) {
    var root = document.getElementById(rootId);
    if (!root) return;
    _state.country = restoreCountry();
    _i18n.ready.then(function () { renderStatics(root); });
    _i18n.ready.then(function () { return Promise.all([loadData(), loadLicences()]); }).then(function (results) {
      var data = results[0];
      _licencesData = results[1];
      indexEntities(data);

      var tableRoot = root.querySelector('#brokersTableRoot');
      renderTable(tableRoot, data);
    }).catch(function (err) {
      root.innerHTML = '<div class="brokers-error">' + t('brokers.load_error', 'Не удалось загрузить данные партнёров.') + '</div>';
      console.error('[brokers]', err);
    });
  }

  // ── Публичный API: встраиваемый BrokerPicker (глава 11, ступень 6) ─────────
  // [ДОПУЩЕНИЕ] SPEC_partner_ladder_ch6_15.md §4.5 для этого же виджета жёстче
  // главной страницы: "партнёр без loss_pct ИСКЛЮЧАЕТСЯ, а не показывается с
  // прочерком — прочерк читается как данные скрыты". Абзац-раскрытие XM (вариант
  // 2 у полной страницы) в узкий встраиваемый виджет внутри главы курса не
  // помещается по смыслу так же хорошо, как на отдельной странице сравнения —
  // здесь строгое правило "нет числа -- нет строки", без исключений.
  function mountPicker(el, opts) {
    opts = opts || {};
    var country = opts.country || restoreCountry() || DEFAULT_COUNTRY;
    var предел = opts.limit || 3;
    Promise.all([loadData(), loadLicences()]).then(function (results) {
      var data = results[0];
      _licencesData = _licencesData || results[1];
      indexEntities(data);
      /* 🔴 ПОЧЕМУ НЕ ЖЁСТКИЙ ФИЛЬТР «НЕТ ЧИСЛА — НЕТ СТРОКИ». Он тут был, и
         виджет оказывался пуст: процент теряющих счетов обязаны публиковать
         только европейские юрлица, а для страны по умолчанию резолвится
         офшорное. Замер: при пустой стране и при MD числа нет ни у одного из
         пяти, при DE — у трёх. То есть читатель из Молдовы видел бы пустую
         рамку с текстом «нет проверенных данных» и уходил с мыслью, что мы
         что-то скрываем.

         Карточка умеет показать «не публикуется» с объяснением, почему —
         ровно так это и сделано на /brokers. Объяснение честнее пустоты, а
         выбор страны рядом показывает, отчего число появляется и исчезает:
         это и есть урок ступени — юрисдикция решает больше, чем бренд. */
      var rows = buildRows(data, country);
      var sorted = sortRows(rows, 'loss', 'asc').slice(0, предел);
      var выбор = '<label class="broker-picker-country">' +
        t('brokers.country_label', 'Страна') +
        ' <select>' + COUNTRIES.map(function (c) {
          return '<option value="' + escapeHtml(c.code) + '"' +
                 (c.code === country ? ' selected' : '') + '>' +
                 escapeHtml(c[_i18n.lang] || c.ru) + '</option>';
        }).join('') + '</select></label>';
      el.innerHTML = '<div class="broker-picker">' + выбор +
        (sorted.length
          ? '<div class="brokers-grid">' + sorted.map(renderCard).join('') + '</div>'
          : '<div class="broker-picker-empty">' +
            t('brokers.empty_state', 'Для этой страны показывать нечего.') + '</div>') +
        '<a class="broker-picker-more" href="' + langPrefix() + '/brokers">' +
        t('brokers.full_compare_link', 'Полное сравнение →') + '</a></div>';
      var сел = el.querySelector('.broker-picker-country select');
      if (сел) сел.addEventListener('change', function (e) {
        persistCountry(e.target.value);
        mountPicker(el, Object.assign({}, opts, { country: e.target.value }));
      });
      /* Карточка содержит рабочие элементы: раскрытие списка юрлиц и
         модалку с лицензиями. Без обработчиков это была бы картинка
         кнопки — читатель жмёт, ничего не происходит.

         Модалка одна на документ и живёт в разметке brokers.html. Внутри
         главы этой разметки нет, поэтому создаём её на лету: openModal
         молча выходит, если контейнера нет, и кнопка «лицензия» тихо
         перестала бы работать. */
      if (!document.getElementById('brokerModal')) {
        var окно = document.createElement('div');
        окно.className = 'bm';
        окно.id = 'brokerModal';
        окно.setAttribute('role', 'dialog');
        окно.setAttribute('aria-modal', 'true');
        окно.hidden = true;
        окно.innerHTML =
          '<div class="bm-backdrop"></div><div class="bm-panel">' +
          '<div class="bm-head"><h2 class="bm-title" id="bmTitle"></h2>' +
          '<button type="button" class="bm-close" aria-label="' +
          t('brokers.m_close', 'Закрыть') + '">&times;</button></div>' +
          '<div class="bm-body"></div></div>';
        document.body.appendChild(окно);
      }
      var резолв = {};
      sorted.forEach(function (r) { if (r.entity) резолв[r.partner.id] = r.entity.id; });
      bindModal();
      bindModalTriggers(el, резолв);
      // Партнёрский клик из главы курса — такая же конверсия, как со
      // страницы сравнения, и считаться должен так же. place говорит,
      // откуда пришёл человек.
      el.querySelectorAll('a[data-aff]').forEach(function (a) {
        a.addEventListener('click', function () {
          track('broker_affiliate_click', {
            partner: a.getAttribute('data-aff'),
            place: opts.place || 'ladder',
            country: country,
            lang: _i18n.lang,
          });
        });
      });
    }).catch(function (err) { console.error('[BrokerPicker]', err); });
  }

  global.SBFBrokers = { mountPage: mountPage, resolveEntity: resolveEntity, loadData: loadData, COUNTRIES: COUNTRIES, DEFAULT_COUNTRY: DEFAULT_COUNTRY };
  global.BrokerPicker = { mount: mountPicker };

  if (document.getElementById('brokersPageRoot')) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { mountPage('brokersPageRoot'); });
    else mountPage('brokersPageRoot');
  }
})(window);
