/* ── SBF Glossary — auto-highlight + popup + /m/glossary page ─────────────── */
(function () {
  'use strict';

  var GLOSSARY = null;         // loaded lazily
  var _popup   = null;
  var _overlay = null;

  var GLOSSARY_URL = '/assets/glossary.json';

  // ── Load glossary data ────────────────────────────────────────────────────
  function loadGlossary(cb) {
    if (GLOSSARY) { cb(GLOSSARY); return; }
    fetch(GLOSSARY_URL)
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (data) { GLOSSARY = data; cb(GLOSSARY); })
      .catch(function () { cb([]); });
  }

  // ── Build term → entry index ──────────────────────────────────────────────
  function buildIndex(data) {
    var idx = {}; // lowercase string → entry
    data.forEach(function (entry) {
      idx[entry.term.toLowerCase()] = entry;
      (entry.aliases || []).forEach(function (a) {
        idx[a.toLowerCase()] = entry;
      });
    });
    return idx;
  }

  // Build longest-first sorted list of all terms/aliases for matching
  function buildTermList(idx) {
    return Object.keys(idx).sort(function (a, b) { return b.length - a.length; });
  }

  // ── Highlight a single content block ─────────────────────────────────────
  // Rules:
  // - max 12 highlights per block
  // - only first occurrence of each slug per block
  // - skip inside <a>, <h1..h6>, already-highlighted <span.gl-term>
  function highlightBlock(el, idx, termList) {
    var highlighted = 0;
    var seenSlugs = {};

    function walkNode(node) {
      if (highlighted >= 12) return;
      if (node.nodeType === 1) {
        var tag = node.tagName.toLowerCase();
        if (tag === 'a' || /^h[1-6]$/.test(tag)) return;
        if (node.classList && node.classList.contains('gl-term')) return;
        var children = Array.prototype.slice.call(node.childNodes);
        children.forEach(function (child) { walkNode(child); });
        return;
      }
      if (node.nodeType !== 3) return; // only text nodes
      var text = node.nodeValue;
      if (!text || text.trim().length < 2) return;

      // Find first matching term in this text node
      var match = null;
      var matchStart = -1;
      var matchEntry = null;

      for (var i = 0; i < termList.length; i++) {
        var term = termList[i];
        var entry = idx[term];
        if (seenSlugs[entry.slug]) continue;
        // Word-boundary regex (case-insensitive)
        var re = new RegExp('(?<![а-яёa-z])' + regEscape(term) + '(?![а-яёa-z])', 'i');
        var m = re.exec(text);
        if (m && (matchStart === -1 || m.index < matchStart)) {
          matchStart = m.index;
          match = term;
          matchEntry = entry;
        }
      }

      if (!match || !matchEntry) return;
      seenSlugs[matchEntry.slug] = true;
      highlighted++;

      var before  = text.substring(0, matchStart);
      var matched = text.substring(matchStart, matchStart + match.length);
      var after   = text.substring(matchStart + match.length);

      var frag = document.createDocumentFragment();
      if (before) frag.appendChild(document.createTextNode(before));

      var span = document.createElement('span');
      span.className = 'gl-term';
      span.textContent = matched;
      span.setAttribute('data-slug', matchEntry.slug);
      span.addEventListener('click', function (e) {
        e.stopPropagation();
        showPopup(matchEntry, span);
      });
      frag.appendChild(span);

      // Replace node with fragment + rest as text
      var parent = node.parentNode;
      if (!parent) return;
      parent.insertBefore(frag, node);

      // Process remaining text recursively (after current span)
      if (after) {
        var rest = document.createTextNode(after);
        parent.insertBefore(rest, node);
        walkNode(rest);
      }
      parent.removeChild(node);
    }

    walkNode(el);
  }

  function regEscape(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  // ── Popup ─────────────────────────────────────────────────────────────────
  function ensurePopup() {
    if (_popup) return;

    _overlay = document.createElement('div');
    _overlay.id = 'glOverlay';
    _overlay.style.cssText =
      'display:none;position:fixed;inset:0;z-index:1000;' +
      'background:rgba(43,43,51,.35);touch-action:none;';
    _overlay.addEventListener('click', closePopup);
    document.body.appendChild(_overlay);

    _popup = document.createElement('div');
    _popup.id = 'glPopup';
    _popup.innerHTML =
      '<button id="glClose" style="position:absolute;top:10px;right:12px;' +
        'border:none;background:none;font-size:20px;cursor:pointer;color:var(--muted,#8A8275);' +
        'line-height:1;padding:0">✕</button>' +
      '<div id="glTerm" style="font-weight:700;font-size:15px;margin-bottom:6px"></div>' +
      '<div id="glShort" style="font-size:13px;line-height:1.6;color:var(--ink,#2B2B33)"></div>' +
      '<div id="glEtymWrap" style="margin-top:10px">' +
        '<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;' +
          'color:var(--gold,#C9A227);margin-bottom:3px">Этимология</div>' +
        '<div id="glEtym" style="font-size:12px;line-height:1.5;color:var(--muted,#8A8275);font-style:italic"></div>' +
      '</div>' +
      '<a id="glMore" href="#" style="display:inline-block;margin-top:10px;font-size:12px;' +
        'color:var(--gold,#C9A227);font-weight:600;text-decoration:none">Подробнее в глоссарии →</a>';
    _popup.style.cssText =
      'display:none;position:fixed;z-index:1001;' +
      'background:var(--paper,#fff);border:1px solid var(--line,#E7DFCF);' +
      'border-radius:14px;padding:20px 18px 16px;box-shadow:0 8px 32px rgba(43,43,51,.18);' +
      'max-width:340px;width:calc(100% - 32px);';
    document.body.appendChild(_popup);

    document.getElementById('glClose').addEventListener('click', closePopup);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closePopup();
    });
  }

  function showPopup(entry, anchor) {
    ensurePopup();
    document.getElementById('glTerm').textContent  = entry.term;
    document.getElementById('glShort').textContent = entry.short;
    var etymWrap = document.getElementById('glEtymWrap');
    if (entry.etym) {
      document.getElementById('glEtym').textContent = entry.etym;
      etymWrap.style.display = 'block';
    } else {
      etymWrap.style.display = 'none';
    }
    var moreLink = document.getElementById('glMore');
    moreLink.href = '/m/glossary#' + entry.slug;

    _overlay.style.display = 'block';
    _popup.style.display = 'block';

    // Position: under anchor on desktop, bottom sheet on mobile
    if (window.innerWidth <= 640) {
      // bottom sheet
      _popup.style.bottom = '80px';
      _popup.style.left   = '50%';
      _popup.style.transform = 'translateX(-50%)';
      _popup.style.top = '';
    } else {
      var rect = anchor.getBoundingClientRect();
      var top = rect.bottom + window.scrollY + 6;
      var left = Math.min(rect.left + window.scrollX, window.innerWidth - 360);
      _popup.style.top  = top + 'px';
      _popup.style.left = Math.max(8, left) + 'px';
      _popup.style.bottom = '';
      _popup.style.transform = '';
    }
  }

  function closePopup() {
    if (_popup)   _popup.style.display   = 'none';
    if (_overlay) _overlay.style.display = 'none';
  }

  // ── Inject CSS ─────────────────────────────────────────────────────────────
  function injectCSS() {
    var st = document.createElement('style');
    st.textContent =
      '.gl-term{border-bottom:1.5px dotted var(--gold,#C9A227);cursor:pointer;color:inherit;' +
      'transition:background .12s;border-radius:2px;}' +
      '.gl-term:hover{background:rgba(201,162,39,.12);}';
    document.head.appendChild(st);
  }

  // ── Public: highlight a DOM element (called after content renders) ─────────
  function highlight(el) {
    loadGlossary(function (data) {
      var idx = buildIndex(data);
      var termList = buildTermList(idx);
      var blocks = el ? [el] : document.querySelectorAll('.report, .edu-content, [data-gl]');
      blocks.forEach(function (block) { highlightBlock(block, idx, termList); });
    });
  }

  // ── Glossary page ─────────────────────────────────────────────────────────
  function renderGlossaryPage(container, openSlug) {
    loadGlossary(function (data) {
      // Sort by Cyrillic then Latin
      var sorted = data.slice().sort(function (a, b) {
        return a.term.localeCompare(b.term, 'ru');
      });

      // Group by first letter
      var groups = {};
      sorted.forEach(function (entry) {
        var letter = entry.term[0].toUpperCase();
        if (!groups[letter]) groups[letter] = [];
        groups[letter].push(entry);
      });

      var letters = Object.keys(groups).sort(function (a, b) {
        return a.localeCompare(b, 'ru');
      });

      // Search input
      var searchHtml =
        '<div style="position:sticky;top:64px;z-index:30;background:var(--cream,#FBF6EF);padding:10px 0 6px">' +
        '<input id="glSearch" type="search" placeholder="Поиск термина…"' +
        ' style="width:100%;padding:10px 14px;border:1.5px solid var(--line,#E7DFCF);border-radius:10px;' +
        'font-size:14px;font-family:Montserrat,sans-serif;background:var(--paper,#fff);color:var(--ink,#2B2B33);' +
        'outline:none;box-sizing:border-box">' +
        '</div>';

      // Letter sections
      var sectionsHtml = letters.map(function (letter) {
        var entries = groups[letter].map(function (entry) {
          var open = entry.slug === openSlug;
          return (
            '<div class="gl-card" id="gl-' + entry.slug + '" data-open="' + (open ? '1' : '0') + '" ' +
              'style="border:1px solid var(--line,#E7DFCF);border-radius:10px;' +
              'background:var(--paper,#fff);margin-bottom:6px;overflow:hidden">' +
            '<button class="gl-card-hd" style="width:100%;text-align:left;border:none;background:none;' +
              'padding:13px 14px;cursor:pointer;display:flex;align-items:center;justify-content:space-between;' +
              'font-family:Montserrat,sans-serif;font-size:13px;font-weight:600;color:var(--ink,#2B2B33)">' +
              '<span>' + esc(entry.term) + '</span>' +
              '<span class="gl-card-arrow" style="font-size:10px;color:var(--muted,#8A8275);' +
                'transform:rotate(' + (open ? '180' : '0') + 'deg);transition:transform .2s">' +
                '▼</span>' +
            '</button>' +
            '<div class="gl-card-body" style="display:' + (open ? 'block' : 'none') + ';' +
              'padding:0 14px 14px;font-size:13px;line-height:1.65;color:var(--ink,#2B2B33)">' +
              '<p style="color:var(--muted,#8A8275);font-size:12px;margin:0 0 8px">' + esc(entry.short) + '</p>' +
              '<p style="margin:0 0 10px">' + esc(entry.full) + '</p>' +
              (entry.etym
                ? '<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;' +
                    'color:var(--gold,#C9A227);margin-bottom:3px">Этимология</div>' +
                  '<p style="margin:0 0 10px;font-size:12px;font-style:italic;color:var(--muted,#8A8275)">' +
                    esc(entry.etym) + '</p>'
                : '') +
              (entry.related && entry.related.length
                ? '<div style="font-size:11px;color:var(--muted,#8A8275)">По теме: ' +
                  entry.related.map(function (slug) {
                    return '<a href="#gl-' + slug + '" class="gl-rel" style="color:var(--gold,#C9A227);' +
                      'text-decoration:none;margin-right:6px">' + slug + '</a>';
                  }).join('') + '</div>'
                : '') +
            '</div>' +
            '</div>'
          );
        }).join('');
        return (
          '<div class="gl-section" data-letter="' + letter + '">' +
          '<div style="font-size:11px;font-weight:700;color:var(--muted,#8A8275);letter-spacing:.05em;' +
            'text-transform:uppercase;padding:10px 2px 6px">' + letter + '</div>' +
          entries +
          '</div>'
        );
      }).join('');

      container.innerHTML = searchHtml + '<div id="glSections">' + sectionsHtml + '</div>';

      // Toggle cards
      container.addEventListener('click', function (e) {
        var hd = e.target.closest('.gl-card-hd');
        if (!hd) return;
        var card = hd.closest('.gl-card');
        var body = card.querySelector('.gl-card-body');
        var arrow = hd.querySelector('.gl-card-arrow');
        var isOpen = card.dataset.open === '1';
        body.style.display = isOpen ? 'none' : 'block';
        arrow.style.transform = isOpen ? 'rotate(0deg)' : 'rotate(180deg)';
        card.dataset.open = isOpen ? '0' : '1';
        if (!isOpen) {
          // Scroll into view
          setTimeout(function () {
            card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          }, 80);
        }
      });

      // Rel links: open target card
      container.addEventListener('click', function (e) {
        var rel = e.target.closest('.gl-rel');
        if (!rel) return;
        e.preventDefault();
        var slug = rel.getAttribute('href').replace('#gl-', '');
        var target = document.getElementById('gl-' + slug);
        if (!target) return;
        var body = target.querySelector('.gl-card-body');
        var arrow = target.querySelector('.gl-card-arrow');
        body.style.display = 'block';
        arrow.style.transform = 'rotate(180deg)';
        target.dataset.open = '1';
        setTimeout(function () {
          target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 80);
      });

      // Open from URL hash on load
      if (openSlug) {
        setTimeout(function () {
          var card = document.getElementById('gl-' + openSlug);
          if (card) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 200);
      }

      // Client-side search
      var searchInput = document.getElementById('glSearch');
      if (searchInput) {
        searchInput.addEventListener('input', function () {
          var q = this.value.toLowerCase().trim();
          var sections = container.querySelectorAll('.gl-section');
          sections.forEach(function (sec) {
            var cards = sec.querySelectorAll('.gl-card');
            var anyVisible = false;
            cards.forEach(function (card) {
              var text = (card.textContent || '').toLowerCase();
              var visible = !q || text.indexOf(q) !== -1;
              card.style.display = visible ? 'block' : 'none';
              if (visible) anyVisible = true;
            });
            sec.style.display = anyVisible ? 'block' : 'none';
          });
        });
      }
    });
  }

  function esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  // ── Init ─────────────────────────────────────────────────────────────────
  injectCSS();

  // Expose public API
  window.SBFGlossary = {
    highlight: highlight,
    renderPage: renderGlossaryPage,
    showPopup: showPopup,
    close: closePopup,
  };

  // Auto-highlight on DOM ready if we're on a content page
  function autoHighlight() {
    var el = document.querySelector('.report, [data-gl="1"]');
    if (el) highlight(el);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoHighlight);
  } else {
    autoHighlight();
  }

}());
