/* ============================================================================
   SBF INTELLIGENCE — персистентный топ-бар (хедер + котировки + нав).
   Подключать как <script src="/assets/sbf-header.js" defer></script>.
   На главной странице (/) вводит только HTML-структуру — данные и часы
   берёт на себя index.html через те же DOM-ID (strip, clock, liveDot, …).
   На всех остальных страницах модуль сам тянет котировки и ведёт часы.
   ========================================================================= */
(function () {
  'use strict';

  // В iframe (calendar в m.html, edu в SBFAcademy Mini App, ...) не добавляем
  // НОВУЮ шапку/нав и не тянем живые котировки — но CSS всё равно нужен: у
  // некоторых embed-страниц (edu/index.html) уже есть свой хардкоженный
  // .g-bottom-nav в разметке, и без этого стиля он рендерится голыми
  // подчёркнутыми ссылками вместо иконок — именно эта строка ниже раньше
  // обрывала выполнение ДО инъекции CSS и ломала именно такие страницы.
  var _inIframe = window.self !== window.top;

  // ?embed=1 — SBFAcademy Mini App iframe'ит эту страницу внутрь своих
  // собственных вкладок (у которых уже есть свой нижний нав) — .g-bottom-nav
  // здесь был бы вторым, дублирующим нав-баром. Сама шапка/тикер на
  // не-главных страницах и так не рисуются в iframe (см. return ниже);
  // .g-bottom-nav — единственное, что рендерится независимо от _inIframe.
  if (new URLSearchParams(location.search).get('embed') === '1') {
    document.documentElement.classList.add('sbf-embed');
  }

  // ?autoheight=1 — используется только вкладкой «Сегодня» SBFAcademy Mini App:
  // без этого iframe там был фиксированной высоты и скроллился ВНУТРИ себя,
  // из-за чего скролл всей страницы-хоста не двигался (и завязанная на него
  // логика — прячущаяся при скролле цитата дня — никогда не срабатывала).
  // Сообщаем родителю реальную высоту контента, чтобы он растянул iframe
  // под неё и скролл стал общим. Не включаем это по умолчанию для всех
  // embed-страниц (Обучение/График/Глоссарий), чтобы не менять их поведение.
  if (_inIframe && new URLSearchParams(location.search).get('autoheight') === '1') {
    var _reportHeight = function () {
      try {
        window.parent.postMessage(
          { type: 'sbf-resize', height: document.documentElement.scrollHeight },
          'https://web.sbfconsult.com'
        );
      } catch (e) { /* ignore */ }
    };
    if ('ResizeObserver' in window) {
      new ResizeObserver(_reportHeight).observe(document.documentElement);
    } else {
      window.addEventListener('load', _reportHeight);
    }
  }

  var path = location.pathname;
  // /ro/<...> — те же маршруты, что и без префикса (см. i18n.lang_from_path на
  // сервере); без этой нормализации isMain/isCalendar/isJournal ломаются на
  // /ro/-страницах (пример реальной поломки: на /ro/ isMain оказывался false,
  // и поверх собственного инлайн-скрипта index.html поверх тех же #clock/
  // #liveDot/#winTxt начинал параллельно писать ещё и clockTick()/setLive()
  // из этого файла — гонка за одни и те же элементы).
  var _bare = path.replace(/^\/ro(?=\/|$)/, '') || '/';
  var isMain     = _bare === '/' || _bare === '/index.html';
  var isCalendar = _bare === '/calendar' || _bare.startsWith('/edu/calendar');
  var isJournal  = _bare === '/journal.html' || _bare === '/journal';
  var isEdu      = !isMain && !isCalendar && !isJournal;

  // Detect edu book pages for RU/RO/EN switcher: /edu/b/n, /edu/ro/b/n, /edu/en/b/n
  var _bookM = path.match(/\/edu\/(ro\/|en\/)?b\/(\d+)/);
  var bookNum  = _bookM ? _bookM[2] : null;
  var bookLang = _bookM ? (_bookM[1] ? _bookM[1].replace('/', '') : 'ru') : null;

  function navCls(page) {
    if (page === 'today'    && isMain)     return 'active';
    if (page === 'calendar' && isCalendar) return 'active';
    if (page === 'journal'  && isJournal)  return 'active';
    if (page === 'edu'      && isEdu)      return 'active';
    return '';
  }

  // ── CSS ──────────────────────────────────────────────────────────────────
  var CSS = [
    ':root{--cream:#FBF6EF;--paper:#FFFFFF;--line:#E7DFCF;',
    '--ink:#2B2B33;--muted:#8A8275;--faint:#C5BAA8;',
    '--gold:#C9A227;--glow:#E6C257;--up:#1e8e5a;--down:#c0392b;}',

    '.sbf-hd{display:flex;align-items:center;gap:18px;padding:10px 24px;',
    'border-bottom:1px solid var(--line);background:var(--paper);',
    'position:sticky;top:0;z-index:50;box-shadow:0 2px 12px rgba(43,43,51,.06);}',
    '.sbf-brand{display:flex;align-items:center;gap:12px;text-decoration:none;}',
    '.sbf-brand .logo-wrap{width:44px;height:44px;display:flex;align-items:center;',
    'justify-content:center;flex-shrink:0;}',
    '.sbf-brand .logo-wrap img{width:44px;height:44px;object-fit:contain;}',
    '.sbf-brand-text b{font-weight:700;font-size:15px;letter-spacing:.5px;color:var(--ink);}',
    '.sbf-brand-text span{color:var(--muted);font-size:11px;display:block;margin-top:1px;}',

    '.sbf-hd .g-nav{display:flex;gap:2px;margin-left:16px;}',
    '.sbf-hd .g-nav-item{font-family:Montserrat,system-ui,sans-serif;font-size:13px;',
    'font-weight:600;color:var(--muted);text-decoration:none;padding:6px 11px;',
    'border-radius:7px;transition:color .12s,background .12s;white-space:nowrap;}',
    '.sbf-hd .g-nav-item:hover{color:var(--ink);background:rgba(201,162,39,.08);text-decoration:none;}',
    '.sbf-hd .g-nav-item.active{color:var(--gold);font-weight:700;}',

    '.sbf-right{margin-left:auto;display:flex;align-items:center;gap:18px;',
    'font-size:12px;font-family:"JetBrains Mono",monospace;}',

    '.sbf-lang-sw{display:flex;gap:2px;align-items:center;margin-left:8px;}',
    '.sbf-lang-sw a{font-family:"JetBrains Mono",monospace;font-size:11px;font-weight:700;',
    'letter-spacing:1.5px;text-decoration:none;color:var(--muted);padding:4px 7px;',
    'border-radius:5px;transition:color .15s,background .15s;}',
    '.sbf-lang-sw a.active{color:var(--gold);}',
    '.sbf-lang-sw a:hover{color:var(--ink);background:rgba(201,162,39,.08);text-decoration:none;}',
    '.sbf-win{display:flex;align-items:center;gap:6px;color:var(--muted);}',
    '.dot{width:7px;height:7px;border-radius:50%;background:var(--faint);}',
    '.dot.on{background:var(--up);box-shadow:0 0 7px var(--up);}',
    '#clock{color:var(--ink);font-weight:500;}',

    '.strip{overflow:hidden;border-bottom:1px solid var(--line);',
    'background:var(--paper);position:sticky;top:65px;z-index:40;}',
    '.strip-i{display:flex;flex-wrap:nowrap;width:max-content;will-change:transform;}',
    '.tick{padding:9px 16px;border-right:1px solid var(--line);min-width:112px;flex:0 0 auto;cursor:default;}',
    '.tick .k{font-size:10px;color:var(--muted);letter-spacing:.5px;text-transform:uppercase;font-weight:600;}',
    '.tick .v{font-family:"JetBrains Mono",monospace;font-weight:600;font-size:14px;margin-top:3px;color:var(--ink);}',
    '.tick .c{font-family:"JetBrains Mono",monospace;font-size:11px;margin-top:1px;}',
    '.up{color:var(--up);}.down{color:var(--down);}',
    '.fng{padding:9px 16px;min-width:150px;flex:0 0 auto;}',
    '.fng .k{font-size:10px;color:var(--muted);letter-spacing:.5px;text-transform:uppercase;font-weight:600;}',
    '.fng .v{font-family:"JetBrains Mono",monospace;font-weight:600;font-size:14px;margin-top:3px;color:var(--ink);}',
    '.fng .bar{height:5px;border-radius:3px;margin-top:7px;',
    'background:linear-gradient(90deg,var(--down),var(--gold),var(--up));}',
    '.fng .mark{width:2px;height:9px;background:var(--ink);position:relative;top:-7px;border-radius:1px;}',

    '@keyframes sbfFlashUp{0%,30%{color:var(--up)}100%{color:var(--ink)}}',
    '@keyframes sbfFlashDn{0%,30%{color:var(--down)}100%{color:var(--ink)}}',
    '.fl-up{animation:sbfFlashUp .9s ease-out forwards;}',
    '.fl-dn{animation:sbfFlashDn .9s ease-out forwards;}',

    '.g-bottom-nav{display:none;position:fixed;bottom:0;left:0;right:0;',
    'background:var(--paper);border-top:1px solid var(--line);z-index:200;',
    'box-shadow:0 -2px 16px rgba(43,43,51,.07);',
    'padding-bottom:env(safe-area-inset-bottom);}',

    // Compact mobile header bar
    '.sbf-mob-bar{display:none;align-items:center;gap:9px;padding:10px 14px;',
    'background:var(--cream,#FBF6EF);border-bottom:1px solid var(--line,#E7DFCF);',
    'position:sticky;top:0;z-index:55;}',
    '.sbf-mob-bar img{width:32px;height:32px;object-fit:contain;flex-shrink:0}',
    '.sbf-mob-bar .mob-brand{font-weight:700;font-size:13px;letter-spacing:.3px;color:var(--ink,#2B2B33)}',
    '.sbf-mob-bar .mob-time{margin-left:auto;display:flex;align-items:center;gap:5px;',
    'font-size:11px;color:var(--muted,#8A8275);font-family:"JetBrains Mono",monospace}',
    '.sbf-mob-bar .mob-dot{width:7px;height:7px;border-radius:50%;',
    'background:var(--up,#1e8e5a);box-shadow:0 0 6px var(--up,#1e8e5a);',
    'animation:mobPulse 1.6s infinite;flex-shrink:0}',
    '.sbf-mob-bar .mob-dot.off{background:var(--faint,#ccc);box-shadow:none;animation:none}',
    '@keyframes mobPulse{50%{opacity:.4}}',
    '.strip{transition:transform .2s ease;}',

    '@media(max-width:760px){',
    '.sbf-hd{display:none!important;}',
    '.sbf-mob-bar{display:flex!important;}',
    '.strip{top:50px!important;}',
    'body{padding-bottom:58px!important;}',
    '.g-bottom-nav{display:flex;}}',
    '.g-bn-item{flex:1;display:flex;flex-direction:column;align-items:center;',
    'justify-content:center;gap:3px;text-decoration:none;color:var(--muted);',
    'padding:6px 0 8px;transition:color .12s;-webkit-tap-highlight-color:transparent;}',
    '.g-bn-item.active{color:var(--gold);}',
    '.g-bn-item:hover{color:var(--ink);text-decoration:none;}',
    '.g-bn-ico{font-size:20px;line-height:1;}',
    '.g-bn-lbl{font-family:"JetBrains Mono",monospace;font-size:11px;letter-spacing:.4px;',
    'font-weight:600;text-transform:uppercase;}',
    '.sbf-embed .g-bottom-nav, .sbf-embed .sbf-mob-bar, .sbf-embed .sbf-fw-btn, .sbf-embed .sbf-fw-bubble{display:none!important;}'
  ].join('');

  var st = document.createElement('style');
  st.textContent = CSS;
  document.head.appendChild(st);

  // CSS применён (что и было нужно для уже существующей на странице разметки).
  // Дальше — добавление НОВОГО хедера/нава и живые котировки/часы: в iframe это
  // не нужно (снаружи уже есть свой хост-хром) и просто расходует ресурсы.
  if (_inIframe) return;

  // ── i18n (см. assets/i18n.js) ───────────────────────────────────────────
  // Шапка вставляется СИНХРОННО (как и раньше) — sbf-profile.js/sbf-feedback.js
  // ожидают .g-bottom-nav в DOM сразу после выполнения этого скрипта. Поэтому
  // текст статичных лейблов (nav/tagline) не ждёт словарь: t(key, fallback)
  // либо сразу отдаёт готовый перевод (если словарь уже успел загрузиться),
  // либо русский fallback — и через data-i18n правится один раз ниже, когда
  // sbfI18n.ready резолвится.
  var _i18n = window.sbfI18n || { lang: 'ru', t: function (k, fb) { return fb || k; }, ready: Promise.resolve() };
  function t(key, fallback) { return _i18n.t(key, fallback); }

  function otherLangHref(lang) {
    var isRo = /^\/ro(\/|$)/.test(path);
    if (lang === 'ro') return isRo ? path : ('/ro' + (path === '/' ? '' : path));
    return isRo ? (path.replace(/^\/ro/, '') || '/') : path;
  }

  // ── HTML ─────────────────────────────────────────────────────────────────
  var isCharts = path === '/chart.html' || path.includes('/chart');

  var _hdHtml = [
    '<header class="sbf-hd">',
    '  <a href="/" class="sbf-brand">',
    '    <div class="logo-wrap"><img src="/assets/logo.png" alt="SBF"></div>',
    '    <div class="sbf-brand-text"><b>SBF INTELLIGENCE</b><span data-i18n="brand.tagline">' + t('brand.tagline', 'рыночная разведка · sbfconsult.com') + '</span></div>',
    '  </a>',
    '  <nav class="g-nav">',
    '    <a href="/"           class="g-nav-item ' + navCls('today')    + '" data-i18n="nav.today">' + t('nav.today', 'Сегодня') + '</a>',
    '    <a href="/edu/"       class="g-nav-item ' + navCls('edu')       + '" data-i18n="nav.edu">' + t('nav.edu', 'Обучение') + '</a>',
    '    <a href="/calendar"   class="g-nav-item ' + navCls('calendar')  + '" data-i18n="nav.calendar">' + t('nav.calendar', 'Календарь') + '</a>',
    '  </nav>',
    '  <div class="sbf-right">',
    '    <div class="sbf-win"><span class="dot" id="liveDot"></span><span id="liveTxt">Live</span></div>',
    '    <div class="sbf-win"><span class="dot" id="winDot"></span><span id="winTxt">—</span></div>',
    '    <div id="clock">—</div>',
    bookNum
      ? '    <div class="sbf-lang-sw">' +
        '<a href="/edu/b/' + bookNum + '"' + (bookLang === 'ru' ? ' class="active"' : '') + '>RU</a>' +
        '<a href="/edu/ro/b/' + bookNum + '"' + (bookLang === 'ro' ? ' class="active"' : '') + '>RO</a>' +
        '<a href="/edu/en/b/' + bookNum + '"' + (bookLang === 'en' ? ' class="active"' : '') + '>EN</a>' +
        '</div>'
      : '    <div class="sbf-lang-sw">' +
        '<a href="' + otherLangHref('ru') + '"' + (_i18n.lang === 'ru' ? ' class="active"' : '') + '>RU</a>' +
        '<a href="' + otherLangHref('ro') + '"' + (_i18n.lang === 'ro' ? ' class="active"' : '') + '>RO</a>' +
        '</div>',
    '  </div>',
    '</header>',
    '<div class="sbf-mob-bar" id="sbfMobBar">',
    '  <img src="/assets/logo.png" alt="SBF">',
    '  <span class="mob-brand">SBF INTELLIGENCE</span>',
    '  <div class="mob-time"><span class="mob-dot" id="mobLiveDot"></span><span id="mobClock">—</span></div>',
    '</div>',
    '<div class="strip" id="strip"><div class="strip-i" id="stripI"></div></div>'
  ].join('\n');

  // Bottom nav built separately so position:fixed is never trapped inside a stacking parent
  var _navHtml = [
    '<a href="/"           class="g-bn-item ' + navCls('today')    + '"><span class="g-bn-ico">☀️</span><span class="g-bn-lbl" data-i18n="nav.today">' + t('nav.today', 'Сегодня') + '</span></a>',
    // Profile injected here as 2nd by sbf-profile.js
    '<a href="/edu/"     class="g-bn-item ' + navCls('edu')       + '"><span class="g-bn-ico">📚</span><span class="g-bn-lbl" data-i18n="nav.edu">' + t('nav.edu', 'Обучение') + '</span></a>',
    '<a href="/calendar" class="g-bn-item ' + navCls('calendar')  + '"><span class="g-bn-ico">📅</span><span class="g-bn-lbl" data-i18n="nav.calendar">' + t('nav.calendar', 'Календарь') + '</span></a>'
  ].join('\n');

  function inject() {
    // Inject full header only if page has no own strip
    if (!document.getElementById('strip')) {
      var hd = document.createElement('div');
      hd.innerHTML = _hdHtml;
      document.body.insertAdjacentElement('afterbegin', hd);
    }
    // Always inject bottom nav (single source of truth for all pages)
    if (!document.querySelector('.g-bottom-nav')) {
      var nav = document.createElement('nav');
      nav.className = 'g-bottom-nav';
      nav.innerHTML = _navHtml;
      document.body.appendChild(nav);
    }
  }
  if (document.body) { inject(); }
  else { document.addEventListener('DOMContentLoaded', inject); }

  // Статичные лейблы (nav/tagline) вставлены синхронно с русским fallback —
  // как только словарь догрузится (обычно за десятки мс), одноразово
  // подставляем реальный перевод по data-i18n. Общий механизм на будущее:
  // любой новый статичный текст в шапке достаточно пометить data-i18n="key".
  _i18n.ready.then(function () {
    if (_i18n.lang === 'ru') return;
    var nodes = document.querySelectorAll('[data-i18n]');
    for (var i = 0; i < nodes.length; i++) {
      nodes[i].textContent = t(nodes[i].getAttribute('data-i18n'), nodes[i].textContent);
    }
  });

  // На главной странице index.html сам управляет данными через те же DOM-ID.
  if (isMain) return;

  // ── Хелперы (только для не-главных страниц) ──────────────────────────────
  var safeId = function (s) { return s.replace(/[^a-zA-Z0-9]/g, '_'); };
  var fmt = function (n) {
    if (n == null) return '—';
    return Math.abs(n) >= 1000 ? n.toLocaleString('en-US', { maximumFractionDigits: 2 }) : String(n);
  };
  var NAMES = {
    'GC=F':'GOLD','SI=F':'SILVER',
    'BTC-USD':'BTCUSD','ETH-USD':'ETHUSD','SOL-USD':'SOLUSD',
    'EURUSD=X':'EURUSD','GBPUSD=X':'GBPUSD',
    '^GSPC':'S&P 500','^IXIC':'Nasdaq','^DJI':'Dow Jones','^VIX':'VIX','DX-Y.NYB':'DXY'
  };
  function tickerName(ticker) {
    if (ticker === 'CL=F') return t('ticker.wti', 'Нефть WTI');
    if (ticker === 'NG=F') return t('ticker.gas', 'Природный газ');
    return NAMES[ticker];
  }
  var BYBIT_MAP = { 'BTCUSDT':'BTC-USD','ETHUSDT':'ETH-USD','SOLUSDT':'SOL-USD' };
  var _fng = null;
  var _live = {};

  // ── Тикер (marquee) ───────────────────────────────────────────────────────
  var _stripPos = 0, _stripHalf = 0, _stripPaused = false;

  function buildStrip(items) {
    var inner = document.getElementById('stripI');
    if (!inner) return;
    var html = (items || []).map(function (i) {
      var chg = i.change_pct;
      var cls = chg > 0 ? 'up' : chg < 0 ? 'down' : '';
      var sign = chg > 0 ? '+' : '';
      var name = tickerName(i.ticker) || i.name || i.ticker;
      _live[i.ticker] = i.price;
      return '<div class="tick"><div class="k">' + name + '</div>' +
        '<div class="v" id="sp_' + safeId(i.ticker) + '">' + fmt(i.price) + '</div>' +
        '<div class="c ' + cls + '" id="sc_' + safeId(i.ticker) + '">' +
        (chg != null ? sign + chg.toFixed(2) + '%' : '—') + '</div></div>';
    }).join('');
    if (_fng) {
      var v = _fng.value;
      html += '<div class="fng"><div class="k">Crypto F&amp;G</div>' +
        '<div class="v">' + v + ' · ' + _fng.label + '</div>' +
        '<div class="bar"></div><div class="mark" style="margin-left:' + v + '%"></div></div>';
    }
    inner.innerHTML = html + html; // duplicate for seamless loop
    _stripHalf = 0; // reset so _frame recalculates
  }

  function _stripFrame() {
    var inner = document.getElementById('stripI');
    if (inner && !_stripPaused) {
      if (!_stripHalf && inner.scrollWidth > 0) _stripHalf = inner.scrollWidth / 2;
      if (_stripHalf) {
        _stripPos += 0.5;
        if (_stripPos >= _stripHalf) _stripPos = 0;
        inner.style.transform = 'translateX(-' + _stripPos + 'px)';
      }
    }
    requestAnimationFrame(_stripFrame);
  }

  (function initStripMarquee() {
    var strip = document.getElementById('strip');
    if (strip) {
      strip.addEventListener('mouseenter', function () { _stripPaused = true; });
      strip.addEventListener('mouseleave', function () { _stripPaused = false; });
    }
    requestAnimationFrame(_stripFrame);
  }());

  function updateStripPrice(sym, price) {
    var el = document.getElementById('sp_' + safeId(sym));
    if (!el) return;
    var prev = _live[sym];
    _live[sym] = price;
    el.textContent = fmt(price);
    if (prev != null && price !== prev) {
      var cls = price > prev ? 'fl-up' : 'fl-dn';
      el.classList.remove('fl-up', 'fl-dn');
      void el.offsetWidth;
      el.classList.add(cls);
    }
  }

  // ── Часы и окно ──────────────────────────────────────────────────────────
  function clockTick() {
    var d = new Date(), h = d.getHours();
    var t = d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    var clockEl = document.getElementById('clock');
    if (clockEl) clockEl.textContent = t;
    var mobClockEl = document.getElementById('mobClock');
    if (mobClockEl) mobClockEl.textContent = t;
    var inWin = h >= 6 && h < 10;
    var winDot = document.getElementById('winDot');
    var winTxt = document.getElementById('winTxt');
    if (winDot) winDot.className = 'dot' + (inWin ? ' on' : '');
    if (winTxt) winTxt.textContent = inWin ? t('clock.morning_window', 'Утренний синтез') : t('clock.always_on', 'Скрипты 24/7');
  }
  clockTick();
  setInterval(clockTick, 60000);
  _i18n.ready.then(clockTick); // подставить перевод сразу, не ждать минуту до первого interval

  function setLive(ok) {
    var liveDot = document.getElementById('liveDot');
    var liveTxt = document.getElementById('liveTxt');
    if (liveDot) liveDot.className = 'dot' + (ok ? ' on' : '');
    if (liveTxt) liveTxt.textContent = ok ? t('live.on', 'Live') : t('live.retry', 'retry…');
    var mobLiveDot = document.getElementById('mobLiveDot');
    if (mobLiveDot) mobLiveDot.className = 'mob-dot' + (ok ? '' : ' off');
  }

  // ── Данные: market.json + quotes.json + Bybit WS ─────────────────────────
  async function pollQuotes() {
    try {
      var r = await fetch('/data/quotes.json?t=' + Date.now());
      var q = r.ok ? await r.json() : null;
      if (!q) { setLive(false); return; }
      for (var sym in (q.quotes || {})) {
        var d = q.quotes[sym];
        if (d.price != null) updateStripPrice(sym, d.price);
        if (d.change_pct != null) {
          var ce = document.getElementById('sc_' + safeId(sym));
          if (ce) {
            var chg = d.change_pct;
            ce.textContent = (chg > 0 ? '+' : '') + chg.toFixed(2) + '%';
            ce.className = 'c ' + (chg > 0 ? 'up' : chg < 0 ? 'down' : '');
          }
        }
      }
      setLive(true);
    } catch (e) { setLive(false); }
  }

  async function loadMarket() {
    try {
      var r = await fetch('/data/market.json?t=' + Date.now());
      var m = r.ok ? await r.json() : null;
      if (!m) return;
      if (m.fear_greed) _fng = m.fear_greed;
      if (m.items) buildStrip(m.items);
    } catch (e) {}
  }

  var _ws = null;
  function startBybitWS() {
    try {
      _ws = new WebSocket('wss://stream.bybit.com/v5/public/spot');
      _ws.onopen = function () {
        _ws.send(JSON.stringify({
          op: 'subscribe',
          args: Object.keys(BYBIT_MAP).map(function (s) { return 'tickers.' + s; })
        }));
      };
      _ws.onmessage = function (ev) {
        try {
          var m = JSON.parse(ev.data);
          if (!m.topic || !m.data || !m.data.lastPrice) return;
          var bsym = m.topic.replace('tickers.', '');
          var ysym = BYBIT_MAP[bsym];
          if (ysym) updateStripPrice(ysym, parseFloat(m.data.lastPrice));
        } catch (e) {}
      };
      _ws.onerror = function () {};
      _ws.onclose = function () { setTimeout(startBybitWS, 5000); };
    } catch (e) { setTimeout(startBybitWS, 5000); }
  }

  loadMarket();
  pollQuotes();
  setInterval(pollQuotes, 10000);
  setInterval(loadMarket, 300000);
  startBybitWS();

  // Strip scroll-hide (mobile only): slides up on scroll down, returns on scroll up
  (function() {
    if (window.innerWidth > 768) return;
    var lastY = 0, hidden = false;
    window.addEventListener('scroll', function() {
      if (window.innerWidth > 768) return;
      var y = window.pageYOffset;
      var diff = y - lastY;
      var strip = document.getElementById('strip');
      if (diff > 8 && !hidden && y > 50) {
        hidden = true;
        if (strip) strip.style.transform = 'translateY(-100%)';
      } else if (diff < -8 && hidden) {
        hidden = false;
        if (strip) strip.style.transform = '';
      }
      lastY = y;
    }, { passive: true });
  }());

})();

// i18n.js НЕ автозагружаем отсюда — sbf-header.js сам строит переведённую
// шапку (нужен словарь ДО того, как этот файл дойдёт до низа и что-то
// заинжектил бы), поэтому i18n.js подключён отдельным <script> пораньше в
// <head> каждой страницы (до sbf-header.js). См. ниже — построение шапки
// дожидается sbfI18n.ready.

// Автозагрузка общего auth-клиента (sbf-auth.js) — ДО профиля и фидбека,
// оба используют window.sbfAuth.
(function () {
  var s = document.createElement('script');
  s.src = '/assets/sbf-auth.js?v=1';
  s.async = false;
  document.head.appendChild(s);
})();

// Автозагрузка модуля профиля
(function () {
  var s = document.createElement('script');
  s.src = '/assets/sbf-profile.js?v=2';
  s.async = false;
  document.head.appendChild(s);
})();

// Автозагрузка виджета обратной связи
(function () {
  var s = document.createElement('script');
  s.src = '/assets/sbf-feedback.js?v=1';
  s.async = false;
  document.head.appendChild(s);
})();
