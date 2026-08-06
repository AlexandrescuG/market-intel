/* ============================================================================
   SBF Admin Panel JS
   ============================================================================ */
'use strict';

var _userId  = localStorage.getItem('sbf_uid')   || '';
var _clusters = [];
var _selectedClusterId = null;
var _filterStatus = '';
var _currentTab = 'clusters';
var _unassigned = [];
var _selectedUnassigned = new Set();

// ── i18n (см. assets/i18n.js, паттерн — sbf-profile.js) ─────────────────────

function t(key, fallback) {
  return (window.sbfI18n && window.sbfI18n.t) ? window.sbfI18n.t(key, fallback) : (fallback || key);
}

function _patchI18n(root) {
  if ((window.sbfI18n && window.sbfI18n.lang) === 'ru') return;
  var tt = window.sbfI18n ? window.sbfI18n.t : function (k, fb) { return fb || k; };
  (root || document).querySelectorAll('[data-i18n]').forEach(function (el) {
    el.textContent = tt(el.getAttribute('data-i18n'), el.textContent);
  });
  (root || document).querySelectorAll('[data-i18n-placeholder]').forEach(function (el) {
    el.setAttribute('placeholder', tt(el.getAttribute('data-i18n-placeholder'), el.getAttribute('placeholder') || ''));
  });
}

// ── Auth ───────────────────────────────────────────────────────────────────

function doLogin() {
  var email = document.getElementById('loginEmail').value.trim();
  var pwd   = document.getElementById('loginPwd').value;
  var btn   = document.getElementById('loginBtn');
  var err   = document.getElementById('loginErr');
  if (!email || !pwd) { showErr(err, t('admin.fill_all_fields', 'Заполни все поля')); return; }
  btn.disabled = true;
  btn.textContent = t('admin.logging_in', 'Входим…');

  fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: email, password: pwd }),
  })
  .then(function (r) { return r.json(); })
  .then(function (d) {
    if (d.error) { btn.disabled = false; btn.textContent = t('admin.login_button', 'Войти'); showErr(err, d.error); return; }
    sbfAuth.setTokens(d.token, d.refresh_token);
    localStorage.setItem('sbf_uid', d.user_id);
    _userId = d.user_id;
    checkAdmin();
  })
  .catch(function (e) {
    btn.disabled = false;
    btn.textContent = t('admin.login_button', 'Войти');
    showErr(err, t('admin.error_prefix', 'Ошибка: ') + e.message);
  });
}

function checkAdmin() {
  if (!sbfAuth.isLoggedIn()) { showLogin(); return; }
  sbfAuth.fetch('/api/admin/me')
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d.is_admin) { showLogin(t('admin.no_access', 'Нет доступа — не в admin_users')); return; }
      document.getElementById('loginGate').style.display = 'none';
      document.getElementById('app').style.display = 'grid';
      document.getElementById('sideUserName').textContent = d.email || _userId;
      loadClusters();
      loadUnassigned();
    })
    .catch(function () { showLogin(); });
}

function showLogin(msg) {
  document.getElementById('loginGate').style.display = 'flex';
  document.getElementById('app').style.display = 'none';
  if (msg) showErr(document.getElementById('loginErr'), msg);
}

function showErr(el, msg) {
  el.textContent = msg;
  el.style.display = msg ? 'block' : 'none';
}

function ah(obj) {
  // Оставлен как есть (используется в опциях fetch ниже) — просто теперь
  // сам fetch(...) заменён на sbfAuth.fetch(...), который добавляет
  // актуальный токен сам; эти extra-заголовки (Content-Type и т.п.)
  // сливаются с ним же.
  return obj || {};
}

// ── Tabs ──────────────────────────────────────────────────────────────────

function showTab(tab) {
  _currentTab = tab;
  ['clusters', 'unassigned', 'copy'].forEach(function (name) {
    document.getElementById('pane' + capitalize(name)).style.display = name === tab ? 'flex' : 'none';
    var tabEl = document.getElementById('tab' + capitalize(name));
    if (tabEl) tabEl.classList.toggle('active', name === tab);
  });
  if (tab === 'unassigned') loadUnassigned();
  if (tab === 'copy')       loadCopyList();
}

function capitalize(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// ── Clusters ──────────────────────────────────────────────────────────────

function loadClusters() {
  var url = '/api/admin/clusters' + (_filterStatus ? '?status=' + _filterStatus : '');
  sbfAuth.fetch(url, { headers: ah() })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      _clusters = d.clusters || [];
      renderClusterList();
    })
    .catch(function () {});
}

function renderClusterList() {
  var el = document.getElementById('clusterList');
  if (!_clusters.length) {
    el.innerHTML = '<div class="adm-empty">' + t('admin.no_clusters', 'Нет кластеров') + '</div>';
    return;
  }
  el.innerHTML = _clusters.map(function (cl) {
    return '<div class="adm-cluster-item' + (cl.id === _selectedClusterId ? ' selected' : '') + '" onclick="selectCluster(\'' + cl.id + '\')">' +
      '<div class="adm-cluster-title">' + esc(cl.title || t('admin.untitled', '(без названия)')) + '</div>' +
      '<div class="adm-cluster-meta">' +
        '<span class="adm-status-dot ' + (cl.status || 'new') + '"></span>' +
        '<span>' + (cl.item_count || 0) + ' ' + t('admin.requests_suffix', 'заявок') + '</span>' +
        '<span class="adm-weight-badge">⚡ ' + (cl.total_weight || 0) + '</span>' +
        '<span style="margin-left:auto;font-size:10px">' + fmtDate(cl.updated_ts) + '</span>' +
      '</div>' +
    '</div>';
  }).join('');
}

function selectCluster(id) {
  _selectedClusterId = id;
  renderClusterList();
  loadClusterDetail(id);
}

function loadClusterDetail(id) {
  var cl = _clusters.find(function (c) { return c.id === id; });
  if (!cl) return;
  var detail = document.getElementById('clusterDetail');
  detail.innerHTML = '<div style="padding:16px 20px;border-bottom:1px solid var(--line);">' +
    '<div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">' +
      '<h2 style="font-size:15px;font-weight:700;flex:1">' + esc(cl.title || t('admin.untitled', '(без названия)')) + '</h2>' +
      '<button class="adm-action-btn" onclick="openRename(\'' + id + '\',\'' + escQ(cl.title) + '\')">' + t('admin.rename_action', '✏ Переименовать') + '</button>' +
      '<button class="adm-action-btn" onclick="openMerge(\'' + id + '\')">' + t('admin.merge_action', '⊕ Слить') + '</button>' +
    '</div>' +
    '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">' +
      '<span style="font-size:12px;color:var(--muted)">' + t('admin.status_label', 'Статус:') + '</span>' +
      '<div class="adm-status-btns">' +
        statusBtn(id, 'new',      cl.status, t('admin.status_new', '⬜ Новое')) +
        statusBtn(id, 'planned',  cl.status, t('admin.status_planned', '📋 В плане')) +
        statusBtn(id, 'done',     cl.status, t('admin.status_done', '✅ Готово')) +
        statusBtn(id, 'rejected', cl.status, t('admin.status_rejected', '❌ Отклонить')) +
      '</div>' +
      '<span style="font-size:12px;color:var(--muted);margin-left:auto">' + t('admin.weight_label', 'Вес:') + ' <b>' + cl.total_weight + '</b> | ' + t('admin.voters_label', 'Голосов:') + ' <b>' + cl.voters + '</b></span>' +
    '</div>' +
  '</div>' +
  '<div style="flex:1;overflow-y:auto;padding:12px 20px" id="fbList"><div style="text-align:center;color:var(--muted);padding:20px;font-size:13px">' + t('admin.loading_data', 'Загружаем…') + '</div></div>';

  detail.style.display = 'flex';
  detail.style.flexDirection = 'column';

  sbfAuth.fetch('/api/admin/cluster/' + encodeURIComponent(id), { headers: ah() })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var fbList = document.getElementById('fbList');
      if (!d.feedbacks || !d.feedbacks.length) {
        fbList.innerHTML = '<div class="adm-empty">' + t('admin.no_requests', 'Нет заявок') + '</div>';
        return;
      }
      fbList.innerHTML = d.feedbacks.map(function (fb) {
        return '<div class="adm-fb-card">' +
          '<div class="adm-fb-header">' +
            '<span class="adm-fb-kind">' + kindEmoji(fb.kind) + ' ' + (fb.kind || '') + '</span>' +
            '<span class="adm-fb-level">' + t('admin.level_short', 'Ур.') + ' ' + (fb.level_at_submit || 1) + '</span>' +
            '<span class="adm-fb-ts">' + fmtDate(fb.created_ts) + '</span>' +
          '</div>' +
          '<div class="adm-fb-comment">' + esc(fb.comment) + '</div>' +
          '<div class="adm-fb-url">📄 ' + esc(fb.page_url || '') + '</div>' +
          (fb.screenshot_path ? '<img class="adm-fb-screenshot" src="/' + esc(fb.screenshot_path) + '" onclick="openImg(this.src)" loading="lazy">' : '') +
          '<div class="adm-fb-actions">' +
            '<button class="adm-fb-split-btn" onclick="splitFeedback(\'' + fb.id + '\')">' + t('admin.split_action', '↗ Выделить в отдельный кластер') + '</button>' +
          '</div>' +
        '</div>';
      }).join('');
    })
    .catch(function () {});
}

function statusBtn(clusterId, status, current, label) {
  return '<button class="adm-status-btn' + (current === status ? ' active' : '') + '" ' +
    'onclick="setStatus(\'' + clusterId + '\',\'' + status + '\')">' + label + '</button>';
}

function setStatus(clusterId, status) {
  sbfAuth.fetch('/api/admin/cluster/' + encodeURIComponent(clusterId) + '/status', {
    method: 'POST',
    headers: ah({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ status: status }),
  })
  .then(function (r) { return r.json(); })
  .then(function (d) {
    if (d.ok) {
      var cl = _clusters.find(function (c) { return c.id === clusterId; });
      if (cl) cl.status = status;
      renderClusterList();
      loadClusterDetail(clusterId);
    }
  });
}

function splitFeedback(feedbackId) {
  if (!confirm(t('admin.split_confirm', 'Выделить эту заявку в отдельный кластер?'))) return;
  sbfAuth.fetch('/api/admin/feedback/' + encodeURIComponent(feedbackId) + '/split', {
    method: 'POST',
    headers: ah({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({}),
  })
  .then(function (r) { return r.json(); })
  .then(function (d) {
    if (d.ok) { loadClusters(); if (_selectedClusterId) loadClusterDetail(_selectedClusterId); }
  });
}

// ── Merge modal ────────────────────────────────────────────────────────────

var _mergeSourceId = null;

function openMerge(sourceId) {
  _mergeSourceId = sourceId;
  var sel = document.getElementById('mergeTarget');
  sel.innerHTML = _clusters
    .filter(function (c) { return c.id !== sourceId; })
    .map(function (c) {
      return '<option value="' + c.id + '">' + esc(c.title || t('admin.untitled', '(без названия)')) + ' (⚡' + c.total_weight + ')</option>';
    }).join('');
  document.getElementById('mergeModal').classList.add('open');
}

function closeMerge() {
  document.getElementById('mergeModal').classList.remove('open');
  _mergeSourceId = null;
}

function confirmMerge() {
  var targetId = document.getElementById('mergeTarget').value;
  if (!_mergeSourceId || !targetId) return;
  sbfAuth.fetch('/api/admin/clusters/merge', {
    method: 'POST',
    headers: ah({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ source_id: _mergeSourceId, target_id: targetId }),
  })
  .then(function (r) { return r.json(); })
  .then(function (d) {
    if (d.ok) { closeMerge(); _selectedClusterId = targetId; loadClusters(); loadClusterDetail(targetId); }
  });
}

// ── Rename modal ───────────────────────────────────────────────────────────

var _renameClusterId = null;

function openRename(clusterId, currentTitle) {
  _renameClusterId = clusterId;
  document.getElementById('renameTitleInput').value = currentTitle || '';
  document.getElementById('renameModal').classList.add('open');
  setTimeout(function () { document.getElementById('renameTitleInput').focus(); }, 60);
}

function closeRename() {
  document.getElementById('renameModal').classList.remove('open');
  _renameClusterId = null;
}

function confirmRename() {
  var title = document.getElementById('renameTitleInput').value.trim();
  if (!title || !_renameClusterId) return;
  sbfAuth.fetch('/api/admin/cluster/' + encodeURIComponent(_renameClusterId) + '/title', {
    method: 'POST',
    headers: ah({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ title: title }),
  })
  .then(function (r) { return r.json(); })
  .then(function (d) {
    if (d.ok) {
      var cl = _clusters.find(function (c) { return c.id === _renameClusterId; });
      if (cl) cl.title = title;
      closeRename();
      renderClusterList();
      if (_selectedClusterId === _renameClusterId) loadClusterDetail(_renameClusterId);
    }
  });
}

// ── Unassigned ─────────────────────────────────────────────────────────────

function loadUnassigned() {
  sbfAuth.fetch('/api/admin/feedback/unassigned', { headers: ah() })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      _unassigned = d.feedbacks || [];
      var badge = document.getElementById('unassignedCount');
      badge.textContent = _unassigned.length ? '(' + _unassigned.length + ')' : '';
      if (_currentTab === 'unassigned') renderUnassigned();
    })
    .catch(function () {});
}

function renderUnassigned() {
  var el = document.getElementById('unassignedList');
  _selectedUnassigned.clear();
  updateSelCount();
  if (!_unassigned.length) {
    el.innerHTML = '<div class="adm-empty">' + t('admin.no_unassigned', 'Нет незакреплённых заявок') + '</div>';
    document.getElementById('unassignedActions').style.display = 'none';
    return;
  }
  document.getElementById('unassignedActions').style.display = 'flex';
  el.innerHTML = _unassigned.map(function (fb) {
    return '<div class="adm-unassigned-row">' +
      '<input type="checkbox" value="' + fb.id + '" onchange="toggleUnassigned(this)">' +
      '<span class="adm-unassigned-txt">' + kindEmoji(fb.kind) + ' ' + esc(fb.comment) + '</span>' +
      '<span style="font-size:10px;color:var(--muted);flex-shrink:0">' + fmtDate(fb.created_ts) + '</span>' +
    '</div>';
  }).join('');
}

function toggleUnassigned(cb) {
  if (cb.checked) _selectedUnassigned.add(cb.value);
  else _selectedUnassigned.delete(cb.value);
  updateSelCount();
}

function updateSelCount() {
  var el = document.getElementById('selCount');
  el.textContent = _selectedUnassigned.size ? t('admin.selected_prefix', 'Выбрано: ') + _selectedUnassigned.size : '';
}

function groupSelected() {
  if (_selectedUnassigned.size < 1) return;
  document.getElementById('groupTitleInput').value = '';
  document.getElementById('groupModal').classList.add('open');
  setTimeout(function () { document.getElementById('groupTitleInput').focus(); }, 60);
}

function closeGroup() {
  document.getElementById('groupModal').classList.remove('open');
}

function confirmGroup() {
  var title = document.getElementById('groupTitleInput').value.trim();
  closeGroup();
  sbfAuth.fetch('/api/admin/clusters/create', {
    method: 'POST',
    headers: ah({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ feedback_ids: Array.from(_selectedUnassigned), title: title }),
  })
  .then(function (r) { return r.json(); })
  .then(function (d) {
    if (d.ok) { loadClusters(); loadUnassigned(); }
  });
}

// ── Filters ────────────────────────────────────────────────────────────────

document.getElementById('filterBar').addEventListener('click', function (e) {
  var chip = e.target.closest('.adm-filter-chip');
  if (!chip) return;
  document.querySelectorAll('.adm-filter-chip').forEach(function (c) {
    c.classList.toggle('active', c === chip);
  });
  _filterStatus = chip.dataset.status || '';
  loadClusters();
});

// ── Copy texts ─────────────────────────────────────────────────────────────

function loadCopyList() {
  sbfAuth.fetch('/api/copy/all', { headers: ah() })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var el = document.getElementById('copyList');
      var items = d.items || [];
      if (!items.length) {
        el.innerHTML = '<div class="adm-empty">' + t('admin.no_copy_texts', 'Нет текстов с data-copy-id') + '</div>';
        return;
      }
      el.innerHTML = items.map(function (item) {
        return '<div style="background:var(--cream);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin-bottom:8px">' +
          '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">' +
            '<code style="font-size:11px;color:var(--gold)">' + esc(item.copy_id) + '</code>' +
            '<span style="font-size:11px;color:var(--muted)">' + esc(item.page || '') + '</span>' +
            '<button class="adm-fb-split-btn" style="margin-left:auto" onclick="resetCopy(\'' + escQ(item.copy_id) + '\')">' + t('admin.reset_default', '↩ По умолчанию') + '</button>' +
          '</div>' +
          '<div contenteditable="true" data-copy-id-adm="' + escQ(item.copy_id) + '" ' +
            'style="font-size:13px;padding:8px;border:1px solid var(--line);border-radius:6px;outline:none;min-height:2em" ' +
            'onblur="saveCopyFromAdmin(this)">' +
            esc(item.text_current) +
          '</div>' +
        '</div>';
      }).join('');
    })
    .catch(function () {});
}

function saveCopyFromAdmin(el) {
  var copyId = el.dataset.copyIdAdm;
  if (!copyId) return;
  sbfAuth.fetch('/api/copy/' + encodeURIComponent(copyId), {
    method: 'POST',
    headers: ah({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ text: el.textContent, page: '' }),
  }).then(function (r) { return r.json(); }).then(function (d) {
    el.style.borderColor = d.ok ? '#16a34a' : '#dc2626';
    setTimeout(function () { el.style.borderColor = ''; }, 1000);
  });
}

function resetCopy(copyId) {
  sbfAuth.fetch('/api/copy/' + encodeURIComponent(copyId) + '/reset', {
    method: 'POST',
    headers: ah({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({}),
  })
  .then(function (r) { return r.json(); })
  .then(function (d) { if (d.ok) loadCopyList(); });
}

// ── Image lightbox ─────────────────────────────────────────────────────────

function openImg(src) {
  document.getElementById('imgModalSrc').src = src;
  document.getElementById('imgModal').classList.add('open');
}

// ── Helpers ────────────────────────────────────────────────────────────────

function esc(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function escQ(s) {
  return String(s || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

function fmtDate(ts) {
  if (!ts) return '';
  var _lg = window.sbfI18n && window.sbfI18n.lang;
  var locale = _lg === 'ro' ? 'ro-RO' : _lg === 'en' ? 'en-US' : 'ru-RU';
  try { return new Date(ts.replace(' ', 'T') + 'Z').toLocaleDateString(locale); } catch (e) { return ts; }
}

function kindEmoji(kind) {
  return kind === 'bug' ? '🐛' : kind === 'idea' ? '💡' : '💬';
}

// ── Init ───────────────────────────────────────────────────────────────────

// Enter key in login
document.getElementById('loginPwd').addEventListener('keydown', function (e) {
  if (e.key === 'Enter') doLogin();
});

// Logout
// NB: this file is a plain (non-defer) <script> at the bottom of <body>, so it
// runs BEFORE the deferred /assets/i18n.js in <head> has executed — t() below
// will resolve to the Russian fallback regardless of language. data-i18n is
// set too so the later _patchI18n(document) pass (once the dict is ready)
// fixes it for ro.
(function () {
  var logoutBtn = document.createElement('button');
  logoutBtn.className = 'adm-logout';
  logoutBtn.setAttribute('data-i18n', 'admin.logout_button');
  logoutBtn.textContent = t('admin.logout_button', 'Выйти');
  logoutBtn.onclick = function () {
    sbfAuth.clear();
    localStorage.removeItem('sbf_uid');
    location.reload();
  };
  document.getElementById('sideUserName').after(logoutBtn);
})();

// Patch statically-rendered [data-i18n] nodes once the dictionary is loaded
// (login gate markup exists before login, so this can run right away).
window.sbfI18n
  ? window.sbfI18n.ready.then(function () { _patchI18n(document); })
  : document.addEventListener('DOMContentLoaded', function () {
      if (window.sbfI18n) window.sbfI18n.ready.then(function () { _patchI18n(document); });
    });

// Auto-check on load
checkAdmin();
