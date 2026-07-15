/* SBF Journal — Web Push регистрация (§0.3) */
(function () {
  'use strict';

  // ── i18n (см. assets/i18n.js, паттерн — sbf-profile.js) ─────────────────────
  function t(key, fallback) {
    return (window.sbfI18n && window.sbfI18n.t) ? window.sbfI18n.t(key, fallback) : (fallback || key);
  }

  var _swReg = null;
  var _pushSub = null;

  // ── Публичный API ────────────────────────────────────────────────────────────
  window.SBFPush = {
    init:        init,
    subscribe:   subscribe,
    unsubscribe: unsubscribe,
    getStatus:   getStatus,
  };

  function init() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      _updatePushUI('unsupported');
      return;
    }
    navigator.serviceWorker.register('/sw.js', { scope: '/' })
      .then(function (reg) {
        _swReg = reg;
        return reg.pushManager.getSubscription();
      })
      .then(function (sub) {
        _pushSub = sub;
        _updatePushUI(sub ? 'subscribed' : 'unsubscribed');
      })
      .catch(function (err) {
        console.warn('[SBFPush] SW registration failed:', err);
        _updatePushUI('error');
      });
  }

  function getStatus() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) return 'unsupported';
    if (_pushSub) return 'subscribed';
    return 'unsubscribed';
  }

  function subscribe() {
    if (!_swReg) { alert(t('push.sw_not_ready', 'Service Worker ещё не готов, попробуй снова через секунду.')); return; }
    _requestPermissionAndSubscribe();
  }

  function unsubscribe() {
    if (!_pushSub) return;
    _pushSub.unsubscribe()
      .then(function (ok) {
        if (ok) {
          _pushSub = null;
          _updatePushUI('unsubscribed');
          _showMsg(t('push.unsubscribed_toast', 'Пуш-уведомления отключены.'));
        }
      })
      .catch(function (e) { console.error('[SBFPush] unsubscribe error', e); });
  }

  // ── Внутреннее ───────────────────────────────────────────────────────────────

  function _requestPermissionAndSubscribe() {
    Notification.requestPermission().then(function (perm) {
      if (perm !== 'granted') {
        _showMsg(t('push.permission_denied', 'Разрешение на уведомления не получено. Включи его в настройках браузера.'));
        return;
      }
      // Получаем VAPID applicationServerKey с сервера
      fetch('/api/push/vapid-key')
        .then(function (r) { return r.json(); })
        .then(function (d) {
          var appKey = d.applicationServerKey;
          if (!appKey) throw new Error('no vapid key');
          return _swReg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: _urlBase64ToUint8Array(appKey),
          });
        })
        .then(function (sub) {
          _pushSub = sub;
          // Отправляем subscription на сервер
          return fetch('/api/push/subscribe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              subscription: sub.toJSON(),
              timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
            }),
          });
        })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (res && res.ok) {
            _updatePushUI('subscribed');
            _showMsg(t('push.subscribed_toast', '🔔 Пуш-уведомления включены!'));
          } else {
            throw new Error((res && res.error) || 'server error');
          }
        })
        .catch(function (err) {
          console.error('[SBFPush] subscribe error:', err);
          _showMsg(t('push.subscribe_error_prefix', 'Ошибка подписки: ') + err.message);
          _updatePushUI('error');
        });
    });
  }

  // Конвертация base64url → Uint8Array (стандартный хелпер для VAPID)
  function _urlBase64ToUint8Array(base64String) {
    var padding = '='.repeat((4 - base64String.length % 4) % 4);
    var base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    var raw = atob(base64);
    var arr = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
    return arr;
  }

  function _updatePushUI(status) {
    var btn = document.getElementById('jPushToggleBtn');
    var info = document.getElementById('jPushStatusInfo');
    if (!btn) return;
    if (status === 'unsupported') {
      btn.textContent = t('push.btn_unsupported', '🔕 Пуши не поддерживаются');
      btn.disabled = true;
      if (info) info.textContent = t('push.info_unsupported', 'Браузер не поддерживает Web Push.');
    } else if (status === 'subscribed') {
      btn.textContent = t('push.btn_subscribed', '🔔 Пуши включены');
      btn.className = btn.className.replace('j-btn-sec', 'j-btn');
      btn.onclick = unsubscribe;
      if (info) info.textContent = t('push.info_subscribed', 'Уведомления активны. Нажми, чтобы отключить.');
    } else if (status === 'error') {
      btn.textContent = t('push.btn_error', '⚠ Ошибка пушей');
      btn.disabled = false;
      btn.onclick = subscribe;
      if (info) info.textContent = t('push.info_error', 'Попробуй снова или проверь настройки браузера.');
    } else {
      btn.textContent = t('push.btn_default', '🔕 Включить пуши');
      btn.className = btn.className.replace(/\bj-btn\b/, 'j-btn-sec') || btn.className;
      btn.onclick = subscribe;
      if (info) info.textContent = t('push.info_default', 'Получай алерты даже когда вкладка закрыта.');
    }
  }

  function _showMsg(text) {
    // Используем тост если доступен
    if (window.SBFJournal && window.SBFJournal._showXpToast) {
      window.SBFJournal._showXpToast(0, text);
      return;
    }
    var el = document.createElement('div');
    el.textContent = text;
    el.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);' +
      'background:#333;color:#fff;padding:10px 18px;border-radius:8px;font-size:13px;z-index:9999';
    document.body.appendChild(el);
    setTimeout(function () { el.remove(); }, 3500);
  }

  // Авто-инициализация после загрузки DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
