(function (global) {
  'use strict';

  var _i18n = global.sbfI18n || { lang: 'ru', t: function (k, fb) { return fb || k; }, ready: Promise.resolve() };
  function t(key, fb) { return _i18n.t(key, fb); }

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function brokerIdFromPath() {
    var parts = location.pathname.replace(/\/+$/, '').split('/');
    return parts[parts.length - 1];
  }

  // Ссылки на другие страницы сайта должны сохранять текущий язык (/en/,
  // /ro/) -- иначе кнопка "Сравнить всех брокеров" всегда уводит на RU.
  function langPrefix() {
    return (_i18n.lang === 'en' || _i18n.lang === 'ro') ? '/' + _i18n.lang : '';
  }

  // [текст](url) -> безопасная ссылка. Только для нашего собственного контента
  // в JSON (не пользовательский ввод), но текст и адрес всё равно экранируются
  // по отдельности -- см. СПЕКА_редактура_страниц.md §3: реальные ссылки на
  // страницы брокера прямо в тексте шага/колбаута, не только в CTA-кнопках.
  function linkify(s) {
    if (s == null) return '';
    var re = /\[([^\]]+)\]\(([^)]+)\)/g;
    var out = '', last = 0, m;
    while ((m = re.exec(s))) {
      out += escapeHtml(s.slice(last, m.index));
      out += '<a href="' + escapeHtml(m[2]) + '" target="_blank" rel="noopener">' + escapeHtml(m[1]) + '</a>';
      last = re.lastIndex;
    }
    out += escapeHtml(s.slice(last));
    return out;
  }

  function paragraphs(body) {
    if (!body) return '';
    var arr = Array.isArray(body) ? body : [body];
    return arr.map(function (p) { return '<p>' + linkify(p) + '</p>'; }).join('');
  }

  // ── Снимок экрана: один сборщик на все три места ───────────────────────────
  //
  // 🔴 Раньше <img> собирался в трёх местах (врезка про юрлицо, шаг, колбаут)
  // тремя одинаковыми строками. Пока к нему добавлялись только alt и lazy,
  // это была терпимая копипаста; с приходом webp и размеров расхождение стало
  // вопросом времени, поэтому сборка одна.
  //
  // width/height — не украшение. Без них браузер не знает пропорций до
  // загрузки, отводит картинке нулевую высоту и двигает страницу, когда она
  // приходит. На гайде таких кадров до 25.
  //
  // <picture> строится ТОЛЬКО когда в данных есть img_webp. Это не
  // перестраховка: <source>, который не загрузился, НЕ откатывается на <img>
  // внутри того же <picture> — на месте картинки остаётся пустая рамка.
  // Поэтому наличие webp подтверждается данными (их проставляет
  // tools/prepare_guide_images.py по факту сборки файла), а не предполагается
  // по имени: нет поля — отдаём обычный PNG, как и раньше.
  function снимок(о, alt, кл) {
    if (!о || !о.img) return '';
    var разм = (о.img_w && о.img_h)
      ? ' width="' + о.img_w + '" height="' + о.img_h + '"' : '';
    var img = '<img src="' + escapeHtml(о.img) + '" alt="' + escapeHtml(alt || '') + '"'
      + разм + (кл ? ' class="' + кл + '"' : '')
      + ' loading="lazy" decoding="async">';
    if (!о.img_webp) return img;
    return '<picture><source type="image/webp" srcset="'
      + escapeHtml(о.img_webp) + '">' + img + '</picture>';
  }

  // ── Блок: врезка про юрлицо (только регистрация) ───────────────────────────
  function renderEntity(e) {
    if (!e) return '';
    if (e.unresolved) {
      return '<div class="entity-box entity-unresolved">' +
        '<div class="entity-box-title">' + escapeHtml(e.title || t('guide.entity_unresolved_title', 'Юрлицо не установлено')) + '</div>' +
        paragraphs(e.body) +
        (e.checked ? '<p class="entity-confirm">' + t('guide.checked_on', 'Проверено') + ' ' + escapeHtml(e.checked) + '</p>' : '') +
        '</div>';
    }
    var rows = [
      ['guide.entity_legal_name', 'Юрлицо', escapeHtml(e.legal_name)],
      ['guide.entity_jurisdiction', 'Юрисдикция', escapeHtml(e.jurisdiction)],
      ['guide.entity_regulator', 'Регулятор', e.regulator ? escapeHtml(e.regulator) : '<span class="entity-no-register">' + t('guide.entity_no_regulator', 'не назван') + '</span>'],
      ['guide.entity_licence', 'Лицензия', e.licence_no ? escapeHtml(e.licence_no) : '<span class="entity-no-register">' + t('guide.entity_no_licence', 'нет') + '</span>']
    ].map(function (r) {
      return '<div class="entity-row"><span>' + t(r[0], r[1]) + '</span><span>' + r[2] + '</span></div>';
    }).join('');

    var register = e.register_url
      ? '<div class="entity-row"><span>' + t('guide.entity_register', 'Реестр') + '</span><span><a href="' + escapeHtml(e.register_url) + '" target="_blank" rel="noopener">' + t('guide.entity_register_link', 'проверить') + '</a></span></div>'
      : (e.register_note ? '<div class="entity-row"><span>' + t('guide.entity_register', 'Реестр') + '</span><span class="entity-no-register">' + escapeHtml(e.register_note) + '</span></div>' : '');

    var confirmClass = e.confirmed ? '' : ' unconfirmed';
    var confirmNote = e.confirm_note ? '<p class="entity-confirm' + confirmClass + '">' + escapeHtml(e.confirm_note) + '</p>' : '';

    var missing = (e.missing && e.missing.length)
      ? '<div class="entity-missing"><div>' + t('guide.entity_missing_title', 'У этого юрлица нет') + '</div><ul>' +
        e.missing.map(function (m) { return '<li>' + escapeHtml(m) + '</li>'; }).join('') + '</ul></div>'
      : '';

    return '<div class="entity-box">' +
      '<div class="entity-box-title">' + t('guide.entity_box_title', 'С кем на самом деле заключается договор') + '</div>' +
      снимок(e, t('guide.entity_box_title', 'С кем на самом деле заключается договор')) +
      rows + register +
      (e.quote ? '<p class="entity-quote">' + escapeHtml(e.quote) + '</p>' : '') +
      confirmNote + missing +
      '</div>';
  }

  // ── Блок: шаги со скриншотами ───────────────────────────────────────────────
  // img: null (ключ ЕСТЬ) -- кадр пытались снять, не получилось технически,
  // показываем плашку-заглушку. img вообще отсутствует в объекте -- шаг
  // изначально текстовый (например, "откройте страницу инструмента"), плашка
  // здесь была бы враньём про несуществующую попытку съёмки.
  function renderStep(s, i) {
    // alt берём из подписи шага, а не пустой: скриншот здесь несёт смысл
    // (какое юрлицо названо на экране), а не декорация. loading="lazy" —
    // на странице до 23 таких кадров, все грузились сразу (аудит 14.08.2026).
    var media = s.img
      ? снимок(s, String(s.caption || '').replace(/<[^>]*>/g, '').slice(0, 120))
      : ('img' in s ? '<div class="guide-step-nomedia">' + t('guide.step_no_image', 'Скриншот этого шага недоступен') + '</div>' : '');
    return '<div class="guide-step">' +
      '<div class="guide-step-cap"><span class="guide-step-num">' + (i + 1) + '</span>' + linkify(s.caption) + '</div>' +
      media +
      (s.note ? '<div class="guide-step-note">' + linkify(s.note) + '</div>' : '') +
      '</div>';
  }

  // ── Блок: колбаут fact/gap/note ─────────────────────────────────────────────
  function renderCallout(b) {
    return '<div class="callout ' + escapeHtml(b.style || 'note') + '">' +
      (b.title ? '<div class="callout-title">' + linkify(b.title) + '</div>' : '') +
      paragraphs(b.body) +
      снимок(b, String(b.title || '').replace(/<[^>]*>/g, '').slice(0, 120)) +
      '</div>';
  }

  // ── Блок: произвольная таблица (условия торговли, факты) ───────────────────
  // 🔴 Название колонки уезжает в data-col КАЖДОЙ ячейки, а не только в шапку.
  // На телефоне таблица разворачивается в карточки (CSS в broker_guide.html):
  // шапка скрыта, и без подписи внутри ячейки «5 USD в месяц после 90 дней»
  // повисает без объяснения, что это. Подпись рисуется из ::before по
  // data-col — поэтому она обязана быть в разметке, а не только в <th>.
  function renderTable(b) {
    var cols = b.columns || [];
    var thead = '<tr>' + cols.map(function (c) { return '<th>' + escapeHtml(c) + '</th>'; }).join('') + '</tr>';
    var tbody = b.rows.map(function (row) {
      return '<tr>' + row.map(function (cell, i) {
        return '<td data-col="' + escapeHtml(cols[i] || '') + '">' + escapeHtml(cell) + '</td>';
      }).join('') + '</tr>';
    }).join('');
    // data-cols нужен мобильной вёрстке: в таблице ровно из двух колонок
    // подпись «Значение» над значением — шум (см. CSS в broker_guide.html).
    return '<table class="guide-table" data-cols="' + cols.length + '"><thead>' + thead + '</thead><tbody>' + tbody + '</tbody></table>' +
      (b.caption ? '<p class="guide-table-caption">' + linkify(b.caption) + '</p>' : '');
  }

  function renderBlock(b) {
    switch (b.type) {
      case 'steps': return b.items.map(renderStep).join('');
      case 'entity': return renderEntity(b);
      case 'callout': return renderCallout(b);
      case 'table': return renderTable(b);
      case 'text': return paragraphs(b.body);
      default: return '';
    }
  }

  function renderProcess(proc, n) {
    var meta = (proc.platform || proc.captured)
      ? '<div class="guide-meta">' + [proc.platform, proc.captured ? t('guide.captured_on', 'по состоянию на') + ' ' + proc.captured : null]
          .filter(Boolean).map(escapeHtml).join(' · ') + '</div>'
      : '';
    var needed = (proc.needed && proc.needed.length)
      ? '<div class="guide-needed"><div>' + t('guide.needed_title', 'Что понадобится') + '</div><ul>' +
        proc.needed.map(function (x) { return '<li>' + escapeHtml(x) + '</li>'; }).join('') + '</ul></div>'
      : '';
    var intro = proc.intro ? '<p class="guide-intro">' + linkify(proc.intro) + '</p>' : '';
    var blocks = (proc.blocks || []).map(renderBlock).join('');
    return '<h2 class="guide-h2"><span class="guide-h2-n">' + n + '</span>' + escapeHtml(proc.label) + '</h2>' +
      meta + intro + needed + blocks;
  }

  function render(broker) {
    document.title = broker.name + ' — ' + t('guide.title_suffix', 'инструкция по брокеру');
    var accTag = broker.account_kind === 'demo' ? 'demo' : 'real';
    var accLabel = broker.account_kind === 'demo' ? t('guide.tag_demo', 'демо') : t('guide.tag_real', 'реальный');
    var head = '<div class="guide-head"><img src="' + escapeHtml(broker.logo) + '" alt="' + escapeHtml(broker.name) + '">' +
      '<div><h1 class="guide-h1">' + escapeHtml(broker.name) + '</h1>' +
      (broker.account_kind ? '<div class="guide-account">' + (broker.account_label ? escapeHtml(broker.account_label) + ' ' : '') + '<span class="tag ' + accTag + '">' + accLabel + '</span></div>' : '') +
      '</div></div>';
    var lead = broker.lead ? '<p class="guide-lead">' + escapeHtml(broker.lead) + '</p>' : '';
    var processes = (broker.processes || []).map(function (p, i) { return renderProcess(p, i + 1); }).join('');
    var cta = '<div class="guide-cta">' +
      '<a class="primary" href="' + escapeHtml(broker.affiliate) + '" target="_blank" rel="noopener sponsored">' + t('guide.cta_open', 'Открыть счёт у') + ' ' + escapeHtml(broker.name) + '</a>' +
      '<a class="secondary" href="' + escapeHtml(langPrefix() + (broker.table_link || '/brokers')) + '">' + t('guide.cta_compare', 'Сравнить всех брокеров') + '</a>' +
      '</div>';
    var risk = '<aside class="rwarn" role="note"><p>' + t('brokers.risk_warning_full', '') + '</p></aside>';

    document.getElementById('guideContent').innerHTML = head + lead + processes + cta + risk;
  }

  function mount() {
    var id = brokerIdFromPath();
    _i18n.ready.then(function () {
      // Данные гайда переведены отдельными файлами per СПЕКА-требование "перевод
      // всех страниц брокеров" -- <id>.json остаётся RU (умолчание), <id>.en.json/
      // <id>.ro.json это полные переводы той же структуры. Если файла для языка
      // нет (ещё не переведён брокер), тихо падаем обратно на RU, а не на пустую
      // страницу -- отсутствие перевода не должно ломать чтение факта.
      // Кэш-бастер -- без него правка ТОЛЬКО JSON-данных (без изменения самого
      // guide.js) не долетала бы до вернувшегося читателя без хард-релоада:
      // static-serving в serve.py (SimpleHTTPRequestHandler) не шлёт
      // Cache-Control, версия в query у guide.js на этот случай не спасает.
      // Тот же приём, что уже в brokers.js -> loadData()/loadLicences().
      var suffix = (_i18n.lang === 'en' || _i18n.lang === 'ro') ? '.' + _i18n.lang : '';
      var bust = '?t=' + Date.now();
      return fetch('/data/guides/' + id + suffix + '.json' + bust).then(function (r) {
        if (r.ok) return r.json();
        if (suffix) return fetch('/data/guides/' + id + '.json' + bust).then(function (r2) {
          if (!r2.ok) throw new Error('not found');
          return r2.json();
        });
        throw new Error('not found');
      });
    }).then(render).catch(function (err) {
      document.getElementById('guideContent').innerHTML = '<div class="guide-error">' + t('guide.load_error', 'Инструкция для этого брокера пока не готова.') + '</div>';
      console.error('[guide]', err);
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();
})(window);
