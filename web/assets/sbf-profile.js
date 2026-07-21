/* ============================================================================
   SBF PROFILE v1.0 — аватар, профильная панель, личный кабинет (Phase 0)
   Загружается автоматически через sbf-header.js на всех страницах.
   Хранилище: localStorage key 'sbf_profile'.
   ============================================================================ */
(function () {
  'use strict';

  // ── i18n (см. assets/i18n.js, паттерн — sbf-header.js) ───────────────────
  var _i18n = window.sbfI18n || { lang: 'ru', t: function (k, fb) { return fb || k; }, ready: Promise.resolve() };
  function t(key, fallback) { return _i18n.t(key, fallback); }

  // Патч-пасс для узлов, отрисованных ДО того как словарь догрузился:
  // data-i18n → textContent, data-i18n-aria → aria-label, data-i18n-ph → placeholder.
  function _patchI18n(root) {
    if (_i18n.lang === 'ru') return;
    var sel = '[data-i18n],[data-i18n-aria],[data-i18n-ph]';
    var found = Array.prototype.slice.call(root.querySelectorAll(sel));
    if (root.matches && root.matches(sel)) found.unshift(root);
    found.forEach(function (el) {
      if (el.hasAttribute('data-i18n')) el.textContent = t(el.getAttribute('data-i18n'), el.textContent);
      if (el.hasAttribute('data-i18n-aria')) el.setAttribute('aria-label', t(el.getAttribute('data-i18n-aria'), el.getAttribute('aria-label')));
      if (el.hasAttribute('data-i18n-ph')) el.setAttribute('placeholder', t(el.getAttribute('data-i18n-ph'), el.getAttribute('placeholder')));
    });
  }

  var KEY = 'sbf_profile';

  // ── Хранилище ────────────────────────────────────────────────────────────────
  function load() {
    try { return JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { return {}; }
  }
  function save(d) { localStorage.setItem(KEY, JSON.stringify(d)); }

  // ── Утилиты ──────────────────────────────────────────────────────────────────
  function getInitials(p) {
    var a = (p.firstName || '').trim(), b = (p.lastName || '').trim();
    if (!a && !b) return '?';
    return ((a[0] || '') + (b[0] || '')).toUpperCase();
  }

  var GRADS = [
    ['#C9A227','#E6C257'], ['#2E8B6F','#3DAA88'], ['#6B5BFF','#9B8FFF'],
    ['#3A7BD5','#6EA3F5'], ['#E07B39','#F0A060'], ['#C0504D','#D97B78']
  ];
  function pickGrad(name) {
    var h = 0;
    for (var i = 0; i < (name || 'A').length; i++) h = (h * 31 + (name || 'A').charCodeAt(i)) & 0xFFFF;
    return GRADS[h % GRADS.length];
  }

  // Алгоритм уровней (спецификация 0.2): XP_total(n) = 500 * (n-1)^1.3
  function calcLevel(xp) {
    xp = Math.max(0, xp | 0);
    var lvl = 1;
    for (;;) {
      if (xp >= Math.floor(500 * Math.pow(lvl, 1.3))) lvl++; else break;
    }
    var base = lvl === 1 ? 0 : Math.floor(500 * Math.pow(lvl - 1, 1.3));
    var next = Math.floor(500 * Math.pow(lvl, 1.3));
    return { level: lvl, xp: xp, progress: (next > base) ? (xp - base) / (next - base) : 0,
             xpInLevel: xp - base, xpToNext: next - base };
  }

  var TITLES = ['Новичок','Наблюдатель','Аналитик','Тактик','Стратег','Мастер','Эксперт','Профессионал'];
  var TITLE_KEYS = [
    'profile.level_title_1', 'profile.level_title_2', 'profile.level_title_3', 'profile.level_title_4',
    'profile.level_title_5', 'profile.level_title_6', 'profile.level_title_7', 'profile.level_title_8'
  ];
  function lvlTitle(n) {
    var idx = Math.min(n - 1, TITLES.length - 1);
    return t(TITLE_KEYS[idx], TITLES[idx]);
  }

  function esc(s) {
    return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // ── CSS ──────────────────────────────────────────────────────────────────────
  var CSS = [
    // Базовый аватар (круг — работает и как <button>, и как <div>)
    '.sbf-av{box-sizing:border-box;flex-shrink:0;border-radius:50%;',
    'border:2px solid var(--gold,#C9A227);',
    'display:flex;align-items:center;justify-content:center;overflow:hidden;',
    'font-family:Montserrat,system-ui,sans-serif;font-weight:700;color:#fff;',
    'background:linear-gradient(135deg,#C9A227,#E6C257);',
    'user-select:none;-webkit-tap-highlight-color:transparent;}',

    'button.sbf-av{cursor:pointer;padding:0;outline:none;}',
    'button.sbf-av:hover{box-shadow:0 0 0 3px rgba(201,162,39,.3);transform:scale(1.06);}',
    'button.sbf-av:focus-visible{box-shadow:0 0 0 3px rgba(201,162,39,.5);}',

    '.sbf-login-link{margin-left:10px;padding:7px 16px;border-radius:8px;',
    'background:var(--gold,#C9A227);color:#fff;font-family:Montserrat,sans-serif;',
    'font-size:12px;font-weight:700;text-decoration:none;white-space:nowrap;',
    'transition:background .12s;}',
    '.sbf-login-link:hover{background:#B8931F;}',
    '.sbf-av img{width:100%;height:100%;object-fit:cover;display:block;}',
    // Аватар внутри кнопки (не кликабельный сам по себе)
    '.sbf-av-in{pointer-events:none;}',

    // Кнопка профиля в нижнем навигаторе
    '.sbf-bn-prof{background:none;border:none;font-family:inherit;',
    'flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;',
    'gap:3px;text-decoration:none;color:var(--muted,#7C7563);',
    'padding:6px 0 8px;transition:color .12s;cursor:pointer;',
    '-webkit-tap-highlight-color:transparent;}',
    '.sbf-bn-prof:hover{color:var(--ink,#2B2B33);}',
    '.sbf-bn-prof:hover .sbf-av{box-shadow:0 0 0 3px rgba(201,162,39,.28);}',

    // Панель — оверлей
    '.sbf-pp-ov{display:none;position:fixed;inset:0;z-index:1000;',
    'background:rgba(43,43,51,.4);backdrop-filter:blur(3px);',
    '-webkit-backdrop-filter:blur(3px);transition:opacity .2s;}',
    '.sbf-pp-ov.open{display:block;}',

    // Панель — ящик справа (desktop) / снизу (mobile)
    '.sbf-pp{position:fixed;top:0;right:0;height:100dvh;width:360px;max-width:100vw;',
    'background:var(--paper,#fff);border-left:1px solid var(--line,#E7DFCF);',
    'z-index:1001;transform:translateX(100%);',
    'transition:transform .26s cubic-bezier(.4,0,.2,1);',
    'display:flex;flex-direction:column;',
    'box-shadow:-6px 0 40px rgba(43,43,51,.16);}',
    '.sbf-pp.open{transform:translateX(0);}',

    '@media(max-width:640px){',
    '.sbf-pp{top:auto;bottom:0;right:0;height:auto;max-height:93dvh;width:100%;',
    'border-left:none;border-top:1px solid var(--line,#E7DFCF);',
    'border-radius:20px 20px 0 0;',
    'transform:translateY(110%);',
    'box-shadow:0 -6px 40px rgba(43,43,51,.16);}',
    '.sbf-pp.open{transform:translateY(0);}}',

    // Drag handle (mobile)
    '.sbf-pp-drag{justify-content:center;padding:10px 0 4px;display:none;}',
    '.sbf-pp-drag::after{content:"";width:40px;height:4px;',
    'background:var(--line,#E7DFCF);border-radius:2px;display:block;}',
    '@media(max-width:640px){.sbf-pp-drag{display:flex;}}',

    // Шапка панели
    '.sbf-pp-hd{display:flex;align-items:center;padding:14px 20px 12px;',
    'border-bottom:1px solid var(--line,#E7DFCF);flex-shrink:0;}',
    '.sbf-pp-hd h3{margin:0;font-size:15px;font-weight:700;',
    'color:var(--ink,#2B2B33);flex:1;letter-spacing:.2px;}',
    '.sbf-pp-x{width:30px;height:30px;border:none;',
    'background:rgba(43,43,51,.06);border-radius:50%;cursor:pointer;',
    'display:flex;align-items:center;justify-content:center;',
    'font-size:14px;color:var(--muted,#8A8275);',
    'transition:background .12s;padding:0;flex-shrink:0;outline:none;}',
    '.sbf-pp-x:hover{background:rgba(43,43,51,.12);}',

    // Тело панели
    '.sbf-pp-body{flex:1;overflow-y:auto;padding:22px 20px 28px;',
    '-webkit-overflow-scrolling:touch;}',

    // Секция аватара
    '.sbf-pp-av-area{display:flex;flex-direction:column;align-items:center;margin-bottom:22px;}',
    '.sbf-pp-av-btn{position:relative;cursor:pointer;border:none;background:none;padding:0;}',
    '.sbf-pp-av-btn:hover .sbf-pp-av-ed{opacity:1;}',
    '.sbf-pp-av-lg{width:80px;height:80px;border-radius:50%;',
    'border:3px solid var(--gold,#C9A227);',
    'display:flex;align-items:center;justify-content:center;overflow:hidden;',
    'font-family:Montserrat,sans-serif;font-size:28px;font-weight:700;color:#fff;',
    'background:linear-gradient(135deg,#C9A227,#E6C257);}',
    '.sbf-pp-av-lg img{width:100%;height:100%;object-fit:cover;display:block;}',
    '.sbf-pp-av-ed{position:absolute;bottom:2px;right:2px;width:24px;height:24px;',
    'background:var(--gold,#C9A227);border-radius:50%;',
    'display:flex;align-items:center;justify-content:center;',
    'font-size:11px;color:#fff;',
    'box-shadow:0 2px 8px rgba(0,0,0,.25);',
    'opacity:.85;transition:opacity .15s;pointer-events:none;}',
    '.sbf-pp-av-hint{font-family:"JetBrains Mono",monospace;font-size:10px;',
    'color:var(--muted,#8A8275);margin-top:8px;letter-spacing:.4px;}',

    // Карточка уровня
    '.sbf-pp-lvl{display:flex;align-items:center;gap:12px;',
    'background:rgba(201,162,39,.07);',
    'border:1px solid rgba(201,162,39,.22);',
    'border-radius:12px;padding:13px 15px;margin-bottom:20px;}',
    '.sbf-pp-lvl-n{font-family:"JetBrains Mono",monospace;',
    'font-size:30px;font-weight:700;color:var(--gold,#C9A227);line-height:1;',
    'min-width:36px;text-align:center;}',
    '.sbf-pp-lvl-i{flex:1;min-width:0;}',
    '.sbf-pp-lvl-t{font-weight:700;font-size:13px;color:var(--ink,#2B2B33);}',
    '.sbf-pp-xp-row{display:flex;justify-content:space-between;margin-top:6px;}',
    '.sbf-pp-xp-lbl{font-family:"JetBrains Mono",monospace;font-size:10px;',
    'color:var(--muted,#8A8275);}',
    '.sbf-pp-xp-bar{height:5px;background:var(--line,#E7DFCF);',
    'border-radius:3px;margin-top:6px;overflow:hidden;}',
    '.sbf-pp-xp-fill{height:100%;',
    'background:linear-gradient(90deg,var(--gold,#C9A227),#E6C257);',
    'border-radius:3px;transition:width .5s ease;}',

    // Форма
    '.sbf-pp-f{margin-bottom:14px;}',
    '.sbf-pp-f label{display:block;font-family:"JetBrains Mono",monospace;',
    'font-size:10px;letter-spacing:.8px;text-transform:uppercase;',
    'color:var(--muted,#8A8275);margin-bottom:6px;font-weight:600;}',
    '.sbf-pp-f input{width:100%;box-sizing:border-box;padding:10px 12px;',
    'border:1.5px solid var(--line,#E7DFCF);border-radius:8px;',
    'font-family:Montserrat,sans-serif;font-size:14px;color:var(--ink,#2B2B33);',
    'background:var(--surface,#FCFAF5);transition:border-color .14s;outline:none;}',
    '.sbf-pp-f input:focus{border-color:var(--gold,#C9A227);}',
    '.sbf-pp-f input::placeholder{color:var(--muted,#8A8275);opacity:.55;}',

    // Ватчлист (Layer4 Ф1.3)
    '.sbf-pp-wl{margin-bottom:14px;}',
    '.sbf-pp-wl label{display:block;font-family:"JetBrains Mono",monospace;',
    'font-size:11px;color:var(--muted,#8A8275);margin-bottom:6px;letter-spacing:.2px;}',
    '.sbf-pp-wl-summary{display:flex;align-items:center;gap:8px;cursor:pointer;',
    'font-size:13px;color:var(--ink,#2B2B33);padding:8px 0;}',
    '.sbf-pp-wl-summary .sbf-pp-wl-edit-ico{margin-left:auto;color:var(--gold,#C9A227);font-size:13px;}',
    '.sbf-pp-wl-chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;}',
    '.sbf-pp-wl-chip{display:flex;align-items:center;gap:4px;background:var(--grid,#F0E9DA);',
    'border-radius:8px;padding:5px 6px 5px 10px;font-family:"JetBrains Mono",monospace;font-size:12px;}',
    '.sbf-pp-wl-chip button{border:none;background:none;cursor:pointer;color:var(--muted,#8A8275);',
    'font-size:11px;padding:2px 4px;line-height:1;}',
    '.sbf-pp-wl-chip button:hover{color:var(--ink,#2B2B33);}',
    '.sbf-pp-wl-add select{width:100%;box-sizing:border-box;padding:8px 10px;',
    'border:1px solid var(--line,#E7DFCF);border-radius:8px;font-family:"JetBrains Mono",monospace;',
    'font-size:12px;background:#fff;color:var(--ink,#2B2B33);}',
    '.sbf-pp-wl-hint{font-size:10px;color:var(--muted,#8A8275);margin-top:6px;line-height:1.4;}',

    // Кнопка сохранить
    '.sbf-pp-save{width:100%;margin-top:8px;padding:12px;',
    'background:var(--gold,#C9A227);color:#fff;border:none;',
    'border-radius:9px;',
    'font-family:Montserrat,sans-serif;font-size:14px;font-weight:700;',
    'cursor:pointer;transition:background .12s,transform .1s;letter-spacing:.3px;outline:none;}',
    '.sbf-pp-save:hover{background:#B8931F;}',
    '.sbf-pp-save:active{transform:scale(.97);}',
    '.sbf-pp-save.saved{background:var(--up,#2E8B6F)!important;}',

    // Journal quick-links section
    '.sbf-pp-journal{margin-top:22px;border-top:1px solid var(--line,#E7DFCF);padding-top:18px;}',
    '.sbf-pp-journal-title{font-size:10px;font-weight:700;letter-spacing:.8px;',
    'text-transform:uppercase;color:var(--muted,#8A8275);margin-bottom:12px;}',
    '.sbf-pp-jlinks{display:grid;grid-template-columns:1fr 1fr;gap:8px;}',
    '.sbf-pp-jlink{display:flex;flex-direction:column;align-items:center;gap:4px;',
    'padding:10px 8px;border:1px solid var(--line,#E7DFCF);border-radius:9px;',
    'text-decoration:none;color:var(--ink,#2B2B33);',
    'font-family:Montserrat,sans-serif;font-size:11px;font-weight:600;',
    'transition:background .12s,border-color .12s;cursor:pointer;background:transparent;}',
    '.sbf-pp-jlink:hover{background:rgba(201,162,39,.08);border-color:var(--gold,#C9A227);',
    'text-decoration:none;color:var(--ink,#2B2B33);}',
    '.sbf-pp-jlink-ico{font-size:20px;line-height:1;}',
    '.sbf-pp-jlink-lbl{font-size:11px;font-weight:600;text-align:center;}',

    // Avatar strip (compact horizontal, outside scroll area)
    '.sbf-pp-av-strip{display:flex;align-items:center;gap:12px;padding:12px 20px;',
    'border-bottom:1px solid var(--line,#E7DFCF);flex-shrink:0;',
    'background:rgba(201,162,39,.04);}',
    '.sbf-pp-av-strip .sbf-pp-av-btn{position:relative;cursor:pointer;border:none;',
    'background:none;padding:0;flex-shrink:0;}',
    '.sbf-pp-av-strip .sbf-pp-av-btn:hover .sbf-pp-av-ed{opacity:1;}',
    '.sbf-pp-av-strip .sbf-pp-av-lg{width:42px;height:42px;font-size:17px;border-width:2px;}',
    '.sbf-pp-av-strip-info{flex:1;min-width:0;}',
    '.sbf-pp-av-strip-name{font-weight:700;font-size:14px;color:var(--ink,#2B2B33);',
    'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
    '.sbf-pp-av-strip-sub{font-family:"JetBrains Mono",monospace;font-size:10px;',
    'color:var(--muted,#8A8275);margin-top:2px;letter-spacing:.2px;}',
    '.sbf-pp-xp-mini{height:3px;background:var(--line,#E7DFCF);',
    'border-radius:2px;margin-top:6px;overflow:hidden;}',
    '.sbf-pp-xp-mini-fill{height:100%;background:linear-gradient(90deg,',
    'var(--gold,#C9A227),#E6C257);border-radius:2px;transition:width .5s ease;}',

    // Tab bar
    '.sbf-pp-tabs{display:flex;border-bottom:1px solid var(--line,#E7DFCF);flex-shrink:0;}',
    '.sbf-pp-tab{flex:1;padding:10px 2px 9px;border:none;background:none;',
    'font-family:Montserrat,system-ui,sans-serif;font-size:11px;font-weight:600;',
    'letter-spacing:.2px;color:var(--muted,#8A8275);cursor:pointer;',
    'border-bottom:2px solid transparent;margin-bottom:-1px;',
    'transition:color .12s,border-color .12s;outline:none;',
    '-webkit-tap-highlight-color:transparent;}',
    '.sbf-pp-tab.active{color:var(--gold,#C9A227);border-bottom-color:var(--gold,#C9A227);}',
    '.sbf-pp-tab:hover{color:var(--ink,#2B2B33);}',

    // Tab panes
    '.sbf-pp-pane{display:none;}',
    '.sbf-pp-pane.active{display:block;}',

    // First-run hero card
    '.sbf-pp-hero{background:rgba(201,162,39,.06);border:1px solid rgba(201,162,39,.22);',
    'border-radius:10px;padding:16px;margin-bottom:16px;text-align:center;}',
    '.sbf-pp-hero-ico{font-size:32px;margin-bottom:8px;line-height:1;display:block;}',
    '.sbf-pp-hero-t{font-size:14px;font-weight:700;color:var(--ink,#2B2B33);margin-bottom:6px;}',
    '.sbf-pp-hero-s{font-size:12px;color:var(--muted,#8A8275);line-height:1.55;margin-bottom:14px;}',
    '.sbf-pp-hero-btn{display:inline-block;padding:9px 18px;background:var(--gold,#C9A227);',
    'color:#fff;border-radius:8px;font-size:13px;font-weight:700;',
    'text-decoration:none;cursor:pointer;font-family:Montserrat,sans-serif;}',
    '.sbf-pp-hero-btn:hover{opacity:.9;text-decoration:none;color:#fff;}',

    // Mini stats row (shown after first trade)
    '.sbf-pp-stats-row{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px;}',
    '.sbf-pp-mini-stat{background:var(--surface,#FCFAF5);border:1px solid var(--line,#E7DFCF);',
    'border-radius:8px;padding:10px 12px;text-align:center;}',
    '.sbf-pp-mini-stat-val{font-family:"JetBrains Mono",monospace;font-size:20px;',
    'font-weight:700;color:var(--ink,#2B2B33);}',
    '.sbf-pp-mini-stat-lbl{font-size:10px;color:var(--muted,#8A8275);',
    'margin-top:3px;text-transform:uppercase;letter-spacing:.4px;}',

    // Tooltip (?) pattern
    '.sbf-tip{position:relative;cursor:help;display:inline-flex;align-items:center;gap:2px;}',
    '.sbf-tip-ico{display:inline-flex;align-items:center;justify-content:center;',
    'width:13px;height:13px;border-radius:50%;background:var(--line,#E7DFCF);',
    'color:var(--muted,#8A8275);font-size:8px;font-weight:700;',
    'font-family:"JetBrains Mono",monospace;flex-shrink:0;line-height:1;}',
    '.sbf-tip:hover .sbf-tip-ico{background:var(--gold,#C9A227);color:#fff;}',
    '.sbf-tip::after{content:attr(data-tip);position:absolute;',
    'bottom:calc(100% + 7px);left:50%;transform:translateX(-50%);',
    'width:max-content;max-width:200px;white-space:normal;',
    'background:var(--ink,#2B2B33);color:#fff;',
    'font-size:11px;font-family:Montserrat,system-ui,sans-serif;font-weight:400;',
    'line-height:1.45;padding:7px 10px;border-radius:7px;',
    'box-shadow:0 4px 16px rgba(0,0,0,.2);',
    'opacity:0;pointer-events:none;transition:opacity .15s;z-index:2010;',
    'text-transform:none;letter-spacing:0;}',
    '.sbf-tip::before{content:"";position:absolute;',
    'bottom:calc(100% + 2px);left:50%;transform:translateX(-50%);',
    'border:5px solid transparent;border-top-color:var(--ink,#2B2B33);',
    'opacity:0;pointer-events:none;transition:opacity .15s;z-index:2010;}',
    '.sbf-tip:hover::after,.sbf-tip:hover::before{opacity:1;}',

    // Section dividers inside panes
    '.sbf-pp-sec-hd{font-size:10px;font-weight:700;letter-spacing:.8px;',
    'text-transform:uppercase;color:var(--muted,#8A8275);margin:0 0 10px;}',
    '.sbf-pp-sec-hd:not(:first-child){margin-top:16px;}',
    '.sbf-pp-links{display:grid;grid-template-columns:1fr 1fr;gap:8px;',
    'margin-bottom:4px;overflow:visible;}',

    // Survey promo card (non-intrusive, session-aware)
    '.sbf-pp-survey-promo{background:rgba(201,162,39,.06);',
    'border:1px solid rgba(201,162,39,.28);border-radius:9px;',
    'padding:12px 13px;margin-bottom:14px;}',
    '.sbf-pp-sp-header{display:flex;align-items:center;justify-content:space-between;',
    'margin-bottom:6px;}',
    '.sbf-pp-sp-badge{display:inline-flex;align-items:center;gap:4px;',
    'font-size:11px;font-weight:700;color:var(--gold,#C9A227);',
    'background:rgba(201,162,39,.12);padding:3px 9px;border-radius:10px;}',
    '.sbf-pp-sp-x{width:22px;height:22px;border:none;background:none;',
    'cursor:pointer;color:var(--muted,#8A8275);font-size:12px;',
    'border-radius:50%;display:flex;align-items:center;justify-content:center;',
    'transition:background .12s;outline:none;padding:0;flex-shrink:0;}',
    '.sbf-pp-sp-x:hover{background:rgba(43,43,51,.08);}',
    '.sbf-pp-sp-text{font-size:12px;color:var(--text,#1a1a1a);',
    'line-height:1.45;margin-bottom:10px;}',
    '.sbf-pp-sp-fine{font-size:10px;color:var(--muted,#8A8275);margin-top:3px;}',
    '.sbf-pp-sp-btn{display:inline-block;padding:7px 14px;',
    'background:var(--gold,#C9A227);color:#fff;border-radius:7px;',
    'font-size:12px;font-weight:700;text-decoration:none;',
    'font-family:Montserrat,system-ui,sans-serif;}',
    '.sbf-pp-sp-btn:hover{opacity:.9;text-decoration:none;color:#fff;}'
  ].join('');

  // ── Реестр аватаров на странице ───────────────────────────────────────────────
  var _avEls = []; // [{el, size}]

  function applyAvatar(el, p, size) {
    el.innerHTML = '';
    if (size) {
      el.style.width  = size + 'px';
      el.style.height = size + 'px';
      el.style.fontSize = Math.floor(size * 0.4) + 'px';
    }
    if (p.avatar) {
      var img = document.createElement('img');
      img.src = p.avatar;
      el.style.background = 'var(--paper,#fff)';
      el.appendChild(img);
    } else {
      var cols = pickGrad((p.firstName || '') + (p.lastName || ''));
      el.style.background = 'linear-gradient(135deg,' + cols[0] + ',' + cols[1] + ')';
      el.textContent = getInitials(p);
    }
  }

  function refreshAllAvatars(p) {
    _avEls.forEach(function (info) { applyAvatar(info.el, p, info.size); });
    refreshLargeAvatar(p);
  }

  // ── Панель ────────────────────────────────────────────────────────────────────
  var overlay, panel, fileInput;
  var _built = false;

  function buildPanel() {
    _built = true;

    overlay = document.createElement('div');
    overlay.className = 'sbf-pp-ov';
    overlay.addEventListener('click', closePanel);

    panel = document.createElement('div');
    panel.className = 'sbf-pp';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'true');
    panel.setAttribute('aria-label', t('profile.aria_my_profile', 'Мой профиль'));
    panel.addEventListener('click', function (e) { e.stopPropagation(); });

    panel.innerHTML = [
      // Drag handle + header
      '<div class="sbf-pp-drag"></div>',
      '<div class="sbf-pp-hd">',
      '  <h3 data-i18n="profile.panel_title">' + t('profile.panel_title', 'Профиль') + '</h3>',
      '  <button class="sbf-pp-x" id="sbfPpX" data-i18n-aria="profile.aria_close" aria-label="' + t('profile.aria_close', 'Закрыть') + '">✕</button>',
      '</div>',

      // Avatar strip (compact, outside scroll)
      '<div class="sbf-pp-av-strip">',
      '  <button class="sbf-pp-av-btn" id="sbfPpAvBtn" data-i18n-aria="profile.aria_change_photo" aria-label="' + t('profile.aria_change_photo', 'Изменить фото') + '">',
      '    <div class="sbf-pp-av-lg" id="sbfPpAvLg"></div>',
      '    <div class="sbf-pp-av-ed">✎</div>',
      '  </button>',
      '  <div class="sbf-pp-av-strip-info">',
      '    <div class="sbf-pp-av-strip-name" id="sbfPpName">—</div>',
      '    <div class="sbf-pp-av-strip-sub" id="sbfPpStripSub">Уровень 1 · Новичок</div>',
      '    <div class="sbf-pp-xp-mini"><div class="sbf-pp-xp-mini-fill" id="sbfPpXMini" style="width:0%"></div></div>',
      '  </div>',
      '</div>',

      // Tab bar
      '<div class="sbf-pp-tabs">',
      '  <button class="sbf-pp-tab active" data-tab="Overview" data-i18n="profile.tab_overview">' + t('profile.tab_overview', 'Обзор') + '</button>',
      '  <button class="sbf-pp-tab" data-tab="Diary" data-i18n="profile.tab_diary">' + t('profile.tab_diary', 'Дневник') + '</button>',
      '  <button class="sbf-pp-tab" data-tab="Progress" data-i18n="profile.tab_progress">' + t('profile.tab_progress', 'Прогресс') + '</button>',
      '  <button class="sbf-pp-tab" data-tab="Account" data-i18n="profile.tab_account">' + t('profile.tab_account', 'Аккаунт') + '</button>',
      '</div>',

      // Scrollable body
      '<div class="sbf-pp-body">',

      // ── Tab: Обзор ──────────────────────────────────────────────────────────
      '<div class="sbf-pp-pane active" id="sbfTabOverview">',

      // Survey promo (hidden after completion or too many dismissals)
      '  <div class="sbf-pp-survey-promo" id="sbfSurveyPromo" style="display:none">',
      '    <div class="sbf-pp-sp-header">',
      '      <span class="sbf-pp-sp-badge" data-i18n="profile.survey_badge">' + t('profile.survey_badge', '🎁 PRO · 30 дней') + '</span>',
      '      <button class="sbf-pp-sp-x" id="sbfSurveyDismiss" data-i18n-aria="profile.aria_close" aria-label="' + t('profile.aria_close', 'Закрыть') + '">✕</button>',
      '    </div>',
      '    <div class="sbf-pp-sp-text" data-i18n="profile.survey_promo_text">',
      '      ' + t('profile.survey_promo_text', 'Пройди опрос трейдера — получи <b>30 дней PRO бесплатно</b>.'),
      '      <div class="sbf-pp-sp-fine" data-i18n="profile.survey_promo_fine">' + t('profile.survey_promo_fine', 'Только за полное прохождение. Без автосписания.') + '</div>',
      '    </div>',
      '    <a href="/survey.html" class="sbf-pp-sp-btn" data-i18n="profile.survey_promo_button">' + t('profile.survey_promo_button', 'Пройти опросник →') + '</a>',
      '  </div>',

      // First-run hero (hidden when trades exist)
      '  <div class="sbf-pp-hero" id="sbfHero">',
      '    <span class="sbf-pp-hero-ico">📓</span>',
      '    <div class="sbf-pp-hero-t" data-i18n="profile.hero_title">' + t('profile.hero_title', 'Начни вести журнал') + '</div>',
      '    <div class="sbf-pp-hero-s"><span data-i18n="profile.hero_text_p1">' + t('profile.hero_text_p1', 'Внеси первую сделку — и сразу увидишь') + '</span>',
      '      <span class="sbf-tip" data-tip="' + t('profile.tip_r_multiple', 'Во сколько прибыль больше риска. +2R = заработал вдвое больше, чем рисковал') + '"><span data-i18n="profile.tip_r_multiple_label">' + t('profile.tip_r_multiple_label', 'R-кратное') + '</span><span class="sbf-tip-ico">?</span></span>,',
      '      <span class="sbf-tip" data-tip="' + t('profile.tip_discipline_full', '% соблюдения ВАШИХ правил — стоп, риск, план. Это не прибыль.') + '"><span data-i18n="profile.hero_discipline_label">' + t('profile.hero_discipline_label', 'дисциплину') + '</span><span class="sbf-tip-ico">?</span></span>',
      '      <span data-i18n="profile.hero_text_p2">' + t('profile.hero_text_p2', 'и аналитику на реальных данных.') + '</span>',
      '    </div>',
      '    <a href="/journal.html#trades" class="sbf-pp-hero-btn" data-i18n="profile.hero_button">' + t('profile.hero_button', 'Добавить сделку →') + '</a>',
      '  </div>',

      // Mini stats (shown after first trade)
      '  <div id="sbfPpStatsCard" style="display:none" class="sbf-pp-stats-row">',
      '    <div class="sbf-pp-mini-stat">',
      '      <div class="sbf-pp-mini-stat-val" id="sbfPpTradeVal">0</div>',
      '      <div class="sbf-pp-mini-stat-lbl" data-i18n="profile.stat_trades_label">' + t('profile.stat_trades_label', 'сделок') + '</div>',
      '    </div>',
      '    <div class="sbf-pp-mini-stat">',
      '      <div class="sbf-pp-mini-stat-val" id="sbfPpDiscVal">—</div>',
      '      <div class="sbf-pp-mini-stat-lbl">',
      '        <span class="sbf-tip" data-tip="' + t('profile.tip_discipline_short', '% соблюдения ВАШИХ правил — стоп, риск, план') + '"><span data-i18n="profile.stat_discipline_label">' + t('profile.stat_discipline_label', 'дисциплина') + '</span><span class="sbf-tip-ico">?</span></span>',
      '      </div>',
      '    </div>',
      '  </div>',

      // Level card
      '  <div class="sbf-pp-lvl">',
      '    <div class="sbf-pp-lvl-n" id="sbfPpLn">1</div>',
      '    <div class="sbf-pp-lvl-i">',
      '      <div class="sbf-pp-lvl-t" id="sbfPpLt">Новичок</div>',
      '      <div class="sbf-pp-xp-row">',
      '        <span class="sbf-pp-xp-lbl">',
      '          <span class="sbf-tip" data-tip="' + t('profile.tip_xp', 'Опыт за полезные действия: уроки, дневник, дисциплина, серии') + '">',
      '            XP<span class="sbf-tip-ico">?</span>',
      '          </span>',
      '        </span>',
      '        <span class="sbf-pp-xp-lbl" id="sbfPpXp">0%</span>',
      '      </div>',
      '      <div class="sbf-pp-xp-bar"><div class="sbf-pp-xp-fill" id="sbfPpXf" style="width:0%"></div></div>',
      '      <div class="sbf-pp-xp-row" style="margin-top:4px">',
      '        <span class="sbf-pp-xp-lbl" id="sbfPpXl" style="font-size:9px">0 XP</span>',
      '      </div>',
      '    </div>',
      '  </div>',

      // Name edit
      '  <div class="sbf-pp-f"><label for="sbfPpFn" data-i18n="profile.field_first_name">' + t('profile.field_first_name', 'Имя') + '</label>',
      '    <input type="text" id="sbfPpFn" data-i18n-ph="profile.placeholder_first_name" placeholder="' + t('profile.placeholder_first_name', 'Введите имя') + '" autocomplete="given-name"></div>',
      '  <div class="sbf-pp-f"><label for="sbfPpLa" data-i18n="profile.field_last_name">' + t('profile.field_last_name', 'Фамилия') + '</label>',
      '    <input type="text" id="sbfPpLa" data-i18n-ph="profile.placeholder_last_name" placeholder="' + t('profile.placeholder_last_name', 'Введите фамилию') + '" autocomplete="family-name"></div>',
      // Ватчлист (SBF_Charts_Layer4_Spec, Фаза 1.3) — только для залогиненных,
      // скрыт для анонима (сама панель профиля доступна и гостю — локальный
      // геймификационный профиль, см. load()/save() выше; ватчлист же —
      // серверная, auth-only фича, здесь читаем window.SBF.user, не local `p`).
      '  <div class="sbf-pp-wl" id="sbfPpWl" style="display:none">',
      '    <label data-i18n="profile.watchlist_label">' + t('profile.watchlist_label', 'Мои инструменты') + '</label>',
      '    <div class="sbf-pp-wl-summary" id="sbfPpWlSummary"></div>',
      '    <div class="sbf-pp-wl-editor" id="sbfPpWlEditor" style="display:none">',
      '      <div class="sbf-pp-wl-chips" id="sbfPpWlChips"></div>',
      '      <div class="sbf-pp-wl-add">',
      '        <select id="sbfPpWlAdd"><option value="" data-i18n="profile.watchlist_add_placeholder">' + t('profile.watchlist_add_placeholder', '+ добавить инструмент') + '</option></select>',
      '      </div>',
      '      <div class="sbf-pp-wl-hint" id="sbfPpWlHint" data-i18n="profile.watchlist_hint">' + t('profile.watchlist_hint', 'До 10 инструментов. Стрелки — порядок (первый попадёт в шапку и график по умолчанию).') + '</div>',
      '    </div>',
      '  </div>',

      '  <button class="sbf-pp-save" id="sbfPpSv" data-i18n="profile.save_button">' + t('profile.save_button', 'Сохранить') + '</button>',
      '</div>',

      // ── Tab: Дневник ────────────────────────────────────────────────────────
      '<div class="sbf-pp-pane" id="sbfTabDiary">',
      '  <div class="sbf-pp-sec-hd" data-i18n="profile.diary_section">' + t('profile.diary_section', 'Дневник') + '</div>',
      '  <div class="sbf-pp-links">',
      '    <a href="/journal.html#trades" class="sbf-pp-jlink">',
      '      <span class="sbf-pp-jlink-ico">📋</span>',
      '      <span class="sbf-pp-jlink-lbl" data-i18n="profile.link_trades">' + t('profile.link_trades', 'Сделки') + '</span></a>',
      '    <a href="/journal.html#brief" class="sbf-pp-jlink">',
      '      <span class="sbf-pp-jlink-ico">☀️</span>',
      '      <span class="sbf-pp-jlink-lbl" data-i18n="profile.link_your_day">' + t('profile.link_your_day', 'Твой день') + '</span></a>',
      '    <a href="/journal.html#checklist" class="sbf-pp-jlink">',
      '      <span class="sbf-pp-jlink-ico">✅</span>',
      '      <span class="sbf-pp-jlink-lbl">',
      '        <span class="sbf-tip" data-tip="' + t('profile.tip_ritual', 'Чек-лист перед входом в сделку — ваши правила в одном месте') + '">',
      '          <span data-i18n="profile.link_ritual">' + t('profile.link_ritual', 'Ритуал') + '</span><span class="sbf-tip-ico">?</span></span></span></a>',
      '    <a href="/journal.html#discipline" class="sbf-pp-jlink">',
      '      <span class="sbf-pp-jlink-ico">🎯</span>',
      '      <span class="sbf-pp-jlink-lbl">',
      '        <span class="sbf-tip" data-tip="' + t('profile.tip_discipline_full', '% соблюдения ВАШИХ правил — стоп, риск, план. Это не прибыль.') + '">',
      '          <span data-i18n="profile.link_discipline">' + t('profile.link_discipline', 'Дисциплина') + '</span><span class="sbf-tip-ico">?</span></span></span></a>',
      '  </div>',
      '  <div class="sbf-pp-sec-hd" data-i18n="profile.analytics_section">' + t('profile.analytics_section', 'Аналитика') + '</div>',
      '  <div class="sbf-pp-links">',
      '    <a href="/journal.html#setups" class="sbf-pp-jlink">',
      '      <span class="sbf-pp-jlink-ico">📐</span>',
      '      <span class="sbf-pp-jlink-lbl">',
      '        <span class="sbf-tip" data-tip="' + t('profile.tip_playbook', 'Ваша коллекция сетапов и как они отработали — ваш личный плейбук') + '">',
      '          <span data-i18n="profile.link_playbook">' + t('profile.link_playbook', 'Плейбук') + '</span><span class="sbf-tip-ico">?</span></span></span></a>',
      '    <a href="/journal.html#alerts" class="sbf-pp-jlink">',
      '      <span class="sbf-pp-jlink-ico">🔔</span>',
      '      <span class="sbf-pp-jlink-lbl" data-i18n="profile.link_alerts">' + t('profile.link_alerts', 'Алерты') + '</span></a>',
      '  </div>',
      '</div>',

      // ── Tab: Прогресс ───────────────────────────────────────────────────────
      '<div class="sbf-pp-pane" id="sbfTabProgress">',
      '  <div class="sbf-pp-sec-hd" data-i18n="profile.development_section">' + t('profile.development_section', 'Развитие') + '</div>',
      '  <div class="sbf-pp-links">',
      '    <a href="/journal.html#gamification" class="sbf-pp-jlink">',
      '      <span class="sbf-pp-jlink-ico">🎮</span>',
      '      <span class="sbf-pp-jlink-lbl">',
      '        <span class="sbf-tip" data-tip="' + t('profile.tip_xp_level', 'Опыт за полезные действия: уроки, дневник, дисциплина') + '">',
      '          <span data-i18n="profile.link_xp_level">' + t('profile.link_xp_level', 'XP и уровень') + '</span><span class="sbf-tip-ico">?</span></span></span></a>',
      '    <a href="/edu/" class="sbf-pp-jlink">',
      '      <span class="sbf-pp-jlink-ico">📚</span>',
      '      <span class="sbf-pp-jlink-lbl" data-i18n="profile.link_education">' + t('profile.link_education', 'Обучение') + '</span></a>',
      '    <a href="/journal.html#goals" class="sbf-pp-jlink">',
      '      <span class="sbf-pp-jlink-ico">🏆</span>',
      '      <span class="sbf-pp-jlink-lbl" data-i18n="profile.link_goals">' + t('profile.link_goals', 'Цели') + '</span></a>',
      '    <a href="/journal.html#gamification" class="sbf-pp-jlink">',
      '      <span class="sbf-pp-jlink-ico">🃏</span>',
      '      <span class="sbf-pp-jlink-lbl">',
      '        <span class="sbf-tip" data-tip="' + t('profile.tip_flashcards', 'Карточки для повторения терминов — алгоритм SM-2 подбирает интервалы') + '">',
      '          <span data-i18n="profile.link_flashcards">' + t('profile.link_flashcards', 'Флешкарты') + '</span><span class="sbf-tip-ico">?</span></span></span></a>',
      '  </div>',
      '  <div class="sbf-pp-sec-hd" data-i18n="profile.streaks_badges_section">' + t('profile.streaks_badges_section', 'Серии и значки') + '</div>',
      '  <div class="sbf-pp-links">',
      '    <a href="/journal.html#gamification" class="sbf-pp-jlink">',
      '      <span class="sbf-pp-jlink-ico">🔥</span>',
      '      <span class="sbf-pp-jlink-lbl">',
      '        <span class="sbf-tip" data-tip="' + t('profile.tip_streak', 'Сколько дней подряд вы держите привычку вести дневник') + '">',
      '          <span data-i18n="profile.link_streak">' + t('profile.link_streak', 'Стрик') + '</span><span class="sbf-tip-ico">?</span></span></span></a>',
      '    <a href="/journal.html#gamification" class="sbf-pp-jlink">',
      '      <span class="sbf-pp-jlink-ico">🏅</span>',
      '      <span class="sbf-pp-jlink-lbl" data-i18n="profile.link_badges">' + t('profile.link_badges', 'Значки') + '</span></a>',
      '  </div>',
      '</div>',

      // ── Tab: Аккаунт ────────────────────────────────────────────────────────
      '<div class="sbf-pp-pane" id="sbfTabAccount">',
      '  <div class="sbf-pp-sec-hd" data-i18n="profile.subscription_section">' + t('profile.subscription_section', 'Подписка и услуги') + '</div>',
      '  <div class="sbf-pp-links">',
      '    <a href="/journal.html#account" class="sbf-pp-jlink">',
      '      <span class="sbf-pp-jlink-ico">⭐</span>',
      '      <span class="sbf-pp-jlink-lbl" data-i18n="profile.link_subscription">' + t('profile.link_subscription', 'Подписка') + '</span></a>',
      '    <a href="/journal.html#account" class="sbf-pp-jlink">',
      '      <span class="sbf-pp-jlink-ico">🤝</span>',
      '      <span class="sbf-pp-jlink-lbl" data-i18n="profile.link_referral">' + t('profile.link_referral', 'Реферал') + '</span></a>',
      '    <a href="/journal.html#account" class="sbf-pp-jlink">',
      '      <span class="sbf-pp-jlink-ico">🏦</span>',
      '      <span class="sbf-pp-jlink-lbl" data-i18n="profile.link_brokers">' + t('profile.link_brokers', 'Брокеры') + '</span></a>',
      '    <a href="/register.html?retake=1" class="sbf-pp-jlink">',
      '      <span class="sbf-pp-jlink-ico">📋</span>',
      '      <span class="sbf-pp-jlink-lbl" data-i18n="profile.link_survey">' + t('profile.link_survey', 'Опросник') + '</span></a>',
      '  </div>',
      '  <div class="sbf-pp-sec-hd" data-i18n="profile.data_privacy_section">' + t('profile.data_privacy_section', 'Данные и приватность') + '</div>',
      '  <div class="sbf-pp-links">',
      '    <a href="/journal.html#account" class="sbf-pp-jlink">',
      '      <span class="sbf-pp-jlink-ico">📤</span>',
      '      <span class="sbf-pp-jlink-lbl" data-i18n="profile.link_export">' + t('profile.link_export', 'Экспорт') + '</span></a>',
      '    <a href="/journal.html#account" class="sbf-pp-jlink">',
      '      <span class="sbf-pp-jlink-ico">🗑</span>',
      '      <span class="sbf-pp-jlink-lbl" data-i18n="profile.link_delete">' + t('profile.link_delete', 'Удаление') + '</span></a>',
      '  </div>',
      '</div>',

      '</div>' // /sbf-pp-body
    ].join('\n');

    document.body.appendChild(overlay);
    document.body.appendChild(panel);

    fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = 'image/*';
    fileInput.style.cssText = 'position:absolute;opacity:0;pointer-events:none;width:1px;height:1px;';
    document.body.appendChild(fileInput);

    document.getElementById('sbfPpX').addEventListener('click', closePanel);
    document.getElementById('sbfPpAvBtn').addEventListener('click', function () { fileInput.click(); });
    document.getElementById('sbfPpFn').addEventListener('input', onNameInput);
    document.getElementById('sbfPpLa').addEventListener('input', onNameInput);
    document.getElementById('sbfPpSv').addEventListener('click', onSave);
    fileInput.addEventListener('change', onFile);
    document.getElementById('sbfPpWlSummary').addEventListener('click', function () {
      var ed = document.getElementById('sbfPpWlEditor');
      ed.style.display = ed.style.display === 'none' ? '' : 'none';
    });
    document.getElementById('sbfPpWlAdd').addEventListener('change', function () {
      if (!this.value) return;
      if (_wlSymbols.length >= 10) { this.value = ''; return; }
      _wlSymbols.push(this.value);
      this.value = '';
      renderWlChips(); renderWlSummary(); renderWlAddOptions();
      saveWatchlist();
    });

    // Survey promo dismiss
    var surveyDismiss = document.getElementById('sbfSurveyDismiss');
    if (surveyDismiss) {
      surveyDismiss.addEventListener('click', function (e) {
        e.stopPropagation();
        var promo = document.getElementById('sbfSurveyPromo');
        if (promo) promo.style.display = 'none';
        sessionStorage.setItem('sbfSurveyDismissed', '1');
        var d = parseInt(localStorage.getItem('sbfSurveyDeclines') || '0') + 1;
        localStorage.setItem('sbfSurveyDeclines', String(d));
      });
    }

    // Tab switching
    panel.querySelectorAll('.sbf-pp-tab').forEach(function (tab) {
      tab.addEventListener('click', function () {
        panel.querySelectorAll('.sbf-pp-tab').forEach(function (t) { t.classList.remove('active'); });
        panel.querySelectorAll('.sbf-pp-pane').forEach(function (p) { p.classList.remove('active'); });
        tab.classList.add('active');
        var pane = document.getElementById('sbfTab' + tab.dataset.tab);
        if (pane) pane.classList.add('active');
      });
    });

    // Auto-close when clicking navigation links inside panel
    panel.querySelector('.sbf-pp-body').addEventListener('click', function (e) {
      var a = e.target.closest('a[href]');
      if (a) { setTimeout(closePanel, 80); }
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && panel.classList.contains('open')) closePanel();
    });

    // Панель могла быть построена ДО того как словарь догрузился (гонка,
    // маловероятна т.к. buildPanel вызывается только по клику пользователя) —
    // подстраховываемся так же, как sbf-header.js делает для шапки.
    _i18n.ready.then(function () { _patchI18n(panel); });
  }

  function _checkSurveyPromo() {
    // §5 правила: ≤1 показ/сессия, исчезает после 3 отказов, исчезает после прохождения
    if (sessionStorage.getItem('sbfSurveyDismissed')) return;
    if (parseInt(localStorage.getItem('sbfSurveyDeclines') || '0') >= 3) return;
    if (localStorage.getItem('sbfSurveyDone')) return;
    if (!window.sbfAuth || !sbfAuth.isLoggedIn()) return;
    sbfAuth.fetch('/api/auth/survey-status')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.done) {
          var el = document.getElementById('sbfSurveyPromo');
          if (el) el.style.display = '';
        } else {
          localStorage.setItem('sbfSurveyDone', '1');
        }
      })
      .catch(function () {});
  }

  function _loadPanelStats() {
    fetch('/api/journal/stats')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var n = (d.stats && (d.stats.total_trades | 0)) || 0;
        var hero = document.getElementById('sbfHero');
        var statsCard = document.getElementById('sbfPpStatsCard');
        if (hero)      hero.style.display      = n > 0 ? 'none' : '';
        if (statsCard) statsCard.style.display = n > 0 ? '' : 'none';
        if (n > 0) {
          var tv = document.getElementById('sbfPpTradeVal');
          var dv = document.getElementById('sbfPpDiscVal');
          if (tv) tv.textContent = n;
          if (dv && d.stats.discipline_pct != null)
            dv.textContent = d.stats.discipline_pct.toFixed(0) + '%';
        }
      })
      .catch(function () {});
    _checkSurveyPromo();
  }

  // ── Ватчлист (SBF_Charts_Layer4_Spec, Фаза 1.3) ─────────────────────────
  var _wlSymbols = [];
  var _wlAvailable = null;
  var _wlPinned = null;   // Focus Engine (SPEC_focus_engine.md §6)

  function fillWatchlist() {
    var wrap = document.getElementById('sbfPpWl');
    if (!wrap) return;
    var user = window.SBF && window.SBF.user;
    if (!user) { wrap.style.display = 'none'; return; }
    wrap.style.display = '';
    _wlSymbols = (user.watchlist || []).slice();
    _wlPinned = user.pinned || null;
    renderWlSummary();
    renderWlChips();
    if (_wlAvailable) { renderWlAddOptions(); return; }
    fetch('/api/chart/symbols').then(function (r) { return r.json(); }).then(function (list) {
      _wlAvailable = list;
      renderWlAddOptions();
    }).catch(function () {});
  }

  function renderWlSummary() {
    var el = document.getElementById('sbfPpWlSummary');
    if (!el) return;
    el.innerHTML = '';
    var txt = document.createElement('span');
    txt.textContent = _wlSymbols.length ? _wlSymbols.join(', ') : t('profile.watchlist_empty', 'не выбрано');
    var ico = document.createElement('span');
    ico.className = 'sbf-pp-wl-edit-ico';
    ico.textContent = '✎';
    el.appendChild(txt);
    el.appendChild(ico);
  }

  function renderWlChips() {
    var box = document.getElementById('sbfPpWlChips');
    if (!box) return;
    box.innerHTML = '';
    _wlSymbols.forEach(function (sym, idx) {
      var chip = document.createElement('div');
      chip.className = 'sbf-pp-wl-chip';
      var label = document.createElement('span');
      label.textContent = sym;
      chip.appendChild(label);
      if (idx > 0) {
        var up = document.createElement('button');
        up.type = 'button'; up.textContent = '↑';
        up.setAttribute('aria-label', t('profile.watchlist_move_up', 'Выше'));
        up.addEventListener('click', function () { moveWl(idx, -1); });
        chip.appendChild(up);
      }
      if (idx < _wlSymbols.length - 1) {
        var down = document.createElement('button');
        down.type = 'button'; down.textContent = '↓';
        down.setAttribute('aria-label', t('profile.watchlist_move_down', 'Ниже'));
        down.addEventListener('click', function () { moveWl(idx, 1); });
        chip.appendChild(down);
      }
      var pin = document.createElement('button');
      pin.type = 'button';
      pin.className = 'sbf-pp-wl-pin' + (sym === _wlPinned ? ' on' : '');
      pin.textContent = sym === _wlPinned ? '★' : '☆';
      pin.title = sym === _wlPinned
        ? t('profile.watchlist_unpin', 'Открепить (вернуть авто-выбор фокуса)')
        : t('profile.watchlist_pin', 'Закрепить как фокус дня');
      pin.addEventListener('click', function () { togglePin(sym); });
      chip.appendChild(pin);
      var rm = document.createElement('button');
      rm.type = 'button'; rm.textContent = '×';
      rm.setAttribute('aria-label', t('profile.watchlist_remove', 'Убрать'));
      rm.addEventListener('click', function () { removeWl(idx); });
      chip.appendChild(rm);
      box.appendChild(chip);
    });
  }

  function togglePin(sym) {
    if (!window.sbfAuth || !window.sbfAuth.isLoggedIn()) return;
    var next = sym === _wlPinned ? null : sym;
    window.sbfAuth.fetch('/api/user/watchlist/pin', {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({symbol: next}),
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (!d || !d.ok) return;
      _wlPinned = d.pinned;
      if (window.SBF && window.SBF.user) window.SBF.user.pinned = d.pinned;
      renderWlChips();
    }).catch(function () {});
  }

  function renderWlAddOptions() {
    var sel = document.getElementById('sbfPpWlAdd');
    if (!sel || !_wlAvailable) return;
    sel.innerHTML = '<option value="">' + t('profile.watchlist_add_placeholder', '+ добавить инструмент') + '</option>';
    _wlAvailable.filter(function (s) { return _wlSymbols.indexOf(s) === -1; }).forEach(function (s) {
      var o = document.createElement('option');
      o.value = s; o.textContent = s;
      sel.appendChild(o);
    });
    sel.disabled = _wlSymbols.length >= 10;
  }

  function moveWl(idx, dir) {
    var j = idx + dir;
    if (j < 0 || j >= _wlSymbols.length) return;
    var tmp = _wlSymbols[idx]; _wlSymbols[idx] = _wlSymbols[j]; _wlSymbols[j] = tmp;
    renderWlChips(); renderWlSummary();
    saveWatchlist();
  }

  function removeWl(idx) {
    _wlSymbols.splice(idx, 1);
    renderWlChips(); renderWlSummary(); renderWlAddOptions();
    saveWatchlist();
  }

  function saveWatchlist() {
    if (!window.sbfAuth || !window.sbfAuth.isLoggedIn()) return;
    window.sbfAuth.fetch('/api/user/watchlist', {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({symbols: _wlSymbols}),
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (!d || !d.watchlist) return;
      _wlSymbols = d.watchlist;
      if (window.SBF && window.SBF.user) window.SBF.user.watchlist = d.watchlist;
      renderWlChips(); renderWlSummary(); renderWlAddOptions();
      document.dispatchEvent(new CustomEvent('sbf:user-ready', {detail: window.SBF.user}));
    }).catch(function () {});
  }

  function fillPanel(p) {
    var lvl = calcLevel(p.xp || 0);
    var pct = Math.round(lvl.progress * 100);
    var left = lvl.xpToNext - lvl.xpInLevel;
    var title = lvlTitle(lvl.level);

    var fn = document.getElementById('sbfPpFn');
    var la = document.getElementById('sbfPpLa');
    if (fn) fn.value = p.firstName || '';
    if (la) la.value = p.lastName  || '';

    var n = document.getElementById('sbfPpLn');
    var ltEl = document.getElementById('sbfPpLt');
    var xl = document.getElementById('sbfPpXl');
    var xp = document.getElementById('sbfPpXp');
    var xf = document.getElementById('sbfPpXf');
    if (n)    n.textContent  = lvl.level;
    if (ltEl) ltEl.textContent = title;
    if (xl) xl.textContent = (p.xp || 0) + ' XP · ' + t('profile.xp_to_level_label', 'до ур.') + ' ' + (lvl.level + 1) + ': ' + left + ' XP';
    if (xp) xp.textContent = pct + '%';
    if (xf) xf.style.width = pct + '%';

    // Avatar strip
    var nm  = document.getElementById('sbfPpName');
    var sub = document.getElementById('sbfPpStripSub');
    var xmf = document.getElementById('sbfPpXMini');
    var fullName = ((p.firstName || '') + ' ' + (p.lastName || '')).trim();
    if (nm)  nm.textContent  = fullName || '—';
    if (sub) sub.textContent = t('profile.level_label', 'Уровень') + ' ' + lvl.level + ' · ' + title + ' · ' + (p.xp || 0) + ' XP';
    if (xmf) xmf.style.width = pct + '%';

    refreshLargeAvatar(p);
  }

  function refreshLargeAvatar(p) {
    var lg = document.getElementById('sbfPpAvLg');
    if (!lg) return;
    lg.innerHTML = '';
    if (p.avatar) {
      var img = document.createElement('img');
      img.src = p.avatar;
      lg.style.background = 'var(--paper,#fff)';
      lg.appendChild(img);
    } else {
      var cols = pickGrad((p.firstName || '') + (p.lastName || ''));
      lg.style.background = 'linear-gradient(135deg,' + cols[0] + ',' + cols[1] + ')';
      lg.textContent = getInitials(p);
    }
  }

  function openPanel() {
    if (!_built) buildPanel();
    fillPanel(load());
    fillWatchlist();
    _loadPanelStats();
    overlay.classList.add('open');
    panel.classList.add('open');
    document.body.style.overflow = 'hidden';
    var fn = document.getElementById('sbfPpFn');
    if (fn) setTimeout(function () { fn.focus(); }, 260);
  }

  function closePanel() {
    if (!_built) return;
    overlay.classList.remove('open');
    panel.classList.remove('open');
    document.body.style.overflow = '';
  }

  function onNameInput() {
    var fn = document.getElementById('sbfPpFn');
    var la = document.getElementById('sbfPpLa');
    var fnV = fn ? fn.value : '';
    var laV = la ? la.value : '';
    var tmp = Object.assign({}, load(), { firstName: fnV, lastName: laV });
    refreshLargeAvatar(tmp);
    // обновляем аватары на странице вживую (только инициалы, без avatar-img)
    if (!tmp.avatar) {
      _avEls.forEach(function (info) { applyAvatar(info.el, tmp, info.size); });
    }
  }

  function onSave() {
    var fn = document.getElementById('sbfPpFn');
    var la = document.getElementById('sbfPpLa');
    var p = load();
    p.firstName = (fn ? fn.value : '').trim();
    p.lastName  = (la ? la.value : '').trim();
    save(p);
    refreshAllAvatars(p);
    var btn = document.getElementById('sbfPpSv');
    if (btn) {
      btn.textContent = t('profile.saved_label', '✓ Сохранено');
      btn.classList.add('saved');
      setTimeout(function () { btn.textContent = t('profile.save_button', 'Сохранить'); btn.classList.remove('saved'); }, 1600);
    }
  }

  function onFile() {
    var file = fileInput.files && fileInput.files[0];
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function (e) {
      cropSquare(e.target.result, 400, function (dataUrl) {
        var p = load();
        p.avatar = dataUrl;
        save(p);
        refreshLargeAvatar(p);
        refreshAllAvatars(p);
      });
    };
    reader.readAsDataURL(file);
    fileInput.value = '';
  }

  function cropSquare(src, size, cb) {
    var img = new Image();
    img.onload = function () {
      var c = document.createElement('canvas');
      c.width = c.height = size;
      var ctx = c.getContext('2d');
      var s = Math.min(img.naturalWidth, img.naturalHeight);
      var ox = (img.naturalWidth  - s) / 2;
      var oy = (img.naturalHeight - s) / 2;
      ctx.drawImage(img, ox, oy, s, s, 0, 0, size, size);
      cb(c.toDataURL('image/jpeg', 0.85));
    };
    img.onerror = function () { cb(src); };
    img.src = src;
  }

  // ── Инъекция в страницу ───────────────────────────────────────────────────────
  function makeHeaderAvatar() {
    var btn = document.createElement('button');
    btn.className = 'sbf-av';
    btn.setAttribute('data-i18n-aria', 'profile.profile_label');
    btn.setAttribute('aria-label', t('profile.profile_label', 'Профиль'));
    btn.style.cssText = 'width:34px;height:34px;margin-left:10px;';
    applyAvatar(btn, load(), 34);
    btn.addEventListener('click', openPanel);
    _avEls.push({ el: btn, size: 34 });
    return btn;
  }

  function makeNavAvatar(size) {
    var div = document.createElement('div');
    div.className = 'sbf-av sbf-av-in';
    div.style.cssText = 'width:' + size + 'px;height:' + size + 'px;flex-shrink:0;pointer-events:none;';
    applyAvatar(div, load(), size);
    _avEls.push({ el: div, size: size });
    return div;
  }

  // Без этого анонимный посетитель сайта (не через Telegram Mini App, где
  // сессия уже есть) не имел НИКАКОГО видимого пути залогиниться —
  // /login.html и /register.html существуют и рабочие, но нигде не были
  // связаны из обычной навигации. Аватар в шапке для гостя открывал только
  // локальный гостевой профиль (геймификация), что выглядело как "я уже
  // вошёл", а входа на самом деле не было. Найдено пользователем вживую.
  function makeLoginLink() {
    var a = document.createElement('a');
    a.className = 'sbf-login-link';
    a.href = '/login.html';
    a.setAttribute('data-i18n', 'nav.login');
    a.textContent = t('nav.login', 'Войти');
    return a;
  }

  function injectIntoStandardHeader() {
    var right = document.querySelector('.sbf-right');
    if (!right || right.querySelector('.sbf-av') || right.querySelector('.sbf-login-link')) return false;
    if (window.sbfAuth && window.sbfAuth.isLoggedIn()) {
      right.appendChild(makeHeaderAvatar());
    } else {
      right.appendChild(makeLoginLink());
    }
    return true;
  }

  function injectIntoStandardBottomNav() {
    var p = load();
    var isLoggedIn = !!(window.sbfAuth && sbfAuth.isLoggedIn());
    var bnavs = document.querySelectorAll('.g-bottom-nav');
    bnavs.forEach(function (bnav) {
      if (bnav.querySelector('.sbf-bn-prof')) return;
      var item;
      if (!isLoggedIn) {
        // Анонимный: показываем ссылку «Войти»
        item = document.createElement('a');
        item.href = '/survey';
        item.className = 'sbf-bn-prof g-bn-item';
        item.setAttribute('data-i18n-aria', 'profile.login_label');
        item.setAttribute('aria-label', t('profile.login_label', 'Войти'));
        var ico = document.createElement('span');
        ico.className = 'g-bn-ico';
        ico.textContent = '👤';
        var lbl = document.createElement('span');
        lbl.className = 'g-bn-lbl';
        lbl.setAttribute('data-i18n', 'profile.login_label');
        lbl.textContent = t('profile.login_label', 'Войти');
        item.appendChild(ico);
        item.appendChild(lbl);
      } else {
        item = document.createElement('button');
        item.className = 'sbf-bn-prof';
        item.setAttribute('data-i18n-aria', 'profile.profile_label');
        item.setAttribute('aria-label', t('profile.profile_label', 'Профиль'));
        item.appendChild(makeNavAvatar(26));
        var lbl2 = document.createElement('span');
        lbl2.className = 'g-bn-lbl';
        lbl2.setAttribute('data-i18n', 'profile.profile_label');
        lbl2.textContent = t('profile.profile_label', 'Профиль');
        item.appendChild(lbl2);
        item.addEventListener('click', function (e) {
          e.stopPropagation();
          openPanel();
        });
      }
      var items = bnav.querySelectorAll('.g-bn-item');
      var insertBefore = items.length >= 3 ? items[2] : null;
      if (insertBefore) bnav.insertBefore(item, insertBefore);
      else              bnav.appendChild(item);
    });
  }

  // m.html: верхняя полоса (.app) и нижний навигатор (nav.nav#nav)
  function injectIntoMobileApp() {
    var appBar = document.querySelector('.app');
    if (!appBar || appBar.querySelector('.sbf-av')) return;
    var btn = document.createElement('button');
    btn.className = 'sbf-av';
    btn.setAttribute('data-i18n-aria', 'profile.profile_label');
    btn.setAttribute('aria-label', t('profile.profile_label', 'Профиль'));
    btn.style.cssText = 'width:32px;height:32px;margin-left:8px;flex-shrink:0;';
    applyAvatar(btn, load(), 32);
    btn.addEventListener('click', openPanel);
    _avEls.push({ el: btn, size: 32 });
    appBar.appendChild(btn);
  }

  function injectIntoMobileNav() {
    var nav = document.getElementById('nav');
    if (!nav || nav.querySelector('.sbf-bn-prof')) return;
    var item = document.createElement('button');
    item.className = 'sbf-bn-prof';
    item.setAttribute('data-i18n-aria', 'profile.profile_label');
    item.setAttribute('aria-label', t('profile.profile_label', 'Профиль'));
    // стили m.html nav-кнопок
    item.style.cssText = 'flex:1;border:none;background:none;padding:10px 0 9px;display:flex;flex-direction:column;align-items:center;gap:3px;color:var(--muted);font-family:Montserrat;font-size:10px;font-weight:600;cursor:pointer;';
    item.innerHTML = '';
    var ic = document.createElement('span');
    ic.style.cssText = 'font-size:19px;line-height:1;';
    ic.appendChild(makeNavAvatar(22));
    item.appendChild(ic);
    var lbl = document.createElement('span');
    lbl.setAttribute('data-i18n', 'profile.profile_label');
    lbl.textContent = t('profile.profile_label', 'Профиль');
    item.appendChild(lbl);
    item.addEventListener('click', function (e) {
      e.stopPropagation(); // не передаём в m.js nav-обработчик
      openPanel();
    });
    // Вставляем 3-м (перед Сигналами, то есть истинный центр из 5)
    var btns = nav.querySelectorAll('button');
    var insertBefore = btns.length >= 3 ? btns[2] : null;
    if (insertBefore) nav.insertBefore(item, insertBefore);
    else              nav.appendChild(item);
  }

  // ── Инициализация ─────────────────────────────────────────────────────────────
  function inject() {
    injectIntoStandardHeader();
    injectIntoStandardBottomNav();
    injectIntoMobileApp();
    injectIntoMobileNav();
  }

  function init() {
    var st = document.createElement('style');
    st.textContent = CSS;
    document.head.appendChild(st);

    // Догоняющий патч переводов для узлов, вставленных здесь ДО того как
    // словарь (sbfI18n.ready) успел догрузиться — тот же приём, что и в
    // sbf-header.js. Вызываем ПОСЛЕ фактической инъекции (в т.ч. после
    // возможного poll), чтобы не промахнуться мимо ещё не созданных узлов.
    function afterInject() {
      _i18n.ready.then(function () { _patchI18n(document); });
    }

    // .sbf-right может ещё не существовать если sbf-header.js чуть задержался
    if (!injectIntoStandardHeader()) {
      var tries = 0;
      var poll = setInterval(function () {
        if (injectIntoStandardHeader() || ++tries > 40) {
          clearInterval(poll);
          injectIntoStandardBottomNav();
          afterInject();
        }
      }, 50);
    } else {
      injectIntoStandardBottomNav();
      afterInject();
    }

    injectIntoMobileApp();
    injectIntoMobileNav();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Публичный API (для расширения из других модулей)
  window.SBFProfile = {
    open: openPanel,
    close: closePanel,
    addXp: function (amount) {
      var p = load();
      p.xp = (p.xp || 0) + (amount | 0);
      save(p);
      refreshAllAvatars(p);
    },
    getProfile: load
  };
})();
