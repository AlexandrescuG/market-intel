/**
 * sbf-journal.js v3 — Дневник сделок + Поведенческое зеркало + Дисциплина (Part 1+2+3).
 */
(function () {
  'use strict';

  /* ─── i18n ───
     Этот файл — обычный <script src> без defer/async, подключён на
     journal.html ДО i18n.js (у i18n.js есть defer, значит его исполнение
     откладывается до конца парсинга документа) — т.е. sbf-journal.js
     выполняется РАНЬШЕ, чем window.sbfI18n появляется. Поэтому t() не
     кэширует window.sbfI18n в замыкании, а смотрит на него при каждом
     вызове — к моменту реальных вызовов (клики, колбэки загрузки данных,
     DOMContentLoaded/init()) defer-скрипты уже отработали. */
  function t(key, fallback) {
    var i = window.sbfI18n;
    return i ? i.t(key, fallback) : (fallback || key);
  }

  function _patchI18n(root) {
    if ((window.sbfI18n && window.sbfI18n.lang) === 'ru') return;
    var tt = window.sbfI18n ? window.sbfI18n.t : function (k, fb) { return fb || k; };
    (root || document).querySelectorAll('[data-i18n]').forEach(function (node) {
      node.textContent = tt(node.getAttribute('data-i18n'), node.textContent);
    });
  }

  // ── Константы ────────────────────────────────────────────────────────────
  function emoLabel(emo) {
    var map = {
      calmness:   'journal.emo_calm',
      revenge:    'journal.emo_revenge',
      confidence: 'journal.emo_confidence',
      fear:       'journal.emo_fear',
      greed:      'journal.emo_greed',
      impatience: 'journal.emo_impatience',
    };
    var k = map[emo.key];
    return k ? t(k, emo.label) : emo.label; // fomo — жаргон, не переводится
  }

  var EMOTIONS = [
    { key: 'calmness',   ico: '🧘', label: 'Спокойствие' },
    { key: 'fomo',       ico: '😰', label: 'FOMO'        },
    { key: 'revenge',    ico: '😡', label: 'Месть'       },
    { key: 'confidence', ico: '💪', label: 'Уверенность' },
    { key: 'fear',       ico: '😨', label: 'Страх'       },
    { key: 'greed',      ico: '🤑', label: 'Жадность'    },
    { key: 'impatience', ico: '⚡', label: 'Нетерпение'  },
  ];

  var SETUP_PRESETS = [
    'breakout','pullback','reversal','false_breakout',
    'trend_line','ob_retest','fvg','sweep','range','scalp','wick_grab',
  ];

  // ── Состояние ──────────────────────────────────────────────────────────────
  var _trades   = [];
  var _chart    = null;
  var _curPage  = 0;
  var _pageSize = 50;
  var _behavioral = null;

  // Meta form state
  var _metaQueue      = [];   // очередь незаполненных сделок
  var _metaQueueIdx   = 0;    // текущий индекс в очереди
  var _metaEmoOpen    = 'calmness';
  var _metaEmoClose   = 'calmness';
  var _metaFollowed   = true;
  var _metaSaveDone   = false; // флаг — нажата кнопка «Готово»

  // Analytics tab
  var _analyticsTab = 'setup';

  // Discipline state
  var _disciplineConfig = [];
  var _discEvals = {};    // trade_id → { criterion: passed }
  var _discAdvanced = false;

  // ── Утилиты ───────────────────────────────────────────────────────────────
  function fmt(n, d) {
    if (n == null || isNaN(n)) return '—';
    return (+n).toFixed(d == null ? 2 : d);
  }
  function fmtDate(s) {
    if (!s) return '—';
    return s.replace('T', ' ').slice(0, 16);
  }
  function fmtMin(m) {
    if (!m && m !== 0) return '—';
    if (m < 60)  return Math.round(m) + ' ' + t('journal.unit_min_short', 'м');
    return (m / 60).toFixed(1) + ' ' + t('journal.unit_hour_short', 'ч');
  }
  function el(id) { return document.getElementById(id); }
  function escHtml(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // ── API ───────────────────────────────────────────────────────────────────
  function apiFetch(path, opts) {
    return fetch(path, opts).then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.error || r.status); });
      return r.json();
    });
  }

  // ── Загрузка ──────────────────────────────────────────────────────────────
  function loadAll() {
    return Promise.all([loadTrades(), loadStats(), loadCurve(), loadBehavioral(), loadDiscipline(), loadBrief(), loadAlertRules(), loadNotifications(), loadSetups(), loadChecklist(), loadTiltState(), loadTiltHeatmap(), loadGameOverview(), loadGoals(), loadSeasons(), loadAccount()]);
  }

  function loadTrades(page) {
    page = page || 0;
    _curPage = page;
    return apiFetch('/api/journal/trades?limit=' + _pageSize + '&offset=' + (page * _pageSize))
      .then(function (d) {
        _trades = d.trades || [];
        renderTable(_trades);
        renderPager(d.total, page);
      }).catch(function (e) { showError(t('journal.error_loading_prefix', 'Ошибка загрузки: ') + e.message); });
  }

  function loadStats() {
    return apiFetch('/api/journal/stats')
      .then(function (d) { renderStats(d); })
      .catch(function () {});
  }

  function loadCurve() {
    return apiFetch('/api/journal/equity-curve')
      .then(function (d) { renderChart(d); })
      .catch(function () {});
  }

  function loadBehavioral() {
    return apiFetch('/api/journal/behavioral')
      .then(function (d) {
        _behavioral = d;
        renderBehavioral(d);
      }).catch(function () {});
  }

  function loadDiscipline() {
    return apiFetch('/api/journal/discipline')
      .then(function (d) {
        _disciplineConfig = d.config || [];
        _discAdvanced     = d.advanced_mode || false;
        renderDiscipline(d);
      }).catch(function () {});
  }

  // ══════════════════════════════════════════════════════════════════════════
  // ── Оценка дисциплины (Part 3) ─────────────────────────────────────────────
  // ══════════════════════════════════════════════════════════════════════════

  function renderDiscipline(d) {
    var section = el('jDiscSection');
    if (!section) return;
    if (!d || d.total_evaluated === 0 && !d.config.some(function (c) { return c.enabled; })) {
      section.style.display = 'none';
      return;
    }
    section.style.display = 'block';

    var score = d.score || {};
    var val   = score.current_score;

    // Ring color
    var ring = el('jDiscRing');
    if (ring) {
      ring.textContent = val != null ? val : '—';
      ring.className = 'j-disc-ring';
      if (val >= 86)      ring.classList.add('score-hi');
      else if (val >= 41) ring.classList.add('score-md');
      else                ring.classList.add('score-lo');
    }

    // Trend
    var trendEl = el('jDiscTrend');
    if (trendEl) {
      var tMap = { up: '↑', down: '↓', stable: '→' };
      var tCls = { up: 'up', down: 'dn', stable: 'st' };
      trendEl.textContent = tMap[score.trend] || '→';
      trendEl.className = 'j-disc-trend ' + (tCls[score.trend] || 'st');
    }

    var cnt = el('jDiscEvalCount');
    if (cnt) cnt.textContent = d.total_evaluated + ' ' + t('journal.trades_word', 'сделок');

    // Worst criterion
    var worstEl = el('jDiscWorst');
    if (worstEl) {
      if (score.worst_criterion) {
        var cInfo = _disciplineConfig.find(function (c) { return c.criterion === score.worst_criterion; });
        var lbl = cInfo ? (cInfo.ico + ' ' + cInfo.label) : score.worst_criterion;
        worstEl.innerHTML = t('journal.weak_spot_prefix', 'Слабое место: ') + '<strong>' + escHtml(lbl) + '</strong>';
      } else {
        worstEl.innerHTML = d.total_evaluated > 0
          ? t('journal.all_criteria_met', '✅ Все критерии выполняются')
          : t('journal.rate_first_trade', 'Оцените первую сделку');
      }
    }

    // Streaks
    var streaksEl = el('jDiscStreaks');
    if (streaksEl && d.streaks) {
      streaksEl.innerHTML = _disciplineConfig.filter(function (c) { return c.enabled; }).map(function (c) {
        var n = d.streaks[c.criterion] || 0;
        var hot = n >= 5;
        return '<div class="j-streak-chip' + (hot ? ' s-hot' : '') + '">'
          + '<span>' + c.ico + '</span>'
          + '<span class="s-n">' + n + '✓</span>'
          + '</div>';
      }).join('');
    }

    // Breakout alert
    var breakout = d.breakout || {};
    var alertEl = el('jBreakoutAlert');
    var alertText = el('jBreakoutText');
    if (breakout.detected) {
      if (alertEl) alertEl.style.display = 'flex';
      if (alertText) alertText.innerHTML =
        '<strong>' + t('journal.discipline_breakout_title', 'Дисциплинарный пробой') + '</strong> — '
        + t('journal.discipline_breakout_desc', 'вы нарушили критические правила стратегии в последней сделке ')
        + '(' + t('journal.discipline_breakout_score_prefix', 'балл: ') + breakout.last_score + '%'
        + t('journal.discipline_breakout_avg_prefix', ' vs средний: ') + breakout.avg_score + '%). '
        + t('journal.discipline_breakout_pause', 'Сделайте паузу и зафиксируйте состояние.');
    } else {
      if (alertEl) alertEl.style.display = 'none';
    }
  }

  // ── Discipline Config Modal ────────────────────────────────────────────────
  function openDiscConfig() {
    var m = el('jDiscConfigModal');
    if (m) m.style.display = 'flex';
    renderDiscConfigTable(_disciplineConfig, _discAdvanced);
    el('jDiscConfigErr') && (el('jDiscConfigErr').textContent = '');
    // Отметить активный пресет
    document.querySelectorAll('.j-preset-btn').forEach(function (b) { b.classList.remove('on'); });
  }
  function closeDiscConfig() {
    var m = el('jDiscConfigModal');
    if (m) m.style.display = 'none';
  }

  function renderDiscConfigTable(config, advMode) {
    var tbody = el('jCritTableBody');
    if (!tbody) return;
    tbody.innerHTML = config.map(function (c) {
      var chk = c.enabled ? 'checked' : '';
      return '<tr>'
        + '<td>' + c.ico + ' ' + escHtml(c.label) + '</td>'
        + '<td style="text-align:center"><input type="checkbox" class="j-crit-en" data-crit="' + c.criterion + '" ' + chk + '></td>'
        + '<td><input type="number" class="j-crit-wt" data-crit="' + c.criterion + '" min="0" max="3" step="0.5" value="' + c.weight + '"></td>'
        + '</tr>';
    }).join('');
    var adv = el('jAdvModeChk');
    if (adv) adv.checked = advMode;
  }

  function applyPreset(preset) {
    apiFetch('/api/journal/discipline/preset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset: preset }),
    }).then(function (r) {
      _disciplineConfig = r.config || _disciplineConfig;
      renderDiscConfigTable(_disciplineConfig, _discAdvanced);
      document.querySelectorAll('.j-preset-btn').forEach(function (b) {
        b.classList.toggle('on', b.dataset.preset === preset);
      });
    }).catch(function (e) { console.error(e); });
  }

  function saveDiscConfig() {
    var errEl = el('jDiscConfigErr');
    if (errEl) errEl.textContent = '';
    var wb = el('jDiscWellbeing');
    if (wb) wb.style.display = 'none';

    var adv = el('jAdvModeChk');
    var advanced = adv ? adv.checked : false;

    var configList = _disciplineConfig.map(function (c) {
      var enEl = document.querySelector('.j-crit-en[data-crit="' + c.criterion + '"]');
      var wtEl = document.querySelector('.j-crit-wt[data-crit="' + c.criterion + '"]');
      return {
        criterion: c.criterion,
        enabled:   enEl ? enEl.checked : c.enabled,
        weight:    wtEl ? parseFloat(wtEl.value) || 0 : c.weight,
      };
    });

    apiFetch('/api/journal/discipline/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: configList, advanced_mode: advanced }),
    }).then(function (r) {
      if (!r.ok) {
        if (wb) { wb.style.display = 'block'; el('jDiscWellbeingText').textContent = r.error; }
        if (errEl) errEl.textContent = r.error || t('journal.error_generic', 'Ошибка');
        return;
      }
      _discAdvanced = advanced;
      closeDiscConfig();
      loadDiscipline();
    }).catch(function (e) {
      if (errEl) errEl.textContent = t('journal.error_prefix', 'Ошибка: ') + e.message;
    });
  }

  // ── Discipline в мета-форме ───────────────────────────────────────────────
  function loadDiscEvalForTrade(tradeId) {
    return apiFetch('/api/journal/discipline/eval/' + tradeId)
      .then(function (evals) {
        _discEvals = {};
        (evals || []).forEach(function (e) { _discEvals[e.criterion] = e.passed; });
        renderMetaDiscSection(tradeId);
      }).catch(function () {
        _discEvals = {};
        renderMetaDiscSection(tradeId);
      });
  }

  function renderMetaDiscSection(tradeId) {
    var section = el('jMetaDiscSection');
    var rows    = el('jMetaDiscRows');
    if (!section || !rows) return;

    var enabled = _disciplineConfig.filter(function (c) { return c.enabled; });
    if (!enabled.length) { section.style.display = 'none'; return; }
    section.style.display = 'block';

    rows.innerHTML = enabled.map(function (c) {
      var curVal = _discEvals[c.criterion];
      var autoLabel = c.auto ? '<span class="j-crit-auto">' + t('journal.auto_short', 'авто') + '</span>' : '';
      var yesCl = curVal === true  ? ' on' : '';
      var noCl  = curVal === false ? ' on' : '';
      return '<div class="j-disc-crit-row">'
        + '<div class="j-disc-crit-lbl">' + c.ico + ' <span>' + escHtml(c.label) + '</span>' + autoLabel + '</div>'
        + '<div class="j-crit-pass-btns">'
        + '<button type="button" class="j-crit-pb yes' + yesCl + '" data-crit="' + c.criterion + '" data-val="1">✓</button>'
        + '<button type="button" class="j-crit-pb no'  + noCl  + '" data-crit="' + c.criterion + '" data-val="0">✗</button>'
        + '</div></div>';
    }).join('');
  }

  // ── Таблица ────────────────────────────────────────────────────────────────
  function renderTable(trades) {
    var tbody = el('jTradesTbody');
    if (!tbody) return;
    if (!trades.length) {
      tbody.innerHTML = '<tr><td colspan="10" class="j-empty">' + t('journal.no_trades_msg', 'Сделок нет. Добавьте первую через «+» или импорт.') + '</td></tr>';
      return;
    }
    // NB: считаем переводы ДО .map(function (t) {...}) — параметр колбэка
    // называется "t" (сделка) и затеняет i18n-хелпер t() внутри замыкания.
    var editAnalysisTip = t('journal.change_analysis_tip', 'Изменить анализ');
    var addAnalysisTip  = t('journal.add_analysis_tip', 'Добавить анализ');
    var deleteTip        = t('journal.delete_tip', 'Удалить');
    tbody.innerHTML = trades.map(function (t) {
      var pnlCl = +t.pnl >= 0 ? 'j-up' : 'j-dn';
      var rCl   = +t.pnl_r >= 0 ? 'j-up' : 'j-dn';
      var dirIc = t.dir === 'buy' ? '▲' : '▼';
      var dirCl = t.dir === 'buy' ? 'j-up' : 'j-dn';
      var hasMeta = t.has_meta;
      var journalBtn = hasMeta
        ? '<button class="j-journal-btn j-journaled" data-id="' + t.id + '" title="' + editAnalysisTip + '">✏️</button>'
        : '<button class="j-journal-btn j-unjournaled" data-id="' + t.id + '" title="' + addAnalysisTip + '">📝</button>';
      return '<tr>'
        + '<td><span class="j-sym">' + escHtml(t.symbol) + '</span></td>'
        + '<td><span class="' + dirCl + '">' + dirIc + ' ' + t.dir.toUpperCase() + '</span></td>'
        + '<td class="j-mono">' + fmt(t.size, 2) + '</td>'
        + '<td class="j-mono">' + fmt(t.entry_price, 5) + '</td>'
        + '<td class="j-mono">' + fmt(t.exit_price, 5) + '</td>'
        + '<td class="j-mono ' + pnlCl + '">' + (t.pnl >= 0 ? '+' : '') + fmt(t.pnl, 2) + '</td>'
        + '<td class="j-mono ' + rCl + '">' + (t.pnl_r >= 0 ? '+' : '') + fmt(t.pnl_r, 2) + 'R</td>'
        + '<td class="j-mono j-muted">' + fmtDate(t.close_ts) + '</td>'
        + '<td>' + journalBtn + '</td>'
        + '<td><button class="j-del-btn" data-id="' + t.id + '" title="' + deleteTip + '">✕</button></td>'
        + '</tr>';
    }).join('');
  }

  function renderPager(total, page) {
    var wrap = el('jPager');
    if (!wrap) return;
    var pages = Math.ceil(total / _pageSize);
    if (pages <= 1) { wrap.innerHTML = ''; return; }
    var html = '';
    if (page > 0) html += '<button class="j-pg-btn" data-p="' + (page - 1) + '">‹</button>';
    html += '<span class="j-pg-info">' + t('journal.page_abbrev', 'стр.') + ' ' + (page + 1) + ' / ' + pages + '</span>';
    if (page < pages - 1) html += '<button class="j-pg-btn" data-p="' + (page + 1) + '">›</button>';
    wrap.innerHTML = html;
  }

  // ── Статистика ─────────────────────────────────────────────────────────────
  function renderStats(s) {
    function set(id, v, cls) {
      var e = el(id);
      if (e) { e.textContent = v; if (cls) e.className = 'j-stat-val ' + cls; }
    }
    set('jStatTotal',   s.total || 0);
    set('jStatWinrate', (s.winrate || 0) + '%');
    set('jStatAvgR',    (s.avg_r >= 0 ? '+' : '') + fmt(s.avg_r, 2) + 'R',
        s.avg_r >= 0 ? 'j-stat-val j-up' : 'j-stat-val j-dn');
    set('jStatPnl',     (s.total_pnl >= 0 ? '+' : '') + fmt(s.total_pnl, 2),
        s.total_pnl >= 0 ? 'j-stat-val j-up' : 'j-stat-val j-dn');
  }

  // ── Equity Curve ───────────────────────────────────────────────────────────
  function renderChart(curve) {
    var canvas = el('jEqChart');
    if (!canvas) return;
    if (typeof Chart === 'undefined') return;
    if (_chart) { _chart.destroy(); _chart = null; }
    if (!curve.length) {
      canvas.parentElement.innerHTML = '<div class="j-empty" style="padding:28px;text-align:center">' + t('journal.no_data', 'Нет данных') + '</div>';
      return;
    }
    var labels = curve.map(function (c) { return fmtDate(c.ts); });
    var data   = curve.map(function (c) { return c.eq_r; });
    var ctx = canvas.getContext('2d');
    var grad = ctx.createLinearGradient(0, 0, 0, 200);
    grad.addColorStop(0, 'rgba(30,142,90,0.25)');
    grad.addColorStop(1, 'rgba(30,142,90,0)');
    _chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: 'Equity (R)',
          data: data,
          borderColor: '#C9A227',
          backgroundColor: grad,
          borderWidth: 2,
          pointRadius: data.length > 60 ? 0 : 3,
          fill: true,
          tension: 0.2,
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: function (ctx) {
            return 'Equity: ' + (ctx.raw >= 0 ? '+' : '') + ctx.raw.toFixed(2) + 'R';
          }}}
        },
        scales: {
          x: { ticks: { maxTicksLimit: 8, font: { family: "'JetBrains Mono'" } } },
          y: { ticks: { font: { family: "'JetBrains Mono'" } }, grid: { color: 'rgba(0,0,0,0.04)' } }
        }
      }
    });
  }

  // ══════════════════════════════════════════════════════════════════════════
  // ── Поведенческое зеркало (Part 2) ────────────────────────────────────────
  // ══════════════════════════════════════════════════════════════════════════

  function renderBehavioral(d) {
    var section = el('jBehavioralSection');
    if (!section) return;

    var hasData = d.queue_count > 0
      || d.insights.length > 0
      || d.setup_metrics.length > 0
      || d.emotion_metrics.length > 0;

    if (!hasData) { section.style.display = 'none'; return; }
    section.style.display = 'block';

    // Queue banner
    var banner = el('jQueueBanner');
    var qCount = el('jQueueCount');
    if (d.queue_count > 0) {
      if (banner) banner.style.display = 'flex';
      if (qCount) qCount.textContent = d.queue_count;
      _metaQueue = d.queue_trades || [];
    } else {
      if (banner) banner.style.display = 'none';
    }

    // Revenge warning
    var rWarn = el('jRevengeWarn');
    var rText = el('jRevengeWarnText');
    if (d.revenge_clusters && d.revenge_clusters.is_revenge_cluster) {
      if (rWarn) rWarn.style.display = 'flex';
      if (rText) rText.textContent =
        t('journal.revenge_cluster_prefix', 'Обнаружен кластер «месть»: ') + d.revenge_clusters.trade_ids.length +
        t('journal.revenge_cluster_suffix', ' сделок открыты в течение 30 мин после убытка с увеличенным объёмом.');
    } else {
      if (rWarn) rWarn.style.display = 'none';
    }

    // Insights
    renderInsights(d.insights);

    // Holding duration
    var holding = d.holding_duration;
    var holdWrap = el('jHoldingWrap');
    if (holding && (holding.avg_win_min > 0 || holding.avg_loss_min > 0)) {
      if (holdWrap) holdWrap.style.display = 'block';
      var w = el('jHoldWin'), l = el('jHoldLoss');
      if (w) w.textContent = fmtMin(holding.avg_win_min);
      if (l) l.textContent = fmtMin(holding.avg_loss_min);
    }

    // Analytics tables
    var analyticsWrap = el('jAnalyticsWrap');
    if (d.setup_metrics.length > 0 || d.emotion_metrics.length > 0) {
      if (analyticsWrap) analyticsWrap.style.display = 'block';
      renderSetupTable(d.setup_metrics);
      renderEmoTable(d.emotion_metrics);
    }
  }

  function renderInsights(insights) {
    var list = el('jInsightsList');
    if (!list) return;
    if (!insights || !insights.length) { list.innerHTML = ''; return; }
    list.innerHTML = insights.map(function (txt) {
      var cls = 'info';
      var ico = 'ℹ️';
      if (txt.indexOf('падал') >= 0 || txt.indexOf('убыток') >= 0) { cls = 'warn'; ico = '⚠️'; }
      if (txt.indexOf('лучший') >= 0 || txt.indexOf('Лучший') >= 0) { cls = 'tip';  ico = '✅'; }
      if (txt.indexOf('пересиживани') >= 0) { cls = 'warn'; ico = '⏱️'; }
      return '<div class="j-insight ' + cls + '">'
        + '<span class="j-insight-ico">' + ico + '</span>'
        + '<span>' + escHtml(txt) + '</span></div>';
    }).join('');
  }

  function renderSetupTable(metrics) {
    var wrap = el('jSetupTableWrap');
    if (!wrap) return;
    if (!metrics.length) {
      wrap.innerHTML = '<div class="j-empty" style="padding:16px">' + t('journal.need_min_trades_setup', 'Нужно ≥3 сделок с одним сетапом и эмоцией для аналитики.') + '</div>';
      return;
    }
    wrap.innerHTML = '<table>'
      + '<thead><tr><th>' + t('journal.th_setup', 'Сетап') + '</th><th>' + t('journal.emotion_label', 'Эмоция') + '</th><th>' + t('journal.th_trades', 'Сделок') + '</th>'
      + '<th>Win%</th><th>' + t('journal.expectancy_r_abbrev', 'МО (R)') + '</th><th>Avg Win</th><th>Avg Loss</th></tr></thead>'
      + '<tbody>' + metrics.map(function (r) {
        var emo = EMOTIONS.find(function (e) { return e.key === r.emo_open; });
        var emoStr = emo ? (emo.ico + ' ' + escHtml(emoLabel(emo))) : r.emo_open;
        var meCl = +r.mathematical_expectancy_r >= 0 ? 'j-up' : 'j-dn';
        return '<tr>'
          + '<td><span class="j-sym">' + escHtml(r.setup_tag || '—') + '</span></td>'
          + '<td>' + emoStr + '</td>'
          + '<td class="j-mono">' + r.total_trades + '</td>'
          + '<td class="j-mono">' + fmt(r.winrate_percent, 1) + '%</td>'
          + '<td class="j-mono ' + meCl + '">' + (r.mathematical_expectancy_r >= 0 ? '+' : '') + fmt(r.mathematical_expectancy_r, 2) + 'R</td>'
          + '<td class="j-mono j-up">+' + fmt(r.avg_win_r, 2) + 'R</td>'
          + '<td class="j-mono j-dn">' + fmt(r.avg_loss_r, 2) + 'R</td>'
          + '</tr>';
      }).join('') + '</tbody></table>';
  }

  function renderEmoTable(metrics) {
    var wrap = el('jEmoTableWrap');
    if (!wrap) return;
    if (!metrics.length) {
      wrap.innerHTML = '<div class="j-empty" style="padding:16px">' + t('journal.need_meta_for_emo_analysis', 'Добавьте метаданные к сделкам для эмоционального анализа.') + '</div>';
      return;
    }
    wrap.innerHTML = '<table>'
      + '<thead><tr><th>' + t('journal.emotion_on_open', 'Эмоция входа') + '</th><th>' + t('journal.th_trades', 'Сделок') + '</th><th>Win%</th><th>' + t('journal.expectancy_r_abbrev', 'МО (R)') + '</th></tr></thead>'
      + '<tbody>' + metrics.map(function (r) {
        var emo = EMOTIONS.find(function (e) { return e.key === r.emo_open; });
        var emoStr = emo ? (emo.ico + ' ' + escHtml(emoLabel(emo))) : r.emo_open;
        var meCl = +r.mathematical_expectancy_r >= 0 ? 'j-up' : 'j-dn';
        return '<tr>'
          + '<td>' + emoStr + '</td>'
          + '<td class="j-mono">' + r.total_trades + '</td>'
          + '<td class="j-mono">' + fmt(r.winrate_percent, 1) + '%</td>'
          + '<td class="j-mono ' + meCl + '">' + (r.mathematical_expectancy_r >= 0 ? '+' : '') + fmt(r.mathematical_expectancy_r, 2) + 'R</td>'
          + '</tr>';
      }).join('') + '</tbody></table>';
  }

  function switchAnalyticsTab(tab) {
    _analyticsTab = tab;
    var setupWrap = el('jSetupTableWrap');
    var emoWrap   = el('jEmoTableWrap');
    var btnS = el('jAtBtnSetup'), btnE = el('jAtBtnEmo');
    if (setupWrap) setupWrap.style.display = tab === 'setup' ? 'block' : 'none';
    if (emoWrap)   emoWrap.style.display   = tab === 'emo'   ? 'block' : 'none';
    if (btnS) btnS.classList.toggle('on', tab === 'setup');
    if (btnE) btnE.classList.toggle('on', tab === 'emo');
  }

  // ══════════════════════════════════════════════════════════════════════════
  // ── Meta Form Modal ────────────────────────────────────────────────────────
  // ══════════════════════════════════════════════════════════════════════════

  function buildEmoGrid(gridId, selectedKey, onChange) {
    var grid = el(gridId);
    if (!grid) return;
    grid.innerHTML = EMOTIONS.map(function (e) {
      return '<button type="button" class="j-emo-btn' + (e.key === selectedKey ? ' on' : '') + '"'
        + ' data-emo="' + e.key + '" data-grid="' + gridId + '">'
        + '<span class="ico">' + e.ico + '</span>' + escHtml(emoLabel(e)) + '</button>';
    }).join('');
  }

  function buildSetupChips() {
    var chips = el('jSetupChips');
    if (!chips) return;
    chips.innerHTML = SETUP_PRESETS.map(function (s) {
      return '<span class="j-setup-chip" data-setup="' + s + '">' + s + '</span>';
    }).join('');
  }

  function openMetaModal(trade) {
    // trade: {id, symbol, dir, size, pnl, pnl_r, open_ts, close_ts}
    _metaEmoOpen  = 'calmness';
    _metaEmoClose = 'calmness';
    _metaFollowed = true;

    // Заполнить summary
    var summary = el('jMetaTradeSummary');
    if (summary) {
      var pnlCl = +trade.pnl >= 0 ? 'j-up' : 'j-dn';
      summary.innerHTML = '<div class="j-meta-trade-row">'
        + kv(t('journal.field_instrument_short', 'Инструмент'), '<span class="j-sym">' + escHtml(trade.symbol) + '</span>')
        + kv(t('journal.th_type', 'Тип'), trade.dir === 'buy' ? '<span class="j-up">▲ BUY</span>' : '<span class="j-dn">▼ SELL</span>')
        + kv('PnL', '<span class="' + pnlCl + '">' + (trade.pnl >= 0 ? '+' : '') + fmt(trade.pnl, 2) + '</span>')
        + kv('R', '<span class="' + pnlCl + '">' + (trade.pnl_r >= 0 ? '+' : '') + fmt(trade.pnl_r, 2) + 'R</span>')
        + kv(t('journal.th_closed', 'Закрыта'), fmtDate(trade.close_ts))
        + '</div>';
    }

    // Предзаполнить существующими данными если есть
    apiFetch('/api/journal/meta/' + trade.id).then(function (meta) {
      if (meta && meta.trade_id) {
        _metaEmoOpen  = meta.emo_open  || 'calmness';
        _metaEmoClose = meta.emo_close || 'calmness';
        _metaFollowed = !!meta.followed_plan;
        var si = el('jMetaSetupInput');
        if (si) si.value = meta.setup_tag || '';
        var note = el('jMetaForm');
        if (note) note.note.value = meta.note || '';
      }
      buildEmoGrid('jEmoOpenGrid',  _metaEmoOpen);
      buildEmoGrid('jEmoCloseGrid', _metaEmoClose);
      updatePlanBtns();
    }).catch(function () {
      buildEmoGrid('jEmoOpenGrid',  _metaEmoOpen);
      buildEmoGrid('jEmoCloseGrid', _metaEmoClose);
      updatePlanBtns();
    });

    buildSetupChips();
    loadDiscEvalForTrade(trade.id);

    // Хранить trade.id в форме
    var form = el('jMetaForm');
    if (form) form.dataset.tradeId = trade.id;

    var m = el('jMetaModal');
    if (m) m.style.display = 'flex';
    var errEl = el('jMetaError');
    if (errEl) errEl.textContent = '';
  }

  function kv(label, val) {
    return '<div class="j-meta-kv">'
      + '<span class="j-meta-kv-lbl">' + label + '</span>'
      + '<span class="j-meta-kv-val">' + val + '</span></div>';
  }

  function updateQueueProgress() {
    var prog = el('jMetaProgress');
    if (!prog || !_metaQueue.length) return;
    var remaining = _metaQueue.length - _metaQueueIdx;
    prog.textContent = t('journal.queue_prefix', 'Очередь: ') + remaining + t('journal.of_connector', ' из ') + _metaQueue.length + ' ' + t('journal.trades_word', 'сделок');
  }

  function updatePlanBtns() {
    var yes = el('jPlanYes'), no = el('jPlanNo');
    if (yes) yes.classList.toggle('on', _metaFollowed);
    if (no)  no.classList.toggle('on',  !_metaFollowed);
  }

  function closeMetaModal() {
    var m = el('jMetaModal');
    if (m) m.style.display = 'none';
    var form = el('jMetaForm');
    if (form) { form.reset(); delete form.dataset.tradeId; }
    el('jMetaError') && (el('jMetaError').textContent = '');
  }

  function submitMeta(andNext) {
    var form  = el('jMetaForm');
    if (!form) return;
    var tradeId = parseInt(form.dataset.tradeId);
    if (!tradeId) return;

    var setupInput = el('jMetaSetupInput');
    var errEl = el('jMetaError');
    if (errEl) errEl.textContent = '';

    var metaPromise = apiFetch('/api/journal/meta', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        trade_id:      tradeId,
        setup_tag:     (setupInput ? setupInput.value.trim() : '') || 'нет',
        emo_open:      _metaEmoOpen,
        emo_close:     _metaEmoClose,
        followed_plan: _metaFollowed,
        note:          form.note ? form.note.value : '',
      }),
    });

    // Discipline evaluations — только те критерии, где пользователь явно нажал YES/NO
    var discCrits = Object.keys(_discEvals);
    var discPromise = discCrits.length > 0
      ? apiFetch('/api/journal/discipline/eval', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            trade_id:    tradeId,
            evaluations: discCrits.map(function (c) {
              return { criterion: c, passed: _discEvals[c] };
            }),
          }),
        }).catch(function () {})
      : Promise.resolve();

    Promise.all([metaPromise, discPromise]).then(function () {
      _discEvals = {};
      if (andNext && _metaQueueIdx < _metaQueue.length - 1) {
        _metaQueueIdx++;
        updateQueueProgress();
        openMetaModal(_metaQueue[_metaQueueIdx]);
      } else {
        closeMetaModal();
        loadAll();
      }
    }).catch(function (e) {
      if (errEl) errEl.textContent = t('journal.error_prefix', 'Ошибка: ') + e.message;
    });
  }

  // ── Queue public entry ────────────────────────────────────────────────────
  function openQueue() {
    if (!_metaQueue.length) {
      if (_behavioral) _metaQueue = _behavioral.queue_trades || [];
    }
    if (!_metaQueue.length) { return; }
    _metaQueueIdx = 0;
    updateQueueProgress();
    openMetaModal(_metaQueue[0]);
  }

  // Открыть модалку для конкретной сделки из таблицы
  function openMetaForTrade(tradeId) {
    var trade = _trades.find(function (t) { return t.id == tradeId; });
    if (!trade) return;
    // Обернуть в одноэлементную "очередь"
    _metaQueue = [trade];
    _metaQueueIdx = 0;
    updateQueueProgress();
    openMetaModal(trade);
  }

  // ══════════════════════════════════════════════════════════════════════════
  // ── Add / Import modals (Part 1) ──────────────────────────────────────────
  // ══════════════════════════════════════════════════════════════════════════

  function openAddModal() {
    var m = el('jAddModal');
    if (m) m.style.display = 'flex';
  }
  function closeAddModal() {
    var m = el('jAddModal');
    if (m) m.style.display = 'none';
    var f = el('jAddForm');
    if (f) f.reset();
    el('jAddError') && (el('jAddError').textContent = '');
  }

  function submitAddTrade(e) {
    e.preventDefault();
    var errEl = el('jAddError');
    if (errEl) errEl.textContent = '';
    var f = e.target;
    var trade = {
      symbol:      f.symbol.value.trim().toUpperCase(),
      dir:         f.dir.value,
      entry_price: parseFloat(f.entry_price.value),
      exit_price:  parseFloat(f.exit_price.value),
      size:        parseFloat(f.size.value),
      open_ts:     f.open_ts.value.replace('T', ' '),
      close_ts:    f.close_ts.value.replace('T', ' '),
      pnl:         parseFloat(f.pnl.value),
      stop_loss:   f.stop_loss.value ? parseFloat(f.stop_loss.value) : undefined,
      note:        f.note.value,
      source:      'manual',
    };
    if (!trade.symbol || isNaN(trade.pnl) || isNaN(trade.entry_price)) {
      if (errEl) errEl.textContent = t('journal.fill_required_fields', 'Заполните обязательные поля');
      return;
    }
    apiFetch('/api/journal/trades', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(trade),
    }).then(function (r) {
      if (r.duplicate) {
        if (errEl) errEl.textContent = t('journal.duplicate_trade_msg', 'Дубликат — эта сделка уже импортирована');
        return;
      }
      closeAddModal();
      loadAll();
    }).catch(function (e) {
      if (errEl) errEl.textContent = t('journal.error_prefix', 'Ошибка: ') + e.message;
    });
  }

  function openImportModal() {
    var m = el('jImportModal');
    if (m) m.style.display = 'flex';
    switchImportTab('csv');
    el('jImportResult') && (el('jImportResult').textContent = '');
  }
  function closeImportModal() {
    var m = el('jImportModal');
    if (m) m.style.display = 'none';
  }
  function switchImportTab(tab) {
    ['csv','ocr'].forEach(function (t) {
      var btn = el('jImTab_' + t), pnl = el('jImPanel_' + t);
      if (btn) btn.classList.toggle('on', t === tab);
      if (pnl) pnl.style.display = t === tab ? 'block' : 'none';
    });
  }

  function submitCsvImport() {
    var ta = el('jCsvText');
    if (!ta || !ta.value.trim()) return;
    var resEl = el('jImportResult');
    if (resEl) resEl.textContent = t('journal.processing_ellipsis', 'Обработка…');
    apiFetch('/api/journal/import/csv', {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain' },
      body: ta.value,
    }).then(function (r) {
      if (resEl) resEl.textContent = t('journal.import_done_prefix', 'Готово: добавлено ') + r.added + t('journal.import_duplicates_mid', ', дублей ') + r.duplicates + t('journal.import_from_mid', ', из ') + r.parsed;
      if (r.added > 0) { closeImportModal(); loadAll(); }
    }).catch(function (e) {
      if (resEl) resEl.textContent = t('journal.error_prefix', 'Ошибка: ') + e.message;
    });
  }

  function submitOcrImport() {
    var inp = el('jOcrFile');
    if (!inp || !inp.files[0]) return;
    var resEl = el('jImportResult');
    if (resEl) resEl.textContent = 'OCR…';
    var reader = new FileReader();
    reader.onload = function (ev) {
      fetch('/api/journal/import/ocr', {
        method: 'POST',
        headers: { 'Content-Type': 'image/png' },
        body: ev.target.result,
      }).then(function (r) { return r.json(); })
        .then(function (r) {
          if (resEl) resEl.textContent = t('journal.ocr_found_prefix', 'OCR: найдено ') + r.parsed + t('journal.ocr_added_mid', ', добавлено ') + r.added;
          if (r.added > 0) { closeImportModal(); loadAll(); }
        }).catch(function (e) {
          if (resEl) resEl.textContent = t('journal.error_ocr_prefix', 'Ошибка OCR: ') + e.message;
        });
    };
    reader.readAsArrayBuffer(inp.files[0]);
  }

  function openMt5Modal() {
    var m = el('jMt5Modal');
    if (m) m.style.display = 'flex';
    el('jMt5Error') && (el('jMt5Error').textContent = '');
    loadAccounts();
  }
  function closeMt5Modal() {
    var m = el('jMt5Modal');
    if (m) m.style.display = 'none';
    var f = el('jMt5Form');
    if (f) f.reset();
  }
  function loadAccounts() {
    apiFetch('/api/journal/accounts').then(function (accs) {
      var list = el('jAccList');
      if (!list) return;
      if (!accs.length) { list.innerHTML = '<div class="j-empty">' + t('journal.no_accounts', 'Нет аккаунтов') + '</div>'; return; }
      list.innerHTML = accs.map(function (a) {
        return '<div class="j-acc-row">'
          + '<span class="j-acc-broker">' + escHtml(a.broker) + '</span>'
          + '<span class="j-acc-no">#' + escHtml(a.account_no) + '</span>'
          + '<span class="j-acc-server j-muted">' + escHtml(a.server) + '</span>'
          + '</div>';
      }).join('');
    }).catch(function () {});
  }
  function submitMt5Account(e) {
    e.preventDefault();
    var errEl = el('jMt5Error');
    if (errEl) errEl.textContent = '';
    var f = e.target;
    apiFetch('/api/journal/accounts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        broker: f.broker.value.trim(), account_no: f.account_no.value.trim(),
        server: f.server.value.trim(), password: f.password.value,
      }),
    }).then(function () {
      f.reset(); loadAccounts();
    }).catch(function (e) {
      if (errEl) errEl.textContent = t('journal.error_prefix', 'Ошибка: ') + e.message;
    });
  }

  function openInvTip(broker) {
    var m = el('jInvTip');
    if (m) m.style.display = 'flex';
    switchInvBroker(broker || 'avatrade');
  }
  function closeInvTip() {
    var m = el('jInvTip');
    if (m) m.style.display = 'none';
  }
  function switchInvBroker(broker) {
    ['avatrade','naga'].forEach(function (b) {
      var btn = el('jInvTab_' + b), pnl = el('jInvPanel_' + b);
      if (btn) btn.classList.toggle('on', b === broker);
      if (pnl) pnl.style.display = b === broker ? 'block' : 'none';
    });
  }

  function deleteTrade(id) {
    if (!confirm(t('journal.confirm_delete_trade_prefix', 'Удалить сделку #') + id + '?')) return;
    fetch('/api/journal/trades/' + id, { method: 'DELETE' })
      .then(function (r) { return r.json(); })
      .then(function () { loadAll(); })
      .catch(function (e) { showError(t('journal.error_prefix', 'Ошибка: ') + e.message); });
  }

  function showError(msg) {
    var e = el('jGlobalErr');
    if (e) { e.textContent = msg; e.style.display = 'block'; }
    else console.error(msg);
  }

  // ══════════════════════════════════════════════════════════════════════════
  // ── Morning Brief «Твой день» (Part 5) ───────────────────────────────────────
  // ══════════════════════════════════════════════════════════════════════════

  var _availableSymbols = [];

  function volLabel(vol) {
    var map = {
      normal:  ['journal.vol_normal', 'норм.'],
      high:    ['journal.vol_high', 'высок.'],
      extreme: ['journal.vol_extreme', 'экстрем.'],
    };
    var e = map[vol];
    return e ? t(e[0], e[1]) : vol;
  }
  function countryName(code) {
    var map = {
      US: ['journal.country_us', '🇺🇸 США'],
      EU: ['journal.country_eu', '🇪🇺 ЕС'],
      GB: ['journal.country_gb', '🇬🇧 Великобр.'],
      JP: ['journal.country_jp', '🇯🇵 Япония'],
      AU: ['journal.country_au', '🇦🇺 Австрал.'],
      NZ: ['journal.country_nz', '🇳🇿 Новая Зел.'],
      CA: ['journal.country_ca', '🇨🇦 Канада'],
      CH: ['journal.country_ch', '🇨🇭 Швейцар.'],
      CN: ['journal.country_cn', '🇨🇳 Китай'],
      KZ: ['journal.country_kz', '🇰🇿 Казахстан'],
    };
    var e = map[code];
    return e ? t(e[0], e[1]) : code;
  }

  function loadBrief() {
    return apiFetch('/api/journal/watchlist')
      .then(function (data) {
        _availableSymbols = data.available || [];
        renderWatchlistChips(data.watchlist || []);
        populateWlSelect(data.watchlist || []);
        return apiFetch('/api/journal/brief');
      })
      .then(function (brief) { renderBrief(brief); })
      .catch(function () {});
  }

  function renderBrief(brief) {
    var dateEl = el('jBriefDate');
    if (dateEl) dateEl.textContent = brief.date || '';

    var emptyEl = el('jBriefEmpty');
    var retroSec = el('jRetroSection');
    var macroSec = el('jMacroSection');

    var wl = brief.watchlist || [];
    if (!wl.length) {
      if (emptyEl) emptyEl.style.display = 'block';
      if (retroSec) retroSec.style.display = 'none';
      if (macroSec) macroSec.style.display = 'none';
      return;
    }
    if (emptyEl) emptyEl.style.display = 'none';

    // ── Ретроспектива ─────────────────────────────────────────────────────
    var moves = brief.yesterday_retrospective || [];
    if (moves.length) {
      if (retroSec) retroSec.style.display = '';
      var grid = el('jRetroGrid');
      if (grid) {
        grid.innerHTML = moves.map(function (m) {
          var up    = m.price_change_percent >= 0;
          var pct   = (up ? '+' : '') + fmt(m.price_change_percent, 2) + '%';
          var cls   = up ? 'j-up' : 'j-dn';
          var vol   = m.volatility_state || 'normal';
          var chartUrl = '/chart.html?s=' + encodeURIComponent(m.symbol);
          return '<a class="j-retro-card" href="' + chartUrl + '" title="' + t('journal.open_chart_tip', 'Открыть график') + '">'
            + '<div class="j-retro-sym">' + escHtml(m.symbol) + '</div>'
            + '<div class="j-retro-chg ' + cls + '">' + pct + '</div>'
            + '<span class="j-retro-vol ' + vol + '">' + volLabel(vol) + '</span>'
            + '<div class="j-retro-close">' + fmt(m.close, 5) + '</div>'
            + '</a>';
        }).join('');
      }
    } else {
      if (retroSec) retroSec.style.display = 'none';
    }

    // ── Макрокалендарь ────────────────────────────────────────────────────
    var events = brief.today_macro_calendar || [];
    if (macroSec) macroSec.style.display = events.length ? '' : 'none';
    var macroList = el('jMacroList');
    if (macroList) {
      if (!events.length) {
        macroList.innerHTML = '<div class="j-macro-empty">' + t('journal.no_events_msg', 'Событий нет') + '</div>';
      } else {
        var factLbl = t('journal.fact_label', 'факт:');
        var forecastLbl = t('journal.forecast_label', 'прогноз:');
        var prevLbl = t('journal.previous_label', 'пред.:');
        macroList.innerHTML = events.map(function (ev) {
          var time = _fmtEventTime(ev.scheduled_ts, ev.ts_utc);
          var imp  = (ev.impact || 'low').toLowerCase();
          var impMap = { high: ['journal.impact_high', 'Высокий'], medium: ['journal.impact_medium', 'Средний'], low: ['journal.impact_low', 'Низкий'] };
          var impLabel = impMap[imp] ? t(impMap[imp][0], impMap[imp][1]) : imp;
          var country = countryName(ev.country);
          var figs = [];
          if (ev.actual)   figs.push('<span><span class="lbl">' + factLbl + '</span> ' + escHtml(ev.actual)   + '</span>');
          if (ev.forecast) figs.push('<span><span class="lbl">' + forecastLbl + '</span> ' + escHtml(ev.forecast) + '</span>');
          if (ev.previous) figs.push('<span><span class="lbl">' + prevLbl + '</span> ' + escHtml(ev.previous) + '</span>');
          return '<div class="j-macro-event">'
            + '<div class="j-macro-time">' + time + '</div>'
            + '<div class="j-macro-body">'
            +   '<div class="j-macro-title">' + escHtml(ev.title) + '</div>'
            +   '<div class="j-macro-country">' + country + '</div>'
            +   (figs.length ? '<div class="j-macro-figures">' + figs.join('') + '</div>' : '')
            + '</div>'
            + '<span class="j-macro-impact ' + imp + '">' + impLabel + '</span>'
            + '</div>';
        }).join('');
      }
    }
  }

  function _fmtEventTime(scheduledTs, tsUtc) {
    if (scheduledTs) {
      var d = new Date(scheduledTs * 1000);
      var locale = (window.sbfI18n && window.sbfI18n.lang === 'ro') ? 'ro-RO' : 'ru';
      return d.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });
    }
    if (tsUtc) {
      var m = tsUtc.match(/T(\d{2}:\d{2})/);
      return m ? m[1] : '—';
    }
    return '—';
  }

  // ── Watchlist ─────────────────────────────────────────────────────────────
  function renderWatchlistChips(symbols) {
    var wrap = el('jWatchlistChips');
    if (!wrap) return;
    if (!symbols.length) {
      wrap.innerHTML = '<span style="font-size:12px;color:var(--muted)">' + t('journal.watchlist_empty', 'Список пуст') + '</span>';
      return;
    }
    var deleteTip = t('journal.delete_tip', 'Удалить');
    wrap.innerHTML = symbols.map(function (sym) {
      return '<div class="j-wl-chip">'
        + '<span class="j-wl-chip-sym">' + escHtml(sym) + '</span>'
        + '<button class="j-wl-chip-del" data-wl-del="' + sym + '" title="' + deleteTip + '">✕</button>'
        + '</div>';
    }).join('');
  }

  function populateWlSelect(current) {
    var sel = el('jWlAddSelect');
    if (!sel) return;
    var currentSet = new Set(current);
    sel.innerHTML = '<option value="">' + t('journal.add_ellipsis', 'Добавить…') + '</option>'
      + _availableSymbols
          .filter(function (s) { return !currentSet.has(s); })
          .map(function (s) { return '<option value="' + s + '">' + s + '</option>'; })
          .join('');
  }

  function addToWatchlist(symbol) {
    if (!symbol) return;
    apiFetch('/api/journal/watchlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: symbol }),
    }).then(function () { loadBrief(); })
      .catch(function () {});
  }

  function removeFromWatchlist(symbol) {
    apiFetch('/api/journal/watchlist/' + encodeURIComponent(symbol), { method: 'DELETE' })
      .then(function () { loadBrief(); })
      .catch(function () {});
  }

  // ══════════════════════════════════════════════════════════════════════════
  // ── Alerts & Notifications (Part 4) ─────────────────────────────────────────
  // ══════════════════════════════════════════════════════════════════════════

  var _notifications = [];   // pending notifications cache
  var _notifOpen     = false;

  // ── KIND helpers ─────────────────────────────────────────────────────────
  var ALERT_KIND_ICO = {
    price_cross:       '📊',
    rsi_extreme:       '📈',
    economic_event:    '📅',
    weekly_range:      '📐',
    behavioral_streak: '🔥',
    behavioral_journal:'📝',
    behavioral_tilt:   '⚠️',
    morning_brief:     '☀️',
  };
  function alertKindLabel(kind) {
    var map = {
      price_cross:        ['journal.alert_price_cross', 'Пересечение цены'],
      rsi_extreme:        ['journal.alert_rsi_extreme', 'Экстремум RSI'],
      economic_event:     ['journal.alert_macro_event', 'Макрособытие'],
      weekly_range:       ['journal.alert_weekly_extreme', 'Недельный экстремум'],
      behavioral_streak:  ['journal.alert_streak_threat', 'Угроза стрику'],
      behavioral_journal: ['journal.alert_anomalous_trade', 'Аномальная сделка'],
      behavioral_tilt:    ['journal.alert_tilt_detector', 'Детектор тильта'],
      morning_brief:      ['journal.alert_morning_brief', 'Утренний бриф'],
    };
    var e = map[kind];
    return e ? t(e[0], e[1]) : kind;
  }
  var MARKET_KINDS = new Set(['price_cross','rsi_extreme','economic_event','weekly_range']);

  // ── Notifications ────────────────────────────────────────────────────────
  function loadNotifications() {
    apiFetch('/api/journal/alerts/notifications')
      .then(function (data) {
        _notifications = Array.isArray(data) ? data : [];
        renderNotifBadge();
        if (_notifOpen) renderNotifPanel();
      }).catch(function () {});
  }

  function renderNotifBadge() {
    var badge = el('jNotifBadge');
    var n = _notifications.length;
    if (!badge) return;
    if (n > 0) {
      badge.textContent = n > 99 ? '99+' : n;
      badge.style.display = 'flex';
    } else {
      badge.style.display = 'none';
    }
  }

  function renderNotifPanel() {
    var list = el('jNotifList');
    var cnt  = el('jNotifPanelCount');
    if (!list) return;
    if (cnt) cnt.textContent = _notifications.length
      ? '(' + _notifications.length + ')'
      : '';
    if (!_notifications.length) {
      list.innerHTML = '<div class="j-notif-empty">' + t('journal.no_new_notifications', 'Новых уведомлений нет') + '</div>';
      return;
    }
    list.innerHTML = _notifications.map(function (n) {
      var cls = n.is_critical ? ' critical' : '';
      var ico = ALERT_KIND_ICO[n.kind] || '🔔';
      var ts  = fmtDate(n.created_at);
      return '<div class="j-notif-item' + cls + '" data-id="' + n.id + '">'
        + '<div class="j-notif-item-title">' + ico + ' ' + escHtml(n.title) + '</div>'
        + '<div class="j-notif-item-body">' + escHtml(n.body) + '</div>'
        + '<div class="j-notif-item-ts">' + ts + '</div>'
        + '</div>';
    }).join('');
  }

  function toggleNotifPanel() {
    var panel = el('jNotifPanel');
    if (!panel) return;
    _notifOpen = !_notifOpen;
    panel.classList.toggle('open', _notifOpen);
    if (_notifOpen) renderNotifPanel();
  }

  function closeNotifPanel() {
    _notifOpen = false;
    var panel = el('jNotifPanel');
    if (panel) panel.classList.remove('open');
  }

  function markAllDelivered() {
    if (!_notifications.length) return;
    var ids = _notifications.map(function (n) { return n.id; });
    apiFetch('/api/journal/alerts/notifications/mark-delivered', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: ids }),
    }).then(function () {
      _notifications = [];
      renderNotifBadge();
      renderNotifPanel();
    }).catch(function () {});
  }

  // ── Alert Rules ───────────────────────────────────────────────────────────
  function loadAlertRules() {
    apiFetch('/api/journal/alerts/rules')
      .then(function (rules) { renderAlertRules(rules); })
      .catch(function () {});
  }

  function renderAlertRules(rules) {
    var wrap = el('jAlertRulesList');
    if (!wrap) return;
    if (!rules || !rules.length) {
      wrap.innerHTML = '<div class="j-alerts-empty">' + t('journal.no_alert_rules_msg', 'Нет настроенных правил. Создайте первый алерт.') + '</div>';
      return;
    }
    var toggleTip = t('journal.toggle_on_off_tip', 'Вкл/Выкл');
    var deleteTip = t('journal.delete_tip', 'Удалить');
    wrap.innerHTML = rules.map(function (r) {
      var ico   = ALERT_KIND_ICO[r.kind] || '🔔';
      var label = alertKindLabel(r.kind);
      var onCls = r.is_active ? ' on' : '';
      var symBadge = r.symbol
        ? '<span class="j-alert-rule-sym">' + escHtml(r.symbol) + '</span>'
        : '';
      var paramStr = _formatRuleParam(r.kind, r.param || {});
      return '<div class="j-alert-rule">'
        + '<span class="j-alert-rule-ico">' + ico + '</span>'
        + '<div class="j-alert-rule-lbl">'
        +   symBadge
        +   '<span class="j-alert-rule-kind">' + escHtml(label)
        +   (paramStr ? ' — ' + escHtml(paramStr) : '') + '</span>'
        + '</div>'
        + '<div class="j-alert-rule-actions">'
        +   '<button class="j-alert-toggle' + onCls + '" data-alert-id="' + r.id + '" data-active="' + (r.is_active ? '1' : '0') + '" title="' + toggleTip + '"></button>'
        +   '<button class="j-alert-del" data-alert-del="' + r.id + '" title="' + deleteTip + '">✕</button>'
        + '</div>'
        + '</div>';
    }).join('');
  }

  function _formatRuleParam(kind, param) {
    if (kind === 'price_cross') {
      var dir = param.direction === 'up' ? '↑' : '↓';
      return dir + ' ' + (param.target || '');
    }
    if (kind === 'rsi_extreme') {
      var cond = param.condition === 'overbought' ? t('journal.overbought', 'Перекупленность') : t('journal.oversold', 'Перепроданность');
      return (param.tf || 'H1') + ' ' + cond + ' ' + (param.level || '');
    }
    if (kind === 'economic_event') return param.event_name || '';
    if (kind === 'weekly_range') return param.extreme === 'high' ? 'High' : 'Low';
    return '';
  }

  function deleteAlertRule(ruleId) {
    apiFetch('/api/journal/alerts/rules/' + ruleId, { method: 'DELETE' })
      .then(function () { loadAlertRules(); })
      .catch(function () {});
  }

  function toggleAlertRule(ruleId, currentActive) {
    var newActive = currentActive === '1' ? false : true;
    apiFetch('/api/journal/alerts/rules/' + ruleId + '/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: newActive }),
    }).then(function () { loadAlertRules(); })
      .catch(function () {});
  }

  // ── Alert Rule Modal ──────────────────────────────────────────────────────
  function openAlertModal() {
    var m = el('jAlertModal');
    if (m) m.style.display = 'flex';
    el('jAlertErr') && (el('jAlertErr').textContent = '');
    _syncAlertKindUI();
  }
  function closeAlertModal() {
    var m = el('jAlertModal');
    if (m) m.style.display = 'none';
  }

  function _syncAlertKindUI() {
    var kind = (el('jAlertKind') || {}).value || 'price_cross';
    var needSym = MARKET_KINDS.has(kind);
    var symWrap = el('jAlertSymbolWrap');
    if (symWrap) symWrap.style.display = needSym ? '' : 'none';
    ['PriceCross','Rsi','Econ','Weekly'].forEach(function (n) {
      var d = el('jAlertParam' + n);
      if (d) d.style.display = 'none';
    });
    var mapKind = { price_cross: 'PriceCross', rsi_extreme: 'Rsi', economic_event: 'Econ', weekly_range: 'Weekly' };
    var paramId = mapKind[kind];
    if (paramId) {
      var pe = el('jAlertParam' + paramId);
      if (pe) pe.style.display = '';
    }
  }

  function _buildAlertParam(kind) {
    var p = {};
    if (kind === 'price_cross') {
      p.target    = parseFloat((el('jAlertTarget') || {}).value) || 0;
      p.direction = (el('jAlertDirection') || {}).value || 'up';
    } else if (kind === 'rsi_extreme') {
      p.tf        = (el('jAlertTf') || {}).value || 'H1';
      p.level     = parseFloat((el('jAlertRsiLevel') || {}).value) || 70;
      p.condition = (el('jAlertCondition') || {}).value || 'overbought';
    } else if (kind === 'economic_event') {
      p.event_name    = ((el('jAlertEventName') || {}).value || '').trim();
      p.minutes_before = parseInt((el('jAlertMinBefore') || {}).value) || 15;
    } else if (kind === 'weekly_range') {
      p.extreme = (el('jAlertExtreme') || {}).value || 'high';
    }
    return p;
  }

  function submitAlertRule() {
    var errEl = el('jAlertErr');
    if (errEl) errEl.textContent = '';
    var kind   = (el('jAlertKind') || {}).value;
    var symbol = ((el('jAlertSymbol') || {}).value || '').trim().toUpperCase();
    if (MARKET_KINDS.has(kind) && !symbol) {
      if (errEl) errEl.textContent = t('journal.specify_instrument_msg', 'Укажите инструмент');
      return;
    }
    var param = _buildAlertParam(kind);
    apiFetch('/api/journal/alerts/rules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: symbol, kind: kind, param: param }),
    }).then(function () {
      closeAlertModal();
      loadAlertRules();
    }).catch(function (e) {
      if (errEl) errEl.textContent = t('journal.error_prefix', 'Ошибка: ') + e.message;
    });
  }

  // ══════════════════════════════════════════════════════════════════════════
  // ── Setups & Playbook (Part 6) ────────────────────────────────────────────────
  // ══════════════════════════════════════════════════════════════════════════

  var _setupFilter    = 'all';
  var _currentSetupId = null;   // редактируемый setup id
  var _statusSetupId  = null;   // setup id для смены статуса

  function statusLabel(st) {
    var map = {
      pending:     ['journal.filter_pending', 'Ожидает'],
      executed:    ['journal.filter_executed', 'Исполнен'],
      invalidated: ['journal.filter_invalidated', 'Отменён'],
      expired:     ['journal.filter_expired', 'Истёк'],
    };
    var e = map[st];
    return e ? t(e[0], e[1]) : st;
  }

  // Список паттернов — динамически получаем из PATTERN_LABELS
  var PATTERN_LIST = [
    ['head_and_shoulders','Голова и плечи'],
    ['inverse_head_and_shoulders','Перевёрнутые г/п'],
    ['double_top','Двойная вершина'],
    ['double_bottom','Двойное дно'],
    ['triangle_ascending','Восходящий треугольник'],
    ['triangle_descending','Нисходящий треугольник'],
    ['triangle_symmetrical','Симметричный треугольник'],
    ['wedge_rising','Расширяющийся клин'],
    ['wedge_falling','Сужающийся клин'],
    ['flag_bull','Бычий флаг'],
    ['flag_bear','Медвежий флаг'],
    ['pennant','Вымпел'],
    ['cup_and_handle','Чашка с ручкой'],
    ['support_level','Уровень поддержки'],
    ['resistance_level','Уровень сопротивления'],
    ['fib_retracement','Фибоначчи (откат)'],
    ['fib_extension','Фибоначчи (цель)'],
    ['breakout','Пробой вверх'],
    ['breakdown','Пробой вниз'],
    ['range','Боковой диапазон'],
    ['trend_continuation','Продолжение тренда'],
    ['trend_reversal','Разворот тренда'],
    ['other','Другое'],
  ];

  function patternLabel(key, fallback) {
    return t('journal.pattern_' + key, fallback);
  }

  // ── Load & Render ─────────────────────────────────────────────────────────
  function loadSetups() {
    var params = _setupFilter !== 'all' ? '?status=' + _setupFilter : '';
    return Promise.all([
      apiFetch('/api/journal/setups' + params),
      apiFetch('/api/journal/setups/playbook-stats'),
    ]).then(function (results) {
      renderSetupCards(results[0]);
      renderPlaybookStats(results[1]);
    }).catch(function () {});
  }

  function renderSetupCards(setups) {
    var wrap = el('jSetupCards');
    if (!wrap) return;
    if (!setups || !setups.length) {
      wrap.innerHTML = '<div class="j-setups-empty">'
        + (_setupFilter === 'all'
            ? t('journal.create_first_setup_msg', 'Создайте первый сетап, нажав «+ Новый сетап»')
            : t('journal.no_setups_status_msg', 'Нет сетапов с таким статусом'))
        + '</div>';
      return;
    }
    var openChartTip = t('journal.open_chart_tip', 'Открыть график');
    var editTip       = t('journal.edit_tip', 'Редактировать');
    var statusTip     = t('journal.status_tip', 'Статус');
    var deleteTip     = t('journal.delete_tip', 'Удалить');
    wrap.innerHTML = setups.map(function (s) {
      var patInfo = PATTERN_LIST.find(function (p) { return p[0] === s.pattern_key; });
      var patLabelText = patInfo ? patternLabel(patInfo[0], patInfo[1]) : '';
      var levelsHtml = (s.levels || []).map(function (l) {
        return '<span class="j-setup-level">' + fmt(l, 5) + '</span>';
      }).join('');
      var tagsHtml = (s.tags || []).map(function (tag) {
        return '<span class="j-setup-tag">' + escHtml(tag) + '</span>';
      }).join('');
      var st  = s.status || 'pending';
      var chartUrl = '/chart.html?s=' + encodeURIComponent(s.symbol) + '&tf=' + encodeURIComponent(s.timeframe);
      var thesis = (s.thesis || '').length > 120
        ? s.thesis.slice(0, 120) + '…'
        : s.thesis;
      return '<div class="j-setup-card" data-setup-id="' + s.id + '">'
        + '<div class="j-setup-card-hd">'
        +   '<div class="j-setup-card-sym">'
        +     '<a class="j-setup-sym-badge" href="' + chartUrl + '" title="' + openChartTip + '">' + escHtml(s.symbol) + '</a>'
        +     '<span class="j-setup-tf">' + escHtml(s.timeframe) + '</span>'
        +   '</div>'
        +   '<span class="j-setup-status ' + st + '">' + statusLabel(st) + '</span>'
        + '</div>'
        + '<div class="j-setup-pattern">📐 ' + escHtml(patLabelText || s.pattern_key) + '</div>'
        + (levelsHtml ? '<div class="j-setup-levels">' + levelsHtml + '</div>' : '')
        + (thesis ? '<div class="j-setup-thesis">' + escHtml(thesis) + '</div>' : '')
        + (tagsHtml ? '<div class="j-setup-tags">' + tagsHtml + '</div>' : '')
        + '<div class="j-setup-footer">'
        +   '<span class="j-setup-date">' + fmtDate(s.created_at) + '</span>'
        +   '<div class="j-setup-actions">'
        +     '<button class="j-setup-action" data-setup-edit="' + s.id + '" title="' + editTip + '">✎</button>'
        +     '<button class="j-setup-action" data-setup-status="' + s.id + '" title="' + statusTip + '">⇄</button>'
        +     '<button class="j-setup-action danger" data-setup-del="' + s.id + '" title="' + deleteTip + '">✕</button>'
        +   '</div>'
        + '</div>'
        + '</div>';
    }).join('');
  }

  function renderPlaybookStats(stats) {
    var section = el('jPlaybookStats');
    var tbody   = el('jPlaybookTbody');
    if (!section || !tbody) return;
    if (!stats || !stats.length) { section.style.display = 'none'; return; }
    section.style.display = '';
    tbody.innerHTML = stats.map(function (s) {
      var wr = s.pattern_winrate;
      var wrCls = wr == null ? 'na' : (wr >= 55 ? 'hi' : 'lo');
      var wrTxt = wr != null ? wr + '%' : '—';
      return '<tr>'
        + '<td>' + escHtml(s.label) + '</td>'
        + '<td style="text-align:center">' + s.total_saved + '</td>'
        + '<td style="text-align:center">' + s.executed_count + '</td>'
        + '<td class="j-pb-wr ' + wrCls + '" style="text-align:center">' + wrTxt + '</td>'
        + '</tr>';
    }).join('');
  }

  // ── Setup Modal ───────────────────────────────────────────────────────────
  function _populatePatternSelect() {
    var sel = el('jSetupPattern');
    if (!sel || sel.options.length > 1) return;
    // Строится один раз за сессию (см. guard выше) — помечаем data-i18n,
    // чтобы _patchI18n мог донасытить перевод, если словарь ещё не был
    // готов на момент первого открытия модалки.
    sel.innerHTML = PATTERN_LIST.map(function (p) {
      return '<option value="' + p[0] + '" data-i18n="journal.pattern_' + p[0] + '">' + patternLabel(p[0], p[1]) + '</option>';
    }).join('');
    _patchI18n(sel);
  }

  function _populateTradeSelect() {
    var sel = el('jSetupTradeSelect');
    if (!sel) return;
    sel.innerHTML = '<option value="">' + t('journal.choose_trade', 'Выберите сделку…') + '</option>'
      + _trades.slice(0, 50).map(function (t) {
        var sign = t.pnl >= 0 ? '+' : '';
        return '<option value="' + t.id + '">'
          + t.symbol + ' ' + t.dir + ' ' + fmtDate(t.close_ts)
          + ' (' + sign + fmt(t.pnl, 2) + ')'
          + '</option>';
      }).join('');
  }

  function openSetupModal(setupId) {
    _currentSetupId = setupId || null;
    var titleEl = el('jSetupModalTitle');
    if (titleEl) titleEl.textContent = setupId
      ? t('journal.edit_setup_title', 'Редактировать сетап')
      : t('journal.new_setup_title', 'Новый сетап');
    _populatePatternSelect();
    el('jSetupErr') && (el('jSetupErr').textContent = '');

    var linkSection = el('jSetupLinkSection');

    if (setupId) {
      // Загрузить данные для редактирования
      apiFetch('/api/journal/setups/' + setupId).then(function (s) {
        if (!s || !s.id) return;
        el('jSetupSymbol')      && (el('jSetupSymbol').value      = s.symbol || '');
        el('jSetupTf')          && (el('jSetupTf').value          = s.timeframe || 'H4');
        el('jSetupPattern')     && (el('jSetupPattern').value     = s.pattern_key || 'other');
        el('jSetupLevels')      && (el('jSetupLevels').value      = (s.levels || []).join(', '));
        el('jSetupThesis')      && (el('jSetupThesis').value      = s.thesis || '');
        el('jSetupTags')        && (el('jSetupTags').value        = (s.tags || []).join(', '));
        el('jSetupReviewWeeks') && (el('jSetupReviewWeeks').value = '4');
        if (linkSection) {
          linkSection.style.display = s.status === 'pending' ? '' : 'none';
          _populateTradeSelect();
        }
      }).catch(function () {});
    } else {
      el('jSetupSymbol')      && (el('jSetupSymbol').value      = '');
      el('jSetupThesis')      && (el('jSetupThesis').value      = '');
      el('jSetupLevels')      && (el('jSetupLevels').value      = '');
      el('jSetupTags')        && (el('jSetupTags').value        = '');
      el('jSetupReviewWeeks') && (el('jSetupReviewWeeks').value = '4');
      if (linkSection) linkSection.style.display = 'none';
    }

    var m = el('jSetupModal');
    if (m) m.style.display = 'flex';
  }

  function closeSetupModal() {
    var m = el('jSetupModal');
    if (m) m.style.display = 'none';
    _currentSetupId = null;
  }

  function submitSetup() {
    var errEl = el('jSetupErr');
    if (errEl) errEl.textContent = '';

    var symbol  = ((el('jSetupSymbol') || {}).value || '').trim().toUpperCase();
    var tf      = (el('jSetupTf') || {}).value || 'H4';
    var pattern = (el('jSetupPattern') || {}).value || 'other';
    var thesis  = ((el('jSetupThesis') || {}).value || '').trim();
    var levStr  = ((el('jSetupLevels') || {}).value || '').trim();
    var tagsStr = ((el('jSetupTags') || {}).value || '').trim();
    var weeks   = parseInt((el('jSetupReviewWeeks') || {}).value) || 4;

    if (!symbol) { if (errEl) errEl.textContent = t('journal.specify_instrument_msg', 'Укажите инструмент'); return; }
    if (!thesis) { if (errEl) errEl.textContent = t('journal.write_thesis_msg', 'Напишите тезис'); return; }

    var levels = levStr ? levStr.split(',').map(function (v) {
      return parseFloat(v.trim());
    }).filter(function (v) { return !isNaN(v); }) : [];

    var tags = tagsStr ? tagsStr.split(',').map(function (t) { return t.trim(); }).filter(Boolean) : [];

    var body = {
      symbol: symbol, timeframe: tf, pattern_key: pattern,
      thesis: thesis, levels: levels, tags: tags,
      review_in_weeks: weeks, render_params: [],
    };

    var method = _currentSetupId ? 'PUT' : 'POST';
    var url    = _currentSetupId
      ? '/api/journal/setups/' + _currentSetupId
      : '/api/journal/setups';

    apiFetch(url, {
      method: method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(function () {
      closeSetupModal();
      loadSetups();
    }).catch(function (e) {
      if (errEl) errEl.textContent = t('journal.error_prefix', 'Ошибка: ') + e.message;
    });
  }

  function deleteSetup(setupId) {
    apiFetch('/api/journal/setups/' + setupId, { method: 'DELETE' })
      .then(function () { loadSetups(); })
      .catch(function () {});
  }

  // ── Status Modal ──────────────────────────────────────────────────────────
  function openStatusModal(setupId) {
    _statusSetupId = setupId;
    var desc = el('jSetupStatusDesc');
    var setup = (document.querySelector('[data-setup-id="' + setupId + '"]') || {});
    if (desc) {
      var sym = (setup.querySelector && setup.querySelector('.j-setup-sym-badge') || {}).textContent || '';
      desc.textContent = t('journal.setup_status_prefix', 'Сетап ') + sym + t('journal.setup_status_suffix', ' — выберите новый статус:');
    }
    var m = el('jSetupStatusModal');
    if (m) m.style.display = 'flex';
  }

  function closeStatusModal() {
    var m = el('jSetupStatusModal');
    if (m) m.style.display = 'none';
    _statusSetupId = null;
  }

  function applyStatus(newStatus) {
    if (!_statusSetupId) return;
    apiFetch('/api/journal/setups/' + _statusSetupId + '/status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus }),
    }).then(function () {
      closeStatusModal();
      loadSetups();
    }).catch(function () {});
  }

  function linkTradeToSetup(setupId) {
    var sel = el('jSetupTradeSelect');
    var tradeId = sel ? parseInt(sel.value) : 0;
    if (!tradeId) return;
    apiFetch('/api/journal/setups/' + setupId + '/link-trade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trade_id: tradeId }),
    }).then(function () {
      closeSetupModal();
      loadSetups();
    }).catch(function () {});
  }

  // ── Инициализация ──────────────────────────────────────────────────────────
  function init() {
    var addBtn    = el('jAddBtn');
    var importBtn = el('jImportBtn');
    var mt5Btn    = el('jMt5Btn');
    var discCfgBtn = el('jDiscConfigBtn');
    if (addBtn)     addBtn.addEventListener('click', openAddModal);
    if (importBtn)  importBtn.addEventListener('click', openImportModal);
    if (mt5Btn)     mt5Btn.addEventListener('click', openMt5Modal);
    if (discCfgBtn) discCfgBtn.addEventListener('click', openDiscConfig);

    // Discipline config save
    var discSaveBtn = el('jDiscConfigSave');
    if (discSaveBtn) discSaveBtn.addEventListener('click', saveDiscConfig);

    // Advanced mode toggle → wellbeing warning
    var advChk = el('jAdvModeChk');
    if (advChk) advChk.addEventListener('change', function () {
      var wb = el('jDiscWellbeing');
      if (wb) wb.style.display = 'none';
    });

    // Notification bell
    var bellBtn = el('jNotifBell');
    if (bellBtn) bellBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      toggleNotifPanel();
    });
    var readAllBtn = el('jNotifReadAll');
    if (readAllBtn) readAllBtn.addEventListener('click', markAllDelivered);

    // Setup buttons
    var addSetupBtn = el('jAddSetupBtn');
    if (addSetupBtn) addSetupBtn.addEventListener('click', function () { openSetupModal(null); });
    var setupSubmit = el('jSetupSubmit');
    if (setupSubmit) setupSubmit.addEventListener('click', submitSetup);
    var setupLinkBtn = el('jSetupLinkBtn');
    if (setupLinkBtn) setupLinkBtn.addEventListener('click', function () {
      if (_currentSetupId) linkTradeToSetup(_currentSetupId);
    });

    // Setup filters
    document.querySelectorAll('.j-sf-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        document.querySelectorAll('.j-sf-btn').forEach(function (b) { b.classList.remove('on'); });
        btn.classList.add('on');
        _setupFilter = btn.dataset.sf || 'all';
        loadSetups();
      });
    });

    // Brief buttons
    var briefRefresh = el('jBriefRefresh');
    if (briefRefresh) briefRefresh.addEventListener('click', function () {
      apiFetch('/api/journal/brief?refresh=1')
        .then(function () { loadBrief(); })
        .catch(function () { loadBrief(); });
    });
    var wlAddBtn = el('jWlAddBtn');
    if (wlAddBtn) wlAddBtn.addEventListener('click', function () {
      var sel = el('jWlAddSelect');
      if (sel && sel.value) { addToWatchlist(sel.value); sel.value = ''; }
    });

    // Alert buttons
    var addAlertBtn = el('jAddAlertBtn');
    if (addAlertBtn) addAlertBtn.addEventListener('click', openAlertModal);
    var alertSubmit = el('jAlertSubmit');
    if (alertSubmit) alertSubmit.addEventListener('click', submitAlertRule);
    var alertKind = el('jAlertKind');
    if (alertKind) alertKind.addEventListener('change', _syncAlertKindUI);

    // Part 8: flashcards button
    var fcBtn = el('jFlashcardsBtn');
    if (fcBtn) fcBtn.addEventListener('click', openFlashcards);
    var fcClose = el('jFcClose');
    if (fcClose) fcClose.addEventListener('click', closeFcModal);

    // Part 7: checklist buttons
    var runClBtn = el('jRunChecklistBtn');
    if (runClBtn) runClBtn.addEventListener('click', runChecklist);
    var clAddBtn = el('jClAddBtn');
    if (clAddBtn) clAddBtn.addEventListener('click', addClItem);
    var clNewText = el('jClNewText');
    if (clNewText) clNewText.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') addClItem();
    });

    // Part 9: goals form buttons
    var goalFormToggle = el('jGoalFormToggle');
    if (goalFormToggle) goalFormToggle.addEventListener('click', function () {
      var form = el('jGoalForm');
      if (form) form.style.display = form.style.display === 'none' ? 'flex' : 'none';
    });
    var goalAddBtn = el('jGoalAddBtn');
    if (goalAddBtn) goalAddBtn.addEventListener('click', createGoal);

    // Part 10: account hub buttons
    var refCopyBtn = el('jRefCopyBtn');
    if (refCopyBtn) refCopyBtn.addEventListener('click', copyReferralCode);
    var refUseBtn = el('jRefUseBtn');
    if (refUseBtn) refUseBtn.addEventListener('click', useReferralCode);
    var exportBtn = el('jExportBtn');
    if (exportBtn) exportBtn.addEventListener('click', exportMyData);
    var deleteBtn = el('jDeleteReqBtn');
    if (deleteBtn) deleteBtn.addEventListener('click', requestDeletion);

    // Polling notifications every 30 s
    setInterval(loadNotifications, 30000);

    // Делегирование кликов
    document.addEventListener('click', function (e) {
      var t = e.target;
      // Закрытие нотификационной панели при клике вне неё
      var panel = el('jNotifPanel');
      if (panel && _notifOpen && !panel.contains(t) && t.id !== 'jNotifBell' && !t.closest('.j-notif-bell')) {
        closeNotifPanel();
      }
      // Закрытие модалок
      if (t.classList.contains('j-modal-bg'))   { closeAddModal(); closeImportModal(); closeMt5Modal(); closeInvTip(); closeMetaModal(); closeDiscConfig(); closeAlertModal(); closeSetupModal(); closeStatusModal(); }
      if (t.id === 'jAddClose')        closeAddModal();
      if (t.id === 'jImClose')         closeImportModal();
      if (t.id === 'jMt5Close')        closeMt5Modal();
      if (t.id === 'jInvClose')        closeInvTip();
      if (t.id === 'jMetaClose')       closeMetaModal();
      if (t.id === 'jDiscConfigClose') closeDiscConfig();
      if (t.id === 'jAlertClose')      closeAlertModal();
      // Watchlist remove
      if (t.dataset.wlDel) removeFromWatchlist(t.dataset.wlDel);
      // Setup actions
      if (t.dataset.setupEdit)   openSetupModal(+t.dataset.setupEdit);
      if (t.dataset.setupDel)    deleteSetup(+t.dataset.setupDel);
      if (t.dataset.setupStatus) openStatusModal(+t.dataset.setupStatus);
      // Status modal buttons
      if (t.dataset.newStatus)   applyStatus(t.dataset.newStatus);
      // Close setup modals
      if (t.id === 'jSetupClose')       closeSetupModal();
      if (t.id === 'jSetupStatusClose') closeStatusModal();
      // Alert rule toggle/delete
      if (t.classList.contains('j-alert-toggle')) toggleAlertRule(t.dataset.alertId, t.dataset.active);
      if (t.dataset.alertDel)                     deleteAlertRule(t.dataset.alertDel);
      // Пресеты дисциплины
      if (t.classList.contains('j-preset-btn') && t.dataset.preset) applyPreset(t.dataset.preset);
      // YES/NO кнопки критериев дисциплины в мета-форме
      if (t.classList.contains('j-crit-pb')) {
        var crit = t.dataset.crit;
        var val  = t.dataset.val === '1';
        _discEvals[crit] = val;
        var row = t.closest('.j-crit-pass-btns');
        if (row) row.querySelectorAll('.j-crit-pb').forEach(function (b) { b.classList.remove('on'); });
        t.classList.add('on');
      }
      // Кнопки InvTip
      if (t.dataset.invTip)        openInvTip(t.dataset.invTip);
      if (t.dataset.invBroker)     switchInvBroker(t.dataset.invBroker);
      // Import tabs
      if (t.dataset.imTab)         switchImportTab(t.dataset.imTab);
      // Таблица
      if (t.classList.contains('j-del-btn'))      deleteTrade(+t.dataset.id);
      if (t.classList.contains('j-journal-btn'))  openMetaForTrade(+t.dataset.id);
      if (t.classList.contains('j-pg-btn'))       loadTrades(+t.dataset.p);
      // Emotion grid
      if (t.classList.contains('j-emo-btn')) {
        var gridId = t.dataset.grid;
        var emo    = t.dataset.emo;
        var grid   = el(gridId);
        if (grid) {
          grid.querySelectorAll('.j-emo-btn').forEach(function (b) { b.classList.remove('on'); });
          t.classList.add('on');
        }
        if (gridId === 'jEmoOpenGrid')  _metaEmoOpen  = emo;
        if (gridId === 'jEmoCloseGrid') _metaEmoClose = emo;
      }
      // Setup chip
      if (t.classList.contains('j-setup-chip')) {
        var si = el('jMetaSetupInput');
        if (si) si.value = t.dataset.setup;
      }
      // Followed plan
      if (t.id === 'jPlanYes') { _metaFollowed = true;  updatePlanBtns(); }
      if (t.id === 'jPlanNo')  { _metaFollowed = false; updatePlanBtns(); }
      // Meta save buttons
      if (t.id === 'jMetaSaveDone') submitMeta(false);
    });

    // Форма добавления сделки
    var addForm = el('jAddForm');
    if (addForm) addForm.addEventListener('submit', submitAddTrade);

    // Meta form: «Сохранить и следующая»
    var metaForm = el('jMetaForm');
    if (metaForm) metaForm.addEventListener('submit', function (e) {
      e.preventDefault(); submitMeta(true);
    });

    // CSV/OCR import
    var csvBtn = el('jCsvSubmit');
    if (csvBtn) csvBtn.addEventListener('click', submitCsvImport);
    var ocrBtn = el('jOcrSubmit');
    if (ocrBtn) ocrBtn.addEventListener('click', submitOcrImport);

    // MT5 form
    var mt5Form = el('jMt5Form');
    if (mt5Form) mt5Form.addEventListener('submit', submitMt5Account);

    // Автозаполнение PnL
    function autoPnl() {
      var f = el('jAddForm');
      if (!f) return;
      var entry = parseFloat(f.entry_price.value);
      var exit_ = parseFloat(f.exit_price.value);
      var size  = parseFloat(f.size.value);
      var dir   = f.dir.value;
      if (!isNaN(entry) && !isNaN(exit_) && !isNaN(size)) {
        f.pnl.value = ((dir === 'buy' ? exit_ - entry : entry - exit_) * size).toFixed(2);
      }
    }
    ['jFldEntry','jFldExit','jFldSize','jFldDir'].forEach(function (id) {
      var e = el(id);
      if (e) { e.addEventListener('input', autoPnl); e.addEventListener('change', autoPnl); }
    });

    loadAll().then(function () { _handleAnchorScroll(); });
  }

  // ── Part 8: Gamification ─────────────────────────────────────────────────

  var _gameData = null;
  var _fcCards = [];
  var _fcIndex = 0;
  var _fcSessionXp = 0;
  var _fcAnswerShown = false;

  function loadGameOverview() {
    return apiFetch('/api/journal/gamification')
      .then(function (d) {
        _gameData = d;
        renderGamePanel(d);
      }).catch(function () {});
  }

  function renderGamePanel(d) {
    if (!d) return;
    _renderXpBar(d.xp);
    _renderGameStreaks(d.streaks);
    _renderQuests(d.quests);
    _renderAchievements(d.achievements);
    _renderCourse(d.course);
    // Due flashcards badge
    var badge = el('jFcDueBadge');
    if (badge && d.due_flashcards_count > 0) {
      badge.style.display = 'inline';
      badge.textContent = d.due_flashcards_count;
    } else if (badge) {
      badge.style.display = 'none';
    }
  }

  function _renderXpBar(xp) {
    if (!xp) return;
    var lvlBadge = el('jXpLevelBadge');
    var fill = el('jXpBarFill');
    var label = el('jXpLabel');
    var titleEl = el('jLevelTitle');
    if (lvlBadge) lvlBadge.textContent = t('journal.level_abbrev_prefix', 'Ур. ') + xp.level;
    if (fill) fill.style.width = Math.round(xp.progress * 100) + '%';
    if (label) label.textContent = xp.xp_in_level + ' / ' + xp.xp_to_next + ' XP';
    if (titleEl && xp.title) titleEl.textContent = xp.title;
    var prestigeRow = el('jPrestigeRow');
    if (prestigeRow) prestigeRow.style.display = xp.level >= 8 ? 'block' : 'none';
  }

  function _streakKindLabel(kind) {
    var map = {
      daily_login:  ['journal.streak_login', 'Вход'],
      journal_fill: ['journal.streak_journal', 'Журнал'],
      lesson_read:  ['journal.streak_lesson', 'Обучение'],
    };
    var e = map[kind];
    return e ? t(e[0], e[1]) : kind;
  }
  function _renderGameStreaks(streaks) {
    var wrap = el('jGameStreaks');
    if (!wrap || !streaks) return;
    var freezeTip = t('journal.freeze_streak_tip', 'Заморозить стрик');
    wrap.innerHTML = Object.entries(streaks).map(function (entry) {
      var kind = entry[0], s = entry[1];
      var cs = s.current_streak || 0;
      var on = cs > 0 ? ' on' : '';
      var fire = cs >= 7 ? '🔥' : cs >= 3 ? '🌟' : '○';
      var freeze = s.freeze_count > 0
        ? '<span class="j-streak-freeze" onclick="SBFJournal.useStreakFreeze(\'' + kind + '\')" title="' + freezeTip + '">❄ ' + s.freeze_count + '</span>'
        : '';
      return '<div class="j-streak-chip' + on + '">' +
        '<span class="j-streak-fire">' + fire + '</span>' +
        '<span class="j-streak-val">' + cs + '</span>' +
        '<span class="j-streak-lbl">' + _streakKindLabel(kind) + '</span>' +
        freeze +
      '</div>';
    }).join('');
  }

  function _renderQuests(quests) {
    var wrap = el('jQuestsList');
    if (!wrap || !quests) return;
    if (!quests.length) {
      wrap.innerHTML = '<div style="font-size:13px;color:var(--muted)">' + t('journal.quests_loading', 'Квесты загружаются…') + '</div>';
      return;
    }
    wrap.innerHTML = quests.map(function (q) {
      var pct = q.target_count > 0 ? Math.round(q.current_count / q.target_count * 100) : 0;
      var done = q.is_completed;
      return '<div class="j-quest-item' + (done ? ' done' : '') + '">' +
        '<span>' + (done ? '✅' : '⬜') + '</span>' +
        '<span style="flex:1;font-size:13px">' + _esc(q.description) + '</span>' +
        '<div class="j-quest-prog-wrap"><div class="j-quest-prog" style="width:' + pct + '%"></div></div>' +
        '<span style="font-size:11px;color:var(--muted);white-space:nowrap">' + q.current_count + '/' + q.target_count + '</span>' +
        (done ? '<span class="j-quest-done-ico">✓</span>' : '<span class="j-quest-xp">+' + q.xp_reward + 'xp</span>') +
      '</div>';
    }).join('');
  }

  function _renderAchievements(ach) {
    var grid = el('jAchGrid');
    if (!grid || !ach) return;
    var all = (ach.unlocked || []).concat(ach.locked || []);
    // Show max 12 (8 unlocked first, then some locked)
    var show = all.slice(0, 16);
    grid.innerHTML = show.map(function (a) {
      var cls = a.unlocked ? 'unlocked' : 'locked';
      return '<div class="j-ach-badge ' + cls + '" title="' + _esc(a.description) + '">' +
        '<span class="j-ach-ico">' + _esc(a.icon || '🏅') + '</span>' +
        '<span class="j-ach-name">' + _esc(a.description.split(' ').slice(0, 3).join(' ')) + '</span>' +
        '<span class="j-ach-xp">+' + (a.xp_reward || 0) + ' xp</span>' +
      '</div>';
    }).join('');
  }

  function _renderCourse(course) {
    var grid = el('jCourseGrid');
    if (!grid || !course) return;
    var html = '';
    var chapterTitlePrefix = t('journal.chapter_title_prefix', 'Глава ');
    for (var i = 1; i <= 15; i++) {
      var ch = course.chapters[i];
      var done = ch && ch.is_completed;
      html += '<button class="j-ch-btn' + (done ? ' done' : '') + '" ' +
        'onclick="SBFJournal.markChapter(' + i + ')" title="' + chapterTitlePrefix + i + '">' +
        (done ? '✓' : i) + '</button>';
    }
    grid.innerHTML = html;
  }

  function markChapter(n) {
    apiFetch('/api/journal/course/complete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chapter_number: n }),
    }).then(function (r) {
      if (r.xp_awarded > 0) {
        _showXpToast('+' + r.xp_awarded + t('journal.chapter_xp_mid', ' XP — Глава ') + n + t('journal.chapter_completed_suffix', ' завершена!'));
        if (r.all_done) { _launchConfetti(); }
      }
      loadGameOverview();
    }).catch(function (e) { showError(e.message); });
  }

  function useStreakFreeze(kind) {
    apiFetch('/api/journal/streaks/freeze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: kind }),
    }).then(function () { loadGameOverview(); })
      .catch(function (e) { showError(e.message); });
  }

  // ── Flashcard Modal ────────────────────────────────────────────────────────

  function openFlashcards() {
    apiFetch('/api/journal/flashcards')
      .then(function (cards) {
        _fcCards = cards;
        _fcIndex = 0;
        _fcSessionXp = 0;
        var m = el('jFcModal');
        if (m) m.style.display = 'flex';
        _renderFcCard();
      }).catch(function (e) { showError(e.message); });
  }

  function closeFcModal() {
    var m = el('jFcModal');
    if (m) m.style.display = 'none';
    if (_fcSessionXp > 0) { loadGameOverview(); }
  }

  function _renderFcCard() {
    var content = el('jFcContent');
    var done = el('jFcDone');
    if (!_fcCards.length || _fcIndex >= _fcCards.length) {
      if (content) content.style.display = 'none';
      if (done) {
        done.style.display = 'block';
        var xpEl = el('jFcSessionXp');
        if (xpEl) xpEl.textContent = _fcSessionXp > 0
          ? '+' + _fcSessionXp + t('journal.xp_session_suffix', ' XP за сессию')
          : t('journal.well_done', 'Молодец!');
      }
      return;
    }
    if (content) content.style.display = 'block';
    if (done) done.style.display = 'none';
    _fcAnswerShown = false;
    var card = _fcCards[_fcIndex];
    var termEl = el('jFcTerm');
    var answerEl = el('jFcAnswer');
    var qualEl = el('jFcQuality');
    var progEl = el('jFcProgressLbl');
    if (termEl) termEl.textContent = card.term;
    if (answerEl) { answerEl.textContent = card.definition; answerEl.style.display = 'none'; }
    if (qualEl) qualEl.style.display = 'none';
    if (progEl) progEl.textContent = (_fcIndex + 1) + ' / ' + _fcCards.length + ' ' + t('journal.cards_word', 'карточек');
    var title = el('jFcModalTitle');
    if (title) title.textContent = t('journal.flashcards', 'Флешкарты') + ' (' + _fcCards.length + t('journal.cards_to_review_suffix', ' к повторению)');
  }

  function revealFcAnswer() {
    if (_fcAnswerShown) return;
    _fcAnswerShown = true;
    var answerEl = el('jFcAnswer');
    var qualEl = el('jFcQuality');
    if (answerEl) answerEl.style.display = 'block';
    if (qualEl) qualEl.style.display = 'flex';
  }

  function rateFc(quality) {
    if (!_fcCards.length || _fcIndex >= _fcCards.length) return;
    var card = _fcCards[_fcIndex];
    apiFetch('/api/journal/flashcards/review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ card_id: card.id, quality: quality }),
    }).then(function (r) {
      if (r.xp_awarded > 0) _fcSessionXp += r.xp_awarded;
      _fcIndex++;
      _renderFcCard();
    }).catch(function (e) { showError(e.message); });
  }

  // ── XP Toast & Confetti ───────────────────────────────────────────────────

  function _showXpToast(msg) {
    var toast = document.createElement('div');
    toast.style.cssText = 'position:fixed;top:80px;right:20px;z-index:9000;' +
      'background:var(--gold);color:#fff;padding:10px 18px;border-radius:10px;' +
      'font-weight:700;font-size:13px;box-shadow:0 4px 16px rgba(0,0,0,.2);' +
      'animation:fadeOut 2.5s forwards';
    toast.textContent = msg;
    if (!document.getElementById('_xpToastStyle')) {
      var s = document.createElement('style');
      s.id = '_xpToastStyle';
      s.textContent = '@keyframes fadeOut{0%{opacity:1;transform:translateY(0)}80%{opacity:1}100%{opacity:0;transform:translateY(-20px)}}';
      document.head.appendChild(s);
    }
    document.body.appendChild(toast);
    setTimeout(function () { toast.remove(); }, 2600);
  }

  function _launchConfetti() {
    var colors = ['#C9A227','#E6C257','#2E8B6F','#3DAA88','#6B5BFF','#E07B39'];
    for (var i = 0; i < 60; i++) {
      (function (delay) {
        setTimeout(function () {
          var p = document.createElement('div');
          p.className = 'j-confetti-piece';
          p.style.cssText = [
            'left:' + (10 + Math.random() * 80) + 'vw',
            'background:' + colors[Math.floor(Math.random() * colors.length)],
            'width:' + (6 + Math.random() * 8) + 'px',
            'height:' + (6 + Math.random() * 8) + 'px',
            'animation-duration:' + (2 + Math.random() * 2) + 's',
            'animation-delay:' + (Math.random() * .5) + 's',
          ].join(';');
          document.body.appendChild(p);
          setTimeout(function () { p.remove(); }, 4500);
        }, delay);
      })(i * 40);
    }
  }

  // ── Part 7: Pre-trade Checklist ──────────────────────────────────────────

  var _checklistItems = [];
  var _checkedIds = [];
  var _cooldownInterval = null;
  var _cooldownDismissed = false;

  function loadChecklist() {
    return apiFetch('/api/journal/checklist')
      .then(function (d) {
        _checklistItems = d.items || [];
        renderChecklist();
        if (d.recent_run) {
          var minAgo = Math.round((Date.now() - new Date(d.recent_run.completed_at + 'Z').getTime()) / 60000);
          var st = el('jClStatus');
          if (st) {
            st.textContent = d.recent_run.passed
              ? t('journal.checklist_passed_prefix', '✅ Чек-лист пройден ') + minAgo + t('journal.min_ago_suffix', ' мин назад')
              : t('journal.checklist_last_run_prefix', '⚠️ Последний прогон ') + minAgo + t('journal.min_ago_suffix', ' мин назад') + t('journal.not_all_items_suffix', ' (не все пункты)');
            st.className = 'j-cl-status ' + (d.recent_run.passed ? 'j-cl-pass' : '');
          }
        }
      }).catch(function () {});
  }

  function renderChecklist() {
    var wrap = el('jChecklistItems');
    if (!wrap) return;
    var enabled = _checklistItems.filter(function (i) { return i.is_enabled; });
    var prog = el('jClProgress');
    if (prog) prog.textContent = '(' + enabled.length + t('journal.items_count_suffix', ' пунктов)');
    if (!_checklistItems.length) {
      wrap.innerHTML = '<div style="font-size:13px;color:var(--muted)">' + t('journal.no_items_msg', 'Нет пунктов') + '</div>';
      return;
    }
    var disableTip = t('journal.disable_tip', 'Отключить');
    var enableTip  = t('journal.enable_tip', 'Включить');
    var deleteTip  = t('journal.delete_tip', 'Удалить');
    wrap.innerHTML = _checklistItems.map(function (item) {
      var checked = _checkedIds.indexOf(item.id) >= 0;
      return '<div class="j-cl-item' + (checked ? ' checked' : '') + (item.is_enabled ? '' : ' disabled') + '" data-id="' + item.id + '">' +
        '<input type="checkbox" ' + (checked ? 'checked' : '') + ' ' + (item.is_enabled ? '' : 'disabled') + '>' +
        '<span class="j-cl-item-text">' + _esc(item.text) + '</span>' +
        '<button class="j-cl-item-del" onclick="SBFJournal.toggleClItem(' + item.id + ')" title="' + (item.is_enabled ? disableTip : enableTip) + '">' +
          (item.is_enabled ? '○' : '●') +
        '</button>' +
        '<button class="j-cl-item-del" onclick="SBFJournal.deleteClItem(' + item.id + ')" title="' + deleteTip + '">✕</button>' +
      '</div>';
    }).join('');
    // Checkbox click
    wrap.querySelectorAll('input[type=checkbox]').forEach(function (cb) {
      cb.addEventListener('change', function () {
        var id = parseInt(cb.closest('.j-cl-item').dataset.id);
        if (cb.checked) {
          if (_checkedIds.indexOf(id) < 0) _checkedIds.push(id);
        } else {
          _checkedIds = _checkedIds.filter(function (x) { return x !== id; });
        }
        renderChecklist();
      });
    });
  }

  function runChecklist() {
    var enabled = _checklistItems.filter(function (i) { return i.is_enabled; });
    if (!enabled.length) { alert(t('journal.add_at_least_one_item', 'Добавьте хотя бы один пункт')); return; }
    apiFetch('/api/journal/checklist/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ checked_ids: _checkedIds }),
    }).then(function (r) {
      var st = el('jClStatus');
      if (st) {
        st.textContent = r.passed
          ? t('journal.checklist_passed_msg', '✅ Чек-лист пройден!')
          : t('journal.checklist_not_all_done_msg', '⚠️ Не все пункты выполнены');
        st.className = 'j-cl-status ' + (r.passed ? 'j-cl-pass' : '');
      }
      if (r.tilt) renderTiltBanner(r.tilt);
      _checkedIds = [];
      renderChecklist();
    }).catch(function (e) { showError(t('journal.error_prefix', 'Ошибка: ') + e.message); });
  }

  function addClItem() {
    var inp = el('jClNewText');
    var text = inp ? inp.value.trim() : '';
    if (!text) return;
    apiFetch('/api/journal/checklist/items', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text }),
    }).then(function () {
      if (inp) inp.value = '';
      loadChecklist();
    }).catch(function (e) { showError(e.message); });
  }

  function toggleClItem(itemId) {
    apiFetch('/api/journal/checklist/items/' + itemId + '/toggle', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      .then(function () { loadChecklist(); })
      .catch(function (e) { showError(e.message); });
  }

  function deleteClItem(itemId) {
    if (!confirm(t('journal.confirm_delete_item', 'Удалить пункт?'))) return;
    apiFetch('/api/journal/checklist/items/' + itemId, { method: 'DELETE' })
      .then(function () { loadChecklist(); })
      .catch(function (e) { showError(e.message); });
  }

  // ── Part 7: Tilt Detector ────────────────────────────────────────────────

  function loadTiltState() {
    return apiFetch('/api/journal/tilt')
      .then(function (d) { renderTiltBanner(d); })
      .catch(function () {});
  }

  function renderTiltBanner(d) {
    var banner = el('jTiltBanner');
    var coolBlock = el('jCooldownBlock');
    if (!banner) return;

    if (!d.is_tilt_detected) {
      banner.style.display = 'none';
    } else {
      banner.style.display = 'block';
      var reasonsEl = el('jTiltReasons');
      if (reasonsEl) {
        reasonsEl.innerHTML = (d.nudges || d.reasons || []).map(function (msg) {
          return '<div class="j-tilt-reason">' + _esc(msg) + '</div>';
        }).join('');
      }
    }

    var remaining = d.cooldown_remaining_min || 0;
    if (coolBlock) {
      if (remaining > 0 && !_cooldownDismissed) {
        coolBlock.style.display = 'block';
        _startCooldownTimer(remaining);
      } else {
        coolBlock.style.display = 'none';
        _stopCooldownTimer();
      }
    }
  }

  function _startCooldownTimer(remainingMin) {
    _stopCooldownTimer();
    var endMs = Date.now() + remainingMin * 60000;
    function tick() {
      var left = Math.max(0, endMs - Date.now());
      var m = Math.floor(left / 60000);
      var s = Math.floor((left % 60000) / 1000);
      var t = el('jCooldownTimer');
      if (t) t.textContent = (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
      if (left <= 0) {
        _stopCooldownTimer();
        var cb = el('jCooldownBlock');
        if (cb) cb.style.display = 'none';
      }
    }
    tick();
    _cooldownInterval = setInterval(tick, 1000);
  }

  function _stopCooldownTimer() {
    if (_cooldownInterval) { clearInterval(_cooldownInterval); _cooldownInterval = null; }
  }

  function dismissCooldown() {
    _cooldownDismissed = true;
    _stopCooldownTimer();
    var cb = el('jCooldownBlock');
    if (cb) cb.style.display = 'none';
  }

  function loadTiltHeatmap() {
    return apiFetch('/api/journal/tilt/heatmap')
      .then(function (d) { renderTiltHeatmap(d); })
      .catch(function () {});
  }

  function renderTiltHeatmap(d) {
    var wrap = el('jTiltHeatmapWrap');
    var tableWrap = el('jTiltHeatmapTable');
    if (!wrap || !tableWrap || !d || d.total === 0) {
      if (wrap) wrap.style.display = 'none';
      return;
    }
    wrap.style.display = 'block';

    var max = 0;
    d.days.forEach(function (day) {
      d.sessions.forEach(function (ses) {
        var v = d.matrix[day][ses] || 0;
        if (v > max) max = v;
      });
    });

    var html = '<table><thead><tr><th></th>';
    d.sessions.forEach(function (s) { html += '<th>' + _esc(s) + '</th>'; });
    html += '</tr></thead><tbody>';
    d.days.forEach(function (day) {
      html += '<tr><td class="j-hm-day">' + _esc(day) + '</td>';
      d.sessions.forEach(function (ses) {
        var v = d.matrix[day][ses] || 0;
        var intensity = max > 0 ? v / max : 0;
        var cls = 'j-hm-0';
        if (intensity > 0.66) cls = 'j-hm-3';
        else if (intensity > 0.33) cls = 'j-hm-2';
        else if (intensity > 0) cls = 'j-hm-1';
        html += '<td class="' + cls + '">' + (v > 0 ? v : '—') + '</td>';
      });
      html += '</tr>';
    });
    html += '</tbody></table>';
    tableWrap.innerHTML = html;
  }

  // ── Part 9: Goals & Seasons ────────────────────────────────────────────
  var _goalsData = null;
  var _seasonData = null;

  function loadGoals() {
    return apiFetch('/api/journal/goals')
      .then(function (d) { _goalsData = d; renderGoals(d); })
      .catch(function () {});
  }

  function loadSeasons() {
    return apiFetch('/api/journal/seasons')
      .then(function (d) { _seasonData = d; renderSeasonWidget(d); })
      .catch(function () {});
  }

  function renderSeasonWidget(d) {
    var wrap = el('jSeasonWidget');
    if (!wrap) return;
    var active = d && d.active;
    if (!active) { wrap.innerHTML = ''; return; }
    var xpGoal = active.xp_goal || 1000;
    var pct = active.total_xp > 0 ? Math.min(100, Math.round(active.total_xp / xpGoal * 100)) : 0;
    wrap.innerHTML =
      '<div class="j-season-bar">' +
        '<div>' +
          '<div class="j-season-name">' + _esc(active.name) + '</div>' +
          '<div class="j-season-meta">' + _esc(active.start_date || '') + ' — ' + _esc(active.end_date || '') +
            ' \xb7 ' + (active.goals_completed || 0) + t('journal.goals_completed_suffix', ' целей выполнено') + '</div>' +
        '</div>' +
        '<div class="j-season-xp">⚡ ' + (active.total_xp || 0) + ' XP</div>' +
        '<button class="j-season-close-btn" onclick="SBFJournal.closeSeason()">' + t('journal.finish_season_btn', 'Завершить сезон') + '</button>' +
      '</div>';
  }

  function renderGoals(d) {
    var listEl = el('jGoalsList');
    if (!listEl) return;
    var goals = (d && d.goals) || [];
    if (!goals.length) {
      listEl.innerHTML = '<div style="font-size:12px;color:var(--muted);padding:8px 0">' + t('journal.no_active_goals_msg', 'Нет активных целей. Выбери пресет или добавь свою.') + '</div>';
      return;
    }
    var deleteTip = t('journal.delete_tip', 'Удалить');
    var deadlinePrefix = t('journal.deadline_prefix', 'до ');
    var completedBadge = t('journal.completed_badge', '✓ Выполнено');
    var html = '';
    goals.forEach(function (g) {
      var pct = g.target > 0 ? Math.min(100, Math.round(g.current / g.target * 100)) : 0;
      var done = g.status === 'completed';
      html +=
        '<div class="j-goal-item">' +
          '<div class="j-goal-left">' +
            '<div class="j-goal-label">' + _esc(g.label || g.kind) + '</div>' +
            '<div class="j-goal-kind">' + _kindLabel(g.kind) + '</div>' +
            '<div class="j-goal-bar-wrap"><div class="j-goal-bar-fill' + (done ? ' done' : '') +
              '" style="width:' + pct + '%"></div></div>' +
            '<div class="j-goal-progress-txt">' + g.current + ' / ' + g.target +
              (g.deadline ? ' \xb7 ' + deadlinePrefix + _esc(g.deadline) : '') + '</div>' +
          '</div>' +
          (done
            ? '<span class="j-goal-done-badge">' + completedBadge + '</span>'
            : '<button class="j-goal-delete" title="' + deleteTip + '" onclick="SBFJournal.deleteGoal(' + g.id + ')">✕</button>') +
        '</div>';
    });
    listEl.innerHTML = html;
  }

  function _kindLabel(kind) {
    var map = {
      journal_streak_days:        ['journal.goal_streak_days', 'Серия дней в журнале'],
      max_risk_per_trade:         ['journal.goal_max_risk', 'Макс. риск на сделку (R)'],
      complete_learning_chapters: ['journal.goal_complete_chapters', 'Главы обучения'],
      maintain_discipline_score:  ['journal.goal_maintain_discipline', 'Дисциплина (%)'],
    };
    var e = map[kind];
    return e ? t(e[0], e[1]) : kind;
  }

  function applyPreset(code) {
    apiFetch('/api/journal/goals/preset/' + encodeURIComponent(code), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    }).then(function (r) {
      if (r && r.id) { loadGoals(); }
      else if (r && r.error) { showError(r.error); }
    }).catch(function (e) { showError(t('journal.error_prefix', 'Ошибка: ') + e.message); });
  }

  function deleteGoal(id) {
    apiFetch('/api/journal/goals/' + id, { method: 'DELETE' })
      .then(function () { loadGoals(); })
      .catch(function () {});
  }

  function createGoal() {
    var kindEl = el('jGoalKind');
    var targetEl = el('jGoalTarget');
    var labelEl = el('jGoalLabel');
    var kind = kindEl && kindEl.value;
    var target = parseFloat((targetEl && targetEl.value) || '0');
    var label = (labelEl && labelEl.value.trim()) || null;
    if (!kind || !target) { showError(t('journal.specify_goal_kind_target', 'Укажи вид цели и целевое значение')); return; }
    apiFetch('/api/journal/goals', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: kind, target: target, label: label })
    }).then(function (r) {
      if (r && r.id) {
        el('jGoalForm').style.display = 'none';
        if (targetEl) targetEl.value = '';
        if (labelEl) labelEl.value = '';
        loadGoals();
      } else if (r && r.error) { showError(r.error); }
    }).catch(function (e) { showError(t('journal.error_prefix', 'Ошибка: ') + e.message); });
  }

  function closeSeason() {
    if (!confirm(t('journal.confirm_close_season', 'Завершить текущий сезон? Прогресс будет сохранён в архиве.'))) return;
    apiFetch('/api/journal/seasons/close', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    }).then(function () { loadSeasons(); loadGoals(); })
      .catch(function (e) { showError(t('journal.error_prefix', 'Ошибка: ') + e.message); });
  }

  // ── Part 10: Account Hub ──────────────────��───────────────────────────────
  var _acctData = null;

  var _TIER_LABELS = { free: 'Free', pro: 'PRO', mentor_mam: 'Mentor MAM' };
  var _BROKER_ICONS = { avatrade: '🅰️', naga: '🔷' };

  function loadAccount() {
    return apiFetch('/api/account')
      .then(function (d) { _acctData = d; renderAccount(d); })
      .catch(function () {});
  }

  function renderAccount(d) {
    if (!d) return;
    _renderSubTier(d.subscription);
    _renderReferral(d.referral);
    _renderBrokers(d.broker_links, d.ib_partners);
    _renderDeletionWarning(d.deletion_pending, d.deletion_info);
  }

  function _renderSubTier(sub) {
    var badge = el('jSubTierBadge');
    var info  = el('jSubRenewInfo');
    if (!sub) return;
    var tier = sub.tier || 'free';
    if (badge) {
      badge.textContent = _TIER_LABELS[tier] || tier;
      badge.className = 'j-tier ' + tier;
    }
    if (info) {
      if (sub.status === 'active' && sub.renew_ts) {
        info.textContent = t('journal.active_until_prefix', 'Активна до ') + sub.renew_ts.replace('T', ' ').slice(0, 16);
      } else if (sub.status === 'expired' || !sub.renew_ts) {
        info.textContent = t('journal.free_tier_msg', 'Бесплатный тариф');
      } else {
        info.textContent = t('journal.status_prefix', 'Статус: ') + (sub.status || '');
      }
    }
  }

  function _renderReferral(ref) {
    var codeEl  = el('jRefCode');
    var statsEl = el('jRefStats');
    if (!ref) return;
    if (codeEl) codeEl.textContent = ref.code || '—';
    if (statsEl) statsEl.textContent = t('journal.invited_prefix', 'Приглашено: ') + (ref.used_count || 0);
  }

  function _renderBrokers(links, partners) {
    var grid = el('jBrokerGrid');
    if (!grid || !partners) return;
    var openAccountLink = t('journal.open_account_link', 'Открыть счёт ↗');
    var verifiedBadge   = t('journal.verified_badge', '✓ Верифицирован');
    var pendingBadge    = t('journal.pending_review_badge', 'На проверке');
    var deleteTip       = t('journal.delete_tip', 'Удалить');
    var noLinkedMsg     = t('journal.no_linked_accounts', 'Нет привязанных счетов');
    var acctNumberPh    = t('journal.trading_account_number_ph', 'Номер торгового счёта');
    var linkBtn         = t('journal.link_btn', 'Привязать');
    var html = '';
    Object.keys(partners).forEach(function (broker) {
      var p = partners[broker];
      var brokerLinks = (links || []).filter(function (l) { return l.broker === broker; });
      var icon = _BROKER_ICONS[broker] || '🏦';
      html +=
        '<div class="j-broker-card">' +
          '<div class="j-broker-card-hd">' +
            '<span class="j-broker-name">' + icon + ' ' + _esc(p.label) + '</span>' +
            '<a class="j-broker-ib-link" href="' + _esc(p.ib_link) + '" target="_blank" rel="noopener">' + openAccountLink + '</a>' +
          '</div>' +
          '<div class="j-broker-accounts">' +
            (brokerLinks.length
              ? brokerLinks.map(function (l) {
                  var stCls = l.status === 'verified' ? ' verified' : '';
                  return '<div class="j-broker-account-row">' +
                    '<span class="j-broker-acct-num">' + _esc(l.account_number) + '</span>' +
                    '<span class="j-broker-acct-status' + stCls + '">' +
                      (l.status === 'verified' ? verifiedBadge : pendingBadge) + '</span>' +
                    '<button class="j-broker-acct-del" ' +
                      'onclick="SBFJournal.deleteBrokerLink(' + l.id + ')" title="' + deleteTip + '">✕</button>' +
                  '</div>';
                }).join('')
              : '<span style="color:var(--muted)">' + noLinkedMsg + '</span>') +
          '</div>' +
          '<div class="j-broker-add-form">' +
            '<input type="text" placeholder="' + acctNumberPh + '" ' +
              'id="jBrokerInput_' + broker + '" maxlength="64">' +
            '<button class="j-btn j-btn-sec" ' +
              'onclick="SBFJournal.addBrokerLink(\'' + broker + '\')">' + linkBtn + '</button>' +
          '</div>' +
        '</div>';
    });
    grid.innerHTML = html;
  }

  function _renderDeletionWarning(pending, info) {
    var warnEl = el('jDelWarn');
    var btn    = el('jDeleteReqBtn');
    if (!warnEl) return;
    if (pending && info) {
      warnEl.style.display = 'block';
      warnEl.textContent   = t('journal.deletion_pending_prefix', 'Запрос на удаление подан. Данные будут удалены ') +
        (info.scheduled_hard_delete_at || '').slice(0, 10) +
        t('journal.deletion_pending_suffix', '. Отменить?');
      if (btn) { btn.textContent = t('journal.cancel_deletion_btn', '↩ Отменить удаление'); btn.onclick = cancelDeletion; }
    } else {
      warnEl.style.display = 'none';
      if (btn) { btn.textContent = t('journal.delete_account', '🗑 Удалить аккаунт'); btn.onclick = requestDeletion; }
    }
  }

  function copyReferralCode() {
    var code = (el('jRefCode') && el('jRefCode').textContent) || '';
    if (!code || code === '—') return;
    navigator.clipboard && navigator.clipboard.writeText(code)
      .then(function () { _showXpToast(0, t('journal.code_copied_prefix', 'Код скопирован: ') + code); })
      .catch(function () { _showXpToast(0, code); });
  }

  function useReferralCode() {
    var inputEl = el('jRefCodeInput');
    var code = (inputEl && inputEl.value.trim()) || '';
    if (!code) { showError(t('journal.enter_referral_code_msg', 'Введи реферальный код')); return; }
    apiFetch('/api/account/referral/use', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: code })
    }).then(function (r) {
      if (r && r.success) {
        if (inputEl) inputEl.value = '';
        _showXpToast(0, t('journal.pro_days_activated_msg', '🎉 +7 дней PRO активировано!'));
        loadAccount();
        loadGameOverview();
      } else if (r && r.error) {
        showError(r.error);
      }
    }).catch(function (e) { showError(t('journal.error_prefix', 'Ошибка: ') + e.message); });
  }

  function addBrokerLink(broker) {
    var inputEl = el('jBrokerInput_' + broker);
    var num = (inputEl && inputEl.value.trim()) || '';
    if (!num) { showError(t('journal.enter_trading_account_number_msg', 'Введи номер торгового счёта')); return; }
    apiFetch('/api/account/broker-links', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ broker: broker, account_number: num })
    }).then(function (r) {
      if (r && r.id) {
        if (inputEl) inputEl.value = '';
        loadAccount();
      } else if (r && r.error) {
        showError(r.error);
      }
    }).catch(function (e) { showError(t('journal.error_prefix', 'Ошибка: ') + e.message); });
  }

  function deleteBrokerLink(id) {
    if (!confirm(t('journal.confirm_delete_broker_link', 'Удалить привязку счёта?'))) return;
    apiFetch('/api/account/broker-links/' + id, { method: 'DELETE' })
      .then(function () { loadAccount(); })
      .catch(function () {});
  }

  function exportMyData() {
    window.location.href = '/api/account/export';
  }

  function requestDeletion() {
    if (!confirm(t('journal.confirm_request_deletion', 'Запросить удаление аккаунта?\nДанные будут удалены через 30 дней.\nВы можете отменить запрос до истечения срока.'))) return;
    apiFetch('/api/account/delete-request', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    }).then(function () { loadAccount(); })
      .catch(function (e) { showError(t('journal.error_prefix', 'Ошибка: ') + e.message); });
  }

  function cancelDeletion() {
    apiFetch('/api/account/delete-cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    }).then(function () { loadAccount(); })
      .catch(function (e) { showError(t('journal.error_prefix', 'Ошибка: ') + e.message); });
  }

  function _handleAnchorScroll() {
    var hash = location.hash.replace('#', '');
    if (!hash) return;
    if (hash === 'discipline') {
      var ds = el('jDiscSection');
      if (ds) ds.style.display = 'block';
    }
    var target = document.getElementById(hash);
    if (target) {
      setTimeout(function () { target.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 300);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.SBFJournal = {
    reload:             loadAll,
    openAdd:            openAddModal,
    openQueue:          openQueue,
    switchAnalyticsTab: switchAnalyticsTab,
    openDiscConfig:     openDiscConfig,
    checkAlerts:        function () { return apiFetch('/api/journal/alerts/check', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(loadNotifications); },
    refreshBrief:       function () { return loadBrief(); },
    openSetup:          openSetupModal,
    // Part 7
    runChecklist:       runChecklist,
    addClItem:          addClItem,
    toggleClItem:       toggleClItem,
    deleteClItem:       deleteClItem,
    dismissCooldown:    dismissCooldown,
    // Part 8
    openFlashcards:     openFlashcards,
    closeFcModal:       closeFcModal,
    revealFcAnswer:     revealFcAnswer,
    rateFc:             rateFc,
    markChapter:        markChapter,
    useStreakFreeze:    useStreakFreeze,
    // Part 9
    loadGoals:          loadGoals,
    loadSeasons:        loadSeasons,
    applyPreset:        applyPreset,
    deleteGoal:         deleteGoal,
    createGoal:         createGoal,
    closeSeason:        closeSeason,
    // Part 10
    loadAccount:        loadAccount,
    copyReferralCode:   copyReferralCode,
    useReferralCode:    useReferralCode,
    addBrokerLink:      addBrokerLink,
    deleteBrokerLink:   deleteBrokerLink,
    exportMyData:       exportMyData,
    requestDeletion:    requestDeletion,
    cancelDeletion:     cancelDeletion,
  };
})();
