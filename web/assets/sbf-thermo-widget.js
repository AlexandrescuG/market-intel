/* ============================================================================
   SBF THERMO WIDGET — общий рендер 4 чипов «Термометра дня» (SBF_Charts_
   Layer3_Spec Фаза 1), переиспользуется chart.html (интерактивная версия
   с тапами) и journal.html «Твой день» (SBF_Charts_Layer4_Spec Фаза 4 —
   акцептанс явно требует "один компонент, изменение в одном месте меняет
   оба", не копию). Только построение HTML чипов — data-fetch и обработчики
   тапов/попапов остаются в вызывающем коде (там они разные: chart.html
   открывает гистограммы/карточки, "Твой день" — просто читает).

   API: window.SBFThermoWidget.buildChipsHtml(data, symbol, helpers)
     data    — ответ /api/chart/thermo (см. day_thermo_job.py)
     symbol  — текущий инструмент (для подписи DVOL-чипа)
     helpers — {t, fmt, esc} — тонкие обёртки вокруг локального i18n/escape
               вызывающей страницы (имена этих функций отличаются между
               chart.html (t/fmt_/escapeHtml) и sbf-journal.js (t/fmt/escHtml)
               — виджет их не предполагает, принимает явно).
   ========================================================================= */
(function () {
  'use strict';

  function thermoScoreClass(score) {
    if (score == null) return 'cold';
    return score > 3 ? 'hot' : score >= 1.5 ? 'warm' : 'cold';
  }
  function fmtPoints(v) {
    if (v == null) return '—';
    const av = Math.abs(v);
    return av < 1 ? v.toFixed(4) : av < 10 ? v.toFixed(2) : Math.round(v).toLocaleString('en');
  }
  function weekdayShort(ts) {
    // toLocaleDateString(undefined, ...) берёт локаль БРАУЗЕРА, а не выбранный
    // язык сайта -- день недели всегда был на английском независимо от ru/ro/en.
    const lang = (window.sbfI18n && window.sbfI18n.lang) || 'ru';
    const locale = lang === 'ro' ? 'ro-RO' : lang === 'en' ? 'en-GB' : 'ru-RU';
    return new Date(ts * 1000).toLocaleDateString(locale, {weekday: 'short'});
  }
  function fmtCountdown(ts, t) {
    const diff = ts - Math.floor(Date.now() / 1000);
    if (diff <= 0) return null;
    const h = Math.floor(diff / 3600), m = Math.floor((diff % 3600) / 60);
    if (h >= 24) return (t('chart.event_in_days_tpl', 'через {d}д {h}ч')).replace('{d}', Math.floor(h / 24)).replace('{h}', h % 24);
    if (h > 0) return (t('chart.event_in_hm_tpl', 'через {h}ч {m}м')).replace('{h}', h).replace('{m}', m);
    return (t('chart.event_in_m_tpl', 'через {m}м')).replace('{m}', m);
  }
  function thermoBarHtml(pctl) {
    const p = pctl == null ? 0 : Math.max(0, Math.min(100, pctl));
    return `<div class="tc-bar"><i style="width:${p}%"></i></div>`;
  }
  function thermoChipHtml(key, label, value, valueCls, extra, esc, hint) {
    return `<div class="thermo-chip" data-k="${key}"${hint ? ` title="${esc(hint)}"` : ''}>
      <div class="tc-label">${esc(label)}</div>
      <div class="tc-value${valueCls ? ' ' + valueCls : ''}">${value}</div>
      ${extra || ''}
    </div>`;
  }

  function buildChipsHtml(data, symbol, helpers) {
    if (!data) return '';
    const t = helpers.t, fmt = helpers.fmt, esc = helpers.esc;

    const volVal = data.range_pctl != null
      ? fmt(t('chart.thermo_range_tpl', '{p}-й перцентиль'), {p: Math.round(data.range_pctl)}) : '—';
    const chip1 = thermoChipHtml('vol', t('chart.thermo_range_label', 'Диапазон дня'), volVal, '', thermoBarHtml(data.range_pctl), esc,
      t('chart.thermo_range_hint', 'Насколько широк сегодняшний диапазон (максимум−минимум) по сравнению с последними 60 днями. Выше 50-го перцентиля — движение шире обычного, ниже — спокойнее обычного. Нажмите для истории.'));

    const nrCls = 'tc-' + thermoScoreClass(data.news_ratio);
    const nrVal = data.news_ratio != null ? '×' + data.news_ratio.toFixed(1) : '—';
    const chip2 = thermoChipHtml('news', t('chart.thermo_news_label', 'Новостной фон'), nrVal, data.news_ratio != null ? nrCls : '', '', esc,
      t('chart.thermo_news_hint', 'Во сколько раз сегодня больше или меньше новостей по этому инструменту, чем в обычный день. ×1.0 — как обычно, выше — повышенное внимание СМИ и соцсетей. Нажмите для истории.'));

    const now = Date.now() / 1000;
    const within48h = data.next_event_ts && (data.next_event_ts - now) > 0 && (data.next_event_ts - now) <= 172800;
    // Метка чипа тоже зависит от состояния -- иначе "Ближайшее событие: Спокоен
    // до Tue" читается как бессмыслица (значение говорит "нет события", а
    // подпись утверждает обратное). "Календарь" корректно подходит к обеим
    // веткам ниже (и "спокоен до ...", и "календарь спокоен").
    let evVal, evLabel;
    if (within48h && data.next_event) {
      const cd = fmtCountdown(data.next_event_ts, t);
      evVal = esc(data.next_event.title || data.next_event.event_type) + (cd ? ' · ' + cd : '');
      evLabel = t('chart.thermo_event_label', 'Ближайшее событие');
    } else if (data.next_event_ts) {
      evVal = fmt(t('chart.thermo_calm_until_tpl', 'Спокоен до {day}'), {day: weekdayShort(data.next_event_ts)});
      evLabel = t('chart.thermo_calendar_label', 'Календарь');
    } else {
      evVal = t('chart.thermo_calm', 'Календарь спокоен');
      evLabel = t('chart.thermo_calendar_label', 'Календарь');
    }
    const chip3 = thermoChipHtml('evt', evLabel, evVal, '', '', esc,
      t('chart.thermo_event_hint', 'Ближайший важный экономический релиз или выступление, способные резко сдвинуть цену. Если рядом ничего нет — показываем, до какого дня спокойно. Нажмите, чтобы посмотреть, как инструмент реагировал на такие события раньше.'));

    let chip4;
    if (data.dvol_pctl != null) {
      const dvVal = fmt(t('chart.thermo_dvol_tpl', '{p}-й перцентиль'), {p: Math.round(data.dvol_pctl)});
      chip4 = thermoChipHtml('dvol', fmt(t('chart.thermo_dvol_label_tpl', 'Ожид. волатильность {sym}'), {sym: symbol}),
        dvVal, '', thermoBarHtml(data.dvol_pctl), esc,
        t('chart.thermo_dvol_hint', 'Подразумеваемая волатильность (ожидания рынка по амплитуде будущих движений) за последние 90 дней. Выше 50-го перцентиля — рынок закладывает более резкие движения, чем обычно.'));
    } else if (data.nearest_zone_low != null) {
      const zVal = fmt(t('chart.thermo_zone_tpl', '{dist} п.'), {dist: fmtPoints(data.dist_points)});
      chip4 = thermoChipHtml('zone', fmt(t('chart.thermo_zone_label_tpl', 'До зоны {low}–{high}'),
        {low: (+data.nearest_zone_low).toLocaleString('en'), high: (+data.nearest_zone_high).toLocaleString('en')}), zVal, '', '', esc,
        t('chart.thermo_zone_hint', 'Расстояние в пунктах до ближайшей «зоны внимания» — ценового диапазона, где цена разворачивалась исторически чаще всего (на графике — золотые линии). Чем ближе цена к зоне, тем больше шанс реакции.'));
    } else {
      chip4 = thermoChipHtml('zone', t('chart.thermo_zone_label', 'Зона внимания'), '—', '', '', esc,
        t('chart.thermo_zone_hint_empty', 'Ближайших значимых зон разворота рядом с текущей ценой не найдено.'));
    }

    return chip1 + chip2 + chip3 + chip4;
  }

  window.SBFThermoWidget = {buildChipsHtml: buildChipsHtml};
})();
