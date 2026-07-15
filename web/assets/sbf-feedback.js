/* ============================================================================
   SBF Feedback Widget — кружок обратной связи.
   Состояния: 0=idle, 1=bubble+voice, 2=form, 3=done
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

  var _STATE = 0;
  var _utt   = null;
  var _twTimer = null;
  var _screenshotDataUrl = null;
  var _adminMode = false;

  function bubbleText() {
    return t('feedback.bubble_text',
      'Если вы нашли баг или хотели бы что-то добавить — ' +
      'нажмите на меня ещё раз, сделайте скриншот и допишите комментарий. ' +
      'Информация уйдёт в техподдержку, мы её рассмотрим.');
  }

  // ── CSS ────────────────────────────────────────────────────────────────────
  var css = `
.sbf-fw-btn {
  position: fixed;
  right: 20px;
  bottom: 80px;
  width: 46px;
  height: 46px;
  border-radius: 50%;
  background: var(--gold, #c9a227);
  border: none;
  cursor: pointer;
  z-index: 9000;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 3px 12px rgba(0,0,0,.25);
  transition: transform .15s, box-shadow .15s;
  user-select: none;
  -webkit-tap-highlight-color: transparent;
}
@media (min-width: 761px) {
  .sbf-fw-btn { bottom: 24px; }
}
.sbf-fw-btn:hover { transform: scale(1.08); box-shadow: 0 5px 18px rgba(0,0,0,.32); }
.sbf-fw-btn svg { width: 22px; height: 22px; fill: #fff; pointer-events: none; }

/* Bubble */
.sbf-fw-bubble {
  position: fixed;
  right: 74px;
  bottom: 80px;
  width: min(300px, calc(100vw - 100px));
  background: var(--paper, #fff);
  border: 1px solid var(--line, #e5e2db);
  border-radius: 14px 14px 4px 14px;
  padding: 14px 16px 12px;
  z-index: 8999;
  box-shadow: 0 4px 20px rgba(0,0,0,.14);
  display: none;
  animation: sbf-fw-pop .18s cubic-bezier(.34,1.56,.64,1) both;
}
@media (min-width: 761px) {
  .sbf-fw-bubble { bottom: 24px; }
}
@keyframes sbf-fw-pop {
  from { opacity: 0; transform: scale(.85) translateY(8px); }
  to   { opacity: 1; transform: scale(1) translateY(0); }
}
.sbf-fw-bubble-text {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text, #1a1a1a);
  min-height: 3.5em;
}
.sbf-fw-bubble-skip {
  display: inline-block;
  margin-top: 10px;
  font-size: 11px;
  color: var(--muted, #6b7280);
  cursor: pointer;
  border: none;
  background: none;
  padding: 0;
  text-decoration: underline;
}

/* Form overlay */
.sbf-fw-form-wrap {
  position: fixed;
  inset: 0;
  z-index: 9100;
  display: none;
  align-items: flex-end;
  justify-content: flex-end;
  padding: 0 20px 20px;
  pointer-events: none;
}
@media (min-width: 761px) {
  .sbf-fw-form-wrap { align-items: flex-end; }
}
.sbf-fw-form-wrap.open { display: flex; pointer-events: all; }
.sbf-fw-form {
  background: var(--paper, #fff);
  border: 1px solid var(--line, #e5e2db);
  border-radius: 14px;
  padding: 18px 18px 16px;
  width: min(360px, calc(100vw - 40px));
  box-shadow: 0 8px 40px rgba(0,0,0,.18);
  animation: sbf-fw-pop .2s cubic-bezier(.34,1.56,.64,1) both;
  margin-bottom: 56px;
}
@media (min-width: 761px) {
  .sbf-fw-form { margin-bottom: 80px; }
}
.sbf-fw-form-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.sbf-fw-form-title { font-size: 14px; font-weight: 700; color: var(--text, #1a1a1a); }
.sbf-fw-close-btn {
  width: 26px; height: 26px;
  background: none; border: none;
  cursor: pointer; font-size: 18px;
  color: var(--muted, #6b7280);
  display: flex; align-items: center; justify-content: center;
  border-radius: 50%;
}
.sbf-fw-close-btn:hover { background: var(--soft, #f0ede4); }
.sbf-fw-screenshot-wrap {
  position: relative;
  margin-bottom: 12px;
}
.sbf-fw-screenshot-preview {
  width: 100%; height: 90px;
  object-fit: cover;
  border-radius: 8px;
  border: 1px solid var(--line, #e5e2db);
  display: none;
}
.sbf-fw-screenshot-progress {
  font-size: 11px; color: var(--muted, #6b7280);
  margin-bottom: 6px;
}
.sbf-fw-file-label {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--gold, #c9a227);
  cursor: pointer; text-decoration: underline;
  margin-bottom: 10px;
}
.sbf-fw-file-input { display: none; }
.sbf-fw-kind-row {
  display: flex; gap: 6px; margin-bottom: 10px;
}
.sbf-fw-kind-btn {
  flex: 1; padding: 6px 0; font-size: 12px; font-weight: 600;
  border: 1.5px solid var(--line, #e5e2db);
  border-radius: 6px; background: none; cursor: pointer;
  color: var(--text, #1a1a1a); transition: border-color .12s, background .12s;
}
.sbf-fw-kind-btn.active {
  border-color: var(--gold, #c9a227);
  background: rgba(201,162,39,.08);
  color: var(--gold, #c9a227);
}
.sbf-fw-textarea {
  width: 100%; min-height: 72px; resize: vertical;
  font-size: 13px; padding: 10px 12px;
  background: var(--cream, #faf9f5);
  border: 1px solid var(--line, #e5e2db);
  border-radius: 8px; color: var(--text, #1a1a1a);
  outline: none; font-family: inherit;
  transition: border-color .15s;
}
.sbf-fw-textarea:focus { border-color: var(--gold, #c9a227); }
.sbf-fw-anon-note {
  font-size: 11px; color: var(--muted, #6b7280);
  margin: 6px 0 10px;
}
.sbf-fw-anon-note a { color: var(--gold, #c9a227); }
.sbf-fw-submit-btn {
  width: 100%; padding: 11px 0; border-radius: 8px;
  background: var(--gold, #c9a227); border: none;
  color: #fff; font-size: 14px; font-weight: 600;
  cursor: pointer; transition: opacity .15s;
}
.sbf-fw-submit-btn:hover { opacity: .88; }
.sbf-fw-submit-btn:disabled { opacity: .45; cursor: not-allowed; }
.sbf-fw-done-msg {
  text-align: center; padding: 20px 0;
  font-size: 14px; color: var(--text, #1a1a1a);
}

/* Admin copy-edit */
.sbf-copy-edit-mode [data-copy-id] {
  outline: 2px dashed rgba(201,162,39,.5);
  outline-offset: 2px;
  cursor: text;
  transition: outline .15s;
}
.sbf-copy-edit-mode [data-copy-id]:hover {
  outline-color: var(--gold, #c9a227);
  background: rgba(201,162,39,.06);
}
[data-copy-id][contenteditable="true"] {
  outline: 2px solid var(--gold, #c9a227) !important;
  background: rgba(201,162,39,.08) !important;
  border-radius: 3px;
}
.sbf-fw-admin-bar {
  position: fixed;
  top: 0; left: 0; right: 0;
  height: 32px;
  background: #1a1917;
  color: #f0ede4;
  font-size: 12px;
  display: none;
  align-items: center;
  gap: 12px;
  padding: 0 14px;
  z-index: 99999;
  border-bottom: 1px solid #c9a227;
}
.sbf-fw-admin-bar.visible { display: flex; }
.sbf-fw-admin-bar a { color: #c9a227; text-decoration: none; margin-right: 8px; }
.sbf-fw-admin-bar a:hover { text-decoration: underline; }
.sbf-fw-admin-toggle {
  margin-left: auto;
  display: flex; align-items: center; gap: 6px;
  cursor: pointer; user-select: none;
}
.sbf-fw-admin-toggle input[type=checkbox] { accent-color: #c9a227; }
`;

  function injectCSS() {
    var st = document.createElement('style');
    st.textContent = css;
    document.head.appendChild(st);
  }

  // ── SVG иконка (пузырь речи) ───────────────────────────────────────────────
  var ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">' +
    '<path d="M12 2C6.477 2 2 6.135 2 11.2c0 2.96 1.38 5.6 3.55 7.38L4.5 22l4.07-1.69' +
    'C9.6 20.74 10.78 21 12 21c5.523 0 10-4.135 10-9.2S17.523 2 12 2z"/></svg>';

  // ── DOM ────────────────────────────────────────────────────────────────────
  var _btn, _bubble, _bubbleText, _form, _preview, _textarea, _kindBtns, _submitBtn;
  var _selectedKind = 'other';
  var _adminBar;

  function buildDOM() {
    // Bubble
    _bubble = document.createElement('div');
    _bubble.className = 'sbf-fw-bubble';
    _bubble.innerHTML =
      '<div class="sbf-fw-bubble-text" id="sbf-fw-btext"></div>' +
      '<button class="sbf-fw-bubble-skip" id="sbf-fw-skip" data-i18n="feedback.bubble_skip">' +
        t('feedback.bubble_skip', 'Пропустить → форма') + '</button>';

    // Кнопка-кружок
    _btn = document.createElement('button');
    _btn.className = 'sbf-fw-btn';
    _btn.setAttribute('data-i18n-aria', 'feedback.aria_feedback');
    _btn.setAttribute('aria-label', t('feedback.aria_feedback', 'Обратная связь'));
    _btn.innerHTML = ICON_SVG;

    // Форма
    _form = document.createElement('div');
    _form.className = 'sbf-fw-form-wrap';
    _form.innerHTML =
      '<div class="sbf-fw-form">' +
        '<div class="sbf-fw-form-header">' +
          '<span class="sbf-fw-form-title" data-i18n="feedback.form_title">' + t('feedback.form_title', 'Оставить отзыв') + '</span>' +
          '<button class="sbf-fw-close-btn" id="sbf-fw-close" data-i18n-aria="feedback.aria_close" aria-label="' + t('feedback.aria_close', 'Закрыть') + '">×</button>' +
        '</div>' +
        '<div class="sbf-fw-screenshot-wrap">' +
          '<div class="sbf-fw-screenshot-progress" id="sbf-fw-scprog" data-i18n="feedback.screenshot_capturing">' + t('feedback.screenshot_capturing', 'Захватываем скриншот…') + '</div>' +
          '<img class="sbf-fw-screenshot-preview" id="sbf-fw-preview" alt="">' +
          '<label class="sbf-fw-file-label">' +
            '<input type="file" accept="image/*" class="sbf-fw-file-input" id="sbf-fw-file">' +
            '<span data-i18n="feedback.attach_screenshot">' + t('feedback.attach_screenshot', '📎 Прикрепить свой скриншот') + '</span>' +
          '</label>' +
        '</div>' +
        '<div class="sbf-fw-kind-row" id="sbf-fw-kinds">' +
          '<button class="sbf-fw-kind-btn" data-kind="bug" data-i18n="feedback.kind_bug">' + t('feedback.kind_bug', '🐛 Баг') + '</button>' +
          '<button class="sbf-fw-kind-btn active" data-kind="other" data-i18n="feedback.kind_other">' + t('feedback.kind_other', '💬 Другое') + '</button>' +
          '<button class="sbf-fw-kind-btn" data-kind="idea" data-i18n="feedback.kind_idea">' + t('feedback.kind_idea', '💡 Идея') + '</button>' +
        '</div>' +
        '<textarea class="sbf-fw-textarea" id="sbf-fw-comment" data-i18n-ph="feedback.comment_placeholder" ' +
          'placeholder="' + t('feedback.comment_placeholder', 'Опишите проблему или предложение…') + '" rows="3"></textarea>' +
        '<div class="sbf-fw-anon-note" id="sbf-fw-anon"></div>' +
        '<button class="sbf-fw-submit-btn" id="sbf-fw-send" data-i18n="feedback.submit_button">' + t('feedback.submit_button', 'Отправить') + '</button>' +
      '</div>';

    // Admin bar
    _adminBar = document.createElement('div');
    _adminBar.className = 'sbf-fw-admin-bar';
    _adminBar.id = 'sbf-fw-admin-bar';
    _adminBar.innerHTML =
      '<span data-i18n="feedback.admin_mode_label">' + t('feedback.admin_mode_label', '⚙ Админ-режим') + '</span>' +
      '<a href="/admin.html" data-i18n="feedback.admin_panel_link">' + t('feedback.admin_panel_link', 'Панель') + '</a>' +
      '<label class="sbf-fw-admin-toggle">' +
        '<input type="checkbox" id="sbf-fw-copy-toggle"><span data-i18n="feedback.admin_copy_edit_label">' + t('feedback.admin_copy_edit_label', ' Правка текстов') + '</span>' +
      '</label>';

    document.body.appendChild(_adminBar);
    document.body.appendChild(_bubble);
    document.body.appendChild(_btn);
    document.body.appendChild(_form);

    _patchI18n(_adminBar);
    _patchI18n(_bubble);
    _patchI18n(_btn);
    _patchI18n(_form);

    _bubbleText = document.getElementById('sbf-fw-btext');
    _preview    = document.getElementById('sbf-fw-preview');
    _textarea   = document.getElementById('sbf-fw-comment');
    _submitBtn  = document.getElementById('sbf-fw-send');
    _kindBtns   = document.querySelectorAll('.sbf-fw-kind-btn');

    _btn.addEventListener('click', onCircleClick);
    document.getElementById('sbf-fw-skip').addEventListener('click', function (e) {
      e.stopPropagation();
      stopSpeech();
      openForm();
    });
    document.getElementById('sbf-fw-close').addEventListener('click', closeAll);
    document.getElementById('sbf-fw-send').addEventListener('click', submitFeedback);
    document.getElementById('sbf-fw-file').addEventListener('change', onFileSelect);
    _kindBtns.forEach(function (b) {
      b.addEventListener('click', function () {
        _selectedKind = b.dataset.kind;
        _kindBtns.forEach(function (x) { x.classList.toggle('active', x === b); });
      });
    });
    document.getElementById('sbf-fw-copy-toggle').addEventListener('change', function (e) {
      toggleCopyEdit(e.target.checked);
    });
  }

  // ── State machine ──────────────────────────────────────────────────────────
  function onCircleClick() {
    if (_STATE === 0) {
      _STATE = 1;
      showBubble();
    } else if (_STATE === 1) {
      stopSpeech();
      openForm();
    } else if (_STATE === 2) {
      closeAll();
    }
  }

  function showBubble() {
    _bubble.style.display = 'block';
    _bubbleText.textContent = '';
    speakAndType(bubbleText(), _bubbleText, function () {});
  }

  function openForm() {
    _STATE = 2;
    _bubble.style.display = 'none';
    _form.classList.add('open');
    // Анонимность
    if (!window.sbfAuth || !sbfAuth.isLoggedIn()) {
      document.getElementById('sbf-fw-anon').innerHTML =
        t('feedback.anon_note', 'Вы анонимны (вес 1). <a href="/journal.html">Войдите</a> — голос весит больше.');
    } else {
      document.getElementById('sbf-fw-anon').textContent = '';
    }
    // Захватить скриншот
    doScreenshot();
  }

  function closeAll() {
    _STATE = 0;
    _bubble.style.display = 'none';
    _form.classList.remove('open');
    stopSpeech();
    _screenshotDataUrl = null;
    _preview.style.display = 'none';
    _preview.src = '';
    _textarea.value = '';
    document.getElementById('sbf-fw-scprog').textContent = '';
    document.getElementById('sbf-fw-send').innerHTML = t('feedback.submit_button', 'Отправить');
    _submitBtn.disabled = false;
  }

  // ── Speech + Typewriter ────────────────────────────────────────────────────
  function speakAndType(text, el, onDone) {
    var reduced = window.matchMedia &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) { el.textContent = text; onDone(); return; }

    var synth = window.speechSynthesis;
    if (!synth) { typewriterFallback(text, el, onDone); return; }

    function _doSpeak() {
      var voices = synth.getVoices();
      var ruVoice = voices.find(function (v) { return v.lang.startsWith('ru'); });
      if (!ruVoice && voices.length === 0) {
        typewriterFallback(text, el, onDone);
        return;
      }
      var utt = new SpeechSynthesisUtterance(text);
      utt.lang = ruVoice ? 'ru-RU' : 'en-US';
      if (ruVoice) utt.voice = ruVoice;
      utt.rate = 1.05;

      utt.onboundary = function (e) {
        if (e.name === 'word') {
          el.textContent = text.substring(0, e.charIndex + (e.charLength || 0));
        }
      };
      utt.onend = function () { el.textContent = text; onDone(); _utt = null; };
      utt.onerror = function () { typewriterFallback(text, el, onDone); _utt = null; };

      _utt = utt;
      synth.speak(utt);
    }

    var voices = synth.getVoices();
    if (voices.length > 0) {
      _doSpeak();
    } else {
      synth.onvoiceschanged = function () { synth.onvoiceschanged = null; _doSpeak(); };
      // Фолбэк если onvoiceschanged не срабатывает
      setTimeout(function () {
        if (!_utt && el.textContent === '') typewriterFallback(text, el, onDone);
      }, 600);
    }
  }

  function typewriterFallback(text, el, onDone) {
    var i = 0;
    _twTimer = setInterval(function () {
      el.textContent = text.substring(0, ++i);
      if (i >= text.length) {
        clearInterval(_twTimer);
        _twTimer = null;
        onDone();
      }
    }, 45);
  }

  function stopSpeech() {
    if (_twTimer) { clearInterval(_twTimer); _twTimer = null; }
    if (window.speechSynthesis) { try { window.speechSynthesis.cancel(); } catch (e) {} }
    _utt = null;
    if (_bubbleText) _bubbleText.textContent = bubbleText();
  }

  // ── Screenshot ─────────────────────────────────────────────────────────────
  function loadHtml2Canvas(cb) {
    if (window.html2canvas) { cb(); return; }
    var s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js';
    s.onload = cb;
    s.onerror = function () {
      document.getElementById('sbf-fw-scprog').textContent =
        t('feedback.screenshot_unavailable', 'Скриншот недоступен — прикрепите свой.');
    };
    document.head.appendChild(s);
  }

  function doScreenshot() {
    var prog = document.getElementById('sbf-fw-scprog');
    prog.textContent = t('feedback.screenshot_capturing', 'Захватываем скриншот…');
    loadHtml2Canvas(function () {
      window.html2canvas(document.body, {
        scale: 0.6,
        useCORS: true,
        allowTaint: true,
        logging: false,
        ignoreElements: function (el) {
          return el.classList && (
            el.classList.contains('sbf-fw-form-wrap') ||
            el.classList.contains('sbf-fw-btn') ||
            el.classList.contains('sbf-fw-bubble')
          );
        },
      }).then(function (canvas) {
        canvas.toBlob(function (blob) {
          if (!blob) { prog.textContent = t('feedback.screenshot_failed', 'Не удалось — прикрепите свой.'); return; }
          var reader = new FileReader();
          reader.onload = function (ev) {
            _screenshotDataUrl = ev.target.result;
            _preview.src = _screenshotDataUrl;
            _preview.style.display = 'block';
            prog.textContent = t('feedback.screenshot_ready', 'Скриншот готов');
          };
          reader.readAsDataURL(blob);
        }, 'image/jpeg', 0.65);
      }).catch(function () {
        prog.textContent = t('feedback.screenshot_failed', 'Не удалось — прикрепите свой.');
      });
    });
  }

  function onFileSelect(e) {
    var file = e.target.files && e.target.files[0];
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function (ev) {
      _screenshotDataUrl = ev.target.result;
      _preview.src = _screenshotDataUrl;
      _preview.style.display = 'block';
      document.getElementById('sbf-fw-scprog').textContent = t('feedback.file_attached', 'Файл прикреплён');
    };
    reader.readAsDataURL(file);
  }

  // ── Submit ─────────────────────────────────────────────────────────────────
  function submitFeedback() {
    var comment = (_textarea.value || '').trim();
    if (!comment) {
      _textarea.focus();
      _textarea.style.borderColor = '#dc2626';
      setTimeout(function () { _textarea.style.borderColor = ''; }, 1200);
      return;
    }

    _submitBtn.disabled = true;
    _submitBtn.textContent = t('feedback.submitting', 'Отправляем…');

    var payload = {
      kind: _selectedKind,
      comment: comment,
      page_url: location.pathname + location.search,
      ua: navigator.userAgent.substring(0, 200),
      viewport: window.innerWidth + 'x' + window.innerHeight,
      screenshot_b64: _screenshotDataUrl || null,
    };

    sbfAuth.fetch('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.ok) {
        _STATE = 3;
        var inner = _form.querySelector('.sbf-fw-form');
        inner.innerHTML =
          '<div class="sbf-fw-done-msg">' +
          '<div style="font-size:32px;margin-bottom:8px">✅</div>' +
          '<div style="font-weight:700;margin-bottom:6px">' + t('feedback.submitted_title', 'Отзыв отправлен!') + '</div>' +
          '<div style="font-size:12px;color:var(--muted,#6b7280)">' + t('feedback.submitted_note', 'Мы рассмотрим его в ближайшее время. Спасибо!') + '</div>' +
          '</div>';
        setTimeout(function () { closeAll(); _STATE = 0; }, 2800);
      } else {
        _submitBtn.disabled = false;
        _submitBtn.textContent = t('feedback.submit_button', 'Отправить');
        alert(d.error || t('feedback.err_generic', 'Ошибка отправки'));
      }
    })
    .catch(function (e) {
      _submitBtn.disabled = false;
      _submitBtn.textContent = t('feedback.submit_button', 'Отправить');
      alert(t('feedback.err_prefix', 'Ошибка: ') + e.message);
    });
  }

  // ── Admin copy-edit ────────────────────────────────────────────────────────
  function checkAdminStatus() {
    if (!window.sbfAuth || !sbfAuth.isLoggedIn()) return;
    sbfAuth.fetch('/api/admin/me')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (d && d.is_admin) {
          _adminMode = true;
          _adminBar.classList.add('visible');
          // Сдвинуть контент вниз если admin-bar видна
          document.body.style.paddingTop = (parseInt(document.body.style.paddingTop) || 0) + 32 + 'px';
        }
      })
      .catch(function () {});
  }

  function toggleCopyEdit(on) {
    if (on) {
      document.documentElement.classList.add('sbf-copy-edit-mode');
      attachCopyHandlers();
    } else {
      document.documentElement.classList.remove('sbf-copy-edit-mode');
    }
  }

  function attachCopyHandlers() {
    var els = document.querySelectorAll('[data-copy-id]');
    els.forEach(function (el) {
      if (el._sbfCopyBound) return;
      el._sbfCopyBound = true;
      el.addEventListener('click', function (e) {
        if (!document.documentElement.classList.contains('sbf-copy-edit-mode')) return;
        e.stopPropagation();
        if (el.contentEditable === 'true') return;
        el.contentEditable = 'true';
        el.focus();
        // Select all text
        var range = document.createRange();
        range.selectNodeContents(el);
        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      });
      el.addEventListener('blur', function () {
        if (el.contentEditable !== 'true') return;
        el.contentEditable = 'false';
        saveCopy(el.dataset.copyId, el.textContent);
      });
      el.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          el.blur();
        }
        if (e.key === 'Escape') {
          el.contentEditable = 'false';
        }
      });
    });
  }

  function saveCopy(copyId, text) {
    sbfAuth.fetch('/api/copy/' + encodeURIComponent(copyId), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text, page: location.pathname }),
    })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d.ok) console.warn('[sbf-copy] save failed', d);
    })
    .catch(function () {});
  }

  // ── Init ───────────────────────────────────────────────────────────────────
  function init() {
    if (document.getElementById('sbf-fw-btn-el')) return;
    injectCSS();
    buildDOM();
    _btn.id = 'sbf-fw-btn-el';
    checkAdminStatus();

    // Подгрузить тексты с data-copy-id из site_copy
    loadCopyTexts();
  }

  function loadCopyTexts() {
    // Получить все data-copy-id на странице и заменить текст из БД
    var els = document.querySelectorAll('[data-copy-id]');
    if (!els.length) return;
    var ids = [];
    els.forEach(function (el) { ids.push(el.dataset.copyId); });
    fetch('/api/copy/batch?ids=' + ids.map(encodeURIComponent).join(','))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.items) return;
        d.items.forEach(function (item) {
          document.querySelectorAll('[data-copy-id="' + item.copy_id + '"]').forEach(function (el) {
            if (item.text_current) el.textContent = item.text_current;
          });
        });
      })
      .catch(function () {});
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
