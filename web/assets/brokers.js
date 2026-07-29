/* ============================================================================
   brokers.js — /brokers (SPEC_brokers_comparison_page.md) + BrokerPicker
   встраиваемый в главу 11 (§1: "один источник данных, две поверхности").

   Единственный источник данных — /data/partners.json. Ни одно число в этом
   файле и в brokers.html не написано руками — см. правило в самом JSON.

   Правило показа (жёсткое, из partners.json._meta.rules): партнёр без
   актуального loss_pct у РЕЗОЛВЛЕННОГО для страны пользователя юрлица не
   отображается. Исключение — юрлицо, у которого НЕ ПУБЛИКУЕТСЯ процент
   подтверждено (entity.loss_pct_confirmed_not_published), и у бренда есть
   юрлицо-сосед с реальным числом для раскрытия (кейс XM, см. §5.2 спеки).
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
  var DEFAULT_COUNTRY = 'MD'; // компания молдавская — честный дефолт, не догадка

  function countryLabel(code, lang) {
    var c = COUNTRIES.filter(function (x) { return x.code === code; })[0];
    return c ? (c[lang] || c.ru) : code;
  }

  // ── Резолв юрлица по стране ────────────────────────────────────────────────
  // entity_resolution.<lowercase country> — явный override спеки (см. XM.md),
  // приоритетнее общей логики serves/excludes/EEA. Общая логика — фолбэк для
  // партнёров без явного оверрайда.
  function resolveEntity(partner, countryCode) {
    var entities = partner.entities || [];
    if (!entities.length) return null;
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
  // Возвращает null, если партнёра вообще нельзя показывать (жёсткое правило).
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
    return null;
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

  function groupOf(data, partnerId) {
    return (data.groups || []).filter(function (g) { return (g.members || []).indexOf(partnerId) !== -1; })[0] || null;
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
    // Сортировка по умолчанию: loss_pct по возрастанию; "не публикуется" -- в конец,
    // без собственного числа сортировать нечем, но и скрывать нельзя.
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

  // ── Рендер одной строки таблицы (используется и полной, и BrokerPicker) ────
  function renderRow(row, opts) {
    opts = opts || {};
    var p = row.partner, e = row.entity, loss = row.loss;
    var lang = _i18n.lang;

    var lossCell;
    if (loss.kind === 'value') {
      lossCell = '<b class="loss-val">' + fmtPct(loss.value) + '%</b> ' + dateBadge(loss.checked) + ' ' + sourceLink(loss.source);
    } else {
      var d = loss.disclose;
      lossCell = '<span class="loss-np">' + t('brokers.loss_pct_not_published', 'не публикуется') + '</span>';
      if (d) {
        lossCell += '<div class="loss-disclose">' + t('brokers.loss_pct_disclosure_tpl',
          'У юрлица {{entity}} — {{pct}}%, но другое плечо ({{lev}}) и {{fund}}', {
            entity: d.legal_name, pct: fmtPct(d.loss_pct),
            lev: d.leverage_retail || '—',
            fund: d.compensation_scheme ? (d.compensation_scheme.amount + ' ' + d.compensation_scheme.currency) : t('brokers.no_fund', 'нет фонда'),
          }) + '</div>';
      }
    }

    var groupBadge = '';
    if (row.group) {
      var others = row.group.members.filter(function (m) { return m !== p.id; });
      groupBadge = '<div class="group-badge">' + (row.group['label_' + lang] || row.group.label_ru) +
        (others.length ? ' · ' + t('brokers.group_same_as', 'та же группа: {{other}}', { other: others.join(', ') }) : '') + '</div>';
    }

    var entityCell = e
      ? escapeHtml(e.legal_name || '—') + '<div class="entity-sub">' + escapeHtml([e.regulator, e.licence_no].filter(Boolean).join(' · ')) + '</div>'
      : '<span class="no-data">' + t('brokers.entity_not_served', 'не обслуживает эту страну') + '</span>';

    var leverage = (e && e.leverage_retail) ? escapeHtml(String(e.leverage_retail)) : '<span class="no-data">' + t('brokers.no_data', '—') + '</span>';

    var spreads = (p.spreads || []).filter(function (s) { return s.typical != null; });
    var spreadCell = spreads.length
      ? spreads.map(function (s) { return escapeHtml(s.symbol) + ': ' + s.typical + (s.account_type ? ' (' + escapeHtml(s.account_type) + ')' : ''); }).join('<br>')
      : '<span class="no-data">' + t('brokers.spreads_not_collected', 'не снято') + '</span>';

    var commission = (p.commission && p.commission.value != null)
      ? escapeHtml(p.commission.model || '') + ' ' + p.commission.value + ' ' + (p.commission.currency || '') + (p.commission.per_volume ? ' / ' + p.commission.per_volume : '')
      : '<span class="no-data">' + t('brokers.no_data', '—') + '</span>';

    var nbp = e && e.negative_balance_protection === true ? t('brokers.yes', 'да')
      : e && e.negative_balance_protection === false ? t('brokers.no', 'нет')
      : '<span class="no-data">' + t('brokers.no_data', '—') + '</span>';

    var comp = e && e.compensation_scheme && e.compensation_scheme.amount
      ? escapeHtml(e.compensation_scheme.name || '') + ' — ' + e.compensation_scheme.amount + ' ' + (e.compensation_scheme.currency || '')
      : (e && e.compensation_scheme === null ? t('brokers.no_fund', 'нет фонда') : '<span class="no-data">' + t('brokers.no_data', '—') + '</span>');

    var minDep = p.min_deposit && p.min_deposit.value != null
      ? p.min_deposit.value + ' ' + (p.min_deposit.currency || '')
      : '<span class="no-data">' + t('brokers.no_data', '—') + '</span>';

    var platforms = (p.platforms || []).length ? escapeHtml(p.platforms.join(' / ')) : '<span class="no-data">' + t('brokers.no_data', '—') + '</span>';

    var demo = p.demo_requires_verification === true ? t('brokers.no', 'нет')
      : p.demo_requires_verification === false ? t('brokers.yes', 'да')
      : '<span class="no-data">' + t('brokers.no_data', '—') + '</span>';

    var affLink = (p.links && p.links.affiliate) || '#';

    var cols = [
      '<td class="col-entity">' + entityCell + groupBadge + '</td>',
      '<td class="col-leverage">' + leverage + '</td>',
      '<td class="col-spread">' + spreadCell + '</td>',
      '<td class="col-commission">' + commission + '</td>',
      '<td class="col-loss">' + lossCell + '</td>',
      '<td class="col-comp">' + comp + '</td>',
      '<td class="col-nbp">' + nbp + '</td>',
      '<td class="col-mindep">' + minDep + '</td>',
      '<td class="col-platforms">' + platforms + '</td>',
      '<td class="col-demo">' + demo + '</td>',
    ];
    if (opts.compact) cols = [cols[0], cols[4], cols[1]]; // BrokerPicker: юрлицо, % теряющих, плечо

    return '<tr data-partner="' + p.id + '">' +
      '<td class="col-name"><a href="' + affLink + '" target="_blank" rel="noopener sponsored">' + escapeHtml(p.name) + '</a></td>' +
      cols.join('') + '</tr>';
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  var FULL_COLS = ['name', 'entity', 'leverage', 'spread', 'commission', 'loss', 'comp', 'nbp', 'mindep', 'platforms', 'demo'];
  var COMPACT_COLS = ['name', 'entity', 'loss', 'leverage'];

  function colLabel(col) {
    var map = {
      name: t('brokers.col_name', 'Брокер'),
      entity: t('brokers.col_entity', 'Юрлицо и регулятор'),
      leverage: t('brokers.col_leverage', 'Плечо'),
      spread: t('brokers.col_spread', 'Спред'),
      commission: t('brokers.col_commission', 'Комиссия'),
      loss: t('brokers.col_loss', '% теряющих'),
      comp: t('brokers.col_comp', 'Компенсация'),
      nbp: t('brokers.col_nbp', 'Защита от отриц. баланса'),
      mindep: t('brokers.col_mindep', 'Мин. депозит'),
      platforms: t('brokers.col_platforms', 'Платформы'),
      demo: t('brokers.col_demo', 'Демо без верификации'),
    };
    return map[col] || col;
  }

  // ── Полная таблица (страница /brokers) ─────────────────────────────────────
  var _state = { country: DEFAULT_COUNTRY, sortCol: 'loss', sortDir: 'asc' };

  function sortRows(rows, col, dir) {
    var key = {
      name: function (r) { return r.partner.name; },
      leverage: function (r) { return r.entity && r.entity.leverage_retail ? String(r.entity.leverage_retail) : ''; },
      loss: function (r) { return r.loss.kind === 'value' ? r.loss.value : Infinity; },
      mindep: function (r) { return (r.partner.min_deposit && r.partner.min_deposit.value) || Infinity; },
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
    var sorted = sortRows(rows, _state.sortCol, _state.sortDir);
    var isDefaultSort = (_state.sortCol === 'loss' && _state.sortDir === 'asc');

    var thead = '<tr>' + FULL_COLS.map(function (c) {
      var sortable = ['name', 'leverage', 'loss', 'mindep'].indexOf(c) !== -1;
      var active = _state.sortCol === c;
      return '<th' + (sortable ? ' data-sort="' + c + '" class="sortable' + (active ? ' active' : '') + '"' : '') + '>' +
        colLabel(c) + (active ? (_state.sortDir === 'asc' ? ' ▲' : ' ▼') : '') + '</th>';
    }).join('') + '</tr>';

    var tbody = sorted.length
      ? sorted.map(function (r) { return renderRow(r); }).join('')
      : '<tr><td colspan="' + FULL_COLS.length + '" class="empty-row">' + t('brokers.empty_state', 'Ни один партнёр не публикует актуальный процент теряющих счетов для этой страны — таблица пуста, потому что мы не показываем оценки без подтверждённого числа.') + '</td></tr>';

    var sortNote = !isDefaultSort
      ? '<div class="sort-note">' + t('brokers.sort_differs', '⚠ Сортировка отличается от умолчания (% теряющих, по возрастанию)') +
        ' <button class="reset-sort">' + t('brokers.sort_reset', 'сбросить') + '</button></div>'
      : '';

    root.innerHTML =
      '<div class="brokers-toolbar">' +
      '  <label class="country-picker">' + t('brokers.country_label', 'Страна') + ': ' +
      '    <select id="brokersCountry">' + COUNTRIES.map(function (c) {
            return '<option value="' + c.code + '"' + (c.code === _state.country ? ' selected' : '') + '>' + (c[_i18n.lang] || c.ru) + '</option>';
          }).join('') + '</select>' +
      '  </label>' +
      '  ' + sortNote +
      '</div>' +
      '<div class="brokers-table-wrap"><table class="brokers-table"><thead>' + thead + '</thead><tbody>' + tbody + '</tbody></table></div>' +
      '<div class="brokers-cards">' + (sorted.length ? sorted.map(renderCard).join('') : '<div class="empty-row">' + t('brokers.empty_state', 'Ни один партнёр не публикует актуальный процент теряющих счетов для этой страны — таблица пуста, потому что мы не показываем оценки без подтверждённого числа.') + '</div>') + '</div>';

    root.querySelector('#brokersCountry').addEventListener('change', function (e) {
      _state.country = e.target.value;
      renderTable(root, data);
    });
    root.querySelectorAll('th.sortable').forEach(function (th) {
      th.addEventListener('click', function () {
        var col = th.getAttribute('data-sort');
        if (_state.sortCol === col) _state.sortDir = _state.sortDir === 'asc' ? 'desc' : 'asc';
        else { _state.sortCol = col; _state.sortDir = 'asc'; }
        renderTable(root, data);
      });
    });
    var resetBtn = root.querySelector('.reset-sort');
    if (resetBtn) resetBtn.addEventListener('click', function () {
      _state.sortCol = 'loss'; _state.sortDir = 'asc';
      renderTable(root, data);
    });

    return rows; // для калькулятора/опросника ниже
  }

  // ── Мобильная карточка (вместо горизонтальной прокрутки таблицы) ───────────
  function renderCard(row) {
    var p = row.partner, e = row.entity, loss = row.loss;
    var lossHtml = loss.kind === 'value'
      ? '<b class="loss-val">' + fmtPct(loss.value) + '%</b> ' + dateBadge(loss.checked)
      : '<span class="loss-np">' + t('brokers.loss_pct_not_published', 'не публикуется') + '</span>';
    return '<div class="broker-card">' +
      '<div class="bc-head"><a href="' + ((p.links && p.links.affiliate) || '#') + '" target="_blank" rel="noopener sponsored">' + escapeHtml(p.name) + '</a>' +
      (row.group ? '<span class="group-badge">' + (row.group['label_' + _i18n.lang] || row.group.label_ru) + '</span>' : '') + '</div>' +
      '<div class="bc-row"><span>' + t('brokers.col_entity', 'Юрлицо') + '</span><span>' + (e ? escapeHtml(e.legal_name) + ' · ' + escapeHtml(e.regulator || '') : t('brokers.entity_not_served', 'не обслуживает эту страну')) + '</span></div>' +
      '<div class="bc-row"><span>' + t('brokers.col_loss', '% теряющих') + '</span><span>' + lossHtml + '</span></div>' +
      '<div class="bc-row"><span>' + t('brokers.col_leverage', 'Плечо') + '</span><span>' + (e && e.leverage_retail ? escapeHtml(String(e.leverage_retail)) : '—') + '</span></div>' +
      '<div class="bc-row"><span>' + t('brokers.col_mindep', 'Мин. депозит') + '</span><span>' + (p.min_deposit && p.min_deposit.value != null ? p.min_deposit.value + ' ' + p.min_deposit.currency : '—') + '</span></div>' +
      '</div>';
  }

  // ── Класс A: калькулятор годовых издержек ──────────────────────────────────
  function renderCalculator(root, data) {
    root.innerHTML =
      '<div class="calc-inputs">' +
      '  <label>' + t('brokers.calc_trades_label', 'Сделок в месяц') + ' <input type="number" id="calcTrades" min="1" value="15"></label>' +
      '  <label>' + t('brokers.calc_volume_label', 'Типичный объём (лоты)') + ' <input type="number" id="calcVolume" min="0.01" step="0.01" value="0.5"></label>' +
      '  <label>' + t('brokers.calc_instrument_label', 'Инструмент') + ' <select id="calcInstrument"><option value="XAUUSD">XAUUSD</option><option value="EURUSD">EURUSD</option></select></label>' +
      '</div>' +
      '<div id="calcResults" class="calc-results"></div>';

    function recompute() {
      var trades = Math.max(1, parseFloat(root.querySelector('#calcTrades').value) || 0);
      var volume = Math.max(0.01, parseFloat(root.querySelector('#calcVolume').value) || 0);
      var instrument = root.querySelector('#calcInstrument').value;
      var rows = buildRows(data, _state.country);
      var out = rows.map(function (r) {
        var p = r.partner;
        var spread = (p.spreads || []).filter(function (s) { return s.symbol === instrument && s.typical != null; })[0];
        var comm = p.commission;
        if (!spread) return { name: p.name, insufficient: true };
        // Комиссия: per_side * 2 либо round_turn, приведено к $ на сделку при заданном объёме
        var commPerTrade = 0;
        if (comm && comm.value != null && comm.per_volume) {
          var notional = volume * 100000; // 1 лот = 100000 единиц базовой валюты (стандартная конвенция FX/металлы)
          var units = notional / comm.per_volume;
          commPerTrade = (comm.round_turn != null ? comm.round_turn : comm.value * 2) * units;
        }
        // Спред в валюте инструмента: типовое значение спреда уже в пунктах/units котировки,
        // без единой таблицы контрактных размеров это не переводится в $ надёжно -- честно
        // показываем как "нет данных", если нет спреда, но НЕ считаем спред-компонент в деньгах
        // без размера контракта (иначе это будет придуманное число).
        var annual = commPerTrade * trades * 12;
        return { name: p.name, annual: annual, hasSpreadCost: false, spread: spread.typical, account: spread.account_type };
      });
      var el = root.querySelector('#calcResults');
      el.innerHTML = '<table class="calc-table"><thead><tr><th>' + t('brokers.col_name', 'Брокер') + '</th><th>' + t('brokers.calc_result_col', 'Комиссия/год') + '</th><th>' + t('brokers.calc_spread_col', 'Тип. спред') + '</th></tr></thead><tbody>' +
        out.map(function (o) {
          if (o.insufficient) return '<tr><td>' + escapeHtml(o.name) + '</td><td colspan="2" class="no-data">' + t('brokers.calc_insufficient_data', 'нет данных о спреде — расчёт невозможен') + '</td></tr>';
          return '<tr><td>' + escapeHtml(o.name) + '</td><td>' + (o.annual ? o.annual.toFixed(2) + ' USD' : '<span class="no-data">' + t('brokers.no_data', '—') + '</span>') + '</td><td>' + o.spread + (o.account ? ' (' + escapeHtml(o.account) + ')' : '') + '</td></tr>';
        }).join('') + '</tbody></table>' +
        '<p class="calc-note">' + t('brokers.calc_note', 'Показана только комиссия (там, где известен размер контракта на объём). Стоимость спреда в деньгах не считаем без подтверждённого контрактного размера — это было бы придуманным числом.') + '</p>';
    }

    root.querySelectorAll('#calcTrades,#calcVolume,#calcInstrument').forEach(function (elm) {
      elm.addEventListener('input', recompute);
      elm.addEventListener('change', recompute);
    });
    recompute();
  }

  // ── Класс B: опросник «что для тебя важнее» ────────────────────────────────
  var QUIZ = [
    { id: 'horizon', q: t('brokers.quiz_q_horizon', 'Как долго обычно держишь позицию?'),
      options: [
        { v: 'scalp', label: t('brokers.quiz_o_scalp', 'Минуты-часы') },
        { v: 'swing', label: t('brokers.quiz_o_swing', 'Дни-недели') },
      ] },
    { id: 'fund', q: t('brokers.quiz_q_fund', 'Важна ли компенсационная схема на случай банкротства брокера?'),
      options: [
        { v: 'yes', label: t('brokers.quiz_o_yes', 'Да, это важно') },
        { v: 'no', label: t('brokers.quiz_o_no', 'Не критично') },
      ] },
  ];

  function renderQuiz(root, data, onResult) {
    var answers = {};
    function step(i) {
      if (i >= QUIZ.length) { return finish(); }
      var qz = QUIZ[i];
      root.innerHTML = '<div class="quiz-q"><p>' + qz.q + '</p>' +
        qz.options.map(function (o) { return '<button class="quiz-opt" data-v="' + o.v + '">' + o.label + '</button>'; }).join('') + '</div>';
      root.querySelectorAll('.quiz-opt').forEach(function (btn) {
        btn.addEventListener('click', function () {
          answers[qz.id] = btn.getAttribute('data-v');
          step(i + 1);
        });
      });
    }
    function finish() {
      var sortCol = 'loss', explain = '';
      if (answers.horizon === 'swing') {
        sortCol = 'loss';
        explain = t('brokers.quiz_explain_swing', 'Ты сказал, что держишь позиции днями-неделями — своп (плата за перенос) важнее спреда, но своп в этой таблице пока не собран по всем партнёрам, поэтому сортировка осталась по % теряющих.');
      } else {
        explain = t('brokers.quiz_explain_scalp', 'Короткий горизонт — важнее спред и комиссия, смотри калькулятор издержек ниже.');
      }
      if (answers.fund === 'yes') {
        explain += ' ' + t('brokers.quiz_explain_fund', 'Компенсационная схема есть не у всех юрлиц в таблице — смотри колонку «Компенсация».');
      }
      root.innerHTML = '<div class="quiz-result"><p>' + explain + '</p><button class="quiz-restart">' + t('brokers.quiz_restart', 'Пройти заново') + '</button></div>';
      root.querySelector('.quiz-restart').addEventListener('click', function () { step(0); });
      if (onResult) onResult({ sortCol: sortCol, answers: answers });
    }
    step(0);
  }

  // ── Публичный API: страница /brokers ────────────────────────────────────────
  function mountPage(rootId) {
    var root = document.getElementById(rootId);
    if (!root) return;
    _i18n.ready.then(loadData).then(function (data) {
      var tableRoot = root.querySelector('#brokersTableRoot');
      renderTable(tableRoot, data);
      var calcRoot = root.querySelector('#brokersCalcRoot');
      if (calcRoot) renderCalculator(calcRoot, data);
      var quizRoot = root.querySelector('#brokersQuizRoot');
      if (quizRoot) renderQuiz(quizRoot, data, function () { renderTable(tableRoot, data); });
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
    var country = opts.country || DEFAULT_COUNTRY;
    loadData().then(function (data) {
      var rows = buildRows(data, country).filter(function (r) { return r.loss.kind === 'value'; });
      var sorted = sortRows(rows, 'loss', 'asc');
      var thead = '<tr>' + COMPACT_COLS.map(function (c) { return '<th>' + colLabel(c) + '</th>'; }).join('') + '</tr>';
      var tbody = sorted.length
        ? sorted.map(function (r) { return renderRow(r, { compact: true }); }).join('')
        : '<tr><td colspan="' + COMPACT_COLS.length + '" class="empty-row">' + t('brokers.empty_state', 'Пока ни один партнёр не показывает актуальный процент теряющих счетов.') + '</td></tr>';
      el.innerHTML = '<div class="broker-picker"><table class="brokers-table compact"><thead>' + thead + '</thead><tbody>' + tbody + '</tbody></table>' +
        '<a class="broker-picker-more" href="/brokers">' + t('brokers.full_compare_link', 'Полное сравнение →') + '</a></div>';
    }).catch(function (err) { console.error('[BrokerPicker]', err); });
  }

  global.SBFBrokers = { mountPage: mountPage, resolveEntity: resolveEntity, loadData: loadData, COUNTRIES: COUNTRIES, DEFAULT_COUNTRY: DEFAULT_COUNTRY };
  global.BrokerPicker = { mount: mountPicker };

  if (document.getElementById('brokersPageRoot')) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { mountPage('brokersPageRoot'); });
    else mountPage('brokersPageRoot');
  }
})(window);
