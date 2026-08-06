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

  // ── Резолв юрлица по стране ────────────────────────────────────────────────
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

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // "Компенсация"/comp, "% теряющих"/loss и "Демо без верификации"/demo убраны
  // из основной таблицы и карточки по прямому запросу 2026-08-06 -- поля
  // по-прежнему считаются в buildFieldHtml() (нужны COMPACT_COLS/BrokerPicker
  // в главе 11, который loss использует как жёсткий фильтр), просто не
  // попадают в порядок рендера главной страницы.
  var FULL_COLS = ['name', 'entity', 'licence', 'leverage', 'nbp', 'spread', 'commission', 'mindep', 'platforms'];
  var COMPACT_COLS = ['name', 'entity', 'loss', 'leverage'];
  var SORTABLE_COLS = ['name', 'entity', 'leverage', 'nbp', 'commission', 'mindep', 'platforms']; // спред -- НИКОГДА (§5: разные размеры лота, сравнение в пунктах даёт 10-кратную ошибку)

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

  function colLabel(col) {
    var map = {
      name: t('brokers.col_name', 'Брокер'),
      entity: t('brokers.col_entity', 'Юрлицо и регулятор'),
      licence: t('brokers.col_licence', 'Лицензия'),
      leverage: t('brokers.col_leverage', 'Плечо для тебя'),
      spread: t('brokers.col_spread', 'Спред'),
      commission: t('brokers.col_commission', 'Комиссия'),
      loss: t('brokers.col_loss', '% теряющих'),
      comp: t('brokers.col_comp', 'Защита при банкротстве'),
      nbp: t('brokers.col_nbp', 'Защита от отриц. баланса'),
      mindep: t('brokers.col_mindep', 'Мин. депозит'),
      platforms: t('brokers.col_platforms', 'Платформы'),
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
    // ведёт ТОЛЬКО на реестр регулятора, никогда на сайт брокера -- см. _meta.rules)
    if (e) {
      f.entity = escapeHtml(e.legal_name || '—') +
        (e.regulator ? '<div class="entity-sub">' + escapeHtml(e.regulator) + '</div>' : '') +
        (lic && lic.register_url ? sourceLink(lic.register_url, t('brokers.register_link', 'реестр')) : '');
    } else {
      f.entity = '<span class="no-data">' + t('brokers.entity_not_served', 'не обслуживает эту страну') + '</span>';
    }

    // Лицензия: unverified не показывается вовсе; register -- номер+ссылка;
    // broker_site -- номер+пометка "со слов брокера" (§4.1)
    if (!lic || !lic.licence_no || lic.licence_verification === 'unverified') {
      f.licence = dash;
    } else if (lic.licence_verification === 'register') {
      f.licence = escapeHtml(lic.licence_no) + (lic.register_url ? ' ' + sourceLink(lic.register_url, t('brokers.register_link', 'реестр')) : '');
    } else {
      f.licence = escapeHtml(lic.licence_no) + '<div class="licence-note">' + t('brokers.licence_broker_site_note', 'по данным брокера — в реестре номер не публикуется') + '</div>';
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
    if (e && e.leverage_retail) {
      f.leverage = escapeHtml(String(e.leverage_retail));
    } else if (p.leverage_retail && p.leverage_retail.value) {
      f.leverage = escapeHtml(String(p.leverage_retail.value)) +
        '<div class="spread-src">' + t('brokers.spread_by_broker', 'по данным брокера') + '</div>';
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
          return { symbol: i.symbol, val: (i.avg != null) ? i.avg : i.spread, unit: i.unit || sp.unit };
        });
      } else if (sp.sample_rows && sp.sample_rows.length) {
        items = sp.sample_rows.map(function (i) {
          return { symbol: i.symbol, val: (i.avg != null) ? i.avg : i.spread, unit: i.unit || 'пипс' };
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
      var unit = base.unit || sp.unit || '';
      f.spread = escapeHtml(base.symbol) + ' ' + escapeHtml(String(val)) + (unit ? ' ' + escapeHtml(unit) : '') +
        '<div class="spread-src">' + t('brokers.spread_by_broker', 'по данным брокера') +
        (sp.checked ? ', ' + escapeHtml(sp.checked) : '') + '</div>';
    })();

    // Комиссия. Сначала наше подтверждённое числовое поле, затем — то, что
    // брокер публикует сам (published_specs.commission), с той же подписью
    // "по данным брокера", что и спред. Пусто остаётся пустым: ноль не
    // додумываем, отсутствие комиссии по спецификации ещё не факт (§4).
    if (p.commission && p.commission.value != null) {
      f.commission = escapeHtml(p.commission.model || '') + ' ' + p.commission.value + ' ' + (p.commission.currency || '') +
        (p.commission.per_volume ? ' / ' + p.commission.per_volume : '');
    } else if (p.published_specs && p.published_specs.commission && p.published_specs.commission.value != null) {
      var pc = String(p.published_specs.commission.value);
      f.commission = escapeHtml(pc.length > 90 ? pc.slice(0, 88) + '…' : pc) +
        '<div class="spread-src">' + t('brokers.spread_by_broker', 'по данным брокера') + '</div>';
    } else {
      f.commission = dash;
    }

    f.mindep = p.min_deposit && p.min_deposit.value != null
      ? p.min_deposit.value + ' ' + (p.min_deposit.currency || '')
      : dash;

    f.platforms = (p.platforms || []).length ? escapeHtml(p.platforms.join(' / ')) : dash;

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

    var affLink = (p.links && p.links.affiliate) || '#';
    var tds = order.map(function (c) { return '<td class="col-' + c + '">' + f[c] + '</td>'; });

    return '<tr data-partner="' + p.id + '">' +
      '<td class="col-name"><a href="' + affLink + '" target="_blank" rel="noopener sponsored">' + nameHtml(p) + '</a></td>' +
      tds.join('') + '</tr>';
  }

  // ── Мобильная карточка — все поля, не подмножество (§7) ─────────────────────
  function renderCard(row) {
    var p = row.partner;
    var f = buildFieldHtml(row);
    var order = FULL_COLS.filter(function (c) { return c !== 'name'; });
    var rows = order.map(function (c) {
      return '<div class="bc-row"><span>' + colLabel(c) + '</span><div class="bc-val">' + f[c] + '</div></div>';
    }).join('');
    return '<div class="broker-card">' +
      '<div class="bc-head"><a href="' + ((p.links && p.links.affiliate) || '#') + '" target="_blank" rel="noopener sponsored">' + nameHtml(p) + '</a>' +
      (row.group ? '<span class="group-badge">' + (row.group['label_' + _i18n.lang] || row.group.label_ru) + '</span>' : '') + '</div>' +
      rows + '</div>';
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

  // ── Полная таблица (страница /brokers) ─────────────────────────────────────
  // Сортировка по умолчанию — по названию: колонка "% теряющих" (была
  // умолчанием) убрана из таблицы 2026-08-06, сортировать по невидимой
  // колонке было бы непонятно читателю.
  var _state = { country: DEFAULT_COUNTRY, sortCol: 'name', sortDir: 'asc', quizFilter: null, quizExplain: '' };

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
    var sorted = sortRows(rows, _state.sortCol, _state.sortDir);
    var isDefaultSort = (_state.sortCol === 'name' && _state.sortDir === 'asc');

    var thead = '<tr>' + FULL_COLS.map(function (c) {
      var sortable = SORTABLE_COLS.indexOf(c) !== -1;
      var active = _state.sortCol === c;
      return '<th' + (sortable ? ' data-sort="' + c + '" class="sortable' + (active ? ' active' : '') + '"' : '') + '>' +
        colLabel(c) + (active ? (_state.sortDir === 'asc' ? ' ▲' : ' ▼') : '') + '</th>';
    }).join('') + '</tr>';

    var emptyMsg = _state.quizFilter
      ? t('brokers.empty_state_filtered', 'Ни один партнёр не подошёл под условия ответа выше — это тоже честный результат, не ошибка.')
      : t('brokers.empty_state', 'Для этой страны нет ни одного партнёра с достаточно проверенными данными — таблица пуста, потому что мы не показываем непроверенное.');

    var tbody = sorted.length
      ? sorted.map(function (r) { return renderRow(r); }).join('')
      : '<tr><td colspan="' + FULL_COLS.length + '" class="empty-row">' + emptyMsg + '</td></tr>';

    var sortNote = !isDefaultSort
      ? '<div class="sort-note">' + t('brokers.sort_differs', '⚠ Сортировка отличается от умолчания (по названию, А→Я)') +
        ' <button class="reset-sort">' + t('brokers.sort_reset', 'сбросить') + '</button></div>'
      : '';

    var quizNote = _state.quizFilter
      ? '<div class="sort-note quiz-filter-note">' + t('brokers.quiz_filter_active', '⚠ Таблица отфильтрована по твоим ответам ниже') +
        ' <button class="clear-quiz-filter">' + t('brokers.sort_reset', 'сбросить') + '</button></div>'
      : '';

    root.innerHTML =
      '<div class="brokers-toolbar">' +
      '  <label class="country-picker">' + t('brokers.country_label', 'Страна') + ': ' +
      '    <select id="brokersCountry">' + COUNTRIES.map(function (c) {
            return '<option value="' + c.code + '"' + (c.code === _state.country ? ' selected' : '') + '>' + (c[_i18n.lang] || c.ru) + '</option>';
          }).join('') + '</select>' +
      '  </label>' +
      '  ' + sortNote + quizNote +
      '</div>' +
      '<div class="brokers-table-wrap"><table class="brokers-table"><thead>' + thead + '</thead><tbody>' + tbody + '</tbody></table></div>' +
      '<div class="brokers-cards">' + (sorted.length ? sorted.map(renderCard).join('') : '<div class="empty-row">' + emptyMsg + '</div>') + '</div>';

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
      _state.sortCol = 'name'; _state.sortDir = 'asc';
      renderTable(root, data);
    });
    var clearQuizBtn = root.querySelector('.clear-quiz-filter');
    if (clearQuizBtn) clearQuizBtn.addEventListener('click', function () {
      _state.quizFilter = null; _state.quizExplain = '';
      renderTable(root, data);
    });

    return rows;
  }

  // ── Публичный API: страница /brokers ────────────────────────────────────────
  function mountPage(rootId) {
    var root = document.getElementById(rootId);
    if (!root) return;
    _i18n.ready.then(function () { return Promise.all([loadData(), loadLicences()]); }).then(function (results) {
      var data = results[0];
      _licencesData = results[1];

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
    var country = opts.country || DEFAULT_COUNTRY;
    Promise.all([loadData(), loadLicences()]).then(function (results) {
      var data = results[0];
      _licencesData = _licencesData || results[1];
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
